from __future__ import annotations

import copy
import json
from pathlib import Path

from audit_h5_3_local_loss_recurrence import build_audit
from validate_h5_3_local_loss_recurrence import validate


def _case(
    location: str,
    candidate_id: str,
    brake: float = 2.0,
    car: str = "Car A",
) -> dict:
    return {
        "review_id": candidate_id,
        "context": {
            "track": "Interlagos",
            "track_layout": "Interlagos",
            "vehicle_variant": "LMP2_ELMS",
            "car_name_raw": car,
        },
        "location_label": location,
        "human_label": "WITHHELD_BUT_ACTIONABLE",
        "occurrences": [{
            "candidate_id": candidate_id,
            "delta_change_s": 0.25,
            "speed_delta_avg": -7.0,
            "throttle_delta_avg": -2.0,
            "brake_delta_avg": brake,
        }],
        "decision": "LOCAL_POLICY_CANDIDATE",
        "authorization": {"authorized": False},
    }


def _evaluation(tmp_path: Path, cases: list[dict]) -> Path:
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps({
        "metadata": {"status": "SHADOW_LOCAL_LOSS_POLICY_EXPERIMENT"},
        "contract": {"historical_actions_authorized": False},
        "local_policy_candidates": cases,
    }), encoding="utf-8")
    return path


def test_same_zone_pattern_from_two_sources_is_exact_recurrence(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("audit_h5_3_local_loss_recurrence.validate_evaluation", lambda doc: [])
    source = _evaluation(tmp_path, [
        _case("T12", "source-a:cand-1"),
        _case("T12", "source-b:cand-2", car="Car B"),
    ])
    audit = build_audit(source)
    assert audit["summary"]["exact_zone_recurrence_count"] == 1
    assert audit["exact_zone_groups"][0]["independent_source_count"] == 2
    assert audit["exact_zone_groups"][0]["context"] == {
        "track": "Interlagos",
        "track_layout": "Interlagos",
        "vehicle_variant": "LMP2_ELMS",
    }
    assert audit["next_step"] == "REVIEW_RECURRENT_EXACT_ZONE_PATTERNS"
    assert validate(audit) == []


def test_same_pattern_in_different_zones_is_not_zone_recurrence(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("audit_h5_3_local_loss_recurrence.validate_evaluation", lambda doc: [])
    source = _evaluation(tmp_path, [
        _case("T8", "source-a:cand-1"),
        _case("T12", "source-b:cand-2"),
    ])
    audit = build_audit(source)
    assert audit["summary"]["exact_zone_recurrence_count"] == 0
    assert audit["summary"]["cross_zone_pattern_count"] == 1
    assert audit["cross_zone_patterns"][0]["status"] == "CROSS_ZONE_PATTERN_ONLY"


def test_same_zone_different_channel_pattern_remains_separate(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("audit_h5_3_local_loss_recurrence.validate_evaluation", lambda doc: [])
    source = _evaluation(tmp_path, [
        _case("T12", "source-a:cand-1", brake=2.0),
        _case("T12", "source-b:cand-2", brake=-2.0),
    ])
    audit = build_audit(source)
    assert audit["summary"]["exact_zone_group_count"] == 2
    assert audit["summary"]["exact_zone_recurrence_count"] == 0


def test_validator_rejects_promoted_cross_zone_pattern(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("audit_h5_3_local_loss_recurrence.validate_evaluation", lambda doc: [])
    source = _evaluation(tmp_path, [_case("T8", "source-a:cand-1")])
    audit = build_audit(source)
    tampered = copy.deepcopy(audit)
    tampered["contract"]["cross_zone_patterns_do_not_confirm_zone_recurrence"] = False
    errors = validate(tampered)
    assert "document does not match deterministic source reconstruction" in errors
    assert "cross-zone patterns cannot confirm exact-zone recurrence" in errors
