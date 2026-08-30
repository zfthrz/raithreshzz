from __future__ import annotations

from pathlib import Path

import duckdb

from race_engineer_statistics import car_display_name, load_history_statistics


def write_history(path: Path) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE sessions (
            session_id BIGINT,
            timestamp_utc VARCHAR,
            track VARCHAR,
            vehicle_family VARCHAR,
            vehicle_variant VARCHAR,
            car_name_raw VARCHAR
        );
        CREATE TABLE laps (
            session_id BIGINT,
            lap INTEGER,
            lap_distance_m DOUBLE,
            is_valid BOOLEAN
        );
        INSERT INTO sessions VALUES
            (1, '2026-07-10T12:00:00Z', 'Spa', 'LMP2', 'LMP2_ELMS', 'Team A #1'),
            (2, '2026-08-11T12:00:00Z', 'Spa', 'LMP2', 'LMP2_WEC', 'Team B #2'),
            (3, '2026-08-20T12:00:00Z', 'Fuji', 'GT3', 'GT3', 'GT Team #3');
        INSERT INTO laps VALUES
            (1, 1, 7000, TRUE),
            (1, 2, 7000, TRUE),
            (1, 3, 1000, FALSE),
            (2, 1, 13600, TRUE),
            (3, 1, 4500, TRUE);
        """
    )
    connection.close()


def test_history_statistics_aggregate_valid_laps_distance_and_months(tmp_path: Path):
    history = tmp_path / "history.duckdb"
    write_history(history)

    result = load_history_statistics(history)

    assert result.overall.session_count == 3
    assert result.overall.valid_lap_count == 4
    assert result.overall.total_distance_km == 32.1
    assert result.overall.favorite_track == "Spa"
    assert result.overall.favorite_category == "LMP2_ELMS"
    assert result.overall.favorite_car == "Oreca 07"
    assert [item.month for item in result.monthly] == ["2026-08", "2026-07"]
    assert result.monthly[0].summary.valid_lap_count == 2
    assert result.monthly[0].summary.total_distance_km == 18.1
    assert result.monthly[1].summary.valid_lap_count == 2
    assert [item.session_id for item in result.sessions] == [3, 2, 1]
    assert result.sessions[0].valid_lap_count == 1
    assert result.sessions[1].total_distance_km == 13.6
    assert [(item.label, item.valid_lap_count) for item in result.track_distribution] == [
        ("Spa", 3),
        ("Fuji", 1),
    ]
    assert result.category_distribution[0].label == "LMP2_ELMS"
    assert result.car_distribution[0].label == "Oreca 07"
    assert result.car_distribution[0].valid_lap_count == 3


def test_lmp2_entries_share_one_car_identity_but_other_classes_fail_closed():
    assert car_display_name("LMP2", "LMP2_ELMS", "IDEC #18") == "Oreca 07"
    assert car_display_name("LMP2", "LMP2_WEC", "DKR #3") == "Oreca 07"
    assert car_display_name("GT3", "GT3", "Manthey #92") == "Manthey #92"
    assert car_display_name("GT3", "GT3", None) == "Auto no identificado"


def test_session_without_timestamp_remains_visible_in_monthly_history(tmp_path: Path):
    history = tmp_path / "history.duckdb"
    write_history(history)
    connection = duckdb.connect(str(history))
    connection.execute(
        "INSERT INTO sessions VALUES (4, NULL, 'Monza', 'GT3', 'GT3', 'Team #4')"
    )
    connection.execute("INSERT INTO laps VALUES (4, 1, 5800, TRUE)")
    connection.close()

    result = load_history_statistics(history)

    assert result.monthly[-1].month == "Sin fecha"
    assert result.monthly[-1].summary.session_count == 1
    assert result.monthly[-1].summary.valid_lap_count == 1
