# ── Test 24: selector_audit selection_status from canonical ──────────────

from pathlib import Path

import audit_h5_3_real_sessions as _mod
from audit_h5_3_real_sessions import (
    audit_llm_selection,
    audit_session,
    build_multitrack_summary,
)


_STATUS = _mod.__dict__


def _make_h5_3_candidates(cids):
    return {
        "metadata": {"schema_version": "2.0"},
        "candidates": [
            {
                "candidate_id": cid,
                "source": "historical",
                "location_label": f"T{i}",
                "zone": f"Z{i}",
                "authorized_observations": ["current_throttle_lower"],
                "observation_codes": ["current_throttle_lower"],
                "action_codes": ["reduce_throttle"],
                "in_historical_actions": True,
                "in_historical_withheld": False,
            }
            for i, cid in enumerate(cids, start=1)
        ],
    }


def _make_h5_3_section():
    return {
        "metadata": {"schema_version": "1.0"},
        "sections": [
            {
                "zone": "Z1",
                "location_label": "T1",
                "brake_zone": True,
                "brake_meters": [0, 150],
            }
        ],
    }


def _make_actions(cids):
    return {
        "metadata": {"schema_version": "1.0", "pipeline_version": "0.2"},
        "actions": [
            {
                "candidate_id": cid,
                "action_code": "reduce_throttle",
                "source": "historical",
            }
            for cid in cids
        ],
    }


def _make_shadow_pipeline_for_session(cids, session_name):
    return {
        "metadata": {
            "schema_version": "1.0",
            "pipeline_version": "0.1",
            "source_candidates_json": f"data/generated/h5_3/{session_name}/candidates.json",
        },
        "pipeline_artifacts": {
            "eligibility": {
                "summary": {
                    "total_candidates": len(cids),
                    "by_status": {"ELIGIBLE_FOR_SELECTION": len(cids), "WITHHELD": 0},
                },
                "status": "ELIGIBILITY_COMPLETE",
            },
        },
        "validation": {"status": "PASS", "errors": []},
    }


def _tmp_session(tmp_path, name):
    session_dir = tmp_path / "runs" / name
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _write_json(session_dir, rel, data):
    (session_dir / rel).parent.mkdir(parents=True, exist_ok=True)
    (session_dir / rel).write_text(_mod.json.dumps(data), encoding="utf-8")

def test_24_selector_audit_selection_status_canonical():
    """Selector audit: selection_status derived from canonical top-level status."""
    selection = {
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": [
            {"candidate_id": "c1", "authorized_observations": ["current_throttle_lower"]},
        ],
        "llm_selection": {
            "selected_candidates": [
                {"candidate_id": "c1", "observation_codes": ["current_throttle_lower"]}
            ],
        },
    }
    result = audit_llm_selection(selection)
    assert result["selection_status"] == "VALIDATED_HISTORICAL_CANDIDATE_SELECTION"


def test_25_selector_audit_selection_status_shadow_fallback():
    """Selector audit: shadow pipeline fallback uses top-level status."""
    shadow_selection = {
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": [
            {"candidate_id": "c1", "authorized_observations": ["current_throttle_lower"]},
        ],
        "llm_selection": {
            "selected_candidates": [
                {"candidate_id": "c1", "observation_codes": ["current_throttle_lower"]}
            ],
        },
    }
    result = audit_llm_selection(shadow_selection)
    assert result["selection_status"] == "VALIDATED_HISTORICAL_CANDIDATE_SELECTION"


def test_26_selector_audit_selection_status_no_top_level():
    """Selector audit: if no top-level status, falls back to llm_selection.status."""
    shadow_selection = {
        "authorized_candidates": [
            {"candidate_id": "c1", "authorized_observations": ["current_throttle_lower"]},
        ],
        "llm_selection": {
            "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
            "selected_candidates": [
                {"candidate_id": "c1", "observation_codes": ["current_throttle_lower"]}
            ],
        },
    }
    result = audit_llm_selection(shadow_selection)
    assert result["selection_status"] == "VALIDATED_HISTORICAL_CANDIDATE_SELECTION"


def test_27_selector_audit_selection_status_empty():
    """Selector audit: empty selection -> NO_SELECTION."""
    result = audit_llm_selection({})
    assert result["selection_status"] == "NO_SELECTION"


def test_28_validator_pass_rate_not_eligibility_rate():
    """Validator pass rate: must not equal eligibility rate when some eligible but all pass validator.

    Eligibility: 3/4 = 0.75. Validator: 3/3 pass = 1.0. They diverge → formula is correct.
    """
    audits = [
        {"session": "s1", "status": _STATUS["STATUS_AUDIT_COMPLETE"], "identity": {"track": "t1"}, "session_summary": {"total_candidates": 4, "eligible_count": 3, "clean_authorized": 3}, "validator_audit": {"overall": True}},
        {"session": "s2", "status": _STATUS["STATUS_AUDIT_COMPLETE"], "identity": {"track": "t1"}, "session_summary": {"total_candidates": 4, "eligible_count": 3, "clean_authorized": 3}, "validator_audit": {"overall": True}},
        {"session": "s3", "status": _STATUS["STATUS_AUDIT_COMPLETE"], "identity": {"track": "t1"}, "session_summary": {"total_candidates": 4, "eligible_count": 3, "clean_authorized": 3}, "validator_audit": {"overall": True}},
        {"session": "s4", "status": _STATUS["STATUS_AUDIT_COMPLETE"], "identity": {"track": "t1"}, "session_summary": {"total_candidates": 4, "eligible_count": 0, "clean_authorized": 0}, "validator_audit": {"overall": True}},
    ]
    multitrack = build_multitrack_summary(audits)
    # eligibility_rate = 9 / 16 = 0.5625
    # validator_pass_rate = 4 / 4 = 1.0
    expected_eligibility = 9 / 16
    assert abs(multitrack["eligibility_rate"] - expected_eligibility) < 0.001
    assert multitrack["validator_pass_rate"] == 1.0
    assert multitrack["eligibility_rate"] != multitrack["validator_pass_rate"]


def test_29_validator_pass_rate_multisession():
    """Validator pass rate: 3/3 = 1.0 when all 3 sessions pass."""
    audits = []
    for i in range(3):
        audits.append({
            "session": f"session_{i}",
            "status": _STATUS["STATUS_AUDIT_COMPLETE"],
            "identity": {"track": "test_track"},
            "session_summary": {"total_candidates": 3, "clean_authorized": 3},
            "validator_audit": {"overall": True},
        })
    multitrack = build_multitrack_summary(audits)
    assert multitrack["validator_pass_rate"] == 1.0
    assert multitrack["sessions_count"] == 3


def test_30_validator_pass_rate_mixed():
    """Validator pass rate: correct with mixed pass/fail."""
    audits = [
        {"session": "pass_1", "status": _STATUS["STATUS_AUDIT_COMPLETE"], "identity": {"track": "t1"}, "session_summary": {"total_candidates": 1, "clean_authorized": 1}, "validator_audit": {"overall": True}},
        {"session": "pass_2", "status": _STATUS["STATUS_AUDIT_COMPLETE"], "identity": {"track": "t1"}, "session_summary": {"total_candidates": 1, "clean_authorized": 1}, "validator_audit": {"overall": True}},
        {"session": "fail", "status": _STATUS["STATUS_AUDIT_COMPLETE"], "identity": {"track": "t1"}, "session_summary": {"total_candidates": 1, "clean_authorized": 0}, "validator_audit": {"overall": False}},
    ]
    multitrack = build_multitrack_summary(audits)
    assert abs(multitrack["validator_pass_rate"] - (2 / 3)) < 0.001


def test_31_validator_pass_rate_includes_incomplete_sessions():
    """Validator pass rate: INCOMPLETE_AUDIT sessions are excluded."""
    audits = [
        {"session": "s1", "status": _STATUS["STATUS_AUDIT_COMPLETE"], "identity": {"track": "t1"}, "session_summary": {"total_candidates": 1, "clean_authorized": 1}, "validator_audit": {"overall": True}},
        {"session": "s2", "status": _STATUS["STATUS_INCOMPLETE_AUDIT"], "session_summary": {}},
    ]
    multitrack = build_multitrack_summary(audits)
    assert multitrack["sessions_count"] == 1
    assert multitrack["validator_pass_rate"] == 1.0


def test_32_validator_pass_rate_empty_audits():
    """Validator pass rate: empty audits -> 0.0."""
    multitrack = build_multitrack_summary([])
    assert multitrack["validator_pass_rate"] == 0.0


def test_33_selector_audit_empty():
    """Selector audit: empty selection -> no errors, NO_SELECTION."""
    result = audit_llm_selection({})
    assert result["selected_count"] == 0
    assert result["observation_codes_valid"] is True
    assert result["selection_status"] == "NO_SELECTION"
