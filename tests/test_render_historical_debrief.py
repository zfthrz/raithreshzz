from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from render_historical_debrief import build_section


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


def _comparison(localization_mode: str = "validated_track_profile") -> dict:
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
                "mode": localization_mode,
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


def _write_sources(tmp_path: Path, localization_mode: str = "validated_track_profile"):
    dual_path = tmp_path / "dual_reference_context.json"
    comparison_path = tmp_path / "cross_session_comparison.json"
    dual_path.write_text(
        json.dumps(_dual_reference(), ensure_ascii=False),
        encoding="utf-8",
    )
    comparison_path.write_text(
        json.dumps(_comparison(localization_mode), ensure_ascii=False),
        encoding="utf-8",
    )
    return dual_path, comparison_path


def test_builds_deterministic_historical_section(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)

    section = build_section(dual_path, comparison_path)

    assert section["status"] == "DETERMINISTIC_HISTORICAL_SECTION"
    assert section["labels"]["current_session"]["lap"] == 3
    assert section["labels"]["historical_reference"]["lap"] == 10
    assert section["labels"]["current_minus_historical_s"] == 1.78
    assert section["labels"]["delta_sign"] == "current_slower"
    assert section["zones"][0]["action_authorized"] is False
    assert section["zones"][0]["observational_only"] is True
    assert "COMPARACIÓN HISTÓRICA (OBSERVACIONAL)" in section["rendered_section"]
    assert "99.280 s" in section["rendered_section"]
    assert "97.500 s" in section["rendered_section"]
    assert "acciones históricas siguen deshabilitadas" in section["rendered_section"]
    assert section["coaching_authority"]["historical_actions_authorized"] is False


def test_output_is_byte_stable_for_same_inputs(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)

    first = json.dumps(
        build_section(dual_path, comparison_path),
        ensure_ascii=False,
        sort_keys=True,
    )
    second = json.dumps(
        build_section(dual_path, comparison_path),
        ensure_ascii=False,
        sort_keys=True,
    )

    assert first == second


def test_unlocalized_comparison_includes_explicit_limitation(tmp_path: Path):
    dual_path, comparison_path = _write_sources(
        tmp_path,
        localization_mode="unavailable",
    )

    section = build_section(dual_path, comparison_path)

    assert "track_profile_localization_unavailable" in section["limitations"]
    assert "perfil: unavailable" in section["rendered_section"]


def test_invalid_temporal_validation_is_rejected(tmp_path: Path):
    dual_path, comparison_path = _write_sources(tmp_path)
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    comparison["temporal_validation"]["status"] = "ERROR"
    comparison_path.write_text(
        json.dumps(comparison, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="temporal_validation"):
        build_section(dual_path, comparison_path)


def test_render_aliases_match_versioned_sources():
    root = Path(__file__).resolve().parents[1]
    alias_hash = hashlib.sha256(
        (root / "render_historical_debrief.py").read_bytes()
    ).digest()
    source_hash = hashlib.sha256(
        (root / "render_historical_debrief_v0_1.py").read_bytes()
    ).digest()
    assert alias_hash == source_hash
