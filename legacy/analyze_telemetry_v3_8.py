import json
import os
import re
import sys

import numpy as np
import pandas as pd

from telemetry import Telemetry
from laps import LapAnalyzer
from delta_comparison import DeltaComparison
from sector_analysis import SectorAnalysis


# ============================================================
# RACE ENGINEER - TELEMETRY ANALYSIS v3.8
# ============================================================
#
# PYTHON:
# - detecta y valida vueltas
# - selecciona la vuelta de referencia
# - compara vueltas del mismo vehículo
# - calcula y valida deltas temporales
# - reconstruye zonas sin huecos ni solapamientos
# - extrae telemetría objetiva
# - genera ranking de pérdidas por impacto temporal
# - genera eventos sostenidos y clusters de pérdida
# - agrupa evidencias solapadas en episodios de pérdida no aditivos
# - marca las comparaciones más útiles para análisis de conducción
#
# LLM:
# - interpreta hechos objetivos
# - formula hipótesis
# - NO recalcula deltas ni inventa datos
#
# Signos:
# delta positivo = vuelta comparada pierde tiempo
# delta negativo = vuelta comparada gana tiempo
# ============================================================


# ============================================================
# ARGUMENTOS
# ============================================================


def parse_arguments():
    validate = False
    database = None

    for argument in sys.argv[1:]:
        if argument == "--validate":
            validate = True
            continue

        if argument.startswith("-"):
            raise ValueError(
                f"Argumento desconocido: {argument}"
            )

        if database is not None:
            raise ValueError(
                "Solo se puede especificar un archivo .duckdb."
            )

        database = argument

    return validate, database


VALIDATE_ONLY, DATABASE_ARGUMENT = parse_arguments()


# ============================================================
# CONFIGURACIÓN BASE
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


# ============================================================
# SELECCIÓN DE BASE DE DATOS
# ============================================================


def find_telemetry_database():
    if DATABASE_ARGUMENT is not None:
        db_path = DATABASE_ARGUMENT

        if not os.path.isabs(db_path):
            db_path = os.path.join(
                BASE_DIR,
                db_path,
            )

        db_path = os.path.abspath(db_path)

        if not os.path.exists(db_path):
            raise FileNotFoundError(
                "No existe el archivo de telemetría:\n"
                f"{db_path}"
            )

        if not db_path.lower().endswith(".duckdb"):
            raise ValueError(
                "El archivo indicado no es una base de datos .duckdb."
            )

        return db_path

    databases = sorted(
        filename
        for filename in os.listdir(BASE_DIR)
        if filename.lower().endswith(".duckdb")
    )

    if not databases:
        raise RuntimeError(
            "No se encontró ningún archivo .duckdb "
            "en el directorio del proyecto."
        )

    if len(databases) == 1:
        return os.path.join(
            BASE_DIR,
            databases[0],
        )

    raise RuntimeError(
        "Se encontraron múltiples archivos .duckdb.\n\n"
        "Indicá cuál utilizar mediante:\n\n"
        'python analyze_telemetry.py "archivo.duckdb"\n\n'
        "Archivos encontrados:\n"
        + "\n".join(
            f"  {filename}"
            for filename in databases
        )
    )


DB_PATH = find_telemetry_database()


# ============================================================
# IDENTIFICACIÓN DEL ARCHIVO
# ============================================================


def parse_telemetry_filename(db_path):
    filename = os.path.basename(db_path)
    stem = os.path.splitext(filename)[0]

    pattern = re.compile(
        r"^(?P<track>.+?)"
        r"_(?P<session>[A-Za-z]+)"
        r"_(?P<date>\d{4}-\d{2}-\d{2})"
        r"T"
        r"(?P<hour>\d{2})"
        r"_(?P<minute>\d{2})"
        r"_(?P<second>\d{2})"
        r"Z$"
    )

    match = pattern.match(stem)

    if match:
        timestamp_utc = (
            f"{match.group('date')}"
            f"T{match.group('hour')}:"
            f"{match.group('minute')}:"
            f"{match.group('second')}Z"
        )

        return {
            "filename": filename,
            "track": match.group("track"),
            "session_type": match.group("session"),
            "timestamp_utc": timestamp_utc,
        }

    return {
        "filename": filename,
        "track": stem,
        "session_type": None,
        "timestamp_utc": None,
    }


FILE_INFO = parse_telemetry_filename(DB_PATH)


# ============================================================
# OUTPUT
# ============================================================

OUTPUT_PATH = os.path.join(
    BASE_DIR,
    os.path.splitext(
        os.path.basename(DB_PATH)
    )[0] + ".json",
)


# ============================================================
# CONFIGURACIÓN DE ANÁLISIS
# ============================================================

IGNORE_INITIAL_LAPS = 1
VALID_DISTANCE_RATIO = 0.95
MIN_LAP_DURATION = 60.0

RESOLUTION = 1.0
SMOOTHING_WINDOW = 21

MIN_ZONE_DISTANCE = 10.0
MAX_ZONES = 15

TEMPORAL_VALIDATION_TOLERANCE = 0.05
ZONE_COVERAGE_TOLERANCE_M = 2.0
MIN_ZONE_TIME_DELTA_S = 0.005

# Número de vueltas más cercanas a la referencia que se marcan
# como prioritarias para el análisis de conducción del LLM.
MAX_DRIVER_ANALYSIS_COMPARISONS = 2

MIN_SUSTAINED_EVENT_DISTANCE_M = 15.0
MAX_SUSTAINED_EVENT_GAP_M = 4.0
MIN_LOSS_CLUSTER_DISTANCE_M = 20.0
MAX_LOSS_CLUSTER_GAP_M = 6.0
MIN_LOSS_CLUSTER_TIME_S = 0.03
LOSS_GRADIENT_SMOOTHING_M = 21
MIN_POSITIVE_LOSS_GRADIENT_S_PER_M = 0.00005

# Episodios de pérdida heredados de v3.7.
# Se conservan por compatibilidad y diagnóstico secundario.
LOSS_EPISODE_MERGE_GAP_M = 12.0
MIN_LOSS_EPISODE_TIME_S = 0.02
MIN_LOSS_EPISODE_DISTANCE_M = 15.0
MAX_PRINTED_LOSS_EPISODES = 10

# v3.8: episodios de ACCIÓN del piloto.
# Speed NO puede unir episodios: velocidad se trata como resultado/propagación.
DRIVER_ACTION_CHANNELS = {
    "throttle",
    "brake",
    "steering_magnitude",
}
DRIVER_ACTION_EPISODE_MERGE_GAP_M = 12.0
MIN_DRIVER_ACTION_EPISODE_TIME_S = 0.02
MIN_DRIVER_ACTION_EPISODE_DISTANCE_M = 15.0
MAX_PRINTED_DRIVER_ACTION_EPISODES = 10

# Una diferencia de velocidad puede quedar vinculada a una acción cercana,
# pero jamás extender los límites del episodio de acción.
SPEED_LINK_GAP_M = 25.0
MIN_SPEED_PROPAGATION_DISTANCE_M = 15.0
SPEED_PROPAGATION_NEUTRAL_TIME_S = 0.005


# ============================================================
# UMBRALES DE EVENTOS OBJETIVOS
# ============================================================

SPEED_EVENT_THRESHOLD = 5.0
THROTTLE_EVENT_THRESHOLD = 10.0
BRAKE_EVENT_THRESHOLD = 10.0
STEERING_EVENT_THRESHOLD = 5.0


# ============================================================
# UTILIDADES
# ============================================================


def print_header(title):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)



def safe_float(value):
    if value is None:
        return None

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if not np.isfinite(value):
        return None

    return value



def safe_int(value):
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None



def percent_of_positive_delta(value, real_delta):
    """
    Porcentaje de una pérdida bruta respecto de pérdidas brutas.

    Puede superar 100% porque las ganancias intermedias compensan
    parte de las pérdidas brutas.
    """
    value = safe_float(value)
    real_delta = safe_float(real_delta)

    if (
        value is None
        or real_delta is None
        or real_delta <= 0
    ):
        return None

    return safe_float(
        value / real_delta * 100.0
    )


# ============================================================
# SERIALIZACIÓN
# ============================================================


def build_lap_summary(laps_df):
    records = []

    for _, row in laps_df.iterrows():
        record = {}

        for column in laps_df.columns:
            value = row[column]

            if isinstance(value, np.integer):
                value = int(value)
            elif isinstance(value, np.floating):
                value = safe_float(value)
            elif pd.isna(value):
                value = None

            record[column] = value

        records.append(record)

    return records


# ============================================================
# MAPA DE CANALES
# ============================================================

CHANNEL_MAP = {
    "ground_speed": (
        "speed_a",
        "speed_b",
    ),
    "engine_rpm": (
        "rpm_a",
        "rpm_b",
    ),
    "throttle_pos": (
        "throttle_a",
        "throttle_b",
    ),
    "brake_pos": (
        "brake_a",
        "brake_b",
    ),
    "steering_pos": (
        "steering_a",
        "steering_b",
    ),
}


# ============================================================
# RESUMEN DE CANALES
# ============================================================


def build_channel_summary(
    comparison,
    start_distance,
    end_distance,
):
    zone_data = comparison[
        (comparison["distance"] >= start_distance)
        &
        (comparison["distance"] <= end_distance)
    ].copy()

    result = {}

    if zone_data.empty:
        return result

    for channel_name, columns in CHANNEL_MAP.items():
        a_column, b_column = columns

        if (
            a_column not in zone_data.columns
            or b_column not in zone_data.columns
        ):
            continue

        a = pd.to_numeric(
            zone_data[a_column],
            errors="coerce",
        ).to_numpy(dtype=float)

        b = pd.to_numeric(
            zone_data[b_column],
            errors="coerce",
        ).to_numpy(dtype=float)

        valid = np.isfinite(a) & np.isfinite(b)

        if valid.sum() == 0:
            continue

        a = a[valid]
        b = b[valid]
        delta = b - a

        result[channel_name] = {
            "reference_mean": safe_float(np.mean(a)),
            "comparison_mean": safe_float(np.mean(b)),
            "comparison_minus_reference_mean": safe_float(
                np.mean(delta)
            ),
            "reference_min": safe_float(np.min(a)),
            "reference_max": safe_float(np.max(a)),
            "comparison_min": safe_float(np.min(b)),
            "comparison_max": safe_float(np.max(b)),
            "delta_min": safe_float(np.min(delta)),
            "delta_max": safe_float(np.max(delta)),
            "delta_abs_max": safe_float(
                np.max(np.abs(delta))
            ),
        }

    return result


# ============================================================
# SNAPSHOT OBJETIVO EN UNA DISTANCIA
# ============================================================


def build_event_snapshot(zone_data, index):
    """
    Captura todos los canales disponibles en el mismo punto espacial.

    No interpreta el evento. Solo permite que el LLM vea el estado
    simultáneo de velocidad/RPM/throttle/freno/dirección.
    """
    snapshot = {}

    mapping = {
        "speed_kmh": ("speed_a", "speed_b"),
        "engine_rpm": ("rpm_a", "rpm_b"),
        "throttle_percent": ("throttle_a", "throttle_b"),
        "brake_percent": ("brake_a", "brake_b"),
        "steering": ("steering_a", "steering_b"),
    }

    for output_name, (a_column, b_column) in mapping.items():
        if (
            a_column not in zone_data.columns
            or b_column not in zone_data.columns
        ):
            continue

        reference_value = safe_float(
            zone_data.iloc[index][a_column]
        )
        comparison_value = safe_float(
            zone_data.iloc[index][b_column]
        )

        if (
            reference_value is None
            or comparison_value is None
        ):
            continue

        snapshot[output_name] = {
            "reference": reference_value,
            "comparison": comparison_value,
            "comparison_minus_reference": safe_float(
                comparison_value - reference_value
            ),
        }

    return snapshot


# ============================================================
# EVENTOS OBJETIVOS
# ============================================================


def append_difference_events(
    events,
    zone_data,
    distances,
    a_column,
    b_column,
    event_type,
    threshold,
    delta_field,
):
    if (
        a_column not in zone_data.columns
        or b_column not in zone_data.columns
    ):
        return

    a = pd.to_numeric(
        zone_data[a_column],
        errors="coerce",
    ).to_numpy(dtype=float)

    b = pd.to_numeric(
        zone_data[b_column],
        errors="coerce",
    ).to_numpy(dtype=float)

    valid = (
        np.isfinite(distances)
        & np.isfinite(a)
        & np.isfinite(b)
    )

    if not valid.any():
        return

    valid_indices = np.flatnonzero(valid)
    valid_delta = (b - a)[valid]

    min_local_index = int(np.argmin(valid_delta))
    max_local_index = int(np.argmax(valid_delta))

    min_index = int(valid_indices[min_local_index])
    max_index = int(valid_indices[max_local_index])

    minimum = safe_float(valid_delta[min_local_index])
    maximum = safe_float(valid_delta[max_local_index])

    if minimum is not None and abs(minimum) >= threshold:
        events.append({
            "type": event_type,
            "direction": "lower_in_comparison_lap",
            "distance_m": safe_float(distances[min_index]),
            delta_field: minimum,
            "reference_value": safe_float(a[min_index]),
            "comparison_value": safe_float(b[min_index]),
            "snapshot": build_event_snapshot(
                zone_data,
                min_index,
            ),
        })

    if maximum is not None and maximum >= threshold:
        events.append({
            "type": event_type,
            "direction": "higher_in_comparison_lap",
            "distance_m": safe_float(distances[max_index]),
            delta_field: maximum,
            "reference_value": safe_float(a[max_index]),
            "comparison_value": safe_float(b[max_index]),
            "snapshot": build_event_snapshot(
                zone_data,
                max_index,
            ),
        })



def detect_objective_events(
    comparison,
    start_distance,
    end_distance,
):
    """
    Detecta diferencias objetivas significativas.

    Cada evento contiene un snapshot simultáneo de los canales
    disponibles para reducir el trabajo del LLM y evitar que mezcle
    puntos espaciales diferentes.
    """
    zone_data = comparison[
        (comparison["distance"] >= start_distance)
        &
        (comparison["distance"] <= end_distance)
    ].copy().reset_index(drop=True)

    if zone_data.empty:
        return []

    distances = pd.to_numeric(
        zone_data["distance"],
        errors="coerce",
    ).to_numpy(dtype=float)

    events = []

    append_difference_events(
        events,
        zone_data,
        distances,
        "speed_a",
        "speed_b",
        "speed_difference",
        SPEED_EVENT_THRESHOLD,
        "delta_kmh",
    )

    append_difference_events(
        events,
        zone_data,
        distances,
        "throttle_a",
        "throttle_b",
        "throttle_difference",
        THROTTLE_EVENT_THRESHOLD,
        "delta_percent",
    )

    append_difference_events(
        events,
        zone_data,
        distances,
        "brake_a",
        "brake_b",
        "brake_difference",
        BRAKE_EVENT_THRESHOLD,
        "delta_percent",
    )

    append_difference_events(
        events,
        zone_data,
        distances,
        "steering_a",
        "steering_b",
        "steering_difference",
        STEERING_EVENT_THRESHOLD,
        "delta",
    )

    return events


# ============================================================
# TIPO DE ZONA
# ============================================================


def classify_zone_type(delta_change_s):
    if delta_change_s is None:
        return "unknown"

    if delta_change_s > MIN_ZONE_TIME_DELTA_S:
        return "loss"

    if delta_change_s < -MIN_ZONE_TIME_DELTA_S:
        return "gain"

    return "neutral"


# ============================================================
# CONSTRUIR ZONA TEMPORAL
# ============================================================


def build_temporal_zone(
    comparison,
    start_distance,
    end_distance,
    zone_id,
    source_type=None,
):
    if comparison.empty:
        return None

    start_distance = float(start_distance)
    end_distance = float(end_distance)

    if end_distance <= start_distance:
        return None

    distances = comparison[
        "distance"
    ].to_numpy(dtype=float)

    deltas = comparison[
        "time_delta"
    ].to_numpy(dtype=float)

    valid = np.isfinite(distances) & np.isfinite(deltas)

    if valid.sum() < 2:
        return None

    distances = distances[valid]
    deltas = deltas[valid]

    delta_start = float(
        np.interp(
            start_distance,
            distances,
            deltas,
        )
    )

    delta_end = float(
        np.interp(
            end_distance,
            distances,
            deltas,
        )
    )

    delta_change = delta_end - delta_start

    return {
        "zone_id": int(zone_id),
        "type": classify_zone_type(delta_change),
        "source_type": source_type,
        "start_distance_m": safe_float(start_distance),
        "end_distance_m": safe_float(end_distance),
        "length_m": safe_float(
            end_distance - start_distance
        ),
        "delta_start_s": safe_float(delta_start),
        "delta_end_s": safe_float(delta_end),
        "delta_change_s": safe_float(delta_change),
        "delta_abs_s": safe_float(abs(delta_change)),
    }


# ============================================================
# RECONSTRUIR ZONAS TEMPORALES
# ============================================================


def rebuild_temporal_zones(
    comparison,
    raw_zones,
):
    if comparison.empty:
        return []

    distance = float(
        comparison["distance"].iloc[-1]
    )

    if distance <= 0:
        return []

    boundaries = {
        0.0,
        distance,
    }

    for zone in raw_zones:
        start = safe_float(
            zone.get("start_distance")
        )
        end = safe_float(
            zone.get("end_distance")
        )

        if start is None or end is None:
            continue

        start = max(
            0.0,
            min(distance, start),
        )
        end = max(
            0.0,
            min(distance, end),
        )

        if end > start:
            boundaries.add(start)
            boundaries.add(end)

    boundaries = sorted(boundaries)
    clean_boundaries = []

    for value in boundaries:
        if not clean_boundaries:
            clean_boundaries.append(value)
            continue

        if (
            value - clean_boundaries[-1]
            > ZONE_COVERAGE_TOLERANCE_M
        ):
            clean_boundaries.append(value)

    if (
        not clean_boundaries
        or abs(clean_boundaries[-1] - distance) > 1e-9
    ):
        clean_boundaries.append(distance)

    zones = []

    for i in range(len(clean_boundaries) - 1):
        start = clean_boundaries[i]
        end = clean_boundaries[i + 1]

        if end <= start:
            continue

        midpoint = (start + end) / 2.0
        source_type = None

        for raw_zone in raw_zones:
            raw_start = safe_float(
                raw_zone.get("start_distance")
            )
            raw_end = safe_float(
                raw_zone.get("end_distance")
            )

            if (
                raw_start is not None
                and raw_end is not None
                and raw_start <= midpoint <= raw_end
            ):
                source_type = raw_zone.get("type")
                break

        zone = build_temporal_zone(
            comparison,
            start,
            end,
            i + 1,
            source_type,
        )

        if zone is not None:
            zones.append(zone)

    if not zones:
        return []

    coverage_start = zones[0]["start_distance_m"]
    coverage_end = zones[-1]["end_distance_m"]

    coverage_error = max(
        abs(coverage_start),
        abs(coverage_end - distance),
    )

    if coverage_error > ZONE_COVERAGE_TOLERANCE_M:
        raise RuntimeError(
            "ZONE_COVERAGE_VALIDATION_FAILED: "
            f"coverage_error={coverage_error:.3f} m"
        )

    for i in range(1, len(zones)):
        previous_end = zones[i - 1]["end_distance_m"]
        current_start = zones[i]["start_distance_m"]
        gap = current_start - previous_end

        if abs(gap) > ZONE_COVERAGE_TOLERANCE_M:
            raise RuntimeError(
                "ZONE_CONTINUITY_VALIDATION_FAILED: "
                f"gap={gap:.3f} m"
            )

    return zones


# ============================================================
# ENRIQUECER ZONAS
# ============================================================


def enrich_temporal_zones(
    zones,
    comparison,
):
    enriched = []

    for zone in zones:
        start = zone["start_distance_m"]
        end = zone["end_distance_m"]

        record = dict(zone)
        record["channels"] = build_channel_summary(
            comparison,
            start,
            end,
        )
        record["events"] = detect_objective_events(
            comparison,
            start,
            end,
        )

        enriched.append(record)

    return enriched


# ============================================================
# IMPORTANCIA DE ZONA
# ============================================================


def zone_importance(zone):
    return abs(
        zone.get("delta_change_s", 0.0)
        or 0.0
    )


# ============================================================
# HECHOS OBJETIVOS COMPACTOS DE UNA ZONA
# ============================================================


def build_zone_objective_facts(zone, real_delta):
    channels = zone.get("channels", {})

    mean_differences = {}
    largest_differences = {}

    output_names = {
        "ground_speed": "speed_kmh",
        "engine_rpm": "engine_rpm",
        "throttle_pos": "throttle_percent",
        "brake_pos": "brake_percent",
        "steering_pos": "steering",
    }

    for channel_name, output_name in output_names.items():
        data = channels.get(channel_name)

        if not isinstance(data, dict):
            continue

        mean_delta = safe_float(
            data.get("comparison_minus_reference_mean")
        )
        abs_max = safe_float(
            data.get("delta_abs_max")
        )

        if mean_delta is not None:
            mean_differences[output_name] = mean_delta

        if abs_max is not None:
            largest_differences[output_name] = abs_max

    delta = safe_float(
        zone.get("delta_change_s")
    )

    return {
        "zone_id": safe_int(zone.get("zone_id")),
        "type": zone.get("type"),
        "start_distance_m": safe_float(
            zone.get("start_distance_m")
        ),
        "end_distance_m": safe_float(
            zone.get("end_distance_m")
        ),
        "length_m": safe_float(zone.get("length_m")),
        "delta_change_s": delta,
        "deficit_share_percent": (
            percent_of_positive_delta(delta, real_delta)
            if zone.get("type") == "loss"
            else None
        ),
        "mean_differences": mean_differences,
        "largest_observed_differences": largest_differences,
        "event_count": len(zone.get("events", [])),
        "events": zone.get("events", []),
    }


# ============================================================
# SEGMENTOS PERSISTENTES v3.6 / EPISODIOS v3.7
# ============================================================


def _contiguous_distance_runs(distances, mask, max_gap_m):
    distances = np.asarray(distances, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    indices = np.flatnonzero(mask & np.isfinite(distances))
    if len(indices) == 0:
        return []
    runs = []
    run_start = int(indices[0])
    previous = int(indices[0])
    for current_raw in indices[1:]:
        current = int(current_raw)
        if distances[current] - distances[previous] > max_gap_m:
            runs.append((run_start, previous))
            run_start = current
        previous = current
    runs.append((run_start, previous))
    return runs


def _segment_time_delta(comparison, start_m, end_m):
    distances = pd.to_numeric(comparison["distance"], errors="coerce").to_numpy(dtype=float)
    deltas = pd.to_numeric(comparison["time_delta"], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(distances) & np.isfinite(deltas)
    if valid.sum() < 2:
        return None, None, None
    distances = distances[valid]
    deltas = deltas[valid]
    ds = float(np.interp(start_m, distances, deltas))
    de = float(np.interp(end_m, distances, deltas))
    return safe_float(ds), safe_float(de), safe_float(de - ds)


def detect_sustained_channel_events(comparison, start_distance, end_distance):
    zone_data = comparison[
        (comparison["distance"] >= start_distance) &
        (comparison["distance"] <= end_distance)
    ].copy().reset_index(drop=True)
    if zone_data.empty:
        return []
    distances = pd.to_numeric(zone_data["distance"], errors="coerce").to_numpy(dtype=float)
    specs = [
        ("speed", "speed_a", "speed_b", SPEED_EVENT_THRESHOLD, "kmh", False),
        ("throttle", "throttle_a", "throttle_b", THROTTLE_EVENT_THRESHOLD, "percent", False),
        ("brake", "brake_a", "brake_b", BRAKE_EVENT_THRESHOLD, "percent", False),
        ("steering_magnitude", "steering_a", "steering_b", STEERING_EVENT_THRESHOLD, "steering", True),
    ]
    events = []
    for name, a_col, b_col, threshold, unit, magnitude_only in specs:
        if a_col not in zone_data.columns or b_col not in zone_data.columns:
            continue
        a = pd.to_numeric(zone_data[a_col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(zone_data[b_col], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(distances) & np.isfinite(a) & np.isfinite(b)
        if not valid.any():
            continue
        signal_a = np.abs(a) if magnitude_only else a
        signal_b = np.abs(b) if magnitude_only else b
        difference = signal_b - signal_a
        mask = valid & (np.abs(difference) >= threshold)
        for i0, i1 in _contiguous_distance_runs(distances, mask, MAX_SUSTAINED_EVENT_GAP_M):
            start_m = float(distances[i0]); end_m = float(distances[i1]); length_m = end_m - start_m
            if length_m < MIN_SUSTAINED_EVENT_DISTANCE_M:
                continue
            seg_indices = np.arange(i0, i1 + 1)
            seg_indices = seg_indices[valid[seg_indices]]
            if len(seg_indices) == 0:
                continue
            seg_diff = difference[seg_indices]
            mean_diff = float(np.mean(seg_diff))
            peak_index = int(seg_indices[np.argmax(np.abs(seg_diff))])
            peak_diff = float(difference[peak_index])
            delta_start, delta_end, event_time_change = _segment_time_delta(comparison, start_m, end_m)
            snapshot = build_event_snapshot(zone_data, peak_index)
            if "steering" in snapshot:
                ref = snapshot["steering"].get("reference")
                cmpv = snapshot["steering"].get("comparison")
                if ref is not None and cmpv is not None:
                    snapshot["steering"]["reference_magnitude"] = abs(ref)
                    snapshot["steering"]["comparison_magnitude"] = abs(cmpv)
                    snapshot["steering"]["magnitude_difference"] = abs(cmpv) - abs(ref)
            events.append({
                "type": f"sustained_{name}_difference",
                "start_distance_m": safe_float(start_m),
                "end_distance_m": safe_float(end_m),
                "length_m": safe_float(length_m),
                "direction": "higher_in_comparison_lap" if mean_diff > 0 else "lower_in_comparison_lap",
                "mean_difference": safe_float(mean_diff),
                "peak_difference": safe_float(peak_diff),
                "unit": unit,
                "peak_distance_m": safe_float(distances[peak_index]),
                "delta_start_s": delta_start,
                "delta_end_s": delta_end,
                "time_delta_change_during_event_s": event_time_change,
                "snapshot_at_peak": snapshot,
                "persistent": True,
            })
    return events


def detect_loss_clusters(comparison, zone):
    if zone.get("type") != "loss":
        return []
    start_m = float(zone["start_distance_m"]); end_m = float(zone["end_distance_m"])
    data = comparison[(comparison["distance"] >= start_m) & (comparison["distance"] <= end_m)].copy()
    d = pd.to_numeric(data["distance"], errors="coerce").to_numpy(dtype=float)
    td = pd.to_numeric(data["time_delta"], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(d) & np.isfinite(td)
    d = d[valid]; td = td[valid]
    if len(d) < 3:
        return []
    gradient = np.gradient(td, d)
    resolution = np.nanmedian(np.diff(d)) if len(d) > 1 else 1.0
    if not np.isfinite(resolution) or resolution <= 0: resolution = 1.0
    window = max(3, int(round(LOSS_GRADIENT_SMOOTHING_M / resolution)))
    if window % 2 == 0: window += 1
    smooth_gradient = pd.Series(gradient).rolling(window=window, center=True, min_periods=1).mean().to_numpy(dtype=float)
    mask = smooth_gradient > MIN_POSITIVE_LOSS_GRADIENT_S_PER_M
    clusters = []
    for i0, i1 in _contiguous_distance_runs(d, mask, MAX_LOSS_CLUSTER_GAP_M):
        c_start = float(d[i0]); c_end = float(d[i1]); length = c_end - c_start
        if length < MIN_LOSS_CLUSTER_DISTANCE_M: continue
        ds, de, dc = _segment_time_delta(comparison, c_start, c_end)
        if dc is None or dc < MIN_LOSS_CLUSTER_TIME_S: continue
        clusters.append({"start_distance_m": safe_float(c_start), "end_distance_m": safe_float(c_end), "length_m": safe_float(length), "delta_loss_s": safe_float(dc), "delta_start_s": ds, "delta_end_s": de})
    clusters.sort(key=lambda x: x["delta_loss_s"], reverse=True)
    for rank, cluster in enumerate(clusters, start=1): cluster["rank"] = rank
    return clusters


def build_objective_time_accounting(zones, real_delta):
    gross_loss = float(sum(z["delta_change_s"] for z in zones if z.get("type") == "loss" and z.get("delta_change_s") is not None))
    gross_gain = float(sum(-z["delta_change_s"] for z in zones if z.get("type") == "gain" and z.get("delta_change_s") is not None))
    neutral_delta = float(sum(z["delta_change_s"] for z in zones if z.get("type") == "neutral" and z.get("delta_change_s") is not None))
    net = gross_loss - gross_gain + neutral_delta
    return {"gross_loss_s": safe_float(gross_loss), "gross_gain_s": safe_float(gross_gain), "neutral_delta_s": safe_float(neutral_delta), "net_from_components_s": safe_float(net), "real_delta_s": safe_float(real_delta), "accounting_error_s": safe_float(net - real_delta), "note": "gross_loss_s es pérdida bruta; gross_gain_s son ganancias compensatorias."}


def build_objective_loss_ranking(zones, real_delta, gross_loss):
    ranking = []
    for zone in zones:
        delta = safe_float(zone.get("delta_change_s"))
        if zone.get("type") != "loss" or delta is None or delta <= MIN_ZONE_TIME_DELTA_S: continue
        item = build_zone_objective_facts(zone, real_delta)
        item["delta_loss_s"] = delta
        item["gross_loss_share_percent"] = safe_float(delta / gross_loss * 100.0) if gross_loss > 0 else None
        item["net_deficit_equivalent_percent"] = item.pop("deficit_share_percent", None)
        item["instantaneous_extremes"] = item.pop("events", [])
        item["instantaneous_extreme_count"] = item.pop("event_count", 0)
        item["loss_clusters"] = zone.get("loss_clusters", [])
        item["sustained_events"] = zone.get("sustained_events", [])
        ranking.append(item)
    ranking.sort(key=lambda x: x["delta_loss_s"], reverse=True)
    for rank, item in enumerate(ranking, start=1): item["rank"] = rank
    return ranking


def build_objective_gain_ranking(zones):
    ranking=[]
    for zone in zones:
        delta=safe_float(zone.get("delta_change_s"))
        if zone.get("type") != "gain" or delta is None or delta >= -MIN_ZONE_TIME_DELTA_S: continue
        ranking.append({"rank":None,"zone_id":safe_int(zone.get("zone_id")),"start_distance_m":safe_float(zone.get("start_distance_m")),"end_distance_m":safe_float(zone.get("end_distance_m")),"delta_gain_s":safe_float(-delta),"signed_delta_change_s":delta})
    ranking.sort(key=lambda x:x["delta_gain_s"], reverse=True)
    for rank,item in enumerate(ranking,start=1): item["rank"]=rank
    return ranking


def _event_evidence(event):
    time_change = safe_float(event.get("time_delta_change_during_event_s")) or 0.0
    length = safe_float(event.get("length_m")) or 0.0
    snapshot = event.get("snapshot_at_peak", {})
    speed = abs(safe_float(snapshot.get("speed_kmh", {}).get("comparison_minus_reference")) or 0.0)
    corroborating = 0
    thresholds = {"speed_kmh":5.0,"engine_rpm":300.0,"throttle_percent":10.0,"brake_percent":10.0,"steering":5.0}
    for key, threshold in thresholds.items():
        if key in snapshot and abs(safe_float(snapshot[key].get("comparison_minus_reference")) or 0.0) >= threshold:
            corroborating += 1
    if time_change >= 0.08 and length >= 25 and (speed >= 5 or corroborating >= 2): return "strong", corroborating
    if time_change >= 0.03 and length >= MIN_SUSTAINED_EVENT_DISTANCE_M: return "moderate", corroborating
    return "weak", corroborating


def build_objective_event_ranking(loss_ranking):
    result=[]
    for zone_item in loss_ranking:
        for event in zone_item.get("sustained_events", []):
            evidence, corroborating = _event_evidence(event)
            event_change = safe_float(event.get("time_delta_change_during_event_s")) or 0.0
            result.append({"rank":None,"priority_basis":"event_time_loss_then_persistence","zone_rank":zone_item["rank"],"zone_id":zone_item["zone_id"],"parent_zone_delta_loss_s":zone_item["delta_loss_s"],"parent_zone_gross_loss_share_percent":zone_item.get("gross_loss_share_percent"),"event_time_loss_s":safe_float(max(0.0,event_change)),"evidence_strength":evidence,"corroborating_channel_count":corroborating,"event":event})
    strength={"strong":2,"moderate":1,"weak":0}
    result.sort(key=lambda x:(x["event_time_loss_s"],strength[x["evidence_strength"]],safe_float(x["event"].get("length_m")) or 0.0,abs(safe_float(x["event"].get("mean_difference")) or 0.0)), reverse=True)
    for rank,item in enumerate(result,start=1): item["rank"]=rank
    return result


def enrich_objective_v38(zones, comparison):
    enriched=[]
    for zone in zones:
        record=dict(zone)
        record["loss_clusters"]=detect_loss_clusters(comparison, zone)
        record["sustained_events"]=detect_sustained_channel_events(comparison, zone["start_distance_m"], zone["end_distance_m"])
        enriched.append(record)
    return enriched


def _event_channel_name(event):
    event_type = str(event.get("type") or "")
    prefix = "sustained_"
    suffix = "_difference"
    if event_type.startswith(prefix) and event_type.endswith(suffix):
        return event_type[len(prefix):-len(suffix)]
    return event_type or "unknown"


def _interval_overlap_m(start_a, end_a, start_b, end_b):
    return max(
        0.0,
        min(float(end_a), float(end_b))
        - max(float(start_a), float(start_b)),
    )


def _episode_evidence_strength(
    episode_time_loss_s,
    length_m,
    channel_count,
    has_loss_cluster_support,
):
    """
    Fuerza de EVIDENCIA objetiva, no certeza causal.
    """
    if (
        episode_time_loss_s >= 0.08
        and length_m >= 25.0
        and (
            channel_count >= 2
            or has_loss_cluster_support
        )
    ):
        return "strong"

    if (
        episode_time_loss_s >= 0.05
        and length_m >= 25.0
    ):
        return "strong"

    if (
        episode_time_loss_s >= 0.03
        and length_m >= MIN_LOSS_EPISODE_DISTANCE_M
    ):
        return "moderate"

    return "weak"


def build_loss_episodes_for_zone(
    comparison,
    zone_item,
):
    """
    Agrupa eventos sostenidos solapados o cercanos dentro de una zona loss.

    IMPORTANTE:

    - NO suma event_time_loss_s de eventos individuales.
    - El tiempo del episodio se calcula UNA sola vez usando time_delta
      entre el inicio y el final del episodio.
    - Los canales son evidencias concurrentes, no causas demostradas.
    """
    sustained_events = []

    for event in zone_item.get("sustained_events", []):
        start_m = safe_float(event.get("start_distance_m"))
        end_m = safe_float(event.get("end_distance_m"))
        event_delta = safe_float(
            event.get("time_delta_change_during_event_s")
        )

        if (
            start_m is None
            or end_m is None
            or end_m <= start_m
            or event_delta is None
            or event_delta <= 0.0
        ):
            continue

        sustained_events.append(event)

    if not sustained_events:
        return []

    sustained_events.sort(
        key=lambda event: (
            float(event["start_distance_m"]),
            float(event["end_distance_m"]),
        )
    )

    groups = []
    current = None

    for event in sustained_events:
        event_start = float(event["start_distance_m"])
        event_end = float(event["end_distance_m"])

        if current is None:
            current = {
                "start_distance_m": event_start,
                "end_distance_m": event_end,
                "events": [event],
            }
            continue

        if (
            event_start
            <= current["end_distance_m"] + LOSS_EPISODE_MERGE_GAP_M
        ):
            current["end_distance_m"] = max(
                current["end_distance_m"],
                event_end,
            )
            current["events"].append(event)
        else:
            groups.append(current)
            current = {
                "start_distance_m": event_start,
                "end_distance_m": event_end,
                "events": [event],
            }

    if current is not None:
        groups.append(current)

    episodes = []
    loss_clusters = zone_item.get("loss_clusters", [])

    for group in groups:
        start_m = float(group["start_distance_m"])
        end_m = float(group["end_distance_m"])
        length_m = end_m - start_m

        if length_m < MIN_LOSS_EPISODE_DISTANCE_M:
            continue

        delta_start, delta_end, delta_change = _segment_time_delta(
            comparison,
            start_m,
            end_m,
        )

        if (
            delta_change is None
            or delta_change < MIN_LOSS_EPISODE_TIME_S
        ):
            continue

        channels = sorted(
            {
                _event_channel_name(event)
                for event in group["events"]
            }
        )

        evidence_by_channel = {}

        for channel in channels:
            channel_events = [
                event
                for event in group["events"]
                if _event_channel_name(event) == channel
            ]

            total_supported_length = float(
                sum(
                    safe_float(event.get("length_m")) or 0.0
                    for event in channel_events
                )
            )

            mean_differences = [
                safe_float(event.get("mean_difference"))
                for event in channel_events
            ]
            mean_differences = [
                value
                for value in mean_differences
                if value is not None
            ]

            peak_differences = [
                safe_float(event.get("peak_difference"))
                for event in channel_events
            ]
            peak_differences = [
                value
                for value in peak_differences
                if value is not None
            ]

            strongest_peak = None
            if peak_differences:
                strongest_peak = max(
                    peak_differences,
                    key=abs,
                )

            evidence_by_channel[channel] = {
                "event_count": len(channel_events),
                "supported_length_m": safe_float(
                    total_supported_length
                ),
                "mean_of_event_mean_differences": (
                    safe_float(np.mean(mean_differences))
                    if mean_differences
                    else None
                ),
                "largest_abs_peak_difference": safe_float(
                    strongest_peak
                ),
                "events": channel_events,
            }

        supporting_clusters = []

        for cluster in loss_clusters:
            overlap = _interval_overlap_m(
                start_m,
                end_m,
                cluster["start_distance_m"],
                cluster["end_distance_m"],
            )

            if overlap <= 0.0:
                continue

            supporting_clusters.append({
                "cluster_rank": cluster.get("rank"),
                "cluster_start_distance_m": safe_float(
                    cluster.get("start_distance_m")
                ),
                "cluster_end_distance_m": safe_float(
                    cluster.get("end_distance_m")
                ),
                "cluster_delta_loss_s": safe_float(
                    cluster.get("delta_loss_s")
                ),
                "overlap_m": safe_float(overlap),
            })

        evidence_strength = _episode_evidence_strength(
            float(delta_change),
            length_m,
            len(channels),
            bool(supporting_clusters),
        )

        parent_zone_loss = safe_float(
            zone_item.get("delta_loss_s")
        )

        parent_equivalent = None
        if parent_zone_loss is not None and parent_zone_loss > 0:
            parent_equivalent = (
                float(delta_change)
                / parent_zone_loss
                * 100.0
            )

        episodes.append({
            "rank": None,
            "zone_id": zone_item.get("zone_id"),
            "parent_zone_rank": zone_item.get("rank"),
            "start_distance_m": safe_float(start_m),
            "end_distance_m": safe_float(end_m),
            "length_m": safe_float(length_m),
            "delta_start_s": delta_start,
            "delta_end_s": delta_end,
            "episode_time_loss_s": safe_float(delta_change),
            "parent_zone_delta_loss_s": parent_zone_loss,
            "parent_zone_net_loss_equivalent_percent": safe_float(
                parent_equivalent
            ),
            "evidence_strength": evidence_strength,
            "evidence_channel_count": len(channels),
            "evidence_channels": channels,
            "evidence_by_channel": evidence_by_channel,
            "supporting_loss_clusters": supporting_clusters,
            "supporting_loss_cluster_count": len(
                supporting_clusters
            ),
            "source_event_count": len(group["events"]),
            "source_events": group["events"],
            "interpretation": {
                "causal_claim": False,
                "event_times_are_not_summed": True,
                "episode_time_is_computed_once_from_time_delta": True,
            },
        })

    episodes.sort(
        key=lambda episode: (
            episode["episode_time_loss_s"],
            episode["evidence_channel_count"],
            episode["length_m"],
        ),
        reverse=True,
    )

    for rank, episode in enumerate(episodes, start=1):
        episode["rank"] = rank

    return episodes




# ============================================================
# v3.8 - EPISODIOS DE ACCIÓN + PROPAGACIÓN DE VELOCIDAD
# ============================================================


def _is_driver_action_event(event):
    return _event_channel_name(event) in DRIVER_ACTION_CHANNELS


def _is_speed_event(event):
    return _event_channel_name(event) == "speed"


def _propagation_status(delta_change):
    if delta_change is None:
        return "unknown"
    if delta_change > SPEED_PROPAGATION_NEUTRAL_TIME_S:
        return "continues_losing_time"
    if delta_change < -SPEED_PROPAGATION_NEUTRAL_TIME_S:
        return "recovers_time"
    return "stable_deficit"


def _summarize_events_by_channel(events):
    channels = sorted({_event_channel_name(event) for event in events})
    result = {}

    for channel in channels:
        channel_events = [
            event
            for event in events
            if _event_channel_name(event) == channel
        ]

        supported_length = float(sum(
            safe_float(event.get("length_m")) or 0.0
            for event in channel_events
        ))

        means = [
            safe_float(event.get("mean_difference"))
            for event in channel_events
        ]
        means = [value for value in means if value is not None]

        peaks = [
            safe_float(event.get("peak_difference"))
            for event in channel_events
        ]
        peaks = [value for value in peaks if value is not None]

        strongest_peak = max(peaks, key=abs) if peaks else None

        result[channel] = {
            "event_count": len(channel_events),
            "supported_length_m": safe_float(supported_length),
            "mean_of_event_mean_differences": (
                safe_float(np.mean(means)) if means else None
            ),
            "largest_abs_peak_difference": safe_float(strongest_peak),
            "events": channel_events,
        }

    return result


def _driver_action_evidence_strength(
    action_time_loss_s,
    length_m,
    action_channel_count,
    has_speed_support,
    has_loss_cluster_support,
):
    """Fuerza de evidencia objetiva. NO expresa certeza causal."""
    if (
        action_time_loss_s >= 0.08
        and length_m >= 25.0
        and (
            action_channel_count >= 2
            or (has_speed_support and has_loss_cluster_support)
        )
    ):
        return "strong"

    if (
        action_time_loss_s >= 0.05
        and length_m >= 25.0
        and (has_speed_support or has_loss_cluster_support)
    ):
        return "strong"

    if (
        action_time_loss_s >= 0.03
        and length_m >= MIN_DRIVER_ACTION_EPISODE_DISTANCE_M
    ):
        return "moderate"

    return "weak"


def build_driver_action_episodes_for_zone(comparison, zone_item):
    """
    Construye episodios usando SOLO inputs del piloto:

    - throttle
    - brake
    - steering magnitude

    Una diferencia sostenida de velocidad NO puede unir dos episodios.
    La velocidad se adjunta como evidencia concurrente o propagación posterior.
    """
    all_events = list(zone_item.get("sustained_events", []))

    action_events = []
    speed_events = []

    for event in all_events:
        start_m = safe_float(event.get("start_distance_m"))
        end_m = safe_float(event.get("end_distance_m"))
        event_delta = safe_float(
            event.get("time_delta_change_during_event_s")
        )

        if (
            start_m is None
            or end_m is None
            or end_m <= start_m
        ):
            continue

        if _is_speed_event(event):
            speed_events.append(event)
            continue

        if not _is_driver_action_event(event):
            continue

        # Para el episodio originador solo interesan acciones que
        # coinciden con crecimiento del déficit. Las demás siguen
        # disponibles en sustained_events como evidencia secundaria.
        if event_delta is None or event_delta <= 0.0:
            continue

        action_events.append(event)

    action_events.sort(
        key=lambda event: (
            float(event["start_distance_m"]),
            float(event["end_distance_m"]),
        )
    )

    groups = []
    current = None

    for event in action_events:
        event_start = float(event["start_distance_m"])
        event_end = float(event["end_distance_m"])

        if current is None:
            current = {
                "start_distance_m": event_start,
                "end_distance_m": event_end,
                "events": [event],
            }
            continue

        if (
            event_start
            <= current["end_distance_m"]
            + DRIVER_ACTION_EPISODE_MERGE_GAP_M
        ):
            current["end_distance_m"] = max(
                current["end_distance_m"],
                event_end,
            )
            current["events"].append(event)
        else:
            groups.append(current)
            current = {
                "start_distance_m": event_start,
                "end_distance_m": event_end,
                "events": [event],
            }

    if current is not None:
        groups.append(current)

    episodes = []
    loss_clusters = zone_item.get("loss_clusters", [])

    for group_index, group in enumerate(groups):
        start_m = float(group["start_distance_m"])
        end_m = float(group["end_distance_m"])
        length_m = end_m - start_m

        if length_m < MIN_DRIVER_ACTION_EPISODE_DISTANCE_M:
            continue

        delta_start, delta_end, action_delta = _segment_time_delta(
            comparison,
            start_m,
            end_m,
        )

        if (
            action_delta is None
            or action_delta < MIN_DRIVER_ACTION_EPISODE_TIME_S
        ):
            continue

        next_action_start = None
        if group_index + 1 < len(groups):
            next_action_start = float(
                groups[group_index + 1]["start_distance_m"]
            )

        action_channels = sorted({
            _event_channel_name(event)
            for event in group["events"]
        })

        # Velocidad concurrente: apoya que la acción coincide con
        # una diferencia de performance, pero no amplía el episodio.
        concurrent_speed_events = []
        propagation_records = []

        for speed_event in speed_events:
            speed_start = float(speed_event["start_distance_m"])
            speed_end = float(speed_event["end_distance_m"])

            overlap = _interval_overlap_m(
                start_m,
                end_m,
                speed_start,
                speed_end,
            )

            linked_by_proximity = (
                speed_start <= end_m + SPEED_LINK_GAP_M
                and speed_end >= start_m - SPEED_LINK_GAP_M
            )

            if overlap > 0.0:
                concurrent_speed_events.append(speed_event)

            if not linked_by_proximity:
                continue

            propagation_start = max(end_m, speed_start)
            propagation_end = speed_end

            if next_action_start is not None:
                propagation_end = min(
                    propagation_end,
                    next_action_start,
                )

            propagation_length = (
                propagation_end - propagation_start
            )

            if (
                propagation_length
                < MIN_SPEED_PROPAGATION_DISTANCE_M
            ):
                continue

            p_start_delta, p_end_delta, p_change = (
                _segment_time_delta(
                    comparison,
                    propagation_start,
                    propagation_end,
                )
            )

            propagation_records.append({
                "start_distance_m": safe_float(propagation_start),
                "end_distance_m": safe_float(propagation_end),
                "length_m": safe_float(propagation_length),
                "delta_start_s": p_start_delta,
                "delta_end_s": p_end_delta,
                "time_delta_change_s": p_change,
                "status": _propagation_status(p_change),
                "speed_event": speed_event,
                "interpretation": {
                    "driver_action": False,
                    "potential_consequence_of_prior_action": True,
                    "causal_claim": False,
                    "does_not_extend_action_episode": True,
                },
            })

        supporting_clusters = []
        for cluster in loss_clusters:
            overlap = _interval_overlap_m(
                start_m,
                end_m,
                cluster["start_distance_m"],
                cluster["end_distance_m"],
            )
            if overlap <= 0.0:
                continue
            supporting_clusters.append({
                "cluster_rank": cluster.get("rank"),
                "cluster_start_distance_m": safe_float(
                    cluster.get("start_distance_m")
                ),
                "cluster_end_distance_m": safe_float(
                    cluster.get("end_distance_m")
                ),
                "cluster_delta_loss_s": safe_float(
                    cluster.get("delta_loss_s")
                ),
                "overlap_m": safe_float(overlap),
            })

        evidence_strength = _driver_action_evidence_strength(
            float(action_delta),
            length_m,
            len(action_channels),
            bool(concurrent_speed_events),
            bool(supporting_clusters),
        )

        parent_zone_loss = safe_float(
            zone_item.get("delta_loss_s")
        )

        parent_equivalent = None
        if parent_zone_loss is not None and parent_zone_loss > 0.0:
            parent_equivalent = (
                float(action_delta)
                / parent_zone_loss
                * 100.0
            )

        episodes.append({
            "rank": None,
            "zone_id": zone_item.get("zone_id"),
            "parent_zone_rank": zone_item.get("rank"),
            "start_distance_m": safe_float(start_m),
            "end_distance_m": safe_float(end_m),
            "length_m": safe_float(length_m),
            "delta_start_s": delta_start,
            "delta_end_s": delta_end,
            "action_time_loss_s": safe_float(action_delta),
            "parent_zone_delta_loss_s": parent_zone_loss,
            "parent_zone_net_loss_equivalent_percent": safe_float(
                parent_equivalent
            ),
            "evidence_strength": evidence_strength,
            "action_channel_count": len(action_channels),
            "action_channels": action_channels,
            "action_evidence_by_channel": _summarize_events_by_channel(
                group["events"]
            ),
            "concurrent_speed_event_count": len(
                concurrent_speed_events
            ),
            "concurrent_speed_events": concurrent_speed_events,
            "speed_propagation": propagation_records,
            "supporting_loss_clusters": supporting_clusters,
            "supporting_loss_cluster_count": len(
                supporting_clusters
            ),
            "source_action_event_count": len(group["events"]),
            "source_action_events": group["events"],
            "interpretation": {
                "primary_unit": "driver_action_episode",
                "causal_claim": False,
                "speed_is_not_used_to_merge_actions": True,
                "speed_propagation_is_consequence_candidate": True,
                "action_time_is_computed_once_from_time_delta": True,
            },
        })

    episodes.sort(
        key=lambda episode: (
            episode["action_time_loss_s"],
            episode["action_channel_count"],
            episode["length_m"],
        ),
        reverse=True,
    )

    for rank, episode in enumerate(episodes, start=1):
        episode["rank"] = rank

    return episodes


def build_driver_action_episode_ranking(comparison, loss_ranking):
    episodes = []

    for zone_item in loss_ranking:
        zone_episodes = build_driver_action_episodes_for_zone(
            comparison,
            zone_item,
        )
        zone_item["driver_action_episodes"] = zone_episodes
        for episode in zone_episodes:
            episodes.append(dict(episode))

    evidence_priority = {
        "strong": 2,
        "moderate": 1,
        "weak": 0,
    }

    episodes.sort(
        key=lambda episode: (
            episode["action_time_loss_s"],
            evidence_priority.get(
                episode.get("evidence_strength"),
                0,
            ),
            episode["action_channel_count"],
            episode["length_m"],
        ),
        reverse=True,
    )

    for global_rank, episode in enumerate(episodes, start=1):
        episode["global_rank"] = global_rank

    return episodes


def build_unattributed_speed_propagation(
    comparison,
    loss_ranking,
    driver_action_episode_ranking,
):
    """
    Diferencias sostenidas de velocidad en zonas loss que no quedan
    razonablemente asociadas a un episodio de acción detectado.

    Se reportan como pérdida/propagación SIN causa atribuida.
    """
    results = []

    action_intervals = [
        (
            float(item["start_distance_m"]),
            float(item["end_distance_m"]),
        )
        for item in driver_action_episode_ranking
    ]

    for zone_item in loss_ranking:
        for event in zone_item.get("sustained_events", []):
            if not _is_speed_event(event):
                continue

            start_m = safe_float(event.get("start_distance_m"))
            end_m = safe_float(event.get("end_distance_m"))
            event_delta = safe_float(
                event.get("time_delta_change_during_event_s")
            )

            if (
                start_m is None
                or end_m is None
                or end_m <= start_m
                or event_delta is None
                or event_delta <= 0.0
            ):
                continue

            associated = False
            for action_start, action_end in action_intervals:
                if (
                    end_m >= action_start - SPEED_LINK_GAP_M
                    and start_m <= action_end + SPEED_LINK_GAP_M
                ):
                    associated = True
                    break

            if associated:
                continue

            results.append({
                "rank": None,
                "zone_id": zone_item.get("zone_id"),
                "parent_zone_rank": zone_item.get("rank"),
                "start_distance_m": start_m,
                "end_distance_m": end_m,
                "length_m": safe_float(end_m - start_m),
                "time_delta_change_s": event_delta,
                "speed_event": event,
                "classification": "unattributed_speed_loss",
                "interpretation": {
                    "driver_action_detected": False,
                    "causal_claim": False,
                    "possible_origin_before_current_interval": True,
                },
            })

    results.sort(
        key=lambda item: item["time_delta_change_s"],
        reverse=True,
    )

    for rank, item in enumerate(results, start=1):
        item["rank"] = rank

    return results

def build_loss_episode_ranking(
    comparison,
    loss_ranking,
):
    """
    Ranking global de episodios de pérdida.

    Un episodio puede contener varios canales, pero su tiempo se cuenta
    una sola vez.
    """
    episodes = []

    for zone_item in loss_ranking:
        zone_episodes = build_loss_episodes_for_zone(
            comparison,
            zone_item,
        )

        zone_item["loss_episodes"] = zone_episodes

        for episode in zone_episodes:
            episodes.append(dict(episode))

    evidence_priority = {
        "strong": 2,
        "moderate": 1,
        "weak": 0,
    }

    episodes.sort(
        key=lambda episode: (
            episode["episode_time_loss_s"],
            evidence_priority.get(
                episode["evidence_strength"],
                0,
            ),
            episode["evidence_channel_count"],
            episode["length_m"],
        ),
        reverse=True,
    )

    for global_rank, episode in enumerate(
        episodes,
        start=1,
    ):
        episode["global_rank"] = global_rank

    return episodes


def build_objective_analysis(zones, real_delta, comparison):
    time_accounting = build_objective_time_accounting(
        zones,
        real_delta,
    )

    loss_ranking = build_objective_loss_ranking(
        zones,
        real_delta,
        time_accounting["gross_loss_s"] or 0.0,
    )

    gain_ranking = build_objective_gain_ranking(zones)

    event_ranking = build_objective_event_ranking(
        loss_ranking
    )

    loss_clusters = []

    for zone_item in loss_ranking:
        for cluster in zone_item.get(
            "loss_clusters",
            [],
        ):
            loss_clusters.append({
                "zone_rank": zone_item["rank"],
                "zone_id": zone_item["zone_id"],
                "parent_zone_delta_loss_s": zone_item[
                    "delta_loss_s"
                ],
                **cluster,
            })

    loss_clusters.sort(
        key=lambda item: item["delta_loss_s"],
        reverse=True,
    )

    for rank, cluster in enumerate(
        loss_clusters,
        start=1,
    ):
        cluster["global_rank"] = rank

    # Compatibilidad v3.7: episodio genérico basado en todos los canales.
    loss_episode_ranking = build_loss_episode_ranking(
        comparison,
        loss_ranking,
    )

    # v3.8: unidad primaria. Speed NO une acciones del piloto.
    driver_action_episode_ranking = (
        build_driver_action_episode_ranking(
            comparison,
            loss_ranking,
        )
    )

    unattributed_speed_propagation = (
        build_unattributed_speed_propagation(
            comparison,
            loss_ranking,
            driver_action_episode_ranking,
        )
    )

    return {
        "priority": "time_loss",
        "primary_interpretation_unit": "driver_action_episode",
        "time_accounting": time_accounting,
        "loss_ranking": loss_ranking,
        "gain_ranking": gain_ranking,
        "loss_clusters": loss_clusters,
        "driver_action_episode_ranking": (
            driver_action_episode_ranking
        ),
        "unattributed_speed_propagation": (
            unattributed_speed_propagation
        ),
        "loss_episode_ranking": loss_episode_ranking,
        "event_ranking": event_ranking,
        "interpretation_constraints": {
            "events_are_not_causes": True,
            "driver_action_episodes_are_primary": True,
            "speed_never_merges_driver_action_episodes": True,
            "speed_propagation_is_not_driver_input": True,
            "speed_propagation_may_be_consequence": True,
            "unattributed_speed_loss_has_no_assigned_cause": True,
            "legacy_loss_episodes_are_secondary": True,
            "event_times_are_not_additive": True,
            "persistent_events_preferred_over_instantaneous_extremes": True,
            "steering_ranking_uses_magnitude_difference": True,
            "python_does_not_diagnose_driver_behavior": True,
        },
    }


# ============================================================
# VALIDACIÓN TEMPORAL
# ============================================================


def validate_temporal_accounting(
    zones,
    calculated_delta,
    real_delta,
    reference_time,
    comparison_time,
):
    zone_delta_sum = float(
        sum(
            zone["delta_change_s"]
            for zone in zones
            if zone["delta_change_s"] is not None
        )
    )

    spatial_vs_calculated_error = (
        zone_delta_sum - calculated_delta
    )

    calculated_vs_real_error = (
        calculated_delta - real_delta
    )

    zone_sum_vs_real_error = (
        zone_delta_sum - real_delta
    )

    status = (
        "OK"
        if (
            abs(zone_sum_vs_real_error)
            <= TEMPORAL_VALIDATION_TOLERANCE
            and abs(calculated_vs_real_error)
            <= TEMPORAL_VALIDATION_TOLERANCE
        )
        else "WARNING"
    )

    return {
        "status": status,
        "reference_time_s": safe_float(reference_time),
        "comparison_time_s": safe_float(comparison_time),
        "real_delta_s": safe_float(real_delta),
        "calculated_spatial_delta_s": safe_float(
            calculated_delta
        ),
        "zone_delta_sum_s": safe_float(zone_delta_sum),
        "zone_sum_vs_real_error_s": safe_float(
            zone_sum_vs_real_error
        ),
        "spatial_vs_calculated_error_s": safe_float(
            spatial_vs_calculated_error
        ),
        "calculated_vs_real_error_s": safe_float(
            calculated_vs_real_error
        ),
        "tolerance_s": TEMPORAL_VALIDATION_TOLERANCE,
    }


# ============================================================
# VALIDAR TIEMPOS DE VUELTA
# ============================================================


def validate_lap_times(laps_df):
    required_columns = [
        "lap",
        "duration",
    ]

    missing = [
        column
        for column in required_columns
        if column not in laps_df.columns
    ]

    if missing:
        raise RuntimeError(
            "Faltan columnas necesarias "
            f"para validar tiempos: {missing}"
        )

    print()
    print("Validando tiempos de vuelta...")

    lap_times = {}

    for _, row in laps_df.iterrows():
        lap = safe_int(row["lap"])
        duration = safe_float(row["duration"])

        if (
            lap is None
            or duration is None
            or duration <= 0
        ):
            print(
                f"  lap {lap}: TIEMPO INVALIDO"
            )
            continue

        lap_times[lap] = duration

        print(
            f"  lap {lap}: {duration:.4f} s"
        )

    if not lap_times:
        raise RuntimeError(
            "No fue posible determinar ningún tiempo de vuelta válido."
        )

    return lap_times


# ============================================================
# VALIDACIÓN DEL MODELO
# ============================================================


def validate_comparison_model(
    reference_lap,
    comparable_laps,
    usable_df,
    discarded_df,
):
    print("\nValidando modelo de datos...")
    print("Modelo confirmado:")
    print("mismo vehículo / distintas vueltas")
    print()
    print(f"Vuelta de referencia: {reference_lap}")
    print(f"Vueltas válidas: {list(usable_df['lap'])}")
    print(f"Vueltas descartadas: {list(discarded_df['lap'])}")
    print(
        f"Comparaciones disponibles: {len(comparable_laps)}"
    )


# ============================================================
# PRIORIDAD DE COMPARACIONES PARA EL LLM
# ============================================================


def build_comparison_priority_map(
    reference_lap,
    comparable_laps,
    lap_times,
):
    reference_time = lap_times[reference_lap]

    ranked = sorted(
        comparable_laps,
        key=lambda lap: abs(
            lap_times[lap] - reference_time
        ),
    )

    result = {}

    for rank, lap in enumerate(ranked, start=1):
        result[lap] = {
            "rank": rank,
            "recommended_for_driver_analysis": (
                rank <= MAX_DRIVER_ANALYSIS_COMPARISONS
            ),
            "selection_basis": "closest_lap_time_to_reference",
        }

    return result


# ============================================================
# VALIDACIÓN GLOBAL DEL OUTPUT
# ============================================================


def validate_global_output(analysis_output):
    comparisons = analysis_output.get(
        "comparisons",
        [],
    )

    if not comparisons:
        return False

    for comparison in comparisons:
        temporal = comparison.get(
            "temporal_validation",
            {},
        )

        if temporal.get("status") != "OK":
            return False

        objective = comparison.get(
            "objective_analysis",
            {},
        )

        losses = objective.get(
            "loss_ranking",
            [],
        )

        if any(
            item.get("delta_loss_s", 0.0)
            <= MIN_ZONE_TIME_DELTA_S
            for item in losses
        ):
            return False

        if any(
            item.get("type") != "loss"
            for item in losses
        ):
            return False

        loss_values = [
            item["delta_loss_s"]
            for item in losses
        ]

        if loss_values != sorted(
            loss_values,
            reverse=True,
        ):
            return False

        expected_ranks = list(
            range(1, len(losses) + 1)
        )

        actual_ranks = [
            item.get("rank")
            for item in losses
        ]

        if actual_ranks != expected_ranks:
            return False

        episodes = objective.get(
            "loss_episode_ranking",
            [],
        )

        episode_losses = [
            safe_float(item.get("episode_time_loss_s"))
            for item in episodes
        ]

        if any(
            value is None
            or value < MIN_LOSS_EPISODE_TIME_S
            for value in episode_losses
        ):
            return False

        if episode_losses != sorted(
            episode_losses,
            reverse=True,
        ):
            return False

        expected_episode_ranks = list(
            range(1, len(episodes) + 1)
        )

        actual_episode_ranks = [
            item.get("global_rank")
            for item in episodes
        ]

        if actual_episode_ranks != expected_episode_ranks:
            return False

        episodes_by_zone = {}
        for episode in episodes:
            episodes_by_zone.setdefault(
                episode.get("zone_id"),
                [],
            ).append(episode)

        for zone_episodes in episodes_by_zone.values():
            ordered = sorted(
                zone_episodes,
                key=lambda item: item["start_distance_m"],
            )
            for index in range(1, len(ordered)):
                if (
                    ordered[index]["start_distance_m"]
                    < ordered[index - 1]["end_distance_m"]
                ):
                    return False

        action_episodes = objective.get(
            "driver_action_episode_ranking",
            [],
        )

        action_losses = [
            safe_float(item.get("action_time_loss_s"))
            for item in action_episodes
        ]

        if any(
            value is None
            or value < MIN_DRIVER_ACTION_EPISODE_TIME_S
            for value in action_losses
        ):
            return False

        if action_losses != sorted(
            action_losses,
            reverse=True,
        ):
            return False

        expected_action_ranks = list(
            range(1, len(action_episodes) + 1)
        )

        actual_action_ranks = [
            item.get("global_rank")
            for item in action_episodes
        ]

        if actual_action_ranks != expected_action_ranks:
            return False

        action_by_zone = {}
        for episode in action_episodes:
            action_by_zone.setdefault(
                episode.get("zone_id"),
                [],
            ).append(episode)

            if "speed" in episode.get("action_channels", []):
                return False

        for zone_episodes in action_by_zone.values():
            ordered = sorted(
                zone_episodes,
                key=lambda item: item["start_distance_m"],
            )
            for index in range(1, len(ordered)):
                if (
                    ordered[index]["start_distance_m"]
                    < ordered[index - 1]["end_distance_m"]
                ):
                    return False

        time_accounting = objective.get(
            "time_accounting",
            {},
        )

        accounting_error = safe_float(
            time_accounting.get("accounting_error_s")
        )

        if (
            accounting_error is None
            or abs(accounting_error)
            > TEMPORAL_VALIDATION_TOLERANCE
        ):
            return False

    return True


# ============================================================
# MAIN
# ============================================================


def main():
    print_header(
        "RACE ENGINEER - TELEMETRY ANALYSIS v3.8"
    )

    print()
    print("Archivo:")
    print(f"  {FILE_INFO['filename']}")
    print()
    print("Circuito:")
    print(f"  {FILE_INFO['track']}")
    print()
    print("Sesión:")
    print(f"  {FILE_INFO['session_type']}")
    print()
    print("Fecha/hora UTC:")
    print(f"  {FILE_INFO['timestamp_utc']}")
    print()
    print("JSON de salida:")
    print(f"  {OUTPUT_PATH}")

    if VALIDATE_ONLY:
        print()
        print("Modo: VALIDATE")

    # ========================================================
    # BASE DE DATOS
    # ========================================================

    print("\n[1] Base de datos:")
    print(DB_PATH)

    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"No existe la base de datos:\n{DB_PATH}"
        )

    print("DB OK")

    # ========================================================
    # TELEMETRY
    # ========================================================

    print("\n[2] Cargando telemetry...")
    telemetry = Telemetry(DB_PATH)
    print("Telemetry OK")

    try:
        # ====================================================
        # LAP ANALYZER
        # ====================================================

        print("\n[3] Creando LapAnalyzer...")
        lap_analyzer = LapAnalyzer(telemetry)
        print("LapAnalyzer OK")

        # ====================================================
        # VUELTAS
        # ====================================================

        print("\n[4] Detectando vueltas...")

        laps = lap_analyzer.all_lap_summaries()

        if isinstance(laps, list):
            laps_df = pd.DataFrame(laps)
        else:
            laps_df = laps.copy()

        if laps_df.empty:
            raise RuntimeError(
                "No se detectaron vueltas."
            )

        print(
            f"Vueltas detectadas: {len(laps_df)}"
        )
        print(
            laps_df.to_string(index=False)
        )

        lap_times = validate_lap_times(
            laps_df
        )

        # ====================================================
        # SELECCIÓN DE VUELTAS
        # ====================================================

        print("\n[5] Seleccionando vueltas...")

        initial_laps_df = laps_df[
            laps_df["lap"] < IGNORE_INITIAL_LAPS
        ].copy()

        candidate_laps_df = laps_df[
            laps_df["lap"] >= IGNORE_INITIAL_LAPS
        ].copy()

        if not initial_laps_df.empty:
            print("\nVueltas iniciales ignoradas:")

            for _, row in initial_laps_df.iterrows():
                lap = safe_int(row["lap"])
                duration = safe_float(row["duration"])
                distance = safe_float(row["lap_distance"])

                print(
                    f"  lap={lap} "
                    f"duration={duration:.3f}s "
                    f"distance={distance:.3f}m "
                    "reason=initial_lap"
                )

        if candidate_laps_df.empty:
            raise RuntimeError(
                "No quedaron vueltas después de descartar "
                "las vueltas iniciales."
            )

        reference_distance = float(
            candidate_laps_df["lap_distance"].max()
        )

        minimum_distance = (
            reference_distance * VALID_DISTANCE_RATIO
        )

        usable_df = candidate_laps_df[
            (candidate_laps_df["duration"] >= MIN_LAP_DURATION)
            &
            (candidate_laps_df["lap_distance"] >= minimum_distance)
        ].copy()

        discarded_df = candidate_laps_df[
            ~candidate_laps_df["lap"].isin(
                usable_df["lap"]
            )
        ].copy()

        if usable_df.empty:
            raise RuntimeError(
                "No hay vueltas utilizables."
            )

        usable_df = (
            usable_df
            .sort_values("duration")
            .reset_index(drop=True)
        )

        reference_lap = safe_int(
            usable_df.iloc[0]["lap"]
        )

        comparable_laps = [
            safe_int(lap)
            for lap in usable_df["lap"]
            if safe_int(lap) != reference_lap
        ]

        comparison_priority = build_comparison_priority_map(
            reference_lap,
            comparable_laps,
            lap_times,
        )

        print()
        print(
            f"Distancia de referencia: {reference_distance:.3f} m"
        )
        print("\nVueltas utilizables:")

        for _, row in usable_df.iterrows():
            print(
                f"  lap={int(row['lap'])} "
                f"duration={row['duration']:.3f}s "
                f"distance={row['lap_distance']:.3f}m"
            )

        if not discarded_df.empty:
            print("\nVueltas descartadas:")

            for _, row in discarded_df.iterrows():
                reasons = []

                if row["duration"] < MIN_LAP_DURATION:
                    reasons.append("too_short")

                if row["lap_distance"] < minimum_distance:
                    reasons.append("incomplete_lap")

                print(
                    f"  lap={int(row['lap'])} "
                    f"duration={row['duration']:.3f}s "
                    f"distance={row['lap_distance']:.3f}m "
                    f"reason={','.join(reasons)}"
                )

        print()
        print(f"Vuelta de referencia: {reference_lap}")
        print(f"Vueltas comparables: {comparable_laps}")

        validate_comparison_model(
            reference_lap,
            comparable_laps,
            usable_df,
            discarded_df,
        )

        # ====================================================
        # DELTA / SECTORES
        # ====================================================

        print("\n[6] Creando DeltaComparison...")
        delta_comparison = DeltaComparison(lap_analyzer)
        print("DeltaComparison OK")

        print("\n[7] Creando SectorAnalysis...")
        sector_analysis = SectorAnalysis(delta_comparison)
        print("SectorAnalysis OK")

        # ====================================================
        # VALIDACIÓN TEMPORAL PREVIA
        # ====================================================

        print_header("VALIDACIÓN TEMPORAL")

        for lap_b in comparable_laps:
            reference_time = lap_times.get(reference_lap)
            comparison_time = lap_times.get(lap_b)

            if (
                reference_time is None
                or comparison_time is None
            ):
                raise RuntimeError(
                    "No existe tiempo absoluto válido para "
                    f"{reference_lap} -> {lap_b}"
                )

            real_delta = comparison_time - reference_time

            print(
                f"Comparación: {reference_lap} -> {lap_b}"
            )
            print(f"  Tiempo A: {reference_time}")
            print(f"  Tiempo B: {comparison_time}")
            print(f"  Delta real: {real_delta}")

        print()
        print("Validación temporal básica completa.")

        # ====================================================
        # OUTPUT GLOBAL
        # ====================================================

        analysis_output = {
            "metadata": {
                "analysis_version": "3.8",
                "source_file": FILE_INFO["filename"],
                "track": FILE_INFO["track"],
                "session_type": FILE_INFO["session_type"],
                "timestamp_utc": FILE_INFO["timestamp_utc"],
                "database": DB_PATH,
                "output_file": OUTPUT_PATH,
                "same_vehicle": True,
                "vehicle_count": 1,
                "lap_comparison_model": (
                    "same_vehicle_different_laps"
                ),
                "reference_lap": reference_lap,
                "reference_lap_role": "fastest_valid_lap",
                "comparison_laps": comparable_laps,
                "driver_analysis_priority": {
                    str(lap): data
                    for lap, data in comparison_priority.items()
                },
                "ignored_initial_laps": [
                    int(x)
                    for x in initial_laps_df["lap"]
                ],
                "reference_distance_m": safe_float(
                    reference_distance
                ),
                "valid_laps": [
                    int(x)
                    for x in usable_df["lap"]
                ],
                "discarded_laps": [
                    int(x)
                    for x in discarded_df["lap"]
                ],
                "lap_times_s": {
                    str(lap): safe_float(time)
                    for lap, time in lap_times.items()
                },
                "configuration": {
                    "ignore_initial_laps": IGNORE_INITIAL_LAPS,
                    "resolution_m": RESOLUTION,
                    "smoothing_window": SMOOTHING_WINDOW,
                    "min_zone_distance_m": MIN_ZONE_DISTANCE,
                    "valid_distance_ratio": VALID_DISTANCE_RATIO,
                    "min_lap_duration_s": MIN_LAP_DURATION,
                    "max_zones_per_comparison": MAX_ZONES,
                    "max_driver_analysis_comparisons": (
                        MAX_DRIVER_ANALYSIS_COMPARISONS
                    ),
                    "temporal_validation_tolerance_s": (
                        TEMPORAL_VALIDATION_TOLERANCE
                    ),
                    "zone_coverage_tolerance_m": (
                        ZONE_COVERAGE_TOLERANCE_M
                    ),
                    "min_zone_time_delta_s": (
                        MIN_ZONE_TIME_DELTA_S
                    ),
                    "objective_v38": {
                        "min_sustained_event_distance_m": MIN_SUSTAINED_EVENT_DISTANCE_M,
                        "max_sustained_event_gap_m": MAX_SUSTAINED_EVENT_GAP_M,
                        "min_loss_cluster_distance_m": MIN_LOSS_CLUSTER_DISTANCE_M,
                        "max_loss_cluster_gap_m": MAX_LOSS_CLUSTER_GAP_M,
                        "min_loss_cluster_time_s": MIN_LOSS_CLUSTER_TIME_S,
                        "loss_gradient_smoothing_m": LOSS_GRADIENT_SMOOTHING_M,
                        "driver_action_channels": sorted(DRIVER_ACTION_CHANNELS),
                        "driver_action_episode_merge_gap_m": DRIVER_ACTION_EPISODE_MERGE_GAP_M,
                        "min_driver_action_episode_time_s": MIN_DRIVER_ACTION_EPISODE_TIME_S,
                        "min_driver_action_episode_distance_m": MIN_DRIVER_ACTION_EPISODE_DISTANCE_M,
                        "speed_link_gap_m": SPEED_LINK_GAP_M,
                        "min_speed_propagation_distance_m": MIN_SPEED_PROPAGATION_DISTANCE_M,
                        "speed_propagation_neutral_time_s": SPEED_PROPAGATION_NEUTRAL_TIME_S,
                        "speed_can_merge_driver_actions": False,
                        "driver_action_episodes_are_primary": True,
                        "legacy_loss_episode_merge_gap_m": LOSS_EPISODE_MERGE_GAP_M,
                    },
                    "event_thresholds": {
                        "speed_kmh": SPEED_EVENT_THRESHOLD,
                        "throttle_percent": (
                            THROTTLE_EVENT_THRESHOLD
                        ),
                        "brake_percent": BRAKE_EVENT_THRESHOLD,
                        "steering": STEERING_EVENT_THRESHOLD,
                    },
                },
            },
            "laps": build_lap_summary(laps_df),
            "comparisons": [],
        }

        # ====================================================
        # COMPARACIONES
        # ====================================================

        for lap_b in comparable_laps:
            print_header(
                f"COMPARACIÓN {reference_lap} -> {lap_b}"
            )

            real_time_reference = lap_times.get(reference_lap)
            real_time_comparison = lap_times.get(lap_b)

            if (
                real_time_reference is None
                or real_time_comparison is None
            ):
                raise RuntimeError(
                    "Tiempo absoluto faltante para comparación "
                    f"{reference_lap} -> {lap_b}"
                )

            real_delta = (
                real_time_comparison - real_time_reference
            )

            priority_data = comparison_priority[lap_b]

            print(f"Tiempo A: {real_time_reference}")
            print(f"Tiempo B: {real_time_comparison}")
            print(f"Delta real: {real_delta}")
            print(
                "Prioridad análisis piloto: "
                f"#{priority_data['rank']} "
                f"({'SI' if priority_data['recommended_for_driver_analysis'] else 'NO'})"
            )

            comparison = delta_comparison.compare(
                reference_lap,
                lap_b,
                resolution=RESOLUTION,
            )

            if comparison.empty:
                print("Comparación vacía.")
                continue

            calculated_delta = safe_float(
                comparison["time_delta"].iloc[-1]
            )

            distance_final = safe_float(
                comparison["distance"].iloc[-1]
            )

            if calculated_delta is None:
                raise RuntimeError(
                    "Delta temporal calculado no disponible para "
                    f"{reference_lap} -> {lap_b}"
                )

            calculated_vs_real_error = (
                calculated_delta - real_delta
            )

            print(
                f"Delta calculado: {calculated_delta:+.6f} s"
            )
            print(
                "Error contra delta real: "
                f"{calculated_vs_real_error:+.6f} s"
            )

            if (
                abs(calculated_vs_real_error)
                > TEMPORAL_VALIDATION_TOLERANCE
            ):
                print(
                    "WARNING: SPATIAL_DELTA_VALIDATION_FAILED"
                )
            else:
                print("Delta temporal validado.")

            # ------------------------------------------------
            # SECTOR ANALYSIS
            # ------------------------------------------------

            print("\nAnalizando zonas...")

            result = sector_analysis.analyze(
                reference_lap,
                lap_b,
                resolution=RESOLUTION,
                smoothing_window=SMOOTHING_WINDOW,
                min_zone_distance=MIN_ZONE_DISTANCE,
            )

            if result is None:
                result = {}

            raw_zones = result.get("zones", [])

            if raw_zones is None:
                raw_zones = []

            print(
                "Zonas originales de SectorAnalysis: "
                f"{len(raw_zones)}"
            )
            print("Reconstruyendo contabilidad temporal...")

            zones = rebuild_temporal_zones(
                comparison,
                raw_zones,
            )

            zones = enrich_temporal_zones(
                zones,
                comparison,
            )

            zones = enrich_objective_v38(
                zones,
                comparison,
            )

            objective_analysis = build_objective_analysis(
                zones,
                real_delta,
                comparison,
            )

            loss_ranking = objective_analysis[
                "loss_ranking"
            ]
            event_ranking = objective_analysis[
                "event_ranking"
            ]
            driver_action_episode_ranking = objective_analysis[
                "driver_action_episode_ranking"
            ]
            unattributed_speed_propagation = objective_analysis[
                "unattributed_speed_propagation"
            ]
            loss_episode_ranking = objective_analysis[
                "loss_episode_ranking"
            ]
            time_accounting = objective_analysis[
                "time_accounting"
            ]

            print()
            print("RANKING OBJETIVO DE PÉRDIDA:")

            if loss_ranking:
                for item in loss_ranking:
                    share = item[
                        "gross_loss_share_percent"
                    ]

                    share_text = (
                        f"{share:.1f}%"
                        if share is not None
                        else "n/a"
                    )

                    print(
                        f"  #{item['rank']:02d} "
                        f"Zona {item['zone_id']:02d} "
                        f"{item['start_distance_m']:.0f}-"
                        f"{item['end_distance_m']:.0f} m "
                        f"LOSS={item['delta_loss_s']:+.4f} s "
                        f"({share_text} de pérdidas brutas)"
                    )
            else:
                print("  No se detectaron zonas loss.")

            print()
            print("CONTABILIDAD OBJETIVA:")
            print(
                "  Pérdidas brutas: "
                f"+{time_accounting['gross_loss_s']:.4f} s"
            )
            print(
                "  Ganancias compensatorias: "
                f"-{time_accounting['gross_gain_s']:.4f} s"
            )
            print(
                "  Neutral: "
                f"{time_accounting['neutral_delta_s']:+.4f} s"
            )
            print(
                "  Delta neto: "
                f"{real_delta:+.4f} s"
            )

            print()
            print("EPISODIOS DE ACCIÓN DEL PILOTO (PRIMARIOS):")

            if driver_action_episode_ranking:
                for episode in driver_action_episode_ranking[
                    :MAX_PRINTED_DRIVER_ACTION_EPISODES
                ]:
                    channels = ",".join(
                        episode.get("action_channels", [])
                    )
                    propagations = episode.get(
                        "speed_propagation",
                        [],
                    )
                    propagation_text = (
                        f" propagation={len(propagations)}"
                        if propagations
                        else ""
                    )
                    print(
                        f"  #{episode['global_rank']:02d} "
                        f"Zona {episode['zone_id']:02d} "
                        f"{episode['start_distance_m']:.0f}-"
                        f"{episode['end_distance_m']:.0f} m "
                        f"action_loss={episode['action_time_loss_s']:+.4f} s "
                        f"inputs={channels or 'n/a'} "
                        f"evidence={episode['evidence_strength']}"
                        f"{propagation_text}"
                    )
            else:
                print(
                    "  No hay episodios de acción detectados "
                    "con pérdida temporal suficiente."
                )

            print()
            print("PROPAGACIÓN DE VELOCIDAD SIN ACCIÓN ATRIBUIDA:")

            if unattributed_speed_propagation:
                for item in unattributed_speed_propagation[:10]:
                    print(
                        f"  #{item['rank']:02d} "
                        f"Zona {item['zone_id']:02d} "
                        f"{item['start_distance_m']:.0f}-"
                        f"{item['end_distance_m']:.0f} m "
                        f"delta_change={item['time_delta_change_s']:+.4f} s"
                    )
            else:
                print(
                    "  No hay propagaciones de velocidad "
                    "sin acción cercana detectada."
                )

            print()
            print("EPISODIOS v3.7 (COMPATIBILIDAD / SECUNDARIOS):")

            if loss_episode_ranking:
                for episode in loss_episode_ranking[:3]:
                    channels = ",".join(
                        episode.get("evidence_channels", [])
                    )
                    print(
                        f"  #{episode['global_rank']:02d} "
                        f"Zona {episode['zone_id']:02d} "
                        f"{episode['start_distance_m']:.0f}-"
                        f"{episode['end_distance_m']:.0f} m "
                        f"loss={episode['episode_time_loss_s']:+.4f} s "
                        f"channels={channels or 'n/a'}"
                    )
            else:
                print("  No hay episodios legacy.")

            print()
            print("EVENTOS SOSTENIDOS (EVIDENCIA SECUNDARIA):")

            if event_ranking:
                for item in event_ranking[:10]:
                    event = item["event"]
                    print(
                        f"  #{item['rank']:02d} "
                        f"Zona {item['zone_id']:02d} "
                        f"{event.get('type')} "
                        f"{event.get('start_distance_m'):.0f}-"
                        f"{event.get('end_distance_m'):.0f} m "
                        f"event_loss={item['event_time_loss_s']:+.4f} s "
                        f"evidence={item['evidence_strength']}"
                    )
            else:
                print("  No hay eventos sostenidos significativos en zonas loss.")

            ranked_zones = sorted(
                zones,
                key=zone_importance,
                reverse=True,
            )

            top_zones = ranked_zones[:MAX_ZONES]

            losses = [
                zone
                for zone in zones
                if zone["type"] == "loss"
            ]

            gains = [
                zone
                for zone in zones
                if zone["type"] == "gain"
            ]

            neutrals = [
                zone
                for zone in zones
                if zone["type"] == "neutral"
            ]

            temporal_validation = validate_temporal_accounting(
                zones,
                calculated_delta,
                real_delta,
                real_time_reference,
                real_time_comparison,
            )

            print()
            print("Validación temporal de zonas:")
            print(
                f"  Estado: {temporal_validation['status']}"
            )
            print(f"  Delta real: {real_delta:+.6f} s")
            print(
                "  Delta calculado: "
                f"{calculated_delta:+.6f} s"
            )
            print(
                "  Suma zonas: "
                f"{temporal_validation['zone_delta_sum_s']:+.6f} s"
            )
            print(
                "  Error zonas vs real: "
                f"{temporal_validation['zone_sum_vs_real_error_s']:+.6f} s"
            )

            if zones:
                print()
                print("Cobertura de zonas:")
                print(
                    "  Inicio: "
                    f"{zones[0]['start_distance_m']:.3f} m"
                )
                print(
                    "  Final: "
                    f"{zones[-1]['end_distance_m']:.3f} m"
                )
                print(
                    "  Distancia comparación: "
                    f"{distance_final:.3f} m"
                )

            print()
            print(f"Zonas reconstruidas: {len(zones)}")
            print(f"Pérdidas: {len(losses)}")
            print(f"Ganancias: {len(gains)}")
            print(f"Neutrales: {len(neutrals)}")
            print()

            for zone in top_zones:
                print(
                    f"Zona {zone['zone_id']:02d}: "
                    f"{zone['start_distance_m']:.0f}-"
                    f"{zone['end_distance_m']:.0f} m "
                    f"{zone['type']} "
                    f"delta={zone['delta_change_s']:+.4f} s"
                )

            comparison_output = {
                "same_vehicle": True,
                "reference_lap": reference_lap,
                "comparison_lap": lap_b,
                "reference_lap_role": "fastest_valid_lap",
                "comparison_lap_role": "other_valid_lap",
                "driver_analysis_priority_rank": (
                    priority_data["rank"]
                ),
                "recommended_for_driver_analysis": (
                    priority_data[
                        "recommended_for_driver_analysis"
                    ]
                ),
                "reference_time_s": safe_float(
                    real_time_reference
                ),
                "comparison_time_s": safe_float(
                    real_time_comparison
                ),
                "comparison_minus_reference_s": safe_float(
                    real_delta
                ),
                "calculated_delta_s": safe_float(
                    calculated_delta
                ),
                "distance_m": safe_float(distance_final),
                "temporal_validation": temporal_validation,
                "objective_analysis": objective_analysis,
                "zone_count": len(zones),
                "loss_count": len(losses),
                "gain_count": len(gains),
                "neutral_count": len(neutrals),
                "zones": top_zones,
            }

            analysis_output["comparisons"].append(
                comparison_output
            )

        # ====================================================
        # VALIDACIÓN GLOBAL
        # ====================================================

        print_header("VALIDACIÓN GLOBAL")

        global_validation = validate_global_output(
            analysis_output
        )

        global_status = (
            "OK"
            if global_validation
            else "WARNING"
        )

        analysis_output["metadata"][
            "temporal_validation_status"
        ] = global_status

        analysis_output["metadata"][
            "objective_analysis_validation"
        ] = global_status

        print(f"Estado global: {global_status}")
        print(
            "Análisis objetivo: "
            f"{global_status}"
        )

        # ====================================================
        # GUARDAR JSON
        # ====================================================

        print_header("GUARDANDO RESULTADO")

        with open(
            OUTPUT_PATH,
            "w",
            encoding="utf-8",
        ) as output_file:
            json.dump(
                analysis_output,
                output_file,
                indent=2,
                ensure_ascii=False,
            )

        print(
            f"Resultado guardado en:\n{OUTPUT_PATH}"
        )

        if VALIDATE_ONLY:
            print_header("VALIDATE RESULT")

            if global_validation:
                print("PASS")
            else:
                print("FAIL")
                raise RuntimeError(
                    "VALIDATION_FAILED"
                )

        print_header("ANALYSIS COMPLETE")

    finally:
        telemetry.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
