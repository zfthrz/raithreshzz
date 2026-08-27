from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import select_historical_reference as h4
from build_dual_reference_context import build_dual_reference


TARGET_TIMESTAMP = "2026-08-24T12:00:00+00:00"
HISTORICAL_TIMESTAMP = "2026-08-23T12:00:00+00:00"


def _session(
    *,
    session_id: int = 10,
    track: str = "Fuji Speedway",
    layout: str = "Fuji Speedway",
    vehicle_variant: str = "LMP2_ELMS",
    car_name: str = "IDEC Sport #18:ELMS25",
    timestamp: str = HISTORICAL_TIMESTAMP,
    valid_laps: int = 5,
) -> dict:
    return {
        "session_id": session_id,
        "timestamp_utc": timestamp,
        "track": track,
        "lmu_track_layout": layout,
        "vehicle_variant": vehicle_variant,
        "car_name_raw": car_name,
        "vehicle_supported_domain": True,
        "temporal_validation_status": "OK",
        "objective_analysis_validation": "OK",
        "valid_lap_count": valid_laps,
        "session_type": "Practice",
        "lmu_session_type": "Practice",
        "weather_conditions": "Clear",
    }


def _lap(*, session_id: int = 10, lap: int = 3, duration: float = 90.0) -> dict:
    return {
        "session_id": session_id,
        "lap": lap,
        "duration_s": duration,
        "samples": 1800,
        "lap_distance_m": 4600.0,
        "is_valid": True,
        "is_discarded": False,
        "is_ignored_initial": False,
        "is_reference": True,
    }


def _evaluate(candidate: dict, *, candidate_lap: dict | None = None) -> dict:
    return h4.evaluate_candidate(
        _session(session_id=1, timestamp=TARGET_TIMESTAMP),
        _lap(session_id=1),
        candidate,
        candidate_lap or _lap(session_id=candidate["session_id"]),
        min_valid_laps=3,
    )


def test_h4_requires_exact_vehicle_variant_and_preserves_lmp2_elms_boundary():
    elms = _evaluate(_session(session_id=2, vehicle_variant="LMP2_ELMS"))
    wec = _evaluate(_session(session_id=3, vehicle_variant="LMP2"))
    family_variant = _evaluate(_session(session_id=4, vehicle_variant="LMP2"))
    family_variant["vehicle_family"] = "LMP2"

    assert elms["eligibility"] == "ELIGIBLE"
    assert wec["eligibility"] == "REJECTED"
    assert "VEHICLE_VARIANT_MISMATCH" in wec["rejection_reasons"]
    assert family_variant["eligibility"] == "REJECTED"
    assert "VEHICLE_VARIANT_MISMATCH" in family_variant["rejection_reasons"]


def test_h4_accepts_different_car_name_inside_same_vehicle_variant():
    candidate = _session(
        session_id=2,
        car_name="Inter Europol Competition #34:ELMS25",
        vehicle_variant="LMP2_ELMS",
    )

    result = _evaluate(candidate)

    assert result["eligibility"] == "ELIGIBLE"
    assert "CAR_NAME_MISMATCH" not in result["rejection_reasons"]
    assert result["compatibility_observations"]["same_car_name_raw"] is False


def test_h4_track_and_layout_are_hard_gates_without_alias_normalization():
    same_context = _evaluate(_session(session_id=2))
    different_layout = _evaluate(_session(session_id=3, layout="Fuji Speedway Short"))
    similar_track = _evaluate(_session(session_id=4, track="Fuji GP"))

    assert same_context["eligibility"] == "ELIGIBLE"
    assert different_layout["eligibility"] == "REJECTED"
    assert "LAYOUT_MISMATCH" in different_layout["rejection_reasons"]
    assert similar_track["eligibility"] == "REJECTED"
    assert "TRACK_MISMATCH" in similar_track["rejection_reasons"]


def test_h4_candidate_filtering_keeps_only_eligible_candidates_and_reports_reasons():
    candidates = [
        _session(session_id=2),
        _session(session_id=3, layout="Fuji Short"),
        _session(session_id=4, valid_laps=2),
        _session(session_id=5, vehicle_variant="LMP2"),
    ]
    results = [_evaluate(candidate) for candidate in candidates]

    eligible = [result for result in results if result["eligibility"] == "ELIGIBLE"]

    assert [result["session_id"] for result in eligible] == [2]
    assert "LAYOUT_MISMATCH" in results[1]["rejection_reasons"]
    assert "INSUFFICIENT_VALID_LAPS" in results[2]["rejection_reasons"]
    assert "VEHICLE_VARIANT_MISMATCH" in results[3]["rejection_reasons"]


def test_h4_zero_eligible_candidates_maps_to_safe_no_reference_state():
    rejected = _evaluate(_session(session_id=2, layout="Fuji Short"))

    assert rejected["eligibility"] == "REJECTED"
    assert rejected["rejection_reasons"]
    eligible = [result for result in [rejected] if result["eligibility"] == "ELIGIBLE"]
    assert eligible == []  # no rejected record may enter a historical ranking


def _analysis(*, next_stint_plan: dict | None = None) -> dict:
    metadata = {
        "track": "Fuji Speedway",
        "reference_lap": 3,
        "timestamp_utc": TARGET_TIMESTAMP,
        "session_type": "Practice",
        "vehicle_identity": {
            "family": "LMP2",
            "variant": "LMP2_ELMS",
            "car_name_raw": "IDEC Sport #18:ELMS25",
        },
        "session_context": {"lmu_track_layout": "Fuji Speedway"},
    }
    analysis = {
        "metadata": metadata,
        "laps": [{"lap": 3, "duration_s": 90.0, "samples": 1800, "lap_distance_m": 4600.0}],
    }
    if next_stint_plan is not None:
        analysis["next_stint_plan"] = next_stint_plan
    return analysis


def _selection(*, status: str, historical: dict | None = None) -> dict:
    target = {
        "session_id": 1,
        "timestamp_utc": TARGET_TIMESTAMP,
        "session_type": "Practice",
        "track": "Fuji Speedway",
        "track_layout": "Fuji Speedway",
        "vehicle_variant": "LMP2_ELMS",
        "car_name_raw": "IDEC Sport #18:ELMS25",
        "session_reference": {"lap": 3, "duration_s": 90.0},
    }
    return {
        "metadata": {"selector_version": "0.3"},
        "selection_status": status,
        "target_session": target,
        "selected_historical_reference": historical,
    }


def _build(tmp_path: Path, analysis: dict, selection: dict) -> dict:
    analysis_path = tmp_path / "analysis.json"
    selection_path = tmp_path / "selection.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    return build_dual_reference(analysis_path, selection_path, equality_tolerance_s=0.1)


def test_h5_1_without_h4_reference_falls_back_without_mutating_session_reference(tmp_path: Path):
    analysis = _analysis(next_stint_plan={"items": ["A", "B"]})
    original_plan = copy.deepcopy(analysis["next_stint_plan"])

    result = _build(
        tmp_path,
        analysis,
        _selection(status="NO_COMPATIBLE_HISTORICAL_REFERENCE"),
    )

    assert result["status"] == "SESSION_REFERENCE_ONLY"
    assert result["historical_reference"] is None
    assert result["coaching_authority"]["active_reference"] == "session_reference"
    assert result["metadata"]["policy"]["historical_action_coaching_enabled"] is False
    assert result["session_reference"]["lap"] == 3
    assert result["session_reference"]["duration_s"] == 90.0
    assert analysis["next_stint_plan"] == original_plan


def test_h5_1_valid_dual_context_keeps_session_authority_and_no_historical_actions(tmp_path: Path):
    historical = {
        "session_id": 9,
        "lap": 4,
        "duration_s": 88.5,
        "timestamp_utc": HISTORICAL_TIMESTAMP,
        "session_type": "Practice",
        "weather_conditions": "Clear",
        "weather_class": "DRY",
        "source_json_path": "historical.json",
    }

    result = _build(
        tmp_path,
        _analysis(next_stint_plan={"items": ["A", "B"]}),
        _selection(
            status="HISTORICAL_REFERENCE_SELECTED",
            historical=historical,
        ),
    )

    assert result["status"] == "DUAL_REFERENCE_AVAILABLE"
    assert result["historical_reference"]["session_id"] == 9
    assert result["session_reference"]["lap"] == 3
    assert result["coaching_authority"] == {
        "active_reference": "session_reference",
        "historical_reference_can_change_driver_cues": False,
        "historical_reference_can_change_global_ABC_plan": False,
        "historical_reference_is_observational_only": True,
    }
    assert result["metadata"]["policy"]["historical_action_coaching_enabled"] is False
    assert result["next_stage"]["cross_session_telemetry_comparison_required_for_historical_actions"] is True
