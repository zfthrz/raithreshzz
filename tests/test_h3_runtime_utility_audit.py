import json
from pathlib import Path

from audit_h3_runtime_utility import audit_h3_runtime_utility, write_report


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _h3_document(*, projected: bool = False) -> dict:
    return {
        "metadata": {
            "status": (
                "MATCHED_CALIBRATED_PROJECTION"
                if projected
                else "MATCHED_PATTERN_MEMBERSHIP"
            ),
            "session_id": 7,
            "context": {
                "track": "Test Track",
                "track_layout": "Test Layout",
                "vehicle_variant": "GT3",
            },
            "observational_only": True,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
        },
        "summary": {},
        "matched_patterns": [] if projected else [
            {
                "pattern_id": "pat_1",
                "state": "persistent_pattern",
                "match_basis": "exact_pattern_member_identity",
                "current_session_member": {"episode_pk": 70},
            }
        ],
        "projected_pattern_matches": [
            {
                "pattern_id": "pat_2",
                "state": "cross_session_repeat",
                "match_basis": "calibrated_h2_match_to_pattern_representative",
                "current_session_episode": {"episode_pk": 71},
            }
        ] if projected else [],
    }


def test_audit_counts_exact_h3_and_h5_without_mutating_inputs(tmp_path: Path):
    generated = tmp_path / "generated"
    source = generated / "h3_1" / "session-a" / "persistent_pattern_selection.json"
    document = _h3_document()
    _write(source, document)
    _write(
        generated / "h4" / "session-a" / "historical_reference_selection.json",
        {
            "selection_status": "HISTORICAL_REFERENCE_SELECTED",
            "target_session": {
                "track": "Test Track",
                "track_layout": "Test Layout",
                "vehicle_variant": "GT3",
            },
        },
    )
    _write(
        generated / "h5_2" / "session-a" / "cross_session_comparison.json",
        {
            "metadata": {"policy": {"historical_coaching_enabled": False}},
            "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
            "context": {
                "track": "Test Track",
                "track_layout": "Test Layout",
                "vehicle_variant": "GT3",
            },
        },
    )
    before = source.read_bytes()

    report = audit_h3_runtime_utility(generated)

    assert source.read_bytes() == before
    assert report["metadata"]["history_opened"] is False
    assert report["metadata"]["matcher_called"] is False
    assert report["summary"]["exact_match_edge_count"] == 1
    assert report["summary"]["projected_match_edge_count"] == 0
    assert report["summary"]["h3_h5_availability"] == {
        "H3_AND_H5_AVAILABLE": 1
    }
    assert report["review_signals"]["authority_contract_violation_count"] == 0


def test_audit_keeps_projection_separate_and_fails_closed_without_h5(tmp_path: Path):
    generated = tmp_path / "generated"
    _write(
        generated / "h3_1" / "session-b" / "persistent_pattern_selection.json",
        _h3_document(projected=True),
    )

    report = audit_h3_runtime_utility(generated)

    assert report["summary"]["exact_match_edge_count"] == 0
    assert report["summary"]["projected_match_edge_count"] == 1
    assert report["summary"]["match_basis_counts"] == {
        "calibrated_h2_match_to_pattern_representative": 1
    }
    assert report["summary"]["h3_h5_availability"] == {
        "H3_AVAILABLE_WITHOUT_H5": 1
    }
    assert report["review_signals"][
        "projected_edges_require_observational_review_count"
    ] == 1


def test_audit_rejects_cross_context_or_authorized_h5_companion(tmp_path: Path):
    generated = tmp_path / "generated"
    _write(
        generated / "h3_1" / "session-x" / "persistent_pattern_selection.json",
        _h3_document(),
    )
    _write(
        generated / "h5_2" / "session-x" / "cross_session_comparison.json",
        {
            "metadata": {"policy": {"historical_coaching_enabled": True}},
            "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
            "context": {
                "track": "Other Track",
                "track_layout": "Other Layout",
                "vehicle_variant": "GT3",
            },
        },
    )

    report = audit_h3_runtime_utility(generated)

    assert report["sessions"][0]["h5_available"] is False
    assert report["sessions"][0]["h5_status"] == "CONTEXT_INVALID"
    assert report["summary"]["h3_h5_availability"] == {
        "H3_AVAILABLE_WITHOUT_H5": 1
    }


def test_audit_flags_authority_violation_duplicate_and_invalid_json(tmp_path: Path):
    generated = tmp_path / "generated"
    document = _h3_document()
    document["metadata"]["historical_actions_authorized"] = True
    document["matched_patterns"].append(dict(document["matched_patterns"][0]))
    _write(
        generated / "h3_1" / "session-c" / "persistent_pattern_selection.json",
        document,
    )
    invalid = generated / "h3_1" / "session-d" / "persistent_pattern_selection.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("{", encoding="utf-8")

    report = audit_h3_runtime_utility(generated)

    assert report["summary"]["invalid_h3_artifact_count"] == 1
    assert report["review_signals"]["authority_contract_violation_count"] == 1
    assert report["review_signals"]["duplicate_match_identity_count"] == 1


def test_write_report_is_json_and_does_not_change_contract(tmp_path: Path):
    report = audit_h3_runtime_utility(tmp_path / "generated")
    output = tmp_path / "diagnostics" / "audit.json"

    write_report(output, report)

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["metadata"]["observational_only"] is True
    assert saved["metadata"]["input_artifacts_mutated"] is False
    assert saved["metadata"]["historical_actions_authorized"] is False
