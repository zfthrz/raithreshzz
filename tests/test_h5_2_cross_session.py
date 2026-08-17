from __future__ import annotations

import json
from pathlib import Path

import pytest

from cross_session_context import (
    CrossSessionNotApplicableError,
    resolve_cross_session_pair,
)
from runtime_paths import cross_session_output_path
from validate_cross_session_comparison import validate


duckdb = pytest.importorskip("duckdb")


def write_dual(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "target_session": {"session_id": 2},
                "session_reference": {"lap": 5},
                "historical_reference": {"session_id": 1, "lap": 8},
            }
        ),
        encoding="utf-8",
    )


def write_history(path: Path, *, historical_track: str = "Fuji Speedway") -> None:
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
        connection.executemany(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    1,
                    "historical.json",
                    r"C:\old\historical.duckdb",
                    historical_track,
                    "P",
                    "2026-08-13T21:40:16Z",
                    "LMP2_ELMS",
                    "IDEC Sport #18:ELMS25",
                    "Fuji Speedway",
                    8,
                ),
                (
                    2,
                    "current.json",
                    r"C:\old\current.duckdb",
                    "Fuji Speedway",
                    "P",
                    "2026-08-13T22:40:32Z",
                    "LMP2_ELMS",
                    "IDEC Sport #18:ELMS25",
                    "Fuji Speedway",
                    5,
                ),
            ],
        )
    finally:
        connection.close()


def test_resolves_both_raw_sessions_from_history_basenames(tmp_path: Path):
    dual = tmp_path / "dual.json"
    history = tmp_path / "history.duckdb"
    telemetry = tmp_path / "telemetria"
    telemetry.mkdir()
    (telemetry / "historical.duckdb").write_bytes(b"historical")
    (telemetry / "current.duckdb").write_bytes(b"current")
    write_dual(dual)
    write_history(history)

    pair = resolve_cross_session_pair(dual, history, telemetry)

    assert pair["historical"]["database"].name == "historical.duckdb"
    assert pair["current"]["database"].name == "current.duckdb"
    assert pair["historical"]["lap"] == 8
    assert pair["current"]["lap"] == 5


def test_rejects_cross_session_context_mismatch(tmp_path: Path):
    dual = tmp_path / "dual.json"
    history = tmp_path / "history.duckdb"
    telemetry = tmp_path / "telemetria"
    telemetry.mkdir()
    write_dual(dual)
    write_history(history, historical_track="Different Track")

    with pytest.raises(CrossSessionNotApplicableError, match="context mismatch"):
        resolve_cross_session_pair(dual, history, telemetry)


def test_validator_preserves_session_reference_authority(tmp_path: Path):
    historical = tmp_path / "historical.duckdb"
    current = tmp_path / "current.duckdb"
    historical.write_bytes(b"historical")
    current.write_bytes(b"current")
    document = {
        "metadata": {"schema_version": "1.1", "cross_session_version": "0.2"},
        "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
        "historical_reference": {
            "session_id": 1,
            "lap": 8,
            "source_database": str(historical),
        },
        "current_session_reference": {
            "session_id": 2,
            "lap": 5,
            "source_database": str(current),
        },
        "temporal_validation": {
            "status": "OK",
            "error_s": 0.0,
            "tolerance_s": 1e-6,
        },
        "spatial_comparison": {
            "trend_zone_summary_count": 0,
            "trend_zone_summaries": [],
            "localization": {
                "version": "0.1",
                "mode": "unavailable",
                "reason": "no_exact_validated_track_profile",
                "profile_id": None,
                "boundary_count": 0,
            },
            "zone_summary_count": 0,
            "zone_summaries": [],
        },
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
        },
    }

    assert validate(document) == []
    document["coaching_authority"]["historical_actions_authorized"] = True
    assert "historical_actions_authorized debe ser false en v0.2" in validate(document)


def test_runtime_path_places_h5_2_under_generated_root():
    path = cross_session_output_path("telemetria/example.duckdb")
    assert path.parts[-3:] == (
        "h5_2",
        "example",
        "cross_session_comparison.json",
    )
