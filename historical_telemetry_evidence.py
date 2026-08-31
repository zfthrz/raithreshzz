"""Deterministic, observational evidence over pre-existing track intervals."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import fmean

from race_engineer_track_map import (
    HistoricalTelemetryComparison,
    TrackMapTurn,
    TrackMapZone,
    summarize_telemetry_interval_delta,
)


HISTORICAL_TELEMETRY_EVIDENCE_VERSION = "0.6"


@dataclass(frozen=True)
class HistoricalTelemetryInterval:
    interval_id: str
    label: str
    start_distance_m: float
    end_distance_m: float
    location_type: str | None = None


@dataclass(frozen=True)
class HistoricalTelemetryIntervalEvidence:
    interval_id: str
    label: str
    start_distance_m: float
    end_distance_m: float
    location_type: str | None
    status: str
    coverage_ratio: float
    sample_count: int
    observed_start_distance_m: float | None
    observed_end_distance_m: float | None
    delta_change_s: float | None
    speed_delta_mean_kmh: float | None
    throttle_delta_mean_percent: float | None
    brake_delta_mean_percent: float | None
    steering_signed_delta_mean_percent: float | None
    steering_magnitude_delta_mean_percent: float | None
    steering_magnitude_delta_peak_percent: float | None
    steering_comparable_sample_count: int
    current_steering_total_variation_percent: float | None
    reference_steering_total_variation_percent: float | None
    steering_total_variation_delta_percent: float | None
    current_steering_sign_change_count: int | None
    reference_steering_sign_change_count: int | None
    steering_trace_scope: str
    steering_observed_span_m: float | None
    current_steering_total_variation_per_100m: float | None
    reference_steering_total_variation_per_100m: float | None
    steering_total_variation_delta_per_100m: float | None
    steering_sign_change_relation: str | None


def intervals_from_track_turns(
    turns: tuple[TrackMapTurn, ...],
) -> tuple[HistoricalTelemetryInterval, ...]:
    """Use validated profile turn bounds without changing their geometry."""

    return tuple(
        HistoricalTelemetryInterval(
            interval_id=f"turn:{turn.turn}",
            label=f"T{turn.turn} — {turn.name}" if turn.name else f"T{turn.turn}",
            start_distance_m=turn.start_distance_m,
            end_distance_m=turn.end_distance_m,
            location_type="corner",
        )
        for turn in turns
    )


def intervals_from_track_zones(
    zones: tuple[TrackMapZone, ...],
) -> tuple[HistoricalTelemetryInterval, ...]:
    """Use existing H5.2 zone bounds without reclassifying or merging them."""

    return tuple(
        HistoricalTelemetryInterval(
            interval_id=f"zone:{zone.zone_id}",
            label=zone.label,
            start_distance_m=zone.start_distance_m,
            end_distance_m=zone.end_distance_m,
            location_type=zone.location_type,
        )
        for zone in zones
    )


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _total_variation(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(abs(right - left) for left, right in zip(values, values[1:]))


def _sign_change_count(values: list[float]) -> int | None:
    if not values:
        return None
    signs = [1 if value > 0.0 else -1 for value in values if value != 0.0]
    return sum(left != right for left, right in zip(signs, signs[1:]))


def build_historical_interval_evidence(
    comparison: HistoricalTelemetryComparison,
    intervals: tuple[HistoricalTelemetryInterval, ...],
) -> tuple[HistoricalTelemetryIntervalEvidence, ...]:
    """Aggregate aligned facts without creating zones, thresholds, or actions."""

    results = []
    common_start = comparison.common_start_distance_m
    common_end = comparison.common_end_distance_m
    for interval in intervals:
        start = float(interval.start_distance_m)
        end = float(interval.end_distance_m)
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise ValueError(f"Intervalo histórico inválido: {interval.interval_id}")
        covered_start = max(start, common_start) if common_start is not None else None
        covered_end = min(end, common_end) if common_end is not None else None
        covered_span = (
            max(covered_end - covered_start, 0.0)
            if covered_start is not None and covered_end is not None
            else 0.0
        )
        coverage_ratio = covered_span / (end - start)
        samples = tuple(
            sample
            for sample in comparison.samples
            if start <= sample.distance_m <= end
        )
        if coverage_ratio <= 0.0 or not samples:
            status = "UNAVAILABLE"
        elif math.isclose(coverage_ratio, 1.0):
            status = "FULL_COVERAGE"
        else:
            status = "PARTIAL_COVERAGE"
        interval_delta = (
            summarize_telemetry_interval_delta(
                comparison,
                covered_start,
                covered_end,
            )
            if covered_span > 0.0
            and covered_start is not None
            and covered_end is not None
            else None
        )
        steering_samples = tuple(
            sample
            for sample in samples
            if sample.current_steering_percent is not None
            and sample.reference_steering_percent is not None
        )
        steering_magnitude_deltas = [
            abs(sample.current_steering_percent)
            - abs(sample.reference_steering_percent)
            for sample in steering_samples
        ]
        steering_peak_delta = (
            max(abs(sample.current_steering_percent) for sample in steering_samples)
            - max(
                abs(sample.reference_steering_percent)
                for sample in steering_samples
            )
            if steering_samples
            else None
        )
        current_steering = [
            sample.current_steering_percent for sample in steering_samples
        ]
        reference_steering = [
            sample.reference_steering_percent for sample in steering_samples
        ]
        current_steering_variation = _total_variation(current_steering)
        reference_steering_variation = _total_variation(reference_steering)
        steering_observed_span = (
            steering_samples[-1].distance_m - steering_samples[0].distance_m
            if len(steering_samples) >= 2
            else None
        )
        comparable_corner_trace = (
            interval.location_type == "corner"
            and steering_observed_span is not None
            and steering_observed_span > 0.0
            and current_steering_variation is not None
            and reference_steering_variation is not None
        )
        current_sign_changes = _sign_change_count(current_steering)
        reference_sign_changes = _sign_change_count(reference_steering)
        if comparable_corner_trace:
            steering_trace_scope = "COMPARABLE_CORNER"
            current_variation_per_100m = (
                current_steering_variation * 100.0 / steering_observed_span
            )
            reference_variation_per_100m = (
                reference_steering_variation * 100.0 / steering_observed_span
            )
            if current_sign_changes > reference_sign_changes:
                sign_change_relation = "current_more"
            elif current_sign_changes < reference_sign_changes:
                sign_change_relation = "current_fewer"
            else:
                sign_change_relation = "equal"
        else:
            steering_trace_scope = (
                "OBSERVATIONAL_NON_CORNER"
                if interval.location_type != "corner" and steering_samples
                else "UNAVAILABLE"
            )
            current_variation_per_100m = None
            reference_variation_per_100m = None
            sign_change_relation = None
        results.append(
            HistoricalTelemetryIntervalEvidence(
                interval_id=interval.interval_id,
                label=interval.label,
                start_distance_m=start,
                end_distance_m=end,
                location_type=interval.location_type,
                status=status,
                coverage_ratio=coverage_ratio,
                sample_count=len(samples),
                observed_start_distance_m=(samples[0].distance_m if samples else None),
                observed_end_distance_m=(samples[-1].distance_m if samples else None),
                delta_change_s=(
                    interval_delta.delta_change_s
                    if interval_delta is not None
                    else None
                ),
                speed_delta_mean_kmh=_mean([
                    sample.speed_delta_kmh
                    for sample in samples
                    if sample.speed_delta_kmh is not None
                ]),
                throttle_delta_mean_percent=_mean([
                    sample.throttle_delta_percent
                    for sample in samples
                    if sample.throttle_delta_percent is not None
                ]),
                brake_delta_mean_percent=_mean([
                    sample.brake_delta_percent
                    for sample in samples
                    if sample.brake_delta_percent is not None
                ]),
                steering_signed_delta_mean_percent=_mean([
                    sample.steering_delta_percent
                    for sample in steering_samples
                    if sample.steering_delta_percent is not None
                ]),
                steering_magnitude_delta_mean_percent=_mean(
                    steering_magnitude_deltas
                ),
                steering_magnitude_delta_peak_percent=steering_peak_delta,
                steering_comparable_sample_count=len(steering_samples),
                current_steering_total_variation_percent=(
                    current_steering_variation
                ),
                reference_steering_total_variation_percent=(
                    reference_steering_variation
                ),
                steering_total_variation_delta_percent=(
                    current_steering_variation - reference_steering_variation
                    if current_steering_variation is not None
                    and reference_steering_variation is not None
                    else None
                ),
                current_steering_sign_change_count=(
                    current_sign_changes
                ),
                reference_steering_sign_change_count=(
                    reference_sign_changes
                ),
                steering_trace_scope=steering_trace_scope,
                steering_observed_span_m=(
                    steering_observed_span if comparable_corner_trace else None
                ),
                current_steering_total_variation_per_100m=(
                    current_variation_per_100m
                ),
                reference_steering_total_variation_per_100m=(
                    reference_variation_per_100m
                ),
                steering_total_variation_delta_per_100m=(
                    current_variation_per_100m - reference_variation_per_100m
                    if current_variation_per_100m is not None
                    and reference_variation_per_100m is not None
                    else None
                ),
                steering_sign_change_relation=sign_change_relation,
            )
        )
    return tuple(results)


def build_historical_interval_evidence_document(
    comparison: HistoricalTelemetryComparison,
    intervals: tuple[HistoricalTelemetryInterval, ...],
) -> dict:
    """Return a serializable shadow artifact with explicit authority limits."""

    evidence = build_historical_interval_evidence(comparison, intervals)
    return {
        "metadata": {
            "version": HISTORICAL_TELEMETRY_EVIDENCE_VERSION,
            "status": comparison.status,
            "current_coverage_ratio": comparison.current_coverage_ratio,
            "reference_coverage_ratio": comparison.reference_coverage_ratio,
            "common_start_distance_m": comparison.common_start_distance_m,
            "common_end_distance_m": comparison.common_end_distance_m,
        },
        "contract": {
            "observational_only": True,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
            "llm_called": False,
        },
        "interval_evidence": [asdict(item) for item in evidence],
    }
