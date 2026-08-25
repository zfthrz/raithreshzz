from __future__ import annotations

import math

import pytest

from extract_lmu_track_gps import (
    align_channel,
    build_master_times,
    deduplicate_time_series,
    infer_times_from_index,
    interpolate_series,
    repair_lap_distance_boundary_sample,
)


@pytest.mark.parametrize(
    ("target_hz", "expected_dt"),
    ((10.0, 0.1), (20.0, 0.05), (50.0, 0.02)),
)
def test_build_master_times_uses_floor_grid_without_passing_end(
    target_hz: float, expected_dt: float
):
    master_times, source = build_master_times(
        {"GPS Time": {"values": [0.0, 2.0]}}, target_hz
    )

    expected_count = max(2, int(math.floor(2.0 / expected_dt)) + 1)
    assert source == "GPS Time.value"
    assert len(master_times) == expected_count
    assert master_times[0] == 0.0
    assert master_times[-1] <= 2.0
    assert all(right > left for left, right in zip(master_times, master_times[1:]))
    assert all(
        right - left == pytest.approx(expected_dt)
        for left, right in zip(master_times, master_times[1:])
    )


def test_build_master_times_has_same_start_for_supported_rates():
    grids = [
        build_master_times({"GPS Time": {"values": [0.0, 2.0]}}, target_hz)[0]
        for target_hz in (10.0, 20.0, 50.0)
    ]

    assert [grid[0] for grid in grids] == [0.0, 0.0, 0.0]


def test_interpolate_series_preserves_physical_time_and_clamps_extremes():
    source_times = [0.0, 1.0, 2.0]
    source_values = [0.0, 100.0, 200.0]

    assert interpolate_series(source_times, source_values, [-1.0, 0.0, 0.5, 2.0, 3.0]) == pytest.approx(
        [0.0, 0.0, 50.0, 200.0, 200.0]
    )

    shared_times = [0.0, 1.0, 2.0]
    for target_hz in (10.0, 20.0, 50.0):
        grid, _ = build_master_times(
            {"GPS Time": {"values": [0.0, 2.0]}}, target_hz
        )
        values = interpolate_series(source_times, source_values, grid)
        shared_values = interpolate_series(source_times, source_values, shared_times)
        assert values[0] == pytest.approx(shared_values[0])
        assert values[len(values) // 2] == pytest.approx(shared_values[1])
        assert values[-1] == pytest.approx(shared_values[2])
        assert all(value is not None and math.isfinite(value) for value in values)


def test_align_channel_with_timestamps_keeps_channel_aligned_to_master_grid():
    master_times, _ = build_master_times(
        {"GPS Time": {"values": [0.0, 2.0]}}, 10.0
    )
    aligned = align_channel(
        {"times": [0.0, 1.0, 2.0], "values": [0.0, 100.0, 200.0]},
        master_times,
        [0.0, 2.0],
    )

    assert aligned[0] == pytest.approx(0.0)
    assert aligned[10] == pytest.approx(100.0)
    assert aligned[-1] == pytest.approx(200.0)
    assert all(value is not None and math.isfinite(value) for value in aligned)


def test_channels_keep_same_physical_values_at_shared_timestamps():
    source = {"times": [0.0, 1.0, 2.0], "values": [0.0, 100.0, 200.0]}

    for target_hz in (10.0, 20.0, 50.0):
        master_times, _ = build_master_times(
            {"GPS Time": {"values": [0.0, 2.0]}}, target_hz
        )
        channels = [
            align_channel(source, master_times, [0.0, 2.0])
            for _ in ("speed", "throttle", "brake")
        ]
        shared_indices = [round(target_hz * second) for second in (0.0, 1.0, 2.0)]
        for channel in channels:
            assert [channel[index] for index in shared_indices] == pytest.approx(
                [0.0, 100.0, 200.0]
            )
        assert [channels[0][index] for index in shared_indices] == pytest.approx(
            [channels[1][index] for index in shared_indices]
        )
        assert [channels[0][index] for index in shared_indices] == pytest.approx(
            [channels[2][index] for index in shared_indices]
        )


def test_infer_times_from_index_spans_reference_range_monotonically():
    inferred = infer_times_from_index(5, [10.0, 20.0, 30.0])

    assert inferred == pytest.approx([10.0, 15.0, 20.0, 25.0, 30.0])
    assert inferred[0] == 10.0
    assert inferred[-1] == 30.0
    assert all(right > left for left, right in zip(inferred, inferred[1:]))


def test_infer_times_from_index_keeps_reference_range_for_all_target_rates():
    for target_hz in (10.0, 20.0, 50.0):
        master_times, _ = build_master_times(
            {"GPS Time": {"values": [0.0, 2.0]}}, target_hz
        )
        aligned = align_channel(
            {"times": None, "values": [0.0, 100.0, 200.0]},
            master_times,
            [0.0, 2.0],
        )
        assert aligned[0] == pytest.approx(0.0)
        assert aligned[-1] == pytest.approx(200.0)


def test_deduplicate_time_series_keeps_last_value_for_duplicate_timestamp():
    times, values = deduplicate_time_series(
        [0.0, 1.0, 1.0, 0.5, 2.0], [0.0, 100.0, 150.0, 50.0, 200.0]
    )

    assert times == [0.0, 1.0, 2.0]
    assert values == [0.0, 150.0, 200.0]
    assert all(right > left for left, right in zip(times, times[1:]))
    assert interpolate_series(times, values, [0.5, 1.5]) == pytest.approx(
        [75.0, 175.0]
    )


def test_lap_dist_reset_is_not_resampled_as_a_physical_ramp():
    master_times, _ = build_master_times(
        {"GPS Time": {"values": [0.0, 3.0]}}, 10.0
    )
    aligned = align_channel(
        {
            "table": "Lap Dist",
            "times": [0.0, 1.0, 2.0, 2.01, 3.0],
            "values": [0.0, 50.0, 100.0, 4050.0, 0.0],
        },
        master_times,
        master_times,
    )

    assert aligned[20] == pytest.approx(100.0)
    assert aligned[21] == pytest.approx(4050.0)
    assert all(
        not (100.0 < float(value) < 4050.0)
        for value in aligned
        if value is not None
    )


def test_repair_lap_distance_boundary_only_repairs_first_interpolated_sample():
    lap_dist = [600.0, 50.0, 100.0]

    repair = repair_lap_distance_boundary_sample([0, 1, 2], lap_dist)

    assert repair is not None
    assert lap_dist == [0.0, 50.0, 100.0]
    assert repair["reason"] == "boundary_linear_interpolation_across_lap_dist_reset"

    unchanged = [0.0, 600.0, 50.0]
    assert repair_lap_distance_boundary_sample([0, 1, 2], unchanged) is None
    assert unchanged == [0.0, 600.0, 50.0]
