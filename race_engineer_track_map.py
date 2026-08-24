"""Read-only GPS track-map model for the Race Engineer desktop GUI."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import duckdb

from cross_session_zone_localization import find_validated_track_profile

from extract_lmu_track_gps import (
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
    distance_min = (
        full_distance_min
        if start_distance_m is None
        else max(full_distance_min, float(start_distance_m))
    )
    distance_max = (
        full_distance_max
        if end_distance_m is None
        else min(full_distance_max, float(end_distance_m))
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
    speed_max = max(100.0, math.ceil(observed_speed_max / 50.0) * 50.0)
    usable_width = float(width_px - left_px - right_px)
    usable_height = float(height_px - top_px - bottom_px)
    lane_height = usable_height / 3.0

    def x_for(distance: float) -> float:
        return left_px + (distance - distance_min) / (distance_max - distance_min) * usable_width

    def series(attribute: str, lane: int, maximum: float) -> tuple[tuple[float, float], ...]:
        result = []
        lane_top = top_px + lane * lane_height
        for point in points:
            distance = point.lap_distance_m
            value = getattr(point, attribute)
            if distance is None or value is None:
                continue
            if not math.isfinite(distance) or not math.isfinite(value):
                continue
            if not distance_min <= float(distance) <= distance_max:
                continue
            normalized = min(max(float(value) / maximum, 0.0), 1.0)
            result.append((x_for(float(distance)), lane_top + (1.0 - normalized) * lane_height))
        return tuple(result)

    return TrackTelemetryChart(
        speed_max_kmh=speed_max,
        speed=series("speed_kmh", 0, speed_max),
        throttle=series("throttle_percent", 1, 100.0),
        brake=series("brake_percent", 2, 100.0),
        distance_min_m=distance_min,
        distance_max_m=distance_max,
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
