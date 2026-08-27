"""Incrementally maintain mixed-cue review revisions without inventing labels."""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any

from label_mixed_cue_review_queue import file_sha256, load_labels
from prepare_mixed_cue_review_queue import build_queue
from shadow_split_mixed_cue_plan import current_validated_debrief_paths, load_json
from validate_mixed_cue_review_labels import validate


VERSION = "0.1"
REVISION_RE = re.compile(r"queue_v(?P<number>\d{3})\.json$")


def _latest_revision(output_dir: Path) -> tuple[int, Path, Path] | None:
    candidates: list[tuple[int, Path]] = []
    for path in output_dir.glob("queue_v*.json"):
        match = REVISION_RE.search(path.name)
        if match:
            candidates.append((int(match.group("number")), path))
    if not candidates:
        return None
    revision, queue_path = max(candidates, key=lambda value: value[0])
    return revision, queue_path, output_dir / f"labels_v{revision:03d}.json"


def _write_queue(path: Path, queue: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _migrate_labels(
    old_labels: dict[str, Any] | None,
    new_queue: dict[str, Any],
    new_queue_path: Path,
    new_labels_path: Path,
) -> tuple[dict[str, Any], int]:
    new_labels = load_labels(new_labels_path, new_queue_path)
    exact_items = {item["review_id"]: item for item in new_queue["review_items"]}
    migrated = 0
    for record in (old_labels or {}).get("labels") or []:
        review_id = record.get("review_id")
        current = exact_items.get(review_id)
        if current is None or record.get("item_snapshot") != current:
            continue
        new_labels["labels"].append(copy.deepcopy(record))
        migrated += 1
    new_labels["metadata"]["migration"] = {
        "policy": "exact_review_id_and_item_snapshot_only",
        "migrated_label_count": migrated,
        "labels_invented": 0,
    }
    new_labels_path.write_text(
        json.dumps(new_labels, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return new_labels, migrated


def maintain(
    runs_dir: Path,
    output_dir: Path,
    *,
    seed_queue_path: Path | None = None,
    seed_labels_path: Path | None = None,
) -> dict[str, Any]:
    paths = current_validated_debrief_paths(runs_dir)
    current = build_queue(paths)
    latest = _latest_revision(output_dir)
    old_queue: dict[str, Any] | None = None
    old_labels: dict[str, Any] | None = None
    previous_revision = 0

    if latest is not None:
        previous_revision, old_queue_path, old_labels_path = latest
        old_queue = load_json(old_queue_path)
        if old_labels_path.is_file():
            old_labels = load_json(old_labels_path)
    elif seed_queue_path and seed_queue_path.is_file():
        old_queue = load_json(seed_queue_path)
        if seed_labels_path and seed_labels_path.is_file():
            errors, _, _ = validate(seed_queue_path, seed_labels_path)
            if errors:
                raise ValueError("Seed labels invalid: " + "; ".join(errors))
            old_labels = load_json(seed_labels_path)

    if (
        latest is not None
        and old_queue is not None
        and old_queue.get("review_items") == current["review_items"]
    ):
        reviewed = len((old_labels or {}).get("labels") or [])
        return {
            "version": VERSION,
            "status": "UP_TO_DATE",
            "revision": previous_revision,
            "review_items": len(current["review_items"]),
            "reviewed": reviewed,
            "pending": len(current["review_items"]) - reviewed,
            "new_labels_invented": 0,
        }

    revision = previous_revision + 1
    queue_path = output_dir / f"queue_v{revision:03d}.json"
    labels_path = output_dir / f"labels_v{revision:03d}.json"
    _write_queue(queue_path, current)
    labels, migrated = _migrate_labels(
        old_labels,
        current,
        queue_path,
        labels_path,
    )
    pending = len(current["review_items"]) - len(labels["labels"])
    return {
        "version": VERSION,
        "status": "WAITING_FOR_HUMAN_REVIEW" if pending else "REVIEW_COMPLETE",
        "revision": revision,
        "queue_path": str(queue_path.resolve()),
        "labels_path": str(labels_path.resolve()),
        "review_items": len(current["review_items"]),
        "migrated_labels": migrated,
        "reviewed": len(labels["labels"]),
        "pending": pending,
        "new_labels_invented": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain mixed-cue human review revisions.")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/generated/runs"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/generated/diagnostics/mixed_cue_reviews"),
    )
    parser.add_argument("--seed-queue", type=Path)
    parser.add_argument("--seed-labels", type=Path)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()
    result = maintain(
        args.runs_dir,
        args.output_dir,
        seed_queue_path=args.seed_queue,
        seed_labels_path=args.seed_labels,
    )
    if args.state:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print("=" * 88)
    print("RACE ENGINEER - MIXED CUE REVIEW MAINTENANCE v0.1")
    print("=" * 88)
    for key, value in result.items():
        print(f"{key}: {value}")
    print("Authority: SHADOW ONLY — no labels invented")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
