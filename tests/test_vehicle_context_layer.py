from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    root_str = str(ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_lmu_context_from_metadata_table(tmp_path):
    module = load_module("vehicle_context_integration", "vehicle_context.py")
    db_path = tmp_path / "sample.duckdb"

    connection = duckdb.connect(str(db_path))
    try:
        connection.execute("CREATE TABLE metadata(key VARCHAR, value VARCHAR)")
        connection.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [
                ("TrackName", "Circuit de Spa-Francorchamps"),
                ("SessionType", "Qualify"),
                ("WeatherConditions", "Light Clouds"),
                ("CarName", "IDEC Sport #18:ELMS25"),
                ("CarClass", "LMP2_ELMS"),
                ("CarSetup", json.dumps({
                    "VM_REAR_WING": {
                        "available": True,
                        "value": 0,
                        "stringValue": "P1",
                    }
                })),
            ],
        )
    finally:
        connection.close()

    context = module.extract_lmu_context_from_duckdb(db_path)

    assert context["metadata_available"] is True
    assert context["vehicle_identity"]["family"] == "LMP2"
    assert context["vehicle_identity"]["variant"] == "LMP2_ELMS"
    assert context["session_context"]["lmu_session_type"] == "Qualify"
    assert context["session_context"]["setup_sha256"] is not None


def create_v1_history_skeleton(db_path: Path) -> None:
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            CREATE TABLE history_meta (
                schema_version INTEGER NOT NULL,
                created_at_utc VARCHAR NOT NULL,
                updated_at_utc VARCHAR NOT NULL
            )
            """
        )
        connection.execute("INSERT INTO history_meta VALUES (1, 'a', 'a')")
        connection.execute(
            """
            CREATE TABLE sessions (
                session_id BIGINT PRIMARY KEY,
                source_json_path VARCHAR NOT NULL,
                source_json_sha256 VARCHAR NOT NULL UNIQUE,
                source_database_path VARCHAR,
                source_analysis_version VARCHAR NOT NULL,
                track VARCHAR,
                session_type VARCHAR,
                timestamp_utc VARCHAR,
                same_vehicle BOOLEAN NOT NULL,
                vehicle_count INTEGER,
                lap_comparison_model VARCHAR,
                reference_lap INTEGER,
                reference_distance_m DOUBLE,
                temporal_validation_status VARCHAR,
                objective_analysis_validation VARCHAR,
                valid_lap_count INTEGER,
                discarded_lap_count INTEGER,
                comparison_count INTEGER,
                imported_at_utc VARCHAR NOT NULL
            )
            """
        )
    finally:
        connection.close()


def test_history_schema_v1_migrates_to_current_schema(tmp_path):
    module = load_module("session_history_migration", "session_history.py")
    db_path = tmp_path / "history.duckdb"
    create_v1_history_skeleton(db_path)

    connection = duckdb.connect(str(db_path))
    try:
        module.initialize_schema(connection)
        version = connection.execute(
            "SELECT schema_version FROM history_meta"
        ).fetchone()[0]
        columns = {
            row[0]
            for row in connection.execute("DESCRIBE sessions").fetchall()
        }
    finally:
        connection.close()

    assert version == 4
    assert "vehicle_variant" in columns
    assert "setup_sha256" in columns
    assert "weather_conditions" in columns


def test_history_insert_persists_vehicle_context(tmp_path):
    module = load_module("session_history_insert", "session_history.py")
    db_path = tmp_path / "history.duckdb"

    connection = duckdb.connect(str(db_path))
    try:
        module.initialize_schema(connection)

        metadata = {
            "analysis_version": "3.8",
            "database": "source.duckdb",
            "track": "Circuit de Spa-Francorchamps",
            "session_type": "Q",
            "timestamp_utc": "2026-08-10T00:53:48Z",
            "same_vehicle": True,
            "vehicle_count": 1,
            "lap_comparison_model": "same_vehicle_different_laps",
            "reference_lap": 4,
            "reference_distance_m": 6973.0,
            "temporal_validation_status": "OK",
            "objective_analysis_validation": "OK",
            "valid_laps": [1, 2, 3, 4],
            "discarded_laps": [5],
            "vehicle_identity": {
                "family": "LMP2",
                "variant": "LMP2_ELMS",
                "car_class_raw": "LMP2_ELMS",
                "car_name_raw": "IDEC Sport #18:ELMS25",
                "identity_source": "lmu_metadata",
                "supported_domain": True,
            },
            "session_context": {
                "weather_conditions": "Light Clouds",
                "setup_sha256": "a" * 64,
                "setup_raw_sha256": "b" * 64,
                "setup_available": True,
                "lmu_session_type": "Qualify",
                "lmu_track_name": "Circuit de Spa-Francorchamps",
            },
        }

        session_id = module.insert_session(
            connection,
            "analysis.json",
            "c" * 64,
            metadata,
            [],
            [],
        )

        row = connection.execute(
            """
            SELECT vehicle_family, vehicle_variant, car_class_raw,
                   car_name_raw, weather_conditions, setup_sha256,
                   lmu_session_type
            FROM sessions
            WHERE session_id = ?
            """,
            [session_id],
        ).fetchone()
    finally:
        connection.close()

    assert row == (
        "LMP2", "LMP2_ELMS", "LMP2_ELMS",
        "IDEC Sport #18:ELMS25", "Light Clouds",
        "a" * 64, "Qualify",
    )


def episode(episode_pk: int, session_id: int, variant: str | None, *, supported=True, setup=None):
    return {
        "episode_pk": episode_pk,
        "session_id": session_id,
        "comparison_id": session_id,
        "episode_id": 1,
        "python_global_rank": 1,
        "track": "Spa",
        "session_type": "P",
        "timestamp_utc": f"t{session_id}",
        "reference_distance_m": 7000.0,
        "vehicle_family": "LMP2" if variant else None,
        "vehicle_variant": variant,
        "car_class_raw": "LMP2_ELMS" if variant == "LMP2_ELMS" else "LMP2",
        "car_name_raw": "IDEC",
        "vehicle_identity_source": "lmu_metadata" if variant else None,
        "vehicle_supported_domain": supported if variant else False,
        "weather_conditions": "Light Clouds",
        "setup_sha256": setup,
        "setup_raw_sha256": None,
        "setup_available": bool(setup),
        "lmu_session_type": "Practice",
        "lmu_track_name": "Spa",
        "lmu_track_layout": "Spa",
        "reference_lap": 1,
        "comparison_lap": 2,
        "driver_analysis_priority_rank": 1,
        "start_distance_m": 1000.0,
        "end_distance_m": 1100.0,
        "center_distance_m": 1050.0,
        "length_m": 100.0,
        "start_lap_fraction": 0.14,
        "end_lap_fraction": 0.16,
        "center_lap_fraction": 0.15,
        "action_time_loss_s": 0.2,
        "evidence_strength": "strong",
        "has_speed_propagation": False,
    }


def test_pair_generation_hard_gates_on_same_supported_variant():
    module = load_module("pair_vehicle_gate", "episode_pair_features.py")

    pairs = module.build_all_cross_session_pairs(
        [
            episode(1, 1, "LMP2_ELMS", setup="a" * 64),
            episode(2, 2, "LMP2_ELMS", setup="b" * 64),
            episode(3, 3, "LMP2_WEC", setup="c" * 64),
            episode(4, 4, None, supported=False),
        ],
        {},
        {},
    )

    assert len(pairs) == 1
    assert pairs[0]["vehicle_variant"] == "LMP2_ELMS"
    assert pairs[0]["same_car_name_raw"] is True
    assert pairs[0]["same_setup_sha256"] is False
