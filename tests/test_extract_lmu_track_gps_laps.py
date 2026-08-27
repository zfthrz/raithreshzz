from __future__ import annotations

import math

import pytest

from extract_lmu_track_gps import (
    assign_laps_from_boundaries,
    choose_default_lap,
    detect_laps_from_distance,
    group_indices_by_lap,
    lap_metrics,
    repair_lap_distance_boundary_sample,
)
from race_engineer_track_map import (
    _complete_lap_metrics,
    _duration_match_available,
    _select_map_lap,
)


def test_assign_laps_from_boundaries_uses_exact_boundary_as_new_lap():
    laps = assign_laps_from_boundaries(
        [0.0, 0.999, 1.0, 1.5, 2.0, 3.0],
        [2.0, 1.0, 2.0],
    )

    assert laps == [0, 0, 0, 0, 1, 1]


def test_assign_laps_from_boundaries_is_deterministic_for_unsorted_duplicates():
    times = [0.0, 5.0, 10.0, 15.0]

    assert assign_laps_from_boundaries(times, [10.0, 5.0, 10.0]) == [0, 0, 1, 1]
    assert assign_laps_from_boundaries(times, [5.0, 10.0]) == [0, 0, 1, 1]
    assert assign_laps_from_boundaries(times, [math.nan, math.inf, -math.inf]) == [0, 0, 0, 0]


def test_detect_laps_from_distance_uses_strong_resets_only():
    laps = detect_laps_from_distance(
        [0.0, 100.0, 99.9, 700.0, 100.0, 800.0, 100.0, 900.0, 0.0]
    )

    assert laps == [0, 0, 0, 0, 1, 1, 2, 2, 3]


def test_detect_laps_from_distance_tolerates_missing_and_nonfinite_values():
    laps = detect_laps_from_distance([None, math.nan, math.inf, 100.0, 50.0, 600.0])

    assert laps == [0, 0, 0, 0, 0, 0]


def test_repair_boundary_changes_only_first_sample_when_conditions_match():
    lap_dist = [700.0, 50.0, 80.0, 100.0]

    repair = repair_lap_distance_boundary_sample([0, 1, 2, 3], lap_dist)

    assert repair is not None
    assert lap_dist == [0.0, 50.0, 80.0, 100.0]
    assert repair["sample_index"] == 0
    assert repair["original_lap_dist_m"] == 700.0


@pytest.mark.parametrize(
    "lap_dist",
    ([700.0, 101.0, 80.0], [500.0, 50.0, 80.0]),
)
def test_repair_boundary_does_not_repair_without_start_or_threshold(
    lap_dist: list[float],
):
    original = list(lap_dist)

    assert repair_lap_distance_boundary_sample([0, 1, 2], lap_dist) is None
    assert lap_dist == original


def test_group_indices_by_lap_preserves_temporal_indices_and_all_samples():
    laps = [1, 0, 1, 2, 0, 2, 1]

    grouped = group_indices_by_lap(laps)

    assert grouped == {1: [0, 2, 6], 0: [1, 4], 2: [3, 5]}
    assert sorted(index for indices in grouped.values() for index in indices) == list(range(7))


def test_lap_metrics_reports_duration_coverage_distance_and_incomplete_gps():
    metrics = lap_metrics(
        [0, 1, 2, 3],
        [0.0, 0.001, None, 0.003],
        [0.0, 0.0, None, 0.0],
        [10.0, None, 30.0, 40.0],
        [5.0, 6.0, 7.0, 8.0],
    )

    assert metrics["duration_s"] == 3.0
    assert metrics["gps_coverage"] == pytest.approx(0.5)
    assert metrics["lap_dist_min_m"] == 10.0
    assert metrics["lap_dist_max_m"] == 40.0
    assert metrics["lap_dist_span_m"] == 30.0
    assert metrics["sample_count"] == 4
    assert metrics["gps_path_m"] > 100.0


def test_complete_lap_metrics_applies_distance_and_gps_path_thresholds():
    metrics = {
        0: {"gps_coverage": 0.90, "duration_s": 40.0, "lap_dist_max_m": 1200.0, "gps_path_m": 1000.0},
        1: {"gps_coverage": 0.90, "duration_s": 40.0, "lap_dist_max_m": 1080.0, "gps_path_m": 850.0},
        2: {"gps_coverage": 0.90, "duration_s": 40.0, "lap_dist_max_m": 1079.0, "gps_path_m": 850.0},
        3: {"gps_coverage": 0.90, "duration_s": 40.0, "lap_dist_max_m": 1200.0, "gps_path_m": 849.0},
        4: {"gps_coverage": 0.90, "duration_s": 29.9, "lap_dist_max_m": 1200.0, "gps_path_m": 1000.0},
        5: {"gps_coverage": 0.69, "duration_s": 40.0, "lap_dist_max_m": 1200.0, "gps_path_m": 1000.0},
    }

    assert _complete_lap_metrics(metrics) == {0: metrics[0], 1: metrics[1]}


def test_select_map_lap_prefers_duration_with_five_percent_or_three_second_tolerance():
    metrics = {
        0: {"duration_s": 40.0},
        1: {"duration_s": 42.0},
    }

    assert _select_map_lap(metrics, preferred_lap=0, preferred_duration_s=42.0) == (
        1,
        "REFERENCE_DURATION_MATCH",
    )
    assert _select_map_lap(metrics, preferred_lap=0, preferred_duration_s=46.0) == (
        0,
        "EXACT_GPS_LAP",
    )


def test_select_map_lap_falls_back_deterministically_when_preferred_lap_missing():
    metrics = {
        0: {"gps_coverage": 0.8, "duration_s": 40.0, "lap_dist_max_m": 2000.0, "gps_path_m": 2000.0},
        1: {"gps_coverage": 0.9, "duration_s": 40.0, "lap_dist_max_m": 2000.0, "gps_path_m": 2000.0},
    }

    assert _select_map_lap(metrics, preferred_lap=9, preferred_duration_s=None) == (
        1,
        "AUTOMATIC_COMPLETE_LAP",
    )


def test_duration_match_available_supports_conservative_distance_reset_fallback():
    stale_event_metrics = {0: {"duration_s": 219.85}}
    distance_reset_metrics = {
        0: {"duration_s": 131.65},
        1: {"duration_s": 103.15},
        2: {"duration_s": 102.45},
    }

    assert not _duration_match_available(stale_event_metrics, 102.52)
    assert _duration_match_available(distance_reset_metrics, 102.52)
    assert not _duration_match_available(distance_reset_metrics, None)


def test_choose_default_lap_prefers_the_highest_deterministic_score():
    metrics = {
        0: {"gps_coverage": 0.8, "duration_s": 40.0, "lap_dist_max_m": 2000.0, "gps_path_m": 2000.0},
        1: {"gps_coverage": 0.9, "duration_s": 40.0, "lap_dist_max_m": 2000.0, "gps_path_m": 2000.0},
    }

    assert choose_default_lap(metrics) == 1
