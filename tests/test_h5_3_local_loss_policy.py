from __future__ import annotations

import copy
import json
from pathlib import Path

from evaluate_h5_3_local_loss_policy import build_evaluation
from validate_h5_3_local_loss_policy import validate


def _audit(tmp_path: Path, *, label: str = "WITHHELD_BUT_ACTIONABLE", delta: float = 0.294) -> Path:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    audit_path = tmp_path / "audit.json"
    document = {
        "metadata": {
            "schema_version": "1.0",
            "audit_version": "0.1",
            "status": "SHADOW_FASTER_LAP_WITHHOLDING_REVIEW",
            "source_queue_json": str(source),
            "source_queue_sha256": "unused",
            "source_labels_json": str(source),
            "source_labels_sha256": "unused",
        },
        "contract": {
            "python_owns_quantitative_evidence": True,
            "human_labels_are_observational_evidence": True,
            "policy_changed": False,
            "automatic_action_authorization": False,
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        },
        "summary": {},
        "cases": [{
            "review_id": "review-1",
            "context": {"track": "Test"},
            "location_label": "T1",
            "human_label": label,
            "occurrences": [{
                "candidate_id": "candidate-1",
                "delta_change_s": delta,
                "start_distance_m": 100.0,
                "end_distance_m": 150.0,
                "speed_delta_avg": -8.8,
                "throttle_delta_avg": -1.3,
                "brake_delta_avg": 2.7,
            }],
        }],
        "next_step": "REVIEW_LOCAL_ACTIONABILITY_POLICY_IN_SHADOW",
    }
    audit_path.write_text(json.dumps(document), encoding="utf-8")
    return audit_path


def test_actionable_review_with_complete_large_local_loss_becomes_shadow_candidate(
    tmp_path: Path, monkeypatch,
):
    audit_path = _audit(tmp_path)
    monkeypatch.setattr("evaluate_h5_3_local_loss_policy.validate_audit", lambda document: [])
    result = build_evaluation(audit_path)
    assert result["summary"] == {
        "source_case_count": 1,
        "local_policy_candidate_count": 1,
        "withheld_count": 0,
    }
    candidate = result["local_policy_candidates"][0]
    assert candidate["decision"] == "LOCAL_POLICY_CANDIDATE"
    assert candidate["authorization"]["authorized"] is False
    assert result["contract"]["historical_actions_authorized"] is False


def test_ambiguous_or_small_loss_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("evaluate_h5_3_local_loss_policy.validate_audit", lambda document: [])
    ambiguous = build_evaluation(_audit(tmp_path, label="AMBIGUOUS"))
    assert ambiguous["summary"]["local_policy_candidate_count"] == 0
    assert ambiguous["withheld"][0]["failed_gates"] == [
        "human_withheld_but_actionable"
    ]
    small_dir = tmp_path / "small"
    small_dir.mkdir()
    small = build_evaluation(_audit(small_dir, delta=0.199))
    assert small["summary"]["local_policy_candidate_count"] == 0
    assert small["withheld"][0]["gates"][
        "all_occurrences_pass_quantitative_gates"
    ] is False


def test_validator_rejects_authority_or_evidence_tampering(tmp_path: Path, monkeypatch):
    audit_path = _audit(tmp_path)
    monkeypatch.setattr("evaluate_h5_3_local_loss_policy.validate_audit", lambda document: [])
    result = build_evaluation(audit_path)
    assert validate(result) == []
    tampered = copy.deepcopy(result)
    tampered["contract"]["historical_actions_authorized"] = True
    errors = validate(tampered)
    assert "document does not match deterministic source reconstruction" in errors
    assert "historical actions must remain unauthorized" in errors
