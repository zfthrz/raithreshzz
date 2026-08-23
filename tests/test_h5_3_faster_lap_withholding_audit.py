from __future__ import annotations

import copy
import json
from pathlib import Path

from audit_h5_3_faster_lap_withholding import build_audit, file_sha256
from historical_action_policy import build_action_candidates
from label_h5_3_action_review_queue import item_snapshot
from prepare_h5_3_action_review_queue import build_queue
from validate_h5_3_faster_lap_withholding import validate


def _sources(tmp_path: Path) -> tuple[Path, Path]:
    session = tmp_path / "session"
    session.mkdir()
    selection_path = session / "candidate_selection.json"
    candidate = {
        "candidate_id": "fast:candidate",
        "context": {"track": "Test", "track_layout": "Test", "vehicle_variant": "LMP2_ELMS"},
        "delta_sign": "current_faster",
        "location_label": "T1 - Test",
        "start_distance_m": 100.0,
        "end_distance_m": 150.0,
        "delta_change_s": 0.25,
        "speed_delta_avg": -4.5,
        "throttle_delta_avg": -7.0,
        "brake_delta_avg": 2.0,
        "authorized_observations": ["time_loss", "current_speed_lower", "current_throttle_lower", "current_brake_higher"],
    }
    selection = {
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": [candidate],
        "llm_selection": {"selected_candidates": [{
            "candidate_id": candidate["candidate_id"],
            "significance": "primary",
            "observation_codes": candidate["authorized_observations"],
        }]},
    }
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    actions_path = session / "historical_actions.json"
    actions_path.write_text(json.dumps(build_action_candidates(selection_path)), encoding="utf-8")
    queue_path = tmp_path / "queue.json"
    queue = build_queue([actions_path], input_root=tmp_path)
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    item = queue["review_items"][0]
    labels_path = tmp_path / "labels.json"
    labels = {
        "metadata": {
            "label_schema_version": "1.0",
            "source_queue_path": str(queue_path.resolve()),
            "source_queue_sha256": file_sha256(queue_path),
            "historical_actions_authorized": False,
        },
        "labels": [{
            "review_id": item["review_id"],
            "human_label": "WITHHELD_BUT_ACTIONABLE",
            "review_notes": "local loss remains useful",
            "reviewed_at_utc": "2026-08-22T00:00:00+00:00",
            "item_snapshot": item_snapshot(item),
        }],
    }
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    return queue_path, labels_path


def test_audit_reconstructs_quantitative_current_faster_evidence(tmp_path: Path):
    queue_path, labels_path = _sources(tmp_path)
    audit = build_audit(queue_path, labels_path)
    assert audit["summary"]["reviewed_current_faster_withheld_count"] == 1
    assert audit["summary"]["withheld_but_actionable_count"] == 1
    case = audit["cases"][0]
    assert case["human_label"] == "WITHHELD_BUT_ACTIONABLE"
    assert case["evidence_status"] == "QUANTITATIVE_EVIDENCE_AVAILABLE"
    assert case["occurrences"][0]["delta_change_s"] == 0.25
    assert case["occurrences"][0]["brake_delta_avg"] == 2.0
    assert audit["contract"]["historical_actions_authorized"] is False
    assert validate(audit) == []


def test_validator_rejects_tampered_quantitative_evidence(tmp_path: Path):
    queue_path, labels_path = _sources(tmp_path)
    audit = build_audit(queue_path, labels_path)
    tampered = copy.deepcopy(audit)
    tampered["cases"][0]["occurrences"][0]["delta_change_s"] = 9.99
    assert "document does not match deterministic source reconstruction" in validate(tampered)


def test_audit_excludes_current_slower_items(tmp_path: Path):
    queue_path, labels_path = _sources(tmp_path)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["review_items"][0]["delta_sign"] = "current_slower"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    labels["metadata"]["source_queue_sha256"] = file_sha256(queue_path)
    labels["labels"][0]["item_snapshot"] = item_snapshot(queue["review_items"][0])
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    audit = build_audit(queue_path, labels_path)
    assert audit["cases"] == []
    assert audit["summary"]["reviewed_current_faster_withheld_count"] == 0
