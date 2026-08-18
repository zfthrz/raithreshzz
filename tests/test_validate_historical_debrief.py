from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from render_historical_debrief import build_section
from validate_historical_debrief import build_safe_fallback, validate


def _context() -> dict:
    return {
        "track": "Autodromo Nazionale Monza",
        "track_layout": "Autodromo Nazionale Monza",
        "vehicle_variant": "LMP2_ELMS",
        "car_name_raw": "IDEC Sport #18",
    }


def _dual_reference() -> dict:
    return {
        "metadata": {
            "schema_version": "1.0",
            "dual_reference_version": "0.2",
        },
        "status": "DUAL_REFERENCE_AVAILABLE",
        "context": _context(),
        "target_session": {"session_id": 23},
        "session_reference": {"lap": 3, "duration_s": 99.28},
        "historical_reference": {"session_id": 19, "lap": 10, "duration_s": 97.5},
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
        "context": _context(),
        "historical_reference": {"session_id": 19, "lap": 10},
        "current_session_reference": {"session_id": 23, "lap": 3},
        "temporal_validation": {
            "status": "OK",
            "calculated_current_minus_historical_s": 1.78,
            "tolerance_s": 1e-6,
        },
        "spatial_comparison": {
            "trend_zone_summary_count": 1,
            "trend_zone_summaries": [{"trend_zone_id": "trend_001"}],
            "localization": {
                "mode": "validated_track_profile",
                "profile_id": "monza-profile",
                "profile_status": "VALIDATED_MULTI_SESSION",
            },
            "zone_summary_count": 1,
            "zone_summaries": [
                {
                    "source_trend_zone_id": "trend_001",
                    "scope": "track_profile_segment",
                    "location": {"label": "T1 - Test", "profile_id": "monza-profile"},
                    "type": "loss",
                    "start_distance": 100.0,
                    "end_distance": 200.0,
                    "delta_change": 1.78,
                    "speed_delta_avg": -4.5,
                    "throttle_delta_avg": -2.0,
                    "brake_delta_avg": 1.5,
                    "steering_delta_avg": 0.4,
                }
            ],
        },
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
        },
    }


def _write_sources(tmp_path: Path):
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


def _section(tmp_path: Path) -> tuple[dict, Path, Path]:
    dual_path, comparison_path = _write_sources(tmp_path)
    return build_section(dual_path, comparison_path), dual_path, comparison_path


def test_valid_section_passes_validator(tmp_path: Path):
    section, _, _ = _section(tmp_path)
    assert validate(section) == []


def test_tampered_render_fails_and_fallback_regenerates(tmp_path: Path):
    section, dual_path, comparison_path = _section(tmp_path)
    tampered = copy.deepcopy(section)
    tampered["rendered_section"] = "texto inventado"

    assert any(
        "rendered_section no coincide" in error
        for error in validate(tampered)
    )

    fallback = build_safe_fallback(dual_path, comparison_path)
    assert fallback["status"] == "DETERMINISTIC_HISTORICAL_SECTION"
    assert fallback["metadata"]["fallback"] == "regenerated_from_validated_sources"
    assert fallback["metadata"]["normal_debrief_unchanged"] is True
    assert fallback["rendered_section"] == section["rendered_section"]
    assert validate(fallback) == []


def test_tampered_zone_is_rejected(tmp_path: Path):
    section, _, _ = _section(tmp_path)
    section["zones"][0]["delta_change"] = 99.0

    assert any("zones no coinciden exactamente" in error for error in validate(section))


def test_wrong_source_hash_is_rejected(tmp_path: Path):
    section, _, _ = _section(tmp_path)
    section["metadata"]["source_comparison_sha256"] = "0" * 64

    assert any("source_comparison_sha256 no coincide" in error for error in validate(section))


def test_fallback_with_invalid_sources_returns_failed_record(tmp_path: Path):
    fallback = build_safe_fallback(
        tmp_path / "missing_dual.json",
        tmp_path / "missing_comparison.json",
    )

    assert fallback["status"] == "H5_3_FAILED"
    assert fallback["normal_debrief_unchanged"] is True
    assert fallback["historical_actions_authorized"] is False
    assert fallback["session_reference_remains_authority"] is True


def test_validator_aliases_match_versioned_sources():
    root = Path(__file__).resolve().parents[1]
    alias_hash = hashlib.sha256(
        (root / "validate_historical_debrief.py").read_bytes()
    ).digest()
    source_hash = hashlib.sha256(
        (root / "validate_historical_debrief_v0_1.py").read_bytes()
    ).digest()
    assert alias_hash == source_hash
