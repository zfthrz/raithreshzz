import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


# ============================================================
# RACE ENGINEER - LLM ANALYSIS v3.8.1
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
# - NO recalcula prioridades
# - NO vuelve a detectar zonas
# - NO suma eventos
# - NO interpreta speed_propagation como acción
# - interpreta los episodios ya construidos por Python
#
# Una llamada a Ollama por comparación.
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

TIMEOUT_SECONDS = 600

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

        "options": {
            "temperature":
                TEMPERATURE,

            "num_ctx":
                CONTEXT_SIZE,
        },
    }

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

    try:

        with urllib.request.urlopen(
            request,
            timeout=TIMEOUT_SECONDS,
        ) as response:

            raw = response.read()

    except urllib.error.URLError as exc:

        raise RuntimeError(
            "No se pudo conectar con Ollama.\n"
            f"URL: {OLLAMA_URL}\n"
            f"Error: {exc}"
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
# SYSTEM PROMPT v3.8
# ============================================================

SYSTEM_PROMPT = """
Sos un ingeniero de carrera especializado en telemetría
de simuladores.

Estás interpretando datos calculados previamente por Python.

============================================================
REGLA DE AUTORIDAD DE DATOS
============================================================

Python es la ÚNICA fuente autoritativa para:

- número de vuelta;
- tiempo absoluto de vuelta;
- delta total de vuelta;
- distancias;
- límites de episodios;
- ranking de episodios;
- action_time_loss_s;
- canales detectados;
- valores de telemetría.

Cuando el prompt contenga un bloque llamado GROUND_TRUTH,
sus valores deben copiarse EXACTAMENTE.

NO reemplaces:

- lap_time_A;
- lap_time_B;
- total_lap_delta_s;

por tiempos internos de episodios, zonas, clusters o eventos.

Un action_time_loss_s NO es un tiempo de vuelta.
Un delta_start_s NO es un tiempo de vuelta.
Un delta_end_s NO es un tiempo de vuelta.

============================================================
MODELO DE DATOS
============================================================

- Todas las vueltas pertenecen al MISMO VEHÍCULO.
- La vuelta de referencia es A.
- La vuelta comparada es B.
- Delta positivo = B perdió tiempo.
- Delta negativo = B ganó tiempo.

============================================================
ARQUITECTURA v3.8.1
============================================================

Python ya determinó:

- tiempos de vuelta;
- delta total;
- zonas;
- loss clusters;
- eventos persistentes;
- driver_action_episode;
- speed_propagation;
- ranking de prioridades.

NO recalcules ni modifiques esos resultados.

La unidad primaria de interpretación es:

    driver_action_episode

Un driver_action_episode se construye solamente a partir de
diferencias persistentes de:

- throttle;
- brake;
- steering_magnitude.

La velocidad NO se usa para unir acciones del piloto.

speed_propagation es una diferencia de velocidad que persiste
después de una acción.

Puede ser consecuencia de una acción anterior.

NO la conviertas automáticamente en:

- nueva acción;
- nuevo error;
- nueva causa.

============================================================
CAUSALIDAD
============================================================

action_time_loss_s significa:

    cuánto cambió el delta mientras el episodio estuvo activo.

NO significa:

    cuánto tiempo causó exactamente esa acción.

Forma correcta:

    "Mientras B utilizó menos acelerador que A,
    el delta aumentó 0.25 s."

Forma incorrecta:

    "El menor acelerador causó una pérdida de 0.25 s."

EVITÁ expresiones causales fuertes como:

- "se debe a";
- "provocó";
- "generó";
- "causó";
- "es consecuencia de";

salvo que explícitamente las presentes como hipótesis.

Usá preferentemente:

- "coincide con";
- "ocurre mientras";
- "es compatible con";
- "podría contribuir";
- "los datos sugieren";
- "no puede confirmarse causalidad".

============================================================
ETIQUETAS DE CONDUCCIÓN
============================================================

NO uses automáticamente términos como:

- frenado insuficiente;
- frenado excesivo;
- frenada tardía;
- frenada temprana;
- aceleración prematura;
- mala salida;
- mala trayectoria;
- inestabilidad;
- subviraje;
- sobreviraje.

Primero describí el HECHO:

    "B utiliza 15 puntos porcentuales menos de freno."

Luego, si corresponde:

    "Esto podría ser compatible con una diferencia
    en la estrategia de frenado."

============================================================
HIPÓTESIS MECÁNICAS
============================================================

No infieras automáticamente:

- pérdida de potencia;
- motor fuera de potencia óptima;
- problema de transmisión;
- fallo de frenos;
- problema aerodinámico;
- gestión de energía;
- avería mecánica.

Una reducción de RPM durante frenado, por sí sola,
NO es evidencia de pérdida de potencia.

============================================================
CLASIFICACIÓN OBLIGATORIA
============================================================

Debés evaluar TODOS los driver_action_episode suministrados.

Cada episodio debe recibir exactamente una clasificación:

- PRIORITARIO
- SECUNDARIO
- NO_ACCIONABLE

No omitas episodios.

La clasificación NO cambia el ranking calculado por Python.

Desarrollá en detalle solamente los PRIORITARIOS y,
si aportan información, los SECUNDARIOS.

Para NO_ACCIONABLE indicá brevemente por qué no merece
una recomendación concreta.

============================================================
PATRONES
============================================================

No llames "patrón repetido" a algo observado en una sola
comparación o un solo episodio.

Para afirmar un patrón recurrente debe existir evidencia
en múltiples comparaciones prioritarias o múltiples episodios
independientes comparables.

============================================================
HECHO / INTERPRETACIÓN / HIPÓTESIS
============================================================

Separá siempre:

HECHO:
dato calculado directamente por Python.

INTERPRETACIÓN:
lectura razonable respaldada por datos.

HIPÓTESIS:
explicación posible no confirmada.

============================================================
PROHIBICIONES
============================================================

NO:

- inventes números;
- inventes curvas;
- inventes sectores;
- inventes eventos;
- sumes tiempos de eventos internos;
- sumes episodios solapados;
- reconstruyas los límites de episodios;
- reordenes prioridades;
- presentes speed_propagation como acción;
- confundas pérdida de un episodio con delta total de vuelta.

Respondé en español.

Sé técnico, concreto y orientado al piloto.
"""


# ============================================================
# PROMPT POR COMPARACIÓN
# ============================================================

def build_comparison_prompt(
    metadata,
    comparison,
):
    reference_lap = comparison["reference_lap"]
    comparison_lap = comparison["comparison_lap"]

    objective = comparison["objective_analysis"]

    driver_episodes = objective[
        "driver_action_episode_ranking"
    ]

    legacy_episodes = objective[
        "legacy_loss_episode_ranking"
    ]

    loss_ranking = objective[
        "loss_ranking"
    ]

    analysis_mode = comparison[
        "analysis_mode"
    ]

    ground_truth = {
        "lap_A_reference":
            reference_lap,

        "lap_B_comparison":
            comparison_lap,

        "lap_time_A_s":
            safe_float(
                comparison.get(
                    "reference_time_s"
                )
            ),

        "lap_time_B_s":
            safe_float(
                comparison.get(
                    "comparison_time_s"
                )
            ),

        "total_lap_delta_B_minus_A_s":
            safe_float(
                comparison.get(
                    "comparison_minus_reference_s"
                )
            ),

        "comparison_distance_m":
            safe_float(
                comparison.get(
                    "distance_m"
                )
            ),
    }

    if driver_episodes:

        primary_data = {
            "driver_action_episode_count":
                len(driver_episodes),

            "driver_action_episode_ranking":
                driver_episodes,

            "loss_ranking_context":
                loss_ranking,

            "objective_summary":
                objective.get(
                    "summary",
                    {},
                ),
        }

        mode_instruction = """
FUENTE PRIMARIA:
driver_action_episode_ranking.

Debés clasificar TODOS los episodios suministrados.

No omitas ninguno.

La cantidad declarada por Python debe coincidir con la
cantidad de episodios listados en tu clasificación.

Después de clasificarlos, desarrollá solamente los episodios
PRIORITARIOS y los SECUNDARIOS que aporten información útil.
"""

    else:

        primary_data = {
            "driver_action_episode_count":
                0,

            "legacy_loss_episode_ranking":
                legacy_episodes,

            "loss_ranking_context":
                loss_ranking,

            "objective_summary":
                objective.get(
                    "summary",
                    {},
                ),
        }

        mode_instruction = """
No existe driver_action_episode_ranking v3.8.

Usá loss_episode_ranking como fallback.

Indicá explícitamente que la capacidad causal del análisis
es menor en este modo.
"""

    return f"""
Analizá esta comparación de dos vueltas del MISMO VEHÍCULO.

============================================================
GROUND_TRUTH
============================================================

{compact_json(ground_truth)}

Estos valores son AUTORITATIVOS.

En "Resultado general" debés copiar exactamente:

- Tiempo referencia = lap_time_A_s
- Tiempo comparación = lap_time_B_s
- Delta total = total_lap_delta_B_minus_A_s

NO uses action_time_loss_s, delta_start_s o delta_end_s como
tiempos absolutos o como delta total.

============================================================
CONTEXTO
============================================================

CIRCUITO:
{metadata.get("track")}

SESIÓN:
{metadata.get("session_type")}

PRIORIDAD PYTHON:
{comparison.get("driver_analysis_priority")}

RANK DE PRIORIDAD:
{comparison.get("driver_analysis_priority_rank")}

MODO:
{analysis_mode}

VALIDACIÓN TEMPORAL:
{compact_json(comparison.get("temporal_validation", {}))}

{mode_instruction}

============================================================
DATOS OBJETIVOS
============================================================

{compact_json(primary_data)}

============================================================
REGLAS
============================================================

1. No modifiques el ranking.
2. No reconstruyas zonas ni episodios.
3. No sumes tiempos de eventos.
4. No conviertas speed_propagation en acción del piloto.
5. action_time_loss_s no es el delta total de vuelta.
6. Describí primero diferencias objetivas.
7. No uses "frenado insuficiente", "aceleración prematura",
   "mala trayectoria", etc. como HECHO.
8. No deduzcas pérdida de potencia a partir de RPM.
9. No inventes nombres de curvas.
10. No declares patrones recurrentes con una sola comparación.
11. Si no puede establecerse causalidad, escribí
    explícitamente "causalidad no confirmada".

============================================================
FORMATO OBLIGATORIO
============================================================

# Comparación {reference_lap} -> {comparison_lap}

## Resultado general

- Tiempo referencia: [COPIAR lap_time_A_s]
- Tiempo comparación: [COPIAR lap_time_B_s]
- Delta total: [COPIAR total_lap_delta_B_minus_A_s]
- Evaluación general:

## Clasificación de TODOS los episodios

Usá exactamente una línea por episodio:

- Episodio #N — CLASIFICACIÓN — distancia — action_time_loss_s — canales

Las únicas clasificaciones válidas son:

PRIORITARIO
SECUNDARIO
NO_ACCIONABLE

No omitas ningún episodio.

## Episodios prioritarios

Para cada PRIORITARIO:

### Episodio #N — distancia

**Impacto observado**
- Durante el episodio el delta cambió ...
- No afirmar que esa acción causó exactamente ese tiempo.

**Hechos**
- ...

**Velocidad concurrente / propagación**
- ...

**Interpretación**
- ...

**Hipótesis**
- ...
- causalidad confirmada/no confirmada.

**Recomendación para el piloto**
- Debe ser específica y derivarse de los hechos.

## Episodios secundarios

- ...

## Episodios no accionables

- ...

## Observaciones de conducción

No usar el término "patrón repetido" salvo que exista
evidencia repetida suficiente.

## Qué no puede determinarse

- ...

## Prioridades

1.
2.
3.

## Conclusión

...
"""


# ============================================================
# PROMPT GLOBAL
# ============================================================

def build_global_prompt(
    metadata,
    comparison_summaries,
):
    ground_truth_comparisons = [
        {
            "reference_lap":
                item["reference_lap"],

            "comparison_lap":
                item["comparison_lap"],

            "lap_time_A_s":
                safe_float(
                    item["reference_time_s"]
                ),

            "lap_time_B_s":
                safe_float(
                    item["comparison_time_s"]
                ),

            "total_lap_delta_B_minus_A_s":
                safe_float(
                    item["delta_s"]
                ),

            "driver_analysis_priority":
                item[
                    "driver_analysis_priority"
                ],

            "driver_analysis_priority_rank":
                item[
                    "driver_analysis_priority_rank"
                ],
        }
        for item in comparison_summaries
    ]

    interpretation_payload = [
        {
            "reference_lap":
                item["reference_lap"],

            "comparison_lap":
                item["comparison_lap"],

            "analysis":
                item["analysis"],
        }
        for item in comparison_summaries
    ]

    return f"""
Realizá la síntesis final de una sesión de telemetría.

============================================================
GROUND_TRUTH DE LA SESIÓN
============================================================

CIRCUITO:
{metadata.get("track")}

SESIÓN:
{metadata.get("session_type")}

VUELTA DE REFERENCIA:
{metadata.get("reference_lap")}

TIEMPOS ABSOLUTOS:
{compact_json(metadata.get("lap_times_s", {}))}

COMPARACIONES AUTORITATIVAS:
{compact_json(ground_truth_comparisons)}

VALIDACIÓN TEMPORAL:
{metadata.get("temporal_validation_status")}

VALIDACIÓN OBJETIVA:
{metadata.get("objective_analysis_validation")}

Los tiempos y deltas anteriores son la ÚNICA fuente
autorizada para escribir:

- mejor vuelta;
- tiempos de vuelta;
- diferencias temporales totales.

NO extraigas esos números desde el texto de los análisis
individuales.

============================================================
INTERPRETACIONES DE LAS COMPARACIONES
============================================================

{compact_json(interpretation_payload)}

============================================================
REGLAS
============================================================

- Python ya determinó la prioridad. No la reordenes.
- No confundas action_time_loss_s con delta total.
- No conviertas speed_propagation en nueva acción.
- No inventes curvas o causas mecánicas.
- No presentes hipótesis como hechos.
- No digas "patrón repetido" si solo existe una comparación.
- Si una observación aparece una sola vez, llamala
  "observación", no "tendencia" ni "patrón".
- Una caída de RPM durante frenado no implica pérdida
  de potencia.
- Conservá el lenguaje causal prudente:
  "coincide con", "podría contribuir", "es compatible con".

============================================================
FORMATO
============================================================

# ANÁLISIS FINAL DE LA SESIÓN

## Resultado general

- Mejor vuelta:
- Tiempos disponibles:
- Comparaciones prioritarias:
- Deltas totales:

Todos esos números deben provenir EXCLUSIVAMENTE de
GROUND_TRUTH.

## Principales oportunidades de mejora

1.
2.
3.

## Observaciones repetidas

Si no hay evidencia repetida suficiente, escribir:

"No hay suficientes comparaciones para establecer
patrones repetidos."

## Episodios más importantes

- ...

## Hipótesis con mayor respaldo

- ...

## Qué no puede determinarse

- ...

## Prioridades para la próxima tanda

1.
2.
3.

## Conclusión del ingeniero

...
"""


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
                "3.8.1",

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

            "analysis_timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat(),
        },

        "comparisons":
            comparison_results,

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
        "RACE ENGINEER - LLM ANALYSIS v3.8.1"
    )

    # ========================================================
    # JSON
    # ========================================================

    input_path = find_json_file()

    data = load_json(
        input_path
    )

    metadata, raw_comparisons = (
        validate_data_model(
            data
        )
    )

    # ========================================================
    # TIEMPOS
    # ========================================================

    lap_times = validate_lap_times(
        data,
        metadata,
        raw_comparisons,
    )

    # ========================================================
    # DATASET
    # ========================================================

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

    # ========================================================
    # OUTPUT DIR
    # ========================================================

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

    # ========================================================
    # INFORMACIÓN
    # ========================================================

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
        "Arquitectura v3.8.1:"
    )

    print(
        "Python = detección + ranking + estructura"
    )

    print(
        "LLM = interpretación"
    )

    print()

    print(
        "Unidad primaria:"
    )

    print(
        "driver_action_episode"
    )

    # ========================================================
    # COMPARACIONES
    # ========================================================

    comparison_results = []

    comparison_summaries = []

    for comparison_index, comparison in enumerate(
        comparisons,
        start=1,
    ):

        reference_lap = comparison[
            "reference_lap"
        ]

        comparison_lap = comparison[
            "comparison_lap"
        ]

        print_header(
            f"COMPARACIÓN {comparison_index}"
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
            f"Prioridad Python: "
            f"{comparison.get('driver_analysis_priority')}"
        )

        print(
            f"Rank prioridad: "
            f"{comparison.get('driver_analysis_priority_rank')}"
        )

        episodes = (
            comparison[
                "objective_analysis"
            ][
                "driver_action_episode_ranking"
            ]
        )

        print(
            f"Driver action episodes: "
            f"{len(episodes)}"
        )

        print(
            f"Modo: "
            f"{comparison['analysis_mode']}"
        )

        print()

        print(
            "Analizando comparación..."
        )

        prompt = build_comparison_prompt(
            metadata,
            comparison,
        )

        if SAVE_COMPARISON_PROMPTS:

            prompt_path = os.path.join(
                output_dir,
                (
                    f"comparison_"
                    f"{reference_lap}_"
                    f"{comparison_lap}_"
                    f"prompt.txt"
                ),
            )

            save_text(
                prompt_path,
                prompt,
            )

        try:

            analysis = ollama_chat(
                SYSTEM_PROMPT,
                prompt,
            )

        except Exception as exc:

            print(
                f"ERROR Ollama: {exc}"
            )

            analysis = (
                "ERROR DURANTE EL ANÁLISIS "
                "DE ESTA COMPARACIÓN:\n"
                f"{exc}"
            )

        print(
            "Comparación analizada."
        )

        result = {
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

            "analysis_mode":
                comparison[
                    "analysis_mode"
                ],

            "driver_action_episode_count":
                len(episodes),

            "analysis":
                analysis,
        }

        comparison_results.append(
            result
        )

        comparison_summaries.append({
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

            "delta_s":
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

            "analysis":
                analysis,
        })

    # ========================================================
    # ANÁLISIS GLOBAL
    # ========================================================

    print_header(
        "SÍNTESIS GLOBAL"
    )

    print(
        "Generando análisis final..."
    )

    global_prompt = build_global_prompt(
        metadata,
        comparison_summaries,
    )

    if SAVE_GLOBAL_PROMPT:

        global_prompt_path = os.path.join(
            output_dir,
            "llm_prompt.txt",
        )

        save_text(
            global_prompt_path,
            global_prompt,
        )

        print()

        print(
            "Prompt guardado en:"
        )

        print(
            global_prompt_path
        )

    global_analysis = ollama_chat(
        SYSTEM_PROMPT,
        global_prompt,
    )

    # ========================================================
    # GUARDAR
    # ========================================================

    output_path, _ = save_result(
        input_path,
        metadata,
        comparison_results,
        global_analysis,
    )

    # ========================================================
    # MOSTRAR
    # ========================================================

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
