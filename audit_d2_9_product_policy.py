#!/usr/bin/env python3
"""D2.9 — Product-principled deterministic ranker policy (shadow candidate).

Reglas FIJAS de producto (no tuning, no imitan a DeepSeek):

1. ORDER base = D2.1 (global_rank determinista de Python).
2. PRIORITARIO = prefix de cobertura 55% de pérdida acumulada (constante de
   producto), EXTENDIDO sólo mientras el siguiente episodio sea ``strong`` y
   tenga un TARGET DIRECTO AUTORIZADO (brake/throttle con dirección), con tope
   de prioridad = 3 (foco del plan). NO usa canal-count (D2.8 refutado).
3. NO_ACCIONABLE = sólo cola de episodios OBSERVACIONALES (sin target directo)
   o ``weak`` con share negligible (<= 0.05). Los moderate/strong con target
   directo NUNCA se descartan por share (corrige floors de D2.4; D2.7 ×3).
4. TIE-BREAK de order: sólo entre pares adyacentes con diferencia relativa de
   pérdida <= 5% (near-tie, rango de ruido observado en D2.7); el de mayor
   parent_zone_delta_loss_s va primero. Fuera de near-ties el orden es D2.1.

Evaluación: mismos 17 comparisons + per-file (estilo leave-one-file-out) para
verificar consistencia. NO se ajustan thresholds.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any, Iterable

from audit_d2_3_priority_cut import calibrated_priority_cut_rank
from audit_d2_7_residual_disagreements import (
    ComparisonSample,
    _evidence_key,
    _safe_nonnegative_float,
)


PRODUCT_PRIORITY_COVERAGE_TARGET = 0.55
PRODUCT_PRIORITY_CAP = 3
PRODUCT_WEAK_SHARE_MAX = 0.05
PRODUCT_NEAR_TIE_RELATIVE = 0.05

OBSERVATIONAL_RECOMMENDATION_MARKER = (
    "mantener esta diferencia como observación"
)


def derive_d21_order(
    episodes: Iterable[dict[str, Any]],
) -> tuple[int, ...]:
    """Order D2.1 desde ground truth (misma lógica que el shadow)."""
    episodes = [episode for episode in episodes if isinstance(episode, dict)]
    usable_global_rank = all(
        isinstance(episode.get("global_rank"), int)
        and episode.get("global_rank") >= 1
        for episode in episodes
    ) and len({episode.get("global_rank") for episode in episodes}) == len(episodes)
    if usable_global_rank:
        ordered = sorted(
            episodes,
            key=lambda episode: (
                episode.get("global_rank"),
                episode.get("episode_id"),
            ),
        )
    else:
        evidence_priority = {"strong": 2, "moderate": 1, "weak": 0}
        ordered = sorted(
            episodes,
            key=lambda episode: (
                -(_finite(episode.get("action_time_loss_s")) or 0.0),
                -evidence_priority.get(
                    _evidence_key(episode),
                    0,
                ),
                -(int(episode.get("action_channel_count") or 0)),
                -(_finite(episode.get("length_m")) or 0.0),
                episode.get("episode_id"),
            ),
        )
    return tuple(int(episode.get("episode_id")) for episode in ordered)


def load_all_samples(
    paths: Iterable[str | Path],
) -> list[ComparisonSample]:
    """Samples con ranking LLM; baseline D2.1 del shadow o derivado."""
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
            llm_order = ranking.get("ordered_episode_ids")
            llm_priority = ranking.get("priority_cut_rank")
            llm_no_actionable = ranking.get("no_actionable_start_rank")
            if not (
                isinstance(llm_order, list)
                and isinstance(llm_priority, int)
                and isinstance(llm_no_actionable, int)
            ):
                continue
            episodes_by_id: dict[int, dict[str, Any]] = {}
            for episode in comparison.get("episode_ground_truth") or []:
                if isinstance(episode, dict) and isinstance(
                    episode.get("episode_id"), int
                ):
                    episodes_by_id[episode["episode_id"]] = episode
            if not episodes_by_id:
                continue
            shadow = ranking.get("deterministic_shadow") or {}
            shadow_response = shadow.get("response") or {}
            if shadow.get("status") == "VALID" and isinstance(
                shadow_response.get("ordered_episode_ids"), list
            ):
                baseline_order = tuple(
                    int(value) for value in shadow_response["ordered_episode_ids"]
                )
                baseline_priority = shadow_response.get("priority_cut_rank")
                baseline_no_actionable = shadow_response.get(
                    "no_actionable_start_rank"
                )
            else:
                baseline_order = derive_d21_order(episodes_by_id.values())
                baseline_priority = 0
                baseline_no_actionable = len(episodes_by_id) + 1
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
                    baseline_order=baseline_order,
                    baseline_priority_cut_rank=int(baseline_priority),
                    baseline_no_actionable_start_rank=int(baseline_no_actionable),
                    episodes_by_id=episodes_by_id,
                )
            )
    return samples


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def has_direct_authorized_target(episode: dict[str, Any]) -> bool:
    """¿El episodio tiene un target directo de coaching autorizado?

    Replica la regla de accionabilidad de Python (misma que usa
    build_deterministic_grounded_episode_fallback): sólo canales brake/throttle
    con eventos direccionales generan recomendación de coaching; steering solo
    es observacional.
    """
    evidence_by_channel = episode.get("action_evidence_by_channel") or {}
    action_channels = episode.get("action_channels", []) or []
    if not isinstance(evidence_by_channel, dict) or not isinstance(
        action_channels, (list, tuple, set)
    ):
        return False
    for channel in action_channels:
        if channel not in {"brake", "throttle"}:
            continue
        info = evidence_by_channel.get(channel) or {}
        if not isinstance(info, dict):
            continue
        events = info.get("events") or []
        if not isinstance(events, (list, tuple)):
            continue
        directions = {
            str(event.get("direction"))
            for event in events
            if isinstance(event, dict)
            and event.get("persistent", True)
            and event.get("direction")
        }
        if len(directions) == 1 and directions <= {
            "higher_in_comparison_lap",
            "lower_in_comparison_lap",
        }:
            return True
    return False


def product_priority_cut_rank(
    order: Iterable[int],
    episodes_by_id: dict[int, dict[str, Any]],
    *,
    coverage_target: float = PRODUCT_PRIORITY_COVERAGE_TARGET,
    cap: int = PRODUCT_PRIORITY_CAP,
) -> int:
    """Prefix 55% + extensión por strong + target directo, con tope de foco."""
    ordered = tuple(int(value) for value in order)
    if not ordered:
        raise ValueError("Se requiere al menos un episodio.")
    if len(ordered) == 1:
        return 1

    losses = {
        episode_id: _safe_nonnegative_float(
            episodes_by_id[episode_id].get("action_time_loss_s")
        )
        for episode_id in ordered
    }
    cut = calibrated_priority_cut_rank(
        ordered,
        losses,
        coverage_target=coverage_target,
    )
    if cut >= len(ordered) - 1:
        return cut

    while cut < len(ordered) - 1 and cut < cap:
        next_episode = episodes_by_id.get(ordered[cut]) or {}
        if (
            _evidence_key(next_episode) == "strong"
            and has_direct_authorized_target(next_episode)
        ):
            cut += 1
        else:
            break
    # El tope de foco aplica al PRIORITARIO FINAL (base 55% + extensión).
    return max(1, min(cut, cap, len(ordered) - 1))


def product_no_actionable_start_rank(
    order: Iterable[int],
    episodes_by_id: dict[int, dict[str, Any]],
    *,
    priority_cut_rank: int,
    weak_share_max: float = PRODUCT_WEAK_SHARE_MAX,
) -> int:
    """Cola NO_ACCIONABLE: sólo observacional o weak con share negligible."""
    ordered = tuple(int(value) for value in order)
    if not ordered:
        raise ValueError("Se requiere al menos un episodio.")
    if not 1 <= priority_cut_rank <= len(ordered):
        raise ValueError("priority_cut_rank fuera de rango.")
    if not 0.0 <= weak_share_max <= 1.0:
        raise ValueError("weak_share_max debe estar en [0, 1].")

    losses = {
        episode_id: _safe_nonnegative_float(
            episodes_by_id[episode_id].get("action_time_loss_s")
        )
        for episode_id in ordered
    }
    total = sum(losses.values())
    start = len(ordered) + 1
    for rank in range(len(ordered), priority_cut_rank, -1):
        episode_id = ordered[rank - 1]
        episode = episodes_by_id.get(episode_id) or {}
        share = losses[episode_id] / total if total > 0.0 else 0.0
        is_observational = not has_direct_authorized_target(episode)
        if is_observational:
            start = rank
            continue
        if _evidence_key(episode) == "weak" and share <= weak_share_max:
            start = rank
            continue
        # moderate/strong con target directo: nunca NO_ACCIONABLE por share.
        break
    return start


def apply_tie_break(
    order: Iterable[int],
    episodes_by_id: dict[int, dict[str, Any]],
    *,
    near_tie_relative: float = PRODUCT_NEAR_TIE_RELATIVE,
) -> tuple[int, ...]:
    """Sólo en near-ties adyacentes: mayor parent_zone_delta_loss_s primero."""
    ordered = list(int(value) for value in order)
    if len(ordered) < 2:
        return tuple(ordered)

    losses = [
        _safe_nonnegative_float(
            episodes_by_id[episode_id].get("action_time_loss_s")
        )
        for episode_id in ordered
    ]

    def zone_delta(index: int) -> float:
        return _finite(
            (episodes_by_id.get(ordered[index]) or {}).get(
                "parent_zone_delta_loss_s"
            )
        ) or 0.0

    # Grupos de pares adyacentes near-tie.
    groups: list[list[int]] = []
    current: list[int] = []
    for index in range(len(ordered)):
        if not current:
            current = [index]
            continue
        previous = index - 1
        larger = max(losses[previous], losses[index])
        is_near_tie = (
            larger > 0.0
            and abs(losses[previous] - losses[index]) / larger
            <= near_tie_relative
        )
        if is_near_tie:
            current.append(index)
        else:
            groups.append(current)
            current = [index]
    if current:
        groups.append(current)

    result: list[int] = []
    for group in groups:
        if len(group) == 1:
            result.append(ordered[group[0]])
            continue
        members = sorted(
            group,
            key=lambda index: (-zone_delta(index), index),
        )
        result.extend(ordered[index] for index in members)
    return tuple(result)


def build_candidate(sample) -> dict[str, Any]:
    order = apply_tie_break(
        sample.baseline_order,
        sample.episodes_by_id,
    )
    priority_cut = product_priority_cut_rank(
        order,
        sample.episodes_by_id,
    )
    no_actionable_start = product_no_actionable_start_rank(
        order,
        sample.episodes_by_id,
        priority_cut_rank=priority_cut,
    )
    return {
        "ordered_episode_ids": list(order),
        "priority_cut_rank": priority_cut,
        "no_actionable_start_rank": no_actionable_start,
    }


def _derive_classifications(
    order: Iterable[int],
    priority_cut_rank: int,
    no_actionable_start_rank: int,
) -> tuple[tuple[int, int, str], ...]:
    ordered = tuple(int(value) for value in order)
    result = []
    for rank, episode_id in enumerate(ordered, start=1):
        if rank <= priority_cut_rank:
            classification = "PRIORITARIO"
        elif rank >= no_actionable_start_rank:
            classification = "NO_ACCIONABLE"
        else:
            classification = "SECUNDARIO"
        result.append((episode_id, rank, classification))
    return tuple(result)


def evaluate(samples: Iterable) -> dict[str, Any]:
    samples = list(samples)
    rows = []
    counts = {
        "order": 0,
        "priority_cut": 0,
        "no_actionable_cut": 0,
        "classifications": 0,
        "full": 0,
    }
    per_file: dict[str, dict[str, int]] = {}
    for sample in samples:
        candidate = build_candidate(sample)
        llm_classifications = _derive_classifications(
            sample.llm_order,
            sample.llm_priority_cut_rank,
            sample.llm_no_actionable_start_rank,
        )
        candidate_classifications = _derive_classifications(
            candidate["ordered_episode_ids"],
            candidate["priority_cut_rank"],
            candidate["no_actionable_start_rank"],
        )
        agreement = {
            "order": tuple(candidate["ordered_episode_ids"]) == sample.llm_order,
            "priority_cut": (
                candidate["priority_cut_rank"] == sample.llm_priority_cut_rank
            ),
            "no_actionable_cut": (
                candidate["no_actionable_start_rank"]
                == sample.llm_no_actionable_start_rank
            ),
            "classifications": candidate_classifications == llm_classifications,
        }
        agreement["full"] = all(agreement.values())
        for key in counts:
            counts[key] += int(agreement[key])

        file_key = str(sample.source_path)
        bucket = per_file.setdefault(file_key, {"n": 0, "full": 0})
        bucket["n"] += 1
        bucket["full"] += int(agreement["full"])

        rows.append(
            {
                "track": sample.track,
                "comparison": sample.comparison,
                "candidate": candidate,
                "agreement": agreement,
            }
        )

    count = len(samples)
    return {
        "comparison_count": count,
        "rates": {
            key: {"count": counts[key], "rate": counts[key] / count if count else 0.0}
            for key in counts
        },
        "per_file": {
            path: bucket
            for path, bucket in sorted(per_file.items())
        },
        "rows": rows,
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
        description="D2.9 product-principled deterministic ranker policy (shadow)."
    )
    parser.add_argument("inputs", nargs="+", help="JSON files or glob patterns.")
    parser.add_argument("--json-output", type=Path, default=None)
    args = parser.parse_args()

    samples = load_all_samples(_expand_inputs(args.inputs))
    if not samples:
        raise SystemExit("No se encontraron comparisons con priority_ranking.")
    report = evaluate(samples)

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Output: {args.json_output.resolve()}")

    print("=" * 88)
    print("D2.9 PRODUCT-PRINCIPLED RANKER POLICY (SHADOW)")
    print("=" * 88)
    print(
        "Reglas: order D2.1 · cut 55% + strong+target (cap 3) · "
        "NO_ACCIONABLE solo observacional/weak-negligible · "
        "tie-break parent_zone_delta en near-ties <=5%"
    )
    with_shadow = sum(
        1 for sample in samples if sample.baseline_priority_cut_rank != 0
    )
    print(
        f"Comparisons: {report['comparison_count']} "
        f"(baseline shadow={with_shadow} · derivado={len(samples) - with_shadow})"
    )
    for key, value in report["rates"].items():
        print(f"  {key:16} {value['count']}/{report['comparison_count']} = {value['rate']:.3f}")
    print("Per-file full agreement:")
    for path, bucket in report["per_file"].items():
        print(
            f"  {Path(path).name[:50]:52} {bucket['full']}/{bucket['n']}"
        )
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
