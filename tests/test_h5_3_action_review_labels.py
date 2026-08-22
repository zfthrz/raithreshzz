from __future__ import annotations

import json
from pathlib import Path

import pytest

from label_h5_3_action_review_queue import (
    allowed_labels,
    item_snapshot,
    load_labels,
    pending_items,
    save_labels,
    upsert_label,
)
from validate_h5_3_action_review_labels import validate


def _item(review_id: str, decision: str) -> dict:
    return {
        "review_id": review_id,
        "decision": decision,
        "context": {"track": "Test Track", "track_layout": "Layout", "vehicle_variant": "LMP2"},
        "location_label": "T1",
        "delta_sign": "current_slower",
        "actions": ["reduce_brake"] if decision == "AUTHORIZED_SHADOW_ACTION" else [],
        "actions_text": ["reducir freno"] if decision == "AUTHORIZED_SHADOW_ACTION" else [],
        "reason": None if decision == "AUTHORIZED_SHADOW_ACTION" else "insufficient_action_context",
        "observation_codes": ["current_brake_higher"],
        "occurrence_count": 1,
        "occurrences": [],
    }


def _write_queue(tmp_path: Path) -> tuple[Path, dict]:
    queue = {
        "metadata": {"status": "H5_3_ACTION_REVIEW_QUEUE_READY"},
        "review_items": [
            _item("action-1", "AUTHORIZED_SHADOW_ACTION"),
            _item("withheld-1", "WITHHELD"),
        ],
    }
    path = tmp_path / "queue.json"
    path.write_text(json.dumps(queue), encoding="utf-8")
    return path, queue


def test_allowed_labels_are_decision_specific():
    assert "ACTION_USEFUL" in allowed_labels("AUTHORIZED_SHADOW_ACTION")
    assert "ACTION_USEFUL" not in allowed_labels("WITHHELD")
    assert "CORRECTLY_WITHHELD" in allowed_labels("WITHHELD")
    assert "CORRECTLY_WITHHELD" not in allowed_labels("AUTHORIZED_SHADOW_ACTION")


def test_labels_save_resume_and_validate(tmp_path: Path):
    queue_path, queue = _write_queue(tmp_path)
    labels_path = tmp_path / "labels.json"
    labels = load_labels(labels_path, queue_path, "reviewer")
    upsert_label(labels, queue["review_items"][0], "ACTION_USEFUL", "clear cue")
    save_labels(labels_path, labels)

    resumed = load_labels(labels_path, queue_path, None)
    assert [item["review_id"] for item in pending_items(queue, resumed)] == ["withheld-1"]
    errors, warnings, summary = validate(queue_path, labels_path)
    assert errors == []
    assert warnings == ["Quedan 1 casos sin revisar."]
    assert summary["reviewed"] == 1


def test_upsert_rejects_label_for_other_decision(tmp_path: Path):
    queue_path, queue = _write_queue(tmp_path)
    labels = load_labels(tmp_path / "labels.json", queue_path, None)
    with pytest.raises(ValueError, match="no es válido"):
        upsert_label(labels, queue["review_items"][1], "ACTION_USEFUL", "")


def test_validator_rejects_tampered_snapshot(tmp_path: Path):
    queue_path, queue = _write_queue(tmp_path)
    labels_path = tmp_path / "labels.json"
    labels = load_labels(labels_path, queue_path, None)
    upsert_label(labels, queue["review_items"][1], "CORRECTLY_WITHHELD", "")
    labels["labels"][0]["item_snapshot"]["reason"] = "tampered"
    save_labels(labels_path, labels)

    errors, _, _ = validate(queue_path, labels_path)
    assert any("item_snapshot no coincide" in error for error in errors)


def test_validator_warns_on_unsafe_and_policy_review(tmp_path: Path):
    queue_path, queue = _write_queue(tmp_path)
    labels_path = tmp_path / "labels.json"
    labels = load_labels(labels_path, queue_path, None)
    upsert_label(labels, queue["review_items"][0], "UNSAFE_ACTION", "unsafe")
    upsert_label(labels, queue["review_items"][1], "WITHHELD_BUT_ACTIONABLE", "missing cue")
    save_labels(labels_path, labels)

    errors, warnings, summary = validate(queue_path, labels_path)
    assert errors == []
    assert summary["unreviewed"] == 0
    assert any("UNSAFE_ACTION" in warning for warning in warnings)
    assert any("WITHHELD_BUT_ACTIONABLE" in warning for warning in warnings)
    assert labels["labels"][0]["item_snapshot"] == item_snapshot(queue["review_items"][0])
