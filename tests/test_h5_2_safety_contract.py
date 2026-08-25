from __future__ import annotations

import copy
import json
from pathlib import Path

import duckdb
import pytest

from cross_session_context import CrossSessionNotApplicableError, resolve_cross_session_pair
from validate_cross_session_comparison import validate


def _dual(*, historical: dict | None = None, plan: dict | None = None) -> dict:
    dual = {
        "target_session": {"session_id": 2},
        "session_reference": {"lap": 5},
        "historical_reference": historical,
    }
    if plan is not None:
        dual["next_stint_plan"] = plan
    return dual


def _write_history(path: Path, *, historical_context: tuple[str, str, str, str] | None = None) -> None:
    historical_context = historical_context or (
        "Fuji Speedway",
        "Fuji Speedway",
        "LMP2_ELMS",
        "IDEC Sport #18:ELMS25",
    )
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE sessions (
                session_id BIGINT,
                source_json_path VARCHAR,
                source_database_path VARCHAR,
                track VARCHAR,
                session_type VARCHAR,
                timestamp_utc VARCHAR,
                vehicle_variant VARCHAR,
                car_name_raw VARCHAR,
                lmu_track_layout VARCHAR,
                reference_lap BIGINT
            )
            """
        )
        track, layout, variant, car = historical_context
        connection.executemany(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "historical.json", "historical.duckdb", track, "P", "2026-08-23T12:00:00Z", variant, car, layout, 8),
                (2, "current.json", "current.duckdb", "Fuji Speedway", "P", "2026-08-24T12:00:00Z", "LMP2_ELMS", "IDEC Sport #18:ELMS25", "Fuji Speedway", 5),
            ],
        )
    finally:
        connection.close()


def _write_pair(tmp_path: Path, dual: dict, *, historical_context: tuple[str, str, str, str] | None = None) -> tuple[Path, Path, Path]:
    dual_path = tmp_path / "dual.json"
    history_path = tmp_path / "history.duckdb"
    telemetry_dir = tmp_path / "telemetria"
    telemetry_dir.mkdir(parents=True)
    (telemetry_dir / "historical.duckdb").write_bytes(b"historical")
    (telemetry_dir / "current.duckdb").write_bytes(b"current")
    dual_path.write_text(json.dumps(dual), encoding="utf-8")
    _write_history(history_path, historical_context=historical_context)
    return dual_path, history_path, telemetry_dir


def test_h5_2_is_not_applicable_without_h5_1_historical_reference(tmp_path: Path):
    dual_path, history_path, telemetry_dir = _write_pair(tmp_path, _dual(historical=None))

    with pytest.raises(CrossSessionNotApplicableError, match="no contiene historical_reference"):
        resolve_cross_session_pair(dual_path, history_path, telemetry_dir)


def test_h5_2_requires_complete_historical_reference_identity(tmp_path: Path):
    dual_path, history_path, telemetry_dir = _write_pair(
        tmp_path,
        _dual(historical={"session_id": 1}),
    )

    with pytest.raises(CrossSessionNotApplicableError, match="historical_reference no identifica"):
        resolve_cross_session_pair(dual_path, history_path, telemetry_dir)


def test_h5_2_requires_exact_track_layout_and_vehicle_context(tmp_path: Path):
    for context, reason in (
        (("Fuji GP", "Fuji Speedway", "LMP2_ELMS", "IDEC Sport #18:ELMS25"), "track"),
        (("Fuji Speedway", "Fuji Short", "LMP2_ELMS", "IDEC Sport #18:ELMS25"), "layout"),
        (("Fuji Speedway", "Fuji Speedway", "LMP2", "IDEC Sport #18:ELMS25"), "vehicle"),
    ):
        case_dir = tmp_path / f"case_{reason}"
        dual_path, history_path, telemetry_dir = _write_pair(
            case_dir,
            _dual(historical={"session_id": 1, "lap": 8}),
            historical_context=context,
        )
        with pytest.raises(CrossSessionNotApplicableError, match="context mismatch"):
            resolve_cross_session_pair(dual_path, history_path, telemetry_dir)


def test_h5_2_resolves_exact_lmp2_elms_pair_and_preserves_plan(tmp_path: Path):
    plan = {"priorities": [{"label": "A", "start_distance_m": 100.0, "end_distance_m": 200.0}]}
    dual_path, history_path, telemetry_dir = _write_pair(
        tmp_path,
        _dual(historical={"session_id": 1, "lap": 8}, plan=plan),
    )
    original = json.loads(dual_path.read_text(encoding="utf-8"))

    pair = resolve_cross_session_pair(dual_path, history_path, telemetry_dir)

    assert pair["context"] == {
        "track": "Fuji Speedway",
        "track_layout": "Fuji Speedway",
        "vehicle_variant": "LMP2_ELMS",
        "car_name_raw": "IDEC Sport #18:ELMS25",
    }
    assert pair["dual_reference"]["next_stint_plan"] == original["next_stint_plan"]
    assert pair["dual_reference"]["session_reference"] == original["session_reference"]
    assert pair["historical"]["lap"] == 8


def test_h5_2_pair_resolution_is_deterministic_and_does_not_authorize_plan_changes(tmp_path: Path):
    dual_path, history_path, telemetry_dir = _write_pair(
        tmp_path,
        _dual(historical={"session_id": 1, "lap": 8}),
    )

    first = resolve_cross_session_pair(dual_path, history_path, telemetry_dir)
    second = resolve_cross_session_pair(dual_path, history_path, telemetry_dir)

    assert first == second
    assert "next_stint_plan" not in first
    assert first["dual_reference"]["historical_reference"] == {
        "session_id": 1,
        "lap": 8,
    }


def _valid_comparison(tmp_path: Path) -> dict:
    historical = tmp_path / "historical.duckdb"
    current = tmp_path / "current.duckdb"
    historical.write_bytes(b"historical")
    current.write_bytes(b"current")
    return {
        "metadata": {"schema_version": "1.1", "cross_session_version": "0.2"},
        "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
        "context": {
            "track": "Fuji Speedway",
            "track_layout": "Fuji Speedway",
            "vehicle_variant": "LMP2_ELMS",
            "car_name_raw": "IDEC Sport #18:ELMS25",
        },
        "historical_reference": {"session_id": 1, "lap": 8, "source_database": str(historical)},
        "current_session_reference": {"session_id": 2, "lap": 5, "source_database": str(current)},
        "temporal_validation": {"status": "OK", "error_s": 0.0, "tolerance_s": 1e-6},
        "spatial_comparison": {
            "trend_zone_summary_count": 1,
            "trend_zone_summaries": [{"trend_zone_id": "trend_1"}],
            "localization": {"version": "0.1", "mode": "unavailable", "reason": "no_exact_validated_track_profile", "profile_id": None, "boundary_count": 0},
            "zone_summary_count": 1,
            "zone_summaries": [{"source_trend_zone_id": "trend_1", "scope": "unlocalized_delta_trend", "location": None}],
        },
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_reference_is_observational": True,
            "historical_actions_authorized": False,
        },
    }


def test_h5_2_validator_accepts_observational_contrast_without_authorizing_actions(tmp_path: Path):
    document = _valid_comparison(tmp_path)
    document["spatial_comparison"]["zone_summaries"][0]["observation"] = {
        "speed_context": "historical reference is faster"
    }

    assert validate(document) == []
    assert document["coaching_authority"]["session_reference_remains_authority"] is True
    assert document["coaching_authority"]["historical_actions_authorized"] is False
    assert "next_stint_plan" not in document
    assert "actions" not in document


def test_h5_2_validator_rejects_missing_schema_and_authority_escalation(tmp_path: Path):
    document = _valid_comparison(tmp_path)

    missing = copy.deepcopy(document)
    del missing["current_session_reference"]
    assert any("current_session_reference ausente" in error for error in validate(missing))

    escalated = copy.deepcopy(document)
    escalated["coaching_authority"]["historical_actions_authorized"] = True
    assert any("historical_actions_authorized debe ser false" in error for error in validate(escalated))

    no_authority = copy.deepcopy(document)
    no_authority["coaching_authority"]["session_reference_remains_authority"] = False
    assert any("session_reference dejó de ser autoridad" in error for error in validate(no_authority))


def test_h5_2_validator_rejects_invented_zone_provenance(tmp_path: Path):
    document = _valid_comparison(tmp_path)
    document["spatial_comparison"]["zone_summaries"][0]["source_trend_zone_id"] = "invented_zone"

    errors = validate(document)

    assert "zone_summaries[0].source_trend_zone_id inválido" in errors
