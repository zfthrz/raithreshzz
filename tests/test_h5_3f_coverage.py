"""Tests for H5.3f deterministic coverage classifier.

Covers synthetic cases for each classification state (SATISFIED, MISSING,
BLOCKING) plus integration against the real v39 review when available.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from assess_h5_3_promotion_v0_2 import (
    assess_evidence,
    EVIDENCE_READY,
    EVIDENCE_INCOMPLETE,
)
from audit_h5_3f_coverage import (
    classify_evidence,
    SATISFIED,
    MISSING,
    BLOCKING,
    SCHEMA_VERSION,
    AUTHORITY,
)
from validate_h5_3f_coverage import validate as validate_snapshot


# ─────────────────────── fixture helpers ───────────────────────


def _make_queue(
    tracks: list[str],
    signs: list[str],
    actions: list[str],
    decisions: list[str] | None = None,
) -> dict:
    """Build a minimal queue dict with *tracks* as review context."""
    decisions = decisions or ["AUTHORIZED_SHADOW_ACTION"] * len(tracks)
    items = []
    for i, track in enumerate(tracks):
        items.append({
            "review_id": f"item_{i}",
            "decision": decisions[i % len(decisions)],
            "context": {"track": track},
            "location_label": "T1",
            "delta_sign": signs[i % len(signs)] if signs else "current_slower",
            "actions": actions if actions else [],
            "actions_text": " ".join(actions),
            "reason": "insufficient_action_context" if decisions[i % len(decisions)] == "WITHHELD" else None,
            "observation_codes": ["current_throttle_higher"] if decisions[i % len(decisions)] == "WITHHELD" else [],
            "occurrence_count": 1,
        })
    return {
        "metadata": {
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        },
        "review_items": items,
    }


def _make_labels(
    review_ids: list[str],
    decision_labels: dict[str, str] | None = None,
) -> dict:
    """Build labels dict.  *decision_labels* maps decision → expected human_label.

    Default mapping:
      AUTHORIZED_SHADOW_ACTION → ACTION_USEFUL
      WITHHELD                 → CORRECTLY_WITHHELD
    """
    default = {
        "AUTHORIZED_SHADOW_ACTION": "ACTION_USEFUL",
        "WITHHELD": "CORRECTLY_WITHHELD",
    }
    decision_labels = decision_labels or default

    labels = []
    for rid in review_ids:
        labels.append({
            "review_id": rid,
            "human_label": decision_labels.get("ACTION_USEFUL"),
        })
    return {"labels": labels}


def _make_structural(verdict: str = "PROMOTION_READY") -> dict:
    return {"verdict": verdict}


def _make_complete_inputs():
    """Build inputs that satisfy the gate: 4 tracks, 2 signs, all actions,
    single-action branches, isolated withhold, all labels affirmative."""
    tracks = [
        "Fuji Speedway",
        "Autodromo Enzo e Dino Ferrari",
        "Autódromo José Carlos Pace",
        "Autodromo Nazionale Monza",
    ]
    signs = ["current_slower", "current_faster"]
    actions_all = ["increase_brake", "increase_throttle", "reduce_brake", "reduce_throttle"]
    # Build items with all 4 tracks, both signs, all action codes,
    # single-action branches, and isolated reduce_throttle_withheld case.
    items = [
        {
            "review_id": "a1",
            "decision": "AUTHORIZED_SHADOW_ACTION",
            "context": {"track": "Fuji Speedway"},
            "location_label": "T1",
            "delta_sign": "current_slower",
            "actions": ["increase_throttle"],
            "actions_text": "increase_throttle",
            "reason": None,
            "observation_codes": [],
            "occurrence_count": 1,
        },
        {
            "review_id": "a2",
            "decision": "AUTHORIZED_SHADOW_ACTION",
            "context": {"track": "Autodromo Enzo e Dino Ferrari"},
            "location_label": "T1",
            "delta_sign": "current_slower",
            "actions": ["increase_brake"],
            "actions_text": "increase_brake",
            "reason": None,
            "observation_codes": [],
            "occurrence_count": 1,
        },
        {
            "review_id": "a3",
            "decision": "AUTHORIZED_SHADOW_ACTION",
            "context": {"track": "Autódromo José Carlos Pace"},
            "location_label": "T1",
            "delta_sign": "current_faster",
            "actions": ["reduce_brake"],
            "actions_text": "reduce_brake",
            "reason": None,
            "observation_codes": [],
            "occurrence_count": 1,
        },
        {
            "review_id": "a4",
            "decision": "AUTHORIZED_SHADOW_ACTION",
            "context": {"track": "Autodromo Nazionale Monza"},
            "location_label": "T1",
            "delta_sign": "current_slower",
            "actions": ["reduce_throttle", "reduce_brake"],
            "actions_text": "reduce_brake reduce_throttle",
            "reason": None,
            "observation_codes": [],
            "occurrence_count": 1,
        },
        {
            "review_id": "w1",
            "decision": "WITHHELD",
            "context": {"track": "Autodromo Enzo e Dino Ferrari"},
            "location_label": "T1",
            "delta_sign": "current_slower",
            "actions": [],
            "actions_text": "",
            "reason": "insufficient_action_context",
            "observation_codes": ["current_throttle_higher"],
            "occurrence_count": 1,
        },
        {
            "review_id": "w2",
            "decision": "WITHHELD",
            "context": {"track": "Autodromo Nazionale Monza"},
            "location_label": "T1",
            "delta_sign": "current_faster",
            "actions": [],
            "actions_text": "",
            "reason": "current_lap_faster_no_actions",
            "observation_codes": [],
            "occurrence_count": 1,
        },
    ]
    labels = [
        {"review_id": "a1", "human_label": "ACTION_USEFUL"},
        {"review_id": "a2", "human_label": "ACTION_USEFUL"},
        {"review_id": "a3", "human_label": "ACTION_USEFUL"},
        {"review_id": "a4", "human_label": "ACTION_USEFUL"},
        {"review_id": "w1", "human_label": "CORRECTLY_WITHHELD"},
        {"review_id": "w2", "human_label": "CORRECTLY_WITHHELD"},
    ]
    structural = {"verdict": "PROMOTION_READY"}
    queue = {
        "metadata": {
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        },
        "review_items": items,
    }
    labels_data = {"labels": labels}
    return structural, queue, labels_data


# ─────────────────────── SATISFIED synthetic case ───────────────────────


def test_all_satisfied_tracks_and_signs():
    """When all manifest requirements are present → all SATISFIED."""
    structural, queue, labels = _make_complete_inputs()
    snapshot = classify_evidence(queue, labels, structural)

    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["authority"] == AUTHORITY
    # All 4 tracks reviewed → SATISFIED
    assert snapshot["requirements"]["required_tracks"]["status"] == SATISFIED
    assert snapshot["requirements"]["required_delta_signs"]["status"] == SATISFIED
    assert snapshot["requirements"]["required_action_codes"]["status"] == SATISFIED
    assert snapshot["requirements"]["required_authorized_single_actions"]["status"] == SATISFIED
    assert snapshot["requirements"]["affirmative_labels"]["status"] == SATISFIED
    assert snapshot["next_priority"] is None


# ─────────────────────── MISSING synthetic case ───────────────────────


def test_missing_track_is_missing():
    """When one required track is absent → required_tracks = MISSING."""
    structural, queue, labels = _make_complete_inputs()
    # Remove Monza item (a4) and its label
    queue["review_items"] = [
        item for item in queue["review_items"]
        if item["review_id"] not in ("a4", "w2")
    ]
    labels["labels"] = [
        lb for lb in labels["labels"]
        if lb["review_id"] not in ("a4", "w2")
    ]

    snapshot = classify_evidence(queue, labels, structural)

    assert snapshot["requirements"]["required_tracks"]["status"] == MISSING
    assert "missing" in snapshot["requirements"]["required_tracks"]["detail"].lower()


def test_missing_delta_sign_is_missing():
    """When current_faster is absent → required_delta_signs = MISSING."""
    structural, queue, labels = _make_complete_inputs()
    # Remove w2 (current_faster) and a3 (also current_faster)
    queue["review_items"] = [
        item for item in queue["review_items"]
        if item["review_id"] not in ("a3", "w2")
    ]
    labels["labels"] = [
        lb for lb in labels["labels"]
        if lb["review_id"] not in ("a3", "w2")
    ]

    snapshot = classify_evidence(queue, labels, structural)

    assert snapshot["requirements"]["required_delta_signs"]["status"] == MISSING


def test_missing_action_code_is_missing():
    """When reduce_throttle is absent → required_action_codes = MISSING."""
    structural, queue, labels = _make_complete_inputs()
    # Remove a4 (has reduce_throttle) and its label
    queue["review_items"] = [
        item for item in queue["review_items"]
        if item["review_id"] != "a4"
    ]
    labels["labels"] = [
        lb for lb in labels["labels"]
        if lb["review_id"] != "a4"
    ]

    snapshot = classify_evidence(queue, labels, structural)

    assert snapshot["requirements"]["required_action_codes"]["status"] == MISSING


def test_missing_single_action_branch_is_missing():
    """When [increase_throttle] is absent → single_actions = MISSING."""
    structural, queue, labels = _make_complete_inputs()
    # Remove a1 (single increase_throttle)
    queue["review_items"] = [
        item for item in queue["review_items"]
        if item["review_id"] != "a1"
    ]
    labels["labels"] = [
        lb for lb in labels["labels"]
        if lb["review_id"] != "a1"
    ]

    snapshot = classify_evidence(queue, labels, structural)

    assert snapshot["requirements"]["required_authorized_single_actions"]["status"] == MISSING


# ─────────────────────── BLOCKING synthetic case ───────────────────────


def test_nonaffirmative_blocks_when_limit_none():
    """When max_non_affirmative_labels is None and count > 0 → BLOCKING."""
    structural, queue, labels = _make_complete_inputs()
    # Add a non-affirmative label
    labels["labels"].append({
        "review_id": "a1",
        "human_label": "AMBIGUOUS",
    })

    snapshot = classify_evidence(queue, labels, structural)

    assert snapshot["requirements"]["affirmative_labels"]["status"] == BLOCKING


# ─────────────────────── next_priority logic ───────────────────────


def test_next_priority_is_first_missing():
    """next_priority points to the first MISSING requirement."""
    structural, queue, labels = _make_complete_inputs()
    # Remove Monza + current_faster to create MISSING
    queue["review_items"] = [
        item for item in queue["review_items"]
        if item["review_id"] not in ("a4", "w2")
    ]
    labels["labels"] = [
        lb for lb in labels["labels"]
        if lb["review_id"] not in ("a4", "w2")
    ]

    snapshot = classify_evidence(queue, labels, structural)

    assert snapshot["next_priority"] is not None
    assert "required_tracks" in snapshot["next_priority"]


def test_next_priority_is_none_when_all_satisfied():
    """When all requirements are SATISFIED → next_priority = None."""
    structural, queue, labels = _make_complete_inputs()
    snapshot = classify_evidence(queue, labels, structural)

    assert snapshot["next_priority"] is None


# ─────────────────────── validator integration ───────────────────────


def _write_json(path: Path, data: dict) -> None:
    """Write JSON to *path* (Python 3.14-compatible, UTF-8 explicit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def test_validator_passes_valid_snapshot():
    """A correctly-formed snapshot should pass validation."""
    structural, queue, labels = _make_complete_inputs()
    snapshot = classify_evidence(queue, labels, structural)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        snapshot_path = tmppath / "snapshot.json"
        queue_path = tmppath / "queue.json"
        labels_path = tmppath / "labels.json"

        _write_json(snapshot_path, snapshot)
        _write_json(queue_path, queue)
        _write_json(labels_path, labels)

        errors = validate_snapshot(snapshot_path, queue_path, labels_path)

    assert errors == [], f"Unexpected validation errors: {errors}"


def test_validator_rejects_wrong_schema():
    """A snapshot with wrong schema_version should fail validation."""
    structural, queue, labels = _make_complete_inputs()
    snapshot = classify_evidence(queue, labels, structural)
    snapshot["schema_version"] = "99.0"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        snapshot_path = tmppath / "snapshot.json"
        queue_path = tmppath / "queue.json"
        labels_path = tmppath / "labels.json"

        _write_json(snapshot_path, snapshot)
        _write_json(queue_path, queue)
        _write_json(labels_path, labels)

        errors = validate_snapshot(snapshot_path, queue_path, labels_path)

    assert any("schema_version" in err for err in errors)


def test_validator_rejects_wrong_authority():
    """A snapshot with wrong authority should fail validation."""
    structural, queue, labels = _make_complete_inputs()
    snapshot = classify_evidence(queue, labels, structural)
    snapshot["authority"] = "AUTHORITATIVE"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        snapshot_path = tmppath / "snapshot.json"
        queue_path = tmppath / "queue.json"
        labels_path = tmppath / "labels.json"

        _write_json(snapshot_path, snapshot)
        _write_json(queue_path, queue)
        _write_json(labels_path, labels)

        errors = validate_snapshot(snapshot_path, queue_path, labels_path)

    assert any("authority" in err for err in errors)


def test_validator_rejects_gate_verdict_contradiction():
    """A snapshot whose gate_verdict contradicts the real gate should fail."""
    structural, queue, labels = _make_complete_inputs()
    snapshot = classify_evidence(queue, labels, structural)
    # Override gate_verdict to something different from what assess_evidence computed
    snapshot["gate_verdict"] = "GATE_CHANGED"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        snapshot_path = tmppath / "snapshot.json"
        queue_path = tmppath / "queue.json"
        labels_path = tmppath / "labels.json"

        _write_json(snapshot_path, snapshot)
        _write_json(queue_path, queue)
        _write_json(labels_path, labels)

        errors = validate_snapshot(snapshot_path, queue_path, labels_path)

    assert any("contradiction" in err.lower() for err in errors)


# ─────────────────────── determinism check ───────────────────────


def test_snapshot_deterministic_except_timestamp():
    """Running the classifier twice with the same inputs should produce
    identical snapshots except for generated_at_utc."""
    structural, queue, labels = _make_complete_inputs()

    s1 = classify_evidence(queue, labels, structural)
    s2 = classify_evidence(queue, labels, structural)

    # Remove timestamps
    s1.pop("generated_at_utc")
    s2.pop("generated_at_utc")

    assert s1 == s2


# ─────────────────────── real v39 case (if available) ───────────────────────


@pytest.fixture
def v39_paths():
    """Return v39 queue/labels paths if available on disk."""
    queue_path = Path("data/generated/h5_3/action_review_queue_v39.json")
    labels_path = Path("data/generated/h5_3/action_review_labels_v39.json")
    if not queue_path.is_file() or not labels_path.is_file():
        pytest.skip("v39 files not available")
    return queue_path, labels_path


def test_v39_real_revision_classification(v39_paths):
    """Run the classifier against the real v39 review.  Should not raise."""
    queue_path, labels_path = v39_paths
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    structural = _make_structural()

    snapshot = classify_evidence(queue, labels, structural)

    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["authority"] == AUTHORITY
    assert "requirements" in snapshot
    assert len(snapshot["requirements"]) == 9


def test_v39_snapshot_validates(v39_paths):
    """The v39 classification snapshot should pass the validator."""
    queue_path, labels_path = v39_paths
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    structural = _make_structural()

    snapshot = classify_evidence(queue, labels, structural)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        snapshot_path = tmppath / "snapshot.json"
        queue_path_tmp = tmppath / "queue.json"
        labels_path_tmp = tmppath / "labels.json"

        _write_json(snapshot_path, snapshot)
        _write_json(queue_path_tmp, queue)
        _write_json(labels_path_tmp, labels)

        errors = validate_snapshot(snapshot_path, queue_path_tmp, labels_path_tmp)

    assert errors == [], f"Unexpected validation errors: {errors}"


def test_v39_gate_verdict_consistent(v39_paths):
    """The snapshot's gate_verdict must match what assess_evidence computes."""
    queue_path, labels_path = v39_paths
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    structural = _make_structural()

    snapshot = classify_evidence(queue, labels, structural)

    real_report = assess_evidence(structural, queue, labels)
    assert snapshot["gate_verdict"] == real_report["verdict"]
