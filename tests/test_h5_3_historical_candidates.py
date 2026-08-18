from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from build_historical_coaching_candidates import build_candidates


def _dual_reference() -> dict:
    return {
        "metadata": {
            "schema_version": "1.0",
            "dual_reference_version": "0.2",
        },
        "status": "DUAL_REFERENCE_AVAILABLE",
        "context": {
            "track": "Autodromo Nazionale Monza",
            "track_layout": "Autodromo Nazionale Monza",
            "vehicle_variant": "LMP2_ELMS",
            "car_name_raw": "IDEC Sport #18",
        },
        "target_session": {"session_id": 23},
        "session_reference": {
            "lap": 3,
            "duration_s": 99.280,
        },
        "historical_reference": {
            "session_id": 19,
            "lap": 10,
            "duration_s": 97.500,
        },
        "coaching_authority": {
            "active_reference": "session_reference",
            "historical_reference_can_change_driver_cues": False,
            "historical_reference_can_change_global_ABC_plan": False,
            "historical_reference_is_observational_only": True,
        },
    }


def _comparison() -> dict:
    return {
        "metadata": {
            "schema_version": "1.1",
            "cross_session_version": "0.2",
        },
        "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
        "context": {
            "track": "Autodromo Nazionale Monza",
            "track_layout": "Autodromo Nazionale Monza",
            "vehicle_variant": "LMP2_ELMS",
            "car_name_raw": "IDEC Sport #18",
        },
        "temporal_validation": {
            "status": "OK",
            "calculated_current_minus_historical_s": 1.78,
            "tolerance_s": 1e-6,
        },
        "spatial_comparison": {
            "trend_zone_summary_count": 2,
            "trend_zone_summaries": [
                {"trend_zone_id": "trend_001"},
                {"trend_zone_id": "trend_002"},
            ],
            "localization": {
                "mode": "validated_track_profile",
                "profile_id": "monza-test-profile",
                "profile_status": "VALIDATED_MULTI_SESSION",
                "profile_track": "Autodromo Nazionale Monza",
                "profile_layout": "Autodromo Nazionale Monza",
            },
            "zone_summary_count": 2,
            "zone_summaries": [
                {
                    "source_trend_zone_id": "trend_001",
                    "scope": "track_profile_segment",
                    "location": {
                        "label": "T1 - Test",
                        "profile_id": "monza-test-profile",
                    },
                    "type": "loss",
                    "start_distance": 100.0,
                    "end_distance": 200.0,
                    "delta_change": 0.32,
                    "speed_delta_avg": -4.5,
                    "throttle_delta_avg": -2.0,
                    "brake_delta_avg": 1.5,
                    "steering_delta_avg": 0.4,
                },
                {
                    "source_trend_zone_id": "trend_002",
                    "scope": "track_profile_segment",
                    "location": {
                        "label": "T2 - Test",
                        "profile_id": "monza-test-profile",
                    },
                    "type": "gain",
                    "start_distance": 200.0,
                    "end_distance": 260.0,
                    "delta_change": -0.12,
                    "speed_delta_avg": 3.0,
                    "throttle_delta_avg": 0.5,
                    "brake_delta_avg": -0.2,
                    "steering_delta_avg": -0.1,
                },
            ],
        },
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
        },
    }


def _write_sources(tmp_path: Path) -> tuple[Path, Path]:
    dual_path = tmp_path / "dual_reference_context.json"
    comparison_path = tmp_path / "cross_session_comparison.json"
    dual_path.write_text(
        json.dumps(_dual_reference(), ensure_ascii=False),
        encoding="utf-8",
    )
    comparison_path.write_text(
        json.dumps(_comparison(), ensure_ascii=False),
        encoding="utf-8",
    )
    return dual_path, comparison_path


def test_builds_shadow_candidates_from_valid_sources(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)

    output = build_candidates(dual_path, comparison_path)

    assert output["status"] == "SHADOW_OBSERVATIONAL_ONLY"
    assert output["prerequisites"]["applicable"] is True
    assert output["prerequisites"]["skip_reason"] is None
    assert output["total_delta"]["current_minus_historical_s"] == 1.78
    assert output["total_delta"]["sign"] == "current_slower"
    assert len(output["candidates"]) == 2
    assert output["candidates"][0]["candidate_id"] == "cand_001"
    assert output["candidates"][0]["location"]["label"] == "T1 - Test"
    assert output["candidates"][0]["authorization"]["action_authorized"] is False
    assert output["coaching_authority"]["historical_actions_authorized"] is False


def test_output_is_byte_stable_for_same_inputs(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)

    first = json.dumps(
        build_candidates(dual_path, comparison_path),
        ensure_ascii=False,
        sort_keys=True,
    )
    second = json.dumps(
        build_candidates(dual_path, comparison_path),
        ensure_ascii=False,
        sort_keys=True,
    )

    assert first == second


def test_missing_historical_reference_returns_explicit_skip(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)
    dual = _dual_reference()
    dual["status"] = "SESSION_REFERENCE_ONLY"
    dual["historical_reference"] = None
    dual_path.write_text(json.dumps(dual, ensure_ascii=False), encoding="utf-8")

    output = build_candidates(dual_path, comparison_path)

    assert output["prerequisites"]["applicable"] is False
    assert output["prerequisites"]["skip_reason"] == (
        "historical_reference_unavailable"
    )
    assert output["candidates"] == []


def test_unlocalized_comparison_returns_explicit_skip(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)
    comparison = _comparison()
    comparison["spatial_comparison"]["localization"]["mode"] = "unavailable"
    comparison_path.write_text(
        json.dumps(comparison, ensure_ascii=False),
        encoding="utf-8",
    )

    output = build_candidates(dual_path, comparison_path)

    assert output["prerequisites"]["applicable"] is False
    assert output["prerequisites"]["skip_reason"] == (
        "no_exact_validated_track_profile"
    )
    assert output["candidates"] == []


def test_tampered_historical_actions_authorization_is_rejected(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)
    comparison = _comparison()
    comparison["coaching_authority"]["historical_actions_authorized"] = True
    comparison_path.write_text(
        json.dumps(comparison, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="historical_actions_authorized"):
        build_candidates(dual_path, comparison_path)


def test_tampered_temporal_validation_is_rejected(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)
    comparison = _comparison()
    comparison["temporal_validation"]["status"] = "ERROR"
    comparison_path.write_text(
        json.dumps(comparison, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="temporal_validation"):
        build_candidates(dual_path, comparison_path)


def test_zone_evidence_traces_to_source_hash(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)

    output = build_candidates(dual_path, comparison_path)

    assert output["metadata"]["source_h5_1_sha256"]
    assert output["metadata"]["source_h5_2_sha256"]
    assert output["candidates"][0]["source_trend_zone_id"] == "trend_001"
    assert output["candidates"][0]["observational_channel_evidence"] == {
        "speed_delta_avg": -4.5,
        "throttle_delta_avg": -2.0,
        "brake_delta_avg": 1.5,
        "steering_delta_avg": 0.4,
    }
