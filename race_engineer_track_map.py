"""Read-only GPS track-map model for the Race Engineer desktop GUI."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import duckdb

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


TRACK_MAP_VERSION = "0.3"


@dataclass(frozen=True)
class TrackMapPoint:
    x_m: float
    y_m: float
    lap_distance_m: float | None


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


def load_track_map(
    database_path: Path,
    *,
    preferred_lap: int | None = None,
    preferred_duration_s: float | None = None,
    target_hz: float = 5.0,
    connect_factory: Callable = duckdb.connect,
) -> TrackMapData:
    """Extract one GPS lap without modifying or exporting the source DuckDB."""

    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if target_hz <= 0 or target_hz > 20:
        raise ValueError("La frecuencia del mapa debe estar entre 0 y 20 Hz.")

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
        points = tuple(
            TrackMapPoint(
                x_m=float(row["x_east_m"]),
                y_m=float(row["y_north_m"]),
                lap_distance_m=(
                    None
                    if row["lap_distance_m"] is None
                    else float(row["lap_distance_m"])
                ),
            )
            for row in rows
        )
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
    zone: TrackMapZone | TrackMapPriority,
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
