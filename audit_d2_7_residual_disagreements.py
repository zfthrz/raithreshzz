#!/usr/bin/env python3
"""D2.7 — Residual disagreement analysis (offline, read-only).

Explica por qué el ranker LLM y el candidato determinista combinado
(D2.1 order + D2.3 priority cut + D2.4 NO_ACCIONABLE cut) divergen en cada
comparison. NO cambia producción, NO ajusta thresholds y NO entrena nada.

Para cada comparison reconstruye:
  1. respuesta LLM (ordered_episode_ids, priority_cut_rank,
     no_actionable_start_rank);
  2. baseline determinista D2.1 (deterministic_shadow.response);
  3. candidato combinado (D2.1 + D2.3 + D2.4);
  4. una fila compacta por episodio con TODOS los facts deterministas que el
     LLM ranker ve (compact_episode_for_priority_ranking + relativos) y los
     facts de pista disponibles en episode_ground_truth;
  5. análisis explícito de ORDER (pares invertidos + diferencias relativas),
     PRIORITY CUT (boundaries + cumulative coverage + adjacent loss ratio) y
     NO_ACCIONABLE (tail + shares + boundaries);
  6. patrón determinista por disagreement o UNRESOLVED si no hay evidencia
     suficiente.
"""

from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from audit_d2_3_priority_cut import calibrated_priority_cut_rank
from audit_d2_4_no_actionable import (
    EpisodeFacts,
    calibrated_no_actionable_start_rank,
)


DEFAULT_PRIORITY_COVERAGE_TARGET = 0.55
DEFAULT_WEAK_SHARE_MAX = 0.05
DEFAULT_MODERATE_SHARE_MAX = 0.04
DEFAULT_STRONG_SHARE_MAX = 0.01

ORDER_PATTERN_MULTI_CHANNEL = "LLM_PROMOTES_MULTI_CHANNEL_OVER_HIGHER_LOSS_SINGLE_CHANNEL"
ORDER_PATTERN_STRONG_EVIDENCE = "LLM_PROMOTES_STRONG_EVIDENCE_OVER_HIGHER_LOSS"
ORDER_PATTERN_PARENT_ZONE = "LLM_PRIORITIZES_PARENT_ZONE_CONTRIBUTION"
ORDER_PATTERN_SPEED_CONTEXT = "LLM_PROMOTES_SPEED_CONTEXT_EPISODE"
CUT_PATTERN_COVERAGE = "LLM_CUT_DIFFERS_IN_CUMULATIVE_COVERAGE"
CUT_PATTERN_LOSS_GAP = "LLM_CUTS_AT_LARGE_RELATIVE_LOSS_GAP"
CUT_PATTERN_LOW_SHARE = "LLM_KEEPS_LOW_SHARE_EPISODE_PRIORITARY"
NA_PATTERN_TINY_LOSS = "LLM_KEEPS_MODERATE_EPISODE_ACTIONABLE_DESPITE_TINY_LOSS"
NA_PATTERN_NONTRIVIAL_TAIL = "LLM_CUTS_TAIL_WITH_NONTRIVIAL_SHARE"
UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ComparisonSample:
    source_path: Path
    track: str
    comparison: str
    llm_order: tuple[int, ...]
    llm_priority_cut_rank: int
    llm_no_actionable_start_rank: int
    baseline_order: tuple[int, ...]
    baseline_priority_cut_rank: int
    baseline_no_actionable_start_rank: int
    episodes_by_id: dict[int, dict[str, Any]]


def _safe_nonnegative_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result != result or result in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, result)


def _finite_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _evidence_key(episode: dict[str, Any]) -> str:
    return str(episode.get("evidence_strength") or "").strip().lower()


def episode_has_speed_context(episode: dict[str, Any]) -> bool:
    return bool(episode.get("concurrent_speed_events")) or bool(
        episode.get("speed_propagation")
    )


def relative_metrics(episodes: Iterable[dict[str, Any]]) -> dict[int, dict[str, float | None]]:
    """Replica _priority_relative_metrics del ranker (mismo contrato)."""
    episodes = list(episodes)
    losses = [
        max(_safe_nonnegative_float(episode.get("action_time_loss_s")), 0.0)
        for episode in episodes
    ]
    max_loss = max(losses) if losses else 0.0
    total_loss = sum(losses)
    metrics: dict[int, dict[str, float | None]] = {}
    for episode, loss in zip(episodes, losses):
        episode_id = episode.get("episode_id")
        if not isinstance(episode_id, int):
            continue
        metrics[episode_id] = {
            "action_loss_vs_max": (
                loss / max_loss if max_loss > 0.0 else None
            ),
            "action_loss_share_of_total": (
                loss / total_loss if total_loss > 0.0 else None
            ),
        }
    return metrics


def load_samples(paths: Iterable[str | Path]) -> list[ComparisonSample]:
    samples: list[ComparisonSample] = []
    for raw_path in paths:
        path = Path(raw_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        track = str((payload.get("metadata") or {}).get("track") or path.stem)
        for comparison in payload.get("comparisons") or []:
            if not isinstance(comparison, dict):
                continue
            audit = comparison.get("llm_validation_audit") or {}
            ranking = audit.get("priority_ranking") or {}
            shadow = ranking.get("deterministic_shadow") or {}
            if shadow.get("status") != "VALID":
                continue
            baseline = shadow.get("response") or {}
            llm_order = ranking.get("ordered_episode_ids")
            llm_priority = ranking.get("priority_cut_rank")
            llm_no_actionable = ranking.get("no_actionable_start_rank")
            baseline_order = baseline.get("ordered_episode_ids")
            baseline_priority = baseline.get("priority_cut_rank")
            baseline_no_actionable = baseline.get("no_actionable_start_rank")
            if not (
                isinstance(llm_order, list)
                and isinstance(llm_priority, int)
                and isinstance(llm_no_actionable, int)
                and isinstance(baseline_order, list)
                and isinstance(baseline_priority, int)
                and isinstance(baseline_no_actionable, int)
            ):
                continue
            episodes_by_id: dict[int, dict[str, Any]] = {}
            for episode in comparison.get("episode_ground_truth") or []:
                if not isinstance(episode, dict):
                    continue
                episode_id = episode.get("episode_id")
                if isinstance(episode_id, int):
                    episodes_by_id[episode_id] = episode
            if set(baseline_order) != set(episodes_by_id):
                continue
            samples.append(
                ComparisonSample(
                    source_path=path,
                    track=track,
                    comparison=(
                        f"{comparison.get('reference_lap')}->"
                        f"{comparison.get('comparison_lap')}"
                    ),
                    llm_order=tuple(int(value) for value in llm_order),
                    llm_priority_cut_rank=llm_priority,
                    llm_no_actionable_start_rank=llm_no_actionable,
                    baseline_order=tuple(int(value) for value in baseline_order),
                    baseline_priority_cut_rank=baseline_priority,
                    baseline_no_actionable_start_rank=baseline_no_actionable,
                    episodes_by_id=episodes_by_id,
                )
            )
    return samples


def build_combined_candidate(sample: ComparisonSample) -> dict[str, Any]:
    losses = {
        episode_id: _safe_nonnegative_float(episode.get("action_time_loss_s"))
        for episode_id, episode in sample.episodes_by_id.items()
    }
    facts = {
        episode_id: EpisodeFacts(
            episode_id=episode_id,
            loss=losses[episode_id],
            evidence_strength=_evidence_key(episode),
        )
        for episode_id, episode in sample.episodes_by_id.items()
    }
    priority_cut = calibrated_priority_cut_rank(
        sample.baseline_order,
        losses,
        coverage_target=DEFAULT_PRIORITY_COVERAGE_TARGET,
    )
    no_actionable_start = calibrated_no_actionable_start_rank(
        sample.baseline_order,
        facts,
        priority_cut_rank=priority_cut,
        weak_share_max=DEFAULT_WEAK_SHARE_MAX,
        moderate_share_max=DEFAULT_MODERATE_SHARE_MAX,
        strong_share_max=DEFAULT_STRONG_SHARE_MAX,
    )
    return {
        "ordered_episode_ids": list(sample.baseline_order),
        "priority_cut_rank": priority_cut,
        "no_actionable_start_rank": no_actionable_start,
    }


def episode_row(
    episode_id: int,
    sample: ComparisonSample,
    relative: dict[int, dict[str, float | None]],
) -> dict[str, Any]:
    episode = sample.episodes_by_id.get(episode_id, {})
    rel = relative.get(episode_id, {})
    return {
        "episode_id": episode_id,
        "objective_rank": (
            episode.get("global_rank")
            or episode.get("rank")
            or episode_id
        ),
        "global_rank": episode.get("global_rank"),
        "action_time_loss_s": _safe_nonnegative_float(
            episode.get("action_time_loss_s")
        ),
        "action_loss_vs_max": rel.get("action_loss_vs_max"),
        "action_loss_share_of_total": rel.get("action_loss_share_of_total"),
        "evidence_strength": _evidence_key(episode),
        "action_channel_count": episode.get("action_channel_count"),
        "action_channels": list(episode.get("action_channels", []) or []),
        "length_m": episode.get("length_m"),
        "parent_zone_rank": episode.get("parent_zone_rank"),
        "parent_zone_delta_loss_s": episode.get("parent_zone_delta_loss_s"),
        "parent_zone_net_loss_equivalent_percent": episode.get(
            "parent_zone_net_loss_equivalent_percent"
        ),
        "zone_id": episode.get("zone_id"),
        "start_distance_m": episode.get("start_distance_m"),
        "end_distance_m": episode.get("end_distance_m"),
        "speed_context_available": episode_has_speed_context(episode),
    }


def cumulative_coverage(
    order: Iterable[int],
    losses: dict[int, float],
) -> list[dict[str, Any]]:
    ordered = tuple(int(value) for value in order)
    total = sum(losses.get(episode_id, 0.0) for episode_id in ordered)
    cumulative = 0.0
    rows = []
    for rank, episode_id in enumerate(ordered, start=1):
        loss = losses.get(episode_id, 0.0)
        cumulative += loss
        rows.append(
            {
                "rank": rank,
                "episode_id": episode_id,
                "loss_s": loss,
                "share": (loss / total if total > 0.0 else 0.0),
                "cumulative_loss_s": cumulative,
                "coverage": (cumulative / total if total > 0.0 else 0.0),
            }
        )
    return rows


def adjacent_loss_ratio(
    cut_rank: int,
    order: Iterable[int],
    losses: dict[int, float],
) -> float | None:
    ordered = tuple(int(value) for value in order)
    if not 1 <= cut_rank < len(ordered):
        return None
    lower = losses.get(ordered[cut_rank - 1], 0.0)
    upper = losses.get(ordered[cut_rank], 0.0)
    if lower <= 0.0:
        return None
    return upper / lower


def boundary_episodes(
    order: Iterable[int],
    cut_rank: int,
) -> dict[str, Any]:
    ordered = tuple(int(value) for value in order)
    before = ordered[cut_rank - 1] if 1 <= cut_rank <= len(ordered) else None
    after = ordered[cut_rank] if 0 <= cut_rank < len(ordered) else None
    return {"before": before, "after": after}


def pair_inversions(
    a_order: Iterable[int],
    b_order: Iterable[int],
) -> list[tuple[int, int]]:
    a = tuple(int(value) for value in a_order)
    b = tuple(int(value) for value in b_order)
    a_index = {episode_id: rank for rank, episode_id in enumerate(a)}
    b_index = {episode_id: rank for rank, episode_id in enumerate(b)}
    inversions: list[tuple[int, int]] = []
    for index, first in enumerate(a):
        for second in a[index + 1 :]:
            if b_index.get(first, -1) > b_index.get(second, -1):
                inversions.append((first, second))
    return inversions


def _row_for(sample: ComparisonSample, relative: dict[int, dict[str, float | None]], episode_id: int) -> dict[str, Any]:
    return episode_row(episode_id, sample, relative)


def analyze_order(
    sample: ComparisonSample,
    candidate_order: tuple[int, ...],
    relative: dict[int, dict[str, float | None]],
) -> dict[str, Any]:
    inversions = pair_inversions(candidate_order, sample.llm_order)
    details = []
    for first, second in inversions:
        first_row = _row_for(sample, relative, first)
        second_row = _row_for(sample, relative, second)
        details.append(
            {
                "llm_before": first,
                "llm_after": second,
                "candidate_order": [second, first],
                "loss_first": first_row["action_time_loss_s"],
                "loss_second": second_row["action_time_loss_s"],
                "loss_ratio_first_over_second": (
                    first_row["action_time_loss_s"]
                    / second_row["action_time_loss_s"]
                    if second_row["action_time_loss_s"] > 0.0
                    else None
                ),
                "share_first": first_row["action_loss_share_of_total"],
                "share_second": second_row["action_loss_share_of_total"],
                "evidence_first": first_row["evidence_strength"],
                "evidence_second": second_row["evidence_strength"],
                "channels_first": first_row["action_channels"],
                "channels_second": second_row["action_channels"],
                "channel_count_first": first_row["action_channel_count"],
                "channel_count_second": second_row["action_channel_count"],
                "length_first": first_row["length_m"],
                "length_second": second_row["length_m"],
                "parent_zone_delta_first": first_row["parent_zone_delta_loss_s"],
                "parent_zone_delta_second": second_row["parent_zone_delta_loss_s"],
                "vs_max_first": first_row["action_loss_vs_max"],
                "vs_max_second": second_row["action_loss_vs_max"],
                "speed_context_first": first_row["speed_context_available"],
                "speed_context_second": second_row["speed_context_available"],
            }
        )
    return {"inversion_count": len(inversions), "inversions": details}


def analyze_priority_cut(
    sample: ComparisonSample,
    candidate: dict[str, Any],
    losses: dict[int, float],
) -> dict[str, Any]:
    llm_cut = sample.llm_priority_cut_rank
    candidate_cut = int(candidate["priority_cut_rank"])
    llm_coverage = cumulative_coverage(sample.llm_order, losses)
    candidate_coverage = cumulative_coverage(candidate["ordered_episode_ids"], losses)
    return {
        "llm_cut_rank": llm_cut,
        "candidate_cut_rank": candidate_cut,
        "llm_boundary": boundary_episodes(sample.llm_order, llm_cut),
        "candidate_boundary": boundary_episodes(
            candidate["ordered_episode_ids"], candidate_cut
        ),
        "llm_cumulative_coverage": llm_coverage,
        "candidate_cumulative_coverage": candidate_coverage,
        "llm_cut_coverage": (
            llm_coverage[llm_cut - 1]["coverage"]
            if 1 <= llm_cut <= len(llm_coverage)
            else None
        ),
        "candidate_cut_coverage": (
            candidate_coverage[candidate_cut - 1]["coverage"]
            if 1 <= candidate_cut <= len(candidate_coverage)
            else None
        ),
        "llm_adjacent_loss_ratio": adjacent_loss_ratio(
            llm_cut, sample.llm_order, losses
        ),
        "candidate_adjacent_loss_ratio": adjacent_loss_ratio(
            candidate_cut, candidate["ordered_episode_ids"], losses
        ),
    }


def analyze_no_actionable(
    sample: ComparisonSample,
    candidate: dict[str, Any],
    relative: dict[int, dict[str, float | None]],
) -> dict[str, Any]:
    llm_start = sample.llm_no_actionable_start_rank
    candidate_start = int(candidate["no_actionable_start_rank"])
    ordered = list(candidate["ordered_episode_ids"])
    tail_from = min(llm_start, candidate_start)
    tail_episodes = ordered[tail_from - 1 :] if tail_from >= 1 else []
    tail_rows = []
    cumulative_tail_share = 0.0
    for episode_id in tail_episodes:
        row = _row_for(sample, relative, episode_id)
        share = row["action_loss_share_of_total"] or 0.0
        cumulative_tail_share += share
        tail_rows.append(
            {
                "episode_id": episode_id,
                "loss_share": share,
                "evidence_strength": row["evidence_strength"],
                "action_channels": row["action_channels"],
            }
        )
    return {
        "llm_no_actionable_start_rank": llm_start,
        "candidate_no_actionable_start_rank": candidate_start,
        "boundary_difference": llm_start - candidate_start,
        "tail_episodes": tail_rows,
        "cumulative_tail_share": cumulative_tail_share,
    }


def _order_pattern(
    sample: ComparisonSample,
    candidate_order: tuple[int, ...],
    relative: dict[int, dict[str, float | None]],
) -> str:
    inversions = pair_inversions(candidate_order, sample.llm_order)
    if not inversions:
        return UNRESOLVED
    for first, second in inversions:
        # El par (first, second) significa: en orden candidato first va antes de
        # second, pero el LLM promueve second por delante de first.
        promoted_row = _row_for(sample, relative, second)
        demoted_row = _row_for(sample, relative, first)
        promoted_channels = int(promoted_row["action_channel_count"] or 0)
        demoted_channels = int(demoted_row["action_channel_count"] or 0)
        promoted_loss = promoted_row["action_time_loss_s"]
        demoted_loss = demoted_row["action_time_loss_s"]
        promoted_evidence = promoted_row["evidence_strength"]
        demoted_evidence = demoted_row["evidence_strength"]
        if (
            promoted_channels > 1
            and demoted_channels == 1
            and promoted_loss < demoted_loss
            and (demoted_loss - promoted_loss) / max(demoted_loss, 1e-9) < 0.25
        ):
            return ORDER_PATTERN_MULTI_CHANNEL
        if (
            promoted_evidence == "strong"
            and demoted_evidence in ("weak", "moderate")
            and promoted_loss < demoted_loss * 1.2
        ):
            return ORDER_PATTERN_STRONG_EVIDENCE
        promoted_zone = _finite_number(promoted_row["parent_zone_delta_loss_s"]) or 0.0
        demoted_zone = _finite_number(demoted_row["parent_zone_delta_loss_s"]) or 0.0
        if promoted_zone > demoted_zone * 1.5 and promoted_zone > 0.0:
            return ORDER_PATTERN_PARENT_ZONE
        if promoted_row["speed_context_available"] and not demoted_row["speed_context_available"]:
            return ORDER_PATTERN_SPEED_CONTEXT
    return UNRESOLVED


def _priority_cut_pattern(
    sample: ComparisonSample,
    candidate: dict[str, Any],
    losses: dict[int, float],
) -> str:
    llm_cut = sample.llm_priority_cut_rank
    candidate_cut = int(candidate["priority_cut_rank"])
    llm_coverage = cumulative_coverage(sample.llm_order, losses)
    llm_cut_coverage = (
        llm_coverage[llm_cut - 1]["coverage"]
        if 1 <= llm_cut <= len(llm_coverage)
        else None
    )
    candidate_cut_coverage = (
        llm_coverage[candidate_cut - 1]["coverage"]
        if 1 <= candidate_cut <= len(llm_coverage)
        else None
    )
    if (
        llm_cut_coverage is not None
        and candidate_cut_coverage is not None
        and abs(llm_cut_coverage - candidate_cut_coverage) > 0.15
    ):
        return CUT_PATTERN_COVERAGE
    ratio = adjacent_loss_ratio(llm_cut, sample.llm_order, losses)
    if ratio is not None and ratio > 2.0:
        return CUT_PATTERN_LOSS_GAP
    before = (
        sample.llm_order[llm_cut - 1] if 1 <= llm_cut <= len(sample.llm_order) else None
    )
    if before is not None:
        row = _row_for(sample, relative_metrics(sample.episodes_by_id.values()), before)
        if (
            llm_cut > candidate_cut
            and (row["action_loss_share_of_total"] or 1.0) < 0.06
            and row["evidence_strength"] in ("weak", "moderate")
        ):
            return CUT_PATTERN_LOW_SHARE
    return UNRESOLVED


def _no_actionable_pattern(
    sample: ComparisonSample,
    candidate: dict[str, Any],
    relative: dict[int, dict[str, float | None]],
) -> str:
    llm_start = sample.llm_no_actionable_start_rank
    candidate_start = int(candidate["no_actionable_start_rank"])
    ordered = list(candidate["ordered_episode_ids"])
    if llm_start > candidate_start:
        between = ordered[candidate_start - 1 : llm_start - 1]
        for episode_id in between:
            row = _row_for(sample, relative, episode_id)
            if (
                (row["action_loss_share_of_total"] or 1.0) < 0.05
                and row["evidence_strength"] in ("moderate", "strong")
            ):
                return NA_PATTERN_TINY_LOSS
        return UNRESOLVED
    if llm_start < candidate_start:
        tail_from_llm = ordered[llm_start - 1 :]
        max_share = max(
            (
                _row_for(sample, relative, episode_id)["action_loss_share_of_total"]
                or 0.0
            )
            for episode_id in tail_from_llm
        )
        if max_share > 0.05:
            return NA_PATTERN_NONTRIVIAL_TAIL
    return UNRESOLVED


def analyze_comparison(sample: ComparisonSample) -> dict[str, Any]:
    candidate = build_combined_candidate(sample)
    relative = relative_metrics(sample.episodes_by_id.values())
    losses = {
        episode_id: _safe_nonnegative_float(episode.get("action_time_loss_s"))
        for episode_id, episode in sample.episodes_by_id.items()
    }
    candidate_order = tuple(int(value) for value in candidate["ordered_episode_ids"])

    disagreements: list[str] = []
    if candidate_order != sample.llm_order:
        disagreements.append("order")
    if int(candidate["priority_cut_rank"]) != sample.llm_priority_cut_rank:
        disagreements.append("priority_cut")
    if int(candidate["no_actionable_start_rank"]) != sample.llm_no_actionable_start_rank:
        disagreements.append("no_actionable_cut")

    patterns: dict[str, str] = {}
    if "order" in disagreements:
        patterns["order"] = _order_pattern(sample, candidate_order, relative)
    if "priority_cut" in disagreements:
        patterns["priority_cut"] = _priority_cut_pattern(sample, candidate, losses)
    if "no_actionable_cut" in disagreements:
        patterns["no_actionable_cut"] = _no_actionable_pattern(
            sample, candidate, relative
        )

    return {
        "track": sample.track,
        "comparison": sample.comparison,
        "source_path": str(sample.source_path),
        "disagreements": disagreements,
        "llm": {
            "ordered_episode_ids": list(sample.llm_order),
            "priority_cut_rank": sample.llm_priority_cut_rank,
            "no_actionable_start_rank": sample.llm_no_actionable_start_rank,
        },
        "baseline": {
            "ordered_episode_ids": list(sample.baseline_order),
            "priority_cut_rank": sample.baseline_priority_cut_rank,
            "no_actionable_start_rank": sample.baseline_no_actionable_start_rank,
        },
        "candidate": candidate,
        "episodes": [
            episode_row(episode_id, sample, relative)
            for episode_id in sample.baseline_order
        ],
        "order_analysis": analyze_order(sample, candidate_order, relative),
        "priority_cut_analysis": analyze_priority_cut(sample, candidate, losses),
        "no_actionable_analysis": analyze_no_actionable(sample, candidate, relative),
        "patterns": patterns,
    }


def aggregate(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    results = list(results)
    counts = {
        "comparison_count": len(results),
        "disagreement_count": 0,
        "order_disagreement_count": 0,
        "priority_cut_disagreement_count": 0,
        "no_actionable_disagreement_count": 0,
    }
    pattern_counter: dict[str, int] = {}
    unresolved: dict[str, int] = {}
    for result in results:
        disagreements = result["disagreements"]
        if disagreements:
            counts["disagreement_count"] += 1
        counts["order_disagreement_count"] += int("order" in disagreements)
        counts["priority_cut_disagreement_count"] += int("priority_cut" in disagreements)
        counts["no_actionable_disagreement_count"] += int(
            "no_actionable_cut" in disagreements
        )
        for kind, pattern in result["patterns"].items():
            key = f"{kind}:{pattern}"
            if pattern == UNRESOLVED:
                unresolved[key] = unresolved.get(key, 0) + 1
            else:
                pattern_counter[key] = pattern_counter.get(key, 0) + 1
    return {
        **counts,
        "patterns": dict(sorted(pattern_counter.items(), key=lambda item: -item[1])),
        "unresolved": dict(sorted(unresolved.items(), key=lambda item: -item[1])),
        "results": results,
    }


def _expand_inputs(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        matches = glob.glob(value)
        if matches:
            result.extend(matches)
        elif Path(value).is_file():
            result.append(value)
    return sorted(set(result))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="D2.7 residual disagreement analysis (offline, read-only)."
    )
    parser.add_argument("inputs", nargs="+", help="JSON files or glob patterns.")
    parser.add_argument("--json-output", type=Path, default=None)
    args = parser.parse_args()

    samples = load_samples(_expand_inputs(args.inputs))
    if not samples:
        raise SystemExit("No se encontraron comparisons con deterministic_shadow VALID.")
    report = aggregate(analyze_comparison(sample) for sample in samples)

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Output: {args.json_output.resolve()}")

    print("=" * 88)
    print("D2.7 RESIDUAL DISAGREEMENT ANALYSIS")
    print("=" * 88)
    print(
        f"Comparisons: {report['comparison_count']} · "
        f"Disagreements: {report['disagreement_count']} · "
        f"order={report['order_disagreement_count']} · "
        f"priority_cut={report['priority_cut_disagreement_count']} · "
        f"no_actionable={report['no_actionable_disagreement_count']}"
    )
    for result in report["results"]:
        if result["disagreements"]:
            print(
                f"  {result['track']} {result['comparison']}: "
                f"{', '.join(result['disagreements'])} :: "
                f"{result['patterns']}"
            )
    print("Patterns:", report["patterns"])
    print("Unresolved:", report["unresolved"])
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
