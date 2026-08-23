from __future__ import annotations

import json
from pathlib import Path

from label_h5_3_action_review_queue import load_labels, save_labels, upsert_label
from migrate_h5_3_action_review_labels import migrate_labels


def _item(review_id: str, location: str = "T1") -> dict:
    return {
        "review_id": review_id,
        "decision": "AUTHORIZED_SHADOW_ACTION",
        "context": {"track": "Test Track"},
        "location_label": location,
        "delta_sign": "current_slower",
        "actions": ["reduce_brake"],
        "actions_text": ["reducir freno"],
        "reason": None,
        "observation_codes": ["current_brake_higher"],
        "occurrence_count": 1,
        "occurrences": [],
    }


def _write_queue(path: Path, items: list[dict]) -> Path:
    path.write_text(json.dumps({"review_items": items}), encoding="utf-8")
    return path


def test_migration_preserves_identical_labels_and_leaves_new_pending(tmp_path: Path):
    old_queue = _write_queue(tmp_path / "old_queue.json", [_item("same")])
    old_labels_path = tmp_path / "old_labels.json"
    old_labels = load_labels(old_labels_path, old_queue, "reviewer")
    upsert_label(old_labels, _item("same"), "ACTION_USEFUL", "confirmed")
    save_labels(old_labels_path, old_labels)
    new_queue = _write_queue(tmp_path / "new_queue.json", [_item("same"), _item("new", "T2")])

    migrated = migrate_labels(old_queue, old_labels_path, new_queue)

    assert [record["review_id"] for record in migrated["labels"]] == ["same"]
    assert migrated["metadata"]["migration"]["preserved_label_count"] == 1
    assert migrated["metadata"]["migration"]["dropped_label_count"] == 0
    assert migrated["metadata"]["source_queue_sha256"]


def test_migration_drops_label_when_snapshot_changed(tmp_path: Path):
    old_item = _item("changed")
    old_queue = _write_queue(tmp_path / "old_queue.json", [old_item])
    old_labels_path = tmp_path / "old_labels.json"
    old_labels = load_labels(old_labels_path, old_queue, "reviewer")
    upsert_label(old_labels, old_item, "ACTION_USEFUL", "confirmed")
    save_labels(old_labels_path, old_labels)
    new_queue = _write_queue(tmp_path / "new_queue.json", [_item("changed", "T3")])

    migrated = migrate_labels(old_queue, old_labels_path, new_queue)

    assert migrated["labels"] == []
    assert migrated["metadata"]["migration"]["dropped"] == [
        {"review_id": "changed", "reason": "snapshot_changed"}
    ]
