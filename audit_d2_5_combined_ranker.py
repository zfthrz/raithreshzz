from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from audit_d2_3_priority_cut import calibrated_priority_cut_rank
from audit_d2_4_no_actionable import (
    EpisodeFacts,
    calibrated_no_actionable_start_rank,
)


DEFAULT_PRIORITY_COVERAGE_TARGET = 0.55
DEFAULT_WEAK_SHARE_MAX = 0.05
DEFAULT_MODERATE_SHARE_MAX = 0.04
DEFAULT_STRONG_SHARE_MAX = 0.01


@dataclass(frozen=True)
class ComparisonSample:
    source_path: Path
    track: str
    comparison: str
    episode_ids: tuple[int, ...]
    llm_order: tuple[int, ...]
    llm_priority_cut_rank: int
    llm_no_actionable_start_rank: int
    baseline_order: tuple[int, ...]
    baseline_priority_cut_rank: int
    baseline_no_actionable_start_rank: int
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


def build_combined_candidate(sample: ComparisonSample) -> dict:
    priority_cut = calibrated_priority_cut_rank(
        sample.baseline_order,
        sample.losses_by_episode_id,
        coverage_target=DEFAULT_PRIORITY_COVERAGE_TARGET,
    )
    no_actionable_start = calibrated_no_actionable_start_rank(
        sample.baseline_order,
        sample.facts_by_episode_id,
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
            baseline_priority = baseline.get("priority_cut_rank")
            baseline_no_actionable = baseline.get("no_actionable_start_rank")

            if (
                not isinstance(llm_order, list)
                or not isinstance(llm_priority, int)
                or not isinstance(llm_no_actionable, int)
                or not isinstance(baseline_order, list)
                or not isinstance(baseline_priority, int)
                or not isinstance(baseline_no_actionable, int)
            ):
                continue

            losses: dict[int, float] = {}
            facts: dict[int, EpisodeFacts] = {}
            episode_ids: list[int] = []
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
                episode_ids.append(episode_id)
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
                    episode_ids=tuple(episode_ids),
                    llm_order=tuple(llm_order),
                    llm_priority_cut_rank=llm_priority,
                    llm_no_actionable_start_rank=llm_no_actionable,
                    baseline_order=tuple(baseline_order),
                    baseline_priority_cut_rank=baseline_priority,
                    baseline_no_actionable_start_rank=baseline_no_actionable,
                    losses_by_episode_id=losses,
                    facts_by_episode_id=facts,
                )
            )

    return samples


def evaluate(samples: Iterable[ComparisonSample]) -> dict:
    samples = list(samples)
    rows = []

    counts = {
        "order": 0,
        "priority_cut": 0,
        "no_actionable_cut": 0,
        "classifications": 0,
        "full": 0,
    }
    baseline_counts = {
        "order": 0,
        "priority_cut": 0,
        "no_actionable_cut": 0,
        "classifications": 0,
        "full": 0,
    }

    for sample in samples:
        candidate = build_combined_candidate(sample)

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
        baseline_classifications = _derive_classifications(
            sample.baseline_order,
            sample.baseline_priority_cut_rank,
            sample.baseline_no_actionable_start_rank,
        )

        agreement = {
            "order": (
                tuple(candidate["ordered_episode_ids"])
                == sample.llm_order
            ),
            "priority_cut": (
                candidate["priority_cut_rank"]
                == sample.llm_priority_cut_rank
            ),
            "no_actionable_cut": (
                candidate["no_actionable_start_rank"]
                == sample.llm_no_actionable_start_rank
            ),
            "classifications": (
                candidate_classifications == llm_classifications
            ),
        }
        agreement["full"] = all(agreement.values())

        baseline_agreement = {
            "order": sample.baseline_order == sample.llm_order,
            "priority_cut": (
                sample.baseline_priority_cut_rank
                == sample.llm_priority_cut_rank
            ),
            "no_actionable_cut": (
                sample.baseline_no_actionable_start_rank
                == sample.llm_no_actionable_start_rank
            ),
            "classifications": (
                baseline_classifications == llm_classifications
            ),
        }
        baseline_agreement["full"] = all(
            baseline_agreement.values()
        )

        for key in counts:
            counts[key] += int(agreement[key])
            baseline_counts[key] += int(baseline_agreement[key])

        rows.append(
            {
                "track": sample.track,
                "comparison": sample.comparison,
                "llm": {
                    "ordered_episode_ids": list(sample.llm_order),
                    "priority_cut_rank": sample.llm_priority_cut_rank,
                    "no_actionable_start_rank": (
                        sample.llm_no_actionable_start_rank
                    ),
                },
                "candidate": candidate,
                "agreement": agreement,
            }
        )

    count = len(samples)

    def _rates(raw_counts):
        return {
            key: {
                "count": raw_counts[key],
                "rate": raw_counts[key] / count if count else 0.0,
            }
            for key in raw_counts
        }

    return {
        "comparison_count": count,
        "baseline": _rates(baseline_counts),
        "combined_candidate": _rates(counts),
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
            "D2.5 combined evaluation: deterministic order + calibrated "
            "priority cut + calibrated NO_ACCIONABLE cut."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="JSON files or glob patterns from data/generated/llm_results.",
    )
    parser.add_argument("--json-output", type=Path, default=None)
    args = parser.parse_args()

    paths = _expand_inputs(args.inputs)
    samples = load_samples(paths)
    if not samples:
        raise SystemExit(
            "No se encontraron comparisons con deterministic_shadow VALID."
        )

    report = evaluate(samples)
    count = report["comparison_count"]
    print(
        f"Files: {len({s.source_path for s in samples})} | "
        f"Comparisons: {count}"
    )

    for label, key in (
        ("Order exact", "order"),
        ("Priority cut exact", "priority_cut"),
        ("NO_ACCIONABLE cut exact", "no_actionable_cut"),
        ("Classifications exact", "classifications"),
        ("Full agreement", "full"),
    ):
        base = report["baseline"][key]
        cand = report["combined_candidate"][key]
        print(
            f"{label}: baseline={base['count']}/{count} "
            f"({base['rate']:.1%}) | "
            f"candidate={cand['count']}/{count} "
            f"({cand['rate']:.1%})"
        )

    disagreements = [
        row for row in report["rows"]
        if not row["agreement"]["full"]
    ]
    if disagreements:
        print("Combined candidate disagreements:")
        for row in disagreements:
            mismatch = [
                key
                for key, value in row["agreement"].items()
                if key != "full" and not value
            ]
            print(
                f"  {row['track']} {row['comparison']}: "
                + ", ".join(mismatch)
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
