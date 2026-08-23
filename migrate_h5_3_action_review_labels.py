"""Safely carry unchanged H5.3 human labels to an expanded review queue."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from label_h5_3_action_review_queue import (
    LABEL_SCHEMA_VERSION,
    file_sha256,
    item_snapshot,
    load_queue,
    utc_now_iso,
)
from validate_h5_3_action_review_labels import validate


def migrate_labels(
    old_queue_path: Path,
    old_labels_path: Path,
    new_queue_path: Path,
) -> dict[str, Any]:
    old_queue_path = Path(old_queue_path).resolve()
    old_labels_path = Path(old_labels_path).resolve()
    new_queue_path = Path(new_queue_path).resolve()
    old_errors, _, _ = validate(old_queue_path, old_labels_path)
    if old_errors:
        raise ValueError("Old labels are invalid: " + "; ".join(old_errors))

    old_labels = json.loads(old_labels_path.read_text(encoding="utf-8"))
    new_queue = load_queue(new_queue_path)
    new_by_id = {item["review_id"]: item for item in new_queue["review_items"]}
    preserved: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    for record in old_labels["labels"]:
        review_id = record["review_id"]
        new_item = new_by_id.get(review_id)
        if new_item is None:
            dropped.append({"review_id": review_id, "reason": "not_present_in_new_queue"})
            continue
        if record.get("item_snapshot") != item_snapshot(new_item):
            dropped.append({"review_id": review_id, "reason": "snapshot_changed"})
            continue
        preserved.append(copy.deepcopy(record))

    old_metadata = old_labels.get("metadata") or {}
    return {
        "metadata": {
            "label_schema_version": LABEL_SCHEMA_VERSION,
            "created_at_utc": utc_now_iso(),
            "updated_at_utc": utc_now_iso(),
            "source_queue_path": str(new_queue_path),
            "source_queue_sha256": file_sha256(new_queue_path),
            "reviewer": old_metadata.get("reviewer"),
            "historical_actions_authorized": False,
            "semantics": old_metadata.get("semantics"),
            "migration": {
                "source_old_queue_path": str(old_queue_path),
                "source_old_queue_sha256": file_sha256(old_queue_path),
                "source_old_labels_path": str(old_labels_path),
                "source_old_labels_sha256": file_sha256(old_labels_path),
                "preserved_label_count": len(preserved),
                "dropped_label_count": len(dropped),
                "dropped": dropped,
                "rule": "preserve only identical review_id plus exact item_snapshot",
            },
        },
        "labels": preserved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate unchanged H5.3 labels to an expanded queue.")
    parser.add_argument("old_queue_json")
    parser.add_argument("old_labels_json")
    parser.add_argument("new_queue_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    new_queue_path = Path(args.new_queue_json).resolve()
    output_path = Path(args.output).resolve()
    migrated = migrate_labels(
        Path(args.old_queue_json),
        Path(args.old_labels_json),
        new_queue_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    errors, warnings, summary = validate(new_queue_path, output_path)
    if errors:
        raise ValueError("Migrated labels failed validation: " + "; ".join(errors))
    migration = migrated["metadata"]["migration"]
    print("=" * 88)
    print("RACE ENGINEER - H5.3 ACTION REVIEW LABEL MIGRATION v1.0")
    print("=" * 88)
    print(f"Preserved labels: {migration['preserved_label_count']}")
    print(f"Dropped labels: {migration['dropped_label_count']}")
    print(f"Pending in expanded queue: {summary['unreviewed']}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    print(f"Output: {output_path}")
    print("Authority: SHADOW ONLY")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
