from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from audit_d2_3_priority_cut import calibrated_priority_cut_rank


DEFAULT_WEAK_SHARE_MAX = 0.05
DEFAULT_MODERATE_SHARE_MAX = 0.04
DEFAULT_STRONG_SHARE_MAX = 0.01
DEFAULT_PRIORITY_COVERAGE_TARGET = 0.55


@dataclass(frozen=True)
class EpisodeFacts:
    episode_id: int
    loss: float
    evidence_strength: str


@dataclass(frozen=True)
class ComparisonSample:
    source_path: Path
    track: str
    comparison: str
    llm_order: tuple[int, ...]
    deterministic_order: tuple[int, ...]
    llm_priority_cut_rank: int
    llm_no_actionable_start_rank: int
    baseline_no_actionable_start_rank: int
    episodes_by_id: dict[int, EpisodeFacts]


def _safe_nonnegative_float(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result != result or result in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, result)


def calibrated_no_actionable_start_rank(
    ordered_episode_ids: Iterable[int],
    episodes_by_id: dict[int, EpisodeFacts],
    *,
    priority_cut_rank: int,
    weak_share_max: float = DEFAULT_WEAK_SHARE_MAX,
    moderate_share_max: float = DEFAULT_MODERATE_SHARE_MAX,
    strong_share_max: float = DEFAULT_STRONG_SHARE_MAX,
) -> int:
    """
    D2.4 offline candidate.

    Starting from the least-important deterministic episode, classify a
    trailing suffix as NO_ACCIONABLE only while each item's deterministic
    action-time-loss share stays below an evidence-conditioned floor.

    The candidate is observational only and cannot move the boundary into the
    PRIORITARIO prefix.
    """
    ordered = tuple(int(value) for value in ordered_episode_ids)
    if not ordered:
        raise ValueError("Se requiere al menos un episodio.")

    thresholds = {
        "weak": weak_share_max,
        "moderate": moderate_share_max,
        "strong": strong_share_max,
    }
    if any(not 0.0 <= value <= 1.0 for value in thresholds.values()):
        raise ValueError("Los thresholds de share deben estar en [0, 1].")

    if not 1 <= priority_cut_rank <= len(ordered):
        raise ValueError("priority_cut_rank fuera de rango.")

    facts = [episodes_by_id[episode_id] for episode_id in ordered]
    total_loss = sum(_safe_nonnegative_float(item.loss) for item in facts)
    if total_loss <= 0.0:
        return len(ordered) + 1

    start = len(ordered) + 1
    for rank in range(len(ordered), priority_cut_rank, -1):
        facts_item = facts[rank - 1]
        evidence = str(facts_item.evidence_strength or "").strip().lower()
        threshold = thresholds.get(evidence, 0.0)
        share = _safe_nonnegative_float(facts_item.loss) / total_loss

        if share > threshold:
            break
        start = rank

    return max(start, priority_cut_rank + 1)


def load_samples(paths: Iterable[str | Path]) -> list[ComparisonSample]:
    samples: list[ComparisonSample] = []

    for raw_path in paths:
        path = Path(raw_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        track = str((payload.get("metadata") or {}).get("track") or path.stem)

        for comparison in payload.get("comparisons") or []:
            audit = comparison.get("llm_validation_audit") or {}
            ranking = audit.get("priority_ranking") or {}
            shadow = ranking.get("deterministic_shadow") or {}
            if shadow.get("status") != "VALID":
                continue

            deterministic_response = shadow.get("response") or {}
            llm_order = ranking.get("ordered_episode_ids")
            deterministic_order = deterministic_response.get(
                "ordered_episode_ids"
            )
            llm_priority_cut = ranking.get("priority_cut_rank")
            llm_no_actionable = ranking.get("no_actionable_start_rank")
            baseline_no_actionable = deterministic_response.get(
                "no_actionable_start_rank"
            )

            if (
                not isinstance(llm_order, list)
                or not isinstance(deterministic_order, list)
                or not isinstance(llm_priority_cut, int)
                or not isinstance(llm_no_actionable, int)
                or not isinstance(baseline_no_actionable, int)
            ):
                continue

            episodes_by_id: dict[int, EpisodeFacts] = {}
            for episode in comparison.get("episode_ground_truth") or []:
                if not isinstance(episode, dict):
                    continue
                episode_id = episode.get("episode_id")
                if not isinstance(episode_id, int):
                    continue
                episodes_by_id[episode_id] = EpisodeFacts(
                    episode_id=episode_id,
                    loss=_safe_nonnegative_float(
                        episode.get("action_time_loss_s")
                    ),
                    evidence_strength=str(
                        episode.get("evidence_strength") or ""
                    ).strip().lower(),
                )

            if any(
                episode_id not in episodes_by_id
                for episode_id in deterministic_order
            ):
                continue

            samples.append(
                ComparisonSample(
                    source_path=path,
                    track=track,
                    comparison=(
                        f"{comparison.get('reference_lap')}->"
                        f"{comparison.get('comparison_lap')}"
                    ),
                    llm_order=tuple(llm_order),
                    deterministic_order=tuple(deterministic_order),
                    llm_priority_cut_rank=llm_priority_cut,
                    llm_no_actionable_start_rank=llm_no_actionable,
                    baseline_no_actionable_start_rank=baseline_no_actionable,
                    episodes_by_id=episodes_by_id,
                )
            )

    return samples


def evaluate_baseline(samples: Iterable[ComparisonSample]) -> dict:
    samples = list(samples)
    exact = sum(
        sample.baseline_no_actionable_start_rank
        == sample.llm_no_actionable_start_rank
        for sample in samples
    )
    absolute_error = sum(
        abs(
            sample.baseline_no_actionable_start_rank
            - sample.llm_no_actionable_start_rank
        )
        for sample in samples
    )
    count = len(samples)
    return {
        "comparison_count": count,
        "exact_match_count": exact,
        "exact_match_rate": exact / count if count else 0.0,
        "mean_absolute_rank_error": absolute_error / count if count else 0.0,
    }


def evaluate_candidate(
    samples: Iterable[ComparisonSample],
    *,
    weak_share_max: float = DEFAULT_WEAK_SHARE_MAX,
    moderate_share_max: float = DEFAULT_MODERATE_SHARE_MAX,
    strong_share_max: float = DEFAULT_STRONG_SHARE_MAX,
    priority_coverage_target: float = DEFAULT_PRIORITY_COVERAGE_TARGET,
) -> dict:
    rows = []
    exact = 0
    absolute_error = 0

    for sample in samples:
        losses = {
            episode_id: facts.loss
            for episode_id, facts in sample.episodes_by_id.items()
        }
        calibrated_priority_cut = calibrated_priority_cut_rank(
            sample.deterministic_order,
            losses,
            coverage_target=priority_coverage_target,
        )
        predicted = calibrated_no_actionable_start_rank(
            sample.deterministic_order,
            sample.episodes_by_id,
            priority_cut_rank=calibrated_priority_cut,
            weak_share_max=weak_share_max,
            moderate_share_max=moderate_share_max,
            strong_share_max=strong_share_max,
        )
        is_exact = predicted == sample.llm_no_actionable_start_rank
        exact += int(is_exact)
        absolute_error += abs(
            predicted - sample.llm_no_actionable_start_rank
        )
        rows.append(
            {
                "track": sample.track,
                "comparison": sample.comparison,
                "llm_no_actionable_start_rank": (
                    sample.llm_no_actionable_start_rank
                ),
                "candidate_no_actionable_start_rank": predicted,
                "calibrated_priority_cut_rank": calibrated_priority_cut,
                "exact": is_exact,
            }
        )

    count = len(rows)
    return {
        "comparison_count": count,
        "exact_match_count": exact,
        "exact_match_rate": exact / count if count else 0.0,
        "mean_absolute_rank_error": absolute_error / count if count else 0.0,
        "thresholds": {
            "weak_share_max": weak_share_max,
            "moderate_share_max": moderate_share_max,
            "strong_share_max": strong_share_max,
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
        description=(
            "D2.4 offline calibration audit for deterministic "
            "NO_ACCIONABLE tail policies."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="JSON files or glob patterns from data/generated/llm_results.",
    )
    parser.add_argument("--weak-share-max", type=float, default=0.05)
    parser.add_argument("--moderate-share-max", type=float, default=0.04)
    parser.add_argument("--strong-share-max", type=float, default=0.01)
    parser.add_argument("--json-output", type=Path, default=None)
    args = parser.parse_args()

    paths = _expand_inputs(args.inputs)
    samples = load_samples(paths)
    if not samples:
        raise SystemExit(
            "No se encontraron comparisons con deterministic_shadow VALID."
        )

    baseline = evaluate_baseline(samples)
    candidate = evaluate_candidate(
        samples,
        weak_share_max=args.weak_share_max,
        moderate_share_max=args.moderate_share_max,
        strong_share_max=args.strong_share_max,
    )

    report = {
        "sample_file_count": len(
            {sample.source_path for sample in samples}
        ),
        "comparison_count": len(samples),
        "baseline": baseline,
        "candidate": candidate,
    }

    print(
        f"Files: {report['sample_file_count']} | "
        f"Comparisons: {report['comparison_count']}"
    )
    print(
        "Baseline exact: "
        f"{baseline['exact_match_count']}/{baseline['comparison_count']} "
        f"({baseline['exact_match_rate']:.1%}), "
        f"MAE={baseline['mean_absolute_rank_error']:.3f}"
    )
    print(
        "Candidate exact: "
        f"{candidate['exact_match_count']}/{candidate['comparison_count']} "
        f"({candidate['exact_match_rate']:.1%}), "
        f"MAE={candidate['mean_absolute_rank_error']:.3f}"
    )
    print(
        "Thresholds: "
        f"weak={args.weak_share_max:.3f} "
        f"moderate={args.moderate_share_max:.3f} "
        f"strong={args.strong_share_max:.3f}"
    )

    disagreements = [
        row for row in candidate["rows"] if not row["exact"]
    ]
    if disagreements:
        print("Candidate disagreements:")
        for row in disagreements:
            print(
                f"  {row['track']} {row['comparison']}: "
                f"LLM={row['llm_no_actionable_start_rank']} "
                f"candidate={row['candidate_no_actionable_start_rank']}"
            )

    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
