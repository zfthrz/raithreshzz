import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone

from runtime_paths import llm_debug_dir, llm_result_dir
from coaching_precision import (
    enrich_patterns_with_precision,
    enrich_plan_items_with_precision,
    enrich_plan_items_with_coaching_sequence,
    enrich_cues_with_deterministic_priority,
    enrich_plan_with_p9_presentation_metadata,
    build_p10_plan_presentation,
    build_p11_plan_focus,
    render_track_reference_section,
)


# ============================================================
# RACE ENGINEER - LLM ANALYSIS v3.10.8.5.4 / DeepSeek provisional v1
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
# Una llamada a DeepSeek API por episodio.
# Una llamada comparativa para clasificar prioridades.
# Una llamada de resumen por comparación.
# Una llamada final para sintetizar la sesión.
#
# ============================================================


# ============================================================
# CONFIGURACIÓN
# ============================================================

DEEPSEEK_URL = os.environ.get(
    "DEEPSEEK_API_URL",
    "https://api.deepseek.com/chat/completions",
)

# Modelo provisional por defecto. Puede cambiarse sin editar el archivo:
#   export DEEPSEEK_MODEL=deepseek-v4-pro
MODEL_NAME = os.environ.get(
    "DEEPSEEK_MODEL",
    "deepseek-v4-pro",
)

DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"

DEEPSEEK_PRICING_USD_PER_MILLION = {
    # Pricing supplied for this experiment.
    "deepseek-v4-flash": {
        "input_cache_hit": 0.0028,
        "input_cache_miss": 0.14,
        "output": 0.28,
    },
    "deepseek-v4-pro": {
        "input_cache_hit": 0.003625,
        "input_cache_miss": 0.435,
        "output": 0.87,
    },
}

DEEPSEEK_USAGE = {
    "http_request_count": 0,
    "usage_response_count": 0,
    "prompt_tokens": 0,
    "prompt_cache_hit_tokens": 0,
    "prompt_cache_miss_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
}


def reset_deepseek_usage():
    for key in DEEPSEEK_USAGE:
        DEEPSEEK_USAGE[key] = 0


def _usage_int(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, value)


def _first_usage_int(usage, *keys):
    if not isinstance(usage, dict):
        return None
    for key in keys:
        value = _usage_int(usage.get(key))
        if value is not None:
            return value
    return None


def record_deepseek_usage(usage):
    """
    Acumula el `usage` devuelto por DeepSeek para TODAS las respuestas
    HTTP válidas, incluidos retries de generación.

    Si DeepSeek no devuelve desglose hit/miss, todo el input desconocido se
    cobra como cache miss para que la estimación no sea optimista.
    """
    if not isinstance(usage, dict):
        return

    prompt = _first_usage_int(
        usage,
        "prompt_tokens",
        "input_tokens",
    ) or 0

    completion = _first_usage_int(
        usage,
        "completion_tokens",
        "output_tokens",
    ) or 0

    total = _first_usage_int(
        usage,
        "total_tokens",
    )
    if total is None:
        total = prompt + completion

    cache_hit = _first_usage_int(
        usage,
        "prompt_cache_hit_tokens",
        "cache_hit_tokens",
        "input_cache_hit_tokens",
    )

    cache_miss = _first_usage_int(
        usage,
        "prompt_cache_miss_tokens",
        "cache_miss_tokens",
        "input_cache_miss_tokens",
    )

    # Reconstruct missing side conservatively from prompt_tokens.
    if cache_hit is None and cache_miss is None:
        cache_hit = 0
        cache_miss = prompt
    elif cache_hit is None:
        cache_hit = max(0, prompt - cache_miss)
    elif cache_miss is None:
        cache_miss = max(0, prompt - cache_hit)

    # Do not let malformed provider accounting exceed prompt total.
    if prompt > 0 and cache_hit + cache_miss > prompt:
        overflow = cache_hit + cache_miss - prompt
        cache_miss = max(0, cache_miss - overflow)

    accounted = cache_hit + cache_miss
    if prompt > accounted:
        # Unknown remainder -> cache miss, conservative.
        cache_miss += prompt - accounted

    DEEPSEEK_USAGE["usage_response_count"] += 1
    DEEPSEEK_USAGE["prompt_tokens"] += prompt
    DEEPSEEK_USAGE["prompt_cache_hit_tokens"] += cache_hit
    DEEPSEEK_USAGE["prompt_cache_miss_tokens"] += cache_miss
    DEEPSEEK_USAGE["completion_tokens"] += completion
    DEEPSEEK_USAGE["total_tokens"] += total


def deepseek_usage_summary():
    pricing = DEEPSEEK_PRICING_USD_PER_MILLION.get(
        MODEL_NAME
    )

    summary = {
        "model": MODEL_NAME,
        "http_request_count":
            DEEPSEEK_USAGE["http_request_count"],
        "usage_response_count":
            DEEPSEEK_USAGE["usage_response_count"],
        "prompt_tokens":
            DEEPSEEK_USAGE["prompt_tokens"],
        "prompt_cache_hit_tokens":
            DEEPSEEK_USAGE["prompt_cache_hit_tokens"],
        "prompt_cache_miss_tokens":
            DEEPSEEK_USAGE["prompt_cache_miss_tokens"],
        "completion_tokens":
            DEEPSEEK_USAGE["completion_tokens"],
        "total_tokens":
            DEEPSEEK_USAGE["total_tokens"],
        "pricing_usd_per_million":
            dict(pricing) if pricing else None,
        "estimated_cost_usd": None,
        "estimated_100_runs_usd": None,
        "pricing_note":
            "pricing supplied for this DeepSeek experiment",
    }

    if pricing:
        cost = (
            DEEPSEEK_USAGE["prompt_cache_hit_tokens"]
            / 1_000_000
            * pricing["input_cache_hit"]
        )
        cost += (
            DEEPSEEK_USAGE["prompt_cache_miss_tokens"]
            / 1_000_000
            * pricing["input_cache_miss"]
        )
        cost += (
            DEEPSEEK_USAGE["completion_tokens"]
            / 1_000_000
            * pricing["output"]
        )

        summary["estimated_cost_usd"] = round(cost, 8)
        summary["estimated_100_runs_usd"] = round(
            cost * 100,
            6,
        )

    return summary


def print_deepseek_usage_summary():
    usage = deepseek_usage_summary()

    print()
    print_header("DEEPSEEK USAGE / COST")
    print(
        f"HTTP requests:      {usage['http_request_count']}"
    )
    print(
        f"Usage responses:    {usage['usage_response_count']}"
    )
    print(
        f"Input tokens:       {usage['prompt_tokens']:,}"
    )
    print(
        "  cache hit:        "
        f"{usage['prompt_cache_hit_tokens']:,}"
    )
    print(
        "  cache miss:       "
        f"{usage['prompt_cache_miss_tokens']:,}"
    )
    print(
        f"Output tokens:      {usage['completion_tokens']:,}"
    )
    print(
        f"Total tokens:       {usage['total_tokens']:,}"
    )

    if usage["estimated_cost_usd"] is not None:
        print(
            "Estimated cost:     "
            f"${usage['estimated_cost_usd']:.6f}"
        )
        print(
            "100 similar runs:   "
            f"${usage['estimated_100_runs_usd']:.4f}"
        )
    else:
        print(
            "Estimated cost:     unavailable "
            f"(no pricing table for {MODEL_NAME})"
        )


# DeepSeek V4 soporta contextos muy superiores; conservamos este valor sólo
# como referencia del baseline local. No se envía como parámetro a la API.
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
MAX_DEEPSEEK_TRANSPORT_ATTEMPTS = 2
DEEPSEEK_TRANSPORT_RETRY_DELAY_SECONDS = 2

# Una respuesta HTTP 200 con message.content vacío no debe abortar la sesión.
# Se considera un fallo recuperable de generación y se repite la misma
# solicitud. "thinking" se desactiva explícitamente porque este pipeline
# sólo consume el JSON final.
MAX_DEEPSEEK_GENERATION_ATTEMPTS = 3
DEEPSEEK_GENERATION_RETRY_DELAY_SECONDS = 1

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
# TRACK LOCATION - CAPA DETERMINISTA
# ============================================================

TRACK_PROFILE_DIR = os.path.join(
    BASE_DIR,
    "track_profiles",
)

VALID_TRACK_PROFILE_STATUSES = {
    "VALIDATED_MULTI_SESSION",
    "VALIDATED",
}


def _normalize_track_identity(value):
    if value is None:
        return ""

    normalized = unicodedata.normalize(
        "NFKD",
        str(value).strip().lower(),
    )

    normalized = "".join(
        char
        for char in normalized
        if not unicodedata.combining(char)
    )

    return re.sub(
        r"[^a-z0-9]+",
        " ",
        normalized,
    ).strip()


def _load_track_location_module():
    """
    Carga track_location.py desde el mismo directorio que llm_analysis.py.

    Es deliberadamente local: la resolución de curvas forma parte del
    pipeline determinista del proyecto y no depende del entorno Python global.
    """
    module_path = os.path.join(
        BASE_DIR,
        "track_location.py",
    )

    if not os.path.isfile(
        module_path
    ):
        return None, {
            "status": "MODULE_NOT_FOUND",
            "module_path": module_path,
        }

    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "race_engineer_track_location",
            module_path,
        )

        if (
            spec is None
            or
            spec.loader is None
        ):
            raise RuntimeError(
                "No se pudo crear spec para track_location.py"
            )

        module = importlib.util.module_from_spec(
            spec
        )

        spec.loader.exec_module(
            module
        )

        if not hasattr(
            module,
            "resolve_interval",
        ):
            raise RuntimeError(
                "track_location.py no expone resolve_interval()"
            )

        return module, None

    except Exception as exc:
        return None, {
            "status": "MODULE_LOAD_ERROR",
            "module_path": module_path,
            "error": str(exc),
        }


def _track_profile_candidate_paths():
    """
    Busca perfiles en:
    1) ./track_profiles/*.json
    2) la raíz del proyecto, sólo archivos cuyo nombre contiene "profile"

    Esto permite migrar gradualmente a track_profiles/ sin romper el uso actual.
    """
    paths = []

    if os.path.isdir(
        TRACK_PROFILE_DIR
    ):
        for filename in sorted(
            os.listdir(
                TRACK_PROFILE_DIR
            )
        ):
            if filename.lower().endswith(
                ".json"
            ):
                paths.append(
                    os.path.join(
                        TRACK_PROFILE_DIR,
                        filename,
                    )
                )

    for filename in sorted(
        os.listdir(
            BASE_DIR
        )
    ):
        lower = filename.lower()

        if (
            lower.endswith(".json")
            and
            "profile" in lower
            and
            "validation" not in lower
        ):
            path = os.path.join(
                BASE_DIR,
                filename,
            )

            if path not in paths:
                paths.append(
                    path
                )

    return paths


def load_track_location_context(
    metadata,
):
    """
    Devuelve contexto de resolución espacial para el circuito de la sesión.

    Sólo activa perfiles explícitamente validados. Un circuito sin perfil
    continúa funcionando exactamente como antes, únicamente con metros.
    """
    track = (
        metadata.get("track")
        if isinstance(metadata, dict)
        else None
    )

    layout = (
        metadata.get("track_layout")
        if isinstance(metadata, dict)
        else None
    )

    track_key = _normalize_track_identity(
        track
    )

    if not track_key:
        return {
            "status": "NO_TRACK_METADATA",
            "track": track,
            "profile": None,
            "profile_path": None,
            "resolver": None,
        }

    module, module_error = (
        _load_track_location_module()
    )

    if module is None:
        return {
            **(
                module_error
                or {
                    "status": "MODULE_NOT_AVAILABLE",
                }
            ),
            "track": track,
            "profile": None,
            "profile_path": None,
            "resolver": None,
        }

    matches = []

    for path in (
        _track_profile_candidate_paths()
    ):
        try:
            with open(
                path,
                "r",
                encoding="utf-8",
            ) as file:
                profile = json.load(
                    file
                )
        except Exception:
            continue

        if not isinstance(
            profile,
            dict,
        ):
            continue

        if not isinstance(
            profile.get("turns"),
            list,
        ):
            continue

        profile_track_key = (
            _normalize_track_identity(
                profile.get("track")
            )
        )

        if (
            profile_track_key
            !=
            track_key
        ):
            continue

        status = str(
            profile.get(
                "status",
                "",
            )
        ).strip().upper()

        if (
            status
            not in
            VALID_TRACK_PROFILE_STATUSES
        ):
            continue

        profile_layout = (
            profile.get("layout")
        )

        layout_match = True

        if (
            layout
            and
            profile_layout
        ):
            layout_match = (
                _normalize_track_identity(
                    layout
                )
                ==
                _normalize_track_identity(
                    profile_layout
                )
            )

        if not layout_match:
            continue

        matches.append(
            (
                str(
                    profile.get(
                        "profile_id",
                        "",
                    )
                ),
                path,
                profile,
            )
        )

    if not matches:
        return {
            "status": "NO_VALIDATED_PROFILE",
            "track": track,
            "profile": None,
            "profile_path": None,
            "resolver": module.resolve_interval,
        }

    # El profile_id incluye versión; orden lexicográfico deja la versión más
    # reciente al final para nuestro esquema actual v0.x/v1.x.
    matches.sort(
        key=lambda item: item[0]
    )

    profile_id, path, profile = (
        matches[-1]
    )

    return {
        "status": "ACTIVE",
        "track": track,
        "profile_id": profile_id,
        "profile_status": profile.get(
            "status"
        ),
        "profile_path": path,
        "numbering_scheme": (
            profile.get(
                "calibration",
                {},
            )
            or {}
        ).get(
            "numbering_scheme"
        ),
        "profile": profile,
        "resolver": module.resolve_interval,
    }


def resolve_track_location(
    context,
    start_distance_m,
    end_distance_m,
):
    if (
        not isinstance(
            context,
            dict,
        )
        or
        context.get("status")
        !=
        "ACTIVE"
    ):
        return None

    start_m = safe_float(
        start_distance_m
    )

    end_m = safe_float(
        end_distance_m
    )

    if (
        start_m is None
        or
        end_m is None
    ):
        return None

    resolver = context.get(
        "resolver"
    )

    profile = context.get(
        "profile"
    )

    if (
        not callable(
            resolver
        )
        or
        not isinstance(
            profile,
            dict,
        )
    ):
        return None

    try:
        result = resolver(
            profile,
            start_m,
            end_m,
        )
    except Exception as exc:
        return {
            "status": "RESOLUTION_ERROR",
            "error": str(exc),
            "start_m": start_m,
            "end_m": end_m,
        }

    if not isinstance(
        result,
        dict,
    ):
        return None

    return {
        **result,
        "status": "RESOLVED",
    }


def enrich_items_with_track_location(
    items,
    context,
):
    if not isinstance(
        items,
        list,
    ):
        return items

    for item in items:
        if not isinstance(
            item,
            dict,
        ):
            continue

        start_m = safe_float(
            item.get(
                "start_distance_m"
            )
        )
        end_m = safe_float(
            item.get(
                "end_distance_m"
            )
        )

        # Los patrones puntuales repetidos pueden no pertenecer todavía a una
        # priority_region. En ese caso conservan la coordenada física de la
        # referencia (onset/release), pero no un intervalo start/end. Resolver
        # un micro-intervalo alrededor de ese punto permite nombrar la curva
        # sin inventar una región de coaching ni alterar las distancias fuente.
        if (
            start_m is None
            or
            end_m is None
        ):
            point_m = None

            for field in (
                "reference_onset_m",
                "reference_release_m",
            ):
                point_m = safe_float(
                    item.get(field)
                )
                if point_m is not None:
                    break

            if point_m is not None:
                start_m = point_m - 10.0
                end_m = point_m + 10.0

        item["track_location"] = (
            resolve_track_location(
                context,
                start_m,
                end_m,
            )
        )

    return items


def track_location_label(
    item,
):
    if not isinstance(
        item,
        dict,
    ):
        return None

    location = item.get(
        "track_location"
    )

    if not isinstance(
        location,
        dict,
    ):
        return None

    if (
        location.get("status")
        !=
        "RESOLVED"
    ):
        return None

    label = location.get(
        "label"
    )

    if not isinstance(
        label,
        str,
    ):
        return None

    label = label.strip()

    return (
        label
        if label
        else None
    )


def track_location_context_summary(
    context,
):
    if not isinstance(
        context,
        dict,
    ):
        return {
            "status": "UNAVAILABLE",
        }

    return {
        "status":
            context.get(
                "status"
            ),
        "track":
            context.get(
                "track"
            ),
        "profile_id":
            context.get(
                "profile_id"
            ),
        "profile_status":
            context.get(
                "profile_status"
            ),
        "profile_path":
            context.get(
                "profile_path"
            ),
        "numbering_scheme":
            context.get(
                "numbering_scheme"
            ),
    }


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
            f"{format_lap_time(lap_times[lap])}"
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
            f"{format_lap_time(reference_time)}"
        )

        print(
            f"  Tiempo B: "
            f"{format_lap_time(comparison_time)}"
        )

        print(
            f"  Delta real: "
            f"{signed_seconds(real_delta)}"
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

        # Métrica determinista independiente de sustained_brake_difference.
        # El LLM todavía no la recibe como texto libre; se conserva para
        # diagnóstico y render objetivo.
        "braking_point_comparison":
            episode.get(
                "braking_point_comparison"
            ),

        "brake_release_point_comparison":
            episode.get(
                "brake_release_point_comparison"
            ),

        "throttle_onset_point_comparison":
            episode.get(
                "throttle_onset_point_comparison"
            ),

        "throttle_release_point_comparison":
            episode.get(
                "throttle_release_point_comparison"
            ),

        # Throttle 1.2: observacional. No se envía al LLM en v3.10.8.
        "throttle_full_throttle_attainment_comparison":
            episode.get(
                "throttle_full_throttle_attainment_comparison"
            ),

        "throttle_partial_lift_comparison":
            episode.get(
                "throttle_partial_lift_comparison"
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

        "braking_point_detection":
            objective.get(
                "braking_point_detection",
                {},
            ),

        "throttle_point_detection":
            objective.get(
                "throttle_point_detection",
                {},
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
# DEEPSEEK API - PROVISIONAL BACKEND
# ============================================================

def deepseek_chat(
    system_prompt,
    user_prompt,
    temperature=None,
    seed=None,
    timeout_seconds=None,
    transport_attempts=None,
    format_schema=None,
):
    """
    Wrapper robusto para DeepSeek Chat Completions.

    Mantiene la misma interfaz interna que el antiguo wrapper de Ollama para
    no modificar prompts, validadores ni el flujo de Race Engineer.

    Decisiones deliberadas para esta prueba:
    - DeepSeek V4 en NON-THINKING para consumir sólo el JSON final y para que
      `temperature` siga teniendo efecto.
    - `response_format={"type": "json_object"}` en todas las llamadas.
    - `seed` se conserva en la firma por compatibilidad con el pipeline, pero
      no se envía: la API pública actual de DeepSeek no documenta `seed`.
    - `format_schema` no se envía como JSON Schema porque DeepSeek JSON Output
      expone `json_object`; los validadores Python existentes siguen siendo la
      autoridad del schema y fuerzan retries si la respuesta no coincide.
    """
    api_key = os.environ.get(DEEPSEEK_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY no está configurada. "
            "En Codespaces agregala como secret y exportala al entorno."
        )

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "stream": False,
        "temperature": (
            TEMPERATURE if temperature is None else temperature
        ),
        "response_format": {
            "type": "json_object",
        },
        # V4 defaults to thinking=enabled, so disable it explicitly.
        "thinking": {
            "type": "disabled",
        },
        # Suficiente para los JSON del pipeline actual y evita respuestas
        # accidentalmente enormes.
        "max_tokens": 8192,
    }

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    effective_timeout = (
        TIMEOUT_SECONDS
        if timeout_seconds is None
        else float(timeout_seconds)
    )

    max_transport_attempts = (
        MAX_DEEPSEEK_TRANSPORT_ATTEMPTS
        if transport_attempts is None
        else max(1, int(transport_attempts))
    )

    last_generation_diagnostic = None

    for generation_attempt in range(
        1,
        MAX_DEEPSEEK_GENERATION_ATTEMPTS + 1,
    ):
        raw = None
        last_transport_error = None

        request = urllib.request.Request(
            DEEPSEEK_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        for transport_attempt in range(
            1,
            max_transport_attempts + 1,
        ):
            try:
                DEEPSEEK_USAGE["http_request_count"] += 1
                with urllib.request.urlopen(
                    request,
                    timeout=effective_timeout,
                ) as response:
                    raw = response.read()

                last_transport_error = None
                break

            except urllib.error.HTTPError as exc:
                try:
                    error_body = exc.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                except Exception:
                    error_body = ""

                # 429/5xx pueden ser transitorios. 4xx restantes son de
                # configuración/payload y conviene fallar inmediatamente.
                retryable = (
                    exc.code == 429
                    or 500 <= exc.code <= 599
                )

                if retryable and transport_attempt < max_transport_attempts:
                    print(
                        "    DeepSeek: HTTP transitorio "
                        f"{exc.code} (intento {transport_attempt}/"
                        f"{max_transport_attempts}). Reintentando..."
                    )
                    time.sleep(
                        DEEPSEEK_TRANSPORT_RETRY_DELAY_SECONDS
                    )
                    continue

                raise RuntimeError(
                    "DEEPSEEK_HTTP_ERROR. "
                    f"HTTP {exc.code}. URL: {DEEPSEEK_URL}\n"
                    f"Respuesta: {error_body[:1200]}"
                ) from exc

            except (
                TimeoutError,
                urllib.error.URLError,
            ) as exc:
                last_transport_error = exc

                if transport_attempt < max_transport_attempts:
                    print(
                        "    DeepSeek: fallo de transporte "
                        f"(intento {transport_attempt}/"
                        f"{max_transport_attempts}): "
                        f"{type(exc).__name__}. Reintentando..."
                    )
                    time.sleep(
                        DEEPSEEK_TRANSPORT_RETRY_DELAY_SECONDS
                    )
                    continue

                raise RuntimeError(
                    "DEEPSEEK_TRANSPORT_FAILED. "
                    f"URL: {DEEPSEEK_URL}\n"
                    f"Timeout por intento: {effective_timeout:g} s\n"
                    f"Error: {exc}"
                ) from exc

        if raw is None:
            raise RuntimeError(
                "DEEPSEEK_TRANSPORT_FAILED sin respuesta utilizable. "
                f"Último error: {last_transport_error}"
            )

        try:
            result = json.loads(raw.decode("utf-8"))
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            last_generation_diagnostic = (
                "respuesta HTTP no decodificable como JSON válido"
            )

            if generation_attempt < MAX_DEEPSEEK_GENERATION_ATTEMPTS:
                print(
                    "    DeepSeek: respuesta de generación inválida "
                    f"(intento {generation_attempt}/"
                    f"{MAX_DEEPSEEK_GENERATION_ATTEMPTS}). "
                    "Reintentando..."
                )
                time.sleep(
                    DEEPSEEK_GENERATION_RETRY_DELAY_SECONDS
                )
                continue

            raise RuntimeError(
                "DEEPSEEK_GENERATION_INVALID_JSON tras "
                f"{MAX_DEEPSEEK_GENERATION_ATTEMPTS} intento(s)."
            ) from exc

        record_deepseek_usage(
            result.get("usage")
        )

        choices = result.get("choices")
        message = None
        finish_reason = None

        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                finish_reason = first_choice.get("finish_reason")

        if isinstance(message, dict):
            content = message.get("content")

            if isinstance(content, str) and content.strip():
                return content

        usage = result.get("usage")
        last_generation_diagnostic = (
            "choices[0].message.content vacío/ausente"
            f"; finish_reason={finish_reason!r}"
            f"; usage={usage!r}"
        )

        if generation_attempt < MAX_DEEPSEEK_GENERATION_ATTEMPTS:
            print(
                "    DeepSeek: respuesta vacía/inutilizable "
                f"(intento {generation_attempt}/"
                f"{MAX_DEEPSEEK_GENERATION_ATTEMPTS}): "
                f"{last_generation_diagnostic}. Reintentando..."
            )
            time.sleep(
                DEEPSEEK_GENERATION_RETRY_DELAY_SECONDS
            )
            continue

        raise RuntimeError(
            "DEEPSEEK_EMPTY_CONTENT tras "
            f"{MAX_DEEPSEEK_GENERATION_ATTEMPTS} intento(s). "
            f"Diagnóstico: {last_generation_diagnostic}"
        )

    raise RuntimeError(
        "DEEPSEEK_GENERATION_FAILED sin respuesta utilizable."
    )


# ============================================================
# SYSTEM PROMPT v3.10.8
# ============================================================

SYSTEM_PROMPT = """
Sos un ingeniero de pista especializado en telemetría y coaching
de pilotos de competición y simulación.

Python ya calculó y validó TODOS los datos objetivos.

Tu tarea es EXCLUSIVAMENTE cualitativa:

- interpretar diferencias observables entre canales autorizados;
- formular hipótesis prudentes sólo cuando aporten valor;
- transformar hallazgos válidos en recomendaciones concretas para la
  próxima vuelta o tanda.

No seas un narrador de telemetría. Un hallazgo útil debe terminar, cuando
la evidencia lo permita, en una acción que el piloto pueda intentar.

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

Los únicos números permitidos en tu respuesta son los valores enteros del
campo JSON "episode_id", porque Python los necesita para relacionar tu
interpretación con los episodios.

Python insertará posteriormente todos los valores numéricos reales en el
informe final.

En esta versión NO existe todavía una métrica autorizada de punto de
frenada para el LLM. Por lo tanto, NO recomiendes frenar antes, frenar más
tarde ni mover un punto de frenada una distancia determinada.

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
NO derives nuevas métricas a partir de límites de eventos.

============================================================
GROUNDING FACTUAL OBLIGATORIO
============================================================

Para CADA episodio, "action_channels" es una WHITELIST semántica de
acciones observables.

Si "brake" NO está en action_channels:
- no menciones freno, frenado, frenada ni acción de frenar.

Si "throttle" NO está en action_channels:
- no menciones acelerador, aceleración ni modulación de gas.

Si "steering_magnitude" NO está en action_channels:
- no menciones volante, dirección, giro ni corrección de trayectoria.

La velocidad sólo puede mencionarse si el episodio contiene contexto de
velocidad autorizado.

La velocidad es contexto o posible resultado observable; NO es una acción
del piloto.

No inventes variables ni causas que Python no suministró. Quedan fuera del
dominio permitido, entre otras:

- obstáculos o incidentes visuales;
- cámaras o imágenes;
- topografía, pendientes, baches o irregularidades de pista;
- adherencia, humedad o clima;
- presión o estado de neumáticos;
- vibraciones o averías mecánicas;
- motor, potencia, transmisión o propulsión;
- aerodinámica o gestión de energía;
- combustible o temperaturas;
- carga o daño del vehículo;
- tracción, demanda de tracción, agarre o grip;
- balance, transferencia de carga o dinámica del vehículo;
- trayectoria, línea o geometría del recorrido salvo que Python las suministre
  explícitamente como datos autorizados.

Estas prohibiciones también se aplican a HIPÓTESIS. No uses un concepto
prohibido sólo por introducirlo con "podría", "quizás", "parece" o
"sería compatible con".

No recomiendes inspeccionar datos que no existen en el payload.

============================================================
PRINCIPIO DE COACHING
============================================================

Una recomendación no debe limitarse a describir que existe una diferencia.
Debe decir QUÉ input autorizado conviene probar y EN QUÉ DIRECCIÓN, siempre
que los datos lo permitan.

Evitá terminar una recomendación con expresiones vagas como:

- "revisar el freno";
- "ajustar el acelerador";
- "trabajar la dirección";
- "comparar con la referencia";
- "buscar una transición más cercana";
- "mejorar la técnica".

Si usás un verbo general como "ajustar", completalo inmediatamente con una
acción concreta y direccional.

Traducí evidencia consistente así:

- más acelerador en la vuelta comparada -> probar menos acelerador hacia la
  referencia;
- menos acelerador -> probar más acelerador hacia la referencia;
- más freno -> probar menos aplicación de freno hacia la referencia;
- menos freno -> probar más aplicación de freno hacia la referencia;
- steering_magnitude puede ser una recomendación directa incluso como única
  acción cuando Python observó ese canal y la dirección es grounded;
- NO conviertas steering_magnitude automáticamente en la recomendación por
  defecto de todos los episodios: si también hay freno/acelerador, elegí una
  maniobra principal según la evidencia y tratá steering como secundario cuando
  corresponda;
- si steering_magnitude es unívoco, cualquier orden direccional debe tender
  hacia la referencia; si es mixed, usá una formulación neutral de
  replicar/acompañar la referencia en lugar de forzar aumentar/reducir.

Estas son instrucciones de prueba respecto de la referencia, NO afirmaciones
de causalidad.

Si un mismo canal cambia de sentido dentro del episodio, NO lo reduzcas
artificialmente a "más" o "menos". En ese caso recomendá reproducir mejor la
secuencia, evolución o modulación de ese canal respecto de la referencia.

Si aparecen varios canales autorizados, no inventes una técnica que los una.
Podés recomendar reproducir su coordinación o secuencia sólo cuando los datos
muestren una relación temporal entre ellos; de lo contrario, expresá el
cambio de cada canal de forma breve y concreta.

No conviertas la mera presencia de varios canales en una lista de pruebas
independientes sin jerarquía. Cuando sea posible, formulá un objetivo principal
claro y tratá los demás canales como contexto o ajuste secundario. Si el payload
no permite decidir cuál debe ser principal, no inventes esa prioridad.

============================================================
FRENO
============================================================

Si el freno está autorizado, podés recomendar cambios relativos en:

- cantidad de freno;
- modulación;
- secuencia de aplicación o liberación sólo cuando esa lectura esté apoyada
  por la evidencia recibida.

NO conviertas automáticamente una diferencia de freno en:

- frenada tardía;
- frenada temprana;
- punto de frenada incorrecto;
- exceso de trail braking;
- falta de trail braking.

Los límites start_distance_m, end_distance_m y peak_distance_m localizan
DIFERENCIAS de telemetría. NO representan por sí solos el comienzo real de
una frenada y no pueden usarse para calcular una distancia de coaching.

============================================================
ACELERADOR
============================================================

Si el acelerador está autorizado:

- una diferencia consistentemente menor puede convertirse en una prueba de
  mayor acelerador hacia la referencia;
- una diferencia consistentemente mayor puede convertirse en una prueba de
  menor acelerador hacia la referencia;
- si la diferencia cambia de sentido, priorizá replicar la modulación o
  secuencia de la referencia.

NO afirmes "acelerar antes" o "acelerar más tarde" si Python no proporciona
una métrica explícita que identifique ese momento.

============================================================
DIRECCIÓN / VOLANTE
============================================================

Si steering_magnitude está autorizado:

- podés DESCRIBIR la diferencia observada de magnitud;
- puede ser una recomendación directa única si ésa es realmente la acción más
  útil del episodio, pero no lo elijas mecánicamente sólo porque el canal existe;
- si también hay freno o acelerador, puede quedar como ajuste secundario o como
  foco principal según la lectura grounded del episodio;
- no atribuyas al steering una mejora de velocidad/tiempo ni una causa dinámica;
- si la dirección de steering es mixed, no fuerces aumentar/reducir: usá una
  formulación neutral de replicar/acompañar la referencia.

No conviertas automáticamente una diferencia de dirección en:

- mala trayectoria;
- ápice incorrecto;
- subviraje;
- sobreviraje;
- corrección por inestabilidad.

No existe geometría de trayectoria salvo que Python la suministre
explícitamente.

============================================================
VELOCIDAD
============================================================

La velocidad puede utilizarse como contexto o criterio de comprobación cuando
esté autorizada.

No la conviertas en acción del piloto y nunca recomiendes simplemente
"aumentar la velocidad".

Si existe propagación de velocidad después de una acción, podés indicar que
esa persistencia vuelve útil probar el cambio de input en la próxima tanda,
sin afirmar que la acción causó la diferencia de velocidad.

============================================================
CAUSALIDAD
============================================================

action_time_loss_s indica cuánto cambió el delta mientras estuvo presente una
diferencia de acción.

NO demuestra que esa acción haya causado exactamente esa pérdida.

Preferí:

- "coincide con";
- "ocurre mientras";
- "es compatible con";
- "podría contribuir";
- "es una prueba útil para la próxima vuelta";
- "causalidad no confirmada".

Evitá afirmar como hechos:

- "causó";
- "provocó";
- "se debe a";
- "generó".

La falta de causalidad demostrada NO impide dar coaching cuando la acción
propuesta está directamente respaldada por una diferencia observable.

============================================================
HECHO / INTERPRETACIÓN / RECOMENDACIÓN / HIPÓTESIS
============================================================

HECHO:
dato calculado por Python.

INTERPRETACIÓN:
lectura prudente directamente respaldada por esos datos.

RECOMENDACIÓN:
cambio concreto que el piloto puede probar respecto de la referencia.

HIPÓTESIS:
explicación posible no confirmada.

No presentes una hipótesis como hecho.
No uses una hipótesis no confirmada como única base de una recomendación.

============================================================
CLASIFICACIÓN OBLIGATORIA
============================================================

Debés devolver EXACTAMENTE un objeto por cada episode_id recibido cuando el
contrato de esa llamada incluya clasificación.

Clasificaciones permitidas:

- PRIORITARIO
- SECUNDARIO
- NO_ACCIONABLE

Usá la clasificación de forma relativa y coherente con la evidencia que
entrega Python. El ranking de Python, action_time_loss_s y evidence_strength
pueden orientar la prioridad, pero NO inventes thresholds ni alternes
etiquetas mecánicamente.

NO_ACCIONABLE debe reservarse para episodios donde la evidencia observable no
permita formular una recomendación útil sin inventar información.

No omitas episodios.
No agregues episodios.
No dupliques episode_id.

============================================================
SALIDA
============================================================

Respondé ÚNICAMENTE con el JSON exigido por cada llamada.

No Markdown.
No bloques de código.
No texto antes o después del JSON.

Todos los textos libres deben estar en español y NO deben contener cifras.
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

# La síntesis global integra varias restricciones simultáneas
# (ranking + targets de onset/release + estilo). Le damos un intento extra,
# sin aumentar los reintentos de cada episodio.
MAX_GLOBAL_LLM_VALIDATION_ATTEMPTS = 3


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


# ============================================================
# GATE DETERMINISTA DE PÉRDIDAS ANÓMALAS v3.8.19
# ============================================================
#
# Objetivo:
# - conservar pérdidas extremas para auditoría;
# - impedir que una incidencia/no-representatividad se transforme en
#   coaching técnico normal;
# - NO inferir la causa (trompo, tráfico, off-track, etc.).
#
# El criterio es deliberadamente conservador y se aplica ANTES de
# cualquier llamada al LLM o al ranker.
# ============================================================

ANOMALY_GATE_CONFIG = {
    "max_episode_length_m": 500.0,
    "min_local_loss_s": 5.0,
    "lap_delta_exceed_margin_s": 1.0,
    "extreme_local_loss_s": 8.0,
    "lap_delta_fraction": 0.75,
}


def classify_non_representative_time_loss(
    episode,
    comparison,
):
    """
    Devuelve metadata de anomalía si el episodio concentra una pérdida
    temporal demasiado grande para tratarla como coaching técnico normal.

    La función sólo clasifica la forma temporal de la anomalía. Nunca
    intenta identificar su causa física o deportiva.
    """
    if not isinstance(episode, dict):
        return None

    if not isinstance(comparison, dict):
        return None

    length_m = safe_float(
        episode.get("length_m")
    )
    local_loss_s = safe_float(
        episode.get("action_time_loss_s")
    )
    lap_delta_s = safe_float(
        comparison.get("comparison_minus_reference_s")
    )

    if (
        length_m is None
        or local_loss_s is None
        or lap_delta_s is None
    ):
        return None

    # Sólo aplica a comparaciones donde la vuelta comparada pierde tiempo.
    if lap_delta_s <= 0.0:
        return None

    if local_loss_s <= 0.0:
        return None

    if (
        length_m
        > ANOMALY_GATE_CONFIG["max_episode_length_m"]
    ):
        return None

    if (
        local_loss_s
        < ANOMALY_GATE_CONFIG["min_local_loss_s"]
    ):
        return None

    reasons = []

    if (
        local_loss_s
        >= lap_delta_s
        + ANOMALY_GATE_CONFIG[
            "lap_delta_exceed_margin_s"
        ]
    ):
        reasons.append(
            "LOCAL_LOSS_EXCEEDS_LAP_DELTA"
        )

    if (
        local_loss_s
        >= ANOMALY_GATE_CONFIG[
            "extreme_local_loss_s"
        ]
        and
        local_loss_s
        >= lap_delta_s
        * ANOMALY_GATE_CONFIG[
            "lap_delta_fraction"
        ]
    ):
        reasons.append(
            "EXTREME_LOCAL_LOSS_CONCENTRATION"
        )

    if not reasons:
        return None

    return {
        "anomaly_status":
            "NON_REPRESENTATIVE_TIME_LOSS",
        "recommended_for_driver_analysis":
            False,
        "excluded_from_coaching":
            True,
        "anomaly_reason":
            "+".join(reasons),
        "anomaly_reasons":
            reasons,
        "local_loss_s":
            local_loss_s,
        "lap_delta_s":
            lap_delta_s,
        "local_loss_to_lap_delta_ratio":
            (
                local_loss_s / lap_delta_s
                if lap_delta_s > 0.0
                else None
            ),
        "detection_basis":
            "DETERMINISTIC_TIME_LOSS_GATE",
        "cause_inferred":
            False,
        "driver_message":
            (
                "Se detectó una pérdida anómala de gran magnitud. "
                "No se utiliza para recomendaciones de técnica."
            ),
    }


def split_episode_catalog_for_coaching(
    comparison,
    episode_catalog,
):
    """
    Mantiene los episode_id originales. Los episodios anómalos se
    conservan aparte para auditoría y no llegan al LLM/ranker/coaching.
    """
    eligible = []
    excluded = []

    for episode in episode_catalog:
        anomaly = (
            classify_non_representative_time_loss(
                episode,
                comparison,
            )
        )

        if anomaly is None:
            eligible.append(episode)
            continue

        record = dict(episode)
        record.update(anomaly)
        excluded.append(record)

    return eligible, excluded


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

    Regla clave v3.8.18:
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
# PROMPT DE COMPARACIÓN v3.8.18
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

No escribas números dentro de interpretation, hypotheses,
recommendation, comparison_observations, limitations o conclusion, ni con dígitos ni con palabras.

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
# GROUNDING FACTUAL v3.8.18
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
    (r"\bestabilidad\b|\binestabilidad\b|\bdinamic(?:a|o|as|os)\b", "estabilidad/dinámica del vehículo"),
    (r"\btrayector(?:ia|ias)\b", "trayectoria no observada"),
    (r"\btraccion\b", "tracción no observada"),
    (r"\bagarre\b|\bgrip\b", "agarre/grip no observado"),
    (r"\bbalance\b", "balance del vehículo no observado"),
    (r"\btransferencia de carga\b", "transferencia de carga no observada"),
    (r"\bsubviraje\b|\bsobreviraje\b", "balance dinámico no observado"),
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



# Speed puede aparecer como contexto/propagación, pero nunca como input objetivo.
# Este guardrail no prohíbe frases descriptivas como "la velocidad fue menor";
# sólo rechaza órdenes o finalidades que convierten velocidad en el target.
SPEED_AS_ACTION_TARGET_PATTERNS = (
    (
        r"\b(?:aumenta|aumentar|incrementa|incrementar|subi|subir|"
        r"reduci|reducir|disminui|disminuir|baja|bajar|"
        r"recupera|recuperar|iguala|igualar)\b[^.;:\n]{0,60}\bvelocidad\b",
        "velocidad usada como acción del piloto",
    ),
    (
        r"\bpara\s+(?:acercar|igualar|llevar|recuperar|mejorar)\b"
        r"[^.;:\n]{0,50}\bvelocidad\b",
        "velocidad usada como objetivo de coaching",
    ),
    (
        r"\bpara\s+que\b[^.;:\n]{0,50}\bvelocidad\b"
        r"[^.;:\n]{0,40}\b(?:se\s+acerque|aumente|suba|baje|disminuya|mejore)\b",
        "velocidad usada como objetivo de coaching",
    ),
)


def validate_speed_not_action_target(value, field_name, errors):
    if not isinstance(value, str):
        return

    normalized = normalize_grounding_text(value)

    for pattern, label in SPEED_AS_ACTION_TARGET_PATTERNS:
        if re.search(pattern, normalized):
            errors.append(
                f"{field_name}: {label}; la velocidad es sólo contexto/propagación, "
                "no un input ni un objetivo de acción."
            )
            break


COACHING_INCREASE_VERB_RE = re.compile(
    r"\b(?:aumenta|aumentar|incrementa|incrementar|subi|subir)\b"
)
COACHING_DECREASE_VERB_RE = re.compile(
    r"\b(?:reduci|reducir|disminui|disminuir|baja|bajar)\b"
)
COACHING_DIRECTION_VERB_RE = re.compile(
    r"\b(?:"
    r"aumenta|aumentar|incrementa|incrementar|subi|subir|"
    r"reduci|reducir|disminui|disminuir|baja|bajar"
    r")\b"
)

# Una nueva acción verbal corta el alcance del verbo direccional anterior.
# Así:
#   "aumentá freno y acelerador" -> ambos reciben AUMENTAR
#   "aumentá freno y replicá volante" -> sólo freno recibe AUMENTAR
COACHING_NEW_ACTION_AFTER_AND_RE = re.compile(
    r"\by\s+(?=(?:"
    r"replica|replicar|ajusta|ajustar|manten|mantener|"
    r"acompan(?:a|ar)|limita|limitar|suaviza|suavizar|"
    r"frena|frenar|solta|soltar|suelta|reaplica|reaplicar|"
    r"aplica|aplicar|modula|modular|"
    r"aumenta|aumentar|incrementa|incrementar|subi|subir|"
    r"reduci|reducir|disminui|disminuir|baja|bajar"
    r")\b)"
)


def _single_objective_channel_direction(episode, channel):
    """
    Devuelve higher/lower sólo cuando todos los eventos persistentes del
    canal apuntan en el mismo sentido. Mixed/ambiguo -> None.
    """
    evidence = (
        episode.get("action_evidence_by_channel", {}) or {}
    ).get(channel, {}) or {}

    events = [
        item
        for item in (evidence.get("events", []) or [])
        if isinstance(item, dict)
        and item.get("persistent", True)
        and item.get("direction")
    ]

    directions = {
        str(item.get("direction"))
        for item in events
    }

    if len(directions) != 1:
        return None

    direction = next(iter(directions))
    if direction not in {
        "higher_in_comparison_lap",
        "lower_in_comparison_lap",
    }:
        return None

    return direction


def _channels_mentioned_in_text(text):
    normalized = normalize_grounding_text(text)
    found = set()

    for channel, patterns in CHANNEL_LANGUAGE_PATTERNS.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            found.add(channel)

    return found


STEERING_DIRECT_ACTION_RE = re.compile(
    r"\b(?:"
    r"aumenta|aumentar|incrementa|incrementar|subi|subir|"
    r"reduci|reducir|disminui|disminuir|baja|bajar|"
    r"replica|replicar|ajusta|ajustar|manten|mantener|"
    r"modula|modular|acompan(?:a|ar)|limita|limitar|"
    r"suaviza|suavizar"
    r")\b[^.;\n]{0,90}\b(?:"
    r"volante|direccion|magnitud\s+de\s+(?:direccion|volante)"
    r")\b"
)


def _steering_direct_action_present(text):
    """
    v3.10.8.5.4

    Distingue una mención descriptiva de steering de una orden directa.
    El steering puede seguir apareciendo en interpretation/observaciones sin
    que eso active el contrato de coaching secundario.
    """
    if not isinstance(text, str):
        return False

    return bool(
        STEERING_DIRECT_ACTION_RE.search(
            normalize_grounding_text(text)
        )
    )


def _steering_companion_channels(text):
    if not isinstance(text, str):
        return set()

    return (
        _channels_mentioned_in_text(text)
        &
        {"brake", "throttle"}
    )


def _episode_has_secondary_steering_context(episode):
    if not isinstance(episode, dict):
        return False

    channels = set(episode.get("action_channels", []) or [])
    return (
        "steering_magnitude" in channels
        and
        bool(channels & {"brake", "throttle"})
    )


def validate_episode_steering_secondary_contract(
    recommendation,
    episode,
    errors,
    field_name="recommendation",
):
    """
    Steering coaching v3.10.8.5.4.

    Permitido:
      - steering como recomendación única o secundaria cuando el canal está
        realmente observado en el episodio;
      - dirección explícita sólo cuando Python observa una dirección unívoca;
      - wording neutral de replicar/acompañar cuando steering es mixed.

    Rechazado:
      - steering inventado en un episodio que no contiene ese canal;
      - aumentar/reducir steering cuando Python observa mixed/ambiguo;
      - dirección explícita invertida (la controla además el validator general).
    """
    if not _steering_direct_action_present(recommendation):
        return

    episode_channels = set(episode.get("action_channels", []) or [])
    if "steering_magnitude" not in episode_channels:
        errors.append(
            f"{field_name}: introduce steering_magnitude como acción, pero "
            "ese canal no está observado en el episodio."
        )
        return

    observed = _single_objective_channel_direction(
        episode,
        "steering_magnitude",
    )

    for clause in _explicit_directional_clauses(recommendation):
        if "steering_magnitude" not in clause.get("channels", set()):
            continue

        if observed is None:
            errors.append(
                f"{field_name}: steering_magnitude es mixed/ambiguo; debe "
                "formularse como replicar/acompañar la referencia, no como "
                "aumentar o reducir."
            )
            return


def _comparison_secondary_steering_directions(episode_catalog):
    directions = set()

    for episode in episode_catalog or []:
        if not isinstance(episode, dict):
            continue
        if "steering_magnitude" not in set(episode.get("action_channels", []) or []):
            continue
        direction = _single_objective_channel_direction(
            episode,
            "steering_magnitude",
        )
        if direction:
            directions.add(direction)

    return directions


def validate_summary_steering_secondary_contract(
    conclusion,
    episode_catalog,
    errors,
):
    """
    El resumen de comparación puede conservar steering como recomendación
    única o secundaria, siempre que exista evidencia de steering en los
    episodios y una orden direccional sea unívoca a nivel de comparación.
    """
    if not _steering_direct_action_present(conclusion):
        return

    steering_episodes = [
        episode
        for episode in (episode_catalog or [])
        if isinstance(episode, dict)
        and "steering_magnitude" in set(episode.get("action_channels", []) or [])
    ]
    if not steering_episodes:
        errors.append(
            "conclusion: introduce steering_magnitude como coaching sin "
            "evidencia de steering en la comparación."
        )
        return

    explicit = _explicit_command_direction_map(conclusion).get(
        "steering_magnitude"
    )
    if explicit is None:
        return

    directions = _comparison_secondary_steering_directions(
        episode_catalog
    )
    if len(directions) != 1:
        errors.append(
            "conclusion: la dirección de steering_magnitude no es unívoca "
            "entre los episodios; usá una formulación neutral hacia la "
            "referencia."
        )
        return

    observed = next(iter(directions))
    expected = (
        "increase"
        if observed == "lower_in_comparison_lap"
        else "decrease"
    )
    if explicit != expected:
        errors.append(
            "conclusion: dirección de coaching invertida para "
            "steering_magnitude respecto de la evidencia agregada."
        )



# ============================================================
# ACTION TARGET MUST BE THE REFERENCE LAP v3.10.8.5.4
# ============================================================

COMPARISON_LAP_TARGET_PHRASE_RE = re.compile(
    r"\bvuelta\s+(?:de\s+)?comparad[ao]\b|"
    r"\bvuelta\s+de\s+comparaci[oó]n\b",
    re.IGNORECASE,
)

ACTION_TARGET_VERB_RE = re.compile(
    r"\b(?:"
    r"replic\w*|reproduc\w*|acompan\w*|ajust\w*|manten\w*|"
    r"segu\w*|imit\w*|copi\w*|igual\w*|modul\w*|"
    r"acerc\w*|orient\w*|tom(?:a|ar|ando)\w*|"
    r"usa|usar|usando|busc\w*|llev\w*"
    r")\b"
)

def _comparison_lap_used_as_action_target(text):
    """True sólo cuando 'vuelta comparada' funciona como modelo/objetivo."""
    if not isinstance(text, str):
        return False
    for match in COMPARISON_LAP_TARGET_PHRASE_RE.finditer(text):
        prefix = text[max(0, match.start() - 180):match.start()]
        boundary = max(prefix.rfind('.'), prefix.rfind(';'), prefix.rfind(':'), prefix.rfind('\n'))
        if boundary >= 0:
            prefix = prefix[boundary + 1:]
        normalized = normalize_grounding_text(prefix)
        if ACTION_TARGET_VERB_RE.search(normalized):
            return True
        if re.search(r"\b(?:hacia|como|segun)\s+(?:la\s+)?$", normalized):
            return True
    return False

def validate_reference_lap_is_action_target(text, field_name, errors):
    if _comparison_lap_used_as_action_target(text):
        errors.append(
            f"{field_name}: usa la vuelta comparada como objetivo de coaching; "
            "la acción debe orientarse a la vuelta de referencia."
        )

def repair_comparison_lap_action_target(text):
    """Reemplaza sólo usos de 'vuelta comparada' que son objetivo de acción."""
    if not isinstance(text, str):
        return text
    spans = []
    for match in COMPARISON_LAP_TARGET_PHRASE_RE.finditer(text):
        prefix = text[max(0, match.start() - 180):match.start()]
        boundary = max(prefix.rfind('.'), prefix.rfind(';'), prefix.rfind(':'), prefix.rfind('\n'))
        if boundary >= 0:
            prefix = prefix[boundary + 1:]
        normalized = normalize_grounding_text(prefix)
        if ACTION_TARGET_VERB_RE.search(normalized) or re.search(r"\b(?:hacia|como|segun)\s+(?:la\s+)?$", normalized):
            spans.append((match.start(), match.end()))
    if not spans:
        return text
    out=[]; cursor=0
    for start,end in spans:
        out.append(text[cursor:start]); out.append('referencia'); cursor=end
    out.append(text[cursor:])
    return ''.join(out)

def _explicit_directional_clauses(value):
    """
    Extrae órdenes explícitas de aumentar/reducir y sus canales.

    El alcance termina ante:
    - otra orden direccional;
    - puntuación fuerte;
    - "y" seguido por una nueva acción verbal.
    """
    if not isinstance(value, str):
        return []

    normalized = normalize_grounding_text(value)
    matches = list(COACHING_DIRECTION_VERB_RE.finditer(normalized))
    clauses = []

    for index, match in enumerate(matches):
        start = match.start()
        next_start = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(normalized)
        )

        raw_segment = normalized[start:next_start]

        stop_positions = []

        strong_stop = re.search(r"[.;:\n]", raw_segment)
        if strong_stop:
            stop_positions.append(strong_stop.start())

        new_action = COACHING_NEW_ACTION_AFTER_AND_RE.search(raw_segment)
        if new_action:
            stop_positions.append(new_action.start())

        if stop_positions:
            raw_segment = raw_segment[:min(stop_positions)]

        verb = match.group(0)
        if COACHING_INCREASE_VERB_RE.fullmatch(verb):
            coaching_direction = "increase"
        elif COACHING_DECREASE_VERB_RE.fullmatch(verb):
            coaching_direction = "decrease"
        else:
            continue

        channels = _channels_mentioned_in_text(raw_segment)
        if channels:
            clauses.append(
                {
                    "direction": coaching_direction,
                    "channels": channels,
                    "text": raw_segment,
                }
            )

    return clauses


def validate_episode_coaching_direction(
    recommendation,
    episode,
    errors,
):
    """
    Invariante factual v3.10.8.

    Canal objetivo unívoco:
      comparison LOWER  -> una orden explícita debe AUMENTAR
      comparison HIGHER -> una orden explícita debe REDUCIR

    Formulaciones neutrales ("replicá", "ajustá hacia la referencia")
    siguen permitidas. Canales mixed no reciben una dirección global forzada.
    """
    if not isinstance(recommendation, str):
        return

    for clause in _explicit_directional_clauses(recommendation):
        commanded = clause["direction"]

        for channel in clause["channels"]:
            observed = _single_objective_channel_direction(
                episode,
                channel,
            )
            if observed is None:
                continue

            expected = (
                "increase"
                if observed == "lower_in_comparison_lap"
                else "decrease"
            )

            if commanded == expected:
                continue

            human_channel = {
                "brake": "freno",
                "throttle": "acelerador",
                "steering_magnitude": "magnitud de dirección/volante",
            }.get(channel, channel)

            observed_human = (
                "menor en la vuelta comparada"
                if observed == "lower_in_comparison_lap"
                else "mayor en la vuelta comparada"
            )
            expected_human = (
                "aumentar"
                if expected == "increase"
                else "reducir"
            )

            errors.append(
                "recommendation: dirección de coaching invertida para "
                f"{human_channel}; Python observó {observed_human}, "
                f"por lo que la orden explícita debe ser {expected_human} "
                "o formularse como replicar/ajustar hacia la referencia."
            )


# ============================================================
# DIRECCIÓN FACTUAL EXPLÍCITA v3.10.8
# ============================================================

FACTUAL_HIGHER_SIGNAL_RE = re.compile(
    r"\b(?:"
    r"mayor|"
    r"superior|"
    r"elevad[oa]s?|"
    r"aumento|aumentad[oa]s?|"
    r"incremento|incrementad[oa]s?|"
    r"mas(?!\s+(?:tarde|temprano|antes|despues))"
    r")\b"
)

FACTUAL_LOWER_SIGNAL_RE = re.compile(
    r"\b(?:"
    r"menor|"
    r"inferior|"
    r"reducid[oa]s?|reduccion|"
    r"disminuid[oa]s?|disminucion|"
    r"menos"
    r")\b"
)


def _directional_phrases_for_validation(
    normalized,
):
    """
    v3.10.8

    Divide el texto sólo en fronteras lingüísticas fuertes para validar
    dirección factual. No intenta reconstruir gramática completa.

    Una frase parcial se considera usable únicamente si contiene:
      - exactamente un canal de acción reconocido;
      - exactamente una dirección explícita (higher o lower).

    Si hay más de un canal o más de una dirección, se considera ambigua y
    se ignora. Esto prioriza evitar falsos positivos.
    """
    if not isinstance(normalized, str):
        return []

    parts = re.split(
        r"(?:"
        r"[.;:\n]+|"
        r",\s*(?:mientras(?:\s+que)?|pero|aunque|luego|despues|posteriormente)\s+|"
        r"\s+\b(?:mientras(?:\s+que)?|pero|aunque|luego|despues|posteriormente)\b\s+|"
        r"\s+\by\b\s+"
        r")",
        normalized,
    )

    return [
        part.strip(" ,")
        for part in parts
        if isinstance(part, str)
        and part.strip(" ,")
    ]


def _channels_explicitly_present(
    value,
):
    channels = set()

    for channel, patterns in CHANNEL_LANGUAGE_PATTERNS.items():
        if any(
            re.search(
                pattern,
                value,
            )
            for pattern in patterns
        ):
            channels.add(
                channel
            )

    return channels


def _directions_explicitly_present(
    value,
):
    directions = set()

    if FACTUAL_HIGHER_SIGNAL_RE.search(
        value
    ):
        directions.add(
            "higher_in_comparison_lap"
        )

    if FACTUAL_LOWER_SIGNAL_RE.search(
        value
    ):
        directions.add(
            "lower_in_comparison_lap"
        )

    return directions


def explicit_factual_direction_by_channel(
    value,
):
    """
    v3.10.8

    Extrae sólo afirmaciones factuales inequívocas.

    Regla conservadora:
      una cláusula -> un canal -> una dirección.

    Ejemplos válidos:
      "dirección menor y acelerador mayor"
      "menos freno; más dirección"

    Ejemplos ambiguos que NO fuerzan validación:
      "dirección y acelerador fueron menores"
      "ajustes menores de dirección y acelerador"
      "variaciones de dirección y acelerador"
    """
    if not isinstance(value, str):
        return {}

    normalized = normalize_grounding_text(
        value
    )

    assertions_by_channel = {}

    for phrase in _directional_phrases_for_validation(
        normalized
    ):
        channels = _channels_explicitly_present(
            phrase
        )
        directions = _directions_explicitly_present(
            phrase
        )

        if len(channels) != 1:
            continue

        if len(directions) != 1:
            continue

        channel = next(
            iter(channels)
        )
        direction = next(
            iter(directions)
        )

        assertions_by_channel.setdefault(
            channel,
            set(),
        ).add(
            direction
        )

    return {
        channel: next(
            iter(directions)
        )
        for channel, directions in assertions_by_channel.items()
        if len(directions) == 1
    }


def validate_episode_interpretation_direction(
    interpretation,
    episode,
    errors,
):
    """
    Invariante factual v3.10.8.

    Si interpretation afirma explícitamente que un canal fue mayor/menor,
    esa dirección debe coincidir con los eventos persistentes suministrados
    por Python. Los canales mixed/ambiguos no reciben una dirección forzada.
    """
    if not isinstance(interpretation, str):
        return

    assertions = explicit_factual_direction_by_channel(
        interpretation
    )

    for channel, asserted in assertions.items():
        observed = _single_objective_channel_direction(
            episode,
            channel,
        )

        if observed is None or asserted == observed:
            continue

        human_channel = {
            "brake": "freno",
            "throttle": "acelerador",
            "steering_magnitude": "magnitud de dirección/volante",
        }.get(channel, channel)

        asserted_human = (
            "mayor"
            if asserted == "higher_in_comparison_lap"
            else "menor"
        )
        observed_human = (
            "mayor"
            if observed == "higher_in_comparison_lap"
            else "menor"
        )

        errors.append(
            "interpretation: dirección factual invertida para "
            f"{human_channel}; el texto afirma {asserted_human}, "
            f"pero Python observó {observed_human} en la vuelta comparada."
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


SPANISH_NUMBER_WORD_TOKEN = (
    r"(?:"
    r"cero|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|"
    r"diez|once|doce|trece|catorce|quince|dieciseis|diecisiete|"
    r"dieciocho|diecinueve|veinte|veintiuno|veintidos|veintitres|"
    r"veinticuatro|veinticinco|veintiseis|veintisiete|veintiocho|"
    r"veintinueve|treinta|cuarenta|cincuenta|sesenta|setenta|"
    r"ochenta|noventa|cien|ciento|doscientos|trescientos|"
    r"cuatrocientos|quinientos|seiscientos|setecientos|"
    r"ochocientos|novecientos|mil"
    r")"
)

SPANISH_NUMBER_WORD_SEQUENCE = (
    rf"{SPANISH_NUMBER_WORD_TOKEN}"
    rf"(?:\s+(?:y\s+)?{SPANISH_NUMBER_WORD_TOKEN}){{0,5}}"
)

SPANISH_SPELLED_MEASUREMENT_RE = re.compile(
    rf"\b{SPANISH_NUMBER_WORD_SEQUENCE}\s+"
    r"(?:"
    r"m|metros?|"
    r"s|segundos?|"
    r"por\s+ciento|"
    r"pp|puntos?\s+porcentuales?|"
    r"km/?h|kilometros?\s+por\s+hora|"
    r"unidades?(?:\s+de\s+input)?"
    r")\b"
)

SPANISH_SPELLED_IDENTIFIER_RE = re.compile(
    rf"\b(?:curva|vuelta|lap|episodio)\s+{SPANISH_NUMBER_WORD_SEQUENCE}\b"
)


def text_contains_number_word(
    value,
):
    """
    Detecta números escritos con palabras sólo cuando expresan una magnitud
    o un identificador numérico prohibido.

    No rechaza conteos cualitativos como "dos tramos": el objetivo es impedir
    que el LLM burle el contrato numérico con "veinte metros", "dos segundos"
    o "curva tres", sin volver a sobrevalidar el lenguaje natural.
    """
    if not isinstance(value, str):
        return False

    normalized = normalize_grounding_text(
        value
    )

    return bool(
        SPANISH_SPELLED_MEASUREMENT_RE.search(
            normalized
        )
        or SPANISH_SPELLED_IDENTIFIER_RE.search(
            normalized
        )
    )


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

    if text_contains_number_word(
        value
    ):
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

            validate_speed_not_action_target(
                recommendation,
                f"Episodio {episode_id}.recommendation",
                errors,
            )

            validate_episode_steering_secondary_contract(
                recommendation,
                episode,
                errors,
                field_name=f"Episodio {episode_id}.recommendation",
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
# RUTA LEGACY DE COMPARACIÓN ELIMINADA EN v3.8.18
# ============================================================
#
# Desde v3.8.18 NO existe una llamada LLM multi-episodio para
# interpretación. Cada driver_action_episode se interpreta y valida
# en aislamiento; Python agrega los resultados ya validados.
# ============================================================

# ============================================================
# ORQUESTACIÓN AISLADA POR EPISODIO v3.8.18
# ============================================================
#
# Motivo del cambio:
# una única llamada con varios episodios permitía contaminación
# semántica entre sus whitelists. Desde v3.8.18 cada episodio se
# interpreta y valida en aislamiento. Python vuelve a reunir los
# objetos ya validados y solicita una síntesis separada.
#
# El contrato externo de llm_structured NO cambia.
# ============================================================

EPISODE_SYSTEM_PROMPT = """
Sos un ingeniero de pista interpretando UN único episodio de
telemetría ya detectado y cuantificado por Python.

Python es la única autoridad sobre hechos, canales, magnitudes, ranking y
contexto. Vos transformás esa evidencia en coaching cualitativo.

Tu recomendación debe ser útil para la próxima vuelta. No te limites a decir
que el piloto debe "revisar", "comparar", "ajustar" o "trabajar" un input.
Siempre que la evidencia permita conocer la dirección, indicá qué debe probar:
reducir, aumentar o reproducir mejor la secuencia/modulación respecto de la
referencia.

Reglas obligatorias:
- respondé únicamente un objeto JSON válido;
- no uses Markdown ni texto fuera del JSON;
- no escribas números en ningún texto libre, ni con dígitos ni con palabras;
- no agregues hechos ni conceptos ausentes del payload;
- usá únicamente el vocabulario de acción incluido en
  allowed_action_language;
- si no hay evidencia suficiente para una hipótesis grounded,
  devolvé hypotheses como lista vacía;
- no atribuyas causas externas que el payload no observa;
- no presentes causalidad como hecho;
- no conviertas diferencias de freno en punto de frenada temprano/tardío;
- no conviertas diferencias de acelerador en aplicación temprana/tardía;
- no conviertas diferencias de dirección en trayectoria, línea, ápice,
  subviraje o sobreviraje, ni siquiera como hipótesis;
- no introduzcas tracción, demanda de tracción, agarre/grip, balance,
  transferencia de carga o dinámica del vehículo;
- no derives ninguna métrica nueva a partir de distancias de eventos;
- si un canal es consistentemente mayor en la comparación, la prueba de
  coaching debe tender a REDUCIR ese input hacia la referencia;
- si es consistentemente menor, la prueba debe tender a AUMENTAR ese input
  hacia la referencia;
- si cambia de sentido dentro del episodio, recomendá reproducir mejor su
  secuencia, evolución o modulación respecto de la referencia en vez de
  forzar una dirección única;
- steering_magnitude puede ser la única recomendación directa cuando está
  observado y grounded, pero no debe convertirse en la salida por defecto de
  todos los episodios;
- si el episodio también contiene freno o acelerador, decidí una maniobra
  principal y usá steering como secundario cuando corresponda;
- si steering_magnitude es mixed/ambiguo, no ordenes aumentarlo o reducirlo:
  formulalo como replicar/acompañar la referencia;
- las hipótesis sólo pueden relacionar acciones autorizadas entre sí o con el
  contexto de velocidad autorizado. No uses trayectoria, línea, tracción,
  agarre/grip, balance, transferencia de carga ni dinámica del vehículo;
- si hay varios canales, evitá transformar automáticamente cada uno en una
  prueba independiente. Preferí una instrucción principal clara cuando la
  evidencia permita identificarla; si no permite priorizar, mantené los cambios
  relativos a la referencia sin inventar cuál es causalmente más importante.

La recomendación debe poder entenderse como una instrucción breve de debrief,
pero sin exceder la evidencia disponible.

ESTILO DE DEBRIEF:
- escribí siempre en español;
- soná como un ingeniero de pista profesional y sobrio, no como un listado de
  variables ni como un personaje interpretando un rol;
- interpretation debe CONECTAR los hechos suministrados en una lectura breve,
  no repetir mecánicamente cada canal;
- evitá empezar sistemáticamente con "en la comparación" o "se observó";
- recommendation debe continuar naturalmente la lectura anterior y estar
  redactada como instrucción directa al piloto ("aumentá", "reducí",
  "replicá"), no como infinitivo impersonal;
- cuando haya varios inputs relacionados, redactalos como una sola maniobra o
  secuencia coherente siempre que el payload lo permita;
- no uses lenguaje grandilocuente, motivacional ni de roleplay;
- preferí una o dos frases claras antes que una enumeración encubierta;
- no prometas que un cambio "mejorará la velocidad" o "ganará tiempo":
  action_time_loss_s y speed context no prueban causalidad;
- no uses "trayectoria", "línea", "ápice", "subviraje", "sobreviraje" o
  "balance" si esos conceptos no fueron suministrados explícitamente;
- cuando haya onset/release autorizado, integralo como parte de la secuencia
  de inputs, no como un dato aislado.
"""


COMPARISON_SUMMARY_SYSTEM_PROMPT = """
Sos un ingeniero de pista que sintetiza evaluaciones de episodios
que ya fueron validadas individualmente por Python.

No reinterpretás telemetría cruda.
No agregás hechos, canales ni causas nuevas.
No cambiás la prioridad ya asignada.
No escribís cifras en ningún texto libre.
No introducís trayectoria, línea, tracción, agarre/grip, balance, transferencia
de carga ni dinámica del vehículo si no aparecen explícitamente autorizados.

La síntesis debe conservar el carácter operativo de las recomendaciones ya
validadas. Priorizá qué debería probar el piloto en la próxima vuelta y evitá
conclusiones que sólo digan "revisar", "ajustar", "comparar" o "trabajar" sin
expresar la acción concreta disponible en las evaluaciones.

ESTILO DE SÍNTESIS:
- escribí siempre en español;
- el cierre debe leerse como un debrief profesional: primero qué patrón importa
  y luego qué debe probar el piloto;
- conectá las recomendaciones entre sí cuando formen una misma maniobra;
- no redactes una lista disfrazada de oración separada por comas;
- evitá repetir "en la comparación", "se observó" y "durante el tramo" si no
  agregan información;
- mantené un tono técnico, seguro y sobrio, sin roleplay ni frases
  motivacionales.

Respondé únicamente JSON válido, sin Markdown ni texto adicional.
"""



def channel_direction_contract_for_llm(
    episode,
):
    """
    v3.10.8

    Python resolves the factual direction of each action channel before the
    LLM sees the episode. This prevents the model from having to reconstruct
    higher/lower/mixed from individual events.

    The contract is factual:
      observed_relation = what Python measured in the comparison lap
      coaching_direction = how an explicit coaching instruction may point
                           toward the reference
    """
    result = {}

    for channel in (
        episode.get(
            "action_channels",
            [],
        )
        or []
    ):
        info = (
            episode.get(
                "action_evidence_by_channel",
                {},
            )
            or {}
        ).get(
            channel,
            {},
        )

        directions = {
            event.get(
                "direction"
            )
            for event in (
                info.get(
                    "events",
                    [],
                )
                or []
            )
            if event.get(
                "direction"
            )
            in {
                "higher_in_comparison_lap",
                "lower_in_comparison_lap",
            }
        }

        if directions == {
            "higher_in_comparison_lap"
        }:
            result[channel] = {
                "observed_relation": "higher_in_comparison_lap",
                "interpretation_relation": "higher",
                "coaching_direction": "decrease",
            }

        elif directions == {
            "lower_in_comparison_lap"
        }:
            result[channel] = {
                "observed_relation": "lower_in_comparison_lap",
                "interpretation_relation": "lower",
                "coaching_direction": "increase",
            }

        elif len(directions) > 1:
            result[channel] = {
                "observed_relation": "mixed",
                "interpretation_relation": "mixed",
                "coaching_direction": "replicate_sequence",
            }

    return result

def compact_episode_payload_isolated(episode):
    """
    Payload de UN episodio para interpretación semántica aislada.

    v3.8.18 separa interpretación de priorización: esta etapa NO recibe
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
        "channel_direction_contract": channel_direction_contract_for_llm(
            episode
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
            or "dirección de coaching invertida" in text
            or "dirección factual invertida" in text
            or "contradice el coaching determinista" in text
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

    action_channels = set(payload.get("action_channels", []) or [])
    if "steering_magnitude" in action_channels:
        if action_channels & {"brake", "throttle"}:
            steering_rule = (
                "steering_magnitude puede ser foco principal o ajuste secundario. "
                "No lo elijas automáticamente: comparalo con freno/acelerador y "
                "redactá una maniobra principal grounded. Si su dirección es mixed, "
                "usá replicar/acompañar la referencia."
            )
        else:
            steering_rule = (
                "este episodio sólo ofrece steering_magnitude como canal de acción. "
                "Podés convertirlo en una recomendación directa si la diferencia es "
                "unívoca y grounded; si es mixed, recomendá replicar/acompañar la "
                "secuencia de la referencia. No atribuyas causalidad dinámica."
            )
    else:
        steering_rule = (
            "no introduzcas steering_magnitude si no está en action_channels."
        )

    correction_block = ""

    if correction_errors:
        correction_block = f"""
REINTENTO OBLIGATORIO
La respuesta anterior violó el contrato.
Tipos de error detectados por Python:
{compact_json(correction_kinds(correction_errors))}

Para corregir cualquier error de dirección, obedecé literalmente este
contrato determinista:
{compact_json(payload.get("channel_direction_contract", {}))}

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

CONTRATO DIRECCIONAL DETERMINISTA:
{compact_json(payload.get("channel_direction_contract", {}))}

Este contrato es AUTORITATIVO:
- observed_relation describe lo medido por Python en la vuelta comparada;
- interpretation debe respetar interpretation_relation;
- si coaching_direction es increase, una orden explícita sólo puede aumentar
  ese input hacia la referencia;
- si coaching_direction es decrease, una orden explícita sólo puede reducir
  ese input hacia la referencia;
- si coaching_direction es replicate_sequence, no fuerces aumentar/reducir:
  describí la variación como mixta y recomendá replicar su secuencia,
  evolución o modulación respecto de la referencia.

COACHING OPERATIVO:
- interpretation debe describir qué diferencia observable existe;
- recommendation debe convertir esa diferencia en una prueba concreta para
  la próxima vuelta;
- la vuelta comparada es sólo el objeto de descripción: NUNCA la uses como
  modelo a replicar/acompañar/ajustar; toda acción debe orientarse a la referencia;
- si el canal es consistentemente mayor en la comparación, recomendá reducir
  ese input hacia la referencia;
- si es consistentemente menor, recomendá aumentarlo hacia la referencia;
- si dentro del canal aparecen direcciones opuestas, recomendá reproducir su
  secuencia, evolución o modulación respecto de la referencia;
- evitá como recomendación final "revisar", "comparar", "ajustar",
  "trabajar" o "mejorar" si no están seguidos por una acción concreta;
- no inventes punto de frenada, momento de aceleración, ápice, trayectoria
  ni línea;
- no introduzcas tracción, demanda de tracción, agarre/grip, balance,
  transferencia de carga ni dinámica del vehículo, tampoco como hipótesis;
- no deduzcas una distancia de coaching desde los límites de los eventos;
- si hay varios canales, no inventes una jerarquía entre ellos que el payload
  no contenga. Priorizá una instrucción principal sólo cuando la evidencia lo
  permita claramente.

STEERING EN ESTA RECOMENDACIÓN:
{steering_rule}

CAUSALIDAD:
- describí coexistencia, asociación o compatibilidad;
- podés usar expresiones prudentes como "podría contribuir";
- no uses "causó", "generó", "provocó", "produjo", "se debe a",
  "debido a" ni "como consecuencia directa".

CONTRATO JSON EXACTO:
- episode_id: entero idéntico al recibido;
- interpretation: string ESTRICTAMENTE CUALITATIVO, sin ningún dígito;
- hypotheses: lista de strings ESTRICTAMENTE CUALITATIVOS, sin ningún dígito;
- recommendation: string ESTRICTAMENTE CUALITATIVO, sin ningún dígito.

REGLA DE CIFRAS PARA ESTE CALL:
- el ÚNICO número permitido en toda tu respuesta es episode_id;
- no copies metros, segundos, porcentajes, número de curva ni ninguna otra
  magnitud del payload dentro de interpretation, hypotheses o recommendation;
- aunque exista un onset/release numérico autorizado en el payload, Python lo
  renderiza por separado: NO lo repitas en estos tres campos de texto.

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

        validate_episode_interpretation_direction(
            interpretation,
            episode,
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

        validate_speed_not_action_target(
            recommendation,
            "recommendation",
            errors,
        )

        validate_episode_steering_secondary_contract(
            recommendation,
            episode,
            errors,
            field_name="recommendation",
        )

        validate_episode_coaching_direction(
            recommendation,
            episode,
            errors,
        )

        validate_reference_lap_is_action_target(
            recommendation,
            "recommendation",
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
    Fallback determinista v3.8.18.

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


def _deterministic_episode_recommendation(episode):
    """Coaching cualitativo derivado sólo del contrato direccional de Python."""
    contract = channel_direction_contract_for_llm(episode)

    labels = {
        ("brake", "increase"):
            "aumentar la aplicación del freno hacia la referencia",
        ("brake", "decrease"):
            "reducir la aplicación del freno hacia la referencia",
        ("brake", "replicate_sequence"):
            "replicar la secuencia y modulación del freno de la referencia",
        ("throttle", "increase"):
            "aumentar el acelerador hacia la referencia",
        ("throttle", "decrease"):
            "reducir el acelerador hacia la referencia",
        ("throttle", "replicate_sequence"):
            "replicar la secuencia y modulación del acelerador de la referencia",
    }

    parts = []
    for channel in (episode.get("action_channels", []) or []):
        info = contract.get(channel, {}) if isinstance(contract, dict) else {}
        direction = info.get("coaching_direction")
        text = labels.get((channel, direction))
        if text and text not in parts:
            parts.append(text)

    if not parts:
        return (
            "mantener esta diferencia como observación; "
            "no hay un target directo de input autorizado"
        )

    return "; ".join(parts)


def build_deterministic_grounded_episode_fallback(episode):
    """
    Texto factual mínimo construido por Python.

    En v3.10.8 también se usa como fuente de reparación selectiva: si una
    respuesta LLM tiene estructura correcta pero invierte un hecho o un target,
    Python reemplaza únicamente el campo narrativo inválido y conserva el resto.
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

    recommendation = _deterministic_episode_recommendation(episode)
    if not recommendation:
        return None

    return {
        "episode_id": episode.get("episode_id"),
        "interpretation": (
            f"se observaron {observation} respecto de la vuelta de referencia"
        ),
        "hypotheses": [],
        "recommendation": recommendation,
    }


def repair_invalid_episode_semantic_fields(response, episode, errors):
    """
    Reparación selectiva v3.10.8 antes de gastar un retry del LLM.

    Sólo actúa cuando schema, tipos e ID ya son correctos y TODOS los errores
    pertenecen a interpretation, recommendation o hypotheses[i]. Los campos
    inválidos se reconstruyen desde hechos autoritativos de Python; el texto LLM
    que pasó validación se conserva. El candidato reparado debe volver a pasar
    por validate_single_episode_llm_response completo.
    """
    if not errors:
        return None, {}

    if not _episode_response_structure_allows_semantic_fallback(
        response,
        episode,
    ):
        return None, {}

    # v3.10.8.5.4: si el único problema de recommendation es que el LLM
    # tomó la vuelta comparada como modelo, corregimos solamente ese destino
    # y preservamos el resto del texto validado.
    target_reference_repairs = []
    target_error_prefix = (
        "recommendation: usa la vuelta comparada como objetivo de coaching"
    )
    if any(str(error).startswith(target_error_prefix) for error in errors):
        repaired_text = repair_comparison_lap_action_target(
            response.get("recommendation")
        )
        if repaired_text != response.get("recommendation"):
            response = dict(response)
            response["recommendation"] = repaired_text
            target_reference_repairs.append("recommendation")
            errors = [
                error for error in errors
                if not str(error).startswith(target_error_prefix)
            ]
            if not errors:
                remaining = validate_single_episode_llm_response(
                    response,
                    episode,
                )
                if not remaining:
                    return response, {
                        "replaced_fields": [],
                        "pruned_hypothesis_indexes": [],
                        "target_reference_repairs": target_reference_repairs,
                    }
                errors = remaining

    deterministic = build_deterministic_grounded_episode_fallback(episode)
    if deterministic is None:
        return None, {}

    repair_interpretation = False
    repair_recommendation = False
    bad_hypotheses = set()

    for error in errors:
        text = str(error).strip().lower()

        if text.startswith("interpretation"):
            repair_interpretation = True
            continue

        if text.startswith("recommendation"):
            repair_recommendation = True
            continue

        index = _parse_list_item_error(error, "hypotheses")
        if index is not None:
            bad_hypotheses.add(index)
            continue

        # Error no atribuible de forma unívoca a texto libre reparable.
        return None, {}

    candidate = dict(response)
    repairs = {
        "replaced_fields": [],
        "pruned_hypothesis_indexes": sorted(bad_hypotheses),
        "target_reference_repairs": target_reference_repairs,
    }

    if repair_interpretation:
        candidate["interpretation"] = deterministic["interpretation"]
        repairs["replaced_fields"].append("interpretation")

    if repair_recommendation:
        candidate["recommendation"] = deterministic["recommendation"]
        repairs["replaced_fields"].append("recommendation")

    if bad_hypotheses:
        hypotheses = list(candidate.get("hypotheses", []))
        if any(index < 0 or index >= len(hypotheses) for index in bad_hypotheses):
            return None, {}
        candidate["hypotheses"] = [
            item
            for index, item in enumerate(hypotheses)
            if index not in bad_hypotheses
        ]

    if (
        not repairs["replaced_fields"]
        and not bad_hypotheses
        and not target_reference_repairs
    ):
        return None, {}

    remaining = validate_single_episode_llm_response(
        candidate,
        episode,
    )
    if remaining:
        return None, {}

    return candidate, repairs


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

        raw = deepseek_chat(
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
                "deterministic_repairs": {},
            }

        repaired, repair_info = repair_invalid_episode_semantic_fields(
            parsed,
            episode,
            errors,
        )

        if repaired is not None:
            fields = repair_info.get("replaced_fields", [])
            pruned = repair_info.get("pruned_hypothesis_indexes", [])
            detail = []
            if fields:
                detail.append("campos=" + ",".join(fields))
            if pruned:
                detail.append(
                    "hipótesis_descartadas="
                    + ",".join(str(index) for index in pruned)
                )

            print(
                f"    Episodio {episode_id}: reparación determinista "
                "v3.10.8 aplicada sin retry"
                + (f" ({'; '.join(detail)})" if detail else "")
                + "."
            )

            return {
                "status": "VALID",
                "attempts": attempt,
                "response": repaired,
                "validation_errors": [],
                "fallback": None,
                "deterministic_repairs": repair_info,
                "pruned_hypothesis_indexes": pruned,
                "original_validation_errors": errors or [],
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
            f"v3.8.18 aplicado; se descartaron "
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
            "v3.8.18 aplicado tras agotar los reintentos."
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



def build_deterministic_comparison_ranker_response(episode_catalog):
    """
    D2.1 shadow — ranker comparativo 100 % determinista.

    Devuelve exactamente el mismo contrato que el ranker LLM actual, pero no
    reemplaza todavía ninguna llamada de producción.

    Autoridades:
    - si global_rank es válido para todo el catálogo, conserva ese orden;
    - de lo contrario reconstruye el mismo orden objetivo desde hechos Python;
    - evidence_strength sólo define los cortes de tier, no reinterpreta
      telemetría ni introduce causalidad.
    """
    if not isinstance(episode_catalog, list) or not episode_catalog:
        raise ValueError(
            "El ranker determinista requiere al menos un episodio."
        )

    episodes = []
    seen_ids = set()

    for episode in episode_catalog:
        if not isinstance(episode, dict):
            raise ValueError(
                "Cada episodio del ranker determinista debe ser objeto."
            )

        episode_id = safe_int(episode.get("episode_id"))
        if episode_id is None:
            raise ValueError(
                "Cada episodio del ranker determinista requiere episode_id."
            )
        if episode_id in seen_ids:
            raise ValueError(
                f"episode_id duplicado en ranker determinista: {episode_id}"
            )

        seen_ids.add(episode_id)
        episodes.append(episode)

    global_ranks = [
        safe_int(episode.get("global_rank"))
        for episode in episodes
    ]
    usable_global_rank = (
        all(
            rank is not None and rank >= 1
            for rank in global_ranks
        )
        and len(set(global_ranks)) == len(global_ranks)
    )

    if usable_global_rank:
        ordered = sorted(
            episodes,
            key=lambda episode: (
                safe_int(episode.get("global_rank")),
                safe_int(episode.get("episode_id")),
            ),
        )
    else:
        evidence_priority = {
            "strong": 2,
            "moderate": 1,
            "weak": 0,
        }

        ordered = sorted(
            episodes,
            key=lambda episode: (
                -(
                    _finite_number(
                        episode.get("action_time_loss_s")
                    )
                    or 0.0
                ),
                -evidence_priority.get(
                    episode.get("evidence_strength"),
                    0,
                ),
                -(
                    safe_int(
                        episode.get("action_channel_count")
                    )
                    or 0
                ),
                -(
                    _finite_number(
                        episode.get("length_m")
                    )
                    or 0.0
                ),
                safe_int(episode.get("episode_id")),
            ),
        )

    ordered_episode_ids = [
        safe_int(episode.get("episode_id"))
        for episode in ordered
    ]

    n = len(ordered)

    # PRIORITARIO:
    # - siempre existe al menos uno;
    # - si el líder es strong, conserva el bloque strong inicial;
    # - con N > 1 nunca todos quedan PRIORITARIO, igual que el contrato LLM.
    if n == 1:
        priority_cut_rank = 1
    elif ordered[0].get("evidence_strength") == "strong":
        strong_prefix = 0
        for episode in ordered:
            if episode.get("evidence_strength") != "strong":
                break
            strong_prefix += 1

        priority_cut_rank = max(
            1,
            min(strong_prefix, n - 1),
        )
    else:
        priority_cut_rank = 1

    # NO_ACCIONABLE:
    # sólo el sufijo final consecutivo de evidencia weak.
    # Un weak intercalado no puede crear un corte que arrastre evidencia mejor.
    weak_suffix_start = n + 1

    for rank in range(n, 0, -1):
        episode = ordered[rank - 1]
        if episode.get("evidence_strength") != "weak":
            break
        weak_suffix_start = rank

    # El contrato exige que NO_ACCIONABLE empiece después del último
    # PRIORITARIO. Si todos son weak, el líder sigue siendo la mejor
    # oportunidad relativa de la comparación.
    no_actionable_start_rank = max(
        weak_suffix_start,
        priority_cut_rank + 1,
    )

    return {
        "ordered_episode_ids": ordered_episode_ids,
        "priority_cut_rank": priority_cut_rank,
        "no_actionable_start_rank": no_actionable_start_rank,
    }

PRIORITY_COVERAGE_TARGET = 0.55


def build_calibrated_priority_cut_rank(
    episode_catalog,
    ordered_episode_ids,
    *,
    coverage_target=PRIORITY_COVERAGE_TARGET,
):
    # D2.3 shadow: smallest deterministic loss-coverage prefix.
    ordered_episode_ids = [
        safe_int(value)
        for value in ordered_episode_ids
    ]
    if not ordered_episode_ids or any(
        value is None for value in ordered_episode_ids
    ):
        raise ValueError(
            "El corte calibrado requiere IDs de episodio válidos."
        )
    if not 0.0 < coverage_target <= 1.0:
        raise ValueError(
            "coverage_target debe estar en el intervalo (0, 1]."
        )

    by_id = {
        safe_int(episode.get("episode_id")): episode
        for episode in episode_catalog
        if isinstance(episode, dict)
    }
    if set(ordered_episode_ids) != set(by_id):
        raise ValueError(
            "El orden calibrado no coincide con episode_catalog."
        )

    losses = []
    for episode_id in ordered_episode_ids:
        loss = _finite_number(
            by_id[episode_id].get("action_time_loss_s")
        )
        losses.append(
            max(0.0, loss) if loss is not None else 0.0
        )

    n = len(ordered_episode_ids)
    if n == 1:
        return 1

    total = sum(losses)
    if total <= 0.0:
        return 1

    cumulative = 0.0
    cut = 1
    for rank, loss in enumerate(losses, start=1):
        cumulative += loss
        cut = rank
        if cumulative / total >= coverage_target:
            break

    return max(1, min(cut, n - 1))


def build_calibrated_comparison_ranker_response(
    episode_catalog,
    *,
    deterministic_response=None,
    coverage_target=PRIORITY_COVERAGE_TARGET,
):
    # D2.3 shadow candidate: keep deterministic order/NO_ACCIONABLE policy,
    # replace only priority_cut_rank with the calibrated loss-coverage cut.
    if deterministic_response is None:
        deterministic_response = (
            build_deterministic_comparison_ranker_response(
                episode_catalog
            )
        )

    ordered_episode_ids = list(
        deterministic_response["ordered_episode_ids"]
    )
    priority_cut_rank = build_calibrated_priority_cut_rank(
        episode_catalog,
        ordered_episode_ids,
        coverage_target=coverage_target,
    )
    no_actionable_start_rank = max(
        deterministic_response["no_actionable_start_rank"],
        priority_cut_rank + 1,
    )

    response = {
        "ordered_episode_ids": ordered_episode_ids,
        "priority_cut_rank": priority_cut_rank,
        "no_actionable_start_rank": no_actionable_start_rank,
    }
    errors = validate_comparison_ranker_response(
        response,
        episode_catalog,
    )
    if errors:
        raise ValueError(
            "El ranker calibrado shadow no cumple el contrato: "
            + "; ".join(errors)
        )
    return response


NO_ACTIONABLE_WEAK_SHARE_MAX = 0.05
NO_ACTIONABLE_MODERATE_SHARE_MAX = 0.04
NO_ACTIONABLE_STRONG_SHARE_MAX = 0.01


def build_calibrated_no_actionable_start_rank(
    episode_catalog,
    ordered_episode_ids,
    *,
    priority_cut_rank,
    weak_share_max=NO_ACTIONABLE_WEAK_SHARE_MAX,
    moderate_share_max=NO_ACTIONABLE_MODERATE_SHARE_MAX,
    strong_share_max=NO_ACTIONABLE_STRONG_SHARE_MAX,
):
    # D2.4 shadow: evidence-conditioned negligible-loss tail.
    ordered_episode_ids = [
        safe_int(value)
        for value in ordered_episode_ids
    ]
    if not ordered_episode_ids or any(
        value is None for value in ordered_episode_ids
    ):
        raise ValueError(
            "El corte NO_ACCIONABLE calibrado requiere IDs válidos."
        )

    thresholds = {
        "weak": weak_share_max,
        "moderate": moderate_share_max,
        "strong": strong_share_max,
    }
    if any(
        not 0.0 <= value <= 1.0
        for value in thresholds.values()
    ):
        raise ValueError(
            "Los thresholds NO_ACCIONABLE deben estar en [0, 1]."
        )

    n = len(ordered_episode_ids)
    if not 1 <= priority_cut_rank <= n:
        raise ValueError("priority_cut_rank fuera de rango.")

    by_id = {
        safe_int(episode.get("episode_id")): episode
        for episode in episode_catalog
        if isinstance(episode, dict)
    }
    if set(ordered_episode_ids) != set(by_id):
        raise ValueError(
            "El orden calibrado no coincide con episode_catalog."
        )

    losses = []
    for episode_id in ordered_episode_ids:
        loss = _finite_number(
            by_id[episode_id].get("action_time_loss_s")
        )
        losses.append(
            max(0.0, loss) if loss is not None else 0.0
        )

    total_loss = sum(losses)
    if total_loss <= 0.0:
        return n + 1

    no_actionable_start_rank = n + 1
    for rank in range(n, priority_cut_rank, -1):
        episode = by_id[ordered_episode_ids[rank - 1]]
        evidence = str(
            episode.get("evidence_strength") or ""
        ).strip().lower()
        threshold = thresholds.get(evidence, 0.0)
        share = losses[rank - 1] / total_loss

        if share > threshold:
            break
        no_actionable_start_rank = rank

    return max(
        no_actionable_start_rank,
        priority_cut_rank + 1,
    )


def build_calibrated_no_actionable_comparison_ranker_response(
    episode_catalog,
    *,
    calibrated_priority_response=None,
):
    # D2.4 shadow candidate: keep D2.3 order/priority cut and calibrate
    # only the NO_ACCIONABLE boundary.
    if calibrated_priority_response is None:
        calibrated_priority_response = (
            build_calibrated_comparison_ranker_response(
                episode_catalog
            )
        )

    ordered_episode_ids = list(
        calibrated_priority_response["ordered_episode_ids"]
    )
    priority_cut_rank = calibrated_priority_response[
        "priority_cut_rank"
    ]
    no_actionable_start_rank = (
        build_calibrated_no_actionable_start_rank(
            episode_catalog,
            ordered_episode_ids,
            priority_cut_rank=priority_cut_rank,
        )
    )

    response = {
        "ordered_episode_ids": ordered_episode_ids,
        "priority_cut_rank": priority_cut_rank,
        "no_actionable_start_rank": no_actionable_start_rank,
    }
    errors = validate_comparison_ranker_response(
        response,
        episode_catalog,
    )
    if errors:
        raise ValueError(
            "El ranker NO_ACCIONABLE calibrado no cumple el contrato: "
            + "; ".join(errors)
        )
    return response


def build_deterministic_ranker_shadow_audit(
    episode_catalog,
    llm_ranker_response,
):
    """
    D2.2 shadow — compara el ranker LLM autoritativo con el ranker
    determinista sin alterar ninguna clasificación de producción.

    El audit conserva ambas clasificaciones completas para poder diagnosticar
    divergencias por episodio cuando haya sesiones reales disponibles.
    """
    llm_errors = validate_comparison_ranker_response(
        llm_ranker_response,
        episode_catalog,
    )
    if llm_errors:
        raise ValueError(
            "El ranker LLM recibido por el shadow no cumple el contrato: "
            + "; ".join(llm_errors)
        )

    deterministic_response = (
        build_deterministic_comparison_ranker_response(
            episode_catalog
        )
    )
    deterministic_errors = validate_comparison_ranker_response(
        deterministic_response,
        episode_catalog,
    )
    if deterministic_errors:
        raise ValueError(
            "El ranker determinista shadow no cumple el contrato: "
            + "; ".join(deterministic_errors)
        )

    llm_classifications = derive_priority_classifications(
        llm_ranker_response,
        episode_catalog,
    )
    deterministic_classifications = derive_priority_classifications(
        deterministic_response,
        episode_catalog,
    )

    calibrated_response = build_calibrated_comparison_ranker_response(
        episode_catalog,
        deterministic_response=deterministic_response,
    )
    calibrated_classifications = derive_priority_classifications(
        calibrated_response,
        episode_catalog,
    )
    calibrated_agreement = {
        "ordered_episode_ids": (
            calibrated_response["ordered_episode_ids"]
            == llm_ranker_response["ordered_episode_ids"]
        ),
        "priority_cut_rank": (
            calibrated_response["priority_cut_rank"]
            == llm_ranker_response["priority_cut_rank"]
        ),
        "no_actionable_start_rank": (
            calibrated_response["no_actionable_start_rank"]
            == llm_ranker_response["no_actionable_start_rank"]
        ),
        "classifications": (
            calibrated_classifications == llm_classifications
        ),
    }
    calibrated_agreement["full"] = all(
        calibrated_agreement.values()
    )

    calibrated_no_actionable_response = (
        build_calibrated_no_actionable_comparison_ranker_response(
            episode_catalog,
            calibrated_priority_response=calibrated_response,
        )
    )
    calibrated_no_actionable_classifications = (
        derive_priority_classifications(
            calibrated_no_actionable_response,
            episode_catalog,
        )
    )
    calibrated_no_actionable_agreement = {
        "ordered_episode_ids": (
            calibrated_no_actionable_response["ordered_episode_ids"]
            == llm_ranker_response["ordered_episode_ids"]
        ),
        "priority_cut_rank": (
            calibrated_no_actionable_response["priority_cut_rank"]
            == llm_ranker_response["priority_cut_rank"]
        ),
        "no_actionable_start_rank": (
            calibrated_no_actionable_response[
                "no_actionable_start_rank"
            ]
            == llm_ranker_response["no_actionable_start_rank"]
        ),
        "classifications": (
            calibrated_no_actionable_classifications
            == llm_classifications
        ),
    }
    calibrated_no_actionable_agreement["full"] = all(
        calibrated_no_actionable_agreement.values()
    )

    agreement = {
        "ordered_episode_ids": (
            deterministic_response["ordered_episode_ids"]
            == llm_ranker_response["ordered_episode_ids"]
        ),
        "priority_cut_rank": (
            deterministic_response["priority_cut_rank"]
            == llm_ranker_response["priority_cut_rank"]
        ),
        "no_actionable_start_rank": (
            deterministic_response["no_actionable_start_rank"]
            == llm_ranker_response["no_actionable_start_rank"]
        ),
        "classifications": (
            deterministic_classifications == llm_classifications
        ),
    }
    agreement["full"] = all(agreement.values())

    return {
        "status": "VALID",
        "response": deterministic_response,
        "agreement": agreement,
        "llm_classifications": llm_classifications,
        "deterministic_classifications": deterministic_classifications,
        "calibrated_candidate": {
            "coverage_target": PRIORITY_COVERAGE_TARGET,
            "response": calibrated_response,
            "agreement": calibrated_agreement,
            "classifications": calibrated_classifications,
        },
        "calibrated_no_actionable_candidate": {
            "weak_share_max": NO_ACTIONABLE_WEAK_SHARE_MAX,
            "moderate_share_max": NO_ACTIONABLE_MODERATE_SHARE_MAX,
            "strong_share_max": NO_ACTIONABLE_STRONG_SHARE_MAX,
            "response": calibrated_no_actionable_response,
            "agreement": calibrated_no_actionable_agreement,
            "classifications": (
                calibrated_no_actionable_classifications
            ),
        },
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

        raw = deepseek_chat(
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
La conclusion debe resumir la acción de coaching más importante ya presente
en las evaluaciones, no limitarse a decir que existen diferencias.
La vuelta comparada puede aparecer en observaciones descriptivas, pero NUNCA
como modelo/objetivo de la conclusion: toda acción debe apuntar a la referencia.
Conservá verbos operativos como reducir, aumentar o replicar cuando estén
respaldados por las recomendaciones validadas.
Steering/dirección puede permanecer en la conclusion como coaching validado.
Si los episodios contienen direcciones de steering_magnitude distintas entre sí,
NO sintetices una orden global de aumentar/reducir volante: usá una formulación
neutral de replicar/acompañar la dirección hacia la referencia. Si la dirección
es unívoca, una orden direccional debe respetar esa evidencia. No elimines por
esto una acción válida de freno/acelerador ya presente en las evaluaciones.
No sustituyas una recomendación concreta por "revisar", "comparar",
"ajustar", "trabajar" o "mejorar".
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

        validate_speed_not_action_target(
            conclusion,
            "conclusion",
            errors,
        )

        validate_summary_steering_secondary_contract(
            conclusion,
            episode_catalog,
            errors,
        )

        validate_reference_lap_is_action_target(
            conclusion,
            "conclusion",
            errors,
        )

    return errors



def _neutral_summary_recommendation_from_validated(recommendation):
    """
    v3.10.8.5.4 hotfix.

    Convierte una recomendación individual YA validada en una formulación
    neutral por canal. Se usa únicamente cuando el resumen de comparación no
    puede conservar una orden direccional de steering porque los episodios
    agregados muestran sentidos distintos. No introduce canales nuevos: sólo
    usa los mencionados en la recomendación validada.
    """
    if not isinstance(recommendation, str):
        return None

    channels = _channels_mentioned_in_text(recommendation)
    parts = []

    if "brake" in channels:
        parts.append("replicá la aplicación de freno hacia la referencia")
    if "throttle" in channels:
        parts.append("replicá la secuencia de acelerador hacia la referencia")
    if "steering_magnitude" in channels:
        parts.append("acompañá la dirección hacia la referencia")

    if not parts:
        return None

    text = "; ".join(parts).strip()
    if not text:
        return None
    return text[0].upper() + text[1:] + "."


def build_deterministic_comparison_summary(
    episode_assessments,
    episode_catalog,
):
    """
    v3.10.8.5.4 hotfix.

    Construye una síntesis mínima exclusivamente desde evaluaciones de episodio
    que YA fueron validadas individualmente por Python. Se usa sólo cuando el
    LLM de resumen insiste en violar el contrato después de los reintentos.

    No reinterpreta telemetría, no introduce números y no convierte velocidad
    en acción. La conclusión se copia de una recomendación ya validada; por
    eso una falla puramente narrativa nunca debe abortar toda la comparación.
    """
    if not isinstance(episode_assessments, list):
        return None

    classification_order = {
        "PRIORITARIO": 0,
        "SECUNDARIO": 1,
        "NO_ACCIONABLE": 2,
    }

    ordered = sorted(
        [item for item in episode_assessments if isinstance(item, dict)],
        key=lambda item: (
            classification_order.get(item.get("classification"), 99),
            safe_int(item.get("episode_id")) or 999999,
        ),
    )

    observations = []
    for item in ordered:
        text = str(item.get("interpretation") or "").strip()
        if text and text not in observations:
            observations.append(text)
        if len(observations) >= 2:
            break

    conclusion = None
    for item in ordered:
        if item.get("classification") == "NO_ACCIONABLE":
            continue
        text = str(item.get("recommendation") or "").strip()
        if text:
            conclusion = text
            break

    if conclusion is None:
        for item in ordered:
            text = str(item.get("recommendation") or "").strip()
            if text:
                conclusion = text
                break

    if conclusion is None:
        for item in ordered:
            text = str(item.get("interpretation") or "").strip()
            if text:
                conclusion = text
                break

    if conclusion is None:
        return None

    candidate = {
        "comparison_observations": observations,
        "limitations": [],
        "conclusion": conclusion,
    }

    errors = validate_comparison_summary_llm_response(
        candidate,
        episode_catalog,
    )
    if not errors:
        return candidate

    # v3.10.8.5.4: una recomendación puede ser válida a nivel de episodio
    # pero dejar de ser direccionalmente válida al sintetizar varios episodios
    # con steering en sentidos opuestos. En ese caso neutralizamos solamente
    # los canales ya presentes en la recomendación validada y revalidamos.
    if _steering_direct_action_present(conclusion):
        directions = _comparison_secondary_steering_directions(episode_catalog)
        if len(directions) != 1:
            neutral = _neutral_summary_recommendation_from_validated(conclusion)
            if neutral:
                neutral_candidate = dict(candidate)
                neutral_candidate["conclusion"] = neutral
                neutral_errors = validate_comparison_summary_llm_response(
                    neutral_candidate,
                    episode_catalog,
                )
                if not neutral_errors:
                    return neutral_candidate

    # La observación agregada es opcional. Si una combinación de episodios
    # produce una colisión semántica inesperada, conservamos sólo la
    # recomendación individual ya validada.
    candidate["comparison_observations"] = []
    errors = validate_comparison_summary_llm_response(
        candidate,
        episode_catalog,
    )
    if not errors:
        return candidate

    if _steering_direct_action_present(conclusion):
        directions = _comparison_secondary_steering_directions(episode_catalog)
        if len(directions) != 1:
            neutral = _neutral_summary_recommendation_from_validated(conclusion)
            if neutral:
                candidate["conclusion"] = neutral
                errors = validate_comparison_summary_llm_response(
                    candidate,
                    episode_catalog,
                )
                if not errors:
                    return candidate

    return None

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

        raw = deepseek_chat(
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

        target_reference_repairs = []
        target_error_prefix = (
            "conclusion: usa la vuelta comparada como objetivo de coaching"
        )
        if any(str(error).startswith(target_error_prefix) for error in errors):
            repaired_conclusion = repair_comparison_lap_action_target(
                parsed.get("conclusion")
            )
            if repaired_conclusion != parsed.get("conclusion"):
                repaired = dict(parsed)
                repaired["conclusion"] = repaired_conclusion
                repaired_errors = validate_comparison_summary_llm_response(
                    repaired,
                    episode_catalog,
                )
                if not repaired_errors:
                    return {
                        "status": "VALID",
                        "attempts": attempt,
                        "response": repaired,
                        "validation_errors": [],
                        "deterministic_repairs": {
                            "target_reference": ["conclusion"]
                        },
                    }
                parsed = repaired
                errors = repaired_errors

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
            "    Resumen: fallback determinista v3.8.18 "
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

    deterministic_summary = build_deterministic_comparison_summary(
        episode_assessments,
        episode_catalog,
    )
    if deterministic_summary is not None:
        print(
            "    Resumen: fallback determinista v3.10.8.5.4 aplicado; "
            "la síntesis se reconstruyó desde episodios ya validados."
        )
        return {
            "status": "VALID",
            "attempts": MAX_LLM_VALIDATION_ATTEMPTS,
            "response": deterministic_summary,
            "validation_errors": [],
            "fallback": "DETERMINISTIC_FROM_VALIDATED_EPISODES",
            "pruned_summary_items": {},
            "original_validation_errors": errors or [],
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
    v3.8.18:
    1) interpreta cada episodio en aislamiento SIN clasificar prioridad;
    2) clasifica prioridad en una llamada comparativa separada;
    3) sintetiza la comparación con evaluaciones ya grounded y clasificadas.

    El contrato externo histórico de llm_structured se conserva.
    """
    episode_assessments = []
    attempt_counts = []
    episode_audit = []

    print(
        "  Modo aislado v3.8.18: interpretación por episodio + "
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
            "deterministic_repairs": validated.get(
                "deterministic_repairs", {}
            ),
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

    try:
        deterministic_ranker_shadow = (
            build_deterministic_ranker_shadow_audit(
                episode_catalog,
                ranker["response"],
            )
        )
    except Exception as exc:
        # D2.2 is observational only: a shadow failure must never alter,
        # reject or block the LLM-authoritative production path.
        deterministic_ranker_shadow = {
            "status": "ERROR",
            "error": str(exc),
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
                "priority_ranking": {
                    "attempts": ranker["attempts"],
                    "deterministic_shadow": deterministic_ranker_shadow,
                },
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
                "priority_ranking": {
                    "attempts": ranker["attempts"],
                    "deterministic_shadow": deterministic_ranker_shadow,
                },
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
            "deterministic_shadow": deterministic_ranker_shadow,
        },
        "summary": {
            "attempts": summary["attempts"],
            "fallback": summary.get("fallback"),
            "pruned_summary_items": summary.get("pruned_summary_items", {}),
            "deterministic_repairs": summary.get("deterministic_repairs", {}),
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


def format_lap_time(value):
    """
    Formato visible de tiempo absoluto de vuelta: m:ss.mmm.

    Los valores objetivos permanecen almacenados internamente en segundos;
    esta función sólo afecta presentación. Los deltas siguen usando
    signed_seconds().
    """
    value = safe_float(
        value
    )

    if value is None:
        return "N/D"

    if value < 0:
        sign = "-"
        value = abs(value)
    else:
        sign = ""

    minutes = int(value // 60)
    seconds = value - (minutes * 60)

    return f"{sign}{minutes}:{seconds:06.3f}"


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

def _episode_authorized_driver_cues(episode, max_cues=2):
    """
    Cues del debrief individual basados sólo en puntos físicos autorizados.
    Steering y diferencias genéricas de nivel quedan como observación.
    """
    if not isinstance(episode, dict):
        return []

    def point(value, later_text, earlier_text):
        if not isinstance(value, dict):
            return None
        if value.get("status") != "VALID" or not value.get("authorized_numeric_coaching"):
            return None
        magnitude = safe_int(value.get("coaching_magnitude_m"))
        direction = value.get("coaching_direction")
        if magnitude is None:
            return None
        if direction == "later":
            return later_text.format(magnitude=magnitude)
        if direction == "earlier":
            return earlier_text.format(magnitude=magnitude)
        return None

    cues = []
    brake_onset = point(
        episode.get("braking_point_comparison"),
        "frená aproximadamente {magnitude} m más tarde",
        "frená aproximadamente {magnitude} m más temprano",
    )
    brake_release = point(
        episode.get("brake_release_point_comparison"),
        "soltá el freno aproximadamente {magnitude} m más tarde",
        "soltá el freno aproximadamente {magnitude} m más temprano",
    )
    if brake_onset or brake_release:
        cues.append({
            "channel": "brake",
            "text": " y ".join(v for v in (brake_onset, brake_release) if v),
            "source": "authorized_brake_onset_release",
        })

    throttle_onset = point(
        episode.get("throttle_onset_point_comparison"),
        "reaplicá el acelerador aproximadamente {magnitude} m más tarde",
        "reaplicá el acelerador aproximadamente {magnitude} m más temprano",
    )
    throttle_release = point(
        episode.get("throttle_release_point_comparison"),
        "soltá el acelerador aproximadamente {magnitude} m más tarde",
        "soltá el acelerador aproximadamente {magnitude} m más temprano",
    )
    if throttle_onset or throttle_release:
        cues.append({
            "channel": "throttle",
            "text": " y ".join(v for v in (throttle_onset, throttle_release) if v),
            "source": "authorized_throttle_onset_release",
        })

    return cues[:max_cues]


def _episode_validated_steering_cue(episode, assessment):
    """
    Convierte una recomendación de steering YA validada por Python en wording
    driver-facing determinista. El LLM decide si steering merece coaching;
    Python conserva la dirección objetiva.
    """
    if not isinstance(episode, dict) or not isinstance(assessment, dict):
        return None
    if "steering_magnitude" not in set(episode.get("action_channels", []) or []):
        return None
    recommendation = str(assessment.get("recommendation") or "").strip()
    if not recommendation or not _steering_direct_action_present(recommendation):
        return None

    observed = _single_objective_channel_direction(
        episode,
        "steering_magnitude",
    )
    if observed == "higher_in_comparison_lap":
        text = "reducí la magnitud del volante hacia la referencia"
    elif observed == "lower_in_comparison_lap":
        text = "aumentá la magnitud del volante hacia la referencia"
    else:
        text = "replicá la secuencia de dirección de la referencia"

    return {
        "channel": "steering_magnitude",
        "kind": "validated_llm_steering",
        "text": text,
        "source": "validated_llm_recommendation+python_direction",
    }


def _compose_episode_driver_cue_text(physical_cues, steering_cue):
    physical_texts = [
        str(cue.get("text") or "").strip()
        for cue in (physical_cues or [])[:2]
        if isinstance(cue, dict) and str(cue.get("text") or "").strip()
    ]
    if physical_texts:
        text = "; ".join(physical_texts)
        if steering_cue and str(steering_cue.get("text") or "").strip():
            text += "; como ajuste de volante, " + str(steering_cue["text"]).strip()
        return text
    if steering_cue:
        return str(steering_cue.get("text") or "").strip()
    return ""


def _comparison_actionable_focus(episode_catalog, structured_response):
    """Cierre driver-facing con cues físicos + steering validado sin saturarlo."""
    amap = assessment_map(structured_response)
    ranked = []
    for episode in episode_catalog:
        assessment = amap.get(episode.get("episode_id"), {})
        classification = assessment.get("classification")
        class_rank = {"PRIORITARIO": 0, "SECUNDARIO": 1}.get(classification, 2)
        physical_cues = _episode_authorized_driver_cues(episode)
        steering_cue = _episode_validated_steering_cue(episode, assessment)

        steering_only = bool(steering_cue and not physical_cues)
        if steering_only and classification != "PRIORITARIO":
            continue
        if not physical_cues and not steering_cue:
            continue

        ranked.append((
            1 if steering_only else 0,
            class_rank,
            safe_int(episode.get("global_rank")) or safe_int(episode.get("rank")) or 999999,
            -abs(safe_float(episode.get("action_time_loss_s")) or 0.0),
            episode,
            physical_cues,
            steering_cue,
        ))

    if not ranked:
        return None

    ranked.sort(key=lambda row: row[:4])
    parts = []
    steering_only_used = False
    for steering_only_rank, _, _, _, episode, physical_cues, steering_cue in ranked:
        steering_only = bool(steering_only_rank)
        if steering_only and steering_only_used:
            continue
        text = _compose_episode_driver_cue_text(physical_cues, steering_cue)
        if not text:
            continue
        location = track_location_label(episode)
        prefix = f"{location}: " if location else ""
        parts.append(prefix + text)
        steering_only_used = steering_only_used or steering_only
        if len(parts) >= 2:
            break

    if not parts:
        return None
    return "Para la próxima vuelta, priorizá " + "; ".join(parts) + "."


def render_comparison_analysis(
    comparison,
    episode_catalog,
    structured_response,
):
    """
    Presentación v2.1.

    El JSON conserva toda la evidencia granular. Este render prioriza una
    lectura de debrief: resultado -> lectura -> acciones -> respaldo técnico.
    """
    amap = assessment_map(structured_response)
    lines = []

    ref_lap = comparison["reference_lap"]
    cmp_lap = comparison["comparison_lap"]

    lines.append(f"# Debrief de vuelta — {ref_lap} → {cmp_lap}")
    lines.append("")

    lines.append("## Lectura rápida")
    lines.append("")
    def prose(value):
        value = str(value or "").strip()
        if not value:
            return ""
        value = value[0].upper() + value[1:]
        if value[-1] not in ".!?":
            value += "."
        return value

    lines.append(
        f"La vuelta {cmp_lap} quedó en "
        f"{format_lap_time(comparison['comparison_time_s'])}, "
        f"{signed_seconds(comparison['comparison_minus_reference_s'])} "
        f"respecto de la referencia de "
        f"{format_lap_time(comparison['reference_time_s'])}."
    )

    actionable_focus = _comparison_actionable_focus(
        episode_catalog,
        structured_response,
    )
    if actionable_focus:
        conclusion = prose(actionable_focus)
    else:
        conclusion = (
            "No hay un punto físico onset/release autorizado para convertir "
            "esta comparación en una instrucción directa; las diferencias de "
            "inputs quedan como observación."
        )
    if conclusion:
        lines.append("")
        lines.append(conclusion)

    priority_episodes = [
        episode
        for episode in episode_catalog
        if amap[episode["episode_id"]]["classification"] == "PRIORITARIO"
    ]

    secondary_episodes = [
        episode
        for episode in episode_catalog
        if amap[episode["episode_id"]]["classification"] == "SECUNDARIO"
    ]

    non_actionable = [
        episode
        for episode in episode_catalog
        if amap[episode["episode_id"]]["classification"] == "NO_ACCIONABLE"
    ]

    def strength_label(value):
        return {
            "strong": "alta",
            "moderate": "media",
            "weak": "baja",
        }.get(str(value).lower(), str(value) if value else None)

    # Evita que una comparación con muchos episodios de steering termine
    # convertida en una lista de órdenes de volante. Sólo el steering-only
    # PRIORITARIO mejor rankeado puede subir a Qué probar; steering que acompaña
    # un cue físico brake/throttle no consume este cupo.
    standalone_steering_priority_id = None
    for candidate in priority_episodes:
        candidate_assessment = amap.get(candidate.get("episode_id"), {})
        if _episode_authorized_driver_cues(candidate):
            continue
        if _episode_validated_steering_cue(candidate, candidate_assessment):
            standalone_steering_priority_id = candidate.get("episode_id")
            break

    def spatial_facts(episode):
        facts = []

        bp = episode.get("braking_point_comparison")
        if isinstance(bp, dict) and bp.get("status") == "VALID":
            delta = safe_float(bp.get("comparison_minus_reference_m"))
            direction = bp.get("relative_direction")
            magnitude = safe_float(bp.get("coaching_magnitude_m"))
            coach = bp.get("coaching_direction")
            if direction == "similar_to_reference":
                facts.append("inicio de frenada dentro de la zona muerta")
            elif delta is not None:
                where = "antes" if delta < 0 else "después"
                item = f"inicio de frenada {abs(delta):.0f} m {where} de la referencia"
                if bp.get("authorized_numeric_coaching") and magnitude is not None:
                    move = "más tarde" if coach == "later" else "más temprano"
                    item += f"; objetivo {magnitude:.0f} m {move}"
                facts.append(item)

        br = episode.get("brake_release_point_comparison")
        if isinstance(br, dict) and br.get("status") == "VALID":
            delta = safe_float(br.get("comparison_minus_reference_m"))
            direction = br.get("relative_direction")
            magnitude = safe_float(br.get("coaching_magnitude_m"))
            coach = br.get("coaching_direction")
            if direction == "similar_to_reference":
                facts.append("liberación de freno dentro de la zona muerta")
            elif delta is not None:
                where = "antes" if delta < 0 else "después"
                item = f"liberación de freno {abs(delta):.0f} m {where} de la referencia"
                if br.get("authorized_numeric_coaching") and magnitude is not None:
                    move = "más tarde" if coach == "later" else "más temprano"
                    item += f"; objetivo {magnitude:.0f} m {move}"
                facts.append(item)

        to = episode.get("throttle_onset_point_comparison")
        if isinstance(to, dict) and to.get("status") == "VALID":
            delta = safe_float(to.get("comparison_minus_reference_m"))
            direction = to.get("relative_direction")
            magnitude = safe_float(to.get("coaching_magnitude_m"))
            coach = to.get("coaching_direction")
            if direction == "similar_to_reference":
                facts.append("reaplicación de acelerador dentro de la zona muerta")
            elif delta is not None:
                where = "antes" if delta < 0 else "después"
                item = f"reaplicación de acelerador {abs(delta):.0f} m {where} de la referencia"
                if to.get("authorized_numeric_coaching") and magnitude is not None:
                    move = "más tarde" if coach == "later" else "más temprano"
                    item += f"; objetivo {magnitude:.0f} m {move}"
                facts.append(item)

        tr = episode.get("throttle_release_point_comparison")
        if isinstance(tr, dict) and tr.get("status") == "VALID":
            delta = safe_float(tr.get("comparison_minus_reference_m"))
            direction = tr.get("relative_direction")
            magnitude = safe_float(tr.get("coaching_magnitude_m"))
            coach = tr.get("coaching_direction")
            if direction == "similar_to_reference":
                facts.append("liberación de acelerador dentro de la zona muerta")
            elif delta is not None:
                where = "antes" if delta < 0 else "después"
                item = f"liberación de acelerador {abs(delta):.0f} m {where} de la referencia"
                if tr.get("authorized_numeric_coaching") and magnitude is not None:
                    move = "más tarde" if coach == "later" else "más temprano"
                    item += f"; objetivo {magnitude:.0f} m {move}"
                facts.append(item)

        ft = episode.get(
            "throttle_full_throttle_attainment_comparison"
        )
        if isinstance(ft, dict) and ft.get("status") == "VALID":
            relation = ft.get("relative_direction")
            delta = safe_float(
                ft.get("comparison_minus_reference_m")
            )

            if (
                relation
                in {
                    "earlier_in_comparison_lap",
                    "later_in_comparison_lap",
                }
                and delta is not None
            ):
                where = (
                    "antes"
                    if delta < 0
                    else "después"
                )
                facts.append(
                    "acelerador casi pleno confirmado "
                    f"{abs(delta):.0f} m {where} de la referencia "
                    "(observacional)"
                )
            elif relation == "similar_to_reference":
                facts.append(
                    "acelerador casi pleno confirmado en un punto "
                    "similar a la referencia (observacional)"
                )
            elif relation == "reference_attained_comparison_not_confirmed":
                facts.append(
                    "la referencia alcanzó acelerador casi pleno confirmado; "
                    "la vuelta comparada no lo confirmó en el mismo evento "
                    "(observacional)"
                )
            elif relation == "comparison_attained_reference_not_confirmed":
                facts.append(
                    "la vuelta comparada alcanzó acelerador casi pleno "
                    "confirmado; la referencia no lo confirmó en el mismo "
                    "evento (observacional)"
                )

        pl = episode.get(
            "throttle_partial_lift_comparison"
        )
        if isinstance(pl, dict) and pl.get("status") == "VALID":
            ref_count = safe_int(
                pl.get("reference_partial_lift_count")
            )
            cmp_count = safe_int(
                pl.get("comparison_partial_lift_count")
            )

            if ref_count is not None and cmp_count is not None:
                facts.append(
                    "lifts parciales recuperados: "
                    f"referencia {ref_count}, comparación {cmp_count} "
                    "(observacional)"
                )

        return facts

    def render_episode(episode, ordinal=None):
        episode_id = episode["episode_id"]
        assessment = amap[episode_id]
        location = track_location_label(episode)
        heading = location or f"Episodio #{episode_id}"
        if ordinal is not None:
            lines.append(f"### {ordinal}. {heading}")
        else:
            lines.append(f"### {heading}")
        lines.append("")

        interpretation = prose(assessment.get("interpretation"))
        if interpretation:
            lines.append(interpretation)
            lines.append("")

        driver_cues = _episode_authorized_driver_cues(episode)
        steering_cue = _episode_validated_steering_cue(episode, assessment)
        classification = assessment.get("classification")
        cue_text = ""
        if driver_cues:
            cue_text = _compose_episode_driver_cue_text(driver_cues, steering_cue)
        elif (
            steering_cue
            and classification == "PRIORITARIO"
            and episode_id == standalone_steering_priority_id
        ):
            cue_text = _compose_episode_driver_cue_text([], steering_cue)

        if cue_text:
            lines.append(
                "**Qué probar:** "
                + prose(cue_text)
            )
            lines.append("")
        elif assessment.get("recommendation"):
            lines.append(
                "**Observación de coaching:** la recomendación validada no "
                "entra en el foco accionable de este debrief; queda como "
                "evidencia secundaria."
            )
            lines.append("")

        objective_bits = [
            f"cambio de delta {signed_seconds(episode.get('action_time_loss_s'))}",
            f"inputs: {format_channel_names(episode.get('action_channels', []))}",
        ]

        strength = strength_label(episode.get("evidence_strength"))
        if strength:
            objective_bits.append(f"evidencia {strength}")

        lines.append("**Referencia objetiva:** " + "; ".join(objective_bits) + ".")

        points = spatial_facts(episode)
        if points:
            lines.append("")
            lines.append("**Puntos medidos:** " + "; ".join(points) + ".")

        if episode.get("speed_propagation"):
            lines.append("")
            lines.append(
                "**Contexto:** la diferencia de velocidad continuó después "
                "de terminar este bloque de acción."
            )

        lines.append("")

    lines.append("")
    lines.append("## Puntos de trabajo")
    lines.append("")

    if priority_episodes:
        for ordinal, episode in enumerate(priority_episodes, start=1):
            render_episode(episode, ordinal)
    else:
        lines.append("No hay episodios prioritarios accionables en esta comparación.")
        lines.append("")

    if secondary_episodes:
        lines.append("## Aspectos secundarios")
        lines.append("")
        for episode in secondary_episodes:
            assessment = amap[episode["episode_id"]]
            location = track_location_label(episode) or f"Episodio #{episode['episode_id']}"
            cues = _episode_authorized_driver_cues(episode)
            steering_cue = _episode_validated_steering_cue(episode, assessment)
            if cues:
                text = _compose_episode_driver_cue_text(cues, steering_cue)
                lines.append(
                    f"- **{location}:** {prose(text)}"
                )
            else:
                observation = prose(assessment.get("interpretation"))
                if observation:
                    lines.append(
                        f"- **{location}:** observación solamente — {observation}"
                    )
        lines.append("")

    lines.append("## Respaldo técnico")
    lines.append("")
    lines.append(
        "La clasificación completa se mantiene en el JSON. "
        "Resumen de episodios:"
    )
    lines.append("")

    for episode in episode_catalog:
        episode_id = episode["episode_id"]
        assessment = amap[episode_id]
        location = track_location_label(episode)
        location_text = f"{location} · " if location else ""
        lines.append(
            f"- #{episode_id} · {assessment['classification']} · "
            f"{location_text}{meters(episode.get('start_distance_m'))}–"
            f"{meters(episode.get('end_distance_m'))} · "
            f"{signed_seconds(episode.get('action_time_loss_s'))}."
        )

    limitations = structured_response.get("limitations") or []
    if limitations:
        lines.append("")
        lines.append("## Límites de esta lectura")
        lines.append("")
        for item in limitations[:2]:
            lines.append(f"- {prose(item)}")

    if non_actionable:
        lines.append("")
        lines.append(
            f"Los episodios no accionables permanecen registrados en el JSON "
            f"y no se convierten en instrucciones de conducción."
        )

    return "\n".join(lines)


# ============================================================
# AGREGACIÓN DETERMINISTA DE COACHING DE SESIÓN v3.8.18
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

    # presentation-only: a steering_magnitude fact describes a magnitude
    # difference, not the sign of the raw steering sample that happened to
    # contain the largest absolute peak. Keep the displayed sign consistent
    # with the already-authoritative repeated direction.
    if unit == "steering_input_units":
        peak_value = safe_float(peak)
        if peak_value is not None:
            if direction == "higher_in_comparison_lap":
                peak = abs(peak_value)
            elif direction == "lower_in_comparison_lap":
                peak = -abs(peak_value)

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




# ============================================================
# PERFIL DE ACCIÓN DE REFERENCIA v3.10.8
# ============================================================

REFERENCE_ACTION_PROFILE_VERSION = "1.1"
REFERENCE_THROTTLE_GAP_MIN_M = 8.0
REFERENCE_THROTTLE_BRIEF_APPLICATION_MAX_M = 20.0
REFERENCE_BRAKE_GAP_MIN_M = 8.0


def _reference_lap_for_region(region):
    if not isinstance(region, dict):
        return None

    findings = [
        item
        for item in (region.get("findings", []) or [])
        if isinstance(item, dict)
    ]
    reference_laps = sorted({
        safe_int(item.get("reference_lap"))
        for item in findings
        if safe_int(item.get("reference_lap")) is not None
    })
    return reference_laps[0] if len(reference_laps) == 1 else None


def _reference_throttle_event_catalog(
    source_data,
    reference_lap=None,
):
    """
    Extrae eventos físicos de acelerador de la vuelta de referencia.

    La fuente es throttle_physical_point_profiles producida por Python.
    No consulta al LLM y no convierte full-throttle attainment en coaching
    numérico: ese dato conserva su política observacional.
    """
    if not isinstance(source_data, dict):
        return []

    container = source_data.get("throttle_physical_point_profiles") or {}
    profiles = container.get("profiles", []) if isinstance(container, dict) else []
    by_event_id = {}

    for profile in profiles or []:
        if not isinstance(profile, dict):
            continue

        profile_reference_lap = safe_int(profile.get("reference_lap"))
        if (
            reference_lap is not None
            and profile_reference_lap is not None
            and profile_reference_lap != reference_lap
        ):
            continue

        event = profile.get("reference_event") or {}
        if not isinstance(event, dict):
            continue

        event_id = str(
            event.get("event_id")
            or profile.get("reference_event_id")
            or ""
        ).strip()
        onset = safe_float(event.get("onset_distance_m"))
        if not event_id or onset is None:
            continue

        by_event_id[event_id] = {
            "event_id": event_id,
            "reference_lap": profile_reference_lap,
            "onset_distance_m": onset,
            "confirmation_distance_m": safe_float(event.get("confirmation_distance_m")),
            "release_distance_m": safe_float(event.get("release_distance_m")),
            "release_confirmed": bool(event.get("release_confirmed")),
            "peak_throttle_percent": safe_float(event.get("peak_throttle_percent")),
            "peak_distance_m": safe_float(event.get("peak_distance_m")),
            "full_throttle_attainment_confirmed": bool(
                event.get("full_throttle_attainment_confirmed")
            ),
            "full_throttle_attainment_distance_m": safe_float(
                event.get("full_throttle_attainment_distance_m")
            ),
            "distance_from_onset_to_full_throttle_m": safe_float(
                event.get("distance_from_onset_to_full_throttle_m")
            ),
            "partial_lift_count": safe_int(event.get("partial_lift_count")) or 0,
        }

    return sorted(
        by_event_id.values(),
        key=lambda item: (
            item.get("onset_distance_m")
            if item.get("onset_distance_m") is not None
            else 999999.0,
            item.get("event_id") or "",
        ),
    )


def _reference_brake_event_catalog(
    source_data,
    reference_lap=None,
):
    """
    Reconstruye los eventos físicos de freno de la vuelta de referencia.

    analyze_telemetry 3.8 no expone todavía un catálogo top-level equivalente
    a throttle_physical_point_profiles. Por eso el catálogo se deduplica desde
    driver_action_episode_ranking, usando exclusivamente braking_point_comparison
    y brake_release_point_comparison ya calculados por Python.
    """
    if not isinstance(source_data, dict):
        return []

    by_event_id = {}

    for comparison in source_data.get("comparisons", []) or []:
        if not isinstance(comparison, dict):
            continue

        comparison_reference_lap = safe_int(comparison.get("reference_lap"))
        if (
            reference_lap is not None
            and comparison_reference_lap is not None
            and comparison_reference_lap != reference_lap
        ):
            continue

        objective = comparison.get("objective_analysis") or {}
        ranking = (
            objective.get("driver_action_episode_ranking", [])
            if isinstance(objective, dict)
            else []
        )

        for episode in ranking or []:
            if not isinstance(episode, dict):
                continue

            onset_cmp = episode.get("braking_point_comparison") or {}
            release_cmp = episode.get("brake_release_point_comparison") or {}
            if not isinstance(onset_cmp, dict):
                onset_cmp = {}
            if not isinstance(release_cmp, dict):
                release_cmp = {}

            event_id = str(
                onset_cmp.get("reference_event_id")
                or release_cmp.get("reference_event_id")
                or ""
            ).strip()
            if not event_id:
                continue

            onset_event = onset_cmp.get("reference_event") or {}
            release_event = release_cmp.get("reference_event") or {}
            if not isinstance(onset_event, dict):
                onset_event = {}
            if not isinstance(release_event, dict):
                release_event = {}

            item = by_event_id.setdefault(
                event_id,
                {
                    "event_id": event_id,
                    "reference_lap": comparison_reference_lap,
                },
            )

            candidates = {
                "onset_distance_m": onset_cmp.get("reference_onset_m"),
                "confirmation_distance_m": (
                    onset_event.get("confirmation_distance_m")
                    if onset_event
                    else release_event.get("confirmation_distance_m")
                ),
                "release_distance_m": (
                    release_cmp.get("reference_release_m")
                    if release_cmp.get("reference_release_m") is not None
                    else onset_event.get("release_distance_m")
                ),
                "peak_brake_percent": (
                    onset_event.get("peak_brake_percent")
                    if onset_event.get("peak_brake_percent") is not None
                    else release_event.get("peak_brake_percent")
                ),
            }

            for key, value in candidates.items():
                numeric = safe_float(value)
                if numeric is not None:
                    item[key] = numeric

    events = [
        item
        for item in by_event_id.values()
        if safe_float(item.get("onset_distance_m")) is not None
    ]

    return sorted(
        events,
        key=lambda item: (
            item.get("onset_distance_m")
            if item.get("onset_distance_m") is not None
            else 999999.0,
            item.get("event_id") or "",
        ),
    )


def _reference_throttle_level_label(peak_percent):
    peak_percent = safe_float(peak_percent)
    if peak_percent is None:
        return "aplicación"
    if peak_percent < 60.0:
        return "aplicación parcial"
    if peak_percent < 85.0:
        return "aplicación media"
    return "aplicación alta"


def _reference_brake_level_label(peak_percent):
    peak_percent = safe_float(peak_percent)
    if peak_percent is None:
        return "aplicación de freno"
    if peak_percent < 30.0:
        return "aplicación ligera de freno"
    if peak_percent < 60.0:
        return "aplicación media de freno"
    if peak_percent < 85.0:
        return "aplicación alta de freno"
    return "aplicación muy alta de freno"


def _reference_throttle_profile_for_region(
    region,
    source_data,
):
    """
    Describe la forma observada del acelerador de la vuelta de referencia.

    Sólo usa eventos cuyo onset cae dentro de la región. Los metros y
    porcentajes quedan en steps como respaldo descriptivo; el target textual
    usa categorías de forma, no nuevos objetivos numéricos no calibrados.
    """
    if not isinstance(region, dict):
        return None

    start = safe_float(region.get("start_distance_m"))
    end = safe_float(region.get("end_distance_m"))
    if start is None or end is None:
        return None
    if end < start:
        start, end = end, start

    reference_lap = _reference_lap_for_region(region)

    events = [
        event
        for event in _reference_throttle_event_catalog(
            source_data,
            reference_lap=reference_lap,
        )
        if (
            event.get("onset_distance_m") is not None
            and start <= event["onset_distance_m"] <= end
        )
    ]
    if not events:
        return None

    steps = []
    previous_release = None

    for event in events:
        onset = safe_float(event.get("onset_distance_m"))
        release = safe_float(event.get("release_distance_m"))
        peak = safe_float(event.get("peak_throttle_percent"))

        if (
            previous_release is not None
            and onset is not None
            and onset > previous_release
        ):
            gap = onset - previous_release
            if gap >= REFERENCE_THROTTLE_GAP_MIN_M:
                steps.append({
                    "kind": "released_gap",
                    "start_distance_m": previous_release,
                    "end_distance_m": onset,
                    "length_m": gap,
                    "shape": (
                        "liberación breve"
                        if gap <= 20.0
                        else "acelerador liberado"
                    ),
                    "descriptive_only": True,
                })

        duration = (
            release - onset
            if onset is not None
            and release is not None
            and release >= onset
            else None
        )

        level = _reference_throttle_level_label(peak)
        if event.get("full_throttle_attainment_confirmed"):
            shape = (
                "reaplicación sostenida sin volver a soltar dentro de la zona"
                if release is not None and release > end
                else "reaplicación sostenida"
            )
        elif duration is not None and duration <= REFERENCE_THROTTLE_BRIEF_APPLICATION_MAX_M:
            shape = f"{level} breve"
        else:
            shape = level

        steps.append({
            "kind": "application",
            "event_id": event.get("event_id"),
            "shape": shape,
            "onset_distance_m": onset,
            "release_distance_m": release,
            "duration_m": duration,
            "peak_throttle_percent": peak,
            "peak_distance_m": safe_float(event.get("peak_distance_m")),
            "full_throttle_attainment_confirmed": bool(
                event.get("full_throttle_attainment_confirmed")
            ),
            "full_throttle_attainment_distance_m": safe_float(
                event.get("full_throttle_attainment_distance_m")
            ),
            "distance_from_onset_to_full_throttle_m": safe_float(
                event.get("distance_from_onset_to_full_throttle_m")
            ),
            "descriptive_only": True,
        })

        if release is not None:
            previous_release = release

    shape_sequence = [
        str(step.get("shape") or "").strip()
        for step in steps
        if str(step.get("shape") or "").strip()
    ]
    if not shape_sequence:
        return None

    detailed_sequence = []
    for step in steps:
        shape = str(step.get("shape") or "").strip()
        if not shape:
            continue

        if step.get("kind") == "released_gap":
            gap_start = safe_float(step.get("start_distance_m"))
            gap_end = safe_float(step.get("end_distance_m"))
            if gap_start is not None and gap_end is not None:
                detailed_sequence.append(
                    f"{shape} (~{gap_start:.0f}–{gap_end:.0f} m)"
                )
            else:
                detailed_sequence.append(shape)
            continue

        onset = safe_float(step.get("onset_distance_m"))
        release = safe_float(step.get("release_distance_m"))
        peak = safe_float(step.get("peak_throttle_percent"))

        detail = shape
        if onset is not None:
            if release is not None and release <= end:
                detail += f" (~{onset:.0f}–{release:.0f} m"
                if peak is not None and not step.get("full_throttle_attainment_confirmed"):
                    detail += f"; pico ~{peak:.0f}%"
                detail += ")"
            else:
                detail += f" desde ~{onset:.0f} m"

        detailed_sequence.append(detail)

    return {
        "version": REFERENCE_ACTION_PROFILE_VERSION,
        "channel": "throttle",
        "reference_lap": reference_lap,
        "region_start_m": start,
        "region_end_m": end,
        "event_count": len(events),
        "steps": steps,
        "shape_sequence": shape_sequence,
        "shape_summary": " → ".join(shape_sequence),
        "shape_summary_detailed": " → ".join(detailed_sequence),
        "source": "throttle_physical_point_profiles.reference_event",
        "descriptive_only": True,
        "numeric_coaching_authorized": False,
    }


def _reference_brake_profile_for_region(
    region,
    source_data,
):
    """
    Describe la secuencia física de freno de la vuelta de referencia.

    No infiere trail braking, progresividad, balance ni dinámica. Sólo resume
    onset, release, nivel pico y separaciones entre eventos ya detectados por
    Python. Los metros/porcentajes son respaldo descriptivo y no nuevos targets.
    """
    if not isinstance(region, dict):
        return None

    start = safe_float(region.get("start_distance_m"))
    end = safe_float(region.get("end_distance_m"))
    if start is None or end is None:
        return None
    if end < start:
        start, end = end, start

    reference_lap = _reference_lap_for_region(region)
    events = []
    for event in _reference_brake_event_catalog(
        source_data,
        reference_lap=reference_lap,
    ):
        onset = safe_float(event.get("onset_distance_m"))
        release = safe_float(event.get("release_distance_m"))
        if onset is None:
            continue
        effective_release = release if release is not None else onset
        if onset <= end and effective_release >= start:
            events.append(event)

    if not events:
        return None

    steps = []
    previous_release = None

    for event in events:
        onset = safe_float(event.get("onset_distance_m"))
        release = safe_float(event.get("release_distance_m"))
        peak = safe_float(event.get("peak_brake_percent"))

        if (
            previous_release is not None
            and onset is not None
            and onset > previous_release
        ):
            gap = onset - previous_release
            if gap >= REFERENCE_BRAKE_GAP_MIN_M:
                steps.append({
                    "kind": "released_gap",
                    "start_distance_m": previous_release,
                    "end_distance_m": onset,
                    "length_m": gap,
                    "shape": (
                        "liberación breve del freno"
                        if gap <= 20.0
                        else "freno liberado"
                    ),
                    "descriptive_only": True,
                })

        duration = (
            release - onset
            if onset is not None
            and release is not None
            and release >= onset
            else None
        )
        steps.append({
            "kind": "application",
            "event_id": event.get("event_id"),
            "shape": _reference_brake_level_label(peak),
            "onset_distance_m": onset,
            "confirmation_distance_m": safe_float(event.get("confirmation_distance_m")),
            "release_distance_m": release,
            "duration_m": duration,
            "peak_brake_percent": peak,
            "descriptive_only": True,
        })

        if release is not None:
            previous_release = release

    # Si el último evento termina claramente antes del final de la región y no
    # hay otra aplicación, esa ausencia de freno también forma parte de la forma.
    if previous_release is not None and end > previous_release:
        trailing_gap = end - previous_release
        if trailing_gap >= REFERENCE_BRAKE_GAP_MIN_M:
            steps.append({
                "kind": "released_gap",
                "start_distance_m": previous_release,
                "end_distance_m": end,
                "length_m": trailing_gap,
                "shape": "freno liberado hasta salir de la zona",
                "descriptive_only": True,
            })

    shape_sequence = [
        str(step.get("shape") or "").strip()
        for step in steps
        if str(step.get("shape") or "").strip()
    ]
    if not shape_sequence:
        return None

    detailed_sequence = []
    for step in steps:
        shape = str(step.get("shape") or "").strip()
        if not shape:
            continue

        if step.get("kind") == "released_gap":
            gap_start = safe_float(step.get("start_distance_m"))
            gap_end = safe_float(step.get("end_distance_m"))
            if gap_start is not None and gap_end is not None:
                detailed_sequence.append(
                    f"{shape} (~{gap_start:.0f}–{gap_end:.0f} m)"
                )
            else:
                detailed_sequence.append(shape)
            continue

        onset = safe_float(step.get("onset_distance_m"))
        release = safe_float(step.get("release_distance_m"))
        peak = safe_float(step.get("peak_brake_percent"))
        detail = shape
        if onset is not None:
            if release is not None:
                detail += f" (~{onset:.0f}–{release:.0f} m"
                if peak is not None:
                    detail += f"; pico ~{peak:.0f}%"
                detail += ")"
            else:
                detail += f" desde ~{onset:.0f} m"
        detailed_sequence.append(detail)

    return {
        "version": REFERENCE_ACTION_PROFILE_VERSION,
        "channel": "brake",
        "reference_lap": reference_lap,
        "region_start_m": start,
        "region_end_m": end,
        "event_count": len(events),
        "steps": steps,
        "shape_sequence": shape_sequence,
        "shape_summary": " → ".join(shape_sequence),
        "shape_summary_detailed": " → ".join(detailed_sequence),
        "source": "driver_action_episode_ranking.braking_point_comparison+brake_release_point_comparison",
        "descriptive_only": True,
        "numeric_coaching_authorized": False,
    }


def _reference_throttle_profile_target_text(profile):
    if not isinstance(profile, dict):
        return None
    summary = str(profile.get("shape_summary") or "").strip()
    if not summary:
        return None
    return "replicar la secuencia de acelerador de la referencia: " + summary


def _reference_brake_profile_target_text(profile):
    if not isinstance(profile, dict):
        return None
    summary = str(profile.get("shape_summary") or "").strip()
    if not summary:
        return None
    return "replicar la secuencia de freno de la referencia: " + summary


def _attach_reference_action_profiles(
    regions,
    source_data,
):
    """
    v3.10.8: throttle/brake sólo se convierten en acción si Python puede
    describir concretamente la secuencia física de la vuelta de referencia.

    La dirección genérica de porcentaje (más/menos) permanece observacional.
    Steering no genera target directo.
    """
    if not isinstance(regions, list):
        return regions

    for region in regions:
        if not isinstance(region, dict):
            continue

        throttle_profile = _reference_throttle_profile_for_region(region, source_data)
        brake_profile = _reference_brake_profile_for_region(region, source_data)

        for repeated in region.get("repeated_differences", []) or []:
            if not isinstance(repeated, dict):
                continue

            channel = repeated.get("channel")
            repeated["target"] = None
            repeated["actionability"] = "observation_only"
            repeated["target_source"] = "observation_only_channel_difference"

            if channel == "throttle":
                profile = throttle_profile
                target = _reference_throttle_profile_target_text(profile)
            elif channel == "brake":
                profile = brake_profile
                target = _reference_brake_profile_target_text(profile)
            else:
                profile = None
                target = None

            if channel in {"throttle", "brake"}:
                repeated["reference_action_profile"] = profile
                if target:
                    repeated["target"] = target
                    repeated["actionability"] = "actionable_reference_profile"
                    repeated["target_source"] = "reference_action_profile"
                else:
                    repeated["target_source"] = "unavailable_reference_action_profile"

        if throttle_profile is not None:
            region["reference_throttle_profile"] = throttle_profile
        if brake_profile is not None:
            region["reference_brake_profile"] = brake_profile

    return regions

def _reference_lap_for_plan_item(item):
    """Infere la vuelta de referencia desde labels `ref->cmp` del plan."""
    if not isinstance(item, dict):
        return None

    laps = set()
    for label in (item.get("comparisons", []) or []):
        match = re.match(r"^\s*(\d+)\s*->", str(label))
        if match:
            laps.add(int(match.group(1)))

    return next(iter(laps)) if len(laps) == 1 else None


def _point_pattern_reference_event_ids(item, fields):
    event_ids = []
    for field in fields:
        for pattern in (item.get(field, []) or []):
            if not isinstance(pattern, dict):
                continue
            event_id = str(pattern.get("reference_event_id") or "").strip()
            if event_id and event_id not in event_ids:
                event_ids.append(event_id)
            for plural_id in (pattern.get("reference_event_ids", []) or []):
                plural_id = str(plural_id or "").strip()
                if plural_id and plural_id not in event_ids:
                    event_ids.append(plural_id)
    return event_ids


def _point_anchored_profile(item, source_data, channel):
    """
    v3.10.8.5.4: un onset/release autorizado arrastra la forma del MISMO evento
    de referencia por reference_event_id.

    Esto evita perder el perfil cuando el punto de referencia queda apenas
    fuera del intervalo agregado de la región. La forma sigue siendo
    descriptiva; sólo onset/release conserva autoridad numérica de coaching.
    """
    if channel == "throttle":
        fields = ("throttle_onset_patterns", "throttle_release_patterns")
        catalog_builder = _reference_throttle_event_catalog
        profile_builder = _reference_throttle_profile_for_region
    elif channel == "brake":
        fields = ("braking_point_patterns", "brake_release_patterns")
        catalog_builder = _reference_brake_event_catalog
        profile_builder = _reference_brake_profile_for_region
    else:
        return None

    wanted_ids = _point_pattern_reference_event_ids(item, fields)
    if not wanted_ids:
        return None

    reference_lap = _reference_lap_for_plan_item(item)
    catalog = catalog_builder(source_data, reference_lap=reference_lap)
    wanted = set(wanted_ids)
    matched = [
        event for event in catalog
        if str(event.get("event_id") or "").strip() in wanted
    ]
    if not matched:
        return None

    event = sorted(
        matched,
        key=lambda row: (
            safe_float(row.get("onset_distance_m"))
            if safe_float(row.get("onset_distance_m")) is not None
            else 999999.0,
            str(row.get("event_id") or ""),
        ),
    )[0]
    anchor = safe_float(event.get("onset_distance_m"))
    if anchor is None:
        return None

    synthetic_region = {
        "start_distance_m": anchor - 1.0,
        "end_distance_m": anchor + 1.0,
        "findings": (
            [{"reference_lap": reference_lap}]
            if reference_lap is not None
            else []
        ),
    }
    profile = profile_builder(synthetic_region, source_data)
    if not isinstance(profile, dict):
        return None

    profile = dict(profile)

    # La ventana sintética de 2 m sólo sirve para identificar el evento.
    # No debe contaminar el wording driver-facing con "dentro de la zona".
    if channel == "throttle":
        verbose = "reaplicación sostenida sin volver a soltar dentro de la zona"
        concise = "reaplicación sostenida"
        if profile.get("shape_summary") == verbose:
            profile["shape_summary"] = concise
        sequence = [
            concise if value == verbose else value
            for value in (profile.get("shape_sequence", []) or [])
        ]
        profile["shape_sequence"] = sequence
        for step in (profile.get("steps", []) or []):
            if isinstance(step, dict) and step.get("shape") == verbose:
                step["shape"] = concise

    profile["attachment"] = "point_reference_event_id"
    profile["reference_event_ids"] = wanted_ids
    profile["plan_region_start_m"] = item.get("start_distance_m")
    profile["plan_region_end_m"] = item.get("end_distance_m")
    return profile


def _attach_point_anchored_reference_profiles(plan, source_data):
    """Completa perfiles de forma para cues espaciales sin autorizar targets nuevos."""
    if not isinstance(plan, list):
        return plan

    for item in plan:
        if not isinstance(item, dict):
            continue

        profiles = [
            profile
            for profile in (item.get("reference_action_profiles", []) or [])
            if isinstance(profile, dict)
        ]
        channels = {
            str(profile.get("channel") or "")
            for profile in profiles
        }

        for channel in ("brake", "throttle"):
            if channel in channels:
                continue
            profile = _point_anchored_profile(item, source_data, channel)
            if profile is not None:
                profiles.append(profile)
                channels.add(channel)

        item["reference_action_profiles"] = profiles

    return plan



def _coaching_target_for_channel_direction(
    channel,
    direction,
):
    """
    v3.10.8.5.4: diferencias deterministas unívocas de NIVEL en brake/throttle
    pueden convertirse en coaching cualitativo hacia la vuelta de referencia.

    Límites:
    - no inventa metros, porcentajes ni causalidad;
    - mixed/ambiguo permanece observacional;
    - steering conserva su vía separada de autorización LLM+Python;
    - los detectores onset/release siguen siendo los únicos dueños de targets
      espaciales numéricos.
    """
    if channel not in {"brake", "throttle"}:
        return None

    label = {
        "brake": "el freno",
        "throttle": "el acelerador",
    }[channel]

    if direction == "higher_in_comparison_lap":
        return f"reducir {label} hacia la referencia"

    if direction == "lower_in_comparison_lap":
        return f"aumentar {label} hacia la referencia"

    return None

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
        "overlap",
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

    raw_kinds = sorted({
        str(item.get("kind"))
        for item in rows
        if item.get("kind")
    })

    def relation_family(kind):
        if kind in {
            "partial_overlap",
            "substantial_overlap",
        }:
            return "overlap"
        return kind

    families = sorted({
        relation_family(kind)
        for kind in raw_kinds
        if kind
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
            raw_kinds,
        "families":
            families,
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

    if len(families) == 1:
        result["kind"] = families[0]
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

    # Una relación temporal regional sólo es un patrón repetido si está
    # respaldada por al menos dos comparaciones distintas. Una observación
    # aislada puede existir en el detalle del episodio, pero no debe escalar
    # al plan repetido de la sesión.
    if count < 2:
        return None

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
        "overlap",
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
                        "priority_episode_count":
                            0,
                        "quantitative_facts":
                            [],
                    },
                )

                row["comparisons"].add(
                    comparison
                )
                row["episode_count"] += 1
                if finding.get("classification") == "PRIORITARIO":
                    row["priority_episode_count"] += 1

                quantitative = channel_fact.get(
                    "quantitative"
                )
                if isinstance(quantitative, dict):
                    row["quantitative_facts"].append(
                        quantitative
                    )

        repeated_differences = []

        channels_with_directional_repeat = set()

        # Si el mismo canal repite AMBAS direcciones en la misma región a
        # través de múltiples comparaciones, no generamos dos targets
        # contradictorios. Se degrada a patrón mixto/replicar secuencia.
        repeated_direction_count_by_channel = {}
        for (channel, _direction), row in channel_rows.items():
            if len(row.get("comparisons", set())) < 2:
                continue
            repeated_direction_count_by_channel[channel] = (
                repeated_direction_count_by_channel.get(channel, 0) + 1
            )

        for (
            channel,
            direction,
        ), row in channel_rows.items():
            comparison_count = len(
                row["comparisons"]
            )

            if comparison_count < 2:
                continue

            if repeated_direction_count_by_channel.get(channel, 0) > 1:
                continue

            channels_with_directional_repeat.add(
                channel
            )

            qualitative_target = _coaching_target_for_channel_direction(
                channel,
                direction,
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
                "recurrence_episode_count":
                    row[
                        "episode_count"
                    ],
                "priority_episode_count":
                    row.get(
                        "priority_episode_count",
                        0,
                    ),
                "target":
                    qualitative_target,
                "actionability": (
                    "qualitative_reference_alignment"
                    if qualitative_target
                    else "observation_only"
                ),
                "target_source": (
                    "deterministic_observed_level_to_reference"
                    if qualitative_target
                    else "observation_only_channel_difference"
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
                    "priority_episode_count": 0,
                    "quantitative_facts": [],
                },
            )

            entry["comparisons"].update(
                row["comparisons"]
            )
            entry["episode_count"] += (
                row["episode_count"]
            )
            entry["priority_episode_count"] += (
                row.get("priority_episode_count", 0)
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
                "recurrence_episode_count":
                    row[
                        "episode_count"
                    ],
                "priority_episode_count":
                    row.get(
                        "priority_episode_count",
                        0,
                    ),
                "target":
                    _coaching_target_for_channel_direction(
                        channel,
                        "mixed",
                    ),
                "actionability": "observation_only",
                "target_source": "observation_only_channel_difference",
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
                -item.get(
                    "recurrence_episode_count",
                    0,
                ),
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
            "recurrence_episode_count":
                len(component),
            "priority_episode_count":
                sum(
                    1
                    for item in component
                    if item.get("classification") == "PRIORITARIO"
                ),
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
            -len(
                item.get(
                    "repeated_differences",
                    [],
                )
            ),
            -item.get(
                "recurrence_episode_count",
                0,
            ),
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


def _sanitize_recurrence_regions(regions):
    """
    Elimina metadata dependiente del ranker de la capa física de recurrencia.

    v3.10.8.5.4: NO muta los dicts originales. priority_findings y
    recurrence_findings pueden compartir objetos durante la construcción;
    sanear in-place borraba relative_priority_rank/classification también de
    la capa prioritaria y terminaba degradando el desempate del plan.
    """
    if not isinstance(regions, list):
        return []

    cleaned_regions = []

    for region in regions:
        if not isinstance(region, dict):
            continue

        cleaned = dict(region)
        cleaned.pop("priority_episode_count", None)
        cleaned.pop("best_episode_priority_rank", None)
        cleaned.pop("best_comparison_priority_rank", None)

        cleaned_repeated = []
        for repeated in (region.get("repeated_differences", []) or []):
            if not isinstance(repeated, dict):
                continue
            repeated_copy = dict(repeated)
            repeated_copy.pop("priority_episode_count", None)
            cleaned_repeated.append(repeated_copy)
        cleaned["repeated_differences"] = cleaned_repeated

        findings = []
        for finding in (region.get("findings", []) or []):
            if not isinstance(finding, dict):
                continue
            finding_copy = dict(finding)
            finding_copy.pop("relative_priority_rank", None)
            finding_copy.pop("classification", None)
            findings.append(finding_copy)

        findings.sort(
            key=lambda item: (
                str(item.get("comparison") or ""),
                item.get("start_distance_m")
                if item.get("start_distance_m") is not None
                else 999999.0,
                item.get("end_distance_m")
                if item.get("end_distance_m") is not None
                else 999999.0,
                item.get("episode_id")
                if item.get("episode_id") is not None
                else 999999,
            )
        )
        cleaned["findings"] = findings
        cleaned_regions.append(cleaned)

    return cleaned_regions



def _single_finding_plan_item(
    finding,
    label,
):
    comparison = finding.get("comparison")
    braking = _single_fact_as_plan_pattern(finding.get("braking_point"), comparison)
    brake_release = _single_fact_as_plan_pattern(finding.get("brake_release"), comparison)
    throttle_onset = _single_fact_as_plan_pattern(finding.get("throttle_onset"), comparison)
    throttle_release = _single_fact_as_plan_pattern(finding.get("throttle_release"), comparison)

    channel_rows = [
        item
        for item in (finding.get("channels", []) or [])
        if isinstance(item, dict)
    ]

    qualitative_targets = []
    observation_only = []

    for item in channel_rows:
        description = item.get("description")
        target = _coaching_target_for_channel_direction(
            item.get("channel"),
            item.get("direction"),
        )
        if target:
            qualitative_targets.append(target)
        elif description:
            observation_only.append(description)

    return {
        "plan_label": label,
        "kind": "single_priority_finding",
        "start_distance_m": finding.get("start_distance_m"),
        "end_distance_m": finding.get("end_distance_m"),
        "comparisons": [finding.get("comparison")],
        "comparison_count": 1,
        "observed_differences": [
            item.get("description")
            for item in channel_rows
            if item.get("description")
        ],
        "observation_only_differences": observation_only,
        "targets": qualitative_targets,
        "reference_action_profiles": [],
        "quantitative_observations": [
            text
            for text in (
                _format_single_channel_quantitative_observation(item)
                for item in channel_rows
            )
            if text
        ],
        "temporal_relationships": [
            text
            for text in [
                _format_single_brake_throttle_relation(
                    finding.get("brake_throttle_relation")
                )
            ]
            if text
        ],
        "temporal_target": None,
        "braking_point_patterns": [braking] if braking else [],
        "braking_point_target": None,
        "brake_release_patterns": [brake_release] if brake_release else [],
        "brake_release_target": None,
        "throttle_onset_patterns": [throttle_onset] if throttle_onset else [],
        "throttle_onset_target": None,
        "throttle_release_patterns": [throttle_release] if throttle_release else [],
        "throttle_release_target": None,
        "speed_directions": finding.get("speed_directions", []),
        "propagation_statuses": finding.get("propagation_statuses", []),
        "comparison_priority_rank": finding.get("comparison_priority_rank"),
        "episode_priority_rank": finding.get("relative_priority_rank"),
        "action_time_loss_s": finding.get("action_time_loss_s"),
        "steering_coaching_requested": bool(
            finding.get("steering_coaching_requested")
        ),
        "validated_recommendation": finding.get("validated_recommendation"),
        "steering_direction": next(
            (
                item.get("direction")
                for item in channel_rows
                if item.get("channel") == "steering_magnitude"
            ),
            None,
        ),
        "source_priority": {
            "comparison_priority_rank": finding.get("comparison_priority_rank"),
            "episode_priority_rank": finding.get("relative_priority_rank"),
        },
    }

BRAKING_POINT_SESSION_MIN_DELTA_M = 8.0
BRAKING_POINT_PATTERN_ONSET_TOLERANCE_M = 8.0
BRAKE_RELEASE_SESSION_MIN_DELTA_M = 8.0
BRAKE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M = 8.0

def _session_braking_point_fact(episode):
    """
    Extrae evidencia física de punto de frenada para la agregación de sesión.

    Importante:
    - VALID + authorized_numeric_coaching=True puede emitir coaching individual.
    - DUPLICATE NO puede emitir coaching individual, pero sigue representando
      el mismo evento físico medido y por lo tanto puede aportar una muestra
      a la agregación entre comparaciones.
    - la agregación posterior ya conserva como máximo una observación por
      comparación para cada evento físico, por lo que incluir DUPLICATE acá
      no reintroduce doble conteo.
    """
    if not isinstance(episode, dict):
        return None

    value = episode.get("braking_point_comparison")
    if not isinstance(value, dict):
        return None

    source_status = value.get("status")
    if source_status not in {"VALID", "DUPLICATE"}:
        return None

    delta_m = safe_float(value.get("comparison_minus_reference_m"))
    reference_onset_m = safe_float(value.get("reference_onset_m"))
    comparison_onset_m = safe_float(value.get("comparison_onset_m"))

    if (
        delta_m is None
        or reference_onset_m is None
        or comparison_onset_m is None
        or abs(delta_m) < BRAKING_POINT_SESSION_MIN_DELTA_M
    ):
        return None

    if delta_m < 0.0:
        coaching_direction = "later"
        relative_direction = "earlier_in_comparison_lap"
    elif delta_m > 0.0:
        coaching_direction = "earlier"
        relative_direction = "later_in_comparison_lap"
    else:
        return None

    return {
        "status": "VALID",
        "source_status": source_status,
        "braking_pair_id": value.get("braking_pair_id"),
        "reference_event_id": value.get("reference_event_id"),
        "comparison_event_id": value.get("comparison_event_id"),
        "reference_onset_m": reference_onset_m,
        "comparison_onset_m": comparison_onset_m,
        "comparison_minus_reference_m": delta_m,
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))),
        "authorized_numeric_coaching": bool(
            source_status == "VALID"
            and value.get("authorized_numeric_coaching")
        ),
        "session_aggregation_eligible": True,
    }



def _session_brake_release_fact(episode):
    """
    Extrae evidencia física de liberación de freno para agregación de sesión.

    VALID puede autorizar coaching individual.
    DUPLICATE conserva la medición física para el agregado entre comparaciones,
    pero nunca autoriza coaching individual.
    """
    if not isinstance(episode, dict):
        return None

    value = episode.get("brake_release_point_comparison")
    if not isinstance(value, dict):
        return None

    source_status = value.get("status")
    if source_status not in {"VALID", "DUPLICATE"}:
        return None

    delta_m = safe_float(value.get("comparison_minus_reference_m"))
    reference_release_m = safe_float(value.get("reference_release_m"))
    comparison_release_m = safe_float(value.get("comparison_release_m"))

    if (
        delta_m is None
        or reference_release_m is None
        or comparison_release_m is None
        or abs(delta_m) < BRAKE_RELEASE_SESSION_MIN_DELTA_M
    ):
        return None

    if delta_m < 0.0:
        coaching_direction = "later"
        relative_direction = "earlier_in_comparison_lap"
    elif delta_m > 0.0:
        coaching_direction = "earlier"
        relative_direction = "later_in_comparison_lap"
    else:
        return None

    return {
        "status": "VALID",
        "source_status": source_status,
        "braking_pair_id": value.get("braking_pair_id"),
        "reference_event_id": value.get("reference_event_id"),
        "comparison_event_id": value.get("comparison_event_id"),
        "reference_release_m": reference_release_m,
        "comparison_release_m": comparison_release_m,
        "comparison_minus_reference_m": delta_m,
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))),
        "authorized_numeric_coaching": bool(
            source_status == "VALID"
            and value.get("authorized_numeric_coaching")
        ),
        "session_aggregation_eligible": True,
    }



THROTTLE_ONSET_SESSION_MIN_DELTA_M = 8.0
THROTTLE_ONSET_PATTERN_REFERENCE_TOLERANCE_M = 12.0
THROTTLE_RELEASE_SESSION_MIN_DELTA_M = 8.0
THROTTLE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M = 12.0


def _session_throttle_onset_fact(episode):
    """Evidencia física de reaplicación de acelerador para agregado de sesión."""
    if not isinstance(episode, dict):
        return None

    value = episode.get("throttle_onset_point_comparison")
    if not isinstance(value, dict):
        return None

    source_status = value.get("status")
    if source_status not in {"VALID", "DUPLICATE"}:
        return None

    delta_m = safe_float(value.get("comparison_minus_reference_m"))
    reference_onset_m = safe_float(value.get("reference_onset_m"))
    comparison_onset_m = safe_float(value.get("comparison_onset_m"))

    if (
        delta_m is None
        or reference_onset_m is None
        or comparison_onset_m is None
        or abs(delta_m) < THROTTLE_ONSET_SESSION_MIN_DELTA_M
    ):
        return None

    if delta_m < 0.0:
        coaching_direction = "later"
        relative_direction = "earlier_in_comparison_lap"
    elif delta_m > 0.0:
        coaching_direction = "earlier"
        relative_direction = "later_in_comparison_lap"
    else:
        return None

    return {
        "status": "VALID",
        "source_status": source_status,
        "throttle_pair_id": value.get("throttle_pair_id"),
        "reference_event_id": value.get("reference_event_id"),
        "comparison_event_id": value.get("comparison_event_id"),
        "reference_onset_m": reference_onset_m,
        "comparison_onset_m": comparison_onset_m,
        "comparison_minus_reference_m": delta_m,
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))),
        "authorized_numeric_coaching": bool(
            source_status == "VALID"
            and value.get("authorized_numeric_coaching")
        ),
        "session_aggregation_eligible": True,
    }


def _session_throttle_release_fact(episode):
    """Evidencia física de liberación de acelerador para agregado de sesión."""
    if not isinstance(episode, dict):
        return None

    value = episode.get("throttle_release_point_comparison")
    if not isinstance(value, dict):
        return None

    source_status = value.get("status")
    if source_status not in {"VALID", "DUPLICATE"}:
        return None

    delta_m = safe_float(value.get("comparison_minus_reference_m"))
    reference_release_m = safe_float(value.get("reference_release_m"))
    comparison_release_m = safe_float(value.get("comparison_release_m"))

    if (
        delta_m is None
        or reference_release_m is None
        or comparison_release_m is None
        or abs(delta_m) < THROTTLE_RELEASE_SESSION_MIN_DELTA_M
    ):
        return None

    if delta_m < 0.0:
        coaching_direction = "later"
        relative_direction = "earlier_in_comparison_lap"
    elif delta_m > 0.0:
        coaching_direction = "earlier"
        relative_direction = "later_in_comparison_lap"
    else:
        return None

    return {
        "status": "VALID",
        "source_status": source_status,
        "throttle_pair_id": value.get("throttle_pair_id"),
        "reference_event_id": value.get("reference_event_id"),
        "comparison_event_id": value.get("comparison_event_id"),
        "reference_release_m": reference_release_m,
        "comparison_release_m": comparison_release_m,
        "comparison_minus_reference_m": delta_m,
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))),
        "authorized_numeric_coaching": bool(
            source_status == "VALID"
            and value.get("authorized_numeric_coaching")
        ),
        "session_aggregation_eligible": True,
    }

def _build_repeated_braking_point_patterns(
    braking_point_findings,
    priority_regions,
):
    """
    Agrupa el mismo evento físico entre comparaciones usando el onset de la
    vuelta de referencia. La agregación es independiente del episodio que
    terminó siendo dueño del coaching numérico en cada comparación.

    Un patrón sólo existe con >=2 comparaciones distintas, misma dirección de
    coaching y delta >= zona muerta. La magnitud de coaching es la MEDIANA de
    los deltas firmados para resistir outliers.
    """
    rows = []

    for finding in braking_point_findings or []:
        if not isinstance(finding, dict):
            continue
        bp = finding.get("braking_point")
        if not isinstance(bp, dict):
            continue
        onset = safe_float(bp.get("reference_onset_m"))
        delta = safe_float(bp.get("comparison_minus_reference_m"))
        direction = bp.get("coaching_direction")
        comparison = finding.get("comparison")
        if (
            onset is None
            or delta is None
            or not comparison
            or direction not in {"later", "earlier"}
            or abs(delta) < BRAKING_POINT_SESSION_MIN_DELTA_M
        ):
            continue
        rows.append(finding)

    rows.sort(
        key=lambda item: safe_float(
            (item.get("braking_point") or {}).get("reference_onset_m")
        ) or 0.0
    )

    clusters = []
    for row in rows:
        onset = safe_float(
            (row.get("braking_point") or {}).get("reference_onset_m")
        )
        placed = False
        for cluster in clusters:
            anchor_onset = cluster["anchor_onset_m"]
            if abs(onset - anchor_onset) <= BRAKING_POINT_PATTERN_ONSET_TOLERANCE_M:
                cluster["rows"].append(row)
                placed = True
                break
        if not placed:
            clusters.append({
                "anchor_onset_m": onset,
                "rows": [row],
            })

    region_members = []
    for region in priority_regions or []:
        if not isinstance(region, dict):
            continue
        keys = {
            (item.get("comparison"), safe_int(item.get("episode_id")))
            for item in (region.get("findings", []) or [])
            if isinstance(item, dict)
        }
        region.setdefault("braking_point_patterns", [])
        region_members.append((region, keys))

    patterns = []

    for cluster in clusters:
        by_direction = {}
        for row in cluster["rows"]:
            direction = (row.get("braking_point") or {}).get("coaching_direction")
            by_direction.setdefault(direction, []).append(row)

        for direction, direction_rows in by_direction.items():
            # Defensa adicional contra outputs v3.8.23 previos a la deduplicación:
            # una comparación sólo aporta una observación al mismo evento físico.
            best_by_comparison = {}
            for row in direction_rows:
                comparison = str(row.get("comparison"))
                action_loss = abs(
                    safe_float(row.get("action_time_loss_s")) or 0.0
                )
                episode_id = safe_int(row.get("episode_id"))
                score = (
                    action_loss,
                    -(episode_id if episode_id is not None else 999999),
                )
                previous = best_by_comparison.get(comparison)
                if previous is None or score > previous[0]:
                    best_by_comparison[comparison] = (score, row)

            selected = [item[1] for item in best_by_comparison.values()]
            if len(selected) < 2:
                continue

            signed_deltas = [
                safe_float((row.get("braking_point") or {}).get("comparison_minus_reference_m"))
                for row in selected
            ]
            signed_deltas = [value for value in signed_deltas if value is not None]
            if len(signed_deltas) < 2:
                continue

            median_delta = float(statistics.median(signed_deltas))
            magnitude = int(round(abs(median_delta)))
            if magnitude < BRAKING_POINT_SESSION_MIN_DELTA_M:
                continue

            comparisons = sorted(str(row.get("comparison")) for row in selected)
            reference_onsets = [
                safe_float((row.get("braking_point") or {}).get("reference_onset_m"))
                for row in selected
            ]
            reference_onsets = [value for value in reference_onsets if value is not None]

            pattern = {
                "status": "REPEATED",
                "comparison_count": len(comparisons),
                "comparisons": comparisons,
                "coaching_direction": direction,
                "coaching_magnitude_m": magnitude,
                "median_delta_m": median_delta,
                "deltas_m": sorted(signed_deltas),
                "reference_onset_m": (
                    float(statistics.median(reference_onsets))
                    if reference_onsets
                    else None
                ),
                "aggregation": "median_comparison_minus_reference_m",
                "source_findings": [
                    {
                        "comparison": row.get("comparison"),
                        "episode_id": safe_int(row.get("episode_id")),
                    }
                    for row in selected
                ],
            }

            # Asignar el evento físico a UNA sola región del plan. Gana la
            # región que contiene más de sus episodios fuente; luego la región
            # con mayor soporte comparativo y finalmente la de mayor pérdida.
            candidates = []
            selected_keys = {
                (row.get("comparison"), safe_int(row.get("episode_id")))
                for row in selected
            }
            for region, keys in region_members:
                votes = len(selected_keys & keys)
                if votes <= 0:
                    continue
                candidates.append((
                    votes,
                    safe_int(region.get("comparison_count")) or 0,
                    abs(safe_float(region.get("max_action_time_loss_s")) or 0.0),
                    region,
                ))

            if candidates:
                candidates.sort(key=lambda item: item[:3], reverse=True)
                chosen_region = candidates[0][3]
                pattern["region_label"] = chosen_region.get("region_label")
                pattern["start_distance_m"] = chosen_region.get("start_distance_m")
                pattern["end_distance_m"] = chosen_region.get("end_distance_m")
                pattern["track_location"] = chosen_region.get("track_location")
                chosen_region.setdefault("braking_point_patterns", []).append(pattern)
            else:
                pattern["region_label"] = None

            patterns.append(pattern)

    patterns.sort(
        key=lambda item: (
            -safe_int(item.get("comparison_count")) if safe_int(item.get("comparison_count")) is not None else 0,
            -abs(safe_float(item.get("median_delta_m")) or 0.0),
            safe_float(item.get("reference_onset_m")) or 999999.0,
        )
    )

    for region in priority_regions or []:
        values = region.get("braking_point_patterns", []) or []
        values.sort(
            key=lambda item: (
                -safe_int(item.get("comparison_count")) if safe_int(item.get("comparison_count")) is not None else 0,
                -abs(safe_float(item.get("median_delta_m")) or 0.0),
            )
        )

    return patterns


def _braking_point_target_text(pattern):
    if not isinstance(pattern, dict) or pattern.get("status") != "REPEATED":
        return None
    magnitude = safe_int(pattern.get("coaching_magnitude_m"))
    direction = pattern.get("coaching_direction")
    if magnitude is None or magnitude < BRAKING_POINT_SESSION_MIN_DELTA_M:
        return None
    if direction == "later":
        return f"frenar aproximadamente {magnitude} m más tarde hacia el punto de la referencia"
    if direction == "earlier":
        return f"frenar aproximadamente {magnitude} m más temprano hacia el punto de la referencia"
    return None



def _build_repeated_brake_release_patterns(
    brake_release_findings,
    priority_regions,
):
    """
    Agrupa liberaciones del mismo evento físico usando la distancia de release
    de la vuelta de referencia. Requiere >=2 comparaciones distintas, misma
    dirección, magnitud >= zona muerta y AUSENCIA de una diferencia accionable
    en dirección opuesta. La magnitud es la mediana firmada.

    DUPLICATE puede aportar evidencia física a la agregación, pero cada
    comparación aporta como máximo una muestra por evento.
    """
    rows = []

    for finding in brake_release_findings or []:
        if not isinstance(finding, dict):
            continue
        release = finding.get("brake_release")
        if not isinstance(release, dict):
            continue
        reference_release = safe_float(
            release.get("reference_release_m")
        )
        delta = safe_float(
            release.get("comparison_minus_reference_m")
        )
        direction = release.get("coaching_direction")
        comparison = finding.get("comparison")
        if (
            reference_release is None
            or delta is None
            or not comparison
            or direction not in {"later", "earlier"}
            or abs(delta) < BRAKE_RELEASE_SESSION_MIN_DELTA_M
        ):
            continue
        rows.append(finding)

    rows.sort(
        key=lambda item: safe_float(
            (item.get("brake_release") or {}).get("reference_release_m")
        ) or 0.0
    )

    clusters = []
    for row in rows:
        reference_release = safe_float(
            (row.get("brake_release") or {}).get("reference_release_m")
        )
        placed = False
        for cluster in clusters:
            anchor_release = cluster["anchor_release_m"]
            if (
                abs(reference_release - anchor_release)
                <= BRAKE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M
            ):
                cluster["rows"].append(row)
                placed = True
                break
        if not placed:
            clusters.append({
                "anchor_release_m": reference_release,
                "rows": [row],
            })

    region_members = []
    for region in priority_regions or []:
        if not isinstance(region, dict):
            continue
        keys = {
            (item.get("comparison"), safe_int(item.get("episode_id")))
            for item in (region.get("findings", []) or [])
            if isinstance(item, dict)
        }
        region.setdefault("brake_release_patterns", [])
        region_members.append((region, keys))

    patterns = []

    for cluster in clusters:
        by_direction = {}
        for row in cluster["rows"]:
            direction = (
                (row.get("brake_release") or {}).get("coaching_direction")
            )
            by_direction.setdefault(direction, []).append(row)

        # Release es más sensible que onset. Si el mismo evento físico tiene
        # diferencias accionables en sentidos opuestos entre comparaciones,
        # no se promueve ningún coaching regional de release.
        actionable_directions = {
            direction
            for direction, rows_for_direction in by_direction.items()
            if (
                direction in {"later", "earlier"}
                and rows_for_direction
            )
        }
        if len(actionable_directions) > 1:
            continue

        for direction, direction_rows in by_direction.items():
            best_by_comparison = {}
            for row in direction_rows:
                comparison = str(row.get("comparison"))
                action_loss = abs(
                    safe_float(row.get("action_time_loss_s")) or 0.0
                )
                episode_id = safe_int(row.get("episode_id"))
                score = (
                    action_loss,
                    -(episode_id if episode_id is not None else 999999),
                )
                previous = best_by_comparison.get(comparison)
                if previous is None or score > previous[0]:
                    best_by_comparison[comparison] = (score, row)

            selected = [item[1] for item in best_by_comparison.values()]
            if len(selected) < 2:
                continue

            signed_deltas = [
                safe_float(
                    (row.get("brake_release") or {}).get(
                        "comparison_minus_reference_m"
                    )
                )
                for row in selected
            ]
            signed_deltas = [
                value for value in signed_deltas
                if value is not None
            ]
            if len(signed_deltas) < 2:
                continue

            median_delta = float(statistics.median(signed_deltas))
            magnitude = int(round(abs(median_delta)))
            if magnitude < BRAKE_RELEASE_SESSION_MIN_DELTA_M:
                continue

            comparisons = sorted(
                str(row.get("comparison"))
                for row in selected
            )
            reference_releases = [
                safe_float(
                    (row.get("brake_release") or {}).get(
                        "reference_release_m"
                    )
                )
                for row in selected
            ]
            reference_releases = [
                value for value in reference_releases
                if value is not None
            ]

            pattern = {
                "status": "REPEATED",
                "comparison_count": len(comparisons),
                "comparisons": comparisons,
                "coaching_direction": direction,
                "coaching_magnitude_m": magnitude,
                "median_delta_m": median_delta,
                "deltas_m": sorted(signed_deltas),
                "reference_release_m": (
                    float(statistics.median(reference_releases))
                    if reference_releases
                    else None
                ),
                "aggregation": "median_comparison_minus_reference_m",
                "source_findings": [
                    {
                        "comparison": row.get("comparison"),
                        "episode_id": safe_int(row.get("episode_id")),
                    }
                    for row in selected
                ],
            }

            candidates = []
            selected_keys = {
                (row.get("comparison"), safe_int(row.get("episode_id")))
                for row in selected
            }
            for region, keys in region_members:
                votes = len(selected_keys & keys)
                if votes <= 0:
                    continue
                candidates.append((
                    votes,
                    safe_int(region.get("comparison_count")) or 0,
                    abs(
                        safe_float(region.get("max_action_time_loss_s"))
                        or 0.0
                    ),
                    region,
                ))

            if candidates:
                candidates.sort(
                    key=lambda item: item[:3],
                    reverse=True,
                )
                chosen_region = candidates[0][3]
                pattern["region_label"] = chosen_region.get("region_label")
                pattern["start_distance_m"] = chosen_region.get(
                    "start_distance_m"
                )
                pattern["end_distance_m"] = chosen_region.get(
                    "end_distance_m"
                )
                pattern["track_location"] = chosen_region.get(
                    "track_location"
                )
                chosen_region.setdefault(
                    "brake_release_patterns",
                    [],
                ).append(pattern)
            else:
                pattern["region_label"] = None

            patterns.append(pattern)

    patterns.sort(
        key=lambda item: (
            -safe_int(item.get("comparison_count"))
            if safe_int(item.get("comparison_count")) is not None
            else 0,
            -abs(safe_float(item.get("median_delta_m")) or 0.0),
            safe_float(item.get("reference_release_m")) or 999999.0,
        )
    )

    for region in priority_regions or []:
        values = region.get("brake_release_patterns", []) or []
        values.sort(
            key=lambda item: (
                -safe_int(item.get("comparison_count"))
                if safe_int(item.get("comparison_count")) is not None
                else 0,
                -abs(safe_float(item.get("median_delta_m")) or 0.0),
            )
        )

    return patterns


def _brake_release_target_text(pattern):
    if not isinstance(pattern, dict) or pattern.get("status") != "REPEATED":
        return None
    magnitude = safe_int(pattern.get("coaching_magnitude_m"))
    direction = pattern.get("coaching_direction")
    if magnitude is None or magnitude < BRAKE_RELEASE_SESSION_MIN_DELTA_M:
        return None
    if direction == "later":
        return (
            f"soltar el freno aproximadamente {magnitude} m más tarde "
            "hacia el punto de la referencia"
        )
    if direction == "earlier":
        return (
            f"soltar el freno aproximadamente {magnitude} m más temprano "
            "hacia el punto de la referencia"
        )
    return None



def _build_repeated_throttle_patterns(
    findings,
    priority_regions,
    *,
    fact_key,
    point_key,
    min_delta_m,
    tolerance_m,
    region_field,
):
    """
    Agrega onset/release de acelerador por punto físico de referencia.

    Reglas conservadoras:
    - >=2 comparaciones distintas;
    - una muestra por comparación;
    - misma dirección de coaching;
    - si existe evidencia accionable en dirección opuesta para el mismo punto,
      no se promueve ningún patrón;
    - magnitud = mediana firmada.
    """
    rows = []
    delta_key = "comparison_minus_reference_m"

    for finding in findings or []:
        if not isinstance(finding, dict):
            continue
        fact = finding.get(fact_key)
        if not isinstance(fact, dict):
            continue
        reference_point = safe_float(fact.get(point_key))
        delta = safe_float(fact.get(delta_key))
        direction = fact.get("coaching_direction")
        comparison = finding.get("comparison")
        if (
            reference_point is None
            or delta is None
            or not comparison
            or direction not in {"later", "earlier"}
            or abs(delta) < min_delta_m
        ):
            continue
        rows.append(finding)

    rows.sort(
        key=lambda item: safe_float(
            (item.get(fact_key) or {}).get(point_key)
        ) or 0.0
    )

    clusters = []
    for row in rows:
        reference_point = safe_float(
            (row.get(fact_key) or {}).get(point_key)
        )
        placed = False
        for cluster in clusters:
            if abs(reference_point - cluster["anchor_m"]) <= tolerance_m:
                cluster["rows"].append(row)
                placed = True
                break
        if not placed:
            clusters.append({
                "anchor_m": reference_point,
                "rows": [row],
            })

    region_members = []
    for region in priority_regions or []:
        if not isinstance(region, dict):
            continue
        keys = {
            (item.get("comparison"), safe_int(item.get("episode_id")))
            for item in (region.get("findings", []) or [])
            if isinstance(item, dict)
        }
        region.setdefault(region_field, [])
        region_members.append((region, keys))

    patterns = []

    for cluster in clusters:
        by_direction = {}
        for row in cluster["rows"]:
            direction = (row.get(fact_key) or {}).get("coaching_direction")
            by_direction.setdefault(direction, []).append(row)

        actionable_directions = {
            direction
            for direction, direction_rows in by_direction.items()
            if direction in {"later", "earlier"} and direction_rows
        }
        if len(actionable_directions) > 1:
            continue

        for direction, direction_rows in by_direction.items():
            best_by_comparison = {}
            for row in direction_rows:
                comparison = str(row.get("comparison"))
                action_loss = abs(
                    safe_float(row.get("action_time_loss_s")) or 0.0
                )
                episode_id = safe_int(row.get("episode_id"))
                score = (
                    action_loss,
                    -(episode_id if episode_id is not None else 999999),
                )
                previous = best_by_comparison.get(comparison)
                if previous is None or score > previous[0]:
                    best_by_comparison[comparison] = (score, row)

            selected = [item[1] for item in best_by_comparison.values()]
            if len(selected) < 2:
                continue

            signed_deltas = [
                safe_float((row.get(fact_key) or {}).get(delta_key))
                for row in selected
            ]
            signed_deltas = [value for value in signed_deltas if value is not None]
            if len(signed_deltas) < 2:
                continue

            median_delta = float(statistics.median(signed_deltas))
            magnitude = int(round(abs(median_delta)))
            if magnitude < min_delta_m:
                continue

            comparisons = sorted(str(row.get("comparison")) for row in selected)
            reference_points = [
                safe_float((row.get(fact_key) or {}).get(point_key))
                for row in selected
            ]
            reference_points = [v for v in reference_points if v is not None]

            reference_event_ids = sorted({
                str((row.get(fact_key) or {}).get("reference_event_id") or "").strip()
                for row in selected
                if str((row.get(fact_key) or {}).get("reference_event_id") or "").strip()
            })

            pattern = {
                "status": "REPEATED",
                "comparison_count": len(comparisons),
                "comparisons": comparisons,
                "coaching_direction": direction,
                "coaching_magnitude_m": magnitude,
                "median_delta_m": median_delta,
                "deltas_m": sorted(signed_deltas),
                point_key: (
                    float(statistics.median(reference_points))
                    if reference_points else None
                ),
                "aggregation": "median_comparison_minus_reference_m",
                "reference_event_id": (
                    reference_event_ids[0]
                    if len(reference_event_ids) == 1
                    else None
                ),
                "reference_event_ids": reference_event_ids,
                "source_findings": [
                    {
                        "comparison": row.get("comparison"),
                        "episode_id": safe_int(row.get("episode_id")),
                    }
                    for row in selected
                ],
            }

            selected_keys = {
                (row.get("comparison"), safe_int(row.get("episode_id")))
                for row in selected
            }
            candidates = []
            for region, keys in region_members:
                votes = len(selected_keys & keys)
                if votes <= 0:
                    continue
                candidates.append((
                    votes,
                    safe_int(region.get("comparison_count")) or 0,
                    abs(safe_float(region.get("max_action_time_loss_s")) or 0.0),
                    region,
                ))

            if candidates:
                candidates.sort(key=lambda item: item[:3], reverse=True)
                chosen_region = candidates[0][3]
                pattern["region_label"] = chosen_region.get("region_label")
                pattern["start_distance_m"] = chosen_region.get("start_distance_m")
                pattern["end_distance_m"] = chosen_region.get("end_distance_m")
                pattern["track_location"] = chosen_region.get("track_location")
                chosen_region.setdefault(region_field, []).append(pattern)
            else:
                # El patrón físico puede ser válido aunque sus episodios no
                # formen una priority_region. Conservar igualmente ubicación
                # de pista si las muestras coinciden en el mismo lugar.
                pattern["region_label"] = None

                locations = [
                    row.get("track_location")
                    for row in selected
                    if isinstance(row.get("track_location"), dict)
                    and row.get("track_location", {}).get("status") == "RESOLVED"
                ]

                labels = {
                    str(location.get("label"))
                    for location in locations
                    if location.get("label")
                }

                if len(labels) == 1 and locations:
                    pattern["track_location"] = dict(locations[0])

                starts = [
                    safe_float(row.get("start_distance_m"))
                    for row in selected
                ]
                starts = [value for value in starts if value is not None]

                ends = [
                    safe_float(row.get("end_distance_m"))
                    for row in selected
                ]
                ends = [value for value in ends if value is not None]

                if starts:
                    pattern["start_distance_m"] = min(starts)
                if ends:
                    pattern["end_distance_m"] = max(ends)

            patterns.append(pattern)

    patterns.sort(
        key=lambda item: (
            -(safe_int(item.get("comparison_count")) or 0),
            -abs(safe_float(item.get("median_delta_m")) or 0.0),
            safe_float(item.get(point_key)) or 999999.0,
        )
    )

    for region in priority_regions or []:
        values = region.get(region_field, []) or []
        values.sort(
            key=lambda item: (
                -(safe_int(item.get("comparison_count")) or 0),
                -abs(safe_float(item.get("median_delta_m")) or 0.0),
            )
        )

    return patterns


def _throttle_onset_target_text(pattern):
    if not isinstance(pattern, dict) or pattern.get("status") != "REPEATED":
        return None
    magnitude = safe_int(pattern.get("coaching_magnitude_m"))
    direction = pattern.get("coaching_direction")
    if magnitude is None or magnitude < THROTTLE_ONSET_SESSION_MIN_DELTA_M:
        return None
    if direction == "later":
        return f"reaplicar el acelerador aproximadamente {magnitude} m más tarde hacia el punto de la referencia"
    if direction == "earlier":
        return f"reaplicar el acelerador aproximadamente {magnitude} m más temprano hacia el punto de la referencia"
    return None


def _throttle_release_target_text(pattern):
    if not isinstance(pattern, dict) or pattern.get("status") != "REPEATED":
        return None
    magnitude = safe_int(pattern.get("coaching_magnitude_m"))
    direction = pattern.get("coaching_direction")
    if magnitude is None or magnitude < THROTTLE_RELEASE_SESSION_MIN_DELTA_M:
        return None
    if direction == "later":
        return f"soltar el acelerador aproximadamente {magnitude} m más tarde hacia el punto de la referencia"
    if direction == "earlier":
        return f"soltar el acelerador aproximadamente {magnitude} m más temprano hacia el punto de la referencia"
    return None

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
            _region_has_actionable_coaching(region)
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
                    item.get("target")
                    for item in (region.get("repeated_differences", []) or [])
                    if item.get("target")
                ],
            "observation_only_differences":
                [
                    item.get("description")
                    for item in (region.get("repeated_differences", []) or [])
                    if item.get("description") and not item.get("target")
                ],
            "reference_action_profiles":
                [
                    item.get("reference_action_profile")
                    for item in (region.get("repeated_differences", []) or [])
                    if isinstance(item.get("reference_action_profile"), dict)
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
            "temporal_target":
                None,
            "braking_point_patterns":
                region.get(
                    "braking_point_patterns",
                    [],
                ),
            "braking_point_target":
                (
                    _braking_point_target_text(
                        (region.get("braking_point_patterns", []) or [None])[0]
                    )
                    if region.get("braking_point_patterns")
                    else None
                ),
            "brake_release_patterns":
                region.get(
                    "brake_release_patterns",
                    [],
                ),
            "brake_release_target":
                (
                    _brake_release_target_text(
                        (region.get("brake_release_patterns", []) or [None])[0]
                    )
                    if region.get("brake_release_patterns")
                    else None
                ),
            "throttle_onset_patterns":
                region.get(
                    "throttle_onset_patterns",
                    [],
                ),
            "throttle_onset_target":
                (
                    _throttle_onset_target_text(
                        (region.get("throttle_onset_patterns", []) or [None])[0]
                    )
                    if region.get("throttle_onset_patterns")
                    else None
                ),
            "throttle_release_patterns":
                region.get(
                    "throttle_release_patterns",
                    [],
                ),
            "throttle_release_target":
                (
                    _throttle_release_target_text(
                        (region.get("throttle_release_patterns", []) or [None])[0]
                    )
                    if region.get("throttle_release_patterns")
                    else None
                ),
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

        candidate = _single_finding_plan_item(
            finding,
            _alpha_label(len(plan)),
        )
        if _plan_item_has_actionable_coaching(candidate):
            plan.append(candidate)

    return plan



# ============================================================
# PRIORIDAD DE SESIÓN POR RECURRENCIA v3.10.8
# ============================================================

SESSION_PRIORITY_POLICY_VERSION = "1.9"


def _plan_overlap_m(
    first,
    second,
):
    values = [
        safe_float(first.get("start_distance_m")),
        safe_float(first.get("end_distance_m")),
        safe_float(second.get("start_distance_m")),
        safe_float(second.get("end_distance_m")),
    ]

    if any(value is None for value in values):
        return 0.0

    a0, a1, b0, b1 = values

    if a1 < a0:
        a0, a1 = a1, a0

    if b1 < b0:
        b0, b1 = b1, b0

    return max(
        0.0,
        min(a1, b1) - max(a0, b0),
    )


def _same_plan_region(
    first,
    second,
):
    """
    Matcher descriptivo intra-sesión.

    Prioriza una ubicación de pista idéntica; si no existe, exige
    solapamiento espacial material. No se persiste entre sesiones.
    """
    first_label = track_location_label(
        first
    )
    second_label = track_location_label(
        second
    )

    if (
        first_label
        and second_label
        and first_label == second_label
    ):
        return True

    overlap = _plan_overlap_m(
        first,
        second,
    )

    if overlap <= 0.0:
        return False

    first_start = safe_float(
        first.get("start_distance_m")
    )
    first_end = safe_float(
        first.get("end_distance_m")
    )
    second_start = safe_float(
        second.get("start_distance_m")
    )
    second_end = safe_float(
        second.get("end_distance_m")
    )

    if any(
        value is None
        for value in (
            first_start,
            first_end,
            second_start,
            second_end,
        )
    ):
        return False

    first_len = max(
        abs(first_end - first_start),
        1.0,
    )
    second_len = max(
        abs(second_end - second_start),
        1.0,
    )

    required = min(
        20.0,
        0.20 * min(first_len, second_len),
    )

    return overlap >= required


def _empty_repeated_point_plan_item(
    pattern,
):
    return {
        "plan_label": None,
        "kind": "repeated_point_pattern",
        "start_distance_m": pattern.get(
            "start_distance_m"
        ),
        "end_distance_m": pattern.get(
            "end_distance_m"
        ),
        "track_location": pattern.get(
            "track_location"
        ),
        "comparisons": [],
        "comparison_count": 0,
        "observed_differences": [],
        "targets": [],
        "quantitative_observations": [],
        "temporal_relationships": [],
        "temporal_target": None,
        "braking_point_patterns": [],
        "braking_point_target": None,
        "brake_release_patterns": [],
        "brake_release_target": None,
        "throttle_onset_patterns": [],
        "throttle_onset_target": None,
        "throttle_release_patterns": [],
        "throttle_release_target": None,
        "speed_directions": [],
        "propagation_statuses": [],
        "session_priority_basis": {
            "repeated_evidence": True,
            "point_pattern_count": 0,
            "comparison_count": 0,
        },
    }


def _attach_point_pattern_to_plan_item(
    item,
    pattern,
    field_name,
    target_name,
    target_builder,
):
    if not isinstance(item, dict) or not isinstance(pattern, dict):
        return

    existing = item.setdefault(
        field_name,
        [],
    )

    if pattern not in existing:
        existing.append(
            pattern
        )

    if not item.get(
        target_name
    ):
        item[target_name] = target_builder(
            pattern
        )

    comparisons = {
        str(value)
        for value in (
            item.get(
                "comparisons",
                [],
            )
            or []
        )
        if value
    }

    comparisons.update(
        str(value)
        for value in (
            pattern.get(
                "comparisons",
                [],
            )
            or []
        )
        if value
    )

    item["comparisons"] = sorted(
        comparisons
    )
    item["comparison_count"] = max(
        safe_int(
            item.get(
                "comparison_count"
            )
        )
        or 0,
        safe_int(
            pattern.get(
                "comparison_count"
            )
        )
        or 0,
        len(comparisons),
    )

    starts = [
        safe_float(
            item.get(
                "start_distance_m"
            )
        ),
        safe_float(
            pattern.get(
                "start_distance_m"
            )
        ),
    ]
    starts = [
        value
        for value in starts
        if value is not None
    ]

    ends = [
        safe_float(
            item.get(
                "end_distance_m"
            )
        ),
        safe_float(
            pattern.get(
                "end_distance_m"
            )
        ),
    ]
    ends = [
        value
        for value in ends
        if value is not None
    ]

    if starts:
        item["start_distance_m"] = min(
            starts
        )

    if ends:
        item["end_distance_m"] = max(
            ends
        )

    basis = item.setdefault(
        "session_priority_basis",
        {},
    )
    basis["repeated_evidence"] = True
    basis["point_pattern_count"] = (
        safe_int(
            basis.get(
                "point_pattern_count"
            )
        )
        or 0
    ) + 1
    basis["comparison_count"] = max(
        safe_int(
            basis.get(
                "comparison_count"
            )
        )
        or 0,
        item.get(
            "comparison_count",
            0,
        ),
    )


def _standalone_repeated_point_candidates(
    existing_plan,
    pattern_specs,
):
    """
    Crea candidatos sólo para patrones físicos repetidos que todavía no
    están representados por una zona del plan.

    Ejemplo Spa:
      Les Combes reaplicación repetida -> candidato de sesión propio.
    """
    candidates = []

    for (
        patterns,
        field_name,
        target_name,
        target_builder,
    ) in pattern_specs:
        for pattern in (
            patterns
            or []
        ):
            if (
                not isinstance(
                    pattern,
                    dict,
                )
                or
                pattern.get(
                    "status"
                )
                != "REPEATED"
                or (
                    safe_int(
                        pattern.get(
                            "comparison_count"
                        )
                    )
                    or 0
                )
                < 2
            ):
                continue

            represented = any(
                _same_plan_region(
                    item,
                    pattern,
                )
                for item in (
                    existing_plan
                    or []
                )
                if isinstance(
                    item,
                    dict,
                )
            )

            if represented:
                continue

            candidate = next(
                (
                    item
                    for item in candidates
                    if _same_plan_region(
                        item,
                        pattern,
                    )
                ),
                None,
            )

            if candidate is None:
                candidate = (
                    _empty_repeated_point_plan_item(
                        pattern
                    )
                )
                candidates.append(
                    candidate
                )

            _attach_point_pattern_to_plan_item(
                candidate,
                pattern,
                field_name,
                target_name,
                target_builder,
            )

    return candidates


def _session_plan_sort_key(
    item,
):
    """
    v3.10.8.5.4: prioridad por especificidad + calidad del hallazgo.

    Jerarquía:
      1) punto físico REPETIDO (Braking Point 2.1 / Throttle Point 1.2.1);
      2) punto físico VALID individual autorizado;
      3) reference_action_profile concreto;
      4) resto de evidencia accionable.

    Dentro del tier de puntos repetidos, el soporte del propio punto físico
    precede a la recurrencia más amplia de la zona. Esto evita que una zona
    frecuente con un punto observado pocas veces desplace a un punto físico
    mejor repetido.

    Dentro del tier individual, el orden es:
      comparison_priority_rank -> episode_priority_rank -> pérdida local.
    La posición en pista es únicamente el último desempate absoluto.
    """
    kind = item.get("kind")

    point_fields = (
        "braking_point_patterns",
        "brake_release_patterns",
        "throttle_onset_patterns",
        "throttle_release_patterns",
    )
    point_patterns = [
        pattern
        for field in point_fields
        for pattern in (item.get(field, []) or [])
        if isinstance(pattern, dict)
    ]

    repeated_point_count = sum(
        1 for pattern in point_patterns
        if (
            pattern.get("status") == "REPEATED"
            and bool(pattern.get("authorized_numeric_coaching"))
        )
    )
    repeated_point_support_count = max(
        [
            safe_int(pattern.get("comparison_count")) or 1
            for pattern in point_patterns
            if (
                pattern.get("status") == "REPEATED"
                and bool(pattern.get("authorized_numeric_coaching"))
            )
        ],
        default=0,
    )
    single_authorized_point_count = sum(
        1 for pattern in point_patterns
        if (
            pattern.get("status") == "SINGLE"
            and bool(pattern.get("authorized_numeric_coaching"))
        )
    )
    point_pattern_count = len(point_patterns)

    profile_count = len([
        profile
        for profile in (item.get("reference_action_profiles", []) or [])
        if isinstance(profile, dict) and str(profile.get("shape_summary") or "").strip()
    ])

    if repeated_point_count:
        evidence_tier = 0
    elif single_authorized_point_count:
        evidence_tier = 1
    elif profile_count:
        evidence_tier = 2
    else:
        evidence_tier = 3

    repeated = int(
        kind in {"repeated_region", "repeated_point_pattern"}
    )
    comparison_count = safe_int(item.get("comparison_count")) or 0
    comparison_rank = (
        safe_int(item.get("comparison_priority_rank"))
        or safe_int((item.get("source_priority") or {}).get("comparison_priority_rank"))
        or 999999
    )
    episode_rank = (
        safe_int(item.get("best_episode_priority_rank"))
        or safe_int(item.get("episode_priority_rank"))
        or safe_int((item.get("source_priority") or {}).get("episode_priority_rank"))
        or 999999
    )
    max_loss = abs(
        safe_float(item.get("max_action_time_loss_s"))
        or safe_float(item.get("action_time_loss_s"))
        or 0.0
    )
    start = safe_float(item.get("start_distance_m"))
    start_key = start if start is not None else 999999.0

    if evidence_tier == 0:
        return (
            0,
            -repeated_point_support_count,
            -repeated_point_count,
            -comparison_count,
            comparison_rank,
            episode_rank,
            -max_loss,
            -point_pattern_count,
            start_key,
        )

    if evidence_tier == 1:
        return (
            1,
            comparison_rank,
            episode_rank,
            -max_loss,
            -single_authorized_point_count,
            -point_pattern_count,
            start_key,
            0,
        )

    if evidence_tier == 2:
        return (
            2,
            -repeated,
            -comparison_count,
            comparison_rank,
            episode_rank,
            -max_loss,
            -profile_count,
            start_key,
        )

    return (
        3,
        -repeated,
        -comparison_count,
        comparison_rank,
        episode_rank,
        -max_loss,
        -point_pattern_count,
        start_key,
    )


def _apply_recurrence_aware_session_priority(
    plan,
    repeated_braking_point_patterns,
    repeated_brake_release_patterns,
    repeated_throttle_onset_patterns,
    repeated_throttle_release_patterns,
    max_items=3,
):
    """
    v3.10.8

    Reordena únicamente el plan GLOBAL de próxima tanda.

    No cambia:
      - detección de episodios;
      - clasificación/ranking dentro de cada comparación;
      - detectores de freno/acelerador;
      - hechos objetivos.

    Un patrón físico repetido puede desplazar a un hallazgo individual si
    reaparece en múltiples comparaciones.
    """
    base_plan = [
        item
        for item in (
            plan
            or []
        )
        if isinstance(
            item,
            dict,
        )
    ]

    pattern_specs = [
        (
            repeated_braking_point_patterns,
            "braking_point_patterns",
            "braking_point_target",
            _braking_point_target_text,
        ),
        (
            repeated_brake_release_patterns,
            "brake_release_patterns",
            "brake_release_target",
            _brake_release_target_text,
        ),
        (
            repeated_throttle_onset_patterns,
            "throttle_onset_patterns",
            "throttle_onset_target",
            _throttle_onset_target_text,
        ),
        (
            repeated_throttle_release_patterns,
            "throttle_release_patterns",
            "throttle_release_target",
            _throttle_release_target_text,
        ),
    ]

    # Primero adjuntamos patrones repetidos a zonas ya presentes.
    for (
        patterns,
        field_name,
        target_name,
        target_builder,
    ) in pattern_specs:
        for pattern in (
            patterns
            or []
        ):
            if (
                not isinstance(
                    pattern,
                    dict,
                )
                or
                pattern.get(
                    "status"
                )
                != "REPEATED"
            ):
                continue

            matching = [
                item
                for item in base_plan
                if _same_plan_region(
                    item,
                    pattern,
                )
            ]

            if not matching:
                continue

            matching.sort(
                key=lambda item: (
                    _plan_overlap_m(
                        item,
                        pattern,
                    ),
                    int(
                        item.get(
                            "kind"
                        )
                        == "repeated_region"
                    ),
                ),
                reverse=True,
            )

            _attach_point_pattern_to_plan_item(
                matching[0],
                pattern,
                field_name,
                target_name,
                target_builder,
            )

    standalone = (
        _standalone_repeated_point_candidates(
            base_plan,
            pattern_specs,
        )
    )

    candidates = (
        base_plan
        +
        standalone
    )

    candidates.sort(
        key=_session_plan_sort_key
    )

    selected = candidates[
        :max_items
    ]

    for index, item in enumerate(
        selected
    ):
        item["plan_label"] = (
            _alpha_label(
                index
            )
        )

        basis = item.setdefault(
            "session_priority_basis",
            {},
        )
        basis["policy_version"] = (
            SESSION_PRIORITY_POLICY_VERSION
        )
        basis["kind"] = item.get(
            "kind"
        )
        basis["comparison_count"] = (
            safe_int(
                item.get(
                    "comparison_count"
                )
            )
            or 0
        )
        basis["repeated_evidence"] = (
            item.get(
                "kind"
            )
            in {
                "repeated_region",
                "repeated_point_pattern",
            }
        )

    return selected

def _attach_repeated_throttle_patterns_to_plan(
    plan,
    onset_patterns,
    release_patterns,
):
    """
    Un patrón repetido de throttle puede aparecer en una zona elegida para el
    plan aunque esa zona haya entrado como single_priority_finding.

    v3.8.30 sólo adjuntaba patrones que ya vivían dentro de priority_regions;
    eso dejaba, por ejemplo, un onset repetido de Bus Stop en el respaldo
    técnico pero fuera del coaching de Zona C.
    """
    if not isinstance(plan, list):
        return plan

    def overlap_m(a_start, a_end, b_start, b_end):
        values = [
            safe_float(a_start),
            safe_float(a_end),
            safe_float(b_start),
            safe_float(b_end),
        ]
        if any(value is None for value in values):
            return 0.0

        a0, a1, b0, b1 = values
        return max(0.0, min(a1, b1) - max(a0, b0))

    def attach(patterns, field_name, target_name, target_builder):
        for pattern in patterns or []:
            if (
                not isinstance(pattern, dict)
                or pattern.get("status") != "REPEATED"
            ):
                continue

            candidates = []
            for item in plan:
                overlap = overlap_m(
                    item.get("start_distance_m"),
                    item.get("end_distance_m"),
                    pattern.get("start_distance_m"),
                    pattern.get("end_distance_m"),
                )
                if overlap <= 0.0:
                    continue

                item_location = track_location_label(item)
                pattern_location = track_location_label(pattern)
                same_location = int(
                    bool(item_location)
                    and bool(pattern_location)
                    and item_location == pattern_location
                )

                candidates.append(
                    (same_location, overlap, item)
                )

            if not candidates:
                continue

            candidates.sort(
                key=lambda row: (row[0], row[1]),
                reverse=True,
            )
            item = candidates[0][2]

            existing = item.setdefault(field_name, [])
            signature = (
                pattern.get("reference_onset_m"),
                pattern.get("reference_release_m"),
                pattern.get("coaching_direction"),
                pattern.get("coaching_magnitude_m"),
            )
            existing_signatures = {
                (
                    value.get("reference_onset_m"),
                    value.get("reference_release_m"),
                    value.get("coaching_direction"),
                    value.get("coaching_magnitude_m"),
                )
                for value in existing
                if isinstance(value, dict)
            }

            if signature not in existing_signatures:
                existing.append(pattern)

            if not item.get(target_name):
                item[target_name] = target_builder(pattern)

    attach(
        onset_patterns,
        "throttle_onset_patterns",
        "throttle_onset_target",
        _throttle_onset_target_text,
    )
    attach(
        release_patterns,
        "throttle_release_patterns",
        "throttle_release_target",
        _throttle_release_target_text,
    )

    return plan




# ============================================================
# CALIDAD GLOBAL DE COMPARACIÓN v3.10.8
# ============================================================

SESSION_COMPARISON_QUALITY_GATE_VERSION = "1.1"
SESSION_COMPARISON_QUALITY_MIN_COUNT = 3
SESSION_COMPARISON_QUALITY_MAD_SIGMA_MULTIPLIER = 6.0
SESSION_COMPARISON_QUALITY_MIN_MARGIN_S = 1.0
SESSION_COMPARISON_QUALITY_RATIO_MULTIPLIER = 3.0


def _session_comparison_key(comparison):
    if not isinstance(comparison, dict):
        return "comparison"
    reference_lap = safe_int(comparison.get("reference_lap"))
    comparison_lap = safe_int(comparison.get("comparison_lap"))
    if reference_lap is not None and comparison_lap is not None:
        return f"{reference_lap}->{comparison_lap}"
    return "comparison"


def _comparison_quality_diagnostics(comparison):
    """
    v3.10.8.5.4 — diagnóstico determinista para confirmar o rechazar un
    candidato estadístico del quality gate.

    Puede trabajar sobre una comparación cruda de analyze_telemetry,
    construyendo el catálogo de episodios sin LLM, o reutilizar
    episode_ground_truth si la comparación ya fue analizada.
    """
    if not isinstance(comparison, dict):
        return None

    episodes = comparison.get("episode_ground_truth")
    excluded_count = safe_int(comparison.get("excluded_anomaly_count")) or 0

    if not isinstance(episodes, list):
        try:
            detected = build_episode_catalog(comparison)
            episodes, excluded = split_episode_catalog_for_coaching(
                comparison,
                detected,
            )
            excluded_count = len(excluded or [])
        except Exception:
            return None

    episodes = [
        item for item in (episodes or [])
        if isinstance(item, dict)
    ]

    losses = [
        abs(safe_float(item.get("action_time_loss_s")) or 0.0)
        for item in episodes
    ]
    lengths = [
        max(0.0, safe_float(item.get("length_m")) or 0.0)
        for item in episodes
    ]
    abs_delta_edges = []
    for item in episodes:
        for key in ("delta_start_s", "delta_end_s"):
            value = safe_float(item.get(key))
            if value is not None:
                abs_delta_edges.append(abs(value))

    return {
        "available": True,
        "coaching_episode_count": len(episodes),
        "excluded_anomaly_count": excluded_count,
        "max_action_time_loss_s": max(losses, default=0.0),
        "median_action_time_loss_s": (
            float(statistics.median(losses))
            if losses else 0.0
        ),
        "sum_action_time_loss_s": sum(losses),
        "max_episode_length_m": max(lengths, default=0.0),
        "max_abs_episode_delta_s": max(abs_delta_edges, default=0.0),
    }


SESSION_COMPARISON_LOCAL_SEVERITY_SIGMA_MULTIPLIER = 8.0
SESSION_COMPARISON_LOCAL_SEVERITY_MIN_MARGIN_S = 1.0


def _confirm_statistical_comparison_outlier(candidate_row, baseline_rows):
    """
    Segunda etapa del gate 1.1.

    Un delta de vuelta atípico NO alcanza para excluir coaching. El candidato
    debe mostrar además severidad local extraordinaria respecto de las demás
    comparaciones de la propia sesión, o contener una anomalía determinista
    ya excluida por el anomaly gate.
    """
    diagnostic = candidate_row.get("diagnostics")
    if not isinstance(diagnostic, dict) or not diagnostic.get("available"):
        return {
            "confirmed": False,
            "reason": "insufficient_local_diagnostics",
            "local_severity_threshold_s": None,
            "baseline_local_loss_median_s": None,
            "baseline_local_loss_mad_s": None,
        }

    if (safe_int(diagnostic.get("excluded_anomaly_count")) or 0) > 0:
        return {
            "confirmed": True,
            "reason": "deterministic_local_anomaly_present",
            "local_severity_threshold_s": None,
            "baseline_local_loss_median_s": None,
            "baseline_local_loss_mad_s": None,
        }

    baseline_values = []
    for row in baseline_rows or []:
        other = row.get("diagnostics")
        if not isinstance(other, dict) or not other.get("available"):
            continue
        value = safe_float(other.get("max_action_time_loss_s"))
        if value is not None:
            baseline_values.append(max(0.0, value))

    if len(baseline_values) < 2:
        return {
            "confirmed": False,
            "reason": "insufficient_baseline_local_diagnostics",
            "local_severity_threshold_s": None,
            "baseline_local_loss_median_s": (
                float(statistics.median(baseline_values))
                if baseline_values else None
            ),
            "baseline_local_loss_mad_s": None,
        }

    baseline_median = float(statistics.median(baseline_values))
    baseline_deviations = [
        abs(value - baseline_median)
        for value in baseline_values
    ]
    baseline_mad = float(statistics.median(baseline_deviations))
    baseline_sigma = 1.4826 * baseline_mad

    threshold = baseline_median + max(
        SESSION_COMPARISON_LOCAL_SEVERITY_MIN_MARGIN_S,
        SESSION_COMPARISON_LOCAL_SEVERITY_SIGMA_MULTIPLIER * baseline_sigma,
    )

    candidate_local_loss = (
        safe_float(diagnostic.get("max_action_time_loss_s"))
        or 0.0
    )
    confirmed = candidate_local_loss > threshold

    return {
        "confirmed": confirmed,
        "reason": (
            "statistical_outlier_plus_extreme_local_loss"
            if confirmed
            else "statistical_outlier_without_extreme_local_loss"
        ),
        "candidate_max_local_loss_s": candidate_local_loss,
        "local_severity_threshold_s": threshold,
        "baseline_local_loss_median_s": baseline_median,
        "baseline_local_loss_mad_s": baseline_mad,
        "baseline_local_loss_robust_sigma_s": baseline_sigma,
    }


def build_session_comparison_quality_gate(valid_comparison_results):
    """
    Comparison Quality Gate v1.1.

    Etapa 1: mediana + MAD + criterio relativo -> candidato estadístico.
    Etapa 2: confirmación determinista de severidad local extraordinaria.

    Ser una vuelta más lenta no alcanza para excluirla del coaching.
    """
    rows = []
    for comparison in valid_comparison_results or []:
        if not isinstance(comparison, dict):
            continue
        if comparison.get("status") not in {None, "VALID"}:
            continue
        delta = safe_float(comparison.get("comparison_minus_reference_s"))
        if delta is None:
            continue
        rows.append({
            "comparison": _session_comparison_key(comparison),
            "reference_lap": safe_int(comparison.get("reference_lap")),
            "comparison_lap": safe_int(comparison.get("comparison_lap")),
            "comparison_minus_reference_s": delta,
            "abs_delta_s": abs(delta),
            "diagnostics": _comparison_quality_diagnostics(comparison),
        })

    if not rows:
        return {
            "version": SESSION_COMPARISON_QUALITY_GATE_VERSION,
            "status": "NO_VALID_COMPARISONS",
            "method": "median_mad_candidate_plus_local_severity_confirmation",
            "comparison_count": 0,
            "included_count": 0,
            "excluded_count": 0,
            "statistical_candidate_count": 0,
            "retained_statistical_outlier_count": 0,
            "comparisons": [],
        }

    values = [row["abs_delta_s"] for row in rows]
    median_delta = float(statistics.median(values))
    deviations = [abs(value - median_delta) for value in values]
    mad = float(statistics.median(deviations))
    robust_sigma = 1.4826 * mad

    enough = len(values) >= SESSION_COMPARISON_QUALITY_MIN_COUNT
    if enough:
        robust_threshold = median_delta + max(
            SESSION_COMPARISON_QUALITY_MIN_MARGIN_S,
            SESSION_COMPARISON_QUALITY_MAD_SIGMA_MULTIPLIER * robust_sigma,
        )
        relative_threshold = max(
            median_delta * SESSION_COMPARISON_QUALITY_RATIO_MULTIPLIER,
            median_delta + SESSION_COMPARISON_QUALITY_MIN_MARGIN_S,
        )
        candidate_threshold = max(robust_threshold, relative_threshold)
    else:
        robust_threshold = None
        relative_threshold = None
        candidate_threshold = None

    candidate_rows = []
    baseline_rows = []
    for row in rows:
        is_candidate = bool(
            enough
            and candidate_threshold is not None
            and row["abs_delta_s"] > candidate_threshold
        )
        row["statistical_outlier_candidate"] = is_candidate
        if is_candidate:
            candidate_rows.append(row)
        else:
            baseline_rows.append(row)

    excluded = []
    retained_candidates = []

    for row in rows:
        if not row["statistical_outlier_candidate"]:
            row["session_plan_eligible"] = True
            row["quality_status"] = "SESSION_PLAN_ELIGIBLE"
            row["reason"] = None
            row["confirmation"] = None
            continue

        confirmation = _confirm_statistical_comparison_outlier(
            row,
            baseline_rows,
        )
        row["confirmation"] = confirmation

        if confirmation.get("confirmed"):
            row["session_plan_eligible"] = False
            row["quality_status"] = "COACHING_EXCLUDED_NON_REPRESENTATIVE_LAP"
            row["reason"] = confirmation.get("reason")
            excluded.append(row["comparison"])
        else:
            row["session_plan_eligible"] = True
            row["quality_status"] = "STATISTICAL_OUTLIER_RETAINED_FOR_COACHING"
            row["reason"] = confirmation.get("reason")
            retained_candidates.append(row["comparison"])

    return {
        "version": SESSION_COMPARISON_QUALITY_GATE_VERSION,
        "status": "ACTIVE" if enough else "INSUFFICIENT_COMPARISONS_FOR_ROBUST_GATE",
        "method": "median_mad_candidate_plus_local_severity_confirmation",
        "comparison_count": len(rows),
        "included_count": sum(1 for row in rows if row["session_plan_eligible"]),
        "excluded_count": len(excluded),
        "statistical_candidate_count": len(candidate_rows),
        "retained_statistical_outlier_count": len(retained_candidates),
        "median_abs_delta_s": median_delta,
        "mad_abs_delta_s": mad,
        "robust_sigma_s": robust_sigma,
        "robust_threshold_s": robust_threshold,
        "relative_threshold_s": relative_threshold,
        "candidate_threshold_s": candidate_threshold,
        "exclusion_threshold_s": candidate_threshold,
        "excluded_comparisons": excluded,
        "retained_statistical_outliers": retained_candidates,
        "comparisons": rows,
        "policy": (
            "statistical pace outlier is only a candidate; exclusion from "
            "session coaching requires deterministic local-severity confirmation"
        ),
    }


def _comparison_quality_map(quality_gate):
    return {
        str(row.get("comparison")): row
        for row in (quality_gate.get("comparisons", []) or [])
        if isinstance(row, dict) and row.get("comparison")
    }


def build_session_coaching_facts(
    valid_comparison_results,
    track_location_context=None,
    source_data=None,
):
    """
    Convierte comparaciones ya validadas en una ficha determinista.

    v3.10.8:
    - priority_findings conserva sólo episodios PRIORITARIOS para el tiebreak;
    - recurrence_findings usa TODOS los episodios coaching-eligible para que la
      recurrencia física no dependa de la clasificación elegida por el LLM;
    - los patrones repetidos sólo se declaran si reaparecen en una región
      espacial compatible y en múltiples comparaciones;
    - Python construye un plan concreto para la próxima tanda;
    - Python distingue secuencia/solapamiento de freno y acelerador;
    - Python resuelve nombres de curva únicamente desde un perfil validado;
    - no se infiere causalidad ni se permite al LLM inventar ubicaciones.
    """
    comparison_order = []
    priority_findings = []
    recurrence_findings = []
    braking_point_findings = []
    brake_release_findings = []
    throttle_onset_findings = []
    throttle_release_findings = []

    comparison_quality_gate = build_session_comparison_quality_gate(
        valid_comparison_results
    )
    comparison_quality_by_key = _comparison_quality_map(
        comparison_quality_gate
    )

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

        quality = comparison_quality_by_key.get(comparison_key, {})
        session_plan_eligible = bool(quality.get("session_plan_eligible", True))

        comparison_order.append({
            "reference_lap": reference_lap,
            "comparison_lap": comparison_lap,
            "comparison_minus_reference_s": safe_float(
                comparison.get("comparison_minus_reference_s")
            ),
            "driver_analysis_priority_rank": safe_int(
                comparison.get("driver_analysis_priority_rank")
            ),
            "session_plan_eligible": session_plan_eligible,
            "quality_status": quality.get("quality_status", "SESSION_PLAN_ELIGIBLE"),
        })

        if not session_plan_eligible:
            continue

        ranking_map = (
            _priority_ranking_map(
                comparison
            )
        )

        assessment_by_episode = {
            safe_int(item.get("episode_id")): item
            for item in (
                ((comparison.get("llm_structured") or {}).get("episode_assessments", []))
                or []
            )
            if isinstance(item, dict) and safe_int(item.get("episode_id")) is not None
        }

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

            braking_point = _session_braking_point_fact(
                episode
            )

            if braking_point is not None:
                braking_point_findings.append({
                    "comparison": comparison_key,
                    "reference_lap": reference_lap,
                    "comparison_lap": comparison_lap,
                    "episode_id": episode_id,
                    "classification": classification,
                    "start_distance_m": safe_float(episode.get("start_distance_m")),
                    "end_distance_m": safe_float(episode.get("end_distance_m")),
                    "track_location": episode.get("track_location"),
                    "action_time_loss_s": safe_float(episode.get("action_time_loss_s")),
                    "braking_point": braking_point,
                })

            brake_release = _session_brake_release_fact(
                episode
            )

            if brake_release is not None:
                brake_release_findings.append({
                    "comparison": comparison_key,
                    "reference_lap": reference_lap,
                    "comparison_lap": comparison_lap,
                    "episode_id": episode_id,
                    "classification": classification,
                    "start_distance_m": safe_float(episode.get("start_distance_m")),
                    "end_distance_m": safe_float(episode.get("end_distance_m")),
                    "track_location": episode.get("track_location"),
                    "action_time_loss_s": safe_float(episode.get("action_time_loss_s")),
                    "brake_release": brake_release,
                })

            throttle_onset = _session_throttle_onset_fact(episode)
            if throttle_onset is not None:
                throttle_onset_findings.append({
                    "comparison": comparison_key,
                    "reference_lap": reference_lap,
                    "comparison_lap": comparison_lap,
                    "episode_id": episode_id,
                    "classification": classification,
                    "start_distance_m": safe_float(episode.get("start_distance_m")),
                    "end_distance_m": safe_float(episode.get("end_distance_m")),
                    "track_location": episode.get("track_location"),
                    "action_time_loss_s": safe_float(episode.get("action_time_loss_s")),
                    "throttle_onset": throttle_onset,
                })

            throttle_release = _session_throttle_release_fact(episode)
            if throttle_release is not None:
                throttle_release_findings.append({
                    "comparison": comparison_key,
                    "reference_lap": reference_lap,
                    "comparison_lap": comparison_lap,
                    "episode_id": episode_id,
                    "classification": classification,
                    "start_distance_m": safe_float(episode.get("start_distance_m")),
                    "end_distance_m": safe_float(episode.get("end_distance_m")),
                    "track_location": episode.get("track_location"),
                    "action_time_loss_s": safe_float(episode.get("action_time_loss_s")),
                    "throttle_release": throttle_release,
                })

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

            assessment = assessment_by_episode.get(episode_id, {})
            validated_recommendation = str(assessment.get("recommendation") or "").strip()
            steering_coaching_requested = bool(
                validated_recommendation
                and _steering_direct_action_present(validated_recommendation)
                and "steering_magnitude" in set(episode.get("action_channels", []) or [])
            )

            finding = {
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
                "track_location":
                    episode.get(
                        "track_location"
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
                "steering_coaching_requested":
                    steering_coaching_requested,
                "validated_recommendation":
                    validated_recommendation,
                "channels":
                    channels,
                "brake_throttle_relation":
                    brake_throttle_relation,
                "braking_point":
                    braking_point,
                "brake_release":
                    brake_release,
                "throttle_onset":
                    throttle_onset,
                "throttle_release":
                    throttle_release,
                **speed_context,
            }

            # La recurrencia física pertenece al ground truth, no al ranker LLM.
            recurrence_findings.append(finding)

            if classification == "PRIORITARIO":
                priority_findings.append(finding)

    recurrence_findings.sort(
        key=lambda item: (
            item.get("comparison_priority_rank")
            if item.get("comparison_priority_rank") is not None
            else 999999,
            -abs(item.get("action_time_loss_s") or 0.0),
            item.get("start_distance_m")
            if item.get("start_distance_m") is not None
            else 999999.0,
            item.get("episode_id")
            if item.get("episode_id") is not None
            else 999999,
        )
    )

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

    # Regiones de coaching: conservan el filtro PRIORITARIO del ranker, pero
    # su orden interno ya no usa relative_priority_rank como criterio.
    priority_regions = (
        _build_priority_regions(
            priority_findings
        )
    )

    # Capa física independiente del modelo: todos los episodios elegibles
    # alimentan recurrencia, sin cambiar por PRIORITARIO/SECUNDARIO/NO_ACCIONABLE.
    recurrence_regions = _sanitize_recurrence_regions(
        _build_priority_regions(
            recurrence_findings
        )
    )

    enrich_items_with_track_location(
        priority_regions,
        track_location_context,
    )
    enrich_items_with_track_location(
        recurrence_regions,
        track_location_context,
    )

    # v3.10.8: el target mixed de acelerador sólo existe si Python puede
    # explicar la forma observada de la vuelta de referencia.
    _attach_reference_action_profiles(
        priority_regions,
        source_data,
    )
    _attach_reference_action_profiles(
        recurrence_regions,
        source_data,
    )

    repeated_braking_point_patterns = (
        _build_repeated_braking_point_patterns(
            braking_point_findings,
            recurrence_regions,
        )
    )

    repeated_brake_release_patterns = (
        _build_repeated_brake_release_patterns(
            brake_release_findings,
            recurrence_regions,
        )
    )

    repeated_throttle_onset_patterns = (
        _build_repeated_throttle_patterns(
            throttle_onset_findings,
            recurrence_regions,
            fact_key="throttle_onset",
            point_key="reference_onset_m",
            min_delta_m=THROTTLE_ONSET_SESSION_MIN_DELTA_M,
            tolerance_m=THROTTLE_ONSET_PATTERN_REFERENCE_TOLERANCE_M,
            region_field="throttle_onset_patterns",
        )
    )

    repeated_throttle_release_patterns = (
        _build_repeated_throttle_patterns(
            throttle_release_findings,
            recurrence_regions,
            fact_key="throttle_release",
            point_key="reference_release_m",
            min_delta_m=THROTTLE_RELEASE_SESSION_MIN_DELTA_M,
            tolerance_m=THROTTLE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M,
            region_field="throttle_release_patterns",
        )
    )

    # Un patrón físico puede ser válido aunque no haya formado una
    # priority_region. Resolver igualmente su nombre de curva desde el perfil
    # validado usando su intervalo agregado, para TODOS los tipos de punto.
    enrich_items_with_track_location(
        repeated_braking_point_patterns,
        track_location_context,
    )
    enrich_items_with_track_location(
        repeated_brake_release_patterns,
        track_location_context,
    )
    enrich_items_with_track_location(
        repeated_throttle_onset_patterns,
        track_location_context,
    )
    enrich_items_with_track_location(
        repeated_throttle_release_patterns,
        track_location_context,
    )

    # H5.4/P1 — precisión driver-facing derivada. La coordenada LMU absoluta
    # permanece intacta; sólo se añade provenance de vueltas y una referencia
    # relativa a curva cuando existe un perfil validado.
    precision_profile = (
        track_location_context.get("profile")
        if isinstance(track_location_context, dict)
        and track_location_context.get("status") == "ACTIVE"
        else None
    )
    enrich_patterns_with_precision(
        repeated_braking_point_patterns,
        precision_profile,
        event_kind="braking_onset",
        point_key="reference_onset_m",
    )
    enrich_patterns_with_precision(
        repeated_brake_release_patterns,
        precision_profile,
        event_kind="brake_release",
        point_key="reference_release_m",
    )
    enrich_patterns_with_precision(
        repeated_throttle_onset_patterns,
        precision_profile,
        event_kind="throttle_onset",
        point_key="reference_onset_m",
    )
    enrich_patterns_with_precision(
        repeated_throttle_release_patterns,
        precision_profile,
        event_kind="throttle_release",
        point_key="reference_release_m",
    )

    # Patrones usados por el debrief mantienen compatibilidad con el plan de
    # coaching. En paralelo exponemos una capa de recurrencia puramente física.
    repeated_input_patterns = []

    for region in recurrence_regions:
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
                "track_location":
                    region.get(
                        "track_location"
                    ),
            })

    repeated_input_patterns.sort(
        key=lambda item: (
            -item.get(
                "comparison_count",
                0,
            ),
            -item.get(
                "recurrence_episode_count",
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

    recurrence_input_patterns = []

    for region in recurrence_regions:
        if region.get("comparison_count", 0) < 2:
            continue

        for repeated in (region.get("repeated_differences", []) or []):
            recurrence_pattern = {
                **repeated,
                "region_label": region.get("region_label"),
                "start_distance_m": region.get("start_distance_m"),
                "end_distance_m": region.get("end_distance_m"),
                "track_location": region.get("track_location"),
            }
            recurrence_pattern.pop("priority_episode_count", None)
            recurrence_input_patterns.append(recurrence_pattern)

    recurrence_input_patterns.sort(
        key=lambda item: (
            -item.get("comparison_count", 0),
            -item.get("recurrence_episode_count", 0),
            item.get("start_distance_m")
            if item.get("start_distance_m") is not None
            else 999999.0,
            item.get("description") or "",
        )
    )

    next_stint_plan = (
        _build_next_stint_plan(
            recurrence_regions,
            priority_findings,
            max_items=max(
                3,
                len(recurrence_regions) + len(priority_findings),
            ),
        )
    )

    enrich_items_with_track_location(
        next_stint_plan,
        track_location_context,
    )

    _attach_repeated_throttle_patterns_to_plan(
        next_stint_plan,
        repeated_throttle_onset_patterns,
        repeated_throttle_release_patterns,
    )

    next_stint_plan = (
        _apply_recurrence_aware_session_priority(
            next_stint_plan,
            repeated_braking_point_patterns,
            repeated_brake_release_patterns,
            repeated_throttle_onset_patterns,
            repeated_throttle_release_patterns,
        )
    )

    enrich_items_with_track_location(
        next_stint_plan,
        track_location_context,
    )

    # H5.4/P2 — extend the same deterministic precision layer to the final
    # selected plan, including authorized SINGLE physical-point cues.
    enrich_plan_items_with_precision(
        next_stint_plan,
        precision_profile,
    )

    # H5.4/P7 — additive deterministic consolidation of already-authorized
    # physical-point cues. Original patterns remain untouched.
    enrich_plan_items_with_coaching_sequence(next_stint_plan)

    _attach_point_anchored_reference_profiles(
        next_stint_plan,
        source_data,
    )

    for item in next_stint_plan:
        if not isinstance(item, dict):
            continue
        item["driver_cues"] = build_driver_cues_for_plan_item(item, max_cues=2)
        # H5.4/P8 — deterministic driver-facing cue priority ordering
        item["driver_cues"] = enrich_cues_with_deterministic_priority(
            item["driver_cues"],
        )
        item["actionable_cue_count"] = len(item["driver_cues"])

    # H5.4/P9 — deterministic cross-zone driver-plan diversity ordering
    next_stint_plan = enrich_plan_with_p9_presentation_metadata(
        next_stint_plan,
    )

    # H5.4/P10 — deterministic driver-facing plan projection
    next_stint_plan_presentation = build_p10_plan_presentation(next_stint_plan)

    # H5.4/P11 — deterministic driver focus slots
    next_stint_focus = build_p11_plan_focus(next_stint_plan, next_stint_plan_presentation)

    return {
        "track_location_profile":
            track_location_context_summary(
                track_location_context
            ),
        "comparison_quality_gate":
            comparison_quality_gate,
        "comparison_order":
            comparison_order,
        "priority_findings":
            priority_findings,
        "recurrence_findings":
            recurrence_findings,
        "priority_regions":
            priority_regions,
        "recurrence_regions":
            recurrence_regions,
        "repeated_input_patterns":
            repeated_input_patterns,
        "recurrence_input_patterns":
            recurrence_input_patterns,
        "repeated_braking_point_patterns":
            repeated_braking_point_patterns,
        "repeated_brake_release_patterns":
            repeated_brake_release_patterns,
        "repeated_throttle_onset_patterns":
            repeated_throttle_onset_patterns,
        "repeated_throttle_release_patterns":
            repeated_throttle_release_patterns,
        "next_stint_plan":
            next_stint_plan,
        "next_stint_plan_presentation":
            next_stint_plan_presentation,
        "next_stint_focus":
            next_stint_focus,
        "session_priority_policy": {
            "version":
                SESSION_PRIORITY_POLICY_VERSION,
            "method":
                "physical_point_support_then_specificity_then_priority_rank",
            "order":
                [
                    "repeated_physical_point",
                    "single_authorized_physical_point",
                    "reference_action_profile",
                    "other_actionable_evidence",
                    "comparison_priority_rank",
                    "episode_priority_rank",
                    "local_loss_tiebreak",
                    "track_distance_last_tiebreak",
                ],
            "per_comparison_ranker_unchanged":
                True,
            "per_comparison_ranker_used_for_recurrence":
                False,
            "recurrence_source":
                "session_plan_eligible_coaching_episode_ground_truth",
            "comparison_quality_gate":
                "median_mad_candidate_plus_local_severity_confirmation",
            "comparison_quality_exclusion_scope":
                "session_aggregation_only",
            "repeated_input_pattern_source":
                "recurrence_regions",
            "next_stint_plan_source":
                "recurrence_regions_plus_physical_points_profiles_and_validated_priority_steering",
            "temporal_observation_policy":
                "descriptive_only_without_temporal_target",
            "mixed_throttle_target_policy":
                "reference_action_profile_or_omit",
            "mixed_brake_target_policy":
                "reference_action_profile_or_omit",
            "actionability_policy_version":
                SESSION_ACTIONABILITY_POLICY_VERSION,
            "generic_channel_difference_policy":
                "qualitative_reference_alignment_for_unambiguous_brake_throttle; steering_separate_validated_path",
            "steering_target_policy":
                "validated_llm_direct_or_secondary_low_priority_no_causal_claim",
            "driver_cue_limit_per_zone":
                2,
            "reference_action_profile_source": {
                "throttle":
                    "throttle_physical_point_profiles.reference_event",
                "brake":
                    "driver_action_episode_ranking.braking_point_comparison+brake_release_point_comparison",
            },
        },
        "priority_finding_count":
            len(
                priority_findings
            ),
        "recurrence_finding_count":
            len(
                recurrence_findings
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

    lower_speed_seen = (
        "lower_in_comparison_lap"
        in speed_directions
    )
    higher_speed_seen = (
        "higher_in_comparison_lap"
        in speed_directions
    )

    if lower_speed_seen and higher_speed_seen:
        speed_context.append(
            "velocidad variable respecto de la referencia "
            "entre comparaciones"
        )
    elif lower_speed_seen:
        speed_context.append(
            "velocidad inferior a la referencia"
        )
    elif higher_speed_seen:
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
    v3.10.8

    El LLM global recibe únicamente hechos CUALITATIVOS.

    Python conserva en privado:
      - magnitudes de input;
      - metros;
      - cantidades de comparaciones;
      - tiempos;
      - cualquier cifra autorizada.

    Esas cifras se insertan después de la respuesta LLM mediante render
    determinista. Así el modelo no puede copiarlas, modificarlas ni
    reubicarlas en opportunities/conclusion.
    """
    plan = []

    for item in (
        session_coaching_facts.get(
            "next_stint_plan",
            [],
        )
        or []
    )[:3]:
        def qualitative_point_coaching(
            field_name,
        ):
            patterns = (
                item.get(
                    field_name,
                    [],
                )
                or []
            )

            if not patterns:
                return None

            pattern = patterns[0]

            if not isinstance(
                pattern,
                dict,
            ):
                return None

            direction = pattern.get(
                "coaching_direction"
            )

            if direction not in {
                "earlier",
                "later",
            }:
                return None

            return {
                "authorized": True,
                "direction": direction,
            }

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
                item.get("targets", []),
            "driver_cues":
                [
                    {
                        "channel": cue.get("channel"),
                        "kind": cue.get("kind"),
                    }
                    for cue in (item.get("driver_cues", []) or [])
                    if isinstance(cue, dict) and cue.get("channel")
                ],
            "observation_only_differences":
                item.get("observation_only_differences", []),
            "temporal_observations":
                item.get(
                    "temporal_relationships",
                    [],
                ),
            "temporal_target":
                item.get(
                    "temporal_target"
                ),
            "braking_point_coaching":
                qualitative_point_coaching(
                    "braking_point_patterns"
                ),
            "brake_release_coaching":
                qualitative_point_coaching(
                    "brake_release_patterns"
                ),
            "throttle_onset_coaching":
                qualitative_point_coaching(
                    "throttle_onset_patterns"
                ),
            "throttle_release_coaching":
                qualitative_point_coaching(
                    "throttle_release_patterns"
                ),
            "repeated_across_multiple_comparisons":
                (
                    item.get(
                        "kind"
                    )
                    in {
                        "repeated_region",
                        "repeated_point_pattern",
                    }
                ),
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
            "repeated_in_same_region":
                True,
        }
        for item in (
            session_coaching_facts.get(
                "recurrence_input_patterns",
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

    lower_speed_seen = (
        "lower_in_comparison_lap"
        in speed_directions
    )
    higher_speed_seen = (
        "higher_in_comparison_lap"
        in speed_directions
    )

    if lower_speed_seen and higher_speed_seen:
        parts.append(
            "velocidad variable respecto de la referencia "
            "entre comparaciones"
        )
    elif lower_speed_seen:
        parts.append(
            "velocidad inferior a la referencia"
        )
    elif higher_speed_seen:
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
        elif item.get("kind") == "repeated_point_pattern":
            basis = (
                f"punto de input repetido en {item.get('comparison_count')} comparaciones"
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

        braking_point_text = ""
        braking_patterns = (
            item.get("braking_point_patterns", [])
            or []
        )
        if braking_patterns:
            braking_pattern = braking_patterns[0]
            bp_magnitude = safe_int(
                braking_pattern.get("coaching_magnitude_m")
            )
            bp_direction = braking_pattern.get("coaching_direction")
            if bp_magnitude is not None and bp_direction == "later":
                braking_point_text = (
                    f" Punto de frenada: iniciá la frenada aproximadamente "
                    f"{bp_magnitude} m más tarde hacia la referencia."
                )
            elif bp_magnitude is not None and bp_direction == "earlier":
                braking_point_text = (
                    f" Punto de frenada: iniciá la frenada aproximadamente "
                    f"{bp_magnitude} m más temprano hacia la referencia."
                )

        brake_release_text = ""
        release_patterns = (
            item.get("brake_release_patterns", [])
            or []
        )
        if release_patterns:
            release_pattern = release_patterns[0]
            release_magnitude = safe_int(
                release_pattern.get("coaching_magnitude_m")
            )
            release_direction = release_pattern.get("coaching_direction")
            if (
                release_magnitude is not None
                and release_direction == "later"
            ):
                brake_release_text = (
                    f" Liberación de freno: soltá el freno aproximadamente "
                    f"{release_magnitude} m más tarde hacia la referencia."
                )
            elif (
                release_magnitude is not None
                and release_direction == "earlier"
            ):
                brake_release_text = (
                    f" Liberación de freno: soltá el freno aproximadamente "
                    f"{release_magnitude} m más temprano hacia la referencia."
                )

        throttle_onset_text = ""
        throttle_onset_patterns = item.get("throttle_onset_patterns", []) or []
        if throttle_onset_patterns:
            pattern = throttle_onset_patterns[0]
            magnitude = safe_int(pattern.get("coaching_magnitude_m"))
            direction = pattern.get("coaching_direction")
            if magnitude is not None and direction == "later":
                throttle_onset_text = (
                    f" Reaplicación de acelerador: reaplicá el acelerador aproximadamente "
                    f"{magnitude} m más tarde hacia la referencia."
                )
            elif magnitude is not None and direction == "earlier":
                throttle_onset_text = (
                    f" Reaplicación de acelerador: reaplicá el acelerador aproximadamente "
                    f"{magnitude} m más temprano hacia la referencia."
                )

        throttle_release_text = ""
        throttle_release_patterns = item.get("throttle_release_patterns", []) or []
        if throttle_release_patterns:
            pattern = throttle_release_patterns[0]
            magnitude = safe_int(pattern.get("coaching_magnitude_m"))
            direction = pattern.get("coaching_direction")
            if magnitude is not None and direction == "later":
                throttle_release_text = (
                    f" Liberación de acelerador: soltá el acelerador aproximadamente "
                    f"{magnitude} m más tarde hacia la referencia."
                )
            elif magnitude is not None and direction == "earlier":
                throttle_release_text = (
                    f" Liberación de acelerador: soltá el acelerador aproximadamente "
                    f"{magnitude} m más temprano hacia la referencia."
                )

        target_text = ""
        if targets:
            target_text = (
                " Objetivo de aplicación: "
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

        location = (
            track_location_label(
                item
            )
        )

        if location:
            zone_heading = (
                f"Zona {label} — {location} "
                f"({start_m}–{end_m})"
            )
        else:
            zone_heading = (
                f"Zona {label} "
                f"({start_m}–{end_m})"
            )

        sentences.append(
            f"{prefix}: {zone_heading}, {basis}."
            + details
            + temporal_text
            + braking_point_text
            + brake_release_text
            + throttle_onset_text
            + throttle_release_text
            + target_text
        )

    return " ".join(sentences)


# ============================================================
# PROMPT GLOBAL ESTRUCTURADO
# ============================================================

GLOBAL_SYSTEM_PROMPT = """
Sos un ingeniero de pista redactando el cierre de una sesión.

Python ya resolvió:
- qué hallazgos son prioritarios;
- qué diferencias de input fueron observadas;
- cuáles se repiten en la MISMA región del circuito;
- qué objetivo relativo a la vuelta de referencia corresponde a cada zona.

No vuelvas a investigar ni a decidir qué ocurrió.
No generalices una diferencia local a todo el circuito.

Tu trabajo es convertir el plan determinista de Python en coaching claro,
directo y ejecutable para la próxima tanda.

REGLAS:
- no agregues hechos, canales, causas ni conceptos que no estén en la ficha;
- no afirmes causalidad;
- no inventes contexto externo;
- no inventes nombres de curva, fase de curva, ápice, trayectoria ideal,
  entrada, salida ni "curvas críticas";
- el punto/inicio de frenada sólo puede mencionarse si el item contiene
  braking_point_coaching con authorized=true;
- la liberación del freno sólo puede mencionarse si el item contiene
  brake_release_coaching con authorized=true;
- la reaplicación del acelerador sólo puede mencionarse como punto espacial si
  throttle_onset_coaching tiene authorized=true;
- la liberación del acelerador sólo puede mencionarse como punto espacial si
  throttle_release_coaching tiene authorized=true;
- no interpretes la liberación como trail braking, técnica, balance ni causa:
  es únicamente un punto espacial medido por Python;
- no calcules, redondees ni modifiques esas magnitudes: usá EXACTAMENTE
  magnitude_m y direction entregados por Python;
- las únicas cifras permitidas en texto libre son los metros autorizados de
  braking_point_coaching, brake_release_coaching, throttle_onset_coaching y
  throttle_release_coaching dentro de la prioridad de ESA misma zona;
- en opportunities, repeated_observations, hypotheses, limitations y
  conclusion no escribas ninguna cifra;
- no escribas números de vuelta, tiempos, porcentajes ni velocidades;
- podés usar las etiquetas alfabéticas "zona prioritaria A", "B", "C";
- next_session_priorities y repeated_observations son propiedad exclusiva de
  Python; repeated_observations debe devolverse sólo como [] placeholder;
- observed_differences son hechos; sólo aquellos que Python materializó también en coaching_targets/driver_cues pueden convertirse en acción; observation_only_differences nunca son órdenes;
- sólo driver_cues, coaching_targets y puntos espaciales autorizados pueden convertirse en acciones;
- steering_magnitude puede ser una oportunidad o conclusión por sí solo SÓLO
  cuando Python lo incluyó explícitamente en driver_cues de esa zona;
- no conviertas una mera observed_difference de steering en orden adicional;
- si la zona también tiene freno/acelerador, steering puede quedar como ajuste
  secundario sin desplazar automáticamente el cue físico principal;
- si steering_magnitude es mixed/ambiguo en esa zona, no fuerces aumentar o
  reducir: usá una formulación neutral de replicar/acompañar la referencia;
- respetá literalmente la DIRECCIÓN del coaching_target de Python;
- convertí "reducir" en una instrucción directa al piloto: "reducí";
- convertí "aumentar" en una instrucción directa al piloto: "aumentá";
- convertí "replicar" en una instrucción directa: "replicá";
- no reemplaces un target concreto por "revisar", "comparar", "analizar",
  "explorar", "evaluar", "monitorear", "investigar", "estudiar",
  "trabajar" o "mejorar";
- evitá la frase aislada "ajustar hacia la referencia": nombrá el input y la
  dirección concreta que Python ya decidió;
- si Python entrega un target de secuencia o modulación, preservalo como tal y
  no lo simplifiques artificialmente a "más" o "menos";
- reference_action_profiles describe la forma física observada de acelerador o
  freno; podés usar sus categorías cualitativas, pero sus metros y porcentajes
  son descriptivos y NO autorizan nuevos objetivos numéricos;
- temporal_observations describe únicamente relaciones medidas entre inputs;
  NO las conviertas en órdenes, objetivos ni técnica de conducción;
- sólo podés convertir una relación temporal en coaching si Python entrega un
  temporal_target explícito y no nulo para esa misma zona;
- no introduzcas trayectoria, línea, tracción, agarre/grip, balance,
  transferencia de carga ni dinámica del vehículo si Python no los suministra
  explícitamente; esta prohibición también aplica a hypotheses y limitations;
- una diferencia observada puede ser una oportunidad de coaching aunque no
  sepamos si fue la causa de la pérdida;
- si existe contexto de velocidad, podés usarlo sólo como motivo para priorizar
  o como criterio cualitativo de comprobación; nunca como acción del piloto;
- si no hay base para una hipótesis adicional, devolvé hypotheses vacío;
- limitations contiene únicamente cosas que NO pueden determinarse con la
  evidencia disponible; no uses ese campo para observaciones medidas;
- velocidad inferior/superior, propagación del delta, diferencias de input y
  patrones repetidos son HECHOS/CONTEXTO, no limitaciones;
- si no existe una limitación útil que agregar, devolvé limitations vacío;
- las limitaciones deben ser breves y no dominar el informe.

Una buena prioridad debe poder leerse como una instrucción de debrief en una
sola frase: zona + input + cambio que debe probar el piloto.

ESTILO DEL INFORME:
- escribí siempre en español;
- soná como un ingeniero de pista profesional: técnico, sobrio, claro y
  orientado a la próxima tanda;
- no hagas roleplay ni uses frases teatrales;
- no redactes campos como inventarios de datos: conectá observación y acción;
- opportunities debe sintetizar focos, no repetir literalmente targets;
- conclusion debe tener una o dos frases fluidas: primero la lectura principal
  de la sesión y después cómo encarar la próxima tanda;
- si conclusion nombra una zona y un input con dirección explícita, esa
  dirección debe coincidir con el coaching_target de esa misma zona;
- evitá cadenas de cláusulas separadas por comas del tipo
  "aumentá X, reducí Y, replicá Z" cuando puedan expresarse como una secuencia
  más natural sin perder precisión;
- variá la sintaxis de forma moderada para evitar que todas las zonas suenen
  idénticas;
- NO copies literalmente expresiones internas como "hacia la referencia",
  "según las direcciones definidas", "según los objetivos definidos" o
  "en los tramos correspondientes" cuando puedan expresarse de manera natural;
- conservá la dirección objetiva, pero redactala como una instrucción de pista:
  por ejemplo, si Python dice "aumentar el acelerador hacia la referencia",
  podés escribir "recuperá más acelerador en esa zona";
- no hagas referencias meta al plan, a la ficha, a los objetivos definidos ni
  al sistema; hablale al piloto sobre la conducción;
- la conclusión debe nombrar la maniobra principal de forma concreta y nunca
  terminar con expresiones como "según las direcciones definidas";
- si una misma zona combina una diferencia de NIVEL de acelerador con un
  objetivo de PUNTO de reaplicación, no los presentes como dos órdenes
  contradictorias: expresá la secuencia. Ejemplo permitido: "empezá a
  reaplicar aproximadamente X m antes, pero mantené una aplicación menor
  durante el tramo" cuando ésos sean exactamente los dos hechos autorizados;
- "más acelerador/menos acelerador" describe nivel de aplicación; "reaplicar
  antes/después" describe posición del onset. No confundas ambos conceptos;
- no afirmes que una acción "mejorará la velocidad", "ganará tiempo" o
  "corregirá la salida" salvo que Python lo autorice explícitamente. Preferí
  "para acercar el input a la referencia" o simplemente indicá qué probar;
- no hables de trayectoria, línea, ápice, subviraje, sobreviraje o balance del
  vehículo salvo que esos hechos estén explícitamente presentes en el payload;
- no uses lenguaje motivacional, exagerado ni de personaje.

Respondé únicamente JSON válido.
No Markdown.
No texto fuera del JSON.
"""




# ============================================================
# ACTIONABILITY GATE v3.10.8
# ============================================================

SESSION_ACTIONABILITY_POLICY_VERSION = "1.7"


def _region_has_actionable_coaching(region):
    if not isinstance(region, dict):
        return False

    if any(
        isinstance(item, dict) and str(item.get("target") or "").strip()
        for item in (region.get("repeated_differences", []) or [])
    ):
        return True

    point_specs = (
        ("braking_point_patterns", _braking_point_target_text),
        ("brake_release_patterns", _brake_release_target_text),
        ("throttle_onset_patterns", _throttle_onset_target_text),
        ("throttle_release_patterns", _throttle_release_target_text),
    )
    for field, builder in point_specs:
        for pattern in (region.get(field, []) or []):
            if isinstance(pattern, dict) and builder(pattern):
                return True

    return False


def _plan_item_has_actionable_coaching(item):
    if not isinstance(item, dict):
        return False
    if any(str(value or "").strip() for value in (item.get("targets", []) or [])):
        return True
    # v3.10.8.5.4: un hallazgo PRIORITARIO puede llegar al plan sólo por
    # steering si el LLM validado lo eligió explícitamente como coaching.
    # Queda en el tier de menor especificidad y nunca desplaza un punto físico
    # repetido/individual ni un reference_action_profile concreto.
    if item.get("steering_coaching_requested"):
        direction = item.get("steering_direction")
        recommendation = str(item.get("validated_recommendation") or "").strip()
        if recommendation and _steering_direct_action_present(recommendation):
            if direction in {
                "higher_in_comparison_lap",
                "lower_in_comparison_lap",
                "mixed",
                None,
            }:
                return True
    for field in (
        "braking_point_patterns",
        "brake_release_patterns",
        "throttle_onset_patterns",
        "throttle_release_patterns",
    ):
        for pattern in (item.get(field, []) or []):
            if not isinstance(pattern, dict):
                continue
            magnitude = safe_int(pattern.get("coaching_magnitude_m"))
            direction = pattern.get("coaching_direction")
            authorized = pattern.get("authorized_numeric_coaching")
            if magnitude is not None and direction in {"later", "earlier"} and authorized is not False:
                return True
    return False


def _single_fact_as_plan_pattern(fact, comparison=None):
    if not isinstance(fact, dict):
        return None
    if not fact.get("authorized_numeric_coaching"):
        return None
    magnitude = safe_int(fact.get("coaching_magnitude_m"))
    direction = fact.get("coaching_direction")
    if magnitude is None or direction not in {"later", "earlier"}:
        return None
    value = dict(fact)
    value["status"] = "SINGLE"
    value["comparison_count"] = 1

    # H5.4/P2 — preserve explicit single-comparison provenance so the same
    # deterministic precision helper used by repeated patterns can describe
    # reference/supporting laps and the observed magnitude without inference.
    comparison_text = str(comparison or "").strip()
    signed_delta = safe_float(value.get("comparison_minus_reference_m"))
    if comparison_text:
        value["comparisons"] = [comparison_text]
    if signed_delta is not None:
        value["deltas_m"] = [signed_delta]
        value["median_delta_m"] = signed_delta

    return value


def _driver_facing_throttle_shape_summary(summary):
    """Normaliza shape_summary para una instrucción breve al piloto."""
    value = str(summary or "").strip()
    if not value:
        return ""
    value = value.replace(
        "reaplicación sostenida sin volver a soltar dentro de la zona",
        "reaplicación sostenida",
    )
    return value


def _driver_facing_throttle_profile_text(summary):
    """Convierte únicamente formas conocidas en una secuencia driver-facing."""
    value = str(summary or "").strip()
    if not value:
        return ""

    fallback = (
        "replicá la secuencia de acelerador de la referencia: "
        + value
    )
    actions = {
        "aplicación": "replicá la aplicación de acelerador",
        "aplicación parcial": "usá una aplicación parcial de acelerador",
        "aplicación media": "usá una aplicación media de acelerador",
        "aplicación alta": "usá una aplicación alta de acelerador",
        "aplicación parcial breve": "hacé una aplicación parcial y breve de acelerador",
        "aplicación media breve": "hacé una aplicación media y breve de acelerador",
        "aplicación alta breve": "hacé una aplicación alta y breve de acelerador",
        "liberación breve": "hacé una liberación breve del acelerador",
        "acelerador liberado": "soltá el acelerador",
        "reaplicación sostenida": "reaplicá y sostené el acelerador",
        "reaplicación sostenida sin volver a soltar dentro de la zona": (
            "reaplicá y sostené el acelerador"
        ),
    }

    tokens = [part.strip() for part in value.split("→") if part.strip()]
    if not tokens or any(token not in actions for token in tokens):
        return fallback

    return "; después, ".join(actions[token] for token in tokens) + (
        " como en la referencia"
    )



def build_driver_cues_for_plan_item(item, max_cues=2):
    """
    Construye como máximo dos cues driver-facing.

    v3.10.8.5.4:
    1) onset/release conserva máxima prioridad como target físico;
    2) reference_action_profile conserva prioridad sobre diferencias de nivel;
    3) brake/throttle con dirección determinista unívoca pueden producir un cue
       cualitativo hacia la referencia, sin magnitud inventada;
    4) steering puede ser cue único o secundario sólo cuando el LLM validado lo
       eligió explícitamente para un hallazgo PRIORITARIO;
    5) temporal_relationships sigue siendo observación y nunca se convierte en
       target por esta función.
    """
    if not isinstance(item, dict):
        return []

    cues = []

    def first_pattern(field):
        values = item.get(field, []) or []
        return values[0] if values and isinstance(values[0], dict) else None

    def point_phrase(pattern, later_text, earlier_text):
        if not isinstance(pattern, dict):
            return None
        magnitude = safe_int(pattern.get("coaching_magnitude_m"))
        direction = pattern.get("coaching_direction")
        if magnitude is None:
            return None
        if direction == "later":
            return later_text.format(magnitude=magnitude)
        if direction == "earlier":
            return earlier_text.format(magnitude=magnitude)
        return None

    profiles_by_channel = {}
    for profile in (item.get("reference_action_profiles", []) or []):
        if not isinstance(profile, dict):
            continue
        channel = profile.get("channel")
        summary = str(profile.get("shape_summary") or "").strip()
        if channel in {"brake", "throttle"} and summary and channel not in profiles_by_channel:
            profiles_by_channel[channel] = profile

    brake_onset = point_phrase(
        first_pattern("braking_point_patterns"),
        "frená aproximadamente {magnitude} m más tarde",
        "frená aproximadamente {magnitude} m más temprano",
    )
    brake_release = point_phrase(
        first_pattern("brake_release_patterns"),
        "soltá el freno aproximadamente {magnitude} m más tarde",
        "soltá el freno aproximadamente {magnitude} m más temprano",
    )
    if brake_onset or brake_release:
        text = " y ".join(value for value in (brake_onset, brake_release) if value)
        brake_patterns = [
            pattern
            for field in ("braking_point_patterns", "brake_release_patterns")
            for pattern in (item.get(field, []) or [])
            if isinstance(pattern, dict)
        ]
        point_count = max(
            [safe_int(pattern.get("comparison_count")) or 1 for pattern in brake_patterns],
            default=1,
        )
        cue = {
            "channel": "brake",
            "kind": "spatial_points",
            "text": text,
            "source": "authorized_brake_onset_release",
            "point_comparison_count": point_count,
            "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
        }
        precision_evidence = [
            pattern.get("precision_evidence")
            for pattern in brake_patterns
            if isinstance(pattern.get("precision_evidence"), dict)
        ]
        if precision_evidence:
            cue["precision_evidence"] = precision_evidence
        cues.append(cue)

    throttle_onset = point_phrase(
        first_pattern("throttle_onset_patterns"),
        "reaplicá el acelerador aproximadamente {magnitude} m más tarde",
        "reaplicá el acelerador aproximadamente {magnitude} m más temprano",
    )
    throttle_release = point_phrase(
        first_pattern("throttle_release_patterns"),
        "soltá el acelerador aproximadamente {magnitude} m más tarde",
        "soltá el acelerador aproximadamente {magnitude} m más temprano",
    )
    if throttle_onset or throttle_release:
        profile = profiles_by_channel.get("throttle")
        profile_text = (
            _driver_facing_throttle_profile_text(
                profile.get("shape_summary")
            )
            if profile is not None
            else ""
        )

        if throttle_onset and throttle_release:
            text = f"{throttle_onset} y {throttle_release}"
        elif throttle_onset:
            text = throttle_onset
        else:
            text = throttle_release

        throttle_patterns = [
            pattern
            for field in ("throttle_onset_patterns", "throttle_release_patterns")
            for pattern in (item.get(field, []) or [])
            if isinstance(pattern, dict)
        ]
        point_count = max(
            [safe_int(pattern.get("comparison_count")) or 1 for pattern in throttle_patterns],
            default=1,
        )

        cue = {
            "channel": "throttle",
            "kind": "spatial_points",
            "text": text,
            "source": "authorized_throttle_onset_release",
            "point_comparison_count": point_count,
            "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
        }
        if profile is not None:
            cue["reference_action_profile"] = profile
        precision_evidence = [
            pattern.get("precision_evidence")
            for pattern in throttle_patterns
            if isinstance(pattern.get("precision_evidence"), dict)
        ]
        if precision_evidence:
            cue["precision_evidence"] = precision_evidence
        cues.append(cue)
        if profile is not None and profile_text:
            cues.append({
                "channel": "throttle",
                "kind": "reference_action_profile",
                "text": profile_text,
                "source": "reference_action_profile",
                "reference_action_profile": profile,
            })

    existing_channels = {cue.get("channel") for cue in cues}
    for channel in ("brake", "throttle"):
        if channel in existing_channels:
            continue
        profile = profiles_by_channel.get(channel)
        if profile is None:
            continue
        summary = str(profile.get("shape_summary") or "").strip()
        if not summary:
            continue
        prefix = "freno" if channel == "brake" else "acelerador"
        text = (
            _driver_facing_throttle_profile_text(summary)
            if channel == "throttle"
            else f"replicá la secuencia de {prefix} de la referencia: {summary}"
        )
        cues.append({
            "channel": channel,
            "kind": "reference_action_profile",
            "text": text,
            "source": "reference_action_profile",
            "reference_action_profile": profile,
        })
        existing_channels.add(channel)

    # v3.10.8.5.4 — si no existe un cue más específico para el canal, una
    # diferencia de nivel unívoca ya materializada en `targets` por Python
    # puede convertirse en instrucción cualitativa. Cuando brake y throttle
    # aparecen juntos, se combinan en UN cue para no expulsar automáticamente
    # un steering secundario del límite de dos cues.
    level_parts = []
    level_channels = []
    for target in (item.get("targets", []) or []):
        if not isinstance(target, str):
            continue
        direction_map = _explicit_command_direction_map(target)
        for channel in ("brake", "throttle"):
            if channel in existing_channels or channel in level_channels:
                continue
            if channel not in direction_map:
                continue
            direct = _direct_coaching_target_text(target)
            if not direct:
                continue
            level_parts.append(direct)
            level_channels.append(channel)

    if level_parts:
        cues.append({
            "channel": (
                "brake+throttle"
                if set(level_channels) == {"brake", "throttle"}
                else level_channels[0]
            ),
            "channels": list(level_channels),
            "kind": "qualitative_reference_level",
            "text": " y ".join(level_parts),
            "source": "deterministic_observed_level_to_reference",
            "point_comparison_count": 0,
            "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
        })

    sequence = item.get("coaching_sequence")
    if isinstance(sequence, dict) and sequence.get("status") == "COMBINED":
        spatial_indexes = [
            index
            for index, cue in enumerate(cues)
            if cue.get("kind") == "spatial_points"
            and cue.get("channel") in {"brake", "throttle"}
        ]
        if len(spatial_indexes) >= 2:
            first_index = spatial_indexes[0]
            evidence = [
                event.get("precision_evidence")
                for event in (sequence.get("events") or [])
                if isinstance(event, dict)
                and isinstance(event.get("precision_evidence"), dict)
            ]
            combined = {
                "channel": "brake+throttle",
                "channels": ["brake", "throttle"],
                "kind": "combined_spatial_sequence",
                "text": str(sequence.get("driver_summary") or "").strip(),
                "source": "deterministic_coaching_sequence",
                "coaching_sequence": sequence,
                "point_comparison_count": max(
                    [
                        safe_int(cues[i].get("point_comparison_count")) or 0
                        for i in spatial_indexes
                    ],
                    default=0,
                ),
                "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
            }
            if evidence:
                combined["precision_evidence"] = evidence
            cues = [
                cue
                for index, cue in enumerate(cues)
                if index not in spatial_indexes
            ]
            cues.insert(first_index, combined)

    if item.get("steering_coaching_requested"):
        recommendation = str(item.get("validated_recommendation") or "").strip()
        if recommendation and _steering_direct_action_present(recommendation):
            direction = item.get("steering_direction")
            if direction == "higher_in_comparison_lap":
                steering_text = "reducí la magnitud del volante hacia la referencia"
            elif direction == "lower_in_comparison_lap":
                steering_text = "aumentá la magnitud del volante hacia la referencia"
            else:
                steering_text = "replicá la secuencia de dirección de la referencia"
            cues.append({
                "channel": "steering_magnitude",
                "kind": "validated_llm_steering",
                "text": steering_text,
                "source": "validated_llm_recommendation+python_direction",
                "point_comparison_count": 0,
                "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
            })

    return cues[:max_cues]

def _render_precision_evidence_lines(cue):
    if not isinstance(cue, dict):
        return []
    evidence_rows = [
        row
        for row in (cue.get("precision_evidence", []) or [])
        if isinstance(row, dict)
    ]
    if not evidence_rows:
        return []

    # El primer punto del cue es el ancla principal. Si el cue contiene onset
    # y release, los detalles completos permanecen en el JSON.
    evidence = evidence_rows[0]
    reference_lap = safe_int(evidence.get("reference_lap"))
    supporting_laps = [
        safe_int(value)
        for value in (evidence.get("supporting_laps", []) or [])
        if safe_int(value) is not None
    ]
    anchor = evidence.get("corner_relative_reference")
    anchor_label = (
        str(anchor.get("driver_label") or "").strip()
        if isinstance(anchor, dict)
        else ""
    )

    lines = []
    reference_parts = []
    if reference_lap is not None:
        reference_parts.append(f"vuelta {reference_lap}")
    if anchor_label:
        reference_parts.append(f"punto de referencia {anchor_label}")
    if reference_parts:
        lines.append("**Referencia del cue:** " + "; ".join(reference_parts) + ".")

    if supporting_laps:
        if len(supporting_laps) == 1:
            laps_text = f"la vuelta {supporting_laps[0]}"
        else:
            laps_text = "las vueltas " + ", ".join(str(v) for v in supporting_laps[:-1]) + f" y {supporting_laps[-1]}"
        evidence_parts = [f"el mismo desvío apareció en {laps_text}"]
        low = safe_float(evidence.get("observed_delta_min_m"))
        high = safe_float(evidence.get("observed_delta_max_m"))
        representative = safe_int(evidence.get("representative_delta_m"))
        if low is not None and high is not None:
            low_i = int(round(low))
            high_i = int(round(high))
            if low_i == high_i:
                evidence_parts.append(f"diferencia observada ~{low_i} m")
            else:
                evidence_parts.append(f"rango observado {low_i}–{high_i} m")
        if representative is not None:
            evidence_parts.append(f"valor representativo {representative} m")
        lines.append("**Evidencia entre vueltas:** " + "; ".join(evidence_parts) + ".")

    return lines


def _deterministic_session_focus(plan):
    parts = []
    for item in (plan or [])[:3]:
        cues = item.get("driver_cues") or build_driver_cues_for_plan_item(item)
        if not cues:
            continue
        label = str(item.get("plan_label") or "?")
        location = track_location_label(item)
        where = f"zona {label}"
        if location:
            where += f" ({location})"
        parts.append(f"{where}: {cues[0]['text']}")
    if not parts:
        return "No apareció un cue de conducción suficientemente respaldado para la próxima tanda."
    return "Priorizá " + "; ".join(parts) + "."


# ============================================================
# PRIORIDADES GLOBALES DETERMINISTAS v3.10.8
# ============================================================

def _direct_coaching_target_text(
    value,
):
    """
    Convierte los coaching targets propiedad de Python de infinitivo a una
    instrucción directa. No cambia input, dirección ni contenido factual.
    """
    value = str(
        value or ""
    ).strip()

    if not value:
        return ""

    replacements = (
        (
            "reducir ",
            "reducí ",
        ),
        (
            "aumentar ",
            "aumentá ",
        ),
        (
            "replicar ",
            "replicá ",
        ),
    )

    lowered = value.lower()

    for source, target in replacements:
        if lowered.startswith(
            source
        ):
            value = (
                target
                + value[
                    len(source):
                ]
            )
            break

    value = re.sub(
        r"\s+hacia\s+(?:el\s+punto\s+de\s+)?la\s+referencia\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()

    return value


def _point_priority_text(
    pattern,
    *,
    action_later,
    action_earlier,
):
    if not isinstance(
        pattern,
        dict,
    ):
        return None

    magnitude = safe_int(
        pattern.get(
            "coaching_magnitude_m"
        )
    )
    direction = pattern.get(
        "coaching_direction"
    )

    if magnitude is None:
        return None

    if direction == "later":
        return action_later.format(
            magnitude=magnitude
        )

    if direction == "earlier":
        return action_earlier.format(
            magnitude=magnitude
        )

    return None


def deterministic_priority_for_plan_item(
    item,
):
    """v3.10.8: el driver ve como máximo dos cues accionables por zona."""
    if not isinstance(item, dict):
        return None
    label = str(item.get("plan_label") or "?").strip()
    cues = item.get("driver_cues") or build_driver_cues_for_plan_item(item)
    texts = [str(cue.get("text") or "").strip() for cue in cues[:2] if isinstance(cue, dict)]
    texts = [text for text in texts if text]
    if not texts:
        return None
    return f"Zona prioritaria {label}: " + "; ".join(texts)

def build_deterministic_next_session_priorities(
    session_coaching_facts,
):
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
    ) or []

    return [
        value
        for value in (
            deterministic_priority_for_plan_item(
                item
            )
            for item in plan[:3]
        )
        if value
    ]


def build_deterministic_repeated_observations(
    session_coaching_facts,
):
    """
    v3.10.8

    repeated_observations is factual session accounting, not narrative model
    judgment. Build one item per selected repeated region from Python-owned
    observed_differences so backends cannot omit or contaminate a zone.
    """
    plan = (
        session_coaching_facts.get("next_stint_plan", [])
        if isinstance(session_coaching_facts, dict)
        else []
    ) or []

    result = []
    for item in plan[:3]:
        if not isinstance(item, dict) or item.get("kind") != "repeated_region":
            continue

        label = str(item.get("plan_label") or "").strip().upper()
        observed = [
            str(value).strip()
            for value in (item.get("observed_differences", []) or [])
            if str(value).strip()
        ]
        if not label or not observed:
            continue

        if len(observed) == 1:
            joined = observed[0]
        elif len(observed) == 2:
            joined = f"{observed[0]} y {observed[1]}"
        else:
            joined = ", ".join(observed[:-1]) + f" y {observed[-1]}"

        result.append(
            f"En la zona {label} se repitió {joined} en la misma región."
        )

    return result


GLOBAL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "opportunities": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "minItems": 0,
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
        "conclusion": {
            "type": "string",
        },
    },
    "required": [
        "opportunities",
        "repeated_observations",
        "hypotheses",
        "limitations",
        "conclusion",
    ],
    "additionalProperties": False,
}


def global_correction_instructions(errors):
    """
    Traduce errores del validator global a instrucciones concretas y seguras.

    En v3.10.8 las prioridades numéricas/direccionales son propiedad de Python. Este bloque sólo corrige campos narrativos del LLM.
    """
    instructions = []

    for error in errors or []:
        value = str(error)

        if (
            "contiene cifras" in value
            or "contenido numérico" in value
        ):
            instructions.append(
                "Eliminá todo contenido numérico del campo rechazado. "
                "No uses dígitos, metros, segundos, porcentajes ni magnitudes "
                "escritas con palabras. Conservá sólo la dirección cualitativa "
                "y la acción autorizada por Python."
            )
            continue

        m = re.search(
            r"next_session_priorities\[(\d+)\]: "
            r"(.+?) debe conservar direction=later como 'más tarde'\.",
            value,
            re.IGNORECASE,
        )
        if m:
            index = int(m.group(1))
            label = m.group(2)
            instructions.append(
                f"En next_session_priorities[{index}], {label} debe decir "
                f"explícitamente 'más tarde'. No uses 'antes' ni "
                f"'más temprano' para ese target."
            )
            continue

        m = re.search(
            r"next_session_priorities\[(\d+)\]: "
            r"(.+?) debe conservar direction=earlier\.",
            value,
            re.IGNORECASE,
        )
        if m:
            index = int(m.group(1))
            label = m.group(2)
            instructions.append(
                f"En next_session_priorities[{index}], {label} debe decir "
                f"'más temprano' o 'antes'. No uses 'más tarde' para ese target."
            )
            continue

        m = re.search(
            r"next_session_priorities\[(\d+)\]: debe usar únicamente las "
            r"magnitudes autorizadas por Python: (.+), cada una exactamente "
            r"una vez\.",
            value,
            re.IGNORECASE,
        )
        if m:
            index = int(m.group(1))
            expected = m.group(2)
            instructions.append(
                f"En next_session_priorities[{index}], usá exactamente estas "
                f"magnitudes y una sola vez cada una: {expected}. "
                f"No agregues otras cifras."
            )
            continue

        m = re.search(
            r"next_session_priorities\[(\d+)\]: debe expresar (.+?) "
            r"con la magnitud autorizada (\d+) m\.",
            value,
            re.IGNORECASE,
        )
        if m:
            index = int(m.group(1))
            label = m.group(2)
            magnitude = m.group(3)
            instructions.append(
                f"En next_session_priorities[{index}], incluí {label} con "
                f"exactamente {magnitude} m."
            )
            continue

        if "contiene cifras sin objetivo numérico autorizado" in value:
            m = re.search(r"next_session_priorities\[(\d+)\]", value)
            if m:
                instructions.append(
                    f"En next_session_priorities[{int(m.group(1))}], "
                    "eliminá todas las cifras: esa zona no tiene un objetivo "
                    "numérico autorizado."
                )
                continue

        if "contiene porcentaje no autorizado" in value:
            m = re.search(r"next_session_priorities\[(\d+)\]", value)
            if m:
                instructions.append(
                    f"En next_session_priorities[{int(m.group(1))}], "
                    "eliminá el porcentaje no autorizado."
                )
                continue

    if instructions:
        return instructions

    # Fallback compacto para errores que no requieren exponer texto rechazado.
    return [
        "Regenerá el objeto completo respetando estrictamente el contrato "
        f"del validator. Categorías: {', '.join(correction_kinds(errors))}."
    ]


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
RESPUESTA ANTERIOR RECHAZADA.

CORRECCIONES OBLIGATORIAS INDICADAS POR EL VALIDATOR DE PYTHON:
{compact_json(global_correction_instructions(correction_errors))}

Regenerá el objeto JSON COMPLETO desde cero.
Conservá todo lo que ya cumplía el contrato y corregí exactamente esos puntos.
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
- resumí únicamente los driver_cues accionables del next_stint_plan;
- no conviertas observed_differences en acciones adicionales salvo que Python ya las haya materializado en coaching_targets/driver_cues de esa misma zona;
- steering_magnitude puede aparecer como acción única o secundaria sólo si
  Python lo incluyó explícitamente en driver_cues de esa misma zona;
- no generalices a todo el circuito;
- si mencionás una zona, usá sólo las etiquetas provistas por Python;
- nombrá el input y conservá la dirección del coaching_target;
- preferí "reducí", "aumentá" o "replicá" según indique Python;
- temporal_observations es contexto descriptivo y no una instrucción;
- no ordenes, separes ni elimines solapamiento entre freno/acelerador salvo que
  temporal_target lo autorice explícitamente para esa zona;
- evitá "revisar", "comparar" o "ajustar" sin una dirección concreta;
- no inventes fase de curva ni nombre de curva.

repeated_observations:
- devolvé una lista vacía [] como placeholder;
- Python construye este campo determinísticamente desde las regiones repetidas;
- no intentes resumirlo ni completarlo.

hypotheses:
- opcional;
- preferí lista vacía antes que una hipótesis genérica.

limitations:
- máximo dos;
- incluí únicamente información que NO puede determinarse con la evidencia;
- NO pongas aquí observaciones medidas como velocidad inferior/superior,
  propagación del delta, diferencias de input o patrones repetidos;
- no repitas varias veces que no puede probarse causalidad;
- si no hay una limitación necesaria, devolvé la lista vacía;
- no pidas análisis adicional de trayectoria, tracción, agarre, balance ni
  dinámica del vehículo si esos dominios no están autorizados en la ficha.

next_session_priorities:
- NO devuelvas este campo; Python lo renderiza de forma determinista desde next_stint_plan.

conclusion:
- una conclusión corta y operativa;
- nunca uses la vuelta comparada como modelo/objetivo; toda acción debe orientarse a la referencia;
- empezá por la acción principal que el piloto debe probar en la próxima tanda;
- debe resumir el plan de zonas prioritarias sin volver a narrar toda la evidencia;
- no uses una conclusión genérica como "ajustar los inputs";
- no debe pedir "más análisis".

No escribas NINGUNA cifra ni magnitud numérica en tu respuesta.
No escribas metros, segundos, porcentajes, cantidades ni identificadores numéricos.
Tampoco escribas una magnitud con palabras.
Las direcciones cualitativas "más temprano" y "más tarde" sí están permitidas.
Python insertará después, de forma determinista, todas las cifras autorizadas
en next_session_priorities y en el informe visible.

{correction_block}

Respondé únicamente JSON válido con las claves exigidas por el schema.
"""

# ============================================================
# VALIDAR RESPUESTA GLOBAL
# ============================================================


def _validate_global_priority_text_list(value, plan, errors):
    if not isinstance(value, list):
        errors.append("next_session_priorities: debe ser lista.")
        return

    for index, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(
                f"next_session_priorities[{index}]: debe ser texto."
            )
            continue

        if "%" in item:
            errors.append(
                f"next_session_priorities[{index}]: contiene porcentaje no autorizado."
            )

        plan_item = (
            plan[index]
            if index < len(plan) and isinstance(plan[index], dict)
            else {}
        )

        authorized_targets = []

        onset_patterns = plan_item.get("braking_point_patterns", []) or []
        onset_pattern = (
            onset_patterns[0]
            if onset_patterns and isinstance(onset_patterns[0], dict)
            else None
        )
        if onset_pattern and onset_pattern.get("status") == "REPEATED":
            magnitude = safe_int(
                onset_pattern.get("coaching_magnitude_m")
            )
            direction = onset_pattern.get("coaching_direction")
            if magnitude is not None and direction in {"later", "earlier"}:
                authorized_targets.append({
                    "kind": "brake_onset",
                    "magnitude": magnitude,
                    "direction": direction,
                })

        release_patterns = plan_item.get("brake_release_patterns", []) or []
        release_pattern = (
            release_patterns[0]
            if release_patterns and isinstance(release_patterns[0], dict)
            else None
        )
        if release_pattern and release_pattern.get("status") == "REPEATED":
            magnitude = safe_int(
                release_pattern.get("coaching_magnitude_m")
            )
            direction = release_pattern.get("coaching_direction")
            if magnitude is not None and direction in {"later", "earlier"}:
                authorized_targets.append({
                    "kind": "brake_release",
                    "magnitude": magnitude,
                    "direction": direction,
                })

        throttle_onset_patterns = plan_item.get("throttle_onset_patterns", []) or []
        throttle_onset_pattern = (
            throttle_onset_patterns[0]
            if throttle_onset_patterns and isinstance(throttle_onset_patterns[0], dict)
            else None
        )
        if throttle_onset_pattern and throttle_onset_pattern.get("status") == "REPEATED":
            magnitude = safe_int(throttle_onset_pattern.get("coaching_magnitude_m"))
            direction = throttle_onset_pattern.get("coaching_direction")
            if magnitude is not None and direction in {"later", "earlier"}:
                authorized_targets.append({
                    "kind": "throttle_onset",
                    "magnitude": magnitude,
                    "direction": direction,
                })

        throttle_release_patterns = plan_item.get("throttle_release_patterns", []) or []
        throttle_release_pattern = (
            throttle_release_patterns[0]
            if throttle_release_patterns and isinstance(throttle_release_patterns[0], dict)
            else None
        )
        if throttle_release_pattern and throttle_release_pattern.get("status") == "REPEATED":
            magnitude = safe_int(throttle_release_pattern.get("coaching_magnitude_m"))
            direction = throttle_release_pattern.get("coaching_direction")
            if magnitude is not None and direction in {"later", "earlier"}:
                authorized_targets.append({
                    "kind": "throttle_release",
                    "magnitude": magnitude,
                    "direction": direction,
                })

        numeric_tokens = re.findall(
            r"\d+(?:[\.,]\d+)?",
            item,
        )
        normalized = [
            token.replace(",", ".")
            for token in numeric_tokens
        ]

        if not authorized_targets:
            if numeric_tokens:
                errors.append(
                    f"next_session_priorities[{index}]: contiene cifras sin objetivo numérico autorizado por Python."
                )
            continue

        expected_tokens = [
            str(target["magnitude"])
            for target in authorized_targets
        ]

        if sorted(normalized) != sorted(expected_tokens):
            expected_text = ", ".join(
                f"{target['magnitude']} m ({target['kind']})"
                for target in authorized_targets
            )
            errors.append(
                f"next_session_priorities[{index}]: debe usar únicamente las magnitudes autorizadas por Python: {expected_text}, cada una exactamente una vez."
            )
            continue

        lowered = item.lower()

        for target in authorized_targets:
            expected = str(target["magnitude"])
            kind = target["kind"]
            direction = target["direction"]

            if kind == "brake_onset":
                keyword = r"fren\w*"
                label = "punto de frenada"
            elif kind == "brake_release":
                keyword = r"(?:solt\w*|liber\w*)[^.!?]{0,35}fren\w*"
                label = "liberación de freno"
            elif kind == "throttle_onset":
                keyword = r"(?:reaplic\w*|aceler\w*[^.!?]{0,20}(?:antes|despu|tarde|temprano))"
                label = "reaplicación de acelerador"
            elif kind == "throttle_release":
                keyword = r"(?:solt\w*|liber\w*)[^.!?]{0,35}acelerador"
                label = "liberación de acelerador"
            else:
                errors.append(
                    f"next_session_priorities[{index}]: tipo de coaching numérico desconocido: {kind}."
                )
                continue

            segment_match = re.search(
                rf"{keyword}[^.!?]{{0,120}}\b{re.escape(expected)}\s*m\b[^.!?]{{0,80}}",
                lowered,
                re.IGNORECASE,
            )

            if not segment_match:
                errors.append(
                    f"next_session_priorities[{index}]: debe expresar {label} con la magnitud autorizada {expected} m."
                )
                continue

            segment = segment_match.group(0)

            if direction == "later" and "más tarde" not in segment:
                errors.append(
                    f"next_session_priorities[{index}]: {label} debe conservar direction=later como 'más tarde'."
                )
            if (
                direction == "earlier"
                and "más temprano" not in segment
                and "antes" not in segment
            ):
                errors.append(
                    f"next_session_priorities[{index}]: {label} debe conservar direction=earlier."
                )



# ============================================================
# CONSISTENCIA DIRECCIONAL GLOBAL v3.10.8
# ============================================================

def _explicit_command_direction_map(
    value,
):
    result = {}

    for clause in _explicit_directional_clauses(
        value
    ):
        direction = clause.get(
            "direction"
        )

        for channel in clause.get(
            "channels",
            set(),
        ):
            result.setdefault(
                channel,
                set(),
            ).add(
                direction
            )

    return {
        channel: next(iter(directions))
        for channel, directions in result.items()
        if len(directions) == 1
    }


def _plan_item_expected_direction_map(
    plan_item,
):
    """
    Los targets de next_stint_plan son propiedad de Python.
    Sólo extraemos direcciones cuando el target es explícito aumentar/reducir.
    """
    result = {}

    if not isinstance(plan_item, dict):
        return result

    for target in (
        plan_item.get(
            "targets",
            [],
        )
        or []
    ):
        if not isinstance(target, str):
            continue

        target_map = _explicit_command_direction_map(
            target
        )

        for channel, direction in target_map.items():
            result.setdefault(
                channel,
                set(),
            ).add(
                direction
            )

    return {
        channel: next(iter(directions))
        for channel, directions in result.items()
        if len(directions) == 1
    }


def _single_zone_segments(
    value,
):
    """
    Divide una conclusión en segmentos operativos y conserva sólo aquellos
    que nombran exactamente una zona A/B/C. Así evitamos atribuir una orden
    a otra zona cuando la frase es ambigua.
    """
    if not isinstance(value, str):
        return {}

    normalized = normalize_grounding_text(
        value
    )

    parts = re.split(
        r"(?<=[.;])|"
        r"\b(?:luego|despues|finalmente|por ultimo|a continuacion)\b",
        normalized,
    )

    result = {}

    for part in parts:
        labels = re.findall(
            r"\bzona(?:\s+prioritaria)?\s+([a-z])\b",
            part,
        )

        labels = {
            label.upper()
            for label in labels
        }

        if len(labels) != 1:
            continue

        label = next(
            iter(labels)
        )
        result.setdefault(
            label,
            [],
        ).append(
            part
        )

    return result



def _zone_labels_in_text(value):
    if not isinstance(value, str):
        return set()

    normalized = normalize_grounding_text(value)

    return {
        label.upper()
        for label in re.findall(
            r"\bzona(?:\s+prioritaria)?\s+([a-z])\b",
            normalized,
        )
    }


def _global_factual_direction_by_channel(value):
    """
    Parser más estricto sólo para repeated_observations globales.

    A diferencia del validator por episodio, acá podemos segmentar también
    por comas porque cada item ya está anclado a una única zona A/B/C.
    Esto permite detectar contaminaciones como:
      "mayor dirección, menos freno y más acelerador"
    sin relajar el parser conservador usado en interpretaciones de episodio.
    """
    if not isinstance(value, str):
        return {}

    normalized = normalize_grounding_text(value)
    parts = re.split(
        r"(?:[.;:\n]+|,\s*|\s+\by\b\s+)",
        normalized,
    )

    result = {}

    for part in parts:
        part = str(part or "").strip(" ,")
        if not part:
            continue

        channels = _channels_explicitly_present(part)
        directions = _directions_explicitly_present(part)

        if len(channels) != 1 or len(directions) != 1:
            continue

        channel = next(iter(channels))
        direction = next(iter(directions))
        result.setdefault(channel, set()).add(direction)

    return {
        channel: next(iter(directions))
        for channel, directions in result.items()
        if len(directions) == 1
    }


def _plan_item_observed_direction_map(plan_item):
    result = {}

    if not isinstance(plan_item, dict):
        return result

    for value in plan_item.get("observed_differences", []) or []:
        if not isinstance(value, str):
            continue

        direction_map = _global_factual_direction_by_channel(value)

        for channel, direction in direction_map.items():
            result.setdefault(channel, set()).add(direction)

    return {
        channel: next(iter(directions))
        for channel, directions in result.items()
        if len(directions) == 1
    }


def _plan_item_observed_channels(plan_item):
    channels = set()

    if not isinstance(plan_item, dict):
        return channels

    for value in plan_item.get("observed_differences", []) or []:
        if not isinstance(value, str):
            continue
        channels.update(_channels_mentioned_in_text(value))

    return channels



def _plan_item_primary_driver_cue_channels(plan_item):
    channels = set()

    if not isinstance(plan_item, dict):
        return channels

    for cue in (plan_item.get("driver_cues", []) or []):
        if not isinstance(cue, dict):
            continue

        explicit_channels = cue.get("channels")
        if isinstance(explicit_channels, list):
            for channel in explicit_channels:
                if channel in {"brake", "throttle"}:
                    channels.add(channel)

        channel = cue.get("channel")
        if channel in {"brake", "throttle"}:
            channels.add(channel)

    return channels

def _plan_item_secondary_steering_expected_direction(plan_item):
    observed = _plan_item_observed_direction_map(plan_item).get(
        "steering_magnitude"
    )
    if observed == "lower_in_comparison_lap":
        return "increase"
    if observed == "higher_in_comparison_lap":
        return "decrease"
    return None


def _secondary_steering_allowed_for_plan_text(value, plan_item):
    """
    Contrato global v3.10.8.5.4.

    Steering directo puede ser único o secundario, pero sólo si Python ya lo
    materializó explícitamente como driver_cue de ESA zona. Una mera
    observed_difference no alcanza para convertirlo en orden.
    """
    if not _steering_direct_action_present(value):
        return True

    if not isinstance(plan_item, dict):
        return False

    observed_channels = _plan_item_observed_channels(plan_item)
    if "steering_magnitude" not in observed_channels:
        return False

    cue_channels = {
        cue.get("channel")
        for cue in (plan_item.get("driver_cues", []) or [])
        if isinstance(cue, dict)
    }
    if "steering_magnitude" not in cue_channels:
        return False

    explicit = _explicit_command_direction_map(value).get(
        "steering_magnitude"
    )
    if explicit is None:
        return True

    expected = _plan_item_secondary_steering_expected_direction(plan_item)
    if expected is None:
        return False

    return explicit == expected


def validate_global_secondary_steering_text(
    value,
    field_name,
    plan,
    errors,
):
    if not _steering_direct_action_present(value):
        return

    labels = _zone_labels_in_text(value)
    if len(labels) != 1:
        errors.append(
            f"{field_name}: steering_magnitude directo debe quedar anclado "
            "a una única zona A/B/C."
        )
        return

    label = next(iter(labels))
    plan_by_label = {
        str(item.get("plan_label") or "").strip().upper(): item
        for item in (plan or [])[:3]
        if isinstance(item, dict) and item.get("plan_label")
    }
    plan_item = plan_by_label.get(label)

    if not _secondary_steering_allowed_for_plan_text(
        value,
        plan_item,
    ):
        errors.append(
            f"{field_name}: steering_magnitude sólo puede convertirse en "
            f"acción de zona {label} si Python lo incluyó explícitamente en "
            "driver_cues y la dirección respeta la evidencia observada."
        )


def validate_global_zone_list_consistency(
    response,
    plan,
    errors,
):
    """
    Invariante global por zona v3.10.8.

    - opportunities[A/B/C] no puede invertir targets deterministas de su zona.
    - repeated_observations[A/B/C] no puede invertir hechos observados ni
      importar canales de otra zona.

    Los errores quedan indexados al item de lista para que, tras agotar retries,
    el fallback global pueda podar sólo ese item opcional y revalidar todo.
    """
    if not isinstance(response, dict):
        return

    plan_by_label = {}

    for item in (plan or [])[:3]:
        if not isinstance(item, dict):
            continue

        label = str(item.get("plan_label", "")).strip().upper()
        if label:
            plan_by_label[label] = item

    human_channel = {
        "brake": "freno",
        "throttle": "acelerador",
        "steering_magnitude": "magnitud de dirección/volante",
    }

    opportunities = response.get("opportunities")
    if isinstance(opportunities, list):
        for index, item in enumerate(opportunities):
            if not isinstance(item, str):
                continue

            labels = _zone_labels_in_text(item)
            if len(labels) != 1:
                continue

            label = next(iter(labels))
            plan_item = plan_by_label.get(label)
            if not isinstance(plan_item, dict):
                errors.append(
                    f"opportunities[{index}]: referencia zona {label} que no existe en next_stint_plan."
                )
                continue

            expected = _plan_item_expected_direction_map(plan_item)
            actual = _explicit_command_direction_map(item)

            unauthorized_channels = set(actual) - set(expected)
            for channel in sorted(unauthorized_channels):
                if (
                    channel == "steering_magnitude"
                    and _secondary_steering_allowed_for_plan_text(
                        item,
                        plan_item,
                    )
                ):
                    continue
                errors.append(
                    f"opportunities[{index}]: convierte una observación en orden no autorizada "
                    f"para {human_channel.get(channel, channel)} en zona {label}."
                )

            for channel in set(expected) & set(actual):
                if expected[channel] == actual[channel]:
                    continue

                expected_human = (
                    "aumentar"
                    if expected[channel] == "increase"
                    else "reducir"
                )

                errors.append(
                    f"opportunities[{index}]: contradice el coaching determinista "
                    f"de zona {label} para {human_channel.get(channel, channel)}; "
                    f"Python requiere {expected_human}."
                )

    repeated = response.get("repeated_observations")
    if isinstance(repeated, list):
        for index, item in enumerate(repeated):
            if not isinstance(item, str):
                continue

            labels = _zone_labels_in_text(item)
            if len(labels) != 1:
                continue

            label = next(iter(labels))
            plan_item = plan_by_label.get(label)
            if not isinstance(plan_item, dict):
                errors.append(
                    f"repeated_observations[{index}]: referencia zona {label} que no existe en next_stint_plan."
                )
                continue

            allowed_channels = _plan_item_observed_channels(plan_item)
            mentioned_channels = _channels_mentioned_in_text(item)

            for channel in sorted(mentioned_channels - allowed_channels):
                errors.append(
                    f"repeated_observations[{index}]: menciona "
                    f"{human_channel.get(channel, channel)} en zona {label}, "
                    "pero ese canal no forma parte de observed_differences de esa zona."
                )

            expected = _plan_item_observed_direction_map(plan_item)
            actual = _global_factual_direction_by_channel(item)

            for channel in set(expected) & set(actual):
                if expected[channel] == actual[channel]:
                    continue

                observed_human = (
                    "mayor"
                    if expected[channel] == "higher_in_comparison_lap"
                    else "menor"
                )

                errors.append(
                    f"repeated_observations[{index}]: dirección factual invertida "
                    f"en zona {label} para {human_channel.get(channel, channel)}; "
                    f"Python observó {observed_human}."
                )


def validate_temporal_observation_not_action_target(
    value,
    field_name,
    plan,
    errors,
):
    """Reject cross-channel temporal coaching unless Python authorized it."""
    if not isinstance(value, str):
        return

    normalized = normalize_grounding_text(value)

    cross_channel_patterns = (
        r"\bsecuencia\s+(?:de|entre)\s+(?:el\s+)?freno\s*(?:y|con|->|→)\s*(?:el\s+)?acelerador\b",
        r"\bsecuencia\s+(?:de|entre)\s+(?:el\s+)?acelerador\s*(?:y|con|->|→)\s*(?:el\s+)?freno\b",
        r"\bsolap(?:amiento|ar|ados?|ada)?\b.{0,50}\bfreno\b.{0,50}\bacelerador\b",
        r"\bsolap(?:amiento|ar|ados?|ada)?\b.{0,50}\bacelerador\b.{0,50}\bfreno\b",
        r"\bfreno\b.{0,50}\bacelerador\b.{0,30}\bsin\s+solapamiento\b",
        r"\bacelerador\b.{0,50}\bfreno\b.{0,30}\bsin\s+solapamiento\b",
        r"\bprimero\s+(?:el\s+)?freno\b.{0,60}\bdespues\s+(?:el\s+)?acelerador\b",
        r"\bprimero\s+(?:el\s+)?acelerador\b.{0,60}\bdespues\s+(?:el\s+)?freno\b",
        r"\bfreno\s+primero\b.{0,60}\bacelerador\s+despues\b",
        r"\bacelerador\s+primero\b.{0,60}\bfreno\s+despues\b",
        r"\bfreno\s*(?:->|→)\s*acelerador\b",
        r"\bacelerador\s*(?:->|→)\s*freno\b",
        r"\bsepar(?:ar|a|e|á)\b.{0,60}\bfreno\b.{0,60}\bacelerador\b",
        r"\bsepar(?:ar|a|e|á)\b.{0,60}\bacelerador\b.{0,60}\bfreno\b",
        r"\bevit(?:ar|a|e|á)\b.{0,40}\bsolap",
        r"\bno\s+solap",
    )

    if not any(
        re.search(pattern, normalized)
        for pattern in cross_channel_patterns
    ):
        return

    plan_by_label = {
        str(item.get("plan_label") or "").strip().upper(): item
        for item in (plan or [])[:3]
        if isinstance(item, dict) and item.get("plan_label")
    }
    labels = _zone_labels_in_text(value)

    authorized = False
    if labels:
        authorized = all(
            bool((plan_by_label.get(label) or {}).get("temporal_target"))
            for label in labels
        )

    if authorized:
        return

    errors.append(
        f"{field_name}: convierte una observación temporal de freno/acelerador "
        "en coaching sin temporal_target autorizado por Python."
    )


def validate_global_direction_consistency(
    response,
    plan,
    errors,
):
    """
    Invariante global v3.10.8.

    1) Una prioridad de zona no puede invertir un target explícito de Python.
    2) Una conclusión que nombra una zona no puede invertir la dirección
       ya fijada para esa zona.

    Los targets de secuencia/mixed permanecen fuera de este chequeo.
    """
    if not isinstance(response, dict):
        return

    expected_by_label = {}

    for item in (
        plan
        or []
    )[:3]:
        if not isinstance(item, dict):
            continue

        label = str(
            item.get(
                "plan_label",
                "",
            )
        ).strip().upper()

        if not label:
            continue

        expected_by_label[label] = (
            _plan_item_expected_direction_map(
                item
            )
        )

    conclusion = response.get(
        "conclusion"
    )
    zone_segments = _single_zone_segments(
        conclusion
    )

    for label, segments in zone_segments.items():
        expected = expected_by_label.get(
            label,
            {},
        )

        if not expected:
            continue

        for segment in segments:
            actual = _explicit_command_direction_map(
                segment
            )

            for channel in (
                set(expected)
                &
                set(actual)
            ):
                if expected[channel] == actual[channel]:
                    continue

                human_channel = {
                    "brake": "freno",
                    "throttle": "acelerador",
                    "steering_magnitude": "magnitud de dirección/volante",
                }.get(channel, channel)

                expected_human = (
                    "aumentar"
                    if expected[channel] == "increase"
                    else "reducir"
                )

                errors.append(
                    "conclusion global: contradice el coaching determinista "
                    f"de zona {label} para {human_channel}; Python requiere "
                    f"{expected_human}."
                )


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

    for field in (
        "opportunities",
        "repeated_observations",
        "hypotheses",
        "limitations",
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
            }.get(field)

            if (
                max_items is not None
                and
                len(value) > max_items
            ):
                errors.append(
                    f"{field}: demasiados elementos; máximo {max_items}."
                )

            if field == "opportunities":
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

                    validate_speed_not_action_target(
                        item,
                        f"{field}[{index}]",
                        errors,
                    )
                    validate_global_secondary_steering_text(
                        item,
                        f"{field}[{index}]",
                        plan,
                        errors,
                    )
                    validate_reference_lap_is_action_target(
                        item,
                        f"{field}[{index}]",
                        errors,
                    )
                    validate_temporal_observation_not_action_target(
                        item,
                        f"{field}[{index}]",
                        plan,
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

        validate_speed_not_action_target(
            conclusion,
            "conclusion global",
            errors,
        )
        validate_global_secondary_steering_text(
            conclusion,
            "conclusion global",
            plan,
            errors,
        )
        validate_reference_lap_is_action_target(
            conclusion,
            "conclusion global",
            errors,
        )
        validate_temporal_observation_not_action_target(
            conclusion,
            "conclusion global",
            plan,
            errors,
        )

        if unsupported_phase.search(
            conclusion
        ):
            errors.append(
                "conclusion global inventa una fase/nombre de curva no suministrado por Python."
            )

    validate_global_direction_consistency(
        response,
        plan,
        errors,
    )

    validate_global_zone_list_consistency(
        response,
        plan,
        errors,
    )

    return errors




def repair_global_optional_list_overflow(
    response,
    session_coaching_facts,
):
    """
    Reparación determinista v3.10.8 para exceso de items en listas globales.

    Mantiene los límites estrictos del schema sin gastar un retry del LLM por
    un problema puramente de cardinalidad. Para opportunities intenta conservar
    primero una oportunidad por cada zona A/B/C presente en next_stint_plan y
    luego completa por orden original hasta el máximo permitido. Las demás
    listas opcionales se recortan por orden original.
    """
    if not isinstance(response, dict):
        return response, {}

    limits = {
        "opportunities": 4,
        "repeated_observations": 4,
        "hypotheses": 3,
        "limitations": 2,
    }

    repaired = dict(response)
    repairs = {}

    plan = (
        session_coaching_facts.get("next_stint_plan", [])
        if isinstance(session_coaching_facts, dict)
        else []
    )
    plan_labels = []
    for item in (plan or [])[:3]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("plan_label", "")).strip().upper()
        if label and label not in plan_labels:
            plan_labels.append(label)

    for field, max_items in limits.items():
        value = response.get(field)
        if not isinstance(value, list) or len(value) <= max_items:
            continue

        if field == "opportunities":
            selected = set()

            # Garantiza cobertura de las zonas deterministas principales si el
            # LLM devolvió al menos una opportunity claramente asociada a ellas.
            for label in plan_labels:
                for index, item in enumerate(value):
                    if index in selected or not isinstance(item, str):
                        continue
                    labels = _zone_labels_in_text(item)
                    if labels == {label}:
                        selected.add(index)
                        break

            # Completa por orden original sin exceder el límite.
            for index in range(len(value)):
                if len(selected) >= max_items:
                    break
                selected.add(index)

            kept_indexes = sorted(selected)[:max_items]
        else:
            kept_indexes = list(range(max_items))

        removed_indexes = [
            index for index in range(len(value))
            if index not in kept_indexes
        ]

        repaired[field] = [value[index] for index in kept_indexes]
        repairs[field] = {
            "original_count": len(value),
            "kept_count": len(kept_indexes),
            "kept_indexes": kept_indexes,
            "removed_indexes": removed_indexes,
            "reason": "max_items_enforced_deterministically",
        }

    return repaired, repairs

def prune_only_invalid_global_list_items(
    response,
    valid_comparison_results,
    session_coaching_facts,
    errors,
):
    """
    Fallback determinista v3.10.8 para listas narrativas opcionales globales.

    Tras agotar los reintentos del LLM, puede eliminar únicamente items
    concretos rechazados por el validator dentro de opportunities,
    repeated_observations, hypotheses o limitations. No reescribe ni elimina
    conclusion, no modifica next_session_priorities y no rescata errores de
    schema, dirección o cualquier error no atribuible a un item de lista.

    El candidato podado vuelve a pasar por validate_global_llm_response
    completo antes de ser aceptado.
    """
    if not isinstance(response, dict) or not errors:
        return None, {}

    allowed_fields = {
        "opportunities",
        "repeated_observations",
        "hypotheses",
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

    remaining = validate_global_llm_response(
        pruned,
        valid_comparison_results,
        session_coaching_facts,
    )
    if remaining:
        return None, {}

    return pruned, removed



def build_deterministic_global_fallback(
    session_coaching_facts,
):
    """
    Fallback global v3.10.8.5.4.

    La síntesis narrativa del LLM nunca debe ser un punto único de fallo.
    Si el backend no logra entregar un JSON global válido, Python construye
    un cierre mínimo únicamente desde next_stint_plan y los hechos recurrentes
    ya validados. No inventa causas, dominios ni objetivos nuevos.
    """
    plan = (
        session_coaching_facts.get("next_stint_plan", [])
        if isinstance(session_coaching_facts, dict)
        else []
    ) or []

    opportunities = []
    qualitative_by_label = {}

    for item in plan[:3]:
        if not isinstance(item, dict):
            continue

        label = str(item.get("plan_label") or "").strip().upper()
        if not label:
            continue

        parts = []
        for target in item.get("targets", []) or []:
            direct = _direct_coaching_target_text(target)
            if not direct:
                continue

            # opportunities/conclusion no admiten cifras. Los targets de punto
            # espacial permanecen exclusivamente en next_session_priorities.
            if text_contains_forbidden_numeric_content(direct):
                continue

            if direct not in parts:
                parts.append(direct)

        if not parts:
            continue

        qualitative_by_label[label] = parts
        opportunities.append(
            f"Zona {label}: " + "; ".join(parts) + "."
        )

    if not opportunities:
        opportunities = [
            "Concentrá la próxima tanda en los inputs repetidos de las zonas prioritarias."
        ]

    repeated_observations = build_deterministic_repeated_observations(
        session_coaching_facts
    )

    primary_label = None
    primary_parts = None
    for item in plan[:3]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("plan_label") or "").strip().upper()
        parts = qualitative_by_label.get(label)
        if label and parts:
            primary_label = label
            primary_parts = parts
            break

    if primary_label and primary_parts:
        conclusion = (
            f"Empezá la próxima tanda por la zona {primary_label}: "
            + "; ".join(primary_parts)
            + ". Después continuá con las demás zonas prioritarias."
        )
    else:
        conclusion = (
            "En la próxima tanda, concentrá la ejecución en los inputs repetidos "
            "de las zonas prioritarias."
        )

    return {
        "opportunities": opportunities[:4],
        "repeated_observations": repeated_observations[:4],
        "hypotheses": [],
        "limitations": [],
        "conclusion": conclusion,
    }


GLOBAL_STEERING_CONCLUSION_ANCHOR_ERROR = (
    "conclusion global: steering_magnitude directo debe quedar anclado "
    "a una única zona A/B/C."
)


def repair_global_steering_conclusion_anchor(
    response,
    valid_comparison_results,
    session_coaching_facts,
    errors,
):
    """
    Hotfix v3.10.8.5.4.

    Repara exclusivamente el caso en que la conclusión del LLM convierte
    steering_magnitude en una orden global sin anclarla a una sola zona.
    El validator NO se relaja: reemplazamos únicamente `conclusion` por la
    conclusión cualitativa derivada del plan determinista y revalidamos todo.
    """
    if not isinstance(response, dict) or not errors:
        return None, {}, list(errors or [])

    if GLOBAL_STEERING_CONCLUSION_ANCHOR_ERROR not in {
        str(error) for error in errors
    }:
        return None, {}, list(errors or [])

    deterministic = build_deterministic_global_fallback(
        session_coaching_facts
    )
    replacement = deterministic.get("conclusion")
    if not isinstance(replacement, str) or not replacement.strip():
        return None, {}, list(errors or [])

    repaired = dict(response)
    repaired["conclusion"] = replacement.strip()

    remaining = validate_global_llm_response(
        repaired,
        valid_comparison_results,
        session_coaching_facts,
    )

    # Si por algún cambio futuro el reemplazo sigue violando el mismo contrato,
    # no lo aceptamos silenciosamente.
    if GLOBAL_STEERING_CONCLUSION_ANCHOR_ERROR in {
        str(error) for error in remaining
    }:
        return None, {}, list(errors or [])

    return repaired, {
        "field": "conclusion",
        "reason": "direct_steering_without_single_zone_anchor",
        "strategy": "deterministic_conclusion_from_next_stint_plan",
    }, remaining


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
        MAX_GLOBAL_LLM_VALIDATION_ATTEMPTS + 1,
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

        raw = deepseek_chat(
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

        if isinstance(parsed, dict) and "repeated_observations" in parsed:
            parsed["repeated_observations"] = (
                build_deterministic_repeated_observations(
                    session_coaching_facts
                )
            )

        parsed, overflow_repairs = repair_global_optional_list_overflow(
            parsed,
            session_coaching_facts,
        )

        if overflow_repairs:
            repaired_fields = ", ".join(
                f"{field}({details['original_count']}→{details['kept_count']})"
                for field, details in overflow_repairs.items()
            )
            print(
                "Síntesis global: reparación determinista de cardinalidad "
                f"aplicada sin retry: {repaired_fields}."
            )

        errors = validate_global_llm_response(
            parsed,
            valid_comparison_results,
            session_coaching_facts,
        )

        steering_conclusion_repair = {}
        if errors:
            repaired_response, steering_conclusion_repair, repaired_errors = (
                repair_global_steering_conclusion_anchor(
                    parsed,
                    valid_comparison_results,
                    session_coaching_facts,
                    errors,
                )
            )
            if repaired_response is not None:
                parsed = repaired_response
                errors = repaired_errors
                print(
                    "Síntesis global: reparación determinista v3.10.8.5.4 "
                    "aplicada sin retry; conclusion con steering global fue "
                    "reemplazada por una conclusión anclada al plan de Python."
                )

        if not errors:
            parsed[
                "next_session_priorities"
            ] = (
                build_deterministic_next_session_priorities(
                    session_coaching_facts
                )
            )

            deterministic_repairs = {}
            if overflow_repairs:
                deterministic_repairs["optional_list_overflow"] = overflow_repairs
            if steering_conclusion_repair:
                deterministic_repairs["global_steering_conclusion"] = (
                    steering_conclusion_repair
                )

            return {
                "status":
                    "VALID",

                "attempts":
                    attempt,

                "response":
                    parsed,

                "validation_errors":
                    [],

                "deterministic_repairs":
                    deterministic_repairs,
            }

    pruned_response, removed_items = (
        prune_only_invalid_global_list_items(
            parsed if 'parsed' in locals() else None,
            valid_comparison_results,
            session_coaching_facts,
            errors,
        )
    )

    if pruned_response is not None:
        removed_count = sum(
            len(indexes)
            for indexes in removed_items.values()
        )

        pruned_response["repeated_observations"] = (
            build_deterministic_repeated_observations(
                session_coaching_facts
            )
        )

        pruned_response[
            "next_session_priorities"
        ] = (
            build_deterministic_next_session_priorities(
                session_coaching_facts
            )
        )

        print(
            "Síntesis global: fallback determinista v3.10.8 "
            f"aplicado; se descartaron {removed_count} items "
            "opcionales no grounded."
        )

        return {
            "status": "VALID",
            "attempts": MAX_GLOBAL_LLM_VALIDATION_ATTEMPTS,
            "response": pruned_response,
            "validation_errors": [],
            "fallback": "PRUNED_INVALID_OPTIONAL_GLOBAL_ITEMS",
            "pruned_global_items": removed_items,
        }

    # Última barrera v3.10.8.5.4: la narrativa global no invalida
    # hechos deterministas ya validados. Si retries + repairs no alcanzan,
    # construimos una síntesis mínima desde next_stint_plan y recurrencia.
    fallback_response = build_deterministic_global_fallback(
        session_coaching_facts
    )
    fallback_errors = validate_global_llm_response(
        fallback_response,
        valid_comparison_results,
        session_coaching_facts,
    )

    if not fallback_errors:
        fallback_response[
            "next_session_priorities"
        ] = (
            build_deterministic_next_session_priorities(
                session_coaching_facts
            )
        )

        print(
            "Síntesis global: fallback determinista v3.10.8.5.4 aplicado; "
            "la narrativa del backend no pudo validarse, pero la sesión se "
            "guarda desde next_stint_plan y recurrencia de Python."
        )

        return {
            "status": "VALID",
            "attempts": MAX_GLOBAL_LLM_VALIDATION_ATTEMPTS,
            "response": fallback_response,
            "validation_errors": [],
            "fallback": "DETERMINISTIC_GLOBAL_FROM_NEXT_STINT_PLAN",
            "llm_validation_errors": errors or [],
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
            MAX_GLOBAL_LLM_VALIDATION_ATTEMPTS,

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
    """
    Presentación v1.0 del debrief de sesión.

    El detalle granular sigue disponible en session_coaching_facts y en cada
    comparación. El texto visible prioriza lectura, plan y respaldo.
    """
    lines = []

    track = metadata.get("track") or "Sesión"
    session_type = metadata.get("session_type")
    title_suffix = f" · {session_type}" if session_type else ""

    lines.append(f"# Debrief de ingeniería — {track}{title_suffix}")
    lines.append("")

    lap_times = metadata.get("lap_times_s", {}) or {}
    reference_lap = safe_int(metadata.get("reference_lap"))
    reference_time = safe_float(lap_times.get(str(reference_lap)))

    plan = session_coaching_facts.get("next_stint_plan", []) or []

    # Repeated physical patterns are shared by both the narrative section
    # and the technical appendix. Initialize them before either section.
    braking_patterns = (
        session_coaching_facts.get("repeated_braking_point_patterns", []) or []
    )
    brake_release_patterns = (
        session_coaching_facts.get("repeated_brake_release_patterns", []) or []
    )
    throttle_onset_patterns = (
        session_coaching_facts.get("repeated_throttle_onset_patterns", []) or []
    )
    throttle_release_patterns = (
        session_coaching_facts.get("repeated_throttle_release_patterns", []) or []
    )

    def prose(value):
        value = str(value or "").strip()
        if not value:
            return ""
        value = value[0].upper() + value[1:]
        if value[-1] not in ".!?":
            value += "."
        return value

    if reference_time is None and comparison_results:
        reference_time = safe_float(
            comparison_results[0].get("reference_time_s")
        )

    # ----------------------------------------------------------
    # Lectura primero: debe poder entenderse sin mirar el apéndice.
    # ----------------------------------------------------------
    lines.append("## Lectura de la sesión")
    lines.append("")

    if reference_lap is not None and reference_time is not None:
        lines.append(
            f"La referencia de trabajo fue la vuelta {reference_lap}, "
            f"con {format_lap_time(reference_time)}."
        )
    elif reference_lap is not None:
        lines.append(f"La referencia de trabajo fue la vuelta {reference_lap}.")

    if plan:
        def item_has_repeated_evidence(item):
            if item.get("kind") == "repeated_region":
                return True

            return any(
                (
                    safe_int(pattern.get("comparison_count"))
                    or 0
                )
                >= 2
                for field in (
                    "braking_point_patterns",
                    "brake_release_patterns",
                    "throttle_onset_patterns",
                    "throttle_release_patterns",
                )
                for pattern in (item.get(field, []) or [])
                if isinstance(pattern, dict)
            )

        repeated_count = sum(
            1 for item in plan
            if item_has_repeated_evidence(item)
        )
        zone_word = "zona prioritaria" if len(plan) == 1 else "zonas prioritarias"
        if repeated_count == len(plan) and repeated_count > 0:
            lines.append(
                f"El plan de la próxima tanda queda concentrado en "
                f"{len(plan)} {zone_word}, todas respaldadas por patrones "
                "repetidos entre comparaciones."
            )
        elif repeated_count:
            if repeated_count == 1:
                lines.append(
                    f"El plan de la próxima tanda queda concentrado en "
                    f"{len(plan)} {zone_word}; una de ellas cuenta con "
                    "patrones repetidos entre comparaciones."
                )
            else:
                lines.append(
                    f"El plan de la próxima tanda queda concentrado en "
                    f"{len(plan)} {zone_word}; {repeated_count} cuentan con "
                    "patrones repetidos entre comparaciones."
                )
        else:
            lines.append(
                f"El plan de la próxima tanda queda concentrado en "
                f"{len(plan)} {zone_word}."
            )

    session_focus = _deterministic_session_focus(plan)
    if session_focus:
        lines.append("")
        lines.append(session_focus)

    quality_gate = session_coaching_facts.get("comparison_quality_gate", {}) or {}
    excluded_comparisons = quality_gate.get("excluded_comparisons", []) or []
    if excluded_comparisons:
        lines.append("")
        if len(excluded_comparisons) == 1:
            lines.append(
                "Una comparación globalmente no representativa quedó fuera del agregado "
                "de coaching de esta sesión; permanece disponible en el JSON."
            )
        else:
            lines.append(
                f"{len(excluded_comparisons)} comparaciones globalmente no representativas "
                "quedaron fuera del agregado de coaching de esta sesión; permanecen disponibles en el JSON."
            )

    # ----------------------------------------------------------
    # Plan accionable
    # ----------------------------------------------------------
    lines.append("")
    lines.append("## Plan para la próxima tanda")
    lines.append("")

    priorities = global_structured.get("next_session_priorities", []) or []

    def clean_priority(text_value, label):
        value = str(text_value or "").strip()
        prefix = f"Zona prioritaria {label}:"
        if value.lower().startswith(prefix.lower()):
            value = value[len(prefix):].strip()
        if value and value[-1] not in ".!?":
            value += "."
        return value

    for index, item in enumerate(plan[:3], start=1):
        label = str(item.get("plan_label") or "?")
        location = track_location_label(item)
        heading = f"Zona {label}"
        if location:
            heading += f" — {location}"

        lines.append(f"### {index}. {heading}")
        lines.append("")

        driver_cues = item.get("driver_cues") or build_driver_cues_for_plan_item(item)
        if driver_cues:
            first_cue = str(driver_cues[0].get("text") or "").strip()
            if first_cue:
                lines.append(f"**Qué cambiar:** {prose(first_cue)}")
                lines.append("")
            if len(driver_cues) > 1:
                second_cue = str(driver_cues[1].get("text") or "").strip()
                if second_cue:
                    lines.append(f"**Segundo cue:** {prose(second_cue)}")
                    lines.append("")

            precision_lines = _render_precision_evidence_lines(driver_cues[0])
            for precision_line in precision_lines:
                lines.append(precision_line)
            if precision_lines:
                lines.append("")

        reference_profiles = [
            profile
            for profile in (item.get("reference_action_profiles", []) or [])
            if isinstance(profile, dict) and profile.get("shape_summary")
        ]
        if reference_profiles:
            channel_labels = {
                "throttle": "Acelerador",
                "brake": "Freno",
            }
            profile_texts = []
            for profile in reference_profiles[:2]:
                summary = str(
                    profile.get("shape_summary_detailed")
                    or profile.get("shape_summary")
                    or ""
                ).strip()
                if not summary:
                    continue
                channel = str(profile.get("channel") or "").strip()
                prefix = channel_labels.get(channel, channel.capitalize() if channel else "Input")
                profile_texts.append(f"{prefix}: {summary}")

            if profile_texts:
                lines.append(
                    "**Forma observada en la referencia:** "
                    + "; ".join(profile_texts)
                    + "."
                )
            lines.append(
                "_Descripción de forma; los puntos numéricos de coaching siguen "
                "siendo únicamente los autorizados por los detectores de eventos._"
            )
            lines.append("")

        comparisons = [
            str(v) for v in (item.get("comparisons", []) or []) if v
        ]
        comparison_count = item.get("comparison_count")
        observed = [
            str(v) for v in (item.get("observed_differences", []) or []) if v
        ]

        support_parts = []
        primary_cue_point_count = 0
        if driver_cues:
            primary_cue_point_count = (
                safe_int(driver_cues[0].get("point_comparison_count"))
                or 0
            )

        if primary_cue_point_count >= 2:
            support_parts.append(
                f"el punto físico que genera este cue se repitió en "
                f"{primary_cue_point_count} comparaciones"
            )
            if (
                item.get("kind") == "repeated_region"
                and comparison_count
                and comparison_count != primary_cue_point_count
            ):
                support_parts.append(
                    f"la región completa apareció en {comparison_count} comparaciones"
                )
        elif item.get("kind") == "repeated_region" and comparison_count:
            support_parts.append(
                f"la región apareció en {comparison_count} comparaciones"
            )
        elif item.get("kind") == "repeated_point_pattern" and comparison_count:
            support_parts.append(
                f"el punto de input se repitió en {comparison_count} comparaciones"
            )
        elif comparisons:
            support_parts.append("es el hallazgo individual mejor priorizado")

        repeated_point_counts = [
            safe_int(pattern.get("comparison_count")) or 0
            for field in (
                "braking_point_patterns",
                "brake_release_patterns",
                "throttle_onset_patterns",
                "throttle_release_patterns",
            )
            for pattern in (item.get(field, []) or [])
            if isinstance(pattern, dict)
        ]
        repeated_point_count = max(repeated_point_counts, default=0)

        if (
            item.get("kind")
            not in {
                "repeated_region",
                "repeated_point_pattern",
            }
            and repeated_point_count >= 2
        ):
            support_parts.append(
                f"además, un punto de input se repitió en "
                f"{repeated_point_count} comparaciones"
            )

        speed_fact = _render_speed_context_fact(item)
        if speed_fact:
            support_parts.append(f"el contexto mostró {speed_fact}")

        if support_parts:
            sentence = "; ".join(support_parts)
            sentence = sentence[0].upper() + sentence[1:] + "."
            lines.append(f"**Por qué está en el plan:** {sentence}")
            lines.append("")

        if observed:
            lines.append("**Qué observamos:** " + prose(", ".join(observed)))
            lines.append("")

        if primary_cue_point_count >= 2:
            lines.append(
                f"**Confianza del cue:** punto físico repetido en "
                f"{primary_cue_point_count} comparaciones válidas para el plan."
            )
            lines.append("")
        elif item.get("kind") == "repeated_region" and comparison_count:
            lines.append(
                f"**Confianza:** región repetida en {comparison_count} comparaciones válidas para el plan."
            )
            lines.append("")

        temporal = [
            str(v)
            for v in (item.get("temporal_relationships", []) or [])
            if v
        ]
        if temporal:
            lines.append(
                "**Secuencia medida:** " + "; ".join(temporal[:2]) + "."
            )
            lines.append("")

    if not plan:
        lines.append(
            "No hay evidencia suficiente para construir un plan de conducción "
            "priorizado en esta sesión."
        )
        lines.append("")

    # ----------------------------------------------------------
    # Patrones repetidos: lectura, no inventario completo.
    # ----------------------------------------------------------
    repeated = global_structured.get("repeated_observations", []) or []
    if repeated:
        lines.append("## Patrón que deja la sesión")
        lines.append("")
        for item in repeated[:4]:
            lines.append(f"- {prose(item)}")
        lines.append("")

    # Patrones físicos repetidos que no entraron en el top 3.
    attached_signatures = set()
    for item in plan:
        for field in (
            "braking_point_patterns",
            "brake_release_patterns",
            "throttle_onset_patterns",
            "throttle_release_patterns",
        ):
            for pattern in (item.get(field, []) or []):
                if not isinstance(pattern, dict):
                    continue
                attached_signatures.add((
                    field,
                    pattern.get("region_label"),
                    pattern.get("reference_onset_m"),
                    pattern.get("reference_release_m"),
                    pattern.get("coaching_direction"),
                    pattern.get("coaching_magnitude_m"),
                ))

    secondary_point_patterns = []

    def collect_secondary(patterns, field, action_name):
        for pattern in patterns or []:
            if (
                not isinstance(pattern, dict)
                or pattern.get("status") != "REPEATED"
            ):
                continue

            signature = (
                field,
                pattern.get("region_label"),
                pattern.get("reference_onset_m"),
                pattern.get("reference_release_m"),
                pattern.get("coaching_direction"),
                pattern.get("coaching_magnitude_m"),
            )
            if signature in attached_signatures:
                continue

            magnitude = safe_int(pattern.get("coaching_magnitude_m"))
            if magnitude is None:
                continue

            direction = pattern.get("coaching_direction")
            move = "más tarde" if direction == "later" else "más temprano"
            location = track_location_label(pattern)
            prefix = location or (
                f"Zona {pattern.get('region_label')}"
                if pattern.get("region_label")
                else "Otra zona"
            )
            comparison_count = safe_int(pattern.get("comparison_count")) or 0

            secondary_point_patterns.append(
                f"{prefix}: {action_name} aproximadamente {magnitude} m "
                f"{move}; patrón repetido en {comparison_count} comparaciones"
            )

    collect_secondary(
        braking_patterns,
        "braking_point_patterns",
        "iniciar la frenada",
    )
    collect_secondary(
        brake_release_patterns,
        "brake_release_patterns",
        "soltar el freno",
    )
    collect_secondary(
        throttle_onset_patterns,
        "throttle_onset_patterns",
        "reaplicar el acelerador",
    )
    collect_secondary(
        throttle_release_patterns,
        "throttle_release_patterns",
        "soltar el acelerador",
    )

    if secondary_point_patterns:
        lines.append("## Patrón repetido fuera del foco principal")
        lines.append("")
        lines.append(
            "No lo subiría por encima de las tres prioridades actuales, "
            "pero conviene tenerlo presente:"
        )
        lines.append("")
        for item in secondary_point_patterns[:3]:
            lines.append(f"- {item}.")
        lines.append("")

    # opportunities queda disponible en global_structured; el render evita
    # repetir el plan con un segundo listado casi equivalente.

    hypotheses = global_structured.get("hypotheses", []) or []
    if hypotheses:
        lines.append("## Hipótesis prudentes")
        lines.append("")
        for item in hypotheses[:3]:
            lines.append(f"- {prose(item)}")
        lines.append("")

    limitations = global_structured.get("limitations", []) or []
    if limitations:
        lines.append("## Límites de la lectura")
        lines.append("")
        for item in limitations[:2]:
            lines.append(f"- {prose(item)}")
        lines.append("")

    # ----------------------------------------------------------
    # Apéndice técnico compacto. La información exhaustiva permanece
    # en el JSON y no hace falta repetirla toda en la narrativa.
    # ----------------------------------------------------------
    lines.append("## Respaldo técnico")
    lines.append("")

    if comparison_results:
        quality_by_key = _comparison_quality_map(
            session_coaching_facts.get("comparison_quality_gate", {}) or {}
        )
        comparison_parts = []
        for r in comparison_results:
            key = _session_comparison_key(r)
            suffix = ""
            quality = quality_by_key.get(key, {})
            if quality and not quality.get("session_plan_eligible", True):
                suffix = " [excluida del plan]"
            elif (
                quality
                and quality.get("quality_status")
                == "STATISTICAL_OUTLIER_RETAINED_FOR_COACHING"
            ):
                suffix = " [outlier estadístico retenido]"
            comparison_parts.append(
                f"{r['reference_lap']}→{r['comparison_lap']} "
                f"{signed_seconds(r['comparison_minus_reference_s'])}{suffix}"
            )
        comparison_text = ", ".join(comparison_parts)
        lines.append(f"**Comparaciones:** {comparison_text}.")

    point_summaries = []

    def current_plan_label_for_pattern(pattern):
        """
        v3.10.8 presentation-only.

        Un patrón físico repetido puede ser promovido/re-etiquetado por el
        plan de recurrencia. El apéndice debe mostrar la etiqueta ACTUAL del
        plan, no la etiqueta de región previa al ranking.
        """
        if not isinstance(pattern, dict):
            return None

        matches = [
            item
            for item in plan[:3]
            if isinstance(item, dict)
            and _same_plan_region(
                item,
                pattern,
            )
        ]

        if not matches:
            return None

        matches.sort(
            key=lambda item: _plan_overlap_m(
                item,
                pattern,
            ),
            reverse=True,
        )

        return (
            matches[0].get("plan_label")
            or pattern.get("region_label")
        )

    for pattern in braking_patterns[:3]:
        label = current_plan_label_for_pattern(pattern)
        location = track_location_label(pattern)
        prefix = (
            f"Zona {label}"
            if label
            else location or "Patrón de frenada"
        )
        magnitude = safe_int(pattern.get("coaching_magnitude_m"))
        direction = pattern.get("coaching_direction")
        if magnitude is not None:
            move = "más tarde" if direction == "later" else "más temprano"
            point_summaries.append(
                f"{prefix}: inicio de frenada {magnitude} m {move}"
            )

    for pattern in brake_release_patterns[:3]:
        label = current_plan_label_for_pattern(pattern)
        location = track_location_label(pattern)
        prefix = (
            f"Zona {label}"
            if label
            else location or "Patrón de frenada"
        )
        magnitude = safe_int(pattern.get("coaching_magnitude_m"))
        direction = pattern.get("coaching_direction")
        if magnitude is not None:
            move = "más tarde" if direction == "later" else "más temprano"
            point_summaries.append(
                f"{prefix}: liberación de freno {magnitude} m {move}"
            )

    for pattern in throttle_onset_patterns[:3]:
        label = current_plan_label_for_pattern(pattern)
        location = track_location_label(pattern)
        prefix = (
            f"Zona {label}"
            if label
            else location or "Patrón de acelerador"
        )
        magnitude = safe_int(pattern.get("coaching_magnitude_m"))
        direction = pattern.get("coaching_direction")
        if magnitude is not None:
            move = "más tarde" if direction == "later" else "más temprano"
            point_summaries.append(
                f"{prefix}: reaplicación de acelerador {magnitude} m {move}"
            )

    for pattern in throttle_release_patterns[:3]:
        label = current_plan_label_for_pattern(pattern)
        location = track_location_label(pattern)
        prefix = (
            f"Zona {label}"
            if label
            else location or "Patrón de acelerador"
        )
        magnitude = safe_int(pattern.get("coaching_magnitude_m"))
        direction = pattern.get("coaching_direction")
        if magnitude is not None:
            move = "más tarde" if direction == "later" else "más temprano"
            point_summaries.append(
                f"{prefix}: liberación de acelerador {magnitude} m {move}"
            )

    if point_summaries:
        lines.append("")
        lines.append("**Objetivos espaciales repetidos:**")
        for item in point_summaries:
            lines.append(f"- {item}.")

    technical_zone_observations = []
    for item in plan[:3]:
        quantitative = [
            str(value)
            for value in (item.get("quantitative_observations", []) or [])
            if value
        ]
        if not quantitative:
            continue
        label = item.get("plan_label") or "?"
        technical_zone_observations.append(
            f"Zona {label}: " + "; ".join(quantitative[:3])
        )
    if technical_zone_observations:
        lines.append("")
        lines.append("**Observaciones cuantitativas por zona:**")
        for value in technical_zone_observations:
            lines.append(f"- {value}.")

    findings = session_coaching_facts.get("priority_findings", []) or []
    if findings:
        lines.append("")
        lines.append("**Episodios que más pesan en la priorización:**")
        for finding in findings[:4]:
            location = track_location_label(finding)
            loc = f" · {location}" if location else ""
            lines.append(
                f"- {finding.get('comparison')} · episodio "
                f"#{finding.get('episode_id')}{loc} · "
                f"{_render_action_delta_fact(finding.get('action_time_loss_s'))}."
            )

    excluded = []
    for result in comparison_results:
        for anomaly in (result.get("excluded_anomalies", []) or []):
            if isinstance(anomaly, dict):
                excluded.append(anomaly)
    if excluded:
        lines.append("")
        lines.append(
            f"**Incidencias excluidas:** {len(excluded)} pérdida(s) anómala(s) "
            "quedaron fuera del coaching de técnica."
        )

    lines.append("")
    lines.append(
        "_La evidencia completa, los episodios descartados, las magnitudes por "
        "canal y las asignaciones onset/release permanecen disponibles en el JSON._"
    )

    return "\n".join(lines)


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
    global_validation_audit=None,
):
    stem = os.path.splitext(
        os.path.basename(
            input_path
        )
    )[0]

    output_dir = str(llm_result_dir(input_path))

    os.makedirs(
        output_dir,
        exist_ok=True,
    )

    output_path = os.path.join(
        output_dir,
        stem + f"_llm_analysis_v3_10_8_5_4_deepseek_v2_{MODEL_NAME}.json",
    )

    braking_point_detection = next(
        (
            item.get("braking_point_detection")
            for item in comparison_results
            if (
                isinstance(item, dict)
                and isinstance(
                    item.get("braking_point_detection"),
                    dict,
                )
                and item.get("braking_point_detection")
            )
        ),
        {},
    )

    throttle_point_detection = next(
        (
            item.get("throttle_point_detection")
            for item in comparison_results
            if (
                isinstance(item, dict)
                and isinstance(
                    item.get("throttle_point_detection"),
                    dict,
                )
                and item.get("throttle_point_detection")
            )
        ),
        {},
    )

    result = {
        "metadata": {
            "llm_analysis_version":
                "3.10.8.5.4",

            "report_presentation_version": "2.4",

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

            "deepseek_usage":
                deepseek_usage_summary(),

            "context":
                CONTEXT_SIZE,

            "temperature":
                TEMPERATURE,

            "track_location_profile":
                session_coaching_facts.get(
                    "track_location_profile"
                ),

            "braking_point_detection":
                braking_point_detection,

            "throttle_point_detection":
                throttle_point_detection,

            "session_comparison_quality_gate":
                session_coaching_facts.get("comparison_quality_gate", {}),

            "anomaly_gate": {
                "version": "1.0",
                "status": "ACTIVE",
                "classification":
                    "NON_REPRESENTATIVE_TIME_LOSS",
                "config":
                    dict(ANOMALY_GATE_CONFIG),
                "cause_inference":
                    False,
            },

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

        "global_validation_audit":
            global_validation_audit or {},

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
    reset_deepseek_usage()

    print_header(
        "RACE ENGINEER - LLM ANALYSIS v3.10.8.5.4 / DeepSeek provisional v2"
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

    track_location_context = (
        load_track_location_context(
            metadata
        )
    )

    if not comparisons:
        raise RuntimeError(
            "El JSON no contiene comparaciones."
        )

    stem = os.path.splitext(
        os.path.basename(
            input_path
        )
    )[0]

    output_dir = str(llm_debug_dir(input_path, backend="deepseek"))

    os.makedirs(
        output_dir,
        exist_ok=True,
    )

    print()

    print(
        f"Modelo/API: {MODEL_NAME} @ DeepSeek"
    )

    print(
        f"Contexto: {CONTEXT_SIZE}"
    )

    print(
        f"Temperatura: {TEMPERATURE}"
    )

    print()

    if (
        track_location_context.get(
            "status"
        )
        ==
        "ACTIVE"
    ):
        print(
            "Ubicación de pista: "
            f"{track_location_context.get('profile_id')} "
            f"[{track_location_context.get('profile_status')}]"
        )
    else:
        print(
            "Ubicación de pista: "
            f"{track_location_context.get('status')} "
            "(se conservan metros sin nombres de curva)"
        )

    print()

    print(
        "Arquitectura v3.10.8.5.4:"
    )

    print(
        "Python = hechos + estructura + validación + gate de anomalías + quality gate 1.1 + ubicación de curva + throttle 1.2 observacional + render"
    )

    print(
        "LLM = interpretación aislada + ranking comparativo + coaching final\nPython fallback = descripción factual mínima si el texto LLM no logra grounded tras reintentos"
    )

    print()

    pre_session_quality_gate = build_session_comparison_quality_gate(comparisons)
    pre_session_quality_by_key = _comparison_quality_map(pre_session_quality_gate)

    excluded_count = safe_int(pre_session_quality_gate.get("excluded_count")) or 0
    retained_outlier_count = (
        safe_int(pre_session_quality_gate.get("retained_statistical_outlier_count"))
        or 0
    )
    if retained_outlier_count:
        print(
            f"Gate de calidad de comparación: {retained_outlier_count} "
            "outlier(s) estadístico(s) conservado(s) para coaching al no "
            "presentar severidad local suficiente para excluirlos."
        )
        print()

    if excluded_count:
        if excluded_count == 1:
            message = (
                "Gate de calidad de comparación: 1 comparación globalmente no representativa "
                "no llamará al LLM ni alimentará el plan de sesión."
            )
        else:
            message = (
                f"Gate de calidad de comparación: {excluded_count} comparaciones globalmente no representativas "
                "no llamarán al LLM ni alimentarán el plan de sesión."
            )
        print(message)
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

        comparison_key = _session_comparison_key(comparison)
        comparison_quality = pre_session_quality_by_key.get(comparison_key, {})
        session_plan_eligible = bool(
            comparison_quality.get("session_plan_eligible", True)
        )

        detected_episode_catalog = (
            build_episode_catalog(
                comparison
            )
        )

        enrich_items_with_track_location(
            detected_episode_catalog,
            track_location_context,
        )

        (
            episode_catalog,
            excluded_anomalies,
        ) = split_episode_catalog_for_coaching(
            comparison,
            detected_episode_catalog,
        )

        print(
            f"Comparación: "
            f"{reference_lap} -> "
            f"{comparison_lap}"
        )

        print(
            f"Tiempo A: "
            f"{format_lap_time(comparison['reference_time_s'])}"
        )

        print(
            f"Tiempo B: "
            f"{format_lap_time(comparison['comparison_time_s'])}"
        )

        print(
            f"Delta real: "
            f"{signed_seconds(comparison['comparison_minus_reference_s'])}"
        )

        print(
            f"Episodios detectados: "
            f"{len(detected_episode_catalog)}"
        )

        print(
            f"Episodios elegibles para coaching: "
            f"{len(episode_catalog)}"
        )

        print(
            f"Pérdidas anómalas excluidas: "
            f"{len(excluded_anomalies)}"
        )

        for anomaly in excluded_anomalies:
            print(
                "  - episodio "
                f"#{anomaly.get('episode_id')} · "
                f"{meters(anomaly.get('start_distance_m'))}–"
                f"{meters(anomaly.get('end_distance_m'))} · "
                f"{signed_seconds(anomaly.get('local_loss_s'))}"
            )

        if not detected_episode_catalog:
            raise RuntimeError(
                "No hay driver_action_episode disponibles "
                f"para {reference_lap} -> {comparison_lap}. "
                "La v3.10.8.5.4 requiere analyze_telemetry v3.8 "
                "con episodios primarios."
            )

        print()

        if not session_plan_eligible:
            print(
                "Comparación excluida por el gate global de calidad; se conserva el ground truth "
                "pero no se llama al LLM ni al ranker."
            )
            validated = {
                "status": "VALID",
                "attempts": 0,
                "response": {
                    "episode_assessments": [],
                    "comparison_observations": [],
                    "limitations": [
                        "Comparación globalmente no representativa; no se usa para coaching de sesión"
                    ],
                    "conclusion": "Comparación preservada para auditoría; excluida del coaching de sesión",
                },
                "validation_errors": [],
                "audit": {
                    "episodes": [],
                    "priority_ranking": {
                        "attempts": 0,
                        "ordered_episode_ids": [],
                        "priority_cut_rank": None,
                        "no_actionable_start_rank": None,
                        "classifications": [],
                    },
                    "summary": {
                        "attempts": 0,
                        "fallback": "COMPARISON_QUALITY_GATE_EXCLUDED_BEFORE_LLM",
                        "pruned_summary_items": {},
                    },
                },
            }
        elif episode_catalog:
            print(
                "Solicitando interpretación aislada + ranking comparativo v3.10.8.5.4..."
            )

            validated = (
                get_validated_comparison_response(
                    metadata,
                    comparison,
                    episode_catalog,
                    output_dir,
                )
            )
        else:
            print(
                "Todos los episodios fueron excluidos por el gate de anomalías; "
                "no se llama al LLM ni al ranker para esta comparación."
            )

            validated = {
                "status": "VALID",
                "attempts": 0,
                "response": {
                    "episode_assessments": [],
                    "comparison_observations": [],
                    "limitations": [
                        (
                            "No se generó coaching técnico porque los episodios "
                            "detectados fueron excluidos como pérdidas anómalas"
                        )
                    ],
                    "conclusion": (
                        "No se genera coaching técnico para esta comparación"
                    ),
                },
                "validation_errors": [],
                "audit": {
                    "episodes": [],
                    "priority_ranking": {
                        "attempts": 0,
                        "ordered_episode_ids": [],
                        "priority_cut_rank": None,
                        "no_actionable_start_rank": None,
                        "classifications": [],
                    },
                    "summary": {
                        "attempts": 0,
                        "fallback": "ALL_EPISODES_EXCLUDED_BY_ANOMALY_GATE",
                        "pruned_summary_items": {},
                    },
                },
            }

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

        if session_plan_eligible:
            rendered = (
                render_comparison_analysis(
                    comparison,
                    episode_catalog,
                    structured,
                )
            )
        else:
            rendered = (
                "Comparación preservada para auditoría. "
                "Fue excluida del coaching de sesión por el gate global de calidad y no se envió al LLM."
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

            "session_plan_eligible":
                session_plan_eligible,

            "session_comparison_quality":
                comparison_quality,

            "detected_driver_action_episode_count":
                len(
                    detected_episode_catalog
                ),

            "driver_action_episode_count":
                len(
                    episode_catalog
                ),

            "coaching_eligible_episode_count":
                len(
                    episode_catalog
                ),

            "excluded_anomaly_count":
                len(
                    excluded_anomalies
                ),

            "excluded_anomalies":
                excluded_anomalies,

            "braking_point_detection":
                (
                    comparison.get(
                        "objective_analysis",
                        {},
                    )
                    or {}
                ).get(
                    "braking_point_detection",
                    {},
                ),

            "throttle_point_detection":
                (
                    comparison.get(
                        "objective_analysis",
                        {},
                    )
                    or {}
                ).get(
                    "throttle_point_detection",
                    {},
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
            comparison_results,
            track_location_context=(
                track_location_context
            ),
            source_data=data,
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

    global_validation_audit = {
        key: global_validated.get(key)
        for key in (
            "status",
            "attempts",
            "fallback",
            "deterministic_repairs",
            "pruned_global_items",
            "llm_validation_errors",
        )
        if global_validated.get(key) not in (None, {}, [])
    }

    global_analysis = (
        render_global_analysis(
            metadata,
            comparison_results,
            session_coaching_facts,
            global_structured,
        )
    )

    track_reference_section = render_track_reference_section(
        track_location_context.get("profile"),
        session_coaching_facts.get("next_stint_plan"),
    )
    if track_reference_section:
        global_analysis = (
            global_analysis.rstrip()
            + "\n\n"
            + track_reference_section
        )

    output_path, _ = save_result(
        input_path,
        metadata,
        comparison_results,
        session_coaching_facts,
        global_structured,
        global_analysis,
        global_validation_audit=global_validation_audit,
    )

    print_deepseek_usage_summary()

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
