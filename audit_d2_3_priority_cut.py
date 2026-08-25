from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_COVERAGE_TARGET = 0.55


@dataclass(frozen=True)
class ComparisonSample:
    source_path: Path
    track: str
    comparison: str
    llm_order: tuple[int, ...]
    deterministic_order: tuple[int, ...]
    llm_priority_cut_rank: int
    baseline_priority_cut_rank: int
    losses_by_episode_id: dict[int, float]


def _safe_nonnegative_float(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result != result or result in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, result)


def calibrated_priority_cut_rank(
    ordered_episode_ids: Iterable[int],
    losses_by_episode_id: dict[int, float],
    *,
    coverage_target: float = DEFAULT_COVERAGE_TARGET,
) -> int:
    """
    D2.3 offline candidate.

    Select the smallest leading prefix whose cumulative deterministic
    action-time loss reaches ``coverage_target`` of the comparison total.

    This is intentionally a calibration candidate only. It does not authorize
    runtime coaching and does not change the production ranker.
    """
    ordered = tuple(int(value) for value in ordered_episode_ids)
    if not ordered:
        raise ValueError("Se requiere al menos un episodio.")
    if not 0.0 < coverage_target <= 1.0:
        raise ValueError("coverage_target debe estar en (0, 1].")

    losses = [
        _safe_nonnegative_float(losses_by_episode_id.get(episode_id))
        for episode_id in ordered
    ]
    total = sum(losses)

    if len(ordered) == 1:
        return 1

    if total <= 0.0:
        return 1

    cumulative = 0.0
    cut = 1
    for rank, loss in enumerate(losses, start=1):
        cumulative += loss
        cut = rank
        if cumulative / total >= coverage_target:
            break

    # Preserve the existing deterministic safety convention: with more than
    # one episode, keep at least one episode outside PRIORITARIO.
    return max(1, min(cut, len(ordered) - 1))


def load_samples(paths: Iterable[str | Path]) -> list[ComparisonSample]:
    samples: list[ComparisonSample] = []

    for raw_path in paths:
        path = Path(raw_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata") or {}
        track = str(metadata.get("track") or path.stem)

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
            llm_cut = ranking.get("priority_cut_rank")
            baseline_cut = deterministic_response.get("priority_cut_rank")

            if (
                not isinstance(llm_order, list)
                or not isinstance(deterministic_order, list)
                or not isinstance(llm_cut, int)
                or not isinstance(baseline_cut, int)
            ):
                continue

            ground_truth = comparison.get("episode_ground_truth") or []
            losses_by_episode_id: dict[int, float] = {}
            for episode in ground_truth:
                if not isinstance(episode, dict):
                    continue
                episode_id = episode.get("episode_id")
                if not isinstance(episode_id, int):
                    continue
                losses_by_episode_id[episode_id] = _safe_nonnegative_float(
                    episode.get("action_time_loss_s")
                )

            if any(
                episode_id not in losses_by_episode_id
                for episode_id in deterministic_order
            ):
                continue

            comparison_label = (
                f"{comparison.get('reference_lap')}->"
                f"{comparison.get('comparison_lap')}"
            )
            samples.append(
                ComparisonSample(
                    source_path=path,
                    track=track,
                    comparison=comparison_label,
                    llm_order=tuple(llm_order),
                    deterministic_order=tuple(deterministic_order),
                    llm_priority_cut_rank=llm_cut,
                    baseline_priority_cut_rank=baseline_cut,
                    losses_by_episode_id=losses_by_episode_id,
                )
            )

    return samples


def evaluate_coverage_target(
    samples: Iterable[ComparisonSample],
    coverage_target: float,
) -> dict:
    rows = []
    exact = 0
    absolute_error = 0

    for sample in samples:
        predicted = calibrated_priority_cut_rank(
            sample.deterministic_order,
            sample.losses_by_episode_id,
            coverage_target=coverage_target,
        )
        is_exact = predicted == sample.llm_priority_cut_rank
        exact += int(is_exact)
        absolute_error += abs(predicted - sample.llm_priority_cut_rank)
        rows.append(
            {
                "track": sample.track,
                "comparison": sample.comparison,
                "llm_cut": sample.llm_priority_cut_rank,
                "candidate_cut": predicted,
                "exact": is_exact,
            }
        )

    count = len(rows)
    return {
        "coverage_target": coverage_target,
        "comparison_count": count,
        "exact_match_count": exact,
        "exact_match_rate": (exact / count) if count else 0.0,
        "mean_absolute_rank_error": (
            absolute_error / count if count else 0.0
        ),
        "rows": rows,
    }


def evaluate_baseline(samples: Iterable[ComparisonSample]) -> dict:
    samples = list(samples)
    exact = sum(
        sample.baseline_priority_cut_rank
        == sample.llm_priority_cut_rank
        for sample in samples
    )
    absolute_error = sum(
        abs(
            sample.baseline_priority_cut_rank
            - sample.llm_priority_cut_rank
        )
        for sample in samples
    )
    count = len(samples)
    return {
        "comparison_count": count,
        "exact_match_count": exact,
        "exact_match_rate": exact / count if count else 0.0,
        "mean_absolute_rank_error": (
            absolute_error / count if count else 0.0
        ),
    }


def grid_search(
    samples: Iterable[ComparisonSample],
    *,
    start: float = 0.45,
    end: float = 0.70,
    step: float = 0.01,
) -> list[dict]:
    samples = list(samples)
    results = []
    value = start

    while value <= end + 1e-12:
        target = round(value, 10)
        result = evaluate_coverage_target(samples, target)
        results.append(result)
        value += step

    return sorted(
        results,
        key=lambda item: (
            -item["exact_match_rate"],
            item["mean_absolute_rank_error"],
            abs(item["coverage_target"] - DEFAULT_COVERAGE_TARGET),
        ),
    )


def _expand_inputs(values: list[str]) -> list[str]:
    result = []
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
            "D2.3 offline calibration audit for deterministic "
            "priority-cut policies."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="JSON files or glob patterns from data/generated/llm_results.",
    )
    parser.add_argument(
        "--coverage-target",
        type=float,
        default=DEFAULT_COVERAGE_TARGET,
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    paths = _expand_inputs(args.inputs)
    samples = load_samples(paths)
    if not samples:
        raise SystemExit(
            "No se encontraron comparisons con deterministic_shadow VALID."
        )

    baseline = evaluate_baseline(samples)
    candidate = evaluate_coverage_target(
        samples,
        args.coverage_target,
    )
    search = grid_search(samples)

    report = {
        "sample_file_count": len(
            {sample.source_path for sample in samples}
        ),
        "comparison_count": len(samples),
        "baseline": baseline,
        "candidate": candidate,
        "grid_search_top_5": [
            {
                key: value
                for key, value in row.items()
                if key != "rows"
            }
            for row in search[:5]
        ],
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
        f"Candidate {args.coverage_target:.2f} exact: "
        f"{candidate['exact_match_count']}/"
        f"{candidate['comparison_count']} "
        f"({candidate['exact_match_rate']:.1%}), "
        f"MAE={candidate['mean_absolute_rank_error']:.3f}"
    )
    print("Best grid candidates:")
    for row in search[:5]:
        print(
            f"  coverage={row['coverage_target']:.2f} "
            f"exact={row['exact_match_count']}/"
            f"{row['comparison_count']} "
            f"({row['exact_match_rate']:.1%}) "
            f"MAE={row['mean_absolute_rank_error']:.3f}"
        )

    disagreements = [
        row for row in candidate["rows"] if not row["exact"]
    ]
    if disagreements:
        print("Candidate disagreements:")
        for row in disagreements:
            print(
                f"  {row['track']} {row['comparison']}: "
                f"LLM={row['llm_cut']} "
                f"candidate={row['candidate_cut']}"
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
