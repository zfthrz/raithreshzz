from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from race_engineer_history_model import (
    filter_history_sessions,
    load_history_detail,
    load_history_sessions,
)
from session_history import default_db_path, initialize_schema


def test_history_cli_default_db_lives_under_data_local():
    """El default de la CLI debe apuntar a data/local, no a la raíz del repo."""
    path = Path(default_db_path())

    assert path.name == "race_engineer_history.duckdb"
    assert "data" in path.parts
    assert "local" in path.parts


def history_database(tmp_path: Path) -> Path:
    path = tmp_path / "history.duckdb"
    connection = duckdb.connect(str(path))
    initialize_schema(connection)
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, source_json_path, source_json_sha256,
            source_database_path, source_analysis_version,
            track, session_type, timestamp_utc, vehicle_variant,
            car_name_raw, weather_conditions, lmu_track_layout,
            same_vehicle, reference_lap, valid_lap_count,
            comparison_count, imported_at_utc
        ) VALUES
            (1, 'fuji.json', 'hash-1', 'Fuji.duckdb', '3.8',
             'Fuji Speedway', 'P', '2026-08-19T19:38:36Z', 'LMP2_ELMS',
             'IDEC Sport #18', 'Clear', 'Fuji Speedway',
             true, 2, 2, 1, '2026-08-19T20:00:00Z'),
            (2, 'monza.json', 'hash-2', 'Monza.duckdb', '3.8',
             'Autodromo Nazionale Monza', 'P', '2026-08-20T19:38:36Z', 'HYPER',
             'Toyota #7', 'Cloudy', 'Autodromo Nazionale Monza',
             true, 3, 3, 2, '2026-08-20T20:00:00Z')
        """
    )
    connection.execute(
        """
        INSERT INTO laps (
            session_id, lap, duration_s, is_valid, is_discarded,
            is_ignored_initial, is_reference
        ) VALUES
            (1, 1, 92.000, true, false, false, false),
            (1, 2, 90.940, true, false, false, true),
            (2, 3, 98.020, true, false, false, true)
        """
    )
    connection.close()
    return path


def test_history_catalogue_is_latest_first_and_uses_reference_lap(tmp_path: Path):
    sessions = load_history_sessions(history_database(tmp_path))

    assert [item.session_id for item in sessions] == [2, 1]
    assert sessions[1].reference_lap == 2
    assert sessions[1].reference_time_s == pytest.approx(90.94)
    assert sessions[1].source_database_path == Path("Fuji.duckdb")


def test_history_filter_requires_every_search_term(tmp_path: Path):
    sessions = load_history_sessions(history_database(tmp_path))

    assert [item.session_id for item in filter_history_sessions(sessions, "fuji lmp2")] == [1]
    assert filter_history_sessions(sessions, "fuji hyper") == []


def test_history_detail_keeps_lap_flags(tmp_path: Path):
    database = history_database(tmp_path)
    session = load_history_sessions(database)[1]

    detail = load_history_detail(database, session)

    assert [lap.lap for lap in detail.laps] == [1, 2]
    assert detail.laps[1].is_reference is True
    assert detail.laps[1].duration_s == pytest.approx(90.94)


def test_history_reader_does_not_create_missing_database(tmp_path: Path):
    missing = tmp_path / "missing.duckdb"
    with pytest.raises(FileNotFoundError):
        load_history_sessions(missing)
    assert not missing.exists()
