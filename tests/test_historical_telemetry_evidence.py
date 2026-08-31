from __future__ import annotations

import pytest

from historical_telemetry_evidence import (
    HistoricalTelemetryInterval,
    build_historical_interval_evidence,
    build_historical_interval_evidence_document,
    intervals_from_track_turns,
    intervals_from_track_zones,
)
from race_engineer_track_map import (
    TrackMapTurn,
    TrackMapZone,
    TrackMapPoint,
    build_historical_telemetry_comparison,
)


def comparison_with_reference_coverage(start: float, end: float):
    current = tuple(
        TrackMapPoint(
            0.0, 0.0, distance,
            180.0, 60.0, 20.0, 3, steering_percent=30.0,
        )
        for distance in (0.0, 50.0, 100.0, 150.0, 200.0)
    )
    reference = (
        TrackMapPoint(
            0.0, 0.0, start, 200.0, 40.0, 10.0, 4,
            steering_percent=20.0,
        ),
        TrackMapPoint(
            0.0, 0.0, end, 200.0, 40.0, 10.0, 4,
            steering_percent=20.0,
        ),
    )
    return build_historical_telemetry_comparison(current, reference)


def test_interval_evidence_aggregates_only_existing_interval():
    comparison = comparison_with_reference_coverage(0.0, 200.0)
    interval = HistoricalTelemetryInterval("T1", "Turn 1", 50.0, 150.0)

    evidence = build_historical_interval_evidence(comparison, (interval,))[0]

    assert evidence.status == "FULL_COVERAGE"
    assert evidence.coverage_ratio == 1.0
    assert evidence.sample_count == 3
    assert evidence.observed_start_distance_m == 50.0
    assert evidence.observed_end_distance_m == 150.0
    assert evidence.delta_change_s == pytest.approx(0.2)
    assert evidence.speed_delta_mean_kmh == pytest.approx(-20.0)
    assert evidence.throttle_delta_mean_percent == pytest.approx(20.0)
    assert evidence.brake_delta_mean_percent == pytest.approx(10.0)
    assert evidence.steering_signed_delta_mean_percent == pytest.approx(10.0)
    assert evidence.steering_magnitude_delta_mean_percent == pytest.approx(10.0)
    assert evidence.steering_magnitude_delta_peak_percent == pytest.approx(10.0)
    assert evidence.steering_comparable_sample_count == 3
    assert evidence.current_steering_total_variation_percent == pytest.approx(0.0)
    assert evidence.reference_steering_total_variation_percent == pytest.approx(0.0)
    assert evidence.steering_total_variation_delta_percent == pytest.approx(0.0)
    assert evidence.current_steering_sign_change_count == 0
    assert evidence.reference_steering_sign_change_count == 0


def test_interval_evidence_reports_partial_coverage_without_extrapolation():
    comparison = comparison_with_reference_coverage(100.0, 200.0)
    interval = HistoricalTelemetryInterval("T1", "Turn 1", 50.0, 150.0)

    evidence = build_historical_interval_evidence(comparison, (interval,))[0]

    assert evidence.status == "PARTIAL_COVERAGE"
    assert evidence.coverage_ratio == pytest.approx(0.5)
    assert evidence.observed_start_distance_m == 100.0
    assert evidence.observed_end_distance_m == 150.0
    assert evidence.sample_count == 2


def test_interval_evidence_uses_exact_bounds_when_only_one_native_sample_is_inside():
    comparison = comparison_with_reference_coverage(0.0, 200.0)
    interval = HistoricalTelemetryInterval("narrow", "Narrow", 25.0, 75.0)

    evidence = build_historical_interval_evidence(comparison, (interval,))[0]

    assert evidence.status == "FULL_COVERAGE"
    assert evidence.sample_count == 1
    assert evidence.observed_start_distance_m == 50.0
    assert evidence.observed_end_distance_m == 50.0
    assert evidence.delta_change_s == pytest.approx(0.1)


def test_steering_signed_cancellation_does_not_hide_magnitude_difference():
    current = (
        TrackMapPoint(
            0.0, 0.0, 0.0, 180.0, steering_percent=30.0
        ),
        TrackMapPoint(
            0.0, 0.0, 100.0, 180.0, steering_percent=-30.0
        ),
    )
    reference = (
        TrackMapPoint(
            0.0, 0.0, 0.0, 200.0, steering_percent=20.0
        ),
        TrackMapPoint(
            0.0, 0.0, 100.0, 200.0, steering_percent=-20.0
        ),
    )
    comparison = build_historical_telemetry_comparison(current, reference)
    interval = HistoricalTelemetryInterval(
        "complex", "Complex", 0.0, 100.0, "corner"
    )

    evidence = build_historical_interval_evidence(comparison, (interval,))[0]

    assert evidence.steering_signed_delta_mean_percent == pytest.approx(0.0)
    assert evidence.steering_magnitude_delta_mean_percent == pytest.approx(10.0)
    assert evidence.steering_magnitude_delta_peak_percent == pytest.approx(10.0)
    assert evidence.steering_comparable_sample_count == 2
    assert evidence.current_steering_total_variation_percent == pytest.approx(60.0)
    assert evidence.reference_steering_total_variation_percent == pytest.approx(40.0)
    assert evidence.steering_total_variation_delta_percent == pytest.approx(20.0)
    assert evidence.current_steering_sign_change_count == 1
    assert evidence.reference_steering_sign_change_count == 1
    assert evidence.steering_trace_scope == "COMPARABLE_CORNER"
    assert evidence.steering_observed_span_m == pytest.approx(100.0)
    assert evidence.current_steering_total_variation_per_100m == pytest.approx(60.0)
    assert evidence.reference_steering_total_variation_per_100m == pytest.approx(40.0)
    assert evidence.steering_total_variation_delta_per_100m == pytest.approx(20.0)
    assert evidence.steering_sign_change_relation == "equal"


def test_normalized_steering_trace_fails_closed_outside_corners():
    comparison = comparison_with_reference_coverage(0.0, 200.0)
    interval = HistoricalTelemetryInterval(
        "transition", "Transition", 50.0, 150.0, "between_corners"
    )

    evidence = build_historical_interval_evidence(comparison, (interval,))[0]

    assert evidence.steering_trace_scope == "OBSERVATIONAL_NON_CORNER"
    assert evidence.steering_observed_span_m is None
    assert evidence.current_steering_total_variation_per_100m is None
    assert evidence.reference_steering_total_variation_per_100m is None
    assert evidence.steering_total_variation_delta_per_100m is None
    assert evidence.steering_sign_change_relation is None


def test_interval_evidence_fails_closed_without_coverage():
    comparison = comparison_with_reference_coverage(150.0, 200.0)
    interval = HistoricalTelemetryInterval("T1", "Turn 1", 0.0, 100.0)

    evidence = build_historical_interval_evidence(comparison, (interval,))[0]

    assert evidence.status == "UNAVAILABLE"
    assert evidence.coverage_ratio == 0.0
    assert evidence.sample_count == 0
    assert evidence.delta_change_s is None
    assert evidence.speed_delta_mean_kmh is None


def test_interval_evidence_rejects_invalid_intervals_and_preserves_inputs():
    comparison = comparison_with_reference_coverage(0.0, 200.0)
    intervals = (HistoricalTelemetryInterval("bad", "Bad", 100.0, 100.0),)

    with pytest.raises(ValueError, match="bad"):
        build_historical_interval_evidence(comparison, intervals)

    assert intervals[0].start_distance_m == 100.0
    assert comparison.samples[0].distance_m == 0.0


def test_existing_turns_and_zones_keep_their_validated_bounds():
    turns = (TrackMapTurn(1, "First", 10.0, 20.0, 30.0),)
    zones = (TrackMapZone("zone_001", "Loss 1", "loss", 40.0, 70.0, 0.2),)

    turn_interval = intervals_from_track_turns(turns)[0]
    zone_interval = intervals_from_track_zones(zones)[0]

    assert turn_interval == HistoricalTelemetryInterval(
        "turn:1", "T1 — First", 10.0, 30.0, "corner"
    )
    assert zone_interval == HistoricalTelemetryInterval(
        "zone:zone_001", "Loss 1", 40.0, 70.0
    )


def test_evidence_document_is_json_ready_and_has_no_action_authority():
    comparison = comparison_with_reference_coverage(0.0, 200.0)
    intervals = (
        HistoricalTelemetryInterval("T1", "Turn 1", 50.0, 150.0, "corner"),
    )

    document = build_historical_interval_evidence_document(comparison, intervals)

    assert document["metadata"]["version"] == "0.6"
    assert document["metadata"]["status"] == "FULL_COMMON_COVERAGE"
    assert document["contract"] == {
        "observational_only": True,
        "affects_next_stint_plan": False,
        "historical_actions_authorized": False,
        "llm_called": False,
    }
    assert document["interval_evidence"][0]["interval_id"] == "T1"
    assert document["interval_evidence"][0]["delta_change_s"] == pytest.approx(0.2)
