#!/usr/bin/env python3
"""
extract_lmu_track_gps.py

Extrae una trayectoria GPS utilizable desde un DuckDB nativo de Le Mans Ultimate.

Objetivo:
- detectar las tablas nativas "GPS Latitude", "GPS Longitude", "GPS Time", "Lap Dist"
- reconstruir una serie temporal común aunque los canales tengan distinta frecuencia
- separar vueltas usando la tabla "Lap" cuando existe, con fallback por reset de Lap Dist
- seleccionar automáticamente una vuelta completa
- exportar:
    <stem>_track_gps.csv
    <stem>_track_gps.geojson
    <stem>_track_gps_summary.json

No modifica el DuckDB.

Uso:
    python extract_lmu_track_gps.py "session.duckdb"

Opciones:
    --lap 3
    --output-dir track_exports
    --target-hz 10
    --no-geojson
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

try:
    import duckdb
except ImportError:
    print("ERROR: falta el paquete 'duckdb'.")
    print("Instalalo con: pip install duckdb")
    raise SystemExit(2)


REQUIRED_GPS_TABLES = ("GPS Latitude", "GPS Longitude")
OPTIONAL_TABLES = ("GPS Time", "Lap Dist", "Lap", "Lap Time", "GPS Speed")
LAP_DISTANCE_RESET_THRESHOLD_M = 500.0


def qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def table_names(con) -> set[str]:
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def describe_columns(con, table: str) -> list[str]:
    return [r[0] for r in con.execute(f"DESCRIBE {qident(table)}").fetchall()]


def read_metadata(con) -> dict[str, Any]:
    tables = table_names(con)
    if "metadata" not in tables:
        return {}
    try:
        rows = con.execute("SELECT key, value FROM metadata").fetchall()
        return {str(k): v for k, v in rows}
    except Exception:
        return {}


def read_value_table(con, table: str) -> dict[str, Any]:
    """
    Devuelve:
      {
        "table": str,
        "columns": [...],
        "times": list[float] | None,
        "values": list[float],
        "mode": "ts" | "rowid"
      }

    Soporta el patrón LMU habitual:
      ts, value
    y el patrón de sólo value alineado por rowid.
    """
    cols = describe_columns(con, table)
    if "value" not in cols:
        raise ValueError(f'La tabla "{table}" no contiene columna value. Columnas: {cols}')

    if "ts" in cols:
        rows = con.execute(
            f"SELECT ts, value FROM {qident(table)} "
            "WHERE value IS NOT NULL ORDER BY ts"
        ).fetchall()
        times = []
        values = []
        for t, v in rows:
            if finite(t) and finite(v):
                times.append(float(t))
                values.append(float(v))
        return {
            "table": table,
            "columns": cols,
            "times": times,
            "values": values,
            "mode": "ts",
        }

    rows = con.execute(
        f"SELECT value FROM {qident(table)} "
        "WHERE value IS NOT NULL ORDER BY rowid"
    ).fetchall()
    values = [float(r[0]) for r in rows if finite(r[0])]
    return {
        "table": table,
        "columns": cols,
        "times": None,
        "values": values,
        "mode": "rowid",
    }


def deduplicate_time_series(times: list[float], values: list[float]):
    if not times:
        return [], []
    out_t = [times[0]]
    out_v = [values[0]]
    for t, v in zip(times[1:], values[1:]):
        if t == out_t[-1]:
            out_v[-1] = v
        elif t > out_t[-1]:
            out_t.append(t)
            out_v.append(v)
    return out_t, out_v


def interpolate_series(
    src_times: list[float],
    src_values: list[float],
    dst_times: list[float],
    discontinuity_threshold_m: float | None = None,
) -> list[float | None]:
    """
    Interpolación lineal con clamp a extremos.
    """
    src_times, src_values = deduplicate_time_series(src_times, src_values)
    if not src_times or not src_values:
        return [None] * len(dst_times)

    if len(src_times) == 1:
        return [src_values[0]] * len(dst_times)

    out = []
    for t in dst_times:
        if t <= src_times[0]:
            out.append(src_values[0])
            continue
        if t >= src_times[-1]:
            out.append(src_values[-1])
            continue

        j = bisect.bisect_right(src_times, t)
        i = j - 1
        t0 = src_times[i]
        t1 = src_times[j]
        v0 = src_values[i]
        v1 = src_values[j]

        if (
            discontinuity_threshold_m is not None
            and v0 - v1 > discontinuity_threshold_m
        ):
            out.append(v0)
            continue
        if t1 <= t0:
            out.append(v0)
        else:
            a = (t - t0) / (t1 - t0)
            out.append(v0 + a * (v1 - v0))
    return out


def infer_times_from_index(
    value_count: int,
    reference_times: list[float],
) -> list[float]:
    """
    Para canales sin ts. Reproduce la idea usada por herramientas LMU:
    distribuye los samples por índice a lo largo del rango de GPS Time.
    """
    if value_count <= 0:
        return []
    if not reference_times:
        return [float(i) for i in range(value_count)]
    if value_count == 1:
        return [reference_times[0]]
    if len(reference_times) == 1:
        return [reference_times[0]] * value_count

    last = len(reference_times) - 1
    result = []
    for i in range(value_count):
        x = i * last / (value_count - 1)
        lo = int(math.floor(x))
        hi = min(lo + 1, last)
        a = x - lo
        result.append(reference_times[lo] + a * (reference_times[hi] - reference_times[lo]))
    return result


def build_master_times(
    channels: dict[str, dict[str, Any]],
    target_hz: float,
) -> tuple[list[float], str]:
    gps_time = channels.get("GPS Time")

    if gps_time and gps_time["values"]:
        # GPS Time normalmente contiene el timestamp como "value".
        values = [float(v) for v in gps_time["values"] if finite(v)]
        if len(values) >= 2 and max(values) > min(values):
            start = min(values)
            end = max(values)
            dt = 1.0 / target_hz
            n = max(2, int(math.floor((end - start) / dt)) + 1)
            return [start + i * dt for i in range(n)], "GPS Time.value"

    # Fallback: usar timestamps explícitos de lat/lon.
    explicit = []
    for name in REQUIRED_GPS_TABLES:
        ch = channels.get(name)
        if ch and ch["times"]:
            explicit.extend(ch["times"])

    if not explicit:
        raise ValueError(
            'No hay "GPS Time" utilizable ni timestamps ts en GPS Latitude/Longitude.'
        )

    start = min(explicit)
    end = max(explicit)
    dt = 1.0 / target_hz
    n = max(2, int(math.floor((end - start) / dt)) + 1)
    return [start + i * dt for i in range(n)], "GPS channel ts"


def align_channel(
    channel: dict[str, Any] | None,
    master_times: list[float],
    reference_times: list[float],
) -> list[float | None]:
    if not channel or not channel["values"]:
        return [None] * len(master_times)

    if channel["times"]:
        src_times = channel["times"]
    else:
        src_times = infer_times_from_index(len(channel["values"]), reference_times)

    discontinuity_threshold_m = (
        LAP_DISTANCE_RESET_THRESHOLD_M
        if channel.get("table") == "Lap Dist"
        else None
    )
    return interpolate_series(
        src_times,
        channel["values"],
        master_times,
        discontinuity_threshold_m=discontinuity_threshold_m,
    )


def read_lap_event_times(con, tables: set[str]) -> list[float]:
    if "Lap" not in tables:
        return []
    cols = describe_columns(con, "Lap")
    if "ts" not in cols:
        return []
    rows = con.execute(
        'SELECT ts FROM "Lap" WHERE ts IS NOT NULL ORDER BY ts'
    ).fetchall()
    return [float(r[0]) for r in rows if finite(r[0])]


def assign_laps_from_boundaries(
    times: list[float],
    boundaries: list[float],
) -> list[int]:
    if not boundaries:
        return [0] * len(times)

    b = sorted(set(float(x) for x in boundaries if finite(x)))
    if not b:
        return [0] * len(times)

    result = []
    for t in times:
        idx = bisect.bisect_right(b, t) - 1
        result.append(max(idx, 0))
    return result


def detect_laps_from_distance(
    lap_dist: list[float | None],
    reset_threshold_m: float = LAP_DISTANCE_RESET_THRESHOLD_M,
) -> list[int]:
    """
    Fallback si no existe Lap.ts.
    Un reset fuerte de Lap Dist inicia nueva vuelta.
    """
    lap = 0
    out = []
    prev = None
    for d in lap_dist:
        if d is not None and finite(d):
            if prev is not None and prev - float(d) > reset_threshold_m:
                lap += 1
        out.append(lap)
        if d is not None and finite(d):
            prev = float(d)
    return out


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


def project_local_xy(lat, lon, lat0, lon0):
    """
    Proyección equirectangular local:
      x = Este
      y = Norte
    precisa de sobra a escala de un circuito.
    """
    r = 6371008.8
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    lat0_rad = math.radians(lat0)
    lon0_rad = math.radians(lon0)
    x = r * (lon_rad - lon0_rad) * math.cos((lat_rad + lat0_rad) / 2.0)
    y = r * (lat_rad - lat0_rad)
    return x, y


def valid_gps(lat, lon):
    if lat is None or lon is None:
        return False
    if not finite(lat) or not finite(lon):
        return False
    lat = float(lat)
    lon = float(lon)
    if abs(lat) > 90 or abs(lon) > 180:
        return False
    if abs(lat) < 1e-12 and abs(lon) < 1e-12:
        return False
    return True



def repair_lap_distance_boundary_sample(
    indices: list[int],
    lap_dist: list[float | None],
    reset_threshold_m: float = LAP_DISTANCE_RESET_THRESHOLD_M,
    expected_start_max_m: float = 100.0,
):
    """
    Corrige el artefacto de interpolación de Lap Dist justo en Lap.ts.

    Lap Dist es discontinuo en el cruce de meta. Si se interpola linealmente
    exactamente sobre el reset, el primer sample de una vuelta puede quedar
    con un valor espurio intermedio mientras el segundo sample ya está cerca
    de 0 m.

    Sólo repara el primer sample cuando:
      - hay al menos dos samples;
      - ambos Lap Dist son finitos;
      - el segundo está cerca del inicio de vuelta;
      - el primero está > reset_threshold_m por encima del segundo.

    El GPS no se descarta: únicamente Lap Dist del primer sample se fija a 0.
    """
    if len(indices) < 2:
        return None

    i0, i1 = indices[0], indices[1]
    d0 = lap_dist[i0]
    d1 = lap_dist[i1]

    if d0 is None or d1 is None or not finite(d0) or not finite(d1):
        return None

    d0 = float(d0)
    d1 = float(d1)

    if d1 <= expected_start_max_m and (d0 - d1) > reset_threshold_m:
        lap_dist[i0] = 0.0
        return {
            "sample_index": int(i0),
            "original_lap_dist_m": d0,
            "repaired_lap_dist_m": 0.0,
            "next_sample_lap_dist_m": d1,
            "reason": "boundary_linear_interpolation_across_lap_dist_reset",
        }

    return None

def group_indices_by_lap(laps: list[int]) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for i, lap in enumerate(laps):
        result.setdefault(int(lap), []).append(i)
    return result


def lap_metrics(
    indices: list[int],
    lat: list[float | None],
    lon: list[float | None],
    lap_dist: list[float | None],
    times: list[float],
):
    gps_idx = [i for i in indices if valid_gps(lat[i], lon[i])]
    if not gps_idx:
        gps_coverage = 0.0
        gps_path_m = 0.0
    else:
        gps_coverage = len(gps_idx) / max(1, len(indices))
        gps_path_m = 0.0
        prev = None
        for i in gps_idx:
            p = (float(lat[i]), float(lon[i]))
            if prev is not None:
                gps_path_m += haversine_m(prev[0], prev[1], p[0], p[1])
            prev = p

    dvals = [float(lap_dist[i]) for i in indices if lap_dist[i] is not None and finite(lap_dist[i])]
    if dvals:
        d_min = min(dvals)
        d_max = max(dvals)
        lap_dist_span = d_max - d_min
        lap_dist_max = d_max
    else:
        d_min = d_max = lap_dist_span = lap_dist_max = None

    duration = times[indices[-1]] - times[indices[0]] if len(indices) >= 2 else 0.0

    return {
        "sample_count": len(indices),
        "duration_s": duration,
        "gps_coverage": gps_coverage,
        "gps_path_m": gps_path_m,
        "lap_dist_min_m": d_min,
        "lap_dist_max_m": lap_dist_max,
        "lap_dist_span_m": lap_dist_span,
    }


def choose_default_lap(metrics: dict[int, dict[str, Any]]) -> int:
    """
    Prefiere:
    - mucha cobertura GPS
    - distancia de vuelta cercana a la mediana de vueltas largas
    - duración > 30 s
    - evita outlaps de 2x longitud
    """
    viable = {
        lap: m for lap, m in metrics.items()
        if m["gps_coverage"] >= 0.70
        and m["duration_s"] >= 30.0
        and (m["lap_dist_max_m"] or 0) >= 1000.0
    }

    if not viable:
        viable = {
            lap: m for lap, m in metrics.items()
            if m["gps_coverage"] >= 0.50 and m["duration_s"] >= 10.0
        }

    if not viable:
        return max(metrics, key=lambda k: metrics[k]["gps_coverage"])

    lengths = [
        m["lap_dist_max_m"]
        for m in viable.values()
        if m["lap_dist_max_m"] is not None and m["lap_dist_max_m"] > 1000
    ]
    ref_len = statistics.median(lengths) if lengths else None

    def score(item):
        lap, m = item
        coverage = m["gps_coverage"]
        if ref_len and m["lap_dist_max_m"]:
            ratio = m["lap_dist_max_m"] / ref_len
            length_score = max(0.0, 1.0 - abs(ratio - 1.0))
        else:
            length_score = 0.5
        # pista recorrida GPS / Lap Dist como sanity suave
        geo_score = 0.0
        if m["gps_path_m"] > 1000 and m["lap_dist_max_m"]:
            ratio2 = m["gps_path_m"] / m["lap_dist_max_m"]
            geo_score = max(0.0, 1.0 - min(abs(ratio2 - 1.0), 1.0))
        return 3.0 * coverage + 2.0 * length_score + geo_score

    return max(viable.items(), key=score)[0]


def csv_rows_for_lap(
    indices,
    times,
    lat,
    lon,
    lap_dist,
    lap_number,
):
    valid_indices = [i for i in indices if valid_gps(lat[i], lon[i])]
    if not valid_indices:
        return []

    lat0 = float(lat[valid_indices[0]])
    lon0 = float(lon[valid_indices[0]])

    first_t = times[indices[0]]
    rows = []

    for i in indices:
        if not valid_gps(lat[i], lon[i]):
            continue

        x, y = project_local_xy(float(lat[i]), float(lon[i]), lat0, lon0)
        rows.append({
            "lap": int(lap_number),
            "session_time_s": float(times[i]),
            "lap_time_s": float(times[i] - first_t),
            "lap_distance_m": None if lap_dist[i] is None else float(lap_dist[i]),
            "latitude_deg": float(lat[i]),
            "longitude_deg": float(lon[i]),
            "x_east_m": x,
            "y_north_m": y,
        })

    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]):
    fields = [
        "lap",
        "session_time_s",
        "lap_time_s",
        "lap_distance_m",
        "latitude_deg",
        "longitude_deg",
        "x_east_m",
        "y_north_m",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_geojson(path: Path, rows: list[dict[str, Any]], properties: dict[str, Any]):
    coords = [
        [r["longitude_deg"], r["latitude_deg"]]
        for r in rows
    ]
    obj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
            }
        ],
    }
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Extrae una vuelta GPS desde telemetría DuckDB nativa de Le Mans Ultimate."
    )
    parser.add_argument("duckdb_file")
    parser.add_argument("--lap", type=int, default=None, help="Número/índice interno de vuelta a exportar.")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--target-hz", type=float, default=10.0)
    parser.add_argument("--no-geojson", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.duckdb_file).expanduser().resolve()
    if not db_path.exists():
        print(f"ERROR: no existe:\n  {db_path}")
        return 2

    if args.target_hz <= 0 or args.target_hz > 100:
        print("ERROR: --target-hz debe estar entre 0 y 100.")
        return 2

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else db_path.parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 76)
    print("LMU GPS TRACK EXTRACTOR")
    print("=" * 76)
    print(f"Archivo: {db_path}")

    con = duckdb.connect(str(db_path), read_only=True)

    try:
        tables = table_names(con)
        metadata = read_metadata(con)

        print("\nMetadata:")
        for key in ("TrackName", "TrackLayout", "Session", "SessionType", "CarName", "CarClass"):
            if key in metadata:
                print(f"  {key}: {metadata[key]}")

        print("\nCanales relevantes:")
        for name in REQUIRED_GPS_TABLES + OPTIONAL_TABLES:
            print(f"  {name}: {'OK' if name in tables else 'NO'}")

        missing = [t for t in REQUIRED_GPS_TABLES if t not in tables]
        if missing:
            print("\nERROR: faltan canales GPS obligatorios:")
            for m in missing:
                print(f"  - {m}")
            print("\nLa telemetría no sirve para reconstrucción GPS sin esos canales.")
            return 3

        channels = {}
        for name in ("GPS Time", "GPS Latitude", "GPS Longitude", "Lap Dist"):
            if name in tables:
                channels[name] = read_value_table(con, name)

        master_times, time_source = build_master_times(channels, args.target_hz)

        gps_time_reference = []
        if "GPS Time" in channels and channels["GPS Time"]["values"]:
            gps_time_reference = [
                float(v) for v in channels["GPS Time"]["values"] if finite(v)
            ]
        if not gps_time_reference:
            gps_time_reference = master_times

        lat = align_channel(channels.get("GPS Latitude"), master_times, gps_time_reference)
        lon = align_channel(channels.get("GPS Longitude"), master_times, gps_time_reference)
        lap_dist = align_channel(channels.get("Lap Dist"), master_times, gps_time_reference)

        lap_boundaries = read_lap_event_times(con, tables)
        if lap_boundaries:
            laps = assign_laps_from_boundaries(master_times, lap_boundaries)
            lap_source = "Lap.ts"
        else:
            laps = detect_laps_from_distance(lap_dist)
            lap_source = "Lap Dist reset"

        groups = group_indices_by_lap(laps)

        lap_distance_boundary_repairs = {}
        for lap, idx in groups.items():
            repair = repair_lap_distance_boundary_sample(idx, lap_dist)
            if repair is not None:
                lap_distance_boundary_repairs[str(lap)] = repair

        metrics = {
            lap: lap_metrics(idx, lat, lon, lap_dist, master_times)
            for lap, idx in groups.items()
        }

        print(f"\nFuente temporal: {time_source}")
        print(f"Frecuencia de exportación: {args.target_hz:g} Hz")
        print(f"Fuente de límites de vuelta: {lap_source}")

        print("\nVueltas candidatas:")
        print(
            f"{'lap':>5} {'dur[s]':>9} {'GPS%':>8} "
            f"{'LapDistMax[m]':>14} {'GPSpath[m]':>12} {'samples':>9}"
        )
        for lap in sorted(metrics):
            m = metrics[lap]
            ld = m["lap_dist_max_m"]
            print(
                f"{lap:>5d} "
                f"{m['duration_s']:>9.3f} "
                f"{100*m['gps_coverage']:>7.1f}% "
                f"{('-' if ld is None else f'{ld:.1f}'):>14} "
                f"{m['gps_path_m']:>12.1f} "
                f"{m['sample_count']:>9d}"
            )

        if args.lap is None:
            selected_lap = choose_default_lap(metrics)
            print(f"\nVuelta seleccionada automáticamente: {selected_lap}")
        else:
            selected_lap = args.lap
            if selected_lap not in groups:
                print(f"\nERROR: vuelta {selected_lap} no existe. Disponibles: {sorted(groups)}")
                return 4
            print(f"\nVuelta seleccionada por usuario: {selected_lap}")

        rows = csv_rows_for_lap(
            groups[selected_lap],
            master_times,
            lat,
            lon,
            lap_dist,
            selected_lap,
        )

        if len(rows) < 10:
            print("ERROR: muy pocos puntos GPS válidos en la vuelta seleccionada.")
            return 5

        stem = db_path.stem
        csv_path = output_dir / f"{stem}_track_gps.csv"
        geojson_path = output_dir / f"{stem}_track_gps.geojson"
        summary_path = output_dir / f"{stem}_track_gps_summary.json"

        write_csv(csv_path, rows)

        selected_metrics = metrics[selected_lap]

        properties = {
            "source_file": db_path.name,
            "track_name": metadata.get("TrackName"),
            "track_layout": metadata.get("TrackLayout"),
            "lap": selected_lap,
        }

        if not args.no_geojson:
            write_geojson(geojson_path, rows, properties)

        lat_vals = [r["latitude_deg"] for r in rows]
        lon_vals = [r["longitude_deg"] for r in rows]
        x_vals = [r["x_east_m"] for r in rows]
        y_vals = [r["y_north_m"] for r in rows]
        d_vals = [
            r["lap_distance_m"] for r in rows
            if r["lap_distance_m"] is not None
        ]

        summary = {
            "source_file": str(db_path),
            "track_name": metadata.get("TrackName"),
            "track_layout": metadata.get("TrackLayout"),
            "selected_lap": selected_lap,
            "time_source": time_source,
            "lap_boundary_source": lap_source,
            "lap_distance_boundary_repairs": lap_distance_boundary_repairs,
            "target_hz": args.target_hz,
            "channel_modes": {
                name: {
                    "mode": ch["mode"],
                    "row_count": len(ch["values"]),
                    "columns": ch["columns"],
                }
                for name, ch in channels.items()
            },
            "selected_lap_metrics": selected_metrics,
            "exported_point_count": len(rows),
            "bounds": {
                "latitude_min": min(lat_vals),
                "latitude_max": max(lat_vals),
                "longitude_min": min(lon_vals),
                "longitude_max": max(lon_vals),
                "x_east_min_m": min(x_vals),
                "x_east_max_m": max(x_vals),
                "y_north_min_m": min(y_vals),
                "y_north_max_m": max(y_vals),
                "lap_distance_min_m": min(d_vals) if d_vals else None,
                "lap_distance_max_m": max(d_vals) if d_vals else None,
            },
            "laps": metrics,
            "outputs": {
                "csv": str(csv_path),
                "geojson": None if args.no_geojson else str(geojson_path),
            },
        }

        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print("\nExportación:")
        print(f"  CSV:     {csv_path}")
        if not args.no_geojson:
            print(f"  GeoJSON: {geojson_path}")
        print(f"  Summary: {summary_path}")

        print("\nSanity check:")
        print(f"  puntos GPS: {len(rows)}")
        print(
            f"  bounding box local: "
            f"{max(x_vals)-min(x_vals):.1f} m x "
            f"{max(y_vals)-min(y_vals):.1f} m"
        )
        if d_vals:
            print(f"  Lap Dist máximo: {max(d_vals):.1f} m")
        print(f"  recorrido GPS aproximado: {selected_metrics['gps_path_m']:.1f} m")

        print("\nSIGUIENTE PASO")
        print(
            "Usar el CSV/GeoJSON para detectar curvatura y calibrar T1..Tn.\n"
            "La calibración de nombres de curva se mantendrá fuera del LLM."
        )
        return 0

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
