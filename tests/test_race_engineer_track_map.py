from __future__ import annotations

import json
import math
from pathlib import Path

import duckdb

from race_engineer_track_map import (
    TrackMapPoint,
    fit_track_points,
    load_track_map,
    load_track_zones,
    zone_for_distance,
    zone_point_ranges,
)


def make_gps_database(path: Path) -> Path:
    connection = duckdb.connect(str(path))
    try:
        connection.execute("CREATE TABLE metadata(key VARCHAR, value VARCHAR)")
        connection.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [("TrackName", "Test Circuit"), ("TrackLayout", "Grand Prix")],
        )
        for table in ("GPS Time", "GPS Latitude", "GPS Longitude", "Lap Dist"):
            connection.execute(f'CREATE TABLE "{table}"(ts DOUBLE, value DOUBLE)')
        rows = []
        for second in range(81):
            phase = (second % 40) / 40.0 * 2.0 * math.pi
            rows.append(
                (
                    float(second),
                    -34.0 + 0.001 * math.sin(phase),
                    -58.0 + 0.001 * math.cos(phase),
                    float((second % 40) * 125),
                )
            )
        connection.executemany(
            'INSERT INTO "GPS Time" VALUES (?, ?)',
            [(time, time) for time, *_ in rows],
        )
        connection.executemany(
            'INSERT INTO "GPS Latitude" VALUES (?, ?)',
            [(time, latitude) for time, latitude, _, _ in rows],
        )
        connection.executemany(
            'INSERT INTO "GPS Longitude" VALUES (?, ?)',
            [(time, longitude) for time, _, longitude, _ in rows],
        )
        connection.executemany(
            'INSERT INTO "Lap Dist" VALUES (?, ?)',
            [(time, distance) for time, _, _, distance in rows],
        )
        connection.execute('CREATE TABLE "Lap"(ts DOUBLE)')
        connection.executemany('INSERT INTO "Lap" VALUES (?)', [(0.0,), (40.0,), (80.0,)])
    finally:
        connection.close()
    return path


def test_load_track_map_reconstructs_preferred_lap_read_only(tmp_path: Path):
    database = make_gps_database(tmp_path / "session.duckdb")
    size_before = database.stat().st_size

    result = load_track_map(database, preferred_lap=1, target_hz=5.0)

    assert result.database_path == database.resolve()
    assert result.track == "Test Circuit"
    assert result.layout == "Grand Prix"
    assert result.lap == 1
    assert result.requested_lap == 1
    assert result.selection_reason == "EXACT_GPS_LAP"
    assert len(result.points) >= 190
    assert result.width_m > 100
    assert result.height_m > 100
    assert any(point.lap_distance_m is not None for point in result.points)
    assert database.stat().st_size == size_before


def test_incomplete_reference_group_is_replaced_by_complete_duration_match(
    tmp_path: Path,
):
    database = make_gps_database(tmp_path / "session.duckdb")

    result = load_track_map(
        database,
        preferred_lap=2,
        preferred_duration_s=39.8,
        target_hz=5.0,
    )

    assert result.requested_lap == 2
    assert result.lap in {0, 1}
    assert result.lap != 2
    assert result.selection_reason == "REFERENCE_DURATION_MATCH"
    assert abs(result.duration_s - 39.8) < 0.01
    assert result.width_m > 100
    assert result.height_m > 100


def test_load_track_map_reports_missing_gps_channels(tmp_path: Path):
    database = tmp_path / "missing.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("CREATE TABLE metadata(key VARCHAR, value VARCHAR)")
    connection.close()

    try:
        load_track_map(database)
    except ValueError as exc:
        assert "Faltan canales GPS" in str(exc)
    else:
        raise AssertionError("una telemetría sin GPS produjo un mapa")


def test_fit_track_points_preserves_aspect_ratio_and_north_orientation():
    points = (
        TrackMapPoint(0.0, 0.0, 0.0),
        TrackMapPoint(100.0, 0.0, 100.0),
        TrackMapPoint(100.0, 50.0, 150.0),
    )

    fitted = fit_track_points(points, width_px=300, height_px=200, padding_px=25)

    assert fitted[0] == (25.0, 162.5)
    assert fitted[1] == (275.0, 162.5)
    assert fitted[2] == (275.0, 37.5)


def test_h5_2_zones_are_loaded_in_track_order_and_mapped_by_lap_distance(
    tmp_path: Path,
):
    source = tmp_path / "h5_2.json"
    source.write_text(
        json.dumps(
            {
                "spatial_comparison": {
                    "zone_summaries": [
                        {
                            "type": "gain",
                            "start_distance": 100,
                            "end_distance": 180,
                            "delta_change": -0.18,
                            "location": {"label": "T2"},
                        },
                        {
                            "type": "loss",
                            "start_distance": 20,
                            "end_distance": 80,
                            "delta_change": 0.24,
                            "location": {"label": "T1"},
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    zones = load_track_zones(source)
    points = tuple(
        TrackMapPoint(float(distance), 0.0, float(distance))
        for distance in (0, 20, 50, 80, 100, 140, 180, 220)
    )

    assert [zone.label for zone in zones] == ["T1", "T2"]
    assert zones[0].kind == "loss"
    assert zones[1].kind == "gain"
    assert zone_for_distance(zones, 50).label == "T1"
    assert zone_for_distance(zones, 90) is None
    assert zone_point_ranges(points, zones[0]) == ((1, 3),)
    assert zone_point_ranges(points, zones[1]) == ((4, 6),)


def test_invalid_h5_2_zone_boundaries_are_ignored(tmp_path: Path):
    source = tmp_path / "h5_2.json"
    source.write_text(
        json.dumps(
            {
                "spatial_comparison": {
                    "zone_summaries": [
                        {"start_distance": 100, "end_distance": 50},
                        {"start_distance": "missing", "end_distance": 80},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_track_zones(source) == ()
