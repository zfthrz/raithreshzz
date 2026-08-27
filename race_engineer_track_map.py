"""Read-only GPS track-map model for the Race Engineer desktop GUI."""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import duckdb

from cross_session_zone_localization import find_validated_track_profile

from extract_lmu_track_gps import (
    LAP_DISTANCE_RESET_THRESHOLD_M,
    REQUIRED_GPS_TABLES,
    align_channel,
    assign_laps_from_boundaries,
    build_master_times,
    choose_default_lap,
    csv_rows_for_lap,
    detect_laps_from_distance,
    group_indices_by_lap,
    lap_metrics,
    read_lap_event_times,
    read_metadata,
    read_value_table,
    repair_lap_distance_boundary_sample,
    table_names,
)


TRACK_MAP_VERSION = "0.7"


@dataclass(frozen=True)
class TrackMapPoint:
    x_m: float
    y_m: float
    lap_distance_m: float | None
    speed_kmh: float | None = None
    throttle_percent: float | None = None
    brake_percent: float | None = None
    gear: int | None = None


@dataclass(frozen=True)
class TrackMapLapOption:
    lap: int
    duration_s: float


@dataclass(frozen=True)
class TrackMapData:
    database_path: Path
    track: str
    layout: str
    lap: int
    requested_lap: int | None
    selection_reason: str
    duration_s: float
    points: tuple[TrackMapPoint, ...]
    width_m: float
    height_m: float


@dataclass(frozen=True)
class TrackMapZone:
    zone_id: str
    label: str
    kind: str
    start_distance_m: float
    end_distance_m: float
    delta_change_s: float | None


@dataclass(frozen=True)
class TrackMapPriority:
    priority_id: str
    label: str
    start_distance_m: float
    end_distance_m: float
    cues: tuple[str, ...]
    is_focus: bool = False


@dataclass(frozen=True)
class TrackMapLocation:
    label: str
    location_type: str
    profile_id: str


@dataclass(frozen=True)
class TrackMapTurn:
    turn: int
    name: str
    start_distance_m: float
    apex_distance_m: float
    end_distance_m: float


@dataclass(frozen=True)
class TrackTelemetrySummary:
    start_distance_m: float
    end_distance_m: float
    sample_count: int
    speed_min_kmh: float | None
    speed_mean_kmh: float | None
    speed_max_kmh: float | None
    throttle_mean_percent: float | None
    throttle_max_percent: float | None
    brake_mean_percent: float | None
    brake_max_percent: float | None


@dataclass(frozen=True)
class TrackTelemetryChart:
    speed_max_kmh: float
    speed: tuple[tuple[float, float], ...]
    throttle: tuple[tuple[float, float], ...]
    brake: tuple[tuple[float, float], ...]
    distance_min_m: float
    distance_max_m: float
    gear: tuple[tuple[float, float], ...] = ()
    gear_max: int = 1


@dataclass(frozen=True)
class AlignedTelemetrySample:
    distance_m: float
    current_speed_kmh: float | None
    reference_speed_kmh: float | None
    speed_delta_kmh: float | None
    current_throttle_percent: float | None
    reference_throttle_percent: float | None
    throttle_delta_percent: float | None
    current_brake_percent: float | None
    reference_brake_percent: float | None
    brake_delta_percent: float | None
    current_gear: int | None
    reference_gear: int | None
    accumulated_delta_s: float | None


@dataclass(frozen=True)
class HistoricalTelemetryComparison:
    status: str
    current_start_distance_m: float | None
    current_end_distance_m: float | None
    reference_start_distance_m: float | None
    reference_end_distance_m: float | None
    common_start_distance_m: float | None
    common_end_distance_m: float | None
    current_coverage_ratio: float
    reference_coverage_ratio: float
    samples: tuple[AlignedTelemetrySample, ...]


def list_track_map_laps(
    database_path: Path,
    *,
    target_hz: float = 20.0,
    connect_factory: Callable = duckdb.connect,
) -> tuple[TrackMapLapOption, ...]:
    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if target_hz <= 0 or target_hz > 50:
        raise ValueError("La frecuencia del mapa debe estar entre 0 y 50 Hz.")

    connection = connect_factory(str(database), read_only=True)
    try:
        tables = table_names(connection)
        missing = [name for name in REQUIRED_GPS_TABLES if name not in tables]
        if missing:
            raise ValueError("Faltan canales GPS: " + ", ".join(missing))
        channels = {
            name: read_value_table(connection, name)
            for name in ("GPS Time", "GPS Latitude", "GPS Longitude", "Lap Dist")
            if name in tables
        }
        master_times, _ = build_master_times(channels, target_hz)
        gps_time_reference = [
            float(value)
            for value in channels.get("GPS Time", {}).get("values", [])
        ] or master_times
        latitude = align_channel(
            channels.get("GPS Latitude"), master_times, gps_time_reference
        )
        longitude = align_channel(
            channels.get("GPS Longitude"), master_times, gps_time_reference
        )
        lap_distance = align_channel(
            channels.get("Lap Dist"), master_times, gps_time_reference
        )
        boundaries = read_lap_event_times(connection, tables)
        laps = (
            assign_laps_from_boundaries(master_times, boundaries)
            if boundaries
            else detect_laps_from_distance(lap_distance)
        )
        groups = group_indices_by_lap(laps)
        for indices in groups.values():
            repair_lap_distance_boundary_sample(indices, lap_distance)
        metrics = {
            lap: lap_metrics(indices, latitude, longitude, lap_distance, master_times)
            for lap, indices in groups.items()
        }
        complete = _complete_lap_metrics(metrics)
        return tuple(
            TrackMapLapOption(
                lap=int(lap),
                duration_s=float(complete[lap]["duration_s"]),
            )
            for lap in sorted(complete)
        )
    finally:
        connection.close()


def load_track_map(
    database_path: Path,
    *,
    preferred_lap: int | None = None,
    preferred_duration_s: float | None = None,
    target_hz: float = 20.0,
    connect_factory: Callable = duckdb.connect,
) -> TrackMapData:
    """Extract one GPS lap without modifying or exporting the source DuckDB."""

    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if target_hz <= 0 or target_hz > 50:
        raise ValueError("La frecuencia del mapa debe estar entre 0 y 50 Hz.")

    connection = connect_factory(str(database), read_only=True)
    try:
        tables = table_names(connection)
        missing = [name for name in REQUIRED_GPS_TABLES if name not in tables]
        if missing:
            raise ValueError("Faltan canales GPS: " + ", ".join(missing))

        channel_names = (
            "GPS Time",
            "GPS Latitude",
            "GPS Longitude",
            "Lap Dist",
            "Ground Speed",
            "GPS Speed",
            "Throttle Pos",
            "Brake Pos",
            "Gear",
        )
        channels = {
            name: read_value_table(connection, name)
            for name in channel_names
            if name in tables
        }
        master_times, _ = build_master_times(channels, target_hz)
        gps_time_reference = [
            float(value)
            for value in channels.get("GPS Time", {}).get("values", [])
        ] or master_times
        latitude = align_channel(
            channels.get("GPS Latitude"), master_times, gps_time_reference
        )
        longitude = align_channel(
            channels.get("GPS Longitude"), master_times, gps_time_reference
        )
        lap_distance = align_channel(
            channels.get("Lap Dist"), master_times, gps_time_reference
        )
        speed_channel = channels.get("Ground Speed") or channels.get("GPS Speed")
        speed = align_channel(speed_channel, master_times, gps_time_reference)
        throttle = align_channel(
            channels.get("Throttle Pos"), master_times, gps_time_reference
        )
        brake = align_channel(
            channels.get("Brake Pos"), master_times, gps_time_reference
        )
        gear = align_channel(
            channels.get("Gear"), master_times, gps_time_reference
        )
        boundaries = read_lap_event_times(connection, tables)
        laps = (
            assign_laps_from_boundaries(master_times, boundaries)
            if boundaries
            else detect_laps_from_distance(lap_distance)
        )
        groups = group_indices_by_lap(laps)
        if not groups:
            raise ValueError("No se pudieron reconstruir vueltas GPS.")
        for indices in groups.values():
            repair_lap_distance_boundary_sample(indices, lap_distance)
        metrics = {
            lap: lap_metrics(indices, latitude, longitude, lap_distance, master_times)
            for lap, indices in groups.items()
        }
        complete_metrics = _complete_lap_metrics(metrics)
        if not complete_metrics:
            raise ValueError(
                "No hay una vuelta GPS geométricamente completa en esta telemetría."
            )
        selected_lap, selection_reason = _select_map_lap(
            complete_metrics,
            preferred_lap=preferred_lap,
            preferred_duration_s=preferred_duration_s,
        )
        rows = csv_rows_for_lap(
            groups[selected_lap],
            master_times,
            latitude,
            longitude,
            lap_distance,
            selected_lap,
        )
        if len(rows) < 10:
            raise ValueError("La vuelta seleccionada tiene muy pocos puntos GPS válidos.")
        time_indices = {value: index for index, value in enumerate(master_times)}
        points = []
        for row in rows:
            master_index = time_indices.get(float(row["session_time_s"]))
            points.append(
                TrackMapPoint(
                    x_m=float(row["x_east_m"]),
                    y_m=float(row["y_north_m"]),
                    lap_distance_m=(
                        None
                        if row["lap_distance_m"] is None
                        else float(row["lap_distance_m"])
                    ),
                    speed_kmh=_finite_at(speed, master_index),
                    throttle_percent=_finite_at(throttle, master_index),
                    brake_percent=_finite_at(brake, master_index),
                    gear=_gear_at(gear, master_index),
                )
            )
        points = tuple(points)
        xs = [point.x_m for point in points]
        ys = [point.y_m for point in points]
        metadata = read_metadata(connection)
        return TrackMapData(
            database_path=database,
            track=str(metadata.get("TrackName") or database.stem.split("_P_", 1)[0]),
            layout=str(metadata.get("TrackLayout") or metadata.get("TrackName") or "—"),
            lap=int(selected_lap),
            requested_lap=preferred_lap,
            selection_reason=selection_reason,
            duration_s=float(metrics[selected_lap]["duration_s"]),
            points=points,
            width_m=max(xs) - min(xs),
            height_m=max(ys) - min(ys),
        )
    finally:
        connection.close()


def _finite_at(values: list[float | None], index: int | None) -> float | None:
    if index is None or index < 0 or index >= len(values):
        return None
    value = values[index]
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _gear_at(values: list[float | None], index: int | None) -> int | None:
    value = _finite_at(values, index)
    if value is None:
        return None
    gear = int(round(value))
    return gear if 0 <= gear <= 20 else None


def telemetry_gear_scale(*point_sets: tuple[TrackMapPoint, ...]) -> int:
    gears = [
        int(point.gear)
        for points in point_sets
        for point in points
        if point.gear is not None and 0 <= int(point.gear) <= 20
    ]
    return max(1, max(gears, default=1))


def summarize_track_interval(
    points: tuple[TrackMapPoint, ...],
    start_distance_m: float,
    end_distance_m: float,
) -> TrackTelemetrySummary | None:
    """Summarize aligned native channels inside one validated distance interval."""

    if not math.isfinite(start_distance_m) or not math.isfinite(end_distance_m):
        return None
    if end_distance_m < start_distance_m:
        return None
    selected = tuple(
        point
        for point in points
        if point.lap_distance_m is not None
        and start_distance_m <= point.lap_distance_m <= end_distance_m
    )
    if not selected:
        return None

    def values(attribute: str) -> list[float]:
        return [
            float(value)
            for point in selected
            if (value := getattr(point, attribute)) is not None
            and math.isfinite(float(value))
        ]

    speeds = values("speed_kmh")
    throttles = values("throttle_percent")
    brakes = values("brake_percent")

    def mean(items: list[float]) -> float | None:
        return sum(items) / len(items) if items else None

    return TrackTelemetrySummary(
        start_distance_m=float(start_distance_m),
        end_distance_m=float(end_distance_m),
        sample_count=len(selected),
        speed_min_kmh=min(speeds) if speeds else None,
        speed_mean_kmh=mean(speeds),
        speed_max_kmh=max(speeds) if speeds else None,
        throttle_mean_percent=mean(throttles),
        throttle_max_percent=max(throttles) if throttles else None,
        brake_mean_percent=mean(brakes),
        brake_max_percent=max(brakes) if brakes else None,
    )


def _complete_lap_metrics(metrics: dict[int, dict]) -> dict[int, dict]:
    """Reject short tails/outlaps before a GPS trace can become a circuit map."""

    viable = {
        lap: values
        for lap, values in metrics.items()
        if values["gps_coverage"] >= 0.70
        and values["duration_s"] >= 30.0
        and (values["lap_dist_max_m"] or 0.0) >= 1000.0
    }
    if not viable:
        return {}
    maximum_lap_distance = max(
        float(values["lap_dist_max_m"] or 0.0) for values in viable.values()
    )
    maximum_gps_path = max(float(values["gps_path_m"] or 0.0) for values in viable.values())
    return {
        lap: values
        for lap, values in viable.items()
        if float(values["lap_dist_max_m"] or 0.0) >= 0.90 * maximum_lap_distance
        and float(values["gps_path_m"] or 0.0) >= 0.85 * maximum_gps_path
    }


def _select_map_lap(
    complete_metrics: dict[int, dict],
    *,
    preferred_lap: int | None,
    preferred_duration_s: float | None,
) -> tuple[int, str]:
    """Match analysis lap numbering to GPS groups, preferring duration evidence."""

    if preferred_duration_s is not None and preferred_duration_s > 0:
        closest = min(
            complete_metrics,
            key=lambda lap: abs(
                float(complete_metrics[lap]["duration_s"]) - preferred_duration_s
            ),
        )
        difference = abs(
            float(complete_metrics[closest]["duration_s"]) - preferred_duration_s
        )
        tolerance = max(3.0, preferred_duration_s * 0.05)
        if difference <= tolerance:
            return closest, "REFERENCE_DURATION_MATCH"
    if preferred_lap is not None and preferred_lap in complete_metrics:
        return preferred_lap, "EXACT_GPS_LAP"
    return choose_default_lap(complete_metrics), "AUTOMATIC_COMPLETE_LAP"


def fit_track_points(
    points: tuple[TrackMapPoint, ...],
    *,
    width_px: int,
    height_px: int,
    padding_px: int = 28,
) -> tuple[tuple[float, float], ...]:
    """Fit local GPS points into a canvas while preserving map aspect ratio."""

    if not points or width_px <= 0 or height_px <= 0:
        return ()
    min_x = min(point.x_m for point in points)
    max_x = max(point.x_m for point in points)
    min_y = min(point.y_m for point in points)
    max_y = max(point.y_m for point in points)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    usable_width = max(1.0, width_px - 2.0 * padding_px)
    usable_height = max(1.0, height_px - 2.0 * padding_px)
    scale = min(usable_width / span_x, usable_height / span_y)
    drawn_width = span_x * scale
    drawn_height = span_y * scale
    offset_x = (width_px - drawn_width) / 2.0
    offset_y = (height_px - drawn_height) / 2.0
    return tuple(
        (
            offset_x + (point.x_m - min_x) * scale,
            offset_y + (max_y - point.y_m) * scale,
        )
        for point in points
    )


def transform_fitted_track_points(
    points: tuple[tuple[float, float], ...],
    *,
    scale: float,
    offset_x_px: float,
    offset_y_px: float,
) -> tuple[tuple[float, float], ...]:
    """Apply a read-only canvas view transform to already fitted GPS points."""
    if scale < 1.0:
        raise ValueError("El zoom del mapa no puede ser menor que 1.")
    return tuple(
        (x * scale + offset_x_px, y * scale + offset_y_px)
        for x, y in points
    )


def zoom_track_canvas_view(
    scale: float,
    offset_x_px: float,
    offset_y_px: float,
    *,
    anchor_x_px: float,
    anchor_y_px: float,
    factor: float,
    min_scale: float = 1.0,
    max_scale: float = 8.0,
) -> tuple[float, float, float]:
    """Zoom around a canvas pointer while keeping its map position stationary."""
    if factor <= 0 or min_scale <= 0 or max_scale < min_scale:
        raise ValueError("Parámetros de zoom del mapa inválidos.")
    new_scale = min(max(scale * factor, min_scale), max_scale)
    if new_scale == min_scale:
        return min_scale, 0.0, 0.0
    applied = new_scale / scale
    return (
        new_scale,
        anchor_x_px - (anchor_x_px - offset_x_px) * applied,
        anchor_y_px - (anchor_y_px - offset_y_px) * applied,
    )


def pan_track_canvas_view(
    fitted_points: tuple[tuple[float, float], ...],
    scale: float,
    offset_x_px: float,
    offset_y_px: float,
    *,
    delta_x_px: float,
    delta_y_px: float,
    width_px: float,
    height_px: float,
    visible_margin_px: float = 40.0,
) -> tuple[float, float]:
    """Pan a zoomed map while keeping part of the circuit inside the viewport."""
    if scale <= 1.0 or not fitted_points:
        return 0.0, 0.0
    if width_px <= 0 or height_px <= 0 or visible_margin_px < 0:
        raise ValueError("Parámetros de desplazamiento del mapa inválidos.")
    min_x = min(point[0] for point in fitted_points)
    max_x = max(point[0] for point in fitted_points)
    min_y = min(point[1] for point in fitted_points)
    max_y = max(point[1] for point in fitted_points)
    proposed_x = offset_x_px + delta_x_px
    proposed_y = offset_y_px + delta_y_px
    lower_x = visible_margin_px - max_x * scale
    upper_x = width_px - visible_margin_px - min_x * scale
    lower_y = visible_margin_px - max_y * scale
    upper_y = height_px - visible_margin_px - min_y * scale
    return (
        min(max(proposed_x, lower_x), upper_x),
        min(max(proposed_y, lower_y), upper_y),
    )


def focus_track_canvas_view(
    fitted_interval_points: tuple[tuple[float, float], ...],
    *,
    width_px: float,
    height_px: float,
    padding_px: float = 55.0,
    max_scale: float = 8.0,
) -> tuple[float, float, float]:
    """Center and enlarge one validated distance interval on the GPS canvas."""
    if not fitted_interval_points:
        return 1.0, 0.0, 0.0
    if width_px <= 0 or height_px <= 0 or padding_px < 0 or max_scale < 1.0:
        raise ValueError("Parámetros de enfoque del mapa inválidos.")
    min_x = min(point[0] for point in fitted_interval_points)
    max_x = max(point[0] for point in fitted_interval_points)
    min_y = min(point[1] for point in fitted_interval_points)
    max_y = max(point[1] for point in fitted_interval_points)
    available_width = max(width_px - 2.0 * padding_px, 1.0)
    available_height = max(height_px - 2.0 * padding_px, 1.0)
    interval_width = max_x - min_x
    interval_height = max_y - min_y
    scale_candidates = [max_scale]
    if interval_width > 1e-9:
        scale_candidates.append(available_width / interval_width)
    if interval_height > 1e-9:
        scale_candidates.append(available_height / interval_height)
    scale = min(max(min(scale_candidates), 1.0), max_scale)
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    return (
        scale,
        width_px / 2.0 - center_x * scale,
        height_px / 2.0 - center_y * scale,
    )


def nearest_fitted_point_index(
    fitted_points: tuple[tuple[float, float], ...],
    *,
    x_px: float,
    y_px: float,
    max_distance_px: float | None = None,
) -> int | None:
    """Return the nearest rendered GPS point, optionally constrained by hit radius."""

    if not fitted_points:
        return None
    index, nearest = min(
        enumerate(fitted_points),
        key=lambda item: (item[1][0] - x_px) ** 2 + (item[1][1] - y_px) ** 2,
    )
    if max_distance_px is not None:
        if max_distance_px < 0:
            raise ValueError("La distancia máxima de selección no puede ser negativa.")
        distance_sq = (nearest[0] - x_px) ** 2 + (nearest[1] - y_px) ** 2
        if distance_sq > max_distance_px**2:
            return None
    return index


def telemetry_speed_scale(
    *point_sets: tuple[TrackMapPoint, ...],
) -> float:
    """Return one deterministic speed ceiling shared by multiple laps."""
    speeds = [
        float(point.speed_kmh)
        for points in point_sets
        for point in points
        if point.speed_kmh is not None and math.isfinite(point.speed_kmh)
    ]
    observed = max(speeds, default=0.0)
    return max(100.0, math.ceil(observed / 50.0) * 50.0)


def _monotonic_telemetry_points(
    points: tuple[TrackMapPoint, ...],
) -> tuple[TrackMapPoint, ...]:
    """Keep the widest monotonic lap segment and one sample per distance."""

    segments = [[]]
    seen_distances = set()
    previous_distance = None
    for point in points:
        distance = point.lap_distance_m
        if distance is None or not math.isfinite(distance):
            continue
        distance = float(distance)
        if previous_distance is not None:
            backward_jump = previous_distance - distance
            if backward_jump > LAP_DISTANCE_RESET_THRESHOLD_M or backward_jump > 5.0:
                # LMU can prepend one or more repaired boundary samples from the
                # prior lap. Preserve segments, then select physical coverage.
                segments.append([])
                seen_distances.clear()
                previous_distance = None
            elif backward_jump > 0.0:
                continue
        previous_distance = distance
        if distance in seen_distances:
            continue
        seen_distances.add(distance)
        segments[-1].append(point)
    populated = [segment for segment in segments if segment]
    if not populated:
        return ()
    widest = max(
        populated,
        key=lambda segment: (
            float(segment[-1].lap_distance_m) - float(segment[0].lap_distance_m),
            len(segment),
        ),
    )
    return tuple(widest)


def _linear_value(
    left: TrackMapPoint,
    right: TrackMapPoint,
    distance_m: float,
    attribute: str,
) -> float | None:
    left_value = getattr(left, attribute)
    right_value = getattr(right, attribute)
    if (
        left_value is None
        or right_value is None
        or not math.isfinite(left_value)
        or not math.isfinite(right_value)
    ):
        return None
    left_distance = float(left.lap_distance_m)
    right_distance = float(right.lap_distance_m)
    if right_distance <= left_distance:
        return float(left_value)
    ratio = (distance_m - left_distance) / (right_distance - left_distance)
    return float(left_value) + ratio * (float(right_value) - float(left_value))


def _difference(current: float | None, reference: float | None) -> float | None:
    if current is None or reference is None:
        return None
    return current - reference


def build_historical_telemetry_comparison(
    current_points: tuple[TrackMapPoint, ...],
    reference_points: tuple[TrackMapPoint, ...],
) -> HistoricalTelemetryComparison:
    """Align laps without extrapolating beyond observed distance coverage.

    Current native distances form the grid. Continuous reference channels are
    linearly interpolated; gear holds the preceding discrete reference value.
    Accumulated delta integrates ``dt = 3.6 * dx / speed_kmh`` trapezoidally.
    """

    current = _monotonic_telemetry_points(current_points)
    reference = _monotonic_telemetry_points(reference_points)
    if len(current) < 2 or len(reference) < 2:
        return HistoricalTelemetryComparison(
            "NO_COMMON_COVERAGE", None, None, None, None, None, None, 0.0, 0.0, ()
        )
    current_start = float(current[0].lap_distance_m)
    current_end = float(current[-1].lap_distance_m)
    reference_start = float(reference[0].lap_distance_m)
    reference_end = float(reference[-1].lap_distance_m)
    common_start = max(current_start, reference_start)
    common_end = min(current_end, reference_end)
    if common_end <= common_start:
        return HistoricalTelemetryComparison(
            "NO_COMMON_COVERAGE", current_start, current_end,
            reference_start, reference_end, None, None, 0.0, 0.0, (),
        )

    current_span = current_end - current_start
    reference_span = reference_end - reference_start
    common_span = common_end - common_start
    current_ratio = common_span / current_span if current_span > 0 else 0.0
    reference_ratio = common_span / reference_span if reference_span > 0 else 0.0
    status = (
        "FULL_COMMON_COVERAGE"
        if math.isclose(current_ratio, 1.0) and math.isclose(reference_ratio, 1.0)
        else "PARTIAL_COMMON_COVERAGE"
    )
    reference_distances = [float(point.lap_distance_m) for point in reference]
    aligned = []
    accumulated_delta = 0.0
    previous = None
    for point in current:
        distance = float(point.lap_distance_m)
        if not common_start <= distance <= common_end:
            continue
        right_index = bisect_right(reference_distances, distance)
        if right_index == 0:
            continue
        if right_index == len(reference):
            if not math.isclose(distance, reference_end):
                continue
            left = right = reference[-1]
        else:
            left = reference[right_index - 1]
            right = reference[right_index]
        reference_speed = _linear_value(left, right, distance, "speed_kmh")
        reference_throttle = _linear_value(left, right, distance, "throttle_percent")
        reference_brake = _linear_value(left, right, distance, "brake_percent")
        current_speed = float(point.speed_kmh) if point.speed_kmh is not None and math.isfinite(point.speed_kmh) else None
        current_throttle = float(point.throttle_percent) if point.throttle_percent is not None and math.isfinite(point.throttle_percent) else None
        current_brake = float(point.brake_percent) if point.brake_percent is not None and math.isfinite(point.brake_percent) else None
        delta_value = 0.0 if previous is None else None
        if previous is not None:
            dx = distance - previous[0]
            speeds = (previous[1], current_speed, previous[2], reference_speed)
            if dx >= 0 and all(value is not None and value > 0 for value in speeds):
                current_dt = 3.6 * dx * (1.0 / previous[1] + 1.0 / current_speed) / 2.0
                reference_dt = 3.6 * dx * (1.0 / previous[2] + 1.0 / reference_speed) / 2.0
                accumulated_delta += current_dt - reference_dt
                delta_value = accumulated_delta
        aligned.append(
            AlignedTelemetrySample(
                distance, current_speed, reference_speed,
                _difference(current_speed, reference_speed),
                current_throttle, reference_throttle,
                _difference(current_throttle, reference_throttle),
                current_brake, reference_brake,
                _difference(current_brake, reference_brake),
                point.gear, left.gear, delta_value,
            )
        )
        previous = (distance, current_speed, reference_speed)
    return HistoricalTelemetryComparison(
        status, current_start, current_end, reference_start, reference_end,
        common_start, common_end, current_ratio, reference_ratio, tuple(aligned),
    )


def historical_telemetry_uncovered_ranges(
    comparison: HistoricalTelemetryComparison,
    *,
    axis_start_distance_m: float,
    axis_end_distance_m: float,
) -> tuple[tuple[float, float], ...]:
    """Return visible axis intervals lacking historical telemetry coverage."""

    if axis_end_distance_m <= axis_start_distance_m:
        return ()
    common_start = comparison.common_start_distance_m
    common_end = comparison.common_end_distance_m
    if common_start is None or common_end is None:
        return ((axis_start_distance_m, axis_end_distance_m),)
    visible_start = max(axis_start_distance_m, common_start)
    visible_end = min(axis_end_distance_m, common_end)
    if visible_end <= visible_start:
        return ((axis_start_distance_m, axis_end_distance_m),)
    ranges = []
    if axis_start_distance_m < visible_start:
        ranges.append((axis_start_distance_m, visible_start))
    if visible_end < axis_end_distance_m:
        ranges.append((visible_end, axis_end_distance_m))
    return tuple(ranges)


def historical_telemetry_sample_at_distance(
    comparison: HistoricalTelemetryComparison,
    distance_m: float,
) -> AlignedTelemetrySample | None:
    """Return the closest aligned sample, but never outside common coverage."""

    if (
        comparison.common_start_distance_m is None
        or comparison.common_end_distance_m is None
        or not comparison.common_start_distance_m
        <= distance_m
        <= comparison.common_end_distance_m
        or not comparison.samples
    ):
        return None
    return min(comparison.samples, key=lambda sample: abs(sample.distance_m - distance_m))


def build_track_telemetry_chart(
    points: tuple[TrackMapPoint, ...],
    *,
    width_px: int,
    height_px: int,
    left_px: int = 74,
    right_px: int = 18,
    top_px: int = 12,
    bottom_px: int = 12,
    start_distance_m: float | None = None,
    end_distance_m: float | None = None,
    speed_max_kmh: float | None = None,
    axis_start_distance_m: float | None = None,
    axis_end_distance_m: float | None = None,
    include_gear: bool = False,
    gear_max: int | None = None,
) -> TrackTelemetryChart | None:
    """Fit native channels into three deterministic distance-based chart lanes."""

    valid_distances = [
        float(point.lap_distance_m)
        for point in points
        if point.lap_distance_m is not None and math.isfinite(point.lap_distance_m)
    ]
    if not valid_distances or width_px <= left_px + right_px or height_px <= top_px + bottom_px:
        return None
    full_distance_min = min(valid_distances)
    full_distance_max = max(valid_distances)
    if full_distance_max <= full_distance_min:
        return None
    requested_start = (
        full_distance_min
        if start_distance_m is None
        else max(full_distance_min, float(start_distance_m))
    )
    requested_end = (
        full_distance_max
        if end_distance_m is None
        else min(full_distance_max, float(end_distance_m))
    )
    distance_min = (
        requested_start
        if axis_start_distance_m is None
        else float(axis_start_distance_m)
    )
    distance_max = (
        requested_end
        if axis_end_distance_m is None
        else float(axis_end_distance_m)
    )
    if not math.isfinite(distance_min) or not math.isfinite(distance_max):
        return None
    if distance_max <= distance_min:
        return None
    speeds = [
        float(point.speed_kmh)
        for point in points
        if point.speed_kmh is not None and math.isfinite(point.speed_kmh)
    ]
    observed_speed_max = max(speeds, default=0.0)
    automatic_speed_max = max(
        100.0,
        math.ceil(observed_speed_max / 50.0) * 50.0,
    )
    speed_max = (
        automatic_speed_max
        if speed_max_kmh is None
        else max(100.0, float(speed_max_kmh))
    )
    usable_width = float(width_px - left_px - right_px)
    usable_height = float(height_px - top_px - bottom_px)
    lane_count = 4 if include_gear else 3
    lane_height = usable_height / float(lane_count)
    resolved_gear_max = (
        telemetry_gear_scale(points)
        if gear_max is None
        else max(1, int(gear_max))
    )

    def x_for(distance: float) -> float:
        return left_px + (distance - distance_min) / (distance_max - distance_min) * usable_width

    def series(attribute: str, lane: int, maximum: float) -> tuple[tuple[float, float], ...]:
        result = []
        lane_top = top_px + lane * lane_height
        # Points are temporal: a decrease marks a second pass, while exact
        # duplicates keep the first valid sample without averaging telemetry.
        previous_distance = None
        seen_distances = set()
        for point in points:
            distance = point.lap_distance_m
            if distance is None or not math.isfinite(distance):
                continue
            distance = float(distance)
            if previous_distance is not None:
                backward_jump = previous_distance - distance
                if backward_jump > LAP_DISTANCE_RESET_THRESHOLD_M:
                    break
                if backward_jump > 5.0:
                    break
                if backward_jump > 0.0:
                    continue
            previous_distance = distance
            value = getattr(point, attribute)
            if value is None or not math.isfinite(value):
                continue
            if distance in seen_distances:
                continue
            seen_distances.add(distance)
            if not requested_start <= distance <= requested_end:
                continue
            normalized = min(max(float(value) / maximum, 0.0), 1.0)
            result.append((x_for(distance), lane_top + (1.0 - normalized) * lane_height))
        return tuple(result)

    gear_points = ()
    if include_gear:
        result = []
        lane_top = top_px + 3 * lane_height
        previous_distance = None
        previous_y = None
        seen_distances = set()
        for point in points:
            distance = point.lap_distance_m
            if distance is None or not math.isfinite(distance):
                continue
            distance = float(distance)
            if previous_distance is not None:
                backward_jump = previous_distance - distance
                if backward_jump > LAP_DISTANCE_RESET_THRESHOLD_M:
                    break
                if backward_jump > 5.0:
                    break
                if backward_jump > 0.0:
                    continue
            previous_distance = distance
            if distance in seen_distances:
                continue
            seen_distances.add(distance)
            if not requested_start <= distance <= requested_end or point.gear is None:
                continue
            gear_value = min(max(int(point.gear), 0), resolved_gear_max)
            x = x_for(distance)
            y = lane_top + (1.0 - gear_value / resolved_gear_max) * lane_height
            if previous_y is not None:
                result.append((x, previous_y))
            result.append((x, y))
            previous_y = y
        gear_points = tuple(result)

    return TrackTelemetryChart(
        speed_max_kmh=speed_max,
        speed=series("speed_kmh", 0, speed_max),
        throttle=series("throttle_percent", 1, 100.0),
        brake=series("brake_percent", 2, 100.0),
        distance_min_m=distance_min,
        distance_max_m=distance_max,
        gear=gear_points,
        gear_max=resolved_gear_max,
    )


def telemetry_chart_x_for_distance(
    chart: TrackTelemetryChart,
    distance_m: float,
    *,
    width_px: int,
    left_px: int = 74,
    right_px: int = 18,
) -> float:
    """Map LMU lap distance to the shared x axis used by the telemetry chart."""

    span = chart.distance_max_m - chart.distance_min_m
    if span <= 0 or width_px <= left_px + right_px:
        return float(left_px)
    clamped = min(max(distance_m, chart.distance_min_m), chart.distance_max_m)
    return left_px + (clamped - chart.distance_min_m) / span * (
        width_px - left_px - right_px
    )


def telemetry_chart_distance_for_x(
    chart: TrackTelemetryChart,
    x_px: float,
    *,
    width_px: int,
    left_px: int = 74,
    right_px: int = 18,
) -> float | None:
    """Map a pointer x coordinate back to distance on the visible chart axis."""

    usable_width = width_px - left_px - right_px
    span = chart.distance_max_m - chart.distance_min_m
    if usable_width <= 0 or span <= 0 or not left_px <= x_px <= width_px - right_px:
        return None
    ratio = (float(x_px) - left_px) / usable_width
    return chart.distance_min_m + ratio * span


def zoom_distance_window(
    current_start_m: float,
    current_end_m: float,
    *,
    full_start_m: float,
    full_end_m: float,
    anchor_m: float,
    factor: float,
    minimum_span_m: float = 100.0,
) -> tuple[float, float]:
    """Zoom a distance window around an anchor while staying inside the full lap."""

    full_span = full_end_m - full_start_m
    current_span = current_end_m - current_start_m
    if full_span <= 0 or current_span <= 0 or factor <= 0:
        raise ValueError("La ventana de telemetría no es válida.")
    minimum_span = min(max(minimum_span_m, 1.0), full_span)
    new_span = min(max(current_span * factor, minimum_span), full_span)
    anchor = min(max(anchor_m, current_start_m), current_end_m)
    anchor_ratio = (anchor - current_start_m) / current_span
    new_start = anchor - anchor_ratio * new_span
    new_start = min(max(new_start, full_start_m), full_end_m - new_span)
    return new_start, new_start + new_span


def pan_distance_window(
    start_m: float,
    end_m: float,
    *,
    full_start_m: float,
    full_end_m: float,
    delta_m: float,
) -> tuple[float, float]:
    """Move a zoom window without changing its span or leaving the full lap."""

    span = end_m - start_m
    full_span = full_end_m - full_start_m
    if span <= 0 or full_span <= 0:
        raise ValueError("La ventana de telemetría no es válida.")
    if span >= full_span:
        return full_start_m, full_end_m
    new_start = min(max(start_m + delta_m, full_start_m), full_end_m - span)
    return new_start, new_start + span


def load_track_zones(path: Path | None) -> tuple[TrackMapZone, ...]:
    """Load deterministic H5.2 distance zones without granting coaching authority."""

    if path is None:
        return ()
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("El artefacto H5.2 no contiene un objeto JSON.")
    spatial = payload.get("spatial_comparison")
    if not isinstance(spatial, dict):
        return ()
    values = spatial.get("zone_summaries")
    if not isinstance(values, list):
        return ()
    zones = []
    for index, value in enumerate(values, start=1):
        if not isinstance(value, dict):
            continue
        try:
            start = float(value.get("start_distance"))
            end = float(value.get("end_distance"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            continue
        location = value.get("location")
        location = location if isinstance(location, dict) else {}
        delta_value = value.get("delta_change")
        try:
            delta = float(delta_value)
            if not math.isfinite(delta):
                delta = None
        except (TypeError, ValueError):
            delta = None
        zones.append(
            TrackMapZone(
                zone_id=str(value.get("zone_id") or f"zone_{index:03d}"),
                label=str(location.get("label") or f"{start:.0f}-{end:.0f} m"),
                kind=str(value.get("type") or "observation").casefold(),
                start_distance_m=start,
                end_distance_m=end,
                delta_change_s=delta,
            )
        )
    zones.sort(key=lambda zone: (zone.start_distance_m, zone.end_distance_m, zone.zone_id))
    return tuple(zones)


def load_track_profile(
    profile_dir: Path,
    *,
    track: str,
    layout: str,
) -> dict[str, Any] | None:
    """Load only the exact validated production profile for one GPS map."""
    profile, _path = find_validated_track_profile(
        Path(profile_dir),
        track=track,
        layout=layout,
    )
    return profile


def profile_location_for_distance(
    profile: dict[str, Any] | None,
    distance_m: float | None,
) -> TrackMapLocation | None:
    """Resolve a point without inventing a name outside a validated profile."""
    if profile is None or distance_m is None or not math.isfinite(distance_m):
        return None
    from track_location import resolve_interval

    # The canonical resolver requires a meaningful overlap (8 m) before naming
    # a turn. A local 20 m inspection window satisfies that gate without turning
    # the single cursor position into a broad telemetry zone.
    result = resolve_interval(
        profile,
        max(0.0, distance_m - 10.0),
        distance_m + 10.0,
    )
    label = str(result.get("label") or "").strip()
    profile_id = str(result.get("profile_id") or "").strip()
    location_type = str(result.get("location_type") or "").strip()
    if not label or not profile_id or not location_type:
        return None
    return TrackMapLocation(label, location_type, profile_id)


def profile_turns(profile: dict[str, Any] | None) -> tuple[TrackMapTurn, ...]:
    """Project validated profile turns into a small read-only map layer."""
    if profile is None:
        return ()
    result = []
    for value in profile.get("turns") or []:
        if not isinstance(value, dict):
            continue
        try:
            turn = int(value["turn"])
            name = str(value["name"]).strip()
            start = float(value["start_m"])
            apex = float(value["apex_m"])
            end = float(value["end_m"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            turn <= 0
            or not name
            or not all(math.isfinite(item) for item in (start, apex, end))
            or not start <= apex <= end
            or end <= start
        ):
            continue
        result.append(TrackMapTurn(turn, name, start, apex, end))
    result.sort(key=lambda item: (item.start_distance_m, item.turn))
    return tuple(result)


def point_index_for_distance(
    points: tuple[TrackMapPoint, ...],
    distance_m: float,
) -> int | None:
    candidates = (
        (abs(point.lap_distance_m - distance_m), index)
        for index, point in enumerate(points)
        if point.lap_distance_m is not None
    )
    return min(candidates, default=(math.inf, None))[1]


def turn_for_number(
    turns: tuple[TrackMapTurn, ...],
    turn_number: int,
) -> TrackMapTurn | None:
    for turn in turns:
        if turn.turn == turn_number:
            return turn
    return None


def zone_for_distance(
    zones: tuple[TrackMapZone, ...],
    distance_m: float | None,
) -> TrackMapZone | None:
    if distance_m is None:
        return None
    for zone in zones:
        if zone.start_distance_m <= distance_m <= zone.end_distance_m:
            return zone
    return None


def load_track_priorities(path: Path | None) -> tuple[TrackMapPriority, ...]:
    """Load validated next-stint plan intervals from an exact debrief artifact."""

    if path is None:
        return ()
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("El debrief no contiene un objeto JSON.")
    facts = payload.get("session_coaching_facts")
    facts = facts if isinstance(facts, dict) else {}
    values = facts.get("next_stint_plan")
    if not isinstance(values, list):
        return ()
    focus = facts.get("next_stint_focus")
    focus = focus if isinstance(focus, dict) else {}
    focus_items = focus.get("items") if focus.get("status") == "ACTIVE" else []
    focus_items = focus_items if isinstance(focus_items, list) else []
    focus_ids = {
        str(item.get("plan_label"))
        for item in focus_items
        if isinstance(item, dict) and item.get("plan_label") is not None
    }
    try:
        focus_count = int(focus.get("focus_count"))
    except (TypeError, ValueError):
        focus_count = 0
    if not (1 <= len(focus_items) <= 2 and focus_count == len(focus_items)):
        focus_ids = set()
    priorities = []
    for index, value in enumerate(values, start=1):
        if not isinstance(value, dict):
            continue
        try:
            start = float(value.get("start_distance_m"))
            end = float(value.get("end_distance_m"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            continue
        location = value.get("track_location")
        location = location if isinstance(location, dict) else {}
        cue_values = value.get("driver_cues")
        cue_values = cue_values if isinstance(cue_values, list) else []
        cues = []
        for cue in cue_values:
            if isinstance(cue, str):
                text = cue.strip()
            elif isinstance(cue, dict):
                text = str(cue.get("text") or cue.get("description") or "").strip()
            else:
                text = ""
            if text:
                cues.append(text)
        priority_id = str(value.get("plan_label") or index)
        priorities.append(
            TrackMapPriority(
                priority_id=priority_id,
                label=str(location.get("label") or f"Zona {priority_id}"),
                start_distance_m=start,
                end_distance_m=end,
                cues=tuple(cues),
                is_focus=priority_id in focus_ids,
            )
        )
    priorities.sort(
        key=lambda item: (item.start_distance_m, item.end_distance_m, item.priority_id)
    )
    return tuple(priorities)


def priority_for_distance(
    priorities: tuple[TrackMapPriority, ...],
    distance_m: float | None,
) -> TrackMapPriority | None:
    if distance_m is None:
        return None
    for priority in priorities:
        if priority.start_distance_m <= distance_m <= priority.end_distance_m:
            return priority
    return None


def zone_point_ranges(
    points: tuple[TrackMapPoint, ...],
    zone: TrackMapZone | TrackMapPriority | TrackMapTurn,
) -> tuple[tuple[int, int], ...]:
    """Return contiguous point-index ranges covered by one distance zone."""

    ranges = []
    start_index = None
    previous_index = None
    for index, point in enumerate(points):
        inside = (
            point.lap_distance_m is not None
            and zone.start_distance_m <= point.lap_distance_m <= zone.end_distance_m
        )
        if inside:
            if start_index is None:
                start_index = index
            previous_index = index
        elif start_index is not None:
            if previous_index is not None and previous_index > start_index:
                ranges.append((start_index, previous_index))
            start_index = None
            previous_index = None
    if start_index is not None and previous_index is not None and previous_index > start_index:
        ranges.append((start_index, previous_index))
    return tuple(ranges)
