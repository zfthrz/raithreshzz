from __future__ import annotations

import json
import math
from pathlib import Path

import duckdb
import pytest

from race_engineer_track_map import (
    TrackMapPoint,
    build_track_telemetry_chart,
    fit_track_points,
    transform_fitted_track_points,
    load_track_map,
    load_track_priorities,
    load_track_zones,
    nearest_fitted_point_index,
    pan_distance_window,
    pan_track_canvas_view,
    priority_for_distance,
    summarize_track_interval,
    telemetry_chart_x_for_distance,
    zoom_distance_window,
    zoom_track_canvas_view,
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
        for table in (
            "GPS Time",
            "GPS Latitude",
            "GPS Longitude",
            "Lap Dist",
            "Ground Speed",
            "Throttle Pos",
            "Brake Pos",
        ):
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
        connection.executemany(
            'INSERT INTO "Ground Speed" VALUES (?, ?)',
            [(time, 100.0 + time) for time, *_ in rows],
        )
        connection.executemany(
            'INSERT INTO "Throttle Pos" VALUES (?, ?)',
            [(time, float(time % 101)) for time, *_ in rows],
        )
        connection.executemany(
            'INSERT INTO "Brake Pos" VALUES (?, ?)',
            [(time, 25.0 if 45.0 <= time <= 50.0 else 0.0) for time, *_ in rows],
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
    assert all(point.speed_kmh is not None for point in result.points)
    assert all(point.throttle_percent is not None for point in result.points)
    assert all(point.brake_percent is not None for point in result.points)
    assert database.stat().st_size == size_before


def test_track_interval_summary_uses_only_aligned_samples_inside_zone():
    points = tuple(
        TrackMapPoint(
            float(distance),
            0.0,
            float(distance),
            speed_kmh=speed,
            throttle_percent=throttle,
            brake_percent=brake,
        )
        for distance, speed, throttle, brake in (
            (0, 100, 100, 0),
            (50, 120, 80, 10),
            (100, 140, 40, 30),
            (150, 160, 20, 50),
            (200, 180, 100, 0),
        )
    )

    summary = summarize_track_interval(points, 50, 150)

    assert summary is not None
    assert summary.sample_count == 3
    assert summary.speed_min_kmh == 120
    assert summary.speed_mean_kmh == 140
    assert summary.speed_max_kmh == 160
    assert summary.throttle_mean_percent == pytest.approx(140 / 3)
    assert summary.throttle_max_percent == 80
    assert summary.brake_mean_percent == 30
    assert summary.brake_max_percent == 50


def test_track_interval_summary_handles_missing_optional_channels():
    points = (TrackMapPoint(0.0, 0.0, 10.0), TrackMapPoint(1.0, 0.0, 20.0))

    summary = summarize_track_interval(points, 0, 30)

    assert summary is not None
    assert summary.sample_count == 2
    assert summary.speed_mean_kmh is None
    assert summary.throttle_mean_percent is None
    assert summary.brake_mean_percent is None


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


def test_nearest_map_point_supports_hit_radius_and_unconstrained_drag():
    fitted = ((10.0, 10.0), (40.0, 10.0), (80.0, 50.0))

    assert nearest_fitted_point_index(
        fitted, x_px=43.0, y_px=12.0, max_distance_px=18.0
    ) == 1
    assert nearest_fitted_point_index(
        fitted, x_px=65.0, y_px=75.0, max_distance_px=18.0
    ) is None
    assert nearest_fitted_point_index(
        fitted, x_px=65.0, y_px=75.0, max_distance_px=None
    ) == 2


def test_map_zoom_keeps_pointer_anchor_and_transforms_selection_geometry():
    scale, offset_x, offset_y = zoom_track_canvas_view(
        1.0, 0.0, 0.0,
        anchor_x_px=100.0,
        anchor_y_px=50.0,
        factor=2.0,
    )
    assert (scale, offset_x, offset_y) == (2.0, -100.0, -50.0)
    transformed = transform_fitted_track_points(
        ((100.0, 50.0), (150.0, 75.0)),
        scale=scale,
        offset_x_px=offset_x,
        offset_y_px=offset_y,
    )
    assert transformed == ((100.0, 50.0), (200.0, 100.0))


def test_map_zoom_clamps_and_full_reset_removes_offsets():
    assert zoom_track_canvas_view(
        1.0, -10.0, -20.0,
        anchor_x_px=40.0,
        anchor_y_px=30.0,
        factor=0.5,
    ) == (1.0, 0.0, 0.0)
    assert zoom_track_canvas_view(
        8.0, -100.0, -100.0,
        anchor_x_px=40.0,
        anchor_y_px=30.0,
        factor=2.0,
    )[0] == 8.0


def test_map_pan_moves_zoomed_view_and_keeps_track_partially_visible():
    fitted = ((25.0, 25.0), (275.0, 175.0))
    assert pan_track_canvas_view(
        fitted, 2.0, -100.0, -50.0,
        delta_x_px=30.0,
        delta_y_px=-20.0,
        width_px=300.0,
        height_px=200.0,
    ) == (-70.0, -70.0)
    assert pan_track_canvas_view(
        fitted, 2.0, 0.0, 0.0,
        delta_x_px=10000.0,
        delta_y_px=10000.0,
        width_px=300.0,
        height_px=200.0,
    ) == (210.0, 110.0)


def test_map_pan_is_disabled_at_full_view():
    assert pan_track_canvas_view(
        ((25.0, 25.0), (275.0, 175.0)), 1.0, -10.0, -20.0,
        delta_x_px=50.0,
        delta_y_px=50.0,
        width_px=300.0,
        height_px=200.0,
    ) == (0.0, 0.0)


def test_telemetry_chart_uses_shared_distance_axis_and_three_fixed_lanes():
    points = (
        TrackMapPoint(0.0, 0.0, 0.0, 0.0, 0.0, 100.0),
        TrackMapPoint(1.0, 0.0, 100.0, 200.0, 100.0, 0.0),
    )

    chart = build_track_telemetry_chart(points, width_px=200, height_px=132)

    assert chart is not None
    assert chart.speed_max_kmh == 200
    assert chart.speed == ((74.0, 48.0), (182.0, 12.0))
    assert chart.throttle == ((74.0, 84.0), (182.0, 48.0))
    assert chart.brake == ((74.0, 84.0), (182.0, 120.0))
    assert telemetry_chart_x_for_distance(chart, 50.0, width_px=200) == 128.0


def test_telemetry_chart_requires_distance_but_tolerates_missing_channels():
    without_channels = (
        TrackMapPoint(0.0, 0.0, 0.0),
        TrackMapPoint(1.0, 0.0, 100.0),
    )

    chart = build_track_telemetry_chart(without_channels, width_px=200, height_px=132)

    assert chart is not None
    assert chart.speed == ()
    assert chart.throttle == ()
    assert chart.brake == ()
    assert build_track_telemetry_chart(
        (TrackMapPoint(0.0, 0.0, None),), width_px=200, height_px=132
    ) is None


def test_telemetry_chart_can_render_only_a_zoomed_distance_window():
    points = tuple(
        TrackMapPoint(float(distance), 0.0, float(distance), float(distance + 100), 50, 10)
        for distance in (0, 25, 50, 75, 100)
    )

    chart = build_track_telemetry_chart(
        points,
        width_px=200,
        height_px=132,
        start_distance_m=25,
        end_distance_m=75,
    )

    assert chart is not None
    assert chart.distance_min_m == 25
    assert chart.distance_max_m == 75
    assert len(chart.speed) == 3
    assert chart.speed[0][0] == 74
    assert chart.speed[-1][0] == 182


def test_zoom_and_pan_distance_windows_remain_inside_complete_lap():
    assert zoom_distance_window(
        0,
        1000,
        full_start_m=0,
        full_end_m=1000,
        anchor_m=500,
        factor=0.5,
    ) == (250, 750)
    assert pan_distance_window(
        250,
        750,
        full_start_m=0,
        full_end_m=1000,
        delta_m=400,
    ) == (500, 1000)
    assert pan_distance_window(
        250,
        750,
        full_start_m=0,
        full_end_m=1000,
        delta_m=-400,
    ) == (0, 500)


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


def test_validated_next_stint_priorities_map_to_gps_intervals(tmp_path: Path):
    source = tmp_path / "debrief.json"
    source.write_text(
        json.dumps(
            {
                "session_coaching_facts": {
                    "next_stint_focus": {
                        "status": "ACTIVE",
                        "focus_count": 1,
                        "items": [{"plan_label": "B"}],
                    },
                    "next_stint_plan": [
                        {
                            "plan_label": "B",
                            "start_distance_m": 500,
                            "end_distance_m": 560,
                            "track_location": {"label": "T5"},
                            "driver_cues": [{"text": "Sostené el acelerador"}],
                        },
                        {
                            "plan_label": "A",
                            "start_distance_m": 100,
                            "end_distance_m": 180,
                            "track_location": {"label": "T1"},
                            "driver_cues": ["Frená hacia la referencia"],
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    points = tuple(
        TrackMapPoint(float(distance), 0.0, float(distance))
        for distance in (0, 100, 140, 180, 300, 500, 530, 560, 700)
    )

    priorities = load_track_priorities(source)

    assert [priority.priority_id for priority in priorities] == ["A", "B"]
    assert priorities[0].label == "T1"
    assert priorities[0].cues == ("Frená hacia la referencia",)
    assert priorities[0].is_focus is False
    assert priorities[1].is_focus is True
    assert priority_for_distance(priorities, 530).priority_id == "B"
    assert priority_for_distance(priorities, 400) is None
    assert zone_point_ranges(points, priorities[0]) == ((1, 3),)
    assert zone_point_ranges(points, priorities[1]) == ((5, 7),)
