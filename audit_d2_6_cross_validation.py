from __future__ import annotations

import argparse
import glob
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from audit_d2_3_priority_cut import calibrated_priority_cut_rank
from audit_d2_4_no_actionable import (
    EpisodeFacts,
    calibrated_no_actionable_start_rank,
)


@dataclass(frozen=True)
class ComparisonSample:
    source_path: Path
    track: str
    comparison: str
    llm_order: tuple[int, ...]
    baseline_order: tuple[int, ...]
    llm_priority_cut_rank: int
    llm_no_actionable_start_rank: int
    losses_by_episode_id: dict[int, float]
    facts_by_episode_id: dict[int, EpisodeFacts]


def _safe_nonnegative_float(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result != result or result in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, result)


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

            baseline = shadow.get("response") or {}
            llm_order = ranking.get("ordered_episode_ids")
            llm_priority = ranking.get("priority_cut_rank")
            llm_no_actionable = ranking.get("no_actionable_start_rank")
            baseline_order = baseline.get("ordered_episode_ids")

            if (
                not isinstance(llm_order, list)
                or not isinstance(llm_priority, int)
                or not isinstance(llm_no_actionable, int)
                or not isinstance(baseline_order, list)
            ):
                continue

            losses: dict[int, float] = {}
            facts: dict[int, EpisodeFacts] = {}
            for episode in comparison.get("episode_ground_truth") or []:
                if not isinstance(episode, dict):
                    continue
                episode_id = episode.get("episode_id")
                if not isinstance(episode_id, int):
                    continue
                loss = _safe_nonnegative_float(
                    episode.get("action_time_loss_s")
                )
                evidence = str(
                    episode.get("evidence_strength") or ""
                ).strip().lower()
                losses[episode_id] = loss
                facts[episode_id] = EpisodeFacts(
                    episode_id=episode_id,
                    loss=loss,
                    evidence_strength=evidence,
                )

            if set(baseline_order) != set(losses):
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
                    baseline_order=tuple(baseline_order),
                    llm_priority_cut_rank=llm_priority,
                    llm_no_actionable_start_rank=llm_no_actionable,
                    losses_by_episode_id=losses,
                    facts_by_episode_id=facts,
                )
            )

    return samples


def predict(sample: ComparisonSample, params: tuple[float, float, float, float]):
    coverage, weak_max, moderate_max, strong_max = params

    priority_cut = calibrated_priority_cut_rank(
        sample.baseline_order,
        sample.losses_by_episode_id,
        coverage_target=coverage,
    )
    no_actionable_start = calibrated_no_actionable_start_rank(
        sample.baseline_order,
        sample.facts_by_episode_id,
        priority_cut_rank=priority_cut,
        weak_share_max=weak_max,
        moderate_share_max=moderate_max,
        strong_share_max=strong_max,
    )
    return priority_cut, no_actionable_start


def score(samples: Iterable[ComparisonSample], params):
    samples = list(samples)
    full = 0
    classifications = 0
    priority = 0
    no_actionable = 0
    cut_error = 0

    for sample in samples:
        priority_cut, no_actionable_start = predict(sample, params)

        priority += int(
            priority_cut == sample.llm_priority_cut_rank
        )
        no_actionable += int(
            no_actionable_start
            == sample.llm_no_actionable_start_rank
        )
        cut_error += (
            abs(priority_cut - sample.llm_priority_cut_rank)
            + abs(
                no_actionable_start
                - sample.llm_no_actionable_start_rank
            )
        )

        llm_cls = _derive_classifications(
            sample.llm_order,
            sample.llm_priority_cut_rank,
            sample.llm_no_actionable_start_rank,
        )
        candidate_cls = _derive_classifications(
            sample.baseline_order,
            priority_cut,
            no_actionable_start,
        )
        cls_match = candidate_cls == llm_cls
        classifications += int(cls_match)

        full_match = (
            sample.baseline_order == sample.llm_order
            and priority_cut == sample.llm_priority_cut_rank
            and no_actionable_start
            == sample.llm_no_actionable_start_rank
            and cls_match
        )
        full += int(full_match)

    n = len(samples)
    return {
        "n": n,
        "full": full,
        "classifications": classifications,
        "priority": priority,
        "no_actionable": no_actionable,
        "cut_mae": (cut_error / (2 * n)) if n else 0.0,
    }


def parameter_grid():
    coverages = [round(v, 2) for v in (
        0.48, 0.50, 0.52, 0.54, 0.55, 0.56, 0.58, 0.60
    )]
    weak_values = [0.03, 0.04, 0.05, 0.06, 0.07]
    moderate_values = [0.02, 0.03, 0.04, 0.05, 0.06]
    strong_values = [0.00, 0.01, 0.02]
    return list(
        itertools.product(
            coverages,
            weak_values,
            moderate_values,
            strong_values,
        )
    )


def _sort_key(item):
    params, metrics = item
    return (
        -metrics["full"],
        -metrics["classifications"],
        -metrics["priority"],
        -metrics["no_actionable"],
        metrics["cut_mae"],
        abs(params[0] - 0.55),
        abs(params[1] - 0.05),
        abs(params[2] - 0.04),
        abs(params[3] - 0.01),
    )


def best_params(samples: Iterable[ComparisonSample]):
    ranked = [
        (params, score(samples, params))
        for params in parameter_grid()
    ]
    ranked.sort(key=_sort_key)
    return ranked


def leave_one_file_out(samples: Iterable[ComparisonSample]):
    samples = list(samples)
    files = sorted({sample.source_path for sample in samples})
    folds = []

    for held_out in files:
        train = [
            sample for sample in samples
            if sample.source_path != held_out
        ]
        test = [
            sample for sample in samples
            if sample.source_path == held_out
        ]
        ranked = best_params(train)
        params, train_metrics = ranked[0]
        test_metrics = score(test, params)
        folds.append(
            {
                "held_out": str(held_out),
                "params": params,
                "train": train_metrics,
                "test": test_metrics,
            }
        )

    return folds


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
            "D2.6 joint grid search + leave-one-file-out cross-validation "
            "for deterministic ranker cut calibration."
        )
    )
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_args()

    paths = _expand_inputs(args.inputs)
    samples = load_samples(paths)
    if not samples:
        raise SystemExit(
            "No se encontraron comparisons con deterministic_shadow VALID."
        )

    ranked = best_params(samples)
    best, best_metrics = ranked[0]
    current = (0.55, 0.05, 0.04, 0.01)
    current_metrics = score(samples, current)

    print(
        f"Files: {len({s.source_path for s in samples})} | "
        f"Comparisons: {len(samples)}"
    )
    print(
        "Current params: "
        f"coverage={current[0]:.2f} weak={current[1]:.2f} "
        f"moderate={current[2]:.2f} strong={current[3]:.2f}"
    )
    print(
        "Current full/classifications: "
        f"{current_metrics['full']}/{current_metrics['n']} "
        f"({current_metrics['full']/current_metrics['n']:.1%}) / "
        f"{current_metrics['classifications']}/{current_metrics['n']} "
        f"({current_metrics['classifications']/current_metrics['n']:.1%})"
    )
    print(
        "Best in-sample params: "
        f"coverage={best[0]:.2f} weak={best[1]:.2f} "
        f"moderate={best[2]:.2f} strong={best[3]:.2f}"
    )
    print(
        "Best in-sample full/classifications: "
        f"{best_metrics['full']}/{best_metrics['n']} "
        f"({best_metrics['full']/best_metrics['n']:.1%}) / "
        f"{best_metrics['classifications']}/{best_metrics['n']} "
        f"({best_metrics['classifications']/best_metrics['n']:.1%})"
    )
    print("Top 5 parameter sets:")
    for params, metrics in ranked[:5]:
        print(
            f"  cov={params[0]:.2f} weak={params[1]:.2f} "
            f"mod={params[2]:.2f} strong={params[3]:.2f} | "
            f"full={metrics['full']}/{metrics['n']} "
            f"cls={metrics['classifications']}/{metrics['n']} "
            f"priority={metrics['priority']}/{metrics['n']} "
            f"noact={metrics['no_actionable']}/{metrics['n']} "
            f"cut_MAE={metrics['cut_mae']:.3f}"
        )

    folds = leave_one_file_out(samples)
    total_test = sum(fold["test"]["n"] for fold in folds)
    total_full = sum(fold["test"]["full"] for fold in folds)
    total_cls = sum(
        fold["test"]["classifications"] for fold in folds
    )

    print("Leave-one-file-out:")
    for fold in folds:
        p = fold["params"]
        t = fold["test"]
        print(
            f"  {Path(fold['held_out']).name}: "
            f"params=({p[0]:.2f},{p[1]:.2f},{p[2]:.2f},{p[3]:.2f}) "
            f"full={t['full']}/{t['n']} "
            f"cls={t['classifications']}/{t['n']}"
        )

    print(
        "LOFO aggregate full/classifications: "
        f"{total_full}/{total_test} "
        f"({total_full/total_test:.1%}) / "
        f"{total_cls}/{total_test} "
        f"({total_cls/total_test:.1%})"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
