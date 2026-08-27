#!/usr/bin/env python3
"""Build a deterministic H2 review queue restricted to evaluation sessions."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from auto_calibrate_matcher import assign_sessions, collect_records, collect_sessions
from build_uncovered_calibration_queue import _slug, write_documents
from pair_review_queue import stable_pair_id


def _number(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def select_evaluation_pairs(
    features: list[dict[str, Any]],
    labeled_ids: set[str],
    evaluation_session_ids: set[int],
    *,
    per_lens: int = 6,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    eligible = [
        item for item in features
        if isinstance(item, dict)
        and isinstance(item.get("pair_id"), str)
        and item["pair_id"] not in labeled_ids
        and item.get("session_a") in evaluation_session_ids
        and item.get("session_b") in evaluation_session_ids
    ]

    def strong(item: dict[str, Any]) -> bool:
        return (
            _number(item.get("center_distance_abs_diff_m"), 1e9) <= 200.0
            and _number(item.get("overlap_over_shorter"), 0.0) >= 0.90
            and _number(item.get("overlap_over_union"), 0.0) >= 0.40
            and len(item.get("shared_channels") or []) >= 1
        )

    def far(item: dict[str, Any]) -> bool:
        return (
            _number(item.get("center_distance_abs_diff_m"), 0.0) > 600.0
            and _number(item.get("overlap_over_union"), 1.0) <= 0.33
        )

    lenses = {
        "high_precision_core": sorted(
            (item for item in eligible if strong(item)),
            key=lambda item: (
                _number(item.get("center_distance_abs_diff_m"), 1e9),
                -_number(item.get("overlap_over_union"), 0.0),
                item["pair_id"],
            ),
        ),
        "clear_spatial_reject": sorted(
            (item for item in eligible if far(item)),
            key=lambda item: (
                -_number(item.get("center_distance_abs_diff_m"), 0.0),
                _number(item.get("overlap_over_union"), 1.0),
                item["pair_id"],
            ),
        ),
        "decision_boundary": sorted(
            (item for item in eligible if not strong(item) and not far(item)),
            key=lambda item: (
                abs(_number(item.get("center_distance_abs_diff_m"), 1e9) - 200.0)
                + 200.0 * abs(_number(item.get("overlap_over_shorter"), 0.0) - 0.90)
                + 200.0 * abs(_number(item.get("overlap_over_union"), 0.0) - 0.40),
                item["pair_id"],
            ),
        ),
    }

    selected: dict[str, dict[str, Any]] = {}
    lens_counts: dict[str, int] = {}
    for lens, candidates in lenses.items():
        added = 0
        for rank, source in enumerate(candidates, start=1):
            pair_id = source["pair_id"]
            if pair_id in selected:
                continue
            item = copy.deepcopy(source)
            item["selected_by"] = [{"lens": lens, "rank": rank}]
            item["features"] = copy.deepcopy(source)
            selected[pair_id] = item
            added += 1
            if added >= per_lens:
                break
        lens_counts[lens] = added

    queue = []
    for position, item in enumerate(selected.values(), start=1):
        item["queue_position"] = position
        queue.append(item)
    return queue, lens_counts


def build_batch(
    batches_root: Path,
    features_path: Path,
    context: tuple[str, str, str],
    *,
    per_lens: int = 6,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    grouped, conflicts = collect_records(batches_root)
    if conflicts.get(context):
        raise ValueError("El contexto tiene labels humanos conflictivos.")
    records = grouped.get(context, [])
    if not records:
        raise ValueError("El contexto no tiene labels humanos válidos.")
    sessions = collect_sessions(records)
    assignment = assign_sessions(sessions, evaluation_fraction=0.25, seed=20260810)
    evaluation_ids = {
        item["session_id"] for item in sessions
        if assignment[item["session_key"]] == "evaluation"
    }
    raw = json.loads(features_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("episode_pair_features debe ser una lista JSON.")
    features = []
    for source in raw:
        if not isinstance(source, dict):
            continue
        item = dict(source)
        item["pair_id"] = stable_pair_id(item)
        features.append(item)
    queue, lens_counts = select_evaluation_pairs(
        features,
        {record["pair_id"] for record in records},
        evaluation_ids,
        per_lens=per_lens,
    )
    pair_ids = [item["pair_id"] for item in queue]
    digest = hashlib.sha256(json.dumps([*context, pair_ids]).encode("utf-8")).hexdigest()[:10]
    batch_id = f"evaluation-{digest}"
    track, layout, variant = context
    dirname = "--".join(filter(None, (_slug(track), _slug(layout) if layout != track else "", _slug(variant), batch_id)))
    batch_dir = batches_root / dirname
    queue_path = batch_dir / "pair_review_queue.json"
    labels_path = batch_dir / "pair_labels.json"
    now = datetime.now(timezone.utc).isoformat()
    queue_doc = {
        "metadata": {
            "queue_schema_version": "1.1",
            "created_at_utc": now,
            "source_features_path": str(features_path.resolve()),
            "selected_pair_count": len(queue),
            "per_lens": per_lens,
            "selection_policy": "h2_evaluation_stratified_v0.1",
            "evaluation_session_ids": sorted(evaluation_ids),
            "lens_counts": lens_counts,
            "semantics": "Human review only; selection lenses are not labels or matcher decisions.",
        },
        "queue": queue,
    }
    status = {
        "orchestrator_version": "evaluation-review-v0.1",
        "updated_at_utc": now,
        "overall_status": "READY_FOR_HUMAN_REVIEW" if queue else "NO_EVALUATION_CANDIDATES",
        "track": track,
        "track_layout": layout,
        "vehicle_variant": variant,
        "batch_id": batch_id,
        "batch_dir": str(batch_dir.resolve()),
        "steps": {
            "vehicle_context_selection": {
                "status": "PASS",
                "session_count": len(sessions),
                "session_ids": [item["session_id"] for item in sessions],
                "evaluation_session_ids": sorted(evaluation_ids),
            },
            "review_queue": {"status": "READY", "path": str(queue_path.resolve()), "queue_pairs": len(queue)},
            "human_labels": {
                "status": "PENDING", "labels_path": str(labels_path.resolve()),
                "queue_pairs": len(queue), "labeled_pairs": 0,
                "unreviewed_pairs": len(queue), "complete": False,
            },
            "calibration_dataset": {"status": "BLOCKED_BY_LABELS"},
            "evaluation_readiness": {"status": "TARGETED_HUMAN_REVIEW", "evaluation_pairs": 0},
        },
    }
    return batch_dir, queue_doc, status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--batches-root", type=Path, default=Path("calibration_batches"))
    parser.add_argument("--track", required=True)
    parser.add_argument("--track-layout", required=True)
    parser.add_argument("--vehicle-variant", required=True)
    parser.add_argument("--per-lens", type=int, default=6)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    batch_dir, queue, status = build_batch(
        args.batches_root, args.features,
        (args.track, args.track_layout, args.vehicle_variant),
        per_lens=args.per_lens,
    )
    if args.write and queue["queue"]:
        write_documents(batch_dir, queue, status)
    print(f"Evaluation pairs selected: {len(queue['queue'])}")
    print(f"Lenses: {queue['metadata']['lens_counts']}")
    print(f"Output: {batch_dir if queue['queue'] else 'NONE'}")
    print("RESULT: " + ("WRITTEN" if args.write and queue["queue"] else "DRY_RUN"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
