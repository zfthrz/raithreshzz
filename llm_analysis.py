import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


# ============================================================
# RACE ENGINEER - LLM ANALYSIS v3.8.2
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

        "format":
            "json",

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
# SYSTEM PROMPT v3.8.2
# ============================================================

SYSTEM_PROMPT = """
Sos un ingeniero de carrera especializado en telemetría
de simuladores.

Python ya calculó y validó TODOS los datos objetivos.

Tu tarea es EXCLUSIVAMENTE cualitativa:

- clasificar episodios;
- interpretar relaciones entre canales;
- formular hipótesis prudentes;
- proponer recomendaciones específicas.

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

Describí primero la relación objetiva y después, si corresponde,
formulá una hipótesis.

============================================================
HIPÓTESIS MECÁNICAS
============================================================

No infieras automáticamente:

- pérdida de potencia;
- problema de motor;
- problema de transmisión;
- fallo de frenos;
- aerodinámica;
- gestión de energía.

Una variación de RPM por sí sola no demuestra un problema
de potencia.

============================================================
CLASIFICACIÓN OBLIGATORIA
============================================================

Debés devolver EXACTAMENTE un objeto por cada episode_id
recibido.

Clasificaciones permitidas:

- PRIORITARIO
- SECUNDARIO
- NO_ACCIONABLE

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


def compact_episode_for_llm(episode):
    """
    Conserva evidencia objetiva suficiente para interpretar,
    pero deja claro que Python es dueño de los números.
    """

    return {
        "episode_id":
            episode["episode_id"],

        "python_rank":
            episode.get(
                "global_rank"
            )
            or
            episode.get(
                "rank"
            )
            or
            episode["episode_id"],

        "start_distance_m":
            episode.get(
                "start_distance_m"
            ),

        "end_distance_m":
            episode.get(
                "end_distance_m"
            ),

        "length_m":
            episode.get(
                "length_m"
            ),

        "action_time_loss_s":
            episode.get(
                "action_time_loss_s"
            ),

        "evidence_strength":
            episode.get(
                "evidence_strength"
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
            episode.get(
                "speed_propagation"
            ),

        "supporting_loss_clusters":
            episode.get(
                "supporting_loss_clusters",
                [],
            ),
    }


# ============================================================
# PROMPT DE COMPARACIÓN v3.8.2
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
- ningún texto libre puede contener cifras.
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
        elif text_contains_forbidden_numeric_content(
            interpretation
        ):
            errors.append(
                f"Episodio {episode_id}: "
                "interpretation contiene cifras."
            )

        hypotheses = assessment.get(
            "hypotheses"
        )

        validate_text_list(
            hypotheses,
            f"Episodio {episode_id}.hypotheses",
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
        elif text_contains_forbidden_numeric_content(
            recommendation
        ):
            errors.append(
                f"Episodio {episode_id}: "
                "recommendation contiene cifras."
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

    validate_text_list(
        response.get(
            "comparison_observations"
        ),
        "comparison_observations",
        errors,
    )

    validate_text_list(
        response.get(
            "limitations"
        ),
        "limitations",
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
    elif text_contains_forbidden_numeric_content(
        conclusion
    ):
        errors.append(
            "conclusion contiene cifras."
        )

    return errors


# ============================================================
# LLAMADA ESTRUCTURADA POR COMPARACIÓN
# ============================================================

def get_validated_comparison_response(
    metadata,
    comparison,
    episode_catalog,
    output_dir,
):
    last_raw = None
    errors = None

    for attempt in range(
        1,
        MAX_LLM_VALIDATION_ATTEMPTS + 1,
    ):
        prompt = build_comparison_prompt(
            metadata,
            comparison,
            episode_catalog,
            correction_errors=errors,
        )

        reference_lap = (
            comparison[
                "reference_lap"
            ]
        )

        comparison_lap = (
            comparison[
                "comparison_lap"
            ]
        )

        if SAVE_COMPARISON_PROMPTS:
            prompt_path = os.path.join(
                output_dir,
                (
                    f"comparison_"
                    f"{reference_lap}_"
                    f"{comparison_lap}_"
                    f"prompt_attempt_{attempt}.txt"
                ),
            )

            save_text(
                prompt_path,
                prompt,
            )

        raw = ollama_chat(
            SYSTEM_PROMPT,
            prompt,
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
            print(
                f"  Respuesta estructurada rechazada "
                f"(intento {attempt}): {errors[0]}"
            )
            continue

        errors = (
            validate_comparison_llm_response(
                parsed,
                episode_catalog,
            )
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

        print(
            f"  Respuesta estructurada rechazada "
            f"(intento {attempt})."
        )

        for error in errors:
            print(
                f"    - {error}"
            )

    rejected_path = os.path.join(
        output_dir,
        (
            f"comparison_"
            f"{comparison['reference_lap']}_"
            f"{comparison['comparison_lap']}_"
            f"REJECTED.txt"
        ),
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
# PROMPT GLOBAL ESTRUCTURADO
# ============================================================

GLOBAL_SYSTEM_PROMPT = """
Sos un ingeniero de carrera.

Python proporcionará hechos objetivos y evaluaciones
cualitativas ya validadas de comparaciones individuales.

Tu tarea es sintetizar cualitativamente la sesión.

NO escribas ninguna cifra.

No escribas tiempos, distancias, porcentajes, velocidades,
RPM ni números de vuelta.

Python agregará todos esos datos al informe final.

Respondé únicamente JSON válido.

No Markdown.
No texto fuera del JSON.

No inventes patrones repetidos.

Si sólo existe una comparación válida, indicá cualitativamente
que no hay evidencia suficiente para afirmar patrones
recurrentes.

No inventes causas mecánicas.

No presentes hipótesis como hechos.
"""


def build_global_prompt(
    metadata,
    valid_comparison_results,
    correction_errors=None,
):
    qualitative_payload = []

    for result in valid_comparison_results:
        structured = result[
            "llm_structured"
        ]

        qualitative_payload.append({
            "priority":
                result.get(
                    "driver_analysis_priority"
                ),

            "episode_assessments":
                structured[
                    "episode_assessments"
                ],

            "comparison_observations":
                structured[
                    "comparison_observations"
                ],

            "limitations":
                structured[
                    "limitations"
                ],

            "conclusion":
                structured[
                    "conclusion"
                ],
        })

    schema = {
        "opportunities": [
            "oportunidad cualitativa sin cifras"
        ],
        "repeated_observations": [
            "observación o aclaración sobre ausencia de patrón"
        ],
        "hypotheses": [
            "hipótesis prudente sin cifras"
        ],
        "limitations": [
            "limitación cualitativa sin cifras"
        ],
        "next_session_priorities": [
            "prioridad concreta sin cifras"
        ],
        "conclusion":
            "síntesis cualitativa sin cifras",
    }

    correction_block = ""

    if correction_errors:
        correction_block = f"""
RESPUESTA ANTERIOR RECHAZADA:

{compact_json(correction_errors)}

Corregí esos errores.
"""

    return f"""
Sintetizá esta sesión.

CIRCUITO:
{metadata.get("track")}

SESIÓN:
{metadata.get("session_type")}

Cantidad de comparaciones válidas:
{len(valid_comparison_results)}

EVALUACIONES CUALITATIVAS:

{compact_json(qualitative_payload)}

CONTRATO JSON:

{compact_json(schema)}

Claves exactas:

- opportunities
- repeated_observations
- hypotheses
- limitations
- next_session_priorities
- conclusion

Todos los campos salvo conclusion son listas de texto.

Ningún texto puede contener cifras.

{correction_block}

Respondé únicamente JSON válido.
"""


# ============================================================
# VALIDAR RESPUESTA GLOBAL
# ============================================================

def validate_global_llm_response(
    response,
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

    for field in (
        "opportunities",
        "repeated_observations",
        "hypotheses",
        "limitations",
        "next_session_priorities",
    ):
        validate_text_list(
            response.get(
                field
            ),
            field,
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
            "conclusion global debe ser texto."
        )
    elif text_contains_forbidden_numeric_content(
        conclusion
    ):
        errors.append(
            "conclusion global contiene cifras."
        )

    return errors


def get_validated_global_response(
    metadata,
    valid_comparison_results,
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
            parsed
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
        "## Observaciones repetidas"
    )
    lines.append("")

    repeated = global_structured[
        "repeated_observations"
    ]

    if repeated:
        lines.extend(
            f"- {item}"
            for item in repeated
        )
    else:
        lines.append(
            "- No hay evidencia suficiente para "
            "establecer patrones repetidos."
        )

    lines.append("")
    lines.append(
        "## Hipótesis con mayor respaldo"
    )
    lines.append("")

    hypotheses = global_structured[
        "hypotheses"
    ]

    if hypotheses:
        lines.extend(
            f"- {item}"
            for item in hypotheses
        )
    else:
        lines.append(
            "- No se formularon hipótesis adicionales."
        )

    lines.append("")
    lines.append(
        "## Qué no puede determinarse"
    )
    lines.append("")

    limitations = global_structured[
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

    lines.append("")
    lines.append(
        "## Conclusión del ingeniero"
    )
    lines.append("")

    lines.append(
        global_structured[
            "conclusion"
        ]
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
                "3.8.2",

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

            "analysis_timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat(),
        },

        "comparisons":
            comparison_results,

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
        "RACE ENGINEER - LLM ANALYSIS v3.8.2"
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
        "Arquitectura v3.8.2:"
    )

    print(
        "Python = hechos + estructura + validación + render"
    )

    print(
        "LLM = clasificación + interpretación cualitativa"
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
                "La v3.8.2 requiere analyze_telemetry v3.8 "
                "con episodios primarios."
            )

        print()

        print(
            "Solicitando interpretación estructurada..."
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

    print(
        "Solicitando síntesis cualitativa estructurada..."
    )

    global_validated = (
        get_validated_global_response(
            metadata,
            comparison_results,
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
            global_structured,
        )
    )

    output_path, _ = save_result(
        input_path,
        metadata,
        comparison_results,
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
