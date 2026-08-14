import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone


# ============================================================
# RACE ENGINEER - LLM ANALYSIS v3.8.17
# ============================================================
#
# Diseñado para:
#
#     analyze_telemetry.py v3.8
#
# Arquitectura:
#
# PYTHON (analyze_telemetry.py):
# - determina vueltas válidas
# - determina referencia
# - calcula tiempos
# - calcula deltas
# - reconstruye zonas
# - detecta loss clusters
# - detecta eventos persistentes
# - separa acciones del piloto de propagación de velocidad
# - construye driver_action_episode_ranking
#
# LLM:
# - NO vuelve a detectar zonas
# - NO suma eventos
# - NO interpreta speed_propagation como acción
# - interpreta cada episodio en aislamiento
# - clasifica prioridades en una llamada comparativa separada
#
# Una llamada a Ollama por episodio.
# Una llamada comparativa para clasificar prioridades.
# Una llamada de resumen por comparación.
# Una llamada final para sintetizar la sesión.
#
# ============================================================


# ============================================================
# CONFIGURACIÓN
# ============================================================

OLLAMA_URL = "http://localhost:11434/api/chat"

MODEL_NAME = "ingenierov2"

CONTEXT_SIZE = 8192

TEMPERATURE = 0.15

# El ranker recibe sólo hechos deterministas y usa sampling determinista.
# La interpretación por episodio y las síntesis conservan TEMPERATURE.
RANKER_TEMPERATURE = 0.0
RANKER_SEED = 3811

TIMEOUT_SECONDS = 600

# El ranker es una respuesta pequeña. Si Ollama queda colgado, no esperamos
# diez minutos antes de recuperar el intento. Los reintentos de transporte
# son independientes de MAX_LLM_VALIDATION_ATTEMPTS.
RANKER_TIMEOUT_SECONDS = 240
MAX_OLLAMA_TRANSPORT_ATTEMPTS = 2
OLLAMA_TRANSPORT_RETRY_DELAY_SECONDS = 2

MAX_DRIVER_ACTION_EPISODES = 8

MAX_LEGACY_LOSS_EPISODES = 5

MAX_LOSS_ZONES = 8

MAX_SPEED_PROPAGATIONS_PER_EPISODE = 4

SAVE_COMPARISON_PROMPTS = True

SAVE_GLOBAL_PROMPT = True


# ============================================================
# DIRECTORIO BASE
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


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

    if value != value:
        return None

    if value in (
        float("inf"),
        float("-inf"),
    ):
        return None

    return value


def safe_int(value):
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compact_json(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def format_seconds(value):
    value = safe_float(value)

    if value is None:
        return "N/D"

    return f"{value:.4f} s"


def trim_list(items, limit):
    if not isinstance(items, list):
        return []

    return items[:limit]


# ============================================================
# SELECCIÓN DEL JSON
# ============================================================

def find_json_file():
    """
    Uso:

        python llm_analysis.py "archivo.json"

    Si no se especifica archivo y existe exactamente un JSON
    candidato, lo utiliza automáticamente.
    """

    if len(sys.argv) > 1:

        path = sys.argv[1]

        if not os.path.isabs(path):
            path = os.path.join(
                BASE_DIR,
                path,
            )

        path = os.path.abspath(
            path
        )

        if not os.path.exists(path):
            raise FileNotFoundError(
                f"No existe el JSON:\n{path}"
            )

        if not path.lower().endswith(
            ".json"
        ):
            raise ValueError(
                "El archivo indicado no es un JSON."
            )

        return path

    files = sorted(
        [
            filename
            for filename in os.listdir(BASE_DIR)
            if filename.lower().endswith(".json")
            and not filename.lower().endswith(
                "_llm_analysis.json"
            )
        ]
    )

    if not files:
        raise RuntimeError(
            "No se encontró ningún archivo JSON."
        )

    if len(files) == 1:
        return os.path.join(
            BASE_DIR,
            files[0],
        )

    raise RuntimeError(
        "Hay múltiples archivos JSON.\n\n"
        "Indicá cuál utilizar:\n\n"
        'python llm_analysis.py "archivo.json"\n\n'
        "Archivos disponibles:\n"
        +
        "\n".join(
            f"  {filename}"
            for filename in files
        )
    )


# ============================================================
# CARGAR JSON
# ============================================================

def load_json(path):
    print()
    print("Cargando JSON:")
    print(path)

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(
            "El JSON raíz debe ser un objeto."
        )

    return data


# ============================================================
# MAPA DE TIEMPOS
# ============================================================

def build_lap_time_map(data):
    """
    Obtiene tiempos absolutos desde:

    1. metadata.lap_times_s
    2. laps[].duration
    """

    result = {}

    metadata = data.get(
        "metadata",
        {},
    )

    metadata_times = metadata.get(
        "lap_times_s",
        {},
    )

    if isinstance(
        metadata_times,
        dict,
    ):
        for lap, duration in metadata_times.items():

            lap_id = safe_int(lap)
            duration_s = safe_float(
                duration
            )

            if (
                lap_id is not None
                and
                duration_s is not None
                and
                duration_s > 0
            ):
                result[lap_id] = duration_s

    laps = data.get(
        "laps",
        [],
    )

    if isinstance(
        laps,
        list,
    ):
        for lap_record in laps:

            if not isinstance(
                lap_record,
                dict,
            ):
                continue

            lap_id = safe_int(
                lap_record.get("lap")
            )

            duration_s = safe_float(
                lap_record.get("duration")
            )

            if (
                lap_id is not None
                and
                duration_s is not None
                and
                duration_s > 0
            ):
                result[lap_id] = duration_s

    return result


# ============================================================
# DETECTAR IDENTIDAD DE COMPARACIÓN
# ============================================================

def resolve_comparison_laps(
    comparison,
    metadata,
):
    """
    Compatibilidad con estructuras anteriores:

    v3.8:
        reference_lap
        comparison_lap

    antiguas:
        lap_a
        lap_b
    """

    reference_lap = safe_int(
        comparison.get(
            "reference_lap"
        )
    )

    comparison_lap = safe_int(
        comparison.get(
            "comparison_lap"
        )
    )

    if reference_lap is None:
        reference_lap = safe_int(
            comparison.get(
                "lap_a"
            )
        )

    if comparison_lap is None:
        comparison_lap = safe_int(
            comparison.get(
                "lap_b"
            )
        )

    if reference_lap is None:
        reference_lap = safe_int(
            metadata.get(
                "reference_lap"
            )
        )

    if (
        reference_lap is None
        or
        comparison_lap is None
    ):
        raise ValueError(
            "No fue posible determinar "
            "reference_lap/comparison_lap "
            "de una comparación."
        )

    return (
        reference_lap,
        comparison_lap,
    )


# ============================================================
# VALIDACIÓN DEL MODELO
# ============================================================

def validate_data_model(data):
    print()
    print("Validando modelo de datos...")

    metadata = data.get(
        "metadata"
    )

    if not isinstance(
        metadata,
        dict,
    ):
        raise ValueError(
            "El JSON no contiene metadata válida."
        )

    comparisons = data.get(
        "comparisons"
    )

    if not isinstance(
        comparisons,
        list,
    ):
        raise ValueError(
            "El JSON no contiene comparisons como lista."
        )

    model = metadata.get(
        "lap_comparison_model"
    )

    same_vehicle = metadata.get(
        "same_vehicle"
    )

    if (
        model
        !=
        "same_vehicle_different_laps"
        and
        same_vehicle is not True
    ):
        raise ValueError(
            "El JSON no corresponde al modelo "
            "mismo vehículo / distintas vueltas."
        )

    version = str(
        metadata.get(
            "analysis_version",
            "unknown",
        )
    )

    print(
        "Modelo confirmado:"
    )

    print(
        "mismo vehículo / distintas vueltas"
    )

    print()

    print(
        f"Analyze Telemetry version: "
        f"{version}"
    )

    print(
        f"Vuelta de referencia: "
        f"{metadata.get('reference_lap')}"
    )

    print(
        f"Vueltas válidas: "
        f"{metadata.get('valid_laps', [])}"
    )

    print(
        f"Vueltas descartadas: "
        f"{metadata.get('discarded_laps', [])}"
    )

    print(
        f"Comparaciones disponibles: "
        f"{len(comparisons)}"
    )

    temporal_status = metadata.get(
        "temporal_validation_status"
    )

    objective_status = metadata.get(
        "objective_analysis_validation"
    )

    if temporal_status is not None:
        print(
            f"Validación temporal: "
            f"{temporal_status}"
        )

    if objective_status is not None:
        print(
            f"Validación objetiva: "
            f"{objective_status}"
        )

    return metadata, comparisons


# ============================================================
# VALIDAR TIEMPOS
# ============================================================

def validate_lap_times(
    data,
    metadata,
    comparisons,
):
    print()
    print(
        "Validando tiempos de vuelta..."
    )

    lap_times = build_lap_time_map(
        data
    )

    if not lap_times:
        raise RuntimeError(
            "No se encontraron tiempos "
            "absolutos de vuelta."
        )

    for lap in sorted(
        lap_times
    ):
        print(
            f"  lap {lap}: "
            f"{lap_times[lap]:.4f} s"
        )

    print()

    for comparison in comparisons:

        reference_lap, comparison_lap = (
            resolve_comparison_laps(
                comparison,
                metadata,
            )
        )

        reference_time = safe_float(
            comparison.get(
                "reference_time_s"
            )
        )

        comparison_time = safe_float(
            comparison.get(
                "comparison_time_s"
            )
        )

        real_delta = safe_float(
            comparison.get(
                "comparison_minus_reference_s"
            )
        )

        if reference_time is None:
            reference_time = lap_times.get(
                reference_lap
            )

        if comparison_time is None:
            comparison_time = lap_times.get(
                comparison_lap
            )

        if (
            reference_time is None
            or
            comparison_time is None
        ):
            raise RuntimeError(
                "Tiempo absoluto faltante "
                f"para comparación "
                f"{reference_lap} -> "
                f"{comparison_lap}"
            )

        expected_delta = (
            comparison_time
            -
            reference_time
        )

        if real_delta is None:
            real_delta = expected_delta

        validation_error = (
            real_delta
            -
            expected_delta
        )

        print(
            f"Comparación: "
            f"{reference_lap} -> "
            f"{comparison_lap}"
        )

        print(
            f"  Tiempo A: "
            f"{reference_time}"
        )

        print(
            f"  Tiempo B: "
            f"{comparison_time}"
        )

        print(
            f"  Delta real: "
            f"{real_delta}"
        )

        print(
            f"  Verificación: "
            f"error="
            f"{validation_error:+.6f} s"
        )

        if abs(validation_error) > 0.001:
            raise RuntimeError(
                "LAP_TIME_VALIDATION_FAILED "
                f"{reference_lap} -> "
                f"{comparison_lap}: "
                f"{validation_error:+.6f} s"
            )

    print()
    print(
        "Validación temporal completa."
    )

    return lap_times


# ============================================================
# NORMALIZAR SPEED PROPAGATION
# ============================================================

def compact_speed_propagation(
    propagation,
):
    if not isinstance(
        propagation,
        (list, dict),
    ):
        return propagation

    if isinstance(
        propagation,
        list,
    ):
        return [
            item
            for item in propagation[
                :MAX_SPEED_PROPAGATIONS_PER_EPISODE
            ]
            if isinstance(item, dict)
        ]

    return propagation


# ============================================================
# LIMPIEZA DE DRIVER ACTION EPISODE
# ============================================================

def clean_driver_action_episode(
    episode,
):
    if not isinstance(
        episode,
        dict,
    ):
        return None

    result = {
        "rank":
            safe_int(
                episode.get("rank")
            ),

        "global_rank":
            safe_int(
                episode.get("global_rank")
            ),

        "zone_id":
            safe_int(
                episode.get("zone_id")
            ),

        "parent_zone_rank":
            safe_int(
                episode.get(
                    "parent_zone_rank"
                )
            ),

        "start_distance_m":
            safe_float(
                episode.get(
                    "start_distance_m"
                )
            ),

        "end_distance_m":
            safe_float(
                episode.get(
                    "end_distance_m"
                )
            ),

        "length_m":
            safe_float(
                episode.get(
                    "length_m"
                )
            ),

        "delta_start_s":
            safe_float(
                episode.get(
                    "delta_start_s"
                )
            ),

        "delta_end_s":
            safe_float(
                episode.get(
                    "delta_end_s"
                )
            ),

        "action_time_loss_s":
            safe_float(
                episode.get(
                    "action_time_loss_s"
                )
            ),

        "parent_zone_delta_loss_s":
            safe_float(
                episode.get(
                    "parent_zone_delta_loss_s"
                )
            ),

        "parent_zone_net_loss_equivalent_percent":
            safe_float(
                episode.get(
                    "parent_zone_net_loss_equivalent_percent"
                )
            ),

        "evidence_strength":
            episode.get(
                "evidence_strength"
            ),

        "action_channel_count":
            safe_int(
                episode.get(
                    "action_channel_count"
                )
            ),

        "action_channels":
            episode.get(
                "action_channels",
                [],
            ),

        "action_evidence_by_channel":
            episode.get(
                "action_evidence_by_channel",
                {},
            ),

        "concurrent_speed_events":
            episode.get(
                "concurrent_speed_events",
                [],
            ),

        "speed_propagation":
            compact_speed_propagation(
                episode.get(
                    "speed_propagation"
                )
            ),

        "supporting_loss_clusters":
            episode.get(
                "supporting_loss_clusters",
                [],
            ),

        "interpretation":
            episode.get(
                "interpretation",
                {
                    "primary_unit":
                        "driver_action_episode",

                    "causal_claim":
                        False,

                    "speed_is_not_used_to_merge_actions":
                        True,

                    "speed_propagation_is_consequence_candidate":
                        True,

                    "action_time_is_computed_once_from_time_delta":
                        True,
                },
            ),
    }

    # Seguridad semántica:
    # speed nunca debe aparecer como action_channel.

    action_channels = result.get(
        "action_channels"
    )

    if isinstance(
        action_channels,
        list,
    ):
        result[
            "action_channels"
        ] = [
            channel
            for channel in action_channels
            if channel != "speed"
        ]

    return result


# ============================================================
# LEGACY LOSS EPISODE
# ============================================================

def clean_legacy_loss_episode(
    episode,
):
    if not isinstance(
        episode,
        dict,
    ):
        return None

    return {
        "rank":
            safe_int(
                episode.get("rank")
            ),

        "global_rank":
            safe_int(
                episode.get(
                    "global_rank"
                )
            ),

        "zone_id":
            safe_int(
                episode.get(
                    "zone_id"
                )
            ),

        "start_distance_m":
            safe_float(
                episode.get(
                    "start_distance_m"
                )
            ),

        "end_distance_m":
            safe_float(
                episode.get(
                    "end_distance_m"
                )
            ),

        "length_m":
            safe_float(
                episode.get(
                    "length_m"
                )
            ),

        "episode_time_loss_s":
            safe_float(
                episode.get(
                    "episode_time_loss_s"
                )
            ),

        "evidence_strength":
            episode.get(
                "evidence_strength"
            ),

        "evidence_channels":
            episode.get(
                "evidence_channels",
                [],
            ),

        "evidence_by_channel":
            episode.get(
                "evidence_by_channel",
                {},
            ),
    }


# ============================================================
# EXTRAER OBJECTIVE ANALYSIS
# ============================================================

def extract_objective_analysis(
    comparison,
):
    objective = comparison.get(
        "objective_analysis",
        {},
    )

    if not isinstance(
        objective,
        dict,
    ):
        objective = {}

    driver_action_episodes = (
        objective.get(
            "driver_action_episode_ranking"
        )
    )

    if not isinstance(
        driver_action_episodes,
        list,
    ):
        driver_action_episodes = (
            comparison.get(
                "driver_action_episode_ranking",
                [],
            )
        )

    cleaned_driver_episodes = []

    for episode in trim_list(
        driver_action_episodes,
        MAX_DRIVER_ACTION_EPISODES,
    ):
        cleaned = (
            clean_driver_action_episode(
                episode
            )
        )

        if cleaned is not None:
            cleaned_driver_episodes.append(
                cleaned
            )

    legacy_episodes = objective.get(
        "loss_episode_ranking",
        comparison.get(
            "loss_episode_ranking",
            [],
        ),
    )

    cleaned_legacy = []

    for episode in trim_list(
        legacy_episodes,
        MAX_LEGACY_LOSS_EPISODES,
    ):
        cleaned = clean_legacy_loss_episode(
            episode
        )

        if cleaned is not None:
            cleaned_legacy.append(
                cleaned
            )

    loss_ranking = objective.get(
        "loss_ranking",
        comparison.get(
            "loss_ranking",
            [],
        ),
    )

    if not isinstance(
        loss_ranking,
        list,
    ):
        loss_ranking = []

    summary = objective.get(
        "summary",
        {},
    )

    if not isinstance(
        summary,
        dict,
    ):
        summary = {}

    return {
        "priority":
            objective.get(
                "priority",
                "time_loss",
            ),

        "driver_action_episode_ranking":
            cleaned_driver_episodes,

        "legacy_loss_episode_ranking":
            cleaned_legacy,

        "loss_ranking":
            trim_list(
                loss_ranking,
                MAX_LOSS_ZONES,
            ),

        "loss_cluster_ranking":
            objective.get(
                "loss_cluster_ranking",
                [],
            ),

        "summary":
            summary,
    }


# ============================================================
# CONSTRUIR DATASET DE COMPARACIÓN
# ============================================================

def clean_comparison(
    comparison,
    metadata,
    lap_times,
):
    if not isinstance(
        comparison,
        dict,
    ):
        raise ValueError(
            "Comparación inválida."
        )

    reference_lap, comparison_lap = (
        resolve_comparison_laps(
            comparison,
            metadata,
        )
    )

    reference_time = safe_float(
        comparison.get(
            "reference_time_s"
        )
    )

    comparison_time = safe_float(
        comparison.get(
            "comparison_time_s"
        )
    )

    if reference_time is None:
        reference_time = lap_times.get(
            reference_lap
        )

    if comparison_time is None:
        comparison_time = lap_times.get(
            comparison_lap
        )

    if (
        reference_time is None
        or
        comparison_time is None
    ):
        raise ValueError(
            "Comparación sin tiempos "
            f"{reference_lap} -> "
            f"{comparison_lap}."
        )

    real_delta = safe_float(
        comparison.get(
            "comparison_minus_reference_s"
        )
    )

    if real_delta is None:
        real_delta = (
            comparison_time
            -
            reference_time
        )

    objective = extract_objective_analysis(
        comparison
    )

    driver_episodes = objective[
        "driver_action_episode_ranking"
    ]

    # Compatibilidad:
    # si falta v3.8, podremos analizar legacy episodes,
    # pero lo señalamos explícitamente.

    analysis_mode = (
        "driver_action_episode_v3_8"
        if driver_episodes
        else
        "legacy_loss_episode_fallback"
    )

    return {
        "same_vehicle":
            comparison.get(
                "same_vehicle",
                True,
            ),

        "reference_lap":
            reference_lap,

        "comparison_lap":
            comparison_lap,

        "reference_time_s":
            reference_time,

        "comparison_time_s":
            comparison_time,

        "comparison_minus_reference_s":
            real_delta,

        "calculated_delta_s":
            safe_float(
                comparison.get(
                    "calculated_delta_s"
                )
            ),

        "distance_m":
            safe_float(
                comparison.get(
                    "distance_m"
                )
            ),

        "temporal_validation":
            comparison.get(
                "temporal_validation",
                {},
            ),

        "driver_analysis_priority":
            comparison.get(
                "driver_analysis_priority"
            ),

        "driver_analysis_priority_rank":
            safe_int(
                comparison.get(
                    "driver_analysis_priority_rank"
                )
            ),

        "analysis_mode":
            analysis_mode,

        "objective_analysis":
            objective,
    }


# ============================================================
# DATASET PARA LLM
# ============================================================

def build_llm_dataset(
    data,
    lap_times,
):
    metadata = data[
        "metadata"
    ]

    raw_comparisons = data[
        "comparisons"
    ]

    comparisons = []

    for raw_comparison in raw_comparisons:

        comparisons.append(
            clean_comparison(
                raw_comparison,
                metadata,
                lap_times,
            )
        )

    # Si Python ya definió prioridad de análisis,
    # la respetamos. No la recalcula el LLM.

    def comparison_sort_key(item):
        priority_rank = (
            item.get(
                "driver_analysis_priority_rank"
            )
        )

        if priority_rank is None:
            priority_rank = 999999

        delta = abs(
            item.get(
                "comparison_minus_reference_s"
            )
            or 0.0
        )

        return (
            priority_rank,
            delta,
        )

    comparisons = sorted(
        comparisons,
        key=comparison_sort_key,
    )

    return {
        "metadata": {
            "analysis_version":
                metadata.get(
                    "analysis_version"
                ),

            "track":
                metadata.get(
                    "track"
                ),

            "session_type":
                metadata.get(
                    "session_type"
                ),

            "timestamp_utc":
                metadata.get(
                    "timestamp_utc"
                ),

            "same_vehicle":
                metadata.get(
                    "same_vehicle",
                    True,
                ),

            "lap_comparison_model":
                metadata.get(
                    "lap_comparison_model"
                ),

            "reference_lap":
                safe_int(
                    metadata.get(
                        "reference_lap"
                    )
                ),

            "valid_laps":
                metadata.get(
                    "valid_laps",
                    [],
                ),

            "discarded_laps":
                metadata.get(
                    "discarded_laps",
                    [],
                ),

            "reference_distance_m":
                safe_float(
                    metadata.get(
                        "reference_distance_m"
                    )
                ),

            "temporal_validation_status":
                metadata.get(
                    "temporal_validation_status"
                ),

            "objective_analysis_validation":
                metadata.get(
                    "objective_analysis_validation"
                ),

            "lap_times_s": {
                str(lap):
                    safe_float(duration)
                for lap, duration
                in lap_times.items()
            },
        },

        "comparisons":
            comparisons,
    }


# ============================================================
# OLLAMA
# ============================================================

def ollama_chat(
    system_prompt,
    user_prompt,
    temperature=None,
    seed=None,
    timeout_seconds=None,
    transport_attempts=None,
    format_schema=None,
):
    payload = {
        "model":
            MODEL_NAME,

        "messages": [
            {
                "role":
                    "system",

                "content":
                    system_prompt,
            },
            {
                "role":
                    "user",

                "content":
                    user_prompt,
            },
        ],

        "stream":
            False,

        "format":
            format_schema if format_schema is not None else "json",

        "options": {
            "temperature":
                TEMPERATURE if temperature is None else temperature,

            "num_ctx":
                CONTEXT_SIZE,
        },
    }

    if seed is not None:
        payload["options"]["seed"] = int(seed)

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    effective_timeout = (
        TIMEOUT_SECONDS
        if timeout_seconds is None
        else float(timeout_seconds)
    )
    max_transport_attempts = (
        MAX_OLLAMA_TRANSPORT_ATTEMPTS
        if transport_attempts is None
        else max(1, int(transport_attempts))
    )

    raw = None
    last_transport_error = None

    for transport_attempt in range(1, max_transport_attempts + 1):
        try:
            with urllib.request.urlopen(
                request,
                timeout=effective_timeout,
            ) as response:
                raw = response.read()
            last_transport_error = None
            break

        except (TimeoutError, urllib.error.URLError) as exc:
            last_transport_error = exc

            if transport_attempt < max_transport_attempts:
                print(
                    "    Ollama: fallo de transporte "
                    f"(intento {transport_attempt}/"
                    f"{max_transport_attempts}): {type(exc).__name__}. "
                    "Reintentando la misma solicitud..."
                )
                time.sleep(OLLAMA_TRANSPORT_RETRY_DELAY_SECONDS)
                continue

            if isinstance(exc, TimeoutError):
                raise RuntimeError(
                    "OLLAMA_TRANSPORT_TIMEOUT. "
                    "Ollama no respondió dentro del tiempo límite "
                    f"tras {max_transport_attempts} intento(s).\n"
                    f"URL: {OLLAMA_URL}\n"
                    f"Timeout por intento: {effective_timeout:g} s"
                ) from exc

            raise RuntimeError(
                "No se pudo conectar con Ollama tras "
                f"{max_transport_attempts} intento(s).\n"
                f"URL: {OLLAMA_URL}\n"
                f"Error: {exc}"
            ) from exc

    if raw is None:
        raise RuntimeError(
            "OLLAMA_TRANSPORT_FAILED sin respuesta utilizable. "
            f"Último error: {last_transport_error}"
        )

    try:

        result = json.loads(
            raw.decode(
                "utf-8"
            )
        )

    except json.JSONDecodeError:

        raise RuntimeError(
            "Ollama devolvió una respuesta "
            "que no es JSON válido."
        )

    message = result.get(
        "message"
    )

    if not isinstance(
        message,
        dict,
    ):
        raise RuntimeError(
            "La respuesta de Ollama "
            "no contiene message."
        )

    content = message.get(
        "content"
    )

    if not content:
        raise RuntimeError(
            "Ollama no devolvió contenido."
        )

    return content



# ============================================================
# SYSTEM PROMPT v3.8.17
# ============================================================

SYSTEM_PROMPT = """
Sos un ingeniero de carrera especializado en telemetría
de simuladores.

Python ya calculó y validó TODOS los datos objetivos.

Tu tarea es EXCLUSIVAMENTE cualitativa:

- clasificar episodios;
- describir relaciones observables entre canales autorizados;
- formular hipótesis prudentes limitadas a la conducción observable;
- proponer recomendaciones concretas de conducción.

============================================================
REGLA CRÍTICA: NO ESCRIBAS NÚMEROS
============================================================

NO escribas cifras en ningún texto cualitativo.

No escribas:

- tiempos;
- distancias;
- porcentajes;
- velocidades;
- RPM;
- números de vuelta;
- números de episodio dentro del texto libre.

Los únicos números permitidos en tu respuesta son los valores
enteros del campo JSON "episode_id", porque Python los necesita
para relacionar tu interpretación con los episodios.

Python insertará posteriormente todos los valores numéricos
reales en el informe final.

============================================================
AUTORIDAD
============================================================

Python es la única fuente autoritativa para:

- tiempos de vuelta;
- delta total;
- límites espaciales;
- pérdidas temporales;
- ranking;
- canales;
- propagación de velocidad;
- telemetría.

NO recalcules nada.
NO reordenes episodios.
NO sumes pérdidas.
NO reconstruyas zonas.

============================================================
GROUNDING FACTUAL OBLIGATORIO
============================================================

Para CADA episodio, "action_channels" es una WHITELIST
semántica de acciones observables.

Si "brake" NO está en action_channels:
- no menciones freno, frenado, frenada ni acción de frenar.

Si "throttle" NO está en action_channels:
- no menciones acelerador, aceleración ni modulación de gas.

Si "steering_magnitude" NO está en action_channels:
- no menciones volante, dirección, giro ni corrección de
  trayectoria.

La velocidad sólo puede mencionarse si el episodio contiene
"concurrent_speed_events" o "speed_propagation".

La velocidad es contexto o posible consecuencia; NO es una
acción del piloto.

No inventes variables ni causas que Python no suministró.
Quedan fuera del dominio permitido, entre otras:

- obstáculos o incidentes visuales;
- cámaras o imágenes;
- topografía, pendientes, baches o irregularidades de pista;
- adherencia, humedad o clima;
- presión o estado de neumáticos;
- vibraciones o averías mecánicas;
- motor, potencia, transmisión o propulsión;
- aerodinámica o gestión de energía;
- combustible o temperaturas;
- carga o daño del vehículo.

No recomiendes inspeccionar datos que no existen en el payload.

Si la causa no puede determinarse con los canales disponibles,
decilo explícitamente de forma cualitativa.

Las recomendaciones deben centrarse en acciones observables del
piloto que sí estén autorizadas para el episodio: modulación de
freno, acelerador o dirección según corresponda.

============================================================
DRIVER ACTION EPISODE
============================================================

La unidad primaria es driver_action_episode.

Se construye a partir de diferencias persistentes de:

- throttle;
- brake;
- steering_magnitude.

La velocidad NO crea ni une episodios de acción.

speed_propagation puede representar la persistencia de una
diferencia de velocidad después de una acción.

NO la conviertas automáticamente en:

- una nueva acción;
- un nuevo error;
- una nueva causa.

============================================================
CAUSALIDAD
============================================================

action_time_loss_s indica cuánto cambió el delta mientras
estuvo presente una diferencia de acción.

NO demuestra que esa acción haya causado exactamente
esa pérdida.

Preferí:

- "coincide con";
- "ocurre mientras";
- "es compatible con";
- "podría contribuir";
- "causalidad no confirmada".

Evitá afirmar:

- "causó";
- "provocó";
- "se debe a";
- "generó";

como hechos.

============================================================
ETIQUETAS DE CONDUCCIÓN
============================================================

No conviertas automáticamente diferencias de canales en:

- frenada tardía;
- frenada temprana;
- frenado insuficiente;
- frenado excesivo;
- aceleración prematura;
- mala salida;
- mala trayectoria;
- inestabilidad;
- subviraje;
- sobreviraje.

No afirmes una trayectoria óptima, línea ideal, ápice o vértice
si Python no proporciona geometría de trayectoria.

Describí primero la relación objetiva y después, si corresponde,
formulá una hipótesis prudente limitada a los canales presentes.

============================================================
CLASIFICACIÓN OBLIGATORIA
============================================================

Debés devolver EXACTAMENTE un objeto por cada episode_id
recibido.

Clasificaciones permitidas:

- PRIORITARIO
- SECUNDARIO
- NO_ACCIONABLE

Usá la clasificación de forma relativa y coherente con la evidencia
que entrega Python. El ranking de Python, action_time_loss_s y
evidence_strength pueden orientar la prioridad, pero NO inventes
thresholds ni alternes etiquetas mecánicamente.

NO_ACCIONABLE debe reservarse para episodios donde la evidencia
observable no permita formular una recomendación de conducción útil,
no simplemente para completar un patrón de etiquetas.

No omitas episodios.
No agregues episodios.
No dupliques episode_id.

============================================================
SALIDA
============================================================

Respondé ÚNICAMENTE con JSON válido.

No Markdown.
No bloques de código.
No texto antes o después del JSON.

Todos los textos libres deben estar en español y NO deben
contener cifras.
"""


# ============================================================
# CONSTANTES DE VALIDACIÓN ESTRUCTURADA
# ============================================================

ALLOWED_CLASSIFICATIONS = {
    "PRIORITARIO",
    "SECUNDARIO",
    "NO_ACCIONABLE",
}

MAX_LLM_VALIDATION_ATTEMPTS = 2


# ============================================================
# PREPARAR CATÁLOGO DE EPISODIOS
# ============================================================

def build_episode_catalog(comparison):
    """
    Crea IDs secuenciales deterministas para el contrato LLM.

    El LLM nunca decide IDs ni ranking.
    """

    episodes = (
        comparison[
            "objective_analysis"
        ][
            "driver_action_episode_ranking"
        ]
    )

    catalog = []

    for episode_id, episode in enumerate(
        episodes,
        start=1,
    ):
        record = dict(episode)

        record["episode_id"] = episode_id

        catalog.append(record)

    return catalog


def compact_action_event_for_llm(event):
    """
    Reduce un evento de acción a evidencia del canal que realmente
    creó el episodio. Deliberadamente elimina snapshot_at_peak,
    porque ese snapshot contiene canales contextuales no autorizados
    y puede inducir al LLM a inventar acciones ausentes.
    """

    if not isinstance(event, dict):
        return {}

    return {
        "type": event.get("type"),
        "direction": event.get("direction"),
        "start_distance_m": event.get("start_distance_m"),
        "end_distance_m": event.get("end_distance_m"),
        "length_m": event.get("length_m"),
        "mean_difference": event.get("mean_difference"),
        "peak_difference": event.get("peak_difference"),
        "time_delta_change_during_event_s": event.get(
            "time_delta_change_during_event_s"
        ),
        "persistent": event.get("persistent"),
    }


def compact_action_evidence_for_llm(episode):
    allowed_channels = set(
        episode.get("action_channels", []) or []
    )

    source = episode.get(
        "action_evidence_by_channel",
        {},
    )

    if not isinstance(source, dict):
        return {}

    result = {}

    for channel in sorted(allowed_channels):
        evidence = source.get(channel)

        if not isinstance(evidence, dict):
            continue

        result[channel] = {
            "event_count": evidence.get("event_count"),
            "supported_length_m": evidence.get("supported_length_m"),
            "mean_of_event_mean_differences": evidence.get(
                "mean_of_event_mean_differences"
            ),
            "largest_abs_peak_difference": evidence.get(
                "largest_abs_peak_difference"
            ),
            "events": [
                compact_action_event_for_llm(event)
                for event in (
                    evidence.get("events", []) or []
                )
                if isinstance(event, dict)
            ],
        }

    return result


def compact_speed_event_for_llm(event):
    """
    Conserva sólo evidencia explícita de velocidad. No incluye
    snapshots con freno/acelerador/dirección para evitar leakage
    semántico de canales no autorizados.
    """

    if not isinstance(event, dict):
        return {}

    return {
        "type": event.get("type"),
        "direction": event.get("direction"),
        "start_distance_m": event.get("start_distance_m"),
        "end_distance_m": event.get("end_distance_m"),
        "length_m": event.get("length_m"),
        "mean_difference": event.get("mean_difference"),
        "peak_difference": event.get("peak_difference"),
        "time_delta_change_during_event_s": event.get(
            "time_delta_change_during_event_s"
        ),
        "persistent": event.get("persistent"),
    }


def compact_speed_context_for_llm(episode):
    concurrent = episode.get(
        "concurrent_speed_events",
        [],
    ) or []

    propagation = episode.get(
        "speed_propagation"
    )

    context = {}

    compact_concurrent = [
        compact_speed_event_for_llm(event)
        for event in concurrent
        if isinstance(event, dict)
    ]

    if compact_concurrent:
        context["concurrent_speed_events"] = (
            compact_concurrent
        )

    if propagation:
        if isinstance(propagation, list):
            compact_propagation = []

            for item in propagation:
                if not isinstance(item, dict):
                    continue

                record = {
                    "start_distance_m": item.get("start_distance_m"),
                    "end_distance_m": item.get("end_distance_m"),
                    "length_m": item.get("length_m"),
                    "time_delta_change_s": item.get("time_delta_change_s"),
                    "status": item.get("status"),
                }

                speed_event = compact_speed_event_for_llm(
                    item.get("speed_event")
                )

                if speed_event:
                    record["speed_event"] = speed_event

                compact_propagation.append(record)

            if compact_propagation:
                context["speed_propagation"] = (
                    compact_propagation
                )

        elif isinstance(propagation, dict):
            record = {
                "start_distance_m": propagation.get("start_distance_m"),
                "end_distance_m": propagation.get("end_distance_m"),
                "length_m": propagation.get("length_m"),
                "time_delta_change_s": propagation.get("time_delta_change_s"),
                "status": propagation.get("status"),
            }

            speed_event = compact_speed_event_for_llm(
                propagation.get("speed_event")
            )

            if speed_event:
                record["speed_event"] = speed_event

            context["speed_propagation"] = record

    return context


def allowed_action_language_for_llm(channels):
    names = {
        "brake": "freno",
        "throttle": "acelerador",
        "steering_magnitude": "dirección/volante",
    }

    return [
        names[channel]
        for channel in channels
        if channel in names
    ]


def compact_episode_for_llm(episode):
    """
    Payload estrictamente saneado para el LLM.

    Regla clave v3.8.17:
    - sólo expone evidencia de action_channels autorizados;
    - no expone snapshots multicanal;
    - sólo expone velocidad si realmente existe contexto de velocidad;
    - conserva números para clasificación relativa, pero Python sigue
      siendo la única autoridad que los renderiza al usuario.
    """

    action_channels = list(
        episode.get("action_channels", []) or []
    )

    result = {
        "episode_id": episode["episode_id"],
        "python_rank": (
            episode.get("global_rank")
            or episode.get("rank")
            or episode["episode_id"]
        ),
        "start_distance_m": episode.get("start_distance_m"),
        "end_distance_m": episode.get("end_distance_m"),
        "length_m": episode.get("length_m"),
        "action_time_loss_s": episode.get("action_time_loss_s"),
        "evidence_strength": episode.get("evidence_strength"),
        "action_channels": action_channels,
        "allowed_action_language": (
            allowed_action_language_for_llm(
                action_channels
            )
        ),
        "action_evidence_by_channel": (
            compact_action_evidence_for_llm(
                episode
            )
        ),
        "supporting_loss_clusters": [
            {
                "cluster_rank": item.get("cluster_rank"),
                "cluster_delta_loss_s": item.get("cluster_delta_loss_s"),
                "overlap_m": item.get("overlap_m"),
            }
            for item in (
                episode.get("supporting_loss_clusters", []) or []
            )
            if isinstance(item, dict)
        ],
    }

    speed_context = compact_speed_context_for_llm(
        episode
    )

    if speed_context:
        result["speed_context"] = speed_context

    return result


# ============================================================
# PROMPT DE COMPARACIÓN v3.8.17
# ============================================================

def build_comparison_prompt(
    metadata,
    comparison,
    episode_catalog,
    correction_errors=None,
):
    ground_truth = {
        "reference_lap":
            comparison[
                "reference_lap"
            ],

        "comparison_lap":
            comparison[
                "comparison_lap"
            ],

        "reference_time_s":
            comparison[
                "reference_time_s"
            ],

        "comparison_time_s":
            comparison[
                "comparison_time_s"
            ],

        "total_lap_delta_s":
            comparison[
                "comparison_minus_reference_s"
            ],

        "comparison_distance_m":
            comparison.get(
                "distance_m"
            ),
    }

    episodes_for_llm = [
        compact_episode_for_llm(
            episode
        )
        for episode in episode_catalog
    ]

    schema_example = {
        "episode_assessments": [
            {
                "episode_id": 1,
                "classification": "PRIORITARIO",
                "interpretation": "texto cualitativo sin cifras",
                "hypotheses": [
                    "hipótesis prudente sin cifras"
                ],
                "recommendation": "recomendación concreta sin cifras",
            }
        ],
        "comparison_observations": [
            "observación cualitativa sin cifras"
        ],
        "limitations": [
            "limitación sin cifras"
        ],
        "conclusion":
            "conclusión cualitativa sin cifras",
    }

    correction_block = ""

    if correction_errors:
        correction_block = f"""
============================================================
TU RESPUESTA ANTERIOR FUE RECHAZADA
============================================================

Errores detectados por Python:

{compact_json(correction_errors)}

Corregí EXCLUSIVAMENTE esos errores.

Recordatorio:
- deben estar TODOS los episode_id;
- no puede haber IDs repetidos;
- sólo clasificaciones permitidas;
- ningún texto libre puede contener cifras;
- action_channels es whitelist por episodio;
- allowed_action_language enumera el vocabulario de acción permitido;
- no menciones un canal ausente aunque aparezca en conocimiento general;
- sólo hablá de velocidad si existe speed_context en ESE episodio;
- hypotheses SIEMPRE es lista de strings;
- comparison_observations SIEMPRE es lista de strings;
- limitations SIEMPRE es lista de strings;
- si no hay contenido para una lista, devolvé [];
- no inventes causas mecánicas, ambientales ni visuales;
- no recomiendes revisar datos que no fueron suministrados;
- reconstruí el objeto JSON completo y válido, no devuelvas un parche parcial.
"""

    return f"""
Analizá una comparación del mismo vehículo.

CIRCUITO:
{metadata.get("track")}

SESIÓN:
{metadata.get("session_type")}

============================================================
GROUND_TRUTH - SOLO PYTHON LO USA EN EL INFORME
============================================================

{compact_json(ground_truth)}

NO copies estos números en tus textos.

============================================================
EPISODIOS OBJETIVOS
============================================================

Cantidad exacta de episodios:
{len(episode_catalog)}

{compact_json(episodes_for_llm)}

El payload anterior ya fue saneado por Python.
No infieras canales que no aparecen en action_channels.
Si no existe speed_context en un episodio, no hables de velocidad.

============================================================
CONTRATO JSON OBLIGATORIO
============================================================

Tu respuesta debe tener exactamente estas claves raíz:

- episode_assessments
- comparison_observations
- limitations
- conclusion

episode_assessments debe contener EXACTAMENTE
{len(episode_catalog)} objetos.

Cada objeto debe contener:

- episode_id
- classification
- interpretation
- hypotheses
- recommendation

classification debe ser exactamente una de:

PRIORITARIO
SECUNDARIO
NO_ACCIONABLE

Los episode_id válidos son:

{[episode["episode_id"] for episode in episode_catalog]}

No agregues otros IDs.

No omitas IDs.

No escribas cifras dentro de interpretation, hypotheses,
recommendation, comparison_observations, limitations o conclusion.

TIPOS JSON OBLIGATORIOS:
- episode_assessments: lista de objetos;
- hypotheses: lista de strings en CADA episodio;
- comparison_observations: lista de strings, aunque esté vacía;
- limitations: lista de strings, aunque esté vacía;
- interpretation: string;
- recommendation: string;
- conclusion: string.

NUNCA reemplaces una lista por un string, null u objeto.

GROUNDING OBLIGATORIO:
- action_channels es una whitelist SEMÁNTICA para cada episodio;
- si un canal no está en action_channels, no lo menciones en los
  textos de ese episodio;
- sólo menciones velocidad cuando el episodio tenga la clave
  speed_context;
- no inventes causas mecánicas, ambientales, visuales o de pista;
- no menciones neumáticos, motor, potencia, obstáculos, cámara,
  topografía, adherencia, clima, vibraciones, averías, aerodinámica,
  energía, combustible, temperaturas, carga o daño del vehículo;
- no afirmes trayectoria óptima, línea ideal, ápice o vértice;
- si no alcanza la evidencia, indicá que la causa no puede
  determinarse con los canales disponibles;
- recomendaciones: sólo sobre acciones de conducción observables
  presentes en action_channels.

Ejemplo de FORMA, no de contenido:

{compact_json(schema_example)}

{correction_block}

Respondé únicamente con JSON válido.
"""


# ============================================================
# PARSEAR JSON DEL LLM
# ============================================================

def parse_llm_json(raw_content):
    if not isinstance(
        raw_content,
        str,
    ):
        raise ValueError(
            "La respuesta del LLM no es texto."
        )

    text = raw_content.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip().startswith(
            "```"
        ):
            lines = lines[:-1]

        text = "\n".join(
            lines
        ).strip()

    try:
        result = json.loads(
            text
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "LLM_JSON_INVALID: "
            f"{exc}"
        )

    if not isinstance(
        result,
        dict,
    ):
        raise ValueError(
            "LLM_JSON_ROOT_NOT_OBJECT"
        )

    return result


# ============================================================
# GROUNDING FACTUAL v3.8.17
# ============================================================

# El validador no intenta "entender" semántica libre.
# Aplica guardrails deterministas y conservadores para impedir
# que el LLM introduzca canales o dominios que Python no entregó.

CHANNEL_LANGUAGE_PATTERNS = {
    "brake": (
        r"\bfren",
        r"\bbrake\b",
    ),
    "throttle": (
        r"\baceler",
        r"\bthrottle\b",
        r"\bmodulacion de gas\b",
        r"\bpedal de gas\b",
    ),
    "steering_magnitude": (
        r"\bdireccion\b",
        r"\bvolante\b",
        r"\bgiro\b",
        r"\btrayector",
        r"\bsteering\b",
    ),
}

SPEED_LANGUAGE_PATTERNS = (
    r"\bvelocidad\b",
    r"\brapidez\b",
    r"\bspeed\b",
)

# Dominios que no existen como evidencia causal en el payload
# de driver_action_episode. Se rechazan incluso cuando aparecen
# como "hipótesis", porque el objetivo es coaching grounded y no
# brainstorming mecánico/ambiental.
FORBIDDEN_EXTERNAL_GROUNDING_PATTERNS = (
    (r"\bobstacul", "obstáculos"),
    (r"\bcamara\b|\bimagenes?\b|\bvideo\b", "cámara/imágenes"),
    (r"\btopograf", "topografía"),
    (r"\bpendient", "pendiente"),
    (r"\bbache", "baches"),
    (r"\birregularidad", "irregularidades de pista"),
    (r"\bsuperficie de (?:la )?pista\b", "superficie de pista"),
    (r"\badheren", "adherencia"),
    (r"\bhumedad\b|\bclima\b|\bmeteorolog", "clima/humedad"),
    (r"\bneumatic", "neumáticos"),
    (r"\bpresion (?:de|del|en) (?:los? )?neumatic", "presión de neumáticos"),
    (r"\bvibracion", "vibraciones"),
    (r"\baveria|\bfallo mecanic|\bproblema mecanic", "avería mecánica"),
    (r"\bmotor\b", "motor"),
    (r"\bpotencia\b", "potencia"),
    (r"\btransmision\b", "transmisión"),
    (r"\bpropulsion\b", "propulsión"),
    (r"\baerodinam", "aerodinámica"),
    (r"\bgestion de energia\b|\benergia\b", "gestión de energía"),
    (r"\bcombustible\b", "combustible"),
    (r"\btemperatura", "temperatura"),
    (r"\bcarga del vehiculo\b", "carga del vehículo"),
    (r"\bdano del vehiculo\b|\bdanos del vehiculo\b", "daño del vehículo"),
    (r"\btrayectoria optima\b|\blinea ideal\b|\blinea de carrera\b", "línea/ trayectoria óptima"),
    (r"\bapice\b|\bvertice\b", "ápice/vértice no observado"),
)

# Lenguaje causal asertivo prohibido. Python observa coexistencia temporal,
# cambios de delta y propagación; no prueba causalidad física exacta.
FORBIDDEN_ASSERTIVE_CAUSAL_PATTERNS = (
    (r"\bcauso\b|\bcausar\b|\bcausad[oa]s?\b|\bcausan\b|\bcausa (?=(?:un|una|el|la|perdida|reduccion|aumento|cambio|diferencia|velocidad|tiempo))", "causalidad afirmada"),
    (r"\bprovoc(?:o|a|ar|ado|ada|an)\b", "causalidad afirmada"),
    (r"\bgener(?:o|a|ar|ado|ada|an)\b", "causalidad afirmada"),
    (r"\bproduj(?:o|eron)\b|\bproduce\b|\bproduc(?:ir|ido|ida)\b", "causalidad afirmada"),
    (r"\bocasion(?:o|a|ar|ado|ada)\b", "causalidad afirmada"),
    (r"\bderiv(?:o|a|ar) en\b", "causalidad afirmada"),
    (r"\bdio lugar a\b", "causalidad afirmada"),
    (r"\bresult(?:o|a) en\b", "causalidad afirmada"),
    (r"\bcomo consecuencia directa\b", "consecuencia directa no demostrada"),
    (r"\bse debe a\b|\bdebido a\b", "atribución causal no demostrada"),
)



def normalize_grounding_text(value):
    if not isinstance(value, str):
        return ""

    normalized = unicodedata.normalize(
        "NFKD",
        value.lower(),
    )

    return "".join(
        char
        for char in normalized
        if not unicodedata.combining(char)
    )


def episode_has_speed_context(episode):
    concurrent = episode.get(
        "concurrent_speed_events"
    )
    propagation = episode.get(
        "speed_propagation"
    )

    return bool(concurrent) or bool(propagation)


def grounding_context_from_episodes(episodes):
    channels = set()
    speed_context = False

    for episode in episodes:
        if not isinstance(episode, dict):
            continue

        for channel in episode.get(
            "action_channels",
            [],
        ) or []:
            if isinstance(channel, str):
                channels.add(channel)

        if episode_has_speed_context(
            episode
        ):
            speed_context = True

    return channels, speed_context


def validate_grounded_text(
    value,
    field_name,
    allowed_action_channels,
    speed_context_available,
    errors,
):
    if not isinstance(value, str):
        return

    normalized = normalize_grounding_text(
        value
    )

    for pattern, label in (
        FORBIDDEN_EXTERNAL_GROUNDING_PATTERNS
    ):
        if re.search(
            pattern,
            normalized,
        ):
            errors.append(
                f"{field_name}: menciona dominio no observado "
                f"({label})."
            )

    for pattern, label in FORBIDDEN_ASSERTIVE_CAUSAL_PATTERNS:
        if re.search(pattern, normalized):
            errors.append(
                f"{field_name}: usa lenguaje causal asertivo "
                f"({label})."
            )

    for channel, patterns in (
        CHANNEL_LANGUAGE_PATTERNS.items()
    ):
        mentions_channel = any(
            re.search(
                pattern,
                normalized,
            )
            is not None
            for pattern in patterns
        )

        if (
            mentions_channel
            and
            channel not in allowed_action_channels
        ):
            errors.append(
                f"{field_name}: menciona {channel} pero ese "
                "canal no está autorizado por action_channels."
            )

    mentions_speed = any(
        re.search(
            pattern,
            normalized,
        )
        is not None
        for pattern in SPEED_LANGUAGE_PATTERNS
    )

    if (
        mentions_speed
        and
        not speed_context_available
    ):
        errors.append(
            f"{field_name}: menciona velocidad sin "
            "speed_context autorizado por Python."
        )


def validate_grounded_text_list(
    value,
    field_name,
    allowed_action_channels,
    speed_context_available,
    errors,
):
    if not isinstance(value, list):
        return

    for index, item in enumerate(value):
        if not isinstance(item, str):
            continue

        validate_grounded_text(
            item,
            f"{field_name}[{index}]",
            allowed_action_channels,
            speed_context_available,
            errors,
        )


# ============================================================
# VALIDAR TEXTO SIN CIFRAS
# ============================================================

def text_contains_forbidden_numeric_content(
    value,
):
    """
    Los números autoritativos siempre los renderiza Python.

    Por eso el texto libre del modelo no puede contener cifras.
    """

    if not isinstance(
        value,
        str,
    ):
        return False

    if re.search(
        r"\d",
        value,
    ):
        return True

    if "%" in value:
        return True

    return False


def validate_text_list(
    value,
    field_name,
    errors,
):
    if not isinstance(
        value,
        list,
    ):
        errors.append(
            f"{field_name}: debe ser lista."
        )
        return

    for index, item in enumerate(
        value
    ):
        if not isinstance(
            item,
            str,
        ):
            errors.append(
                f"{field_name}[{index}]: debe ser texto."
            )
            continue

        if text_contains_forbidden_numeric_content(
            item
        ):
            errors.append(
                f"{field_name}[{index}]: contiene cifras."
            )


# ============================================================
# VALIDAR RESPUESTA DE COMPARACIÓN
# ============================================================

def validate_comparison_llm_response(
    response,
    episode_catalog,
):
    errors = []

    expected_root_keys = {
        "episode_assessments",
        "comparison_observations",
        "limitations",
        "conclusion",
    }

    actual_root_keys = set(
        response.keys()
    )

    missing_root = (
        expected_root_keys
        -
        actual_root_keys
    )

    extra_root = (
        actual_root_keys
        -
        expected_root_keys
    )

    if missing_root:
        errors.append(
            "Faltan claves raíz: "
            + ", ".join(
                sorted(missing_root)
            )
        )

    if extra_root:
        errors.append(
            "Claves raíz no permitidas: "
            + ", ".join(
                sorted(extra_root)
            )
        )

    assessments = response.get(
        "episode_assessments"
    )

    if not isinstance(
        assessments,
        list,
    ):
        errors.append(
            "episode_assessments debe ser lista."
        )
        assessments = []

    expected_ids = [
        episode[
            "episode_id"
        ]
        for episode in episode_catalog
    ]

    episode_by_id = {
        safe_int(
            episode.get("episode_id")
        ): episode
        for episode in episode_catalog
        if safe_int(
            episode.get("episode_id")
        ) is not None
    }

    comparison_channels, comparison_speed_context = (
        grounding_context_from_episodes(
            episode_catalog
        )
    )

    actual_ids = []

    for index, assessment in enumerate(
        assessments
    ):
        if not isinstance(
            assessment,
            dict,
        ):
            errors.append(
                f"episode_assessments[{index}] no es objeto."
            )
            continue

        expected_keys = {
            "episode_id",
            "classification",
            "interpretation",
            "hypotheses",
            "recommendation",
        }

        actual_keys = set(
            assessment.keys()
        )

        if actual_keys != expected_keys:
            missing = (
                expected_keys
                -
                actual_keys
            )
            extra = (
                actual_keys
                -
                expected_keys
            )

            if missing:
                errors.append(
                    f"Episodio índice {index}: "
                    "faltan claves "
                    + ", ".join(
                        sorted(missing)
                    )
                )

            if extra:
                errors.append(
                    f"Episodio índice {index}: "
                    "sobran claves "
                    + ", ".join(
                        sorted(extra)
                    )
                )

        episode_id = safe_int(
            assessment.get(
                "episode_id"
            )
        )

        if episode_id is None:
            errors.append(
                f"Episodio índice {index}: episode_id inválido."
            )
        else:
            actual_ids.append(
                episode_id
            )

        episode = episode_by_id.get(
            episode_id
        )

        if isinstance(episode, dict):
            allowed_action_channels = set(
                episode.get(
                    "action_channels",
                    [],
                )
                or []
            )
            speed_context_available = (
                episode_has_speed_context(
                    episode
                )
            )
        else:
            allowed_action_channels = set()
            speed_context_available = False

        classification = assessment.get(
            "classification"
        )

        if classification not in (
            ALLOWED_CLASSIFICATIONS
        ):
            errors.append(
                f"Episodio {episode_id}: "
                f"classification inválida: "
                f"{classification}"
            )

        interpretation = assessment.get(
            "interpretation"
        )

        if not isinstance(
            interpretation,
            str,
        ):
            errors.append(
                f"Episodio {episode_id}: "
                "interpretation debe ser texto."
            )
        else:
            if text_contains_forbidden_numeric_content(
                interpretation
            ):
                errors.append(
                    f"Episodio {episode_id}: "
                    "interpretation contiene cifras."
                )

            validate_grounded_text(
                interpretation,
                f"Episodio {episode_id}.interpretation",
                allowed_action_channels,
                speed_context_available,
                errors,
            )

        hypotheses = assessment.get(
            "hypotheses"
        )

        validate_text_list(
            hypotheses,
            f"Episodio {episode_id}.hypotheses",
            errors,
        )

        validate_grounded_text_list(
            hypotheses,
            f"Episodio {episode_id}.hypotheses",
            allowed_action_channels,
            speed_context_available,
            errors,
        )

        recommendation = assessment.get(
            "recommendation"
        )

        if not isinstance(
            recommendation,
            str,
        ):
            errors.append(
                f"Episodio {episode_id}: "
                "recommendation debe ser texto."
            )
        else:
            if text_contains_forbidden_numeric_content(
                recommendation
            ):
                errors.append(
                    f"Episodio {episode_id}: "
                    "recommendation contiene cifras."
                )

            validate_grounded_text(
                recommendation,
                f"Episodio {episode_id}.recommendation",
                allowed_action_channels,
                speed_context_available,
                errors,
            )

    if len(
        assessments
    ) != len(
        episode_catalog
    ):
        errors.append(
            "Cantidad de episodios incorrecta: "
            f"esperados={len(episode_catalog)} "
            f"recibidos={len(assessments)}"
        )

    if len(
        actual_ids
    ) != len(
        set(actual_ids)
    ):
        errors.append(
            "Hay episode_id duplicados."
        )

    if sorted(
        actual_ids
    ) != sorted(
        expected_ids
    ):
        errors.append(
            "Los episode_id no coinciden con los esperados: "
            f"esperados={expected_ids} "
            f"recibidos={actual_ids}"
        )

    comparison_observations = response.get(
        "comparison_observations"
    )

    validate_text_list(
        comparison_observations,
        "comparison_observations",
        errors,
    )

    validate_grounded_text_list(
        comparison_observations,
        "comparison_observations",
        comparison_channels,
        comparison_speed_context,
        errors,
    )

    limitations = response.get(
        "limitations"
    )

    validate_text_list(
        limitations,
        "limitations",
        errors,
    )

    validate_grounded_text_list(
        limitations,
        "limitations",
        comparison_channels,
        comparison_speed_context,
        errors,
    )

    conclusion = response.get(
        "conclusion"
    )

    if not isinstance(
        conclusion,
        str,
    ):
        errors.append(
            "conclusion debe ser texto."
        )
    else:
        if text_contains_forbidden_numeric_content(
            conclusion
        ):
            errors.append(
                "conclusion contiene cifras."
            )

        validate_grounded_text(
            conclusion,
            "conclusion",
            comparison_channels,
            comparison_speed_context,
            errors,
        )

    return errors


# ============================================================
# RUTA LEGACY DE COMPARACIÓN ELIMINADA EN v3.8.17
# ============================================================
#
# Desde v3.8.17 NO existe una llamada LLM multi-episodio para
# interpretación. Cada driver_action_episode se interpreta y valida
# en aislamiento; Python agrega los resultados ya validados.
# ============================================================

# ============================================================
# ORQUESTACIÓN AISLADA POR EPISODIO v3.8.17
# ============================================================
#
# Motivo del cambio:
# una única llamada con varios episodios permitía contaminación
# semántica entre sus whitelists. Desde v3.8.17 cada episodio se
# interpreta y valida en aislamiento. Python vuelve a reunir los
# objetos ya validados y solicita una síntesis separada.
#
# El contrato externo de llm_structured NO cambia.
# ============================================================

EPISODE_SYSTEM_PROMPT = """
Sos un ingeniero de carrera que interpreta UN único episodio de
telemetría ya detectado y cuantificado por Python.

Python es la única autoridad sobre hechos, canales, magnitudes,
ranking y contexto.

Tu tarea es cualitativa.

Reglas obligatorias:
- respondé únicamente un objeto JSON válido;
- no uses Markdown ni texto fuera del JSON;
- no escribas cifras en ningún texto libre;
- no agregues hechos ni conceptos ausentes del payload;
- usá únicamente el vocabulario de acción incluido en
  allowed_action_language;
- si no hay evidencia suficiente para una hipótesis segura,
  devolvé hypotheses como lista vacía;
- no atribuyas causas externas que el payload no observa;
- la recomendación debe referirse únicamente a la acción observable
  autorizada para este episodio;
- no presentes causalidad como hecho.
"""


COMPARISON_SUMMARY_SYSTEM_PROMPT = """
Sos un ingeniero de carrera que sintetiza evaluaciones de episodios
que ya fueron validadas individualmente por Python.

No reinterpretás telemetría cruda.
No agregás hechos, canales ni causas nuevas.
No escribís cifras en ningún texto libre.
Respondé únicamente JSON válido, sin Markdown ni texto adicional.
"""


def compact_episode_payload_isolated(episode):
    """
    Payload de UN episodio para interpretación semántica aislada.

    v3.8.17 separa interpretación de priorización: esta etapa NO recibe
    rank, action_time_loss, loss clusters ni límites espaciales. Sólo ve
    acciones autorizadas y, cuando existe, contexto de velocidad saneado.
    """
    action_channels = list(episode.get("action_channels", []) or [])
    result = {
        "episode_id": episode["episode_id"],
        "action_channels": action_channels,
        "allowed_action_language": allowed_action_language_for_llm(
            action_channels
        ),
        "action_evidence_by_channel": compact_action_evidence_for_llm(
            episode
        ),
    }

    speed_context = compact_speed_context_for_llm(episode)
    if speed_context:
        result["speed_context"] = speed_context

    return result


def correction_kinds(errors):
    """
    Resume errores sin repetir vocabulario prohibido dentro del retry.
    Esto evita reinyectar al modelo exactamente los conceptos que
    acabamos de rechazar.
    """
    kinds = set()

    for error in errors or []:
        text = str(error).lower()

        if (
            "faltan claves" in text
            or "sobran claves" in text
            or "debe ser" in text
            or "episode_id" in text
            or "cantidad" in text
        ):
            kinds.add("schema")

        if "cifra" in text:
            kinds.add("digits")

        if (
            "autorizado" in text
            or "ground" in text
            or "dominio no observado" in text
            or "speed_context" in text
            or "causal" in text
        ):
            kinds.add("grounding")

        if "json" in text:
            kinds.add("json")

    if not kinds:
        kinds.add("contract")

    return sorted(kinds)


def build_single_episode_prompt(
    metadata,
    comparison,
    episode,
    correction_errors=None,
):
    payload = compact_episode_payload_isolated(episode)

    allowed_words = payload.get(
        "allowed_action_language",
        [],
    )

    speed_allowed = "speed_context" in payload

    if speed_allowed:
        speed_rule = (
            "El payload incluye contexto explícito de velocidad. "
            "Podés describir coexistencia temporal o posible propagación, "
            "pero no afirmar que una acción causó la velocidad observada."
        )
    else:
        speed_rule = (
            "No introduzcas ningún concepto físico o dinámico adicional "
            "fuera de las acciones expresamente autorizadas."
        )

    correction_block = ""

    if correction_errors:
        correction_block = f"""
REINTENTO OBLIGATORIO
La respuesta anterior violó el contrato.
Tipos de error detectados por Python:
{compact_json(correction_kinds(correction_errors))}

Regenerá el objeto COMPLETO desde cero.
No devuelvas un parche ni una clave aislada.
"""

    schema = {
        "episode_id": episode["episode_id"],
        "interpretation": "descripción cualitativa sin cifras",
        "hypotheses": [
            "hipótesis prudente limitada a la evidencia"
        ],
        "recommendation": "recomendación cualitativa sin cifras",
    }

    return f"""
Interpretá únicamente ESTE episodio.

No uses información de otros episodios.
No clasifiques su prioridad; otra etapa comparará todos los episodios.
No completes información por conocimiento general del circuito,
del vehículo ni de conducción.

VOCABULARIO DE ACCIÓN AUTORIZADO PARA ESTE EPISODIO:
{compact_json(allowed_words)}

Si una palabra o concepto de acción no está representado por esa
whitelist, no lo introduzcas.

{speed_rule}

EPISODIO SANEADO POR PYTHON:
{compact_json(payload)}

CAUSALIDAD:
- describí coexistencia, asociación o compatibilidad;
- podés usar expresiones prudentes como "podría contribuir";
- no uses "causó", "generó", "provocó", "produjo", "se debe a",
  "debido a" ni "como consecuencia directa".

CONTRATO JSON EXACTO:
- episode_id: entero idéntico al recibido;
- interpretation: string sin cifras;
- hypotheses: lista de strings sin cifras;
- recommendation: string sin cifras.

No agregues ni omitas claves.
Si no podés formular una hipótesis grounded, usá hypotheses: [].

Ejemplo de FORMA:
{compact_json(schema)}

{correction_block}

Respondé únicamente con el objeto JSON completo.
"""


def validate_single_episode_llm_response(
    response,
    episode,
):
    errors = []

    expected_keys = {
        "episode_id",
        "interpretation",
        "hypotheses",
        "recommendation",
    }

    actual_keys = set(response.keys())

    if actual_keys != expected_keys:
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys

        if missing:
            errors.append(
                "Faltan claves del episodio: "
                + ", ".join(sorted(missing))
            )

        if extra:
            errors.append(
                "Sobran claves del episodio: "
                + ", ".join(sorted(extra))
            )

    expected_id = safe_int(
        episode.get("episode_id")
    )
    actual_id = safe_int(
        response.get("episode_id")
    )

    if actual_id != expected_id:
        errors.append(
            "episode_id no coincide con el episodio solicitado."
        )

    allowed_action_channels = set(
        episode.get("action_channels", []) or []
    )
    speed_context_available = episode_has_speed_context(
        episode
    )

    interpretation = response.get(
        "interpretation"
    )

    if not isinstance(interpretation, str):
        errors.append(
            "interpretation debe ser texto."
        )
    else:
        if text_contains_forbidden_numeric_content(
            interpretation
        ):
            errors.append(
                "interpretation contiene cifras."
            )

        validate_grounded_text(
            interpretation,
            "interpretation",
            allowed_action_channels,
            speed_context_available,
            errors,
        )

    hypotheses = response.get(
        "hypotheses"
    )

    validate_text_list(
        hypotheses,
        "hypotheses",
        errors,
    )

    validate_grounded_text_list(
        hypotheses,
        "hypotheses",
        allowed_action_channels,
        speed_context_available,
        errors,
    )

    recommendation = response.get(
        "recommendation"
    )

    if not isinstance(recommendation, str):
        errors.append(
            "recommendation debe ser texto."
        )
    else:
        if text_contains_forbidden_numeric_content(
            recommendation
        ):
            errors.append(
                "recommendation contiene cifras."
            )

        validate_grounded_text(
            recommendation,
            "recommendation",
            allowed_action_channels,
            speed_context_available,
            errors,
        )

    return errors



def _parse_list_item_error(error, field_name):
    """Devuelve el índice de field_name[i] si el error pertenece sólo a ese item."""
    match = re.match(
        rf"^{re.escape(field_name)}\[(\d+)\]:",
        str(error),
    )
    if not match:
        return None
    return int(match.group(1))


def prune_only_invalid_episode_hypotheses(
    response,
    episode,
    errors,
):
    """
    Fallback determinista v3.8.17.

    Sólo se permite si TODOS los errores restantes pertenecen a
    hypotheses[i]. Como hypotheses es una lista opcional, Python elimina
    únicamente los items no grounded y vuelve a validar el objeto completo.
    Nunca reescribe interpretation ni recommendation.
    """
    if not isinstance(response, dict) or not errors:
        return None, []

    hypotheses = response.get("hypotheses")
    if not isinstance(hypotheses, list):
        return None, []

    bad_indexes = []
    for error in errors:
        index = _parse_list_item_error(error, "hypotheses")
        if index is None:
            return None, []
        bad_indexes.append(index)

    bad_indexes = sorted(set(bad_indexes))
    if any(index < 0 or index >= len(hypotheses) for index in bad_indexes):
        return None, []

    pruned = dict(response)
    pruned["hypotheses"] = [
        item
        for index, item in enumerate(hypotheses)
        if index not in set(bad_indexes)
    ]

    remaining = validate_single_episode_llm_response(
        pruned,
        episode,
    )
    if remaining:
        return None, []

    return pruned, bad_indexes



def _episode_response_structure_allows_semantic_fallback(response, episode):
    """
    Permite fallback semántico sólo si el LLM respetó la estructura básica.

    Python NO rescata JSON roto, IDs incorrectos ni tipos inválidos. El
    fallback únicamente reemplaza texto libre después de agotar los intentos.
    """
    if not isinstance(response, dict):
        return False

    expected_keys = {
        "episode_id",
        "interpretation",
        "hypotheses",
        "recommendation",
    }
    if set(response.keys()) != expected_keys:
        return False

    if safe_int(response.get("episode_id")) != safe_int(episode.get("episode_id")):
        return False

    if not isinstance(response.get("interpretation"), str):
        return False
    if not isinstance(response.get("recommendation"), str):
        return False

    hypotheses = response.get("hypotheses")
    if not isinstance(hypotheses, list):
        return False
    if any(not isinstance(item, str) for item in hypotheses):
        return False

    return True


def _channel_direction_phrase(channel, evidence):
    """Descripción puramente factual del sentido de los eventos del canal."""
    events = []
    if isinstance(evidence, dict):
        events = [
            item for item in (evidence.get("events", []) or [])
            if isinstance(item, dict)
        ]

    directions = {
        str(item.get("direction"))
        for item in events
        if item.get("direction")
    }

    single_direction = next(iter(directions)) if len(directions) == 1 else None

    if channel == "brake":
        if single_direction == "higher_in_comparison_lap":
            return "una aplicación de freno mayor"
        if single_direction == "lower_in_comparison_lap":
            return "una aplicación de freno menor"
        return "variaciones sostenidas en la aplicación del freno"

    if channel == "throttle":
        if single_direction == "higher_in_comparison_lap":
            return "un uso del acelerador mayor"
        if single_direction == "lower_in_comparison_lap":
            return "un uso del acelerador menor"
        return "variaciones sostenidas en el uso del acelerador"

    if channel == "steering_magnitude":
        if single_direction == "higher_in_comparison_lap":
            return "una magnitud de dirección/volante mayor"
        if single_direction == "lower_in_comparison_lap":
            return "una magnitud de dirección/volante menor"
        return "variaciones sostenidas en la magnitud de dirección/volante"

    return None


def build_deterministic_grounded_episode_fallback(episode):
    """
    Fallback factual mínimo v3.8.17.

    No interpreta causas ni inventa coaching específico. Describe únicamente
    los action_channels y direcciones que Python ya calculó. hypotheses queda
    vacío. Se usa sólo después de dos fallos semánticos del LLM.
    """
    channels = list(episode.get("action_channels", []) or [])
    evidence_by_channel = episode.get("action_evidence_by_channel", {}) or {}

    phrases = []
    for channel in channels:
        phrase = _channel_direction_phrase(
            channel,
            evidence_by_channel.get(channel, {}),
        )
        if phrase:
            phrases.append(phrase)

    if not phrases:
        return None

    if len(phrases) == 1:
        observation = phrases[0]
    elif len(phrases) == 2:
        observation = f"{phrases[0]} y {phrases[1]}"
    else:
        observation = ", ".join(phrases[:-1]) + f" y {phrases[-1]}"

    allowed_words = allowed_action_language_for_llm(channels)
    if len(allowed_words) == 1:
        recommendation = (
            f"revisar la consistencia del uso de {allowed_words[0]} "
            "en este episodio"
        )
    elif len(allowed_words) == 2:
        recommendation = (
            f"revisar la coordinación entre {allowed_words[0]} y "
            f"{allowed_words[1]} en este episodio"
        )
    else:
        recommendation = (
            "revisar la coordinación entre "
            + ", ".join(allowed_words[:-1])
            + f" y {allowed_words[-1]} en este episodio"
        )

    return {
        "episode_id": episode.get("episode_id"),
        "interpretation": (
            f"se observaron {observation} respecto de la vuelta de referencia"
        ),
        "hypotheses": [],
        "recommendation": recommendation,
    }


def deterministic_episode_semantic_fallback(response, episode, errors):
    """
    Rescate final tras agotar reintentos.

    Sólo se activa si el último objeto tiene schema/tipos/ID correctos. Se
    descarta TODO el texto libre del LLM y se reconstruye una descripción
    mínima desde hechos de Python; luego se vuelve a pasar por el validator.
    """
    if not errors:
        return None

    if not _episode_response_structure_allows_semantic_fallback(response, episode):
        return None

    candidate = build_deterministic_grounded_episode_fallback(episode)
    if candidate is None:
        return None

    remaining = validate_single_episode_llm_response(candidate, episode)
    if remaining:
        return None

    return candidate


def prune_only_invalid_summary_list_items(
    response,
    episode_catalog,
    errors,
):
    """
    Fallback determinista para listas opcionales del resumen.

    Puede descartar únicamente items inválidos de
    comparison_observations y limitations. La conclusión nunca se reescribe
    ni se descarta automáticamente.
    """
    if not isinstance(response, dict) or not errors:
        return None, {}

    allowed_fields = {
        "comparison_observations",
        "limitations",
    }
    bad = {field: set() for field in allowed_fields}

    for error in errors:
        matched = False
        for field in allowed_fields:
            index = _parse_list_item_error(error, field)
            if index is not None:
                bad[field].add(index)
                matched = True
                break
        if not matched:
            return None, {}

    pruned = dict(response)
    removed = {}
    for field, indexes in bad.items():
        if not indexes:
            continue
        value = response.get(field)
        if not isinstance(value, list):
            return None, {}
        if any(index < 0 or index >= len(value) for index in indexes):
            return None, {}
        pruned[field] = [
            item
            for index, item in enumerate(value)
            if index not in indexes
        ]
        removed[field] = sorted(indexes)

    remaining = validate_comparison_summary_llm_response(
        pruned,
        episode_catalog,
    )
    if remaining:
        return None, {}

    return pruned, removed


def get_validated_episode_response(
    metadata,
    comparison,
    episode,
    output_dir,
):
    errors = None
    last_raw = None
    episode_id = episode["episode_id"]

    for attempt in range(
        1,
        MAX_LLM_VALIDATION_ATTEMPTS + 1,
    ):
        prompt = build_single_episode_prompt(
            metadata,
            comparison,
            episode,
            correction_errors=errors,
        )

        if SAVE_COMPARISON_PROMPTS:
            path = os.path.join(
                output_dir,
                (
                    f"comparison_{comparison['reference_lap']}_"
                    f"{comparison['comparison_lap']}_"
                    f"episode_{episode_id}_"
                    f"prompt_attempt_{attempt}.txt"
                ),
            )
            save_text(path, prompt)

        raw = ollama_chat(
            EPISODE_SYSTEM_PROMPT,
            prompt,
        )
        last_raw = raw

        try:
            parsed = parse_llm_json(raw)
        except Exception as exc:
            errors = [str(exc)]
            print(
                f"    Episodio {episode_id}: respuesta rechazada "
                f"(intento {attempt}): JSON inválido."
            )
            continue

        errors = validate_single_episode_llm_response(
            parsed,
            episode,
        )

        if not errors:
            return {
                "status": "VALID",
                "attempts": attempt,
                "response": parsed,
                "validation_errors": [],
            }

        print(
            f"    Episodio {episode_id}: respuesta rechazada "
            f"(intento {attempt})."
        )

        for error in errors:
            print(f"      - {error}")

    pruned_response, removed_indexes = (
        prune_only_invalid_episode_hypotheses(
            parsed if 'parsed' in locals() else None,
            episode,
            errors,
        )
    )

    if pruned_response is not None:
        print(
            f"    Episodio {episode_id}: fallback determinista "
            f"v3.8.17 aplicado; se descartaron "
            f"{len(removed_indexes)} hipótesis no grounded."
        )
        return {
            "status": "VALID",
            "attempts": MAX_LLM_VALIDATION_ATTEMPTS,
            "response": pruned_response,
            "validation_errors": [],
            "fallback": "PRUNED_INVALID_HYPOTHESES",
            "pruned_hypothesis_indexes": removed_indexes,
            "original_validation_errors": errors or [],
        }

    semantic_fallback = deterministic_episode_semantic_fallback(
        parsed if 'parsed' in locals() else None,
        episode,
        errors,
    )

    if semantic_fallback is not None:
        print(
            f"    Episodio {episode_id}: fallback factual mínimo "
            "v3.8.17 aplicado tras agotar los reintentos."
        )
        return {
            "status": "VALID",
            "attempts": MAX_LLM_VALIDATION_ATTEMPTS,
            "response": semantic_fallback,
            "validation_errors": [],
            "fallback": "DETERMINISTIC_GROUNDED_EPISODE_TEXT",
            "pruned_hypothesis_indexes": [],
            "original_validation_errors": errors or [],
        }

    rejected_path = os.path.join(
        output_dir,
        (
            f"comparison_{comparison['reference_lap']}_"
            f"{comparison['comparison_lap']}_"
            f"episode_{episode_id}_REJECTED.txt"
        ),
    )

    save_text(
        rejected_path,
        (
            "VALIDATION ERRORS\n"
            "=================\n"
            + "\n".join(errors or [])
            + "\n\nRAW RESPONSE\n"
            "============\n"
            + (
                last_raw
                if isinstance(last_raw, str)
                else repr(last_raw)
            )
        ),
    )

    return {
        "status": "REJECTED",
        "attempts": MAX_LLM_VALIDATION_ATTEMPTS,
        "response": None,
        "validation_errors": errors or [],
    }



COMPARISON_RANKER_SYSTEM_PROMPT = """
Sos un ingeniero de carrera que recibe todos los episodios de UNA comparación.
Recibís únicamente hechos comparativos deterministas calculados por Python.

Tu única tarea es construir una JERARQUÍA RELATIVA entre esos episodios.
No reinterpretás telemetría, no agregás causas y no escribís explicación libre.
Respondé únicamente JSON válido.

Primero ordená TODOS los episode_id desde la oportunidad de coaching más
importante hasta la menos importante. Después elegí dos cortes de tier:

- priority_cut_rank: último puesto que pertenece al tier PRIORITARIO.
- no_actionable_start_rank: primer puesto que pertenece a NO_ACCIONABLE.
  Usá N+1 cuando no haya episodios NO_ACCIONABLES.

Los puestos entre ambos cortes son SECUNDARIO.

PRIORITARIO se reserva para el grupo superior comparativamente más claro y
accionable de ESTA comparación.
SECUNDARIO indica oportunidades reales de menor urgencia relativa.
NO_ACCIONABLE se reserva para evidencia descriptiva que no justifica una
acción de coaching inmediata.

No existe threshold de segundos ni cantidad fija por clase. La jerarquía debe
surgir de la comparación entre los episodios, usando la magnitud relativa de
pérdida, el ranking objetivo de Python, la fuerza de evidencia, los canales de
acción y la disponibilidad de contexto de velocidad.
"""


def _finite_number(value):
    value = safe_float(value)
    if value is None:
        return None
    try:
        if not math.isfinite(value):
            return None
    except Exception:
        return None
    return value


def _priority_relative_metrics(episode_catalog):
    """Métricas comparativas deterministas para ayudar al ranker sin thresholds."""
    losses = []
    for episode in episode_catalog:
        value = _finite_number(episode.get("action_time_loss_s"))
        losses.append(max(value, 0.0) if value is not None else 0.0)

    max_loss = max(losses) if losses else 0.0
    total_loss = sum(losses)

    metrics = {}
    for episode, loss in zip(episode_catalog, losses):
        episode_id = safe_int(episode.get("episode_id"))
        metrics[episode_id] = {
            "action_loss_vs_max": (
                loss / max_loss if max_loss > 0.0 else None
            ),
            "action_loss_share_of_total": (
                loss / total_loss if total_loss > 0.0 else None
            ),
        }
    return metrics


def compact_episode_for_priority_ranking(
    episode,
    assessment,
    relative_metrics=None,
):
    """Sólo hechos deterministas para que el ranker tenga prompt estable."""
    episode_id = safe_int(episode.get("episode_id"))
    relative_metrics = relative_metrics or {}
    rel = relative_metrics.get(episode_id, {})

    return {
        "episode_id": episode["episode_id"],
        "objective_rank": (
            episode.get("global_rank")
            or episode.get("rank")
            or episode["episode_id"]
        ),
        "action_time_loss_s": episode.get("action_time_loss_s"),
        "action_loss_vs_max": rel.get("action_loss_vs_max"),
        "action_loss_share_of_total": rel.get(
            "action_loss_share_of_total"
        ),
        "parent_zone_delta_loss_s": episode.get("parent_zone_delta_loss_s"),
        "parent_zone_net_loss_equivalent_percent": episode.get(
            "parent_zone_net_loss_equivalent_percent"
        ),
        "evidence_strength": episode.get("evidence_strength"),
        "action_channel_count": episode.get("action_channel_count"),
        "action_channels": list(episode.get("action_channels", []) or []),
        "speed_context_available": episode_has_speed_context(episode),
    }


def _neutral_ranker_payload_order(payload):
    """Orden estable no relacionado con objective_rank para reducir anchoring."""
    def key(item):
        episode_id = safe_int(item.get("episode_id"))
        token = f"ranker-neutral-order-v1:{episode_id}".encode("utf-8")
        return hashlib.sha256(token).hexdigest()

    return sorted(payload, key=key)


def comparison_ranker_json_schema():
    """Schema estructural sin valores de ejemplo que puedan anclar al modelo."""
    return {
        "type": "object",
        "properties": {
            "ordered_episode_ids": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "priority_cut_rank": {"type": "integer"},
            "no_actionable_start_rank": {"type": "integer"},
        },
        "required": [
            "ordered_episode_ids",
            "priority_cut_rank",
            "no_actionable_start_rank",
        ],
        "additionalProperties": False,
    }


def build_comparison_ranker_prompt(
    episode_catalog,
    episode_assessments,
    correction_errors=None,
):
    relative_metrics = _priority_relative_metrics(episode_catalog)
    payload = [
        compact_episode_for_priority_ranking(
            episode,
            assessment,
            relative_metrics=relative_metrics,
        )
        for episode, assessment in zip(
            episode_catalog,
            episode_assessments,
        )
    ]
    payload = _neutral_ranker_payload_order(payload)

    ids = [
        safe_int(episode.get("episode_id"))
        for episode in episode_catalog
    ]
    n = len(ids)

    correction_block = ""
    if correction_errors:
        correction_block = f"""
REINTENTO OBLIGATORIO
La respuesta anterior violó el contrato.
Tipos de error:
{compact_json(correction_kinds(correction_errors))}
Regenerá el objeto raíz COMPLETO desde cero.
"""

    return f"""
Construí la prioridad RELATIVA usando exclusivamente estos hechos deterministas.

EPISODIOS:
{compact_json(payload)}

REGLAS DE ORDEN:
- ordered_episode_ids debe contener TODOS los episode_id exactamente una vez;
- el primer ID es la oportunidad de coaching de mayor prioridad relativa;
- el último ID es la de menor prioridad relativa;
- no copies automáticamente objective_rank: usalo como evidencia objetiva junto
  con el resto de los hechos deterministas;
- no inventes información nueva.

REGLAS DE TIERS:
- priority_cut_rank es el último puesto del tier PRIORITARIO;
- si hay más de un episodio, al menos uno debe quedar fuera de PRIORITARIO;
- no_actionable_start_rank es el primer puesto NO_ACCIONABLE;
- si ningún episodio es NO_ACCIONABLE, devolvé {n + 1};
- los puestos entre ambos cortes son SECUNDARIO;
- no existe cuota fija ni threshold numérico de tiempo;
- elegí los cortes observando la separación RELATIVA entre los episodios.

No devuelvas classification por episodio: Python la deriva de forma
determinista a partir del orden y los cortes.
No devuelvas explicación, rationale ni texto adicional.

La estructura JSON está impuesta externamente mediante JSON Schema.
IMPORTANTE: no existe ningún ejemplo de valores correctos en este prompt.
Debés decidir el orden y ambos cortes exclusivamente a partir de EPISODIOS.

{correction_block}

Respondé únicamente con el objeto JSON completo.
"""


def validate_comparison_ranker_response(response, episode_catalog):
    errors = []
    expected_keys = {
        "ordered_episode_ids",
        "priority_cut_rank",
        "no_actionable_start_rank",
    }
    actual_keys = set(response.keys()) if isinstance(response, dict) else set()

    if actual_keys != expected_keys:
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        if missing:
            errors.append(
                "Faltan claves del ranker: " + ", ".join(sorted(missing))
            )
        if extra:
            errors.append(
                "Sobran claves del ranker: " + ", ".join(sorted(extra))
            )

    if not isinstance(response, dict):
        return errors or ["La respuesta del ranker debe ser objeto."]

    ordered = response.get("ordered_episode_ids")
    expected_ids = [
        safe_int(ep.get("episode_id"))
        for ep in episode_catalog
    ]
    n = len(expected_ids)

    if not isinstance(ordered, list):
        errors.append("ordered_episode_ids debe ser lista.")
        ordered_ids = []
    else:
        ordered_ids = [safe_int(value) for value in ordered]
        if any(value is None for value in ordered_ids):
            errors.append(
                "ordered_episode_ids debe contener sólo IDs enteros."
            )

    if len(ordered_ids) != n:
        errors.append(
            "Cantidad de IDs ordenados incorrecta: "
            f"esperados={n} recibidos={len(ordered_ids)}"
        )

    if (
        sorted(x for x in ordered_ids if x is not None)
        != sorted(x for x in expected_ids if x is not None)
    ):
        errors.append(
            "ordered_episode_ids no coincide con los episode_id esperados."
        )

    if len(ordered_ids) != len(set(ordered_ids)):
        errors.append("ordered_episode_ids contiene IDs duplicados.")

    priority_cut = safe_int(response.get("priority_cut_rank"))
    no_actionable_start = safe_int(
        response.get("no_actionable_start_rank")
    )

    if n <= 0:
        errors.append("El ranker requiere al menos un episodio.")
        return errors

    if priority_cut is None:
        errors.append("priority_cut_rank debe ser entero.")
    else:
        max_priority_cut = 1 if n == 1 else n - 1
        if not (1 <= priority_cut <= max_priority_cut):
            errors.append(
                "priority_cut_rank fuera de rango: "
                f"debe estar entre 1 y {max_priority_cut}."
            )

    if no_actionable_start is None:
        errors.append("no_actionable_start_rank debe ser entero.")
    elif not (1 <= no_actionable_start <= n + 1):
        errors.append(
            "no_actionable_start_rank fuera de rango: "
            f"debe estar entre 1 y {n + 1}."
        )

    if (
        priority_cut is not None
        and no_actionable_start is not None
        and no_actionable_start <= priority_cut
    ):
        errors.append(
            "no_actionable_start_rank debe ser posterior a "
            "priority_cut_rank."
        )

    return errors


def derive_priority_classifications(
    ranker_response,
    episode_catalog,
):
    ordered = [
        safe_int(value)
        for value in ranker_response.get("ordered_episode_ids", [])
    ]
    priority_cut = safe_int(ranker_response.get("priority_cut_rank"))
    no_actionable_start = safe_int(
        ranker_response.get("no_actionable_start_rank")
    )

    position_by_id = {
        episode_id: rank
        for rank, episode_id in enumerate(ordered, start=1)
    }

    classifications = []
    for episode in episode_catalog:
        episode_id = safe_int(episode.get("episode_id"))
        rank = position_by_id[episode_id]

        if rank <= priority_cut:
            classification = "PRIORITARIO"
        elif rank >= no_actionable_start:
            classification = "NO_ACCIONABLE"
        else:
            classification = "SECUNDARIO"

        classifications.append(
            {
                "episode_id": episode_id,
                "relative_priority_rank": rank,
                "classification": classification,
            }
        )

    return classifications


def get_validated_comparison_ranker_response(
    episode_catalog,
    episode_assessments,
    comparison,
    output_dir,
):
    errors = None
    last_raw = None

    for attempt in range(1, MAX_LLM_VALIDATION_ATTEMPTS + 1):
        prompt = build_comparison_ranker_prompt(
            episode_catalog,
            episode_assessments,
            correction_errors=errors,
        )

        if SAVE_COMPARISON_PROMPTS:
            path = os.path.join(
                output_dir,
                (
                    f"comparison_{comparison['reference_lap']}_"
                    f"{comparison['comparison_lap']}_"
                    f"ranker_prompt_attempt_{attempt}.txt"
                ),
            )
            save_text(path, prompt)

        raw = ollama_chat(
            COMPARISON_RANKER_SYSTEM_PROMPT,
            prompt,
            temperature=RANKER_TEMPERATURE,
            seed=RANKER_SEED,
            timeout_seconds=RANKER_TIMEOUT_SECONDS,
            format_schema=comparison_ranker_json_schema(),
        )
        last_raw = raw

        try:
            parsed = parse_llm_json(raw)
        except Exception as exc:
            errors = [str(exc)]
            print(
                f"    Ranker: respuesta rechazada "
                f"(intento {attempt}): JSON inválido."
            )
            continue

        errors = validate_comparison_ranker_response(parsed, episode_catalog)
        if not errors:
            return {
                "status": "VALID",
                "attempts": attempt,
                "response": parsed,
                "validation_errors": [],
            }

        print(f"    Ranker: respuesta rechazada (intento {attempt}).")
        for error in errors:
            print(f"      - {error}")

    rejected_path = os.path.join(
        output_dir,
        (
            f"comparison_{comparison['reference_lap']}_"
            f"{comparison['comparison_lap']}_ranker_REJECTED.txt"
        ),
    )
    save_text(
        rejected_path,
        "VALIDATION ERRORS\n=================\n"
        + "\n".join(errors or [])
        + "\n\nRAW RESPONSE\n============\n"
        + (last_raw if isinstance(last_raw, str) else repr(last_raw)),
    )
    return {
        "status": "REJECTED",
        "attempts": MAX_LLM_VALIDATION_ATTEMPTS,
        "response": None,
        "validation_errors": errors or [],
    }


def apply_priority_classifications(
    episode_assessments,
    episode_catalog,
    ranker_response,
):
    derived = derive_priority_classifications(
        ranker_response,
        episode_catalog,
    )
    by_id = {
        safe_int(item.get("episode_id")): item
        for item in derived
    }

    merged = []
    for assessment in episode_assessments:
        item = dict(assessment)
        episode_id = safe_int(item.get("episode_id"))
        item["classification"] = by_id[episode_id]["classification"]
        merged.append(item)
    return merged


def build_comparison_summary_prompt(
    episode_assessments,
    correction_errors=None,
):
    payload = [
        {
            "classification": item.get("classification"),
            "interpretation": item.get("interpretation"),
            "hypotheses": item.get("hypotheses"),
            "recommendation": item.get("recommendation"),
        }
        for item in episode_assessments
    ]

    schema = {
        "comparison_observations": [
            "observación cualitativa apoyada por evaluaciones validadas"
        ],
        "limitations": [
            "la causa no puede determinarse con la evidencia disponible"
        ],
        "conclusion": "síntesis cualitativa sin cifras",
    }

    correction_block = ""

    if correction_errors:
        correction_block = f"""
REINTENTO OBLIGATORIO
La respuesta anterior violó el contrato.
Tipos de error:
{compact_json(correction_kinds(correction_errors))}
Regenerá el objeto raíz COMPLETO desde cero.
"""

    return f"""
Sintetizá únicamente las evaluaciones ya validadas que siguen.
No reinterpretes telemetría ni agregues conceptos nuevos.

EVALUACIONES VALIDADAS:
{compact_json(payload)}

CONTRATO JSON EXACTO:
- comparison_observations: lista de strings;
- limitations: lista de strings;
- conclusion: string.

Las listas pueden ser [].
No escribas cifras.
No agregues ni omitas claves.
Las limitaciones deben ser neutrales y referirse sólo a lo que no
puede inferirse de la evidencia disponible.

Ejemplo de FORMA:
{compact_json(schema)}

{correction_block}

Respondé únicamente con el objeto JSON completo.
"""


def validate_comparison_summary_llm_response(
    response,
    episode_catalog,
):
    errors = []

    expected_keys = {
        "comparison_observations",
        "limitations",
        "conclusion",
    }

    actual_keys = set(response.keys())

    if actual_keys != expected_keys:
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys

        if missing:
            errors.append(
                "Faltan claves del resumen: "
                + ", ".join(sorted(missing))
            )

        if extra:
            errors.append(
                "Sobran claves del resumen: "
                + ", ".join(sorted(extra))
            )

    allowed_channels, speed_context_available = (
        grounding_context_from_episodes(
            episode_catalog
        )
    )

    observations = response.get(
        "comparison_observations"
    )
    validate_text_list(
        observations,
        "comparison_observations",
        errors,
    )
    validate_grounded_text_list(
        observations,
        "comparison_observations",
        allowed_channels,
        speed_context_available,
        errors,
    )

    limitations = response.get(
        "limitations"
    )
    validate_text_list(
        limitations,
        "limitations",
        errors,
    )
    validate_grounded_text_list(
        limitations,
        "limitations",
        allowed_channels,
        speed_context_available,
        errors,
    )

    conclusion = response.get(
        "conclusion"
    )

    if not isinstance(conclusion, str):
        errors.append(
            "conclusion debe ser texto."
        )
    else:
        if text_contains_forbidden_numeric_content(
            conclusion
        ):
            errors.append(
                "conclusion contiene cifras."
            )

        validate_grounded_text(
            conclusion,
            "conclusion",
            allowed_channels,
            speed_context_available,
            errors,
        )

    return errors


def get_validated_comparison_summary_response(
    episode_assessments,
    episode_catalog,
    comparison,
    output_dir,
):
    errors = None
    last_raw = None

    for attempt in range(
        1,
        MAX_LLM_VALIDATION_ATTEMPTS + 1,
    ):
        prompt = build_comparison_summary_prompt(
            episode_assessments,
            correction_errors=errors,
        )

        if SAVE_COMPARISON_PROMPTS:
            path = os.path.join(
                output_dir,
                (
                    f"comparison_{comparison['reference_lap']}_"
                    f"{comparison['comparison_lap']}_"
                    f"summary_prompt_attempt_{attempt}.txt"
                ),
            )
            save_text(path, prompt)

        raw = ollama_chat(
            COMPARISON_SUMMARY_SYSTEM_PROMPT,
            prompt,
        )
        last_raw = raw

        try:
            parsed = parse_llm_json(raw)
        except Exception as exc:
            errors = [str(exc)]
            print(
                f"    Resumen: respuesta rechazada "
                f"(intento {attempt}): JSON inválido."
            )
            continue

        errors = validate_comparison_summary_llm_response(
            parsed,
            episode_catalog,
        )

        if not errors:
            return {
                "status": "VALID",
                "attempts": attempt,
                "response": parsed,
                "validation_errors": [],
            }

        print(
            f"    Resumen: respuesta rechazada "
            f"(intento {attempt})."
        )
        for error in errors:
            print(f"      - {error}")

    pruned_response, removed_items = (
        prune_only_invalid_summary_list_items(
            parsed if 'parsed' in locals() else None,
            episode_catalog,
            errors,
        )
    )

    if pruned_response is not None:
        removed_count = sum(
            len(indexes)
            for indexes in removed_items.values()
        )
        print(
            "    Resumen: fallback determinista v3.8.17 "
            f"aplicado; se descartaron {removed_count} items "
            "opcionales no grounded."
        )
        return {
            "status": "VALID",
            "attempts": MAX_LLM_VALIDATION_ATTEMPTS,
            "response": pruned_response,
            "validation_errors": [],
            "fallback": "PRUNED_INVALID_OPTIONAL_SUMMARY_ITEMS",
            "pruned_summary_items": removed_items,
        }

    rejected_path = os.path.join(
        output_dir,
        (
            f"comparison_{comparison['reference_lap']}_"
            f"{comparison['comparison_lap']}_"
            "summary_REJECTED.txt"
        ),
    )

    save_text(
        rejected_path,
        (
            "VALIDATION ERRORS\n"
            "=================\n"
            + "\n".join(errors or [])
            + "\n\nRAW RESPONSE\n"
            "============\n"
            + (
                last_raw
                if isinstance(last_raw, str)
                else repr(last_raw)
            )
        ),
    )

    return {
        "status": "REJECTED",
        "attempts": MAX_LLM_VALIDATION_ATTEMPTS,
        "response": None,
        "validation_errors": errors or [],
    }


def get_validated_comparison_response(
    metadata,
    comparison,
    episode_catalog,
    output_dir,
):
    """
    v3.8.17:
    1) interpreta cada episodio en aislamiento SIN clasificar prioridad;
    2) clasifica prioridad en una llamada comparativa separada;
    3) sintetiza la comparación con evaluaciones ya grounded y clasificadas.

    El contrato externo histórico de llm_structured se conserva.
    """
    episode_assessments = []
    attempt_counts = []
    episode_audit = []

    print(
        "  Modo aislado v3.8.17: interpretación por episodio + "
        "ranker comparativo separado."
    )

    for episode in episode_catalog:
        validated = get_validated_episode_response(
            metadata,
            comparison,
            episode,
            output_dir,
        )

        attempt_counts.append(validated["attempts"])
        audit_item = {
            "episode_id": episode["episode_id"],
            "attempts": validated["attempts"],
            "fallback": validated.get("fallback"),
            "pruned_hypothesis_indexes": validated.get(
                "pruned_hypothesis_indexes", []
            ),
            "original_validation_errors": validated.get(
                "original_validation_errors", []
            ),
        }
        episode_audit.append(audit_item)

        if validated["status"] != "VALID":
            return {
                "status": "REJECTED",
                "attempts": max(attempt_counts or [1]),
                "response": None,
                "validation_errors": [
                    f"Episodio {episode['episode_id']}: {error}"
                    for error in validated["validation_errors"]
                ],
                "audit": {"episodes": episode_audit},
            }

        episode_assessments.append(validated["response"])

    print("    Clasificando prioridad relativa entre episodios...")
    ranker = get_validated_comparison_ranker_response(
        episode_catalog,
        episode_assessments,
        comparison,
        output_dir,
    )
    attempt_counts.append(ranker["attempts"])

    if ranker["status"] != "VALID":
        return {
            "status": "REJECTED",
            "attempts": max(attempt_counts or [1]),
            "response": None,
            "validation_errors": [
                f"Ranker: {error}" for error in ranker["validation_errors"]
            ],
            "audit": {
                "episodes": episode_audit,
                "priority_ranking": {"attempts": ranker["attempts"]},
            },
        }

    classified_assessments = apply_priority_classifications(
        episode_assessments,
        episode_catalog,
        ranker["response"],
    )

    summary = get_validated_comparison_summary_response(
        classified_assessments,
        episode_catalog,
        comparison,
        output_dir,
    )
    attempt_counts.append(summary["attempts"])

    if summary["status"] != "VALID":
        return {
            "status": "REJECTED",
            "attempts": max(attempt_counts or [1]),
            "response": None,
            "validation_errors": [
                f"Resumen: {error}" for error in summary["validation_errors"]
            ],
            "audit": {
                "episodes": episode_audit,
                "priority_ranking": {"attempts": ranker["attempts"]},
                "summary": {"attempts": summary["attempts"]},
            },
        }

    structured = {
        "episode_assessments": classified_assessments,
        "comparison_observations": summary["response"]["comparison_observations"],
        "limitations": summary["response"]["limitations"],
        "conclusion": summary["response"]["conclusion"],
    }

    final_errors = validate_comparison_llm_response(
        structured,
        episode_catalog,
    )
    if final_errors:
        return {
            "status": "REJECTED",
            "attempts": max(attempt_counts or [1]),
            "response": None,
            "validation_errors": final_errors,
            "audit": {
                "episodes": episode_audit,
                "priority_ranking": {"attempts": ranker["attempts"]},
                "summary": {"attempts": summary["attempts"]},
            },
        }

    audit = {
        "episodes": episode_audit,
        "priority_ranking": {
            "attempts": ranker["attempts"],
            "ordered_episode_ids": ranker["response"][
                "ordered_episode_ids"
            ],
            "priority_cut_rank": ranker["response"][
                "priority_cut_rank"
            ],
            "no_actionable_start_rank": ranker["response"][
                "no_actionable_start_rank"
            ],
            "classifications": derive_priority_classifications(
                ranker["response"],
                episode_catalog,
            ),
        },
        "summary": {
            "attempts": summary["attempts"],
            "fallback": summary.get("fallback"),
            "pruned_summary_items": summary.get("pruned_summary_items", {}),
        },
    }

    return {
        "status": "VALID",
        "attempts": max(attempt_counts or [1]),
        "response": structured,
        "validation_errors": [],
        "audit": audit,
    }


# ============================================================
# FORMATEO DETERMINISTA
# ============================================================

def signed_seconds(value):
    value = safe_float(
        value
    )

    if value is None:
        return "N/D"

    return f"{value:+.4f} s"


def plain_seconds(value):
    value = safe_float(
        value
    )

    if value is None:
        return "N/D"

    return f"{value:.4f} s"


def meters(value):
    value = safe_float(
        value
    )

    if value is None:
        return "N/D"

    return f"{value:.0f} m"


def format_channel_names(
    channels,
):
    if not channels:
        return "sin canales de acción"

    names = {
        "throttle":
            "acelerador",

        "brake":
            "freno",

        "steering_magnitude":
            "magnitud de dirección",
    }

    return ", ".join(
        names.get(
            channel,
            channel,
        )
        for channel in channels
    )


def render_hypotheses(
    hypotheses,
):
    if not hypotheses:
        return "- Sin hipótesis adicional."

    return "\n".join(
        f"- {item}"
        for item in hypotheses
    )


def assessment_map(
    structured_response,
):
    return {
        safe_int(
            item[
                "episode_id"
            ]
        ):
            item
        for item in structured_response[
            "episode_assessments"
        ]
    }


# ============================================================
# RENDER DE COMPARACIÓN
# ============================================================

def render_comparison_analysis(
    comparison,
    episode_catalog,
    structured_response,
):
    amap = assessment_map(
        structured_response
    )

    lines = []

    lines.append(
        f"# Comparación "
        f"{comparison['reference_lap']} -> "
        f"{comparison['comparison_lap']}"
    )

    lines.append("")
    lines.append(
        "## Resultado general"
    )
    lines.append("")

    lines.append(
        "- Tiempo referencia: "
        + plain_seconds(
            comparison[
                "reference_time_s"
            ]
        )
    )

    lines.append(
        "- Tiempo comparación: "
        + plain_seconds(
            comparison[
                "comparison_time_s"
            ]
        )
    )

    lines.append(
        "- Delta total: "
        + signed_seconds(
            comparison[
                "comparison_minus_reference_s"
            ]
        )
    )

    priority = comparison.get(
        "driver_analysis_priority"
    )

    if priority is not None:
        lines.append(
            f"- Prioridad Python: {priority}"
        )

    lines.append("")
    lines.append(
        "## Clasificación de TODOS los episodios"
    )
    lines.append("")

    for episode in episode_catalog:
        episode_id = episode[
            "episode_id"
        ]

        assessment = amap[
            episode_id
        ]

        start = meters(
            episode.get(
                "start_distance_m"
            )
        )

        end = meters(
            episode.get(
                "end_distance_m"
            )
        )

        loss = signed_seconds(
            episode.get(
                "action_time_loss_s"
            )
        )

        channels = format_channel_names(
            episode.get(
                "action_channels",
                [],
            )
        )

        lines.append(
            f"- Episodio #{episode_id} — "
            f"{assessment['classification']} — "
            f"{start} a {end} — "
            f"cambio de delta {loss} — "
            f"{channels}"
        )

    for classification, title in (
        (
            "PRIORITARIO",
            "## Episodios prioritarios",
        ),
        (
            "SECUNDARIO",
            "## Episodios secundarios",
        ),
        (
            "NO_ACCIONABLE",
            "## Episodios no accionables",
        ),
    ):
        lines.append("")
        lines.append(title)
        lines.append("")

        selected = [
            episode
            for episode in episode_catalog
            if amap[
                episode["episode_id"]
            ][
                "classification"
            ]
            ==
            classification
        ]

        if not selected:
            lines.append(
                "- Ninguno."
            )
            continue

        for episode in selected:
            episode_id = episode[
                "episode_id"
            ]

            assessment = amap[
                episode_id
            ]

            lines.append(
                f"### Episodio #{episode_id} — "
                f"{meters(episode.get('start_distance_m'))} "
                f"a "
                f"{meters(episode.get('end_distance_m'))}"
            )

            lines.append("")

            lines.append(
                "**Impacto objetivo calculado por Python**"
            )

            lines.append("")

            lines.append(
                "- Cambio de delta durante el episodio: "
                + signed_seconds(
                    episode.get(
                        "action_time_loss_s"
                    )
                )
            )

            lines.append(
                "- Canales de acción detectados: "
                + format_channel_names(
                    episode.get(
                        "action_channels",
                        [],
                    )
                )
            )

            evidence_strength = episode.get(
                "evidence_strength"
            )

            if evidence_strength:
                lines.append(
                    f"- Fuerza de evidencia objetiva: "
                    f"{evidence_strength}"
                )

            speed_propagation = episode.get(
                "speed_propagation"
            )

            if speed_propagation:
                lines.append(
                    "- Python detectó propagación de "
                    "diferencia de velocidad posterior."
                )
            else:
                lines.append(
                    "- No se registró propagación de "
                    "velocidad asociada en el bloque suministrado."
                )

            lines.append("")
            lines.append(
                "**Interpretación del LLM**"
            )
            lines.append("")

            lines.append(
                assessment[
                    "interpretation"
                ]
            )

            lines.append("")
            lines.append(
                "**Hipótesis**"
            )
            lines.append("")

            lines.append(
                render_hypotheses(
                    assessment[
                        "hypotheses"
                    ]
                )
            )

            lines.append("")
            lines.append(
                "**Recomendación**"
            )
            lines.append("")

            lines.append(
                assessment[
                    "recommendation"
                ]
            )

            lines.append("")

    lines.append(
        "## Observaciones de conducción"
    )
    lines.append("")

    observations = (
        structured_response[
            "comparison_observations"
        ]
    )

    if observations:
        lines.extend(
            f"- {item}"
            for item in observations
        )
    else:
        lines.append(
            "- Sin observaciones adicionales."
        )

    lines.append("")
    lines.append(
        "## Qué no puede determinarse"
    )
    lines.append("")

    limitations = structured_response[
        "limitations"
    ]

    if limitations:
        lines.extend(
            f"- {item}"
            for item in limitations
        )
    else:
        lines.append(
            "- No se declararon limitaciones adicionales."
        )

    lines.append("")
    lines.append(
        "## Conclusión"
    )
    lines.append("")

    lines.append(
        structured_response[
            "conclusion"
        ]
    )

    return "\n".join(
        lines
    )



# ============================================================
# AGREGACIÓN DETERMINISTA DE COACHING DE SESIÓN v3.8.17
# ============================================================

def _single_event_direction(evidence):
    events = []

    if isinstance(evidence, dict):
        events = [
            item
            for item in (evidence.get("events", []) or [])
            if isinstance(item, dict)
        ]

    directions = {
        str(item.get("direction"))
        for item in events
        if item.get("direction")
    }

    if len(directions) == 1:
        return next(iter(directions))

    if directions:
        return "mixed"

    return None


def _channel_direction_coaching_label(
    channel,
    evidence,
):
    direction = _single_event_direction(
        evidence
    )

    labels = {
        ("throttle", "higher_in_comparison_lap"):
            "más acelerador",
        ("throttle", "lower_in_comparison_lap"):
            "menos acelerador",
        ("brake", "higher_in_comparison_lap"):
            "más freno",
        ("brake", "lower_in_comparison_lap"):
            "menos freno",
        ("steering_magnitude", "higher_in_comparison_lap"):
            "mayor magnitud de dirección/volante",
        ("steering_magnitude", "lower_in_comparison_lap"):
            "menor magnitud de dirección/volante",
    }

    if (channel, direction) in labels:
        return labels[
            (channel, direction)
        ]

    fallback = {
        "throttle":
            "modulación distinta del acelerador",
        "brake":
            "aplicación distinta del freno",
        "steering_magnitude":
            "magnitud distinta de dirección/volante",
    }

    return fallback.get(
        channel,
        str(channel),
    )



def _channel_quantitative_fact(
    channel,
    evidence,
):
    """
    Resume magnitudes observadas sin inferir causalidad.

    Para freno/acelerador las diferencias se expresan en puntos porcentuales
    porque los canales de origen están en percent. Para steering_magnitude se
    conservan las unidades nativas del input de volante; no se asumen grados.
    """
    if not isinstance(evidence, dict):
        evidence = {}

    events = [
        item
        for item in (evidence.get("events", []) or [])
        if isinstance(item, dict)
    ]

    event_mean_differences = [
        value
        for value in (
            safe_float(item.get("mean_difference"))
            for item in events
        )
        if value is not None
    ]

    event_peak_differences = [
        value
        for value in (
            safe_float(item.get("peak_difference"))
            for item in events
        )
        if value is not None
    ]

    mean_difference = safe_float(
        evidence.get("mean_of_event_mean_differences")
    )
    peak_difference = safe_float(
        evidence.get("largest_abs_peak_difference")
    )

    if peak_difference is None and event_peak_differences:
        peak_difference = max(
            event_peak_differences,
            key=lambda value: abs(value),
        )

    unit = None

    if channel in ("throttle", "brake"):
        unit = "percentage_points"
    elif channel == "steering_magnitude":
        unit = "steering_input_units"
    else:
        for event in events:
            raw_unit = event.get("unit")
            if raw_unit:
                unit = str(raw_unit)
                break

    return {
        "mean_difference": mean_difference,
        "peak_difference": peak_difference,
        "event_mean_min": (
            min(event_mean_differences)
            if event_mean_differences
            else None
        ),
        "event_mean_max": (
            max(event_mean_differences)
            if event_mean_differences
            else None
        ),
        "event_count": len(events),
        "unit": unit,
    }


def _aggregate_channel_quantitative_facts(
    channel_facts,
):
    facts = [
        item
        for item in (channel_facts or [])
        if isinstance(item, dict)
    ]

    means = [
        safe_float(item.get("mean_difference"))
        for item in facts
    ]
    means = [value for value in means if value is not None]

    peaks = [
        safe_float(item.get("peak_difference"))
        for item in facts
    ]
    peaks = [value for value in peaks if value is not None]

    event_mins = [
        safe_float(item.get("event_mean_min"))
        for item in facts
    ]
    event_mins = [value for value in event_mins if value is not None]

    event_maxs = [
        safe_float(item.get("event_mean_max"))
        for item in facts
    ]
    event_maxs = [value for value in event_maxs if value is not None]

    unit = next(
        (
            item.get("unit")
            for item in facts
            if item.get("unit")
        ),
        None,
    )

    peak_max_abs = (
        max(peaks, key=lambda value: abs(value))
        if peaks
        else None
    )

    return {
        "mean_difference_min": min(means) if means else None,
        "mean_difference_max": max(means) if means else None,
        "peak_difference_max_abs": peak_max_abs,
        "event_mean_min": min(event_mins) if event_mins else None,
        "event_mean_max": max(event_maxs) if event_maxs else None,
        "sample_count": len(facts),
        "unit": unit,
    }


def _format_signed_metric(
    value,
    unit,
):
    value = safe_float(value)

    if value is None:
        return None

    if unit == "percentage_points":
        return f"{value:+.1f} pp"

    if unit == "steering_input_units":
        return f"{value:+.1f} unidades de input de volante"

    if unit:
        return f"{value:+.1f} {unit}"

    return f"{value:+.1f}"


def _format_single_channel_quantitative_observation(
    channel_fact,
):
    if not isinstance(channel_fact, dict):
        return None

    description = channel_fact.get("description") or channel_fact.get("channel")
    quantitative = channel_fact.get("quantitative") or {}
    unit = quantitative.get("unit")
    direction = channel_fact.get("direction")

    if direction == "mixed":
        low = _format_signed_metric(
            quantitative.get("event_mean_min"),
            unit,
        )
        high = _format_signed_metric(
            quantitative.get("event_mean_max"),
            unit,
        )
        peak = _format_signed_metric(
            quantitative.get("peak_difference"),
            unit,
        )

        pieces = []
        if low and high:
            pieces.append(f"medias por evento entre {low} y {high}")
        if peak:
            pieces.append(f"pico de mayor magnitud {peak}")

        if pieces:
            return f"{description}: " + "; ".join(pieces)

        return None

    mean = _format_signed_metric(
        quantitative.get("mean_difference"),
        unit,
    )
    peak = _format_signed_metric(
        quantitative.get("peak_difference"),
        unit,
    )

    pieces = []
    if mean:
        pieces.append(f"promedio {mean}")
    if peak:
        pieces.append(f"pico {peak}")

    if not pieces:
        return None

    return f"{description}: " + "; ".join(pieces)


def _format_aggregate_quantitative_observation(
    repeated_difference,
):
    if not isinstance(repeated_difference, dict):
        return None

    description = repeated_difference.get("description") or repeated_difference.get("channel")
    quantitative = repeated_difference.get("quantitative") or {}
    unit = quantitative.get("unit")

    mean_min = safe_float(
        quantitative.get("mean_difference_min")
    )
    mean_max = safe_float(
        quantitative.get("mean_difference_max")
    )
    peak = quantitative.get("peak_difference_max_abs")

    pieces = []

    direction = repeated_difference.get("direction")

    if direction == "mixed_across_comparisons":
        event_min = _format_signed_metric(
            quantitative.get("event_mean_min"),
            unit,
        )
        event_max = _format_signed_metric(
            quantitative.get("event_mean_max"),
            unit,
        )
        if event_min and event_max:
            pieces.append(
                f"medias por evento entre {event_min} y {event_max}"
            )
    elif mean_min is not None and mean_max is not None:
        low = _format_signed_metric(mean_min, unit)
        high = _format_signed_metric(mean_max, unit)

        if low == high:
            pieces.append(f"promedio {low}")
        else:
            pieces.append(f"promedio entre {low} y {high}")
    else:
        event_min = _format_signed_metric(
            quantitative.get("event_mean_min"),
            unit,
        )
        event_max = _format_signed_metric(
            quantitative.get("event_mean_max"),
            unit,
        )
        if event_min and event_max:
            pieces.append(
                f"medias por evento entre {event_min} y {event_max}"
            )

    peak_text = _format_signed_metric(peak, unit)
    if peak_text:
        pieces.append(f"pico de mayor magnitud {peak_text}")

    if not pieces:
        return None

    return f"{description}: " + "; ".join(pieces)

def _episode_speed_context_facts(
    episode,
):
    concurrent = [
        item
        for item in (
            episode.get(
                "concurrent_speed_events",
                [],
            )
            or []
        )
        if isinstance(item, dict)
    ]

    speed_directions = sorted({
        str(item.get("direction"))
        for item in concurrent
        if item.get("direction")
    })

    propagations = [
        item
        for item in (
            episode.get(
                "speed_propagation",
                [],
            )
            or []
        )
        if isinstance(item, dict)
    ]

    propagation_statuses = sorted({
        str(item.get("status"))
        for item in propagations
        if item.get("status")
    })

    return {
        "speed_context_available":
            bool(
                concurrent
                or
                propagations
            ),

        "speed_directions":
            speed_directions,

        "propagation_statuses":
            propagation_statuses,
    }


def _priority_ranking_map(
    comparison_result,
):
    audit = comparison_result.get(
        "llm_validation_audit",
        {},
    )

    ranking = (
        audit.get(
            "priority_ranking",
            {},
        )
        if isinstance(audit, dict)
        else {}
    )

    rows = (
        ranking.get(
            "classifications",
            [],
        )
        if isinstance(ranking, dict)
        else []
    )

    result = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        episode_id = safe_int(
            row.get(
                "episode_id"
            )
        )

        if episode_id is None:
            continue

        result[episode_id] = {
            "classification":
                row.get(
                    "classification"
                ),

            "relative_priority_rank":
                safe_int(
                    row.get(
                        "relative_priority_rank"
                    )
                ),
        }

    return result


def _coaching_target_for_channel_direction(
    channel,
    direction,
):
    targets = {
        ("throttle", "higher_in_comparison_lap"):
            "reducir el acelerador hacia la referencia",
        ("throttle", "lower_in_comparison_lap"):
            "aumentar el acelerador hacia la referencia",
        ("brake", "higher_in_comparison_lap"):
            "reducir la aplicación del freno hacia la referencia",
        ("brake", "lower_in_comparison_lap"):
            "aumentar la aplicación del freno hacia la referencia",
        ("steering_magnitude", "higher_in_comparison_lap"):
            "reducir la magnitud de dirección/volante hacia la referencia",
        ("steering_magnitude", "lower_in_comparison_lap"):
            "aumentar la magnitud de dirección/volante hacia la referencia",
    }

    if (channel, direction) in targets:
        return targets[(channel, direction)]

    fallback = {
        "throttle":
            "replicar la secuencia y modulación del acelerador de la referencia",
        "brake":
            "replicar la secuencia de aplicación del freno de la referencia",
        "steering_magnitude":
            "replicar la evolución de la magnitud de dirección/volante de la referencia",
    }

    return fallback.get(
        channel,
        "acercar el input observado a la referencia",
    )



def _channel_event_distance_intervals(
    evidence,
):
    intervals = []

    if not isinstance(evidence, dict):
        return intervals

    for event in (
        evidence.get("events", [])
        or []
    ):
        if not isinstance(event, dict):
            continue

        start = safe_float(
            event.get(
                "start_distance_m"
            )
        )
        end = safe_float(
            event.get(
                "end_distance_m"
            )
        )

        if start is None or end is None:
            continue

        if end < start:
            start, end = end, start

        if end <= start:
            continue

        intervals.append(
            (start, end)
        )

    intervals.sort()
    return intervals


def _merge_distance_intervals(
    intervals,
):
    clean = sorted(
        [
            (float(start), float(end))
            for start, end in (
                intervals
                or []
            )
            if (
                _finite_number(start)
                and
                _finite_number(end)
                and
                float(end) > float(start)
            )
        ]
    )

    if not clean:
        return []

    merged = [
        [
            clean[0][0],
            clean[0][1],
        ]
    ]

    for start, end in clean[1:]:
        current = merged[-1]

        if start <= current[1]:
            current[1] = max(
                current[1],
                end,
            )
        else:
            merged.append(
                [start, end]
            )

    return [
        (start, end)
        for start, end in merged
    ]


def _interval_total_length(
    intervals,
):
    return sum(
        max(
            0.0,
            end - start,
        )
        for start, end in (
            intervals
            or []
        )
    )


def _interval_intersection_length(
    first,
    second,
):
    total = 0.0

    a = _merge_distance_intervals(
        first
    )
    b = _merge_distance_intervals(
        second
    )

    i = 0
    j = 0

    while (
        i < len(a)
        and
        j < len(b)
    ):
        start = max(
            a[i][0],
            b[j][0],
        )
        end = min(
            a[i][1],
            b[j][1],
        )

        if end > start:
            total += (
                end - start
            )

        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1

    return total


def _minimum_interval_gap(
    first,
    second,
):
    gaps = []

    for a0, a1 in (
        first
        or []
    ):
        for b0, b1 in (
            second
            or []
        ):
            if (
                a1 <= b0
            ):
                gaps.append(
                    b0 - a1
                )
            elif (
                b1 <= a0
            ):
                gaps.append(
                    a0 - b1
                )
            else:
                return 0.0

    if not gaps:
        return None

    return min(gaps)


def _brake_throttle_relation_from_channels(
    channels,
):
    by_channel = {
        str(item.get("channel")):
            item
        for item in (
            channels
            or []
        )
        if (
            isinstance(item, dict)
            and
            item.get("channel")
        )
    }

    brake = by_channel.get(
        "brake"
    )
    throttle = by_channel.get(
        "throttle"
    )

    if not brake or not throttle:
        return None

    brake_intervals = (
        _merge_distance_intervals(
            brake.get(
                "event_intervals_m",
                [],
            )
        )
    )
    throttle_intervals = (
        _merge_distance_intervals(
            throttle.get(
                "event_intervals_m",
                [],
            )
        )
    )

    if (
        not brake_intervals
        or
        not throttle_intervals
    ):
        return None

    overlap_m = (
        _interval_intersection_length(
            brake_intervals,
            throttle_intervals,
        )
    )

    brake_length_m = (
        _interval_total_length(
            brake_intervals
        )
    )
    throttle_length_m = (
        _interval_total_length(
            throttle_intervals
        )
    )

    relation = {
        "kind":
            None,
        "overlap_m":
            overlap_m,
        "gap_m":
            None,
        "brake_event_length_m":
            brake_length_m,
        "throttle_event_length_m":
            throttle_length_m,
        "brake_intervals_m":
            [
                [start, end]
                for start, end in brake_intervals
            ],
        "throttle_intervals_m":
            [
                [start, end]
                for start, end in throttle_intervals
            ],
    }

    if overlap_m > 1e-9:
        shorter_length = min(
            brake_length_m,
            throttle_length_m,
        )

        if (
            shorter_length > 0.0
            and
            overlap_m >= (
                0.95
                * shorter_length
            )
        ):
            relation["kind"] = (
                "substantial_overlap"
            )
        else:
            relation["kind"] = (
                "partial_overlap"
            )

        relation["gap_m"] = 0.0
        return relation

    brake_first_start = (
        brake_intervals[0][0]
    )
    brake_last_end = (
        brake_intervals[-1][1]
    )
    throttle_first_start = (
        throttle_intervals[0][0]
    )
    throttle_last_end = (
        throttle_intervals[-1][1]
    )

    if (
        brake_last_end
        <= throttle_first_start
    ):
        relation["kind"] = (
            "brake_then_throttle"
        )
        relation["gap_m"] = (
            throttle_first_start
            - brake_last_end
        )
        return relation

    if (
        throttle_last_end
        <= brake_first_start
    ):
        relation["kind"] = (
            "throttle_then_brake"
        )
        relation["gap_m"] = (
            brake_first_start
            - throttle_last_end
        )
        return relation

    relation["kind"] = (
        "interleaved_without_overlap"
    )
    relation["gap_m"] = (
        _minimum_interval_gap(
            brake_intervals,
            throttle_intervals,
        )
    )
    return relation


def _format_single_brake_throttle_relation(
    relation,
):
    if not isinstance(
        relation,
        dict,
    ):
        return None

    kind = relation.get(
        "kind"
    )
    overlap = safe_float(
        relation.get(
            "overlap_m"
        )
    )
    gap = safe_float(
        relation.get(
            "gap_m"
        )
    )

    if kind == "brake_then_throttle":
        if gap is not None:
            return (
                "freno primero y acelerador después, "
                f"sin solapamiento; separación aproximada {gap:.0f} m"
            )
        return (
            "freno primero y acelerador después, "
            "sin solapamiento"
        )

    if kind == "throttle_then_brake":
        if gap is not None:
            return (
                "acelerador primero y freno después, "
                f"sin solapamiento; separación aproximada {gap:.0f} m"
            )
        return (
            "acelerador primero y freno después, "
            "sin solapamiento"
        )

    if kind in (
        "partial_overlap",
        "substantial_overlap",
    ):
        if overlap is not None:
            return (
                "los eventos de freno y acelerador se solaparon "
                f"durante aproximadamente {overlap:.0f} m de recorrido"
            )
        return (
            "los eventos de freno y acelerador presentaron solapamiento"
        )

    if kind == "interleaved_without_overlap":
        return (
            "los eventos de freno y acelerador se alternaron "
            "dentro de la zona sin solapamiento directo"
        )

    return None


def _aggregate_region_brake_throttle_relation(
    component,
):
    rows = []

    for finding in (
        component
        or []
    ):
        relation = finding.get(
            "brake_throttle_relation"
        )

        if not isinstance(
            relation,
            dict,
        ):
            continue

        rows.append({
            "comparison":
                finding.get(
                    "comparison"
                ),
            **relation,
        })

    if not rows:
        return None

    comparisons = {
        str(item.get("comparison"))
        for item in rows
        if item.get("comparison")
    }

    kinds = sorted({
        str(item.get("kind"))
        for item in rows
        if item.get("kind")
    })

    gap_values = [
        safe_float(
            item.get(
                "gap_m"
            )
        )
        for item in rows
        if safe_float(
            item.get(
                "gap_m"
            )
        ) is not None
    ]

    overlap_values = [
        safe_float(
            item.get(
                "overlap_m"
            )
        )
        for item in rows
        if (
            safe_float(
                item.get(
                    "overlap_m"
                )
            )
            is not None
            and
            safe_float(
                item.get(
                    "overlap_m"
                )
            )
            > 0.0
        )
    ]

    result = {
        "comparison_count":
            len(comparisons),
        "kinds":
            kinds,
        "gap_min_m":
            min(gap_values)
            if gap_values
            else None,
        "gap_max_m":
            max(gap_values)
            if gap_values
            else None,
        "overlap_min_m":
            min(overlap_values)
            if overlap_values
            else None,
        "overlap_max_m":
            max(overlap_values)
            if overlap_values
            else None,
        "per_comparison":
            rows,
    }

    if len(kinds) == 1:
        result["kind"] = kinds[0]
    else:
        result["kind"] = (
            "mixed_across_comparisons"
        )

    return result


def _format_region_brake_throttle_relation(
    relation,
):
    if not isinstance(
        relation,
        dict,
    ):
        return None

    kind = relation.get(
        "kind"
    )
    count = safe_int(
        relation.get(
            "comparison_count"
        )
    ) or 0

    gap_min = safe_float(
        relation.get(
            "gap_min_m"
        )
    )
    gap_max = safe_float(
        relation.get(
            "gap_max_m"
        )
    )
    overlap_min = safe_float(
        relation.get(
            "overlap_min_m"
        )
    )
    overlap_max = safe_float(
        relation.get(
            "overlap_max_m"
        )
    )

    if kind == "brake_then_throttle":
        suffix = ""
        if (
            gap_min is not None
            and
            gap_max is not None
        ):
            if abs(
                gap_max
                - gap_min
            ) < 0.5:
                suffix = (
                    f"; separación aproximada {gap_min:.0f} m"
                )
            else:
                suffix = (
                    "; separación entre eventos de "
                    f"{gap_min:.0f} a {gap_max:.0f} m"
                )

        return (
            "se repitió la secuencia freno → acelerador "
            f"sin solapamiento en {count} comparaciones"
            + suffix
        )

    if kind == "throttle_then_brake":
        suffix = ""
        if (
            gap_min is not None
            and
            gap_max is not None
        ):
            if abs(
                gap_max
                - gap_min
            ) < 0.5:
                suffix = (
                    f"; separación aproximada {gap_min:.0f} m"
                )
            else:
                suffix = (
                    "; separación entre eventos de "
                    f"{gap_min:.0f} a {gap_max:.0f} m"
                )

        return (
            "se repitió la secuencia acelerador → freno "
            f"sin solapamiento en {count} comparaciones"
            + suffix
        )

    if kind in (
        "partial_overlap",
        "substantial_overlap",
    ):
        suffix = ""
        if (
            overlap_min is not None
            and
            overlap_max is not None
        ):
            if abs(
                overlap_max
                - overlap_min
            ) < 0.5:
                suffix = (
                    f"; solapamiento aproximado {overlap_min:.0f} m"
                )
            else:
                suffix = (
                    "; solapamiento observado entre "
                    f"{overlap_min:.0f} y {overlap_max:.0f} m"
                )

        return (
            "se repitió solapamiento de freno y acelerador "
            f"en {count} comparaciones"
            + suffix
        )

    if kind == "interleaved_without_overlap":
        return (
            "se repitió una secuencia alternada de freno y acelerador "
            f"sin solapamiento directo en {count} comparaciones"
        )

    if kind == "mixed_across_comparisons":
        return (
            "la relación entre freno y acelerador cambió entre comparaciones; "
            "no se trata como un patrón temporal repetido"
        )

    return None


def _finding_interval(finding):
    start = safe_float(
        finding.get("start_distance_m")
    )
    end = safe_float(
        finding.get("end_distance_m")
    )

    if start is None or end is None:
        return None

    if end < start:
        start, end = end, start

    return start, end


def _findings_share_spatial_region(
    first,
    second,
):
    """
    Agrupación descriptiva intra-sesión, NO matcher persistente.

    Dos episodios se consideran de la misma región sólo si tienen una
    superposición espacial material. Esto evita declarar un patrón global
    simplemente porque el mismo canal apareció en curvas distintas.

    No se usa distancia de centro ni un umbral de similitud aprendido.
    """
    interval_a = _finding_interval(first)
    interval_b = _finding_interval(second)

    if interval_a is None or interval_b is None:
        return False

    a0, a1 = interval_a
    b0, b1 = interval_b

    overlap = max(
        0.0,
        min(a1, b1) - max(a0, b0),
    )

    if overlap <= 0.0:
        return False

    len_a = max(a1 - a0, 1.0)
    len_b = max(b1 - b0, 1.0)

    # Exige al menos 20 % del episodio más corto, con tope de 20 m.
    # Es una regla conservadora de reporte; no se persiste como matcher.
    required_overlap = min(
        20.0,
        0.20 * min(len_a, len_b),
    )

    return overlap >= required_overlap


def _alpha_label(index):
    index = int(index)
    letters = ""

    while True:
        index, remainder = divmod(index, 26)
        letters = chr(ord("A") + remainder) + letters

        if index == 0:
            return letters

        index -= 1


def _build_priority_regions(
    priority_findings,
):
    findings = [
        item
        for item in priority_findings
        if _finding_interval(item) is not None
    ]

    count = len(findings)

    adjacency = {
        index: set()
        for index in range(count)
    }

    for left in range(count):
        for right in range(left + 1, count):
            if _findings_share_spatial_region(
                findings[left],
                findings[right],
            ):
                adjacency[left].add(right)
                adjacency[right].add(left)

    components = []
    visited = set()

    for root in range(count):
        if root in visited:
            continue

        stack = [root]
        component = []
        visited.add(root)

        while stack:
            current = stack.pop()
            component.append(
                findings[current]
            )

            for neighbour in sorted(
                adjacency[current]
            ):
                if neighbour in visited:
                    continue

                visited.add(neighbour)
                stack.append(neighbour)

        components.append(component)

    regions = []

    for component in components:
        starts = []
        ends = []
        comparisons = set()

        for finding in component:
            interval = _finding_interval(
                finding
            )

            if interval is not None:
                starts.append(interval[0])
                ends.append(interval[1])

            comparison = finding.get(
                "comparison"
            )

            if comparison:
                comparisons.add(
                    str(comparison)
                )

        channel_rows = {}

        for finding in component:
            comparison = str(
                finding.get("comparison")
            )

            for channel_fact in (
                finding.get("channels", [])
                or []
            ):
                channel = channel_fact.get(
                    "channel"
                )
                direction = (
                    channel_fact.get("direction")
                    or "unknown"
                )

                if not channel:
                    continue

                key = (
                    str(channel),
                    str(direction),
                )

                row = channel_rows.setdefault(
                    key,
                    {
                        "channel":
                            str(channel),
                        "direction":
                            str(direction),
                        "description":
                            channel_fact.get(
                                "description"
                            ),
                        "comparisons":
                            set(),
                        "episode_count":
                            0,
                        "quantitative_facts":
                            [],
                    },
                )

                row["comparisons"].add(
                    comparison
                )
                row["episode_count"] += 1

                quantitative = channel_fact.get(
                    "quantitative"
                )
                if isinstance(quantitative, dict):
                    row["quantitative_facts"].append(
                        quantitative
                    )

        repeated_differences = []

        channels_with_directional_repeat = set()

        for (
            channel,
            direction,
        ), row in channel_rows.items():
            comparison_count = len(
                row["comparisons"]
            )

            if comparison_count < 2:
                continue

            channels_with_directional_repeat.add(
                channel
            )

            repeated_differences.append({
                "channel":
                    channel,
                "direction":
                    direction,
                "description":
                    row.get(
                        "description"
                    ),
                "comparison_count":
                    comparison_count,
                "priority_episode_count":
                    row[
                        "episode_count"
                    ],
                "target":
                    _coaching_target_for_channel_direction(
                        channel,
                        direction,
                    ),
                "quantitative":
                    _aggregate_channel_quantitative_facts(
                        row.get(
                            "quantitative_facts",
                            [],
                        )
                    ),
            })

        channel_presence = {}

        for (
            channel,
            _direction,
        ), row in channel_rows.items():
            entry = channel_presence.setdefault(
                channel,
                {
                    "comparisons": set(),
                    "episode_count": 0,
                    "quantitative_facts": [],
                },
            )

            entry["comparisons"].update(
                row["comparisons"]
            )
            entry["episode_count"] += (
                row["episode_count"]
            )
            entry["quantitative_facts"].extend(
                row.get(
                    "quantitative_facts",
                    [],
                )
            )

        for channel, row in channel_presence.items():
            if channel in channels_with_directional_repeat:
                continue

            comparison_count = len(
                row["comparisons"]
            )

            if comparison_count < 2:
                continue

            description = {
                "throttle":
                    "modulación distinta del acelerador",
                "brake":
                    "aplicación distinta del freno",
                "steering_magnitude":
                    "magnitud distinta de dirección/volante",
            }.get(
                channel,
                str(channel),
            )

            repeated_differences.append({
                "channel":
                    channel,
                "direction":
                    "mixed_across_comparisons",
                "description":
                    description,
                "comparison_count":
                    comparison_count,
                "priority_episode_count":
                    row[
                        "episode_count"
                    ],
                "target":
                    _coaching_target_for_channel_direction(
                        channel,
                        "mixed",
                    ),
                "quantitative":
                    _aggregate_channel_quantitative_facts(
                        row.get(
                            "quantitative_facts",
                            [],
                        )
                    ),
            })

        repeated_differences.sort(
            key=lambda item: (
                -item[
                    "comparison_count"
                ],
                -item[
                    "priority_episode_count"
                ],
                item[
                    "description"
                ]
                or "",
            )
        )

        best_comparison_rank = min(
            (
                item.get(
                    "comparison_priority_rank"
                )
                if item.get(
                    "comparison_priority_rank"
                ) is not None
                else 999999
            )
            for item in component
        )

        best_episode_rank = min(
            (
                item.get(
                    "relative_priority_rank"
                )
                if item.get(
                    "relative_priority_rank"
                ) is not None
                else 999999
            )
            for item in component
        )

        max_action_loss = max(
            abs(
                safe_float(
                    item.get(
                        "action_time_loss_s"
                    )
                )
                or 0.0
            )
            for item in component
        )

        speed_directions = sorted({
            direction
            for item in component
            for direction in (
                item.get(
                    "speed_directions",
                    [],
                )
                or []
            )
        })

        propagation_statuses = sorted({
            status
            for item in component
            for status in (
                item.get(
                    "propagation_statuses",
                    [],
                )
                or []
            )
        })

        region_brake_throttle_relation = (
            _aggregate_region_brake_throttle_relation(
                component
            )
        )

        regions.append({
            "start_distance_m":
                min(starts)
                if starts
                else None,
            "end_distance_m":
                max(ends)
                if ends
                else None,
            "comparison_count":
                len(comparisons),
            "comparisons":
                sorted(comparisons),
            "priority_episode_count":
                len(component),
            "best_comparison_priority_rank":
                best_comparison_rank,
            "best_episode_priority_rank":
                best_episode_rank,
            "max_action_time_loss_s":
                max_action_loss,
            "repeated_differences":
                repeated_differences,
            "brake_throttle_relation":
                region_brake_throttle_relation,
            "speed_directions":
                speed_directions,
            "propagation_statuses":
                propagation_statuses,
            "findings":
                sorted(
                    component,
                    key=lambda item: (
                        item.get(
                            "comparison_priority_rank"
                        )
                        if item.get(
                            "comparison_priority_rank"
                        ) is not None
                        else 999999,
                        item.get(
                            "relative_priority_rank"
                        )
                        if item.get(
                            "relative_priority_rank"
                        ) is not None
                        else 999999,
                    ),
                ),
        })

    regions.sort(
        key=lambda item: (
            -(
                1
                if (
                    item["comparison_count"] >= 2
                    and
                    item["repeated_differences"]
                )
                else 0
            ),
            -item[
                "comparison_count"
            ],
            item[
                "best_comparison_priority_rank"
            ],
            item[
                "best_episode_priority_rank"
            ],
            -item[
                "max_action_time_loss_s"
            ],
            item[
                "start_distance_m"
            ]
            if item[
                "start_distance_m"
            ] is not None
            else 999999.0,
        )
    )

    for index, region in enumerate(
        regions
    ):
        region["region_label"] = (
            _alpha_label(index)
        )

    return regions


def _single_finding_plan_item(
    finding,
    label,
):
    targets = []

    for channel_fact in (
        finding.get("channels", [])
        or []
    ):
        channel = channel_fact.get(
            "channel"
        )
        direction = channel_fact.get(
            "direction"
        )

        if not channel:
            continue

        target = (
            _coaching_target_for_channel_direction(
                channel,
                direction,
            )
        )

        if target not in targets:
            targets.append(target)

    return {
        "plan_label":
            label,
        "kind":
            "single_priority_finding",
        "start_distance_m":
            finding.get(
                "start_distance_m"
            ),
        "end_distance_m":
            finding.get(
                "end_distance_m"
            ),
        "comparisons":
            [
                finding.get(
                    "comparison"
                )
            ],
        "comparison_count":
            1,
        "observed_differences":
            [
                item.get(
                    "description"
                )
                for item in (
                    finding.get(
                        "channels",
                        [],
                    )
                    or []
                )
                if item.get(
                    "description"
                )
            ],
        "targets":
            targets,
        "quantitative_observations":
            [
                text
                for text in (
                    _format_single_channel_quantitative_observation(
                        item
                    )
                    for item in (
                        finding.get(
                            "channels",
                            [],
                        )
                        or []
                    )
                )
                if text
            ],
        "temporal_relationships":
            [
                text
                for text in [
                    _format_single_brake_throttle_relation(
                        finding.get(
                            "brake_throttle_relation"
                        )
                    )
                ]
                if text
            ],
        "speed_directions":
            finding.get(
                "speed_directions",
                [],
            ),
        "propagation_statuses":
            finding.get(
                "propagation_statuses",
                [],
            ),
        "source_priority":
            {
                "comparison_priority_rank":
                    finding.get(
                        "comparison_priority_rank"
                    ),
                "episode_priority_rank":
                    finding.get(
                        "relative_priority_rank"
                    ),
            },
    }


def _build_next_stint_plan(
    priority_regions,
    priority_findings,
    max_items=3,
):
    plan = []
    consumed_findings = set()

    repeated_regions = [
        region
        for region in priority_regions
        if (
            region.get(
                "comparison_count",
                0,
            )
            >= 2
            and
            region.get(
                "repeated_differences"
            )
        )
    ]

    for region in repeated_regions:
        if len(plan) >= max_items:
            break

        label = _alpha_label(
            len(plan)
        )

        plan.append({
            "plan_label":
                label,
            "kind":
                "repeated_region",
            "start_distance_m":
                region.get(
                    "start_distance_m"
                ),
            "end_distance_m":
                region.get(
                    "end_distance_m"
                ),
            "comparisons":
                region.get(
                    "comparisons",
                    [],
                ),
            "comparison_count":
                region.get(
                    "comparison_count",
                    0,
                ),
            "observed_differences":
                [
                    item.get(
                        "description"
                    )
                    for item in (
                        region.get(
                            "repeated_differences",
                            [],
                        )
                        or []
                    )
                    if item.get(
                        "description"
                    )
                ],
            "targets":
                [
                    item.get(
                        "target"
                    )
                    for item in (
                        region.get(
                            "repeated_differences",
                            [],
                        )
                        or []
                    )
                    if item.get(
                        "target"
                    )
                ],
            "quantitative_observations":
                [
                    text
                    for text in (
                        _format_aggregate_quantitative_observation(
                            item
                        )
                        for item in (
                            region.get(
                                "repeated_differences",
                                [],
                            )
                            or []
                        )
                    )
                    if text
                ],
            "temporal_relationships":
                [
                    text
                    for text in [
                        _format_region_brake_throttle_relation(
                            region.get(
                                "brake_throttle_relation"
                            )
                        )
                    ]
                    if text
                ],
            "speed_directions":
                region.get(
                    "speed_directions",
                    [],
                ),
            "propagation_statuses":
                region.get(
                    "propagation_statuses",
                    [],
                ),
        })

        for finding in (
            region.get(
                "findings",
                [],
            )
            or []
        ):
            consumed_findings.add(
                (
                    finding.get(
                        "comparison"
                    ),
                    finding.get(
                        "episode_id"
                    ),
                )
            )

    for finding in priority_findings:
        if len(plan) >= max_items:
            break

        key = (
            finding.get(
                "comparison"
            ),
            finding.get(
                "episode_id"
            ),
        )

        if key in consumed_findings:
            continue

        plan.append(
            _single_finding_plan_item(
                finding,
                _alpha_label(
                    len(plan)
                ),
            )
        )

    return plan


def build_session_coaching_facts(
    valid_comparison_results,
):
    """
    Convierte comparaciones ya validadas en una ficha determinista.

    v3.8.17:
    - los hallazgos siguen siendo episodios PRIORITARIOS;
    - los patrones repetidos sólo se declaran si reaparecen en una región
      espacial compatible y en múltiples comparaciones;
    - Python construye un plan concreto para la próxima tanda;
    - Python distingue secuencia/solapamiento de freno y acelerador;
    - no se infiere causalidad ni se asignan nombres de curva/fase.
    """
    comparison_order = []
    priority_findings = []

    ordered_results = sorted(
        [
            item
            for item in valid_comparison_results
            if (
                isinstance(item, dict)
                and
                item.get("status") == "VALID"
            )
        ],
        key=lambda item: (
            safe_int(
                item.get(
                    "driver_analysis_priority_rank"
                )
            )
            if safe_int(
                item.get(
                    "driver_analysis_priority_rank"
                )
            ) is not None
            else 999999,
            abs(
                safe_float(
                    item.get(
                        "comparison_minus_reference_s"
                    )
                )
                or 0.0
            ),
        ),
    )

    for comparison in ordered_results:
        reference_lap = safe_int(
            comparison.get(
                "reference_lap"
            )
        )
        comparison_lap = safe_int(
            comparison.get(
                "comparison_lap"
            )
        )

        comparison_key = (
            f"{reference_lap}->{comparison_lap}"
            if (
                reference_lap is not None
                and
                comparison_lap is not None
            )
            else "comparison"
        )

        comparison_order.append({
            "reference_lap":
                reference_lap,
            "comparison_lap":
                comparison_lap,
            "comparison_minus_reference_s":
                safe_float(
                    comparison.get(
                        "comparison_minus_reference_s"
                    )
                ),
            "driver_analysis_priority_rank":
                safe_int(
                    comparison.get(
                        "driver_analysis_priority_rank"
                    )
                ),
        })

        ranking_map = (
            _priority_ranking_map(
                comparison
            )
        )

        episodes = [
            item
            for item in (
                comparison.get(
                    "episode_ground_truth",
                    [],
                )
                or []
            )
            if isinstance(item, dict)
        ]

        for episode in episodes:
            episode_id = safe_int(
                episode.get(
                    "episode_id"
                )
            )

            ranking = ranking_map.get(
                episode_id,
                {},
            )

            classification = (
                ranking.get(
                    "classification"
                )
            )

            if classification != "PRIORITARIO":
                continue

            channels = []

            evidence_by_channel = (
                episode.get(
                    "action_evidence_by_channel",
                    {},
                )
                or {}
            )

            for channel in (
                episode.get(
                    "action_channels",
                    [],
                )
                or []
            ):
                evidence = (
                    evidence_by_channel.get(
                        channel,
                        {},
                    )
                    if isinstance(
                        evidence_by_channel,
                        dict,
                    )
                    else {}
                )

                direction = (
                    _single_event_direction(
                        evidence
                    )
                )

                channels.append({
                    "channel":
                        channel,
                    "direction":
                        direction,
                    "description":
                        _channel_direction_coaching_label(
                            channel,
                            evidence,
                        ),
                    "quantitative":
                        _channel_quantitative_fact(
                            channel,
                            evidence,
                        ),
                    "event_intervals_m":
                        [
                            [start, end]
                            for start, end in (
                                _channel_event_distance_intervals(
                                    evidence
                                )
                            )
                        ],
                })

            brake_throttle_relation = (
                _brake_throttle_relation_from_channels(
                    channels
                )
            )

            speed_context = (
                _episode_speed_context_facts(
                    episode
                )
            )

            priority_findings.append({
                "comparison":
                    comparison_key,
                "reference_lap":
                    reference_lap,
                "comparison_lap":
                    comparison_lap,
                "comparison_minus_reference_s":
                    safe_float(
                        comparison.get(
                            "comparison_minus_reference_s"
                        )
                    ),
                "comparison_priority_rank":
                    safe_int(
                        comparison.get(
                            "driver_analysis_priority_rank"
                        )
                    ),
                "episode_id":
                    episode_id,
                "relative_priority_rank":
                    safe_int(
                        ranking.get(
                            "relative_priority_rank"
                        )
                    ),
                "classification":
                    classification,
                "start_distance_m":
                    safe_float(
                        episode.get(
                            "start_distance_m"
                        )
                    ),
                "end_distance_m":
                    safe_float(
                        episode.get(
                            "end_distance_m"
                        )
                    ),
                "action_time_loss_s":
                    safe_float(
                        episode.get(
                            "action_time_loss_s"
                        )
                    ),
                "evidence_strength":
                    episode.get(
                        "evidence_strength"
                    ),
                "channels":
                    channels,
                "brake_throttle_relation":
                    brake_throttle_relation,
                **speed_context,
            })

    priority_findings.sort(
        key=lambda item: (
            item.get(
                "comparison_priority_rank"
            )
            if item.get(
                "comparison_priority_rank"
            ) is not None
            else 999999,
            item.get(
                "relative_priority_rank"
            )
            if item.get(
                "relative_priority_rank"
            ) is not None
            else 999999,
            -abs(
                item.get(
                    "action_time_loss_s"
                )
                or 0.0
            ),
        )
    )

    priority_regions = (
        _build_priority_regions(
            priority_findings
        )
    )

    repeated_input_patterns = []

    for region in priority_regions:
        if (
            region.get(
                "comparison_count",
                0,
            )
            < 2
        ):
            continue

        for repeated in (
            region.get(
                "repeated_differences",
                [],
            )
            or []
        ):
            repeated_input_patterns.append({
                **repeated,
                "region_label":
                    region.get(
                        "region_label"
                    ),
                "start_distance_m":
                    region.get(
                        "start_distance_m"
                    ),
                "end_distance_m":
                    region.get(
                        "end_distance_m"
                    ),
            })

    repeated_input_patterns.sort(
        key=lambda item: (
            -item.get(
                "comparison_count",
                0,
            ),
            -item.get(
                "priority_episode_count",
                0,
            ),
            item.get(
                "start_distance_m"
            )
            if item.get(
                "start_distance_m"
            ) is not None
            else 999999.0,
            item.get(
                "description"
            )
            or "",
        )
    )

    next_stint_plan = (
        _build_next_stint_plan(
            priority_regions,
            priority_findings,
        )
    )

    return {
        "comparison_order":
            comparison_order,
        "priority_findings":
            priority_findings,
        "priority_regions":
            priority_regions,
        "repeated_input_patterns":
            repeated_input_patterns,
        "next_stint_plan":
            next_stint_plan,
        "priority_finding_count":
            len(
                priority_findings
            ),
    }

def _finding_text_for_llm(
    finding,
):
    channel_text = ", ".join(
        item.get(
            "description",
            "",
        )
        for item in (
            finding.get(
                "channels",
                [],
            )
            or []
        )
        if item.get(
            "description"
        )
    )

    speed_context = []

    speed_directions = set(
        finding.get(
            "speed_directions",
            [],
        )
        or []
    )

    if (
        "lower_in_comparison_lap"
        in speed_directions
    ):
        speed_context.append(
            "velocidad inferior a la referencia"
        )

    if (
        "higher_in_comparison_lap"
        in speed_directions
    ):
        speed_context.append(
            "velocidad superior a la referencia"
        )

    propagation_statuses = set(
        finding.get(
            "propagation_statuses",
            [],
        )
        or []
    )

    if (
        "continues_losing_time"
        in propagation_statuses
    ):
        speed_context.append(
            "el delta siguió empeorando después de la acción"
        )

    return {
        "comparison_priority_rank":
            finding.get(
                "comparison_priority_rank"
            ),

        "episode_priority_rank":
            finding.get(
                "relative_priority_rank"
            ),

        "observed_inputs":
            channel_text,

        "speed_context":
            speed_context,

        "evidence_strength":
            finding.get(
                "evidence_strength"
            ),
    }


def compact_session_coaching_facts_for_llm(
    session_coaching_facts,
):
    """
    El LLM global recibe el plan ya resuelto por Python.

    No recibe metros, segundos, números de vuelta ni IDs de episodio.
    Cada item lleva sólo una etiqueta alfabética y el target determinista.
    """
    plan = []

    for item in (
        session_coaching_facts.get(
            "next_stint_plan",
            [],
        )
        or []
    )[:3]:
        plan.append({
            "zone_label":
                item.get(
                    "plan_label"
                ),
            "kind":
                item.get(
                    "kind"
                ),
            "observed_differences":
                item.get(
                    "observed_differences",
                    [],
                ),
            "coaching_targets":
                item.get(
                    "targets",
                    [],
                ),
            "quantitative_evidence":
                item.get(
                    "quantitative_observations",
                    [],
                ),
            "input_sequence":
                item.get(
                    "temporal_relationships",
                    [],
                ),
            "repeated_across_multiple_comparisons":
                (
                    safe_int(
                        item.get(
                            "comparison_count"
                        )
                    )
                    or 0
                )
                >= 2,
            "speed_context":
                _render_speed_context_fact(
                    item
                ),
        })

    spatial_patterns = [
        {
            "zone_label":
                item.get(
                    "region_label"
                ),
            "description":
                item.get(
                    "description"
                ),
            "target":
                item.get(
                    "target"
                ),
            "quantitative_evidence":
                _format_aggregate_quantitative_observation(
                    item
                ),
            "repeated_in_same_region":
                True,
        }
        for item in (
            session_coaching_facts.get(
                "repeated_input_patterns",
                [],
            )
            or []
        )[:6]
    ]

    return {
        "next_stint_plan":
            plan,
        "spatially_repeated_input_patterns":
            spatial_patterns,
    }

def _render_speed_context_fact(
    finding,
):
    parts = []

    speed_directions = set(
        finding.get(
            "speed_directions",
            [],
        )
        or []
    )

    if (
        "lower_in_comparison_lap"
        in speed_directions
    ):
        parts.append(
            "velocidad inferior a la referencia"
        )

    if (
        "higher_in_comparison_lap"
        in speed_directions
    ):
        parts.append(
            "velocidad superior a la referencia"
        )

    statuses = set(
        finding.get(
            "propagation_statuses",
            [],
        )
        or []
    )

    if (
        "continues_losing_time"
        in statuses
    ):
        parts.append(
            "el delta siguió empeorando después de terminar la acción"
        )

    if not parts:
        return None

    return "; ".join(
        parts
    )


def _render_action_delta_fact(
    value,
):
    value = safe_float(
        value
    )

    if value is None:
        return "variación de delta N/D"

    if value >= 0:
        return (
            f"+{value:.4f} s de pérdida "
            "durante la acción"
        )

    return (
        f"{abs(value):.4f} s de ganancia "
        "durante la acción"
    )



def _render_deterministic_engineer_conclusion(
    session_coaching_facts,
):
    """
    Conclusión visible propiedad de Python.

    Siempre ancla el coaching a zona(s) métricas y, cuando la evidencia lo
    permite, incluye magnitudes concretas de los cambios de input. El LLM no
    puede degradar esta conclusión a una frase genérica.
    """
    plan = (
        session_coaching_facts.get(
            "next_stint_plan",
            [],
        )
        if isinstance(session_coaching_facts, dict)
        else []
    ) or []

    if not plan:
        return (
            "No hay una zona prioritaria con evidencia suficiente para "
            "formular un objetivo cuantificado en esta sesión."
        )

    sentences = []

    for index, item in enumerate(
        plan[:2]
    ):
        label = str(
            item.get("plan_label") or "?"
        )
        start_m = meters(
            item.get("start_distance_m")
        )
        end_m = meters(
            item.get("end_distance_m")
        )

        quantitative = [
            str(value)
            for value in (
                item.get(
                    "quantitative_observations",
                    [],
                )
                or []
            )
            if value
        ]

        targets = [
            str(value)
            for value in (
                item.get(
                    "targets",
                    [],
                )
                or []
            )
            if value
        ]

        if item.get("kind") == "repeated_region":
            basis = (
                f"patrón repetido en {item.get('comparison_count')} comparaciones"
            )
        else:
            basis = "hallazgo prioritario individual"

        details = ""
        if quantitative:
            details = (
                " Se observó "
                + "; ".join(quantitative[:3])
                + "."
            )
        else:
            observed = [
                str(value)
                for value in (
                    item.get(
                        "observed_differences",
                        [],
                    )
                    or []
                )
                if value
            ]
            if observed:
                details = (
                    " Se observó "
                    + ", ".join(observed[:3])
                    + "."
                )

        target_text = ""
        if targets:
            target_text = (
                " Objetivo: "
                + "; ".join(targets[:3])
                + "."
            )

        temporal = [
            str(value)
            for value in (
                item.get(
                    "temporal_relationships",
                    [],
                )
                or []
            )
            if value
        ]

        temporal_text = ""
        if temporal:
            temporal_text = (
                " Secuencia de inputs: "
                + "; ".join(temporal[:2])
                + "."
            )

        prefix = (
            "Prioridad principal"
            if index == 0
            else "Segunda prioridad"
        )

        sentences.append(
            f"{prefix}: Zona {label} ({start_m}–{end_m}), {basis}."
            + details
            + temporal_text
            + target_text
        )

    return " ".join(sentences)


# ============================================================
# PROMPT GLOBAL ESTRUCTURADO
# ============================================================

GLOBAL_SYSTEM_PROMPT = """
Sos un ingeniero de carrera redactando el cierre de una sesión.

Python ya resolvió:
- qué hallazgos son prioritarios;
- qué diferencias de input fueron observadas;
- cuáles se repiten en la MISMA región del circuito;
- qué objetivo relativo a la vuelta de referencia corresponde a cada zona.

No vuelvas a investigar ni a decidir qué ocurrió.
No generalices una diferencia local a todo el circuito.

Tu trabajo es redactar coaching claro a partir del plan de Python.

REGLAS:
- no agregues hechos, canales, causas ni conceptos que no estén en la ficha;
- no afirmes causalidad;
- no inventes contexto externo;
- no inventes nombres de curva, fase de curva, punto de frenada, ápice,
  trayectoria ideal, entrada, salida ni "curvas críticas";
- no escribas ninguna cifra;
- no escribas números de vuelta, metros, tiempos, porcentajes ni velocidades;
- podés usar las etiquetas alfabéticas "zona prioritaria A", "B", "C";
- no uses "analizar", "explorar", "evaluar", "monitorear", "investigar" o
  "estudiar" como recomendación principal;
- cada prioridad de próxima tanda debe corresponder a un item de
  next_stint_plan y conservar su etiqueta de zona;
- una diferencia observada puede ser una oportunidad de coaching aunque no
  sepamos si fue la causa de la pérdida;
- si no hay base para una hipótesis adicional, devolvé hypotheses vacío;
- las limitaciones deben ser breves y no dominar el informe.

Respondé únicamente JSON válido.
No Markdown.
No texto fuera del JSON.
"""


GLOBAL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "opportunities": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "minItems": 1,
            "maxItems": 4,
        },
        "repeated_observations": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "maxItems": 4,
        },
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "maxItems": 3,
        },
        "limitations": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "maxItems": 2,
        },
        "next_session_priorities": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "minItems": 1,
            "maxItems": 3,
        },
        "conclusion": {
            "type": "string",
        },
    },
    "required": [
        "opportunities",
        "repeated_observations",
        "hypotheses",
        "limitations",
        "next_session_priorities",
        "conclusion",
    ],
    "additionalProperties": False,
}


def build_global_prompt(
    metadata,
    valid_comparison_results,
    session_coaching_facts,
    correction_errors=None,
):
    coaching_payload = (
        compact_session_coaching_facts_for_llm(
            session_coaching_facts
        )
    )

    correction_block = ""

    if correction_errors:
        correction_block = f"""
RESPUESTA ANTERIOR RECHAZADA:

{compact_json(correction_kinds(correction_errors))}

Corregí únicamente esas categorías de error.
"""

    plan_labels = [
        str(
            item.get(
                "plan_label"
            )
        )
        for item in (
            session_coaching_facts.get(
                "next_stint_plan",
                [],
            )
            or []
        )[:3]
        if item.get(
            "plan_label"
        )
    ]

    labels_text = ", ".join(
        plan_labels
    )

    return f"""
Redactá el coaching final de esta sesión a partir de esta ficha determinista.

CIRCUITO:
{metadata.get("track")}

SESIÓN:
{metadata.get("session_type")}

FICHA DE COACHING VALIDADA POR PYTHON:

{compact_json(coaching_payload)}

ETIQUETAS DE ZONA DEL PLAN:
{labels_text}

OBJETIVO DE CADA CAMPO:

opportunities:
- resumí los focos del next_stint_plan;
- no generalices a todo el circuito;
- si mencionás una zona, usá sólo las etiquetas provistas por Python;
- describí el input que conviene acercar a la referencia;
- no inventes fase de curva ni nombre de curva.

repeated_observations:
- sólo declaralas si aparecen en spatially_repeated_input_patterns;
- deben quedar explícitamente como repeticiones de una misma zona;
- no conviertas una repetición local en un defecto global de conducción.

hypotheses:
- opcional;
- preferí lista vacía antes que una hipótesis genérica.

limitations:
- máximo dos;
- sólo límites realmente necesarios;
- no repitas varias veces que no puede probarse causalidad.

next_session_priorities:
- debe haber exactamente una prioridad por cada item de next_stint_plan;
- mantené el mismo orden;
- cada frase debe empezar con "Zona prioritaria X:", usando la etiqueta
  alfabética correspondiente;
- seguí el coaching_target entregado por Python;
- no inventes "entrada a curva", "salida", "punto de frenada", "ápice" ni
  "curva crítica".

conclusion:
- una conclusión corta;
- debe resumir el plan de zonas prioritarias;
- no debe pedir "más análisis".

No escribas cifras. Python renderizará por separado la evidencia exacta.

{correction_block}

Respondé únicamente JSON válido con las claves exigidas por el schema.
"""

# ============================================================
# VALIDAR RESPUESTA GLOBAL
# ============================================================

def validate_global_llm_response(
    response,
    valid_comparison_results=None,
    session_coaching_facts=None,
):
    errors = []

    expected_keys = {
        "opportunities",
        "repeated_observations",
        "hypotheses",
        "limitations",
        "next_session_priorities",
        "conclusion",
    }

    actual_keys = set(
        response.keys()
    )

    if actual_keys != expected_keys:
        missing = (
            expected_keys
            -
            actual_keys
        )

        extra = (
            actual_keys
            -
            expected_keys
        )

        if missing:
            errors.append(
                "Faltan claves globales: "
                + ", ".join(
                    sorted(missing)
                )
            )

        if extra:
            errors.append(
                "Sobran claves globales: "
                + ", ".join(
                    sorted(extra)
                )
            )

    source_episodes = []

    for result in (
        valid_comparison_results or []
    ):
        if not isinstance(result, dict):
            continue

        episodes = result.get(
            "episode_ground_truth",
            [],
        )

        if isinstance(episodes, list):
            source_episodes.extend(
                episode
                for episode in episodes
                if isinstance(episode, dict)
            )

    allowed_channels, speed_context_available = (
        grounding_context_from_episodes(
            source_episodes
        )
    )

    unsupported_phase = re.compile(
        r"\b("
        r"entrada\s+a\s+curva|"
        r"salida\s+de\s+curva|"
        r"curvas?\s+cr[ií]ticas?|"
        r"punto\s+de\s+frenada|"
        r"[aá]pice|"
        r"v[eé]rtice|"
        r"trail\s*brak(?:e|ing)|"
        r"fase\s+de\s+entrada|"
        r"fase\s+de\s+salida"
        r")\b",
        re.IGNORECASE,
    )

    for field in (
        "opportunities",
        "repeated_observations",
        "hypotheses",
        "limitations",
        "next_session_priorities",
    ):
        value = response.get(
            field
        )

        validate_text_list(
            value,
            field,
            errors,
        )

        validate_grounded_text_list(
            value,
            field,
            allowed_channels,
            speed_context_available,
            errors,
        )

        if isinstance(value, list):
            max_items = {
                "opportunities": 4,
                "repeated_observations": 4,
                "hypotheses": 3,
                "limitations": 2,
                "next_session_priorities": 3,
            }.get(field)

            if (
                max_items is not None
                and
                len(value) > max_items
            ):
                errors.append(
                    f"{field}: demasiados elementos; máximo {max_items}."
                )

            if field in (
                "opportunities",
                "next_session_priorities",
            ):
                vague_start = re.compile(
                    r"^\s*(analizar|explorar|evaluar|monitorear|investigar|estudiar)\b",
                    re.IGNORECASE,
                )

                for index, item in enumerate(value):
                    if not isinstance(item, str):
                        continue

                    if vague_start.search(item):
                        errors.append(
                            f"{field}[{index}]: recomendación demasiado vaga."
                        )

                    if unsupported_phase.search(item):
                        errors.append(
                            f"{field}[{index}]: inventa una fase/nombre de curva no suministrado por Python."
                        )

    plan = (
        session_coaching_facts.get(
            "next_stint_plan",
            [],
        )
        if isinstance(
            session_coaching_facts,
            dict,
        )
        else []
    )

    priorities = response.get(
        "next_session_priorities"
    )

    if (
        isinstance(priorities, list)
        and
        plan
    ):
        expected_plan = plan[:3]

        if len(priorities) != len(
            expected_plan
        ):
            errors.append(
                "next_session_priorities: debe contener exactamente una prioridad por zona del plan Python."
            )
        else:
            for index, (
                item,
                plan_item,
            ) in enumerate(
                zip(
                    priorities,
                    expected_plan,
                )
            ):
                label = str(
                    plan_item.get(
                        "plan_label",
                        "",
                    )
                ).strip()

                if not label:
                    continue

                expected_prefix = (
                    f"zona prioritaria {label}:"
                ).lower()

                if (
                    not isinstance(
                        item,
                        str,
                    )
                    or
                    not item.strip().lower().startswith(
                        expected_prefix
                    )
                ):
                    errors.append(
                        f"next_session_priorities[{index}]: debe comenzar con 'Zona prioritaria {label}:'."
                    )

    conclusion = response.get(
        "conclusion"
    )

    if not isinstance(
        conclusion,
        str,
    ):
        errors.append(
            "conclusion global debe ser texto."
        )
    else:
        if text_contains_forbidden_numeric_content(
            conclusion
        ):
            errors.append(
                "conclusion global contiene cifras."
            )

        validate_grounded_text(
            conclusion,
            "conclusion global",
            allowed_channels,
            speed_context_available,
            errors,
        )

        if unsupported_phase.search(
            conclusion
        ):
            errors.append(
                "conclusion global inventa una fase/nombre de curva no suministrado por Python."
            )

    return errors


def get_validated_global_response(
    metadata,
    valid_comparison_results,
    session_coaching_facts,
    output_dir,
):
    errors = None
    last_raw = None

    for attempt in range(
        1,
        MAX_LLM_VALIDATION_ATTEMPTS + 1,
    ):
        prompt = build_global_prompt(
            metadata,
            valid_comparison_results,
            session_coaching_facts,
            correction_errors=errors,
        )

        if SAVE_GLOBAL_PROMPT:
            prompt_path = os.path.join(
                output_dir,
                f"global_prompt_attempt_{attempt}.txt",
            )

            save_text(
                prompt_path,
                prompt,
            )

        raw = ollama_chat(
            GLOBAL_SYSTEM_PROMPT,
            prompt,
            temperature=0.0,
            seed=3815,
            format_schema=GLOBAL_RESPONSE_SCHEMA,
        )

        last_raw = raw

        try:
            parsed = parse_llm_json(
                raw
            )
        except Exception as exc:
            errors = [
                str(exc)
            ]
            continue

        errors = validate_global_llm_response(
            parsed,
            valid_comparison_results,
            session_coaching_facts,
        )

        if not errors:
            return {
                "status":
                    "VALID",

                "attempts":
                    attempt,

                "response":
                    parsed,

                "validation_errors":
                    [],
            }

    rejected_path = os.path.join(
        output_dir,
        "global_REJECTED.txt",
    )

    save_text(
        rejected_path,
        (
            "VALIDATION ERRORS\n"
            "=================\n"
            + "\n".join(
                errors or []
            )
            + "\n\nRAW RESPONSE\n"
            "============\n"
            + (
                last_raw
                if isinstance(
                    last_raw,
                    str,
                )
                else repr(last_raw)
            )
        ),
    )

    return {
        "status":
            "REJECTED",

        "attempts":
            MAX_LLM_VALIDATION_ATTEMPTS,

        "response":
            None,

        "validation_errors":
            errors or [],
    }


# ============================================================
# RENDER GLOBAL DETERMINISTA
# ============================================================

def render_global_analysis(
    metadata,
    comparison_results,
    session_coaching_facts,
    global_structured,
):
    lines = []

    lines.append(
        "# ANÁLISIS FINAL DE LA SESIÓN"
    )

    lines.append("")
    lines.append(
        "## Resultado general"
    )
    lines.append("")

    lap_times = metadata.get(
        "lap_times_s",
        {},
    )

    reference_lap = safe_int(
        metadata.get(
            "reference_lap"
        )
    )

    reference_time = safe_float(
        lap_times.get(
            str(reference_lap)
        )
    )

    if reference_lap is not None:
        if reference_time is not None:
            lines.append(
                f"- Mejor vuelta: vuelta "
                f"{reference_lap} — "
                f"{plain_seconds(reference_time)}"
            )
        else:
            lines.append(
                f"- Vuelta de referencia: "
                f"{reference_lap}"
            )

    if lap_times:
        lines.append(
            "- Tiempos disponibles:"
        )

        for lap, duration in sorted(
            (
                (
                    safe_int(lap),
                    safe_float(duration),
                )
                for lap, duration
                in lap_times.items()
            ),
            key=lambda item: (
                item[0]
                if item[0] is not None
                else 999999
            ),
        ):
            if (
                lap is None
                or
                duration is None
            ):
                continue

            lines.append(
                f"  - Vuelta {lap}: "
                f"{plain_seconds(duration)}"
            )

    if comparison_results:
        lines.append(
            "- Comparaciones analizadas:"
        )

        for result in comparison_results:
            lines.append(
                f"  - "
                f"{result['reference_lap']} -> "
                f"{result['comparison_lap']}: "
                f"{signed_seconds(result['comparison_minus_reference_s'])}"
            )

    lines.append("")
    lines.append(
        "## Evidencia priorizada por Python"
    )
    lines.append("")

    findings = (
        session_coaching_facts.get(
            "priority_findings",
            [],
        )
        or []
    )

    if findings:
        for index, finding in enumerate(
            findings[:6],
            start=1,
        ):
            channels = ", ".join(
                item.get(
                    "description",
                    "",
                )
                for item in (
                    finding.get(
                        "channels",
                        [],
                    )
                    or []
                )
                if item.get(
                    "description"
                )
            )

            start = meters(
                finding.get(
                    "start_distance_m"
                )
            )
            end = meters(
                finding.get(
                    "end_distance_m"
                )
            )

            lines.append(
                f"{index}. "
                f"{finding.get('comparison')} · "
                f"Episodio #{finding.get('episode_id')} · "
                f"{start}–{end} · "
                f"{_render_action_delta_fact(finding.get('action_time_loss_s'))}"
            )

            if channels:
                lines.append(
                    f"   - Diferencia de input observada: {channels}."
                )

            quantitative_lines = [
                text
                for text in (
                    _format_single_channel_quantitative_observation(
                        item
                    )
                    for item in (
                        finding.get(
                            "channels",
                            [],
                        )
                        or []
                    )
                )
                if text
            ]

            if quantitative_lines:
                lines.append(
                    "   - Magnitud observada respecto de la referencia: "
                    + "; ".join(quantitative_lines)
                    + "."
                )

            brake_throttle_text = (
                _format_single_brake_throttle_relation(
                    finding.get(
                        "brake_throttle_relation"
                    )
                )
            )

            if brake_throttle_text:
                lines.append(
                    "   - Secuencia freno/acelerador: "
                    + brake_throttle_text
                    + "."
                )

            speed_fact = (
                _render_speed_context_fact(
                    finding
                )
            )

            if speed_fact:
                lines.append(
                    f"   - Contexto de velocidad: {speed_fact}."
                )

            evidence_strength = (
                finding.get(
                    "evidence_strength"
                )
            )

            if evidence_strength:
                lines.append(
                    f"   - Evidencia: {evidence_strength}; "
                    "clasificación: PRIORITARIO."
                )
    else:
        lines.append(
            "- No hay episodios PRIORITARIOS validados."
        )

    lines.append("")
    lines.append(
        "## Patrones repetidos en la misma región"
    )
    lines.append("")

    patterns = (
        session_coaching_facts.get(
            "repeated_input_patterns",
            [],
        )
        or []
    )

    if patterns:
        for item in patterns[:6]:
            start_m = meters(
                item.get(
                    "start_distance_m"
                )
            )
            end_m = meters(
                item.get(
                    "end_distance_m"
                )
            )
            label = item.get(
                "region_label"
            )

            quantitative = (
                _format_aggregate_quantitative_observation(
                    item
                )
            )

            suffix = (
                f" Magnitud: {quantitative}."
                if quantitative
                else ""
            )

            lines.append(
                f"- Zona {label} · {start_m}–{end_m}: "
                f"{item.get('description')} se repitió en "
                f"{item.get('comparison_count')} comparación(es) "
                "dentro de esa misma región."
                + suffix
            )
    else:
        lines.append(
            "- No se detectó una misma diferencia de input repetida espacialmente en múltiples comparaciones."
        )

    lines.append("")
    lines.append(
        "## Plan concreto para la próxima tanda (Python)"
    )
    lines.append("")

    plan = (
        session_coaching_facts.get(
            "next_stint_plan",
            [],
        )
        or []
    )

    if plan:
        for index, item in enumerate(
            plan,
            start=1,
        ):
            start_m = meters(
                item.get(
                    "start_distance_m"
                )
            )
            end_m = meters(
                item.get(
                    "end_distance_m"
                )
            )
            label = item.get(
                "plan_label"
            )
            comparisons = ", ".join(
                str(value)
                for value in (
                    item.get(
                        "comparisons",
                        [],
                    )
                    or []
                )
                if value
            )

            kind = item.get(
                "kind"
            )

            if kind == "repeated_region":
                basis = (
                    f"patrón repetido en "
                    f"{item.get('comparison_count')} comparaciones"
                )
            else:
                basis = (
                    "hallazgo prioritario de mayor utilidad "
                    "que no formó un patrón espacial repetido"
                )

            lines.append(
                f"{index}. Zona prioritaria {label} · "
                f"{start_m}–{end_m} · {basis}."
            )

            observed = [
                value
                for value in (
                    item.get(
                        "observed_differences",
                        [],
                    )
                    or []
                )
                if value
            ]

            if observed:
                lines.append(
                    "   - Se observó: "
                    + ", ".join(
                        observed
                    )
                    + "."
                )

            quantitative = [
                value
                for value in (
                    item.get(
                        "quantitative_observations",
                        [],
                    )
                    or []
                )
                if value
            ]

            if quantitative:
                lines.append(
                    "   - Valores respecto de la referencia: "
                    + "; ".join(quantitative)
                    + "."
                )

            temporal_relationships = [
                value
                for value in (
                    item.get(
                        "temporal_relationships",
                        [],
                    )
                    or []
                )
                if value
            ]

            if temporal_relationships:
                lines.append(
                    "   - Secuencia de inputs: "
                    + "; ".join(temporal_relationships)
                    + "."
                )

            targets = [
                value
                for value in (
                    item.get(
                        "targets",
                        [],
                    )
                    or []
                )
                if value
            ]

            if targets:
                lines.append(
                    "   - Objetivo respecto de la referencia: "
                    + "; ".join(
                        targets
                    )
                    + "."
                )

            speed_fact = (
                _render_speed_context_fact(
                    item
                )
            )

            if speed_fact:
                lines.append(
                    f"   - Contexto: {speed_fact}."
                )

            if comparisons:
                lines.append(
                    f"   - Evidencia proveniente de: {comparisons}."
                )
    else:
        lines.append(
            "- No hay un plan determinista disponible para esta sesión."
        )

    lines.append("")
    lines.append(
        "## Principales oportunidades de mejora"
    )
    lines.append("")

    opportunities = global_structured[
        "opportunities"
    ]

    if opportunities:
        for index, item in enumerate(
            opportunities,
            start=1,
        ):
            lines.append(
                f"{index}. {item}"
            )
    else:
        lines.append(
            "- No se identificaron oportunidades adicionales."
        )

    lines.append("")
    lines.append(
        "## Prioridades para la próxima tanda"
    )
    lines.append("")

    priorities = global_structured[
        "next_session_priorities"
    ]

    if priorities:
        for index, item in enumerate(
            priorities,
            start=1,
        ):
            lines.append(
                f"{index}. {item}"
            )
    else:
        lines.append(
            "- Sin prioridades adicionales."
        )

    repeated = global_structured[
        "repeated_observations"
    ]

    if repeated:
        lines.append("")
        lines.append(
            "## Lectura cualitativa de los patrones"
        )
        lines.append("")

        lines.extend(
            f"- {item}"
            for item in repeated
        )

    hypotheses = global_structured[
        "hypotheses"
    ]

    if hypotheses:
        lines.append("")
        lines.append(
            "## Hipótesis prudentes"
        )
        lines.append("")

        lines.extend(
            f"- {item}"
            for item in hypotheses
        )

    limitations = global_structured[
        "limitations"
    ]

    if limitations:
        lines.append("")
        lines.append(
            "## Límites del análisis"
        )
        lines.append("")

        lines.extend(
            f"- {item}"
            for item in limitations[:2]
        )

    lines.append("")
    lines.append(
        "## Conclusión del ingeniero"
    )
    lines.append("")

    lines.append(
        _render_deterministic_engineer_conclusion(
            session_coaching_facts
        )
    )

    return "\n".join(
        lines
    )


# ============================================================
# GUARDAR TEXTO
# ============================================================

def save_text(
    path,
    content,
):
    os.makedirs(
        os.path.dirname(path),
        exist_ok=True,
    )

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:
        file.write(
            content
        )


# ============================================================
# GUARDAR RESULTADO
# ============================================================

def save_result(
    input_path,
    metadata,
    comparison_results,
    session_coaching_facts,
    global_structured,
    global_analysis,
):
    stem = os.path.splitext(
        os.path.basename(
            input_path
        )
    )[0]

    output_dir = os.path.join(
        os.path.dirname(
            input_path
        ),
        stem + "_llm",
    )

    os.makedirs(
        output_dir,
        exist_ok=True,
    )

    output_path = os.path.join(
        output_dir,
        stem + "_llm_analysis.json",
    )

    result = {
        "metadata": {
            "llm_analysis_version":
                "3.8.17",

            "source_json":
                input_path,

            "source_analysis_version":
                metadata.get(
                    "analysis_version"
                ),

            "track":
                metadata.get(
                    "track"
                ),

            "session_type":
                metadata.get(
                    "session_type"
                ),

            "timestamp_utc":
                metadata.get(
                    "timestamp_utc"
                ),

            "reference_lap":
                metadata.get(
                    "reference_lap"
                ),

            "model":
                MODEL_NAME,

            "context":
                CONTEXT_SIZE,

            "temperature":
                TEMPERATURE,

            "structured_validation":
                "PASS",

            "factual_grounding_validation":
                "PASS",

            "analysis_timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat(),
        },

        "comparisons":
            comparison_results,

        "session_coaching_facts":
            session_coaching_facts,

        "global_structured":
            global_structured,

        "global_analysis":
            global_analysis,
    }

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            result,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return (
        output_path,
        output_dir,
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print_header(
        "RACE ENGINEER - LLM ANALYSIS v3.8.17"
    )

    input_path = find_json_file()

    data = load_json(
        input_path
    )

    metadata, raw_comparisons = (
        validate_data_model(
            data
        )
    )

    lap_times = validate_lap_times(
        data,
        metadata,
        raw_comparisons,
    )

    dataset = build_llm_dataset(
        data,
        lap_times,
    )

    metadata = dataset[
        "metadata"
    ]

    comparisons = dataset[
        "comparisons"
    ]

    if not comparisons:
        raise RuntimeError(
            "El JSON no contiene comparaciones."
        )

    stem = os.path.splitext(
        os.path.basename(
            input_path
        )
    )[0]

    output_dir = os.path.join(
        os.path.dirname(
            input_path
        ),
        stem + "_llm",
    )

    os.makedirs(
        output_dir,
        exist_ok=True,
    )

    print()

    print(
        f"Modelo: {MODEL_NAME}"
    )

    print(
        f"Contexto: {CONTEXT_SIZE}"
    )

    print(
        f"Temperatura: {TEMPERATURE}"
    )

    print()

    print(
        "Arquitectura v3.8.17:"
    )

    print(
        "Python = hechos + estructura + validación + render"
    )

    print(
        "LLM = interpretación aislada + ranking comparativo + coaching final\nPython fallback = descripción factual mínima si el texto LLM no logra grounded tras reintentos"
    )

    print()

    comparison_results = []

    for comparison_index, comparison in enumerate(
        comparisons,
        start=1,
    ):
        print_header(
            f"COMPARACIÓN {comparison_index}"
        )

        reference_lap = comparison[
            "reference_lap"
        ]

        comparison_lap = comparison[
            "comparison_lap"
        ]

        episode_catalog = build_episode_catalog(
            comparison
        )

        print(
            f"Comparación: "
            f"{reference_lap} -> "
            f"{comparison_lap}"
        )

        print(
            f"Tiempo A: "
            f"{comparison['reference_time_s']}"
        )

        print(
            f"Tiempo B: "
            f"{comparison['comparison_time_s']}"
        )

        print(
            f"Delta real: "
            f"{comparison['comparison_minus_reference_s']}"
        )

        print(
            f"Episodios esperados: "
            f"{len(episode_catalog)}"
        )

        if not episode_catalog:
            raise RuntimeError(
                "No hay driver_action_episode disponibles "
                f"para {reference_lap} -> {comparison_lap}. "
                "La v3.8.17 requiere analyze_telemetry v3.8 "
                "con episodios primarios."
            )

        print()

        print(
            "Solicitando interpretación aislada + ranking comparativo v3.8.17..."
        )

        validated = (
            get_validated_comparison_response(
                metadata,
                comparison,
                episode_catalog,
                output_dir,
            )
        )

        if validated[
            "status"
        ] != "VALID":
            print_header(
                "LLM RESPONSE REJECTED"
            )

            print(
                f"Comparación "
                f"{reference_lap} -> "
                f"{comparison_lap}"
            )

            for error in validated[
                "validation_errors"
            ]:
                print(
                    f"  - {error}"
                )

            raise RuntimeError(
                "LLM_STRUCTURED_VALIDATION_FAILED. "
                "La respuesta no se guardó como análisis válido."
            )

        structured = validated[
            "response"
        ]

        rendered = (
            render_comparison_analysis(
                comparison,
                episode_catalog,
                structured,
            )
        )

        print(
            f"Respuesta validada en "
            f"{validated['attempts']} intento(s)."
        )

        comparison_result = {
            "status":
                "VALID",

            "validation_attempts":
                validated[
                    "attempts"
                ],

            "llm_validation_audit":
                validated.get(
                    "audit",
                    {},
                ),

            "ground_truth": {
                "reference_lap":
                    reference_lap,

                "comparison_lap":
                    comparison_lap,

                "reference_time_s":
                    comparison[
                        "reference_time_s"
                    ],

                "comparison_time_s":
                    comparison[
                        "comparison_time_s"
                    ],

                "comparison_minus_reference_s":
                    comparison[
                        "comparison_minus_reference_s"
                    ],
            },

            "reference_lap":
                reference_lap,

            "comparison_lap":
                comparison_lap,

            "reference_time_s":
                comparison[
                    "reference_time_s"
                ],

            "comparison_time_s":
                comparison[
                    "comparison_time_s"
                ],

            "comparison_minus_reference_s":
                comparison[
                    "comparison_minus_reference_s"
                ],

            "driver_analysis_priority":
                comparison.get(
                    "driver_analysis_priority"
                ),

            "driver_analysis_priority_rank":
                comparison.get(
                    "driver_analysis_priority_rank"
                ),

            "driver_action_episode_count":
                len(
                    episode_catalog
                ),

            "episode_ground_truth":
                episode_catalog,

            "llm_structured":
                structured,

            "analysis":
                rendered,
        }

        comparison_results.append(
            comparison_result
        )

    print_header(
        "SÍNTESIS GLOBAL"
    )

    session_coaching_facts = (
        build_session_coaching_facts(
            comparison_results
        )
    )

    print(
        "Agregación determinista de coaching: "
        f"{session_coaching_facts['priority_finding_count']} "
        "hallazgo(s) prioritario(s)."
    )

    print(
        "Solicitando síntesis de coaching estructurada..."
    )

    global_validated = (
        get_validated_global_response(
            metadata,
            comparison_results,
            session_coaching_facts,
            output_dir,
        )
    )

    if global_validated[
        "status"
    ] != "VALID":
        print_header(
            "GLOBAL RESPONSE REJECTED"
        )

        for error in global_validated[
            "validation_errors"
        ]:
            print(
                f"  - {error}"
            )

        raise RuntimeError(
            "GLOBAL_LLM_STRUCTURED_VALIDATION_FAILED. "
            "La síntesis global no se guardó como válida."
        )

    global_structured = (
        global_validated[
            "response"
        ]
    )

    global_analysis = (
        render_global_analysis(
            metadata,
            comparison_results,
            session_coaching_facts,
            global_structured,
        )
    )

    output_path, _ = save_result(
        input_path,
        metadata,
        comparison_results,
        session_coaching_facts,
        global_structured,
        global_analysis,
    )

    print()

    print_header(
        "ANÁLISIS FINAL"
    )

    print(
        global_analysis
    )

    print()

    print_header(
        "RESULTADO GUARDADO"
    )

    print(
        output_path
    )

    print()

    print_header(
        "ANALYSIS COMPLETE"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
