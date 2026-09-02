
from session_coaching import build_session_coaching_facts

from session_coaching_recurrence import (
    _apply_recurrence_aware_session_priority,
    _attach_point_anchored_reference_profiles,
    _attach_point_pattern_to_plan_item,
    _attach_repeated_throttle_patterns_to_plan,
    _brake_throttle_relation_from_channels,
    _channel_direction_coaching_label,
    _channel_quantitative_fact,
    _comparison_quality_map,
    _empty_repeated_point_plan_item,
    _point_anchored_profile,
    _point_pattern_reference_event_ids,
    _priority_ranking_map,
    _reference_lap_for_plan_item,
    _sanitize_recurrence_regions,
    _session_plan_sort_key,
    _standalone_repeated_point_candidates,
)

from session_coaching_intervals import (
    _finite_number,
    _merge_distance_intervals,
    _interval_total_length,
    _interval_intersection_length,
    _minimum_interval_gap,
    _plan_overlap_m,
    _same_plan_region,
    _channel_event_distance_intervals,
)

from session_coaching_location import (
    resolve_track_location,
    track_location_label,
    track_location_context_summary,
    enrich_items_with_track_location,
)

from session_coaching_plan import (
    _brake_release_target_text,
    _braking_point_target_text,
    _build_next_stint_plan,
    _format_aggregate_quantitative_observation,
    _format_region_brake_throttle_relation,
    _format_signed_metric,
    _format_single_brake_throttle_relation,
    _format_single_channel_quantitative_observation,
    _plan_item_has_actionable_coaching,
    _region_has_actionable_coaching,
    _single_fact_as_plan_pattern,
    _single_finding_plan_item,
    _throttle_onset_target_text,
    _throttle_release_target_text,
)

from session_coaching_priority import (
    _alpha_label,
    _finding_interval,
    _findings_share_spatial_region,
    _build_priority_regions,
)

from session_coaching_reference import (
    _attach_reference_action_profiles,
    _reference_brake_event_catalog,
    _reference_brake_level_label,
    _reference_brake_profile_for_region,
    _reference_brake_profile_target_text,
    _reference_lap_for_region,
    _reference_throttle_event_catalog,
    _reference_throttle_level_label,
    _reference_throttle_profile_for_region,
    _reference_throttle_profile_target_text,
)

from session_coaching_patterns import (
    _build_repeated_braking_point_patterns,
    _build_repeated_brake_release_patterns,
    _build_repeated_throttle_patterns,
)

from session_coaching_quality import (
    _comparison_quality_diagnostics,
    _confirm_statistical_comparison_outlier,
    _session_comparison_key,
    build_episode_catalog,
    build_session_comparison_quality_gate,
    classify_non_representative_time_loss,
    split_episode_catalog_for_coaching,
)

from deterministic_coaching import (
    safe_float,
    _aggregate_channel_quantitative_facts,
    _aggregate_region_brake_throttle_relation,
    _session_brake_release_fact,
    _session_braking_point_fact,
    _session_throttle_onset_fact,
    _session_throttle_release_fact,
    safe_int,
    normalize_grounding_text,
    _channels_mentioned_in_text,
    _explicit_command_direction_map,
    _explicit_directional_clauses,
    _steering_direct_action_present,
    build_driver_cues_for_plan_item,
    deterministic_priority_for_plan_item,
    build_deterministic_next_session_priorities,
)

from deterministic_coaching import (
    _channel_direction_phrase,
    _coaching_target_for_channel_direction,
    _direct_coaching_target_text,
    _driver_facing_throttle_profile_text,
    _episode_speed_context_facts,
    _plan_item_primary_driver_cue_channels,
    _render_speed_context_fact,
    _single_event_direction,
    _single_objective_channel_direction,
    build_deterministic_repeated_observations,
)

from deterministic_global_fallback import (
    build_deterministic_global_fallback,
    build_validated_deterministic_global_response,
)
from deterministic_text_validation import (
    text_contains_forbidden_numeric_content,
    text_contains_number_word,
)
from comparison_response_pipeline import build_validated_comparison_response
from deterministic_comparison_render import (
    comparison_actionable_focus as _comparison_actionable_focus,
    compose_episode_driver_cue_text as _compose_episode_driver_cue_text,
    assessment_map,
    episode_authorized_driver_cues as _episode_authorized_driver_cues,
    episode_spatial_facts,
    episode_validated_steering_cue as _episode_validated_steering_cue,
    format_channel_names,
    format_lap_time,
    meters,
    render_comparison_analysis as _render_comparison_analysis,
    render_hypotheses,
    signed_seconds,
)
from deterministic_debrief_document import (
    build_comparison_result,
    build_debrief_document,
    compatible_debrief_output_path,
    write_debrief_document,
)
from deterministic_debrief_finalize import finalize_validated_global_debrief
from deterministic_debrief_input import prepare_debrief_input
from deterministic_comparison_decision import resolve_comparison_response
from deterministic_comparison_preparation import (
    prepare_comparison,
    require_detected_episodes,
)
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

from runtime_paths import llm_debug_dir
from product_priority_ranker import build_product_priority_ranker_response
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


def deterministic_first_enabled(flag_name: str) -> bool:
    """D3: modo deterministic-first por default.

    RACE_ENGINEER_DETERMINISTIC_FIRST (default "1") habilita episodio, summary y
    global deterministas sin llamada LLM salvo que su flag específico sea "0".
    Con el master en "0", un flag específico "1" sigue habilitando sólo ese modo.
    """
    master = os.environ.get("RACE_ENGINEER_DETERMINISTIC_FIRST", "1") == "1"
    value = os.environ.get(flag_name)
    if value is None:
        return master
    return value == "1"


def llm_ranker_enabled() -> bool:
    """D2.9 cutover: ranker determinista por default.

    RACE_ENGINEER_LLM_RANKER=1 restaura el ranker LLM (rollback).
    """
    return os.environ.get("RACE_ENGINEER_LLM_RANKER", "0") == "1"


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










# ============================================================
# UTILIDADES
# ============================================================

def print_header(title):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)






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

    deterministic_first = deterministic_first_enabled(
        "RACE_ENGINEER_EPISODE_DETERMINISTIC"
    )
    if deterministic_first:
        deterministic_fallback = build_deterministic_grounded_episode_fallback(
            episode
        )
        if deterministic_fallback is not None:
            fallback_errors = validate_single_episode_llm_response(
                deterministic_fallback,
                episode,
            )
            if not fallback_errors:
                print(
                    f"    Episodio {episode_id}: modo deterministic-first "
                    "(default); sin llamada LLM."
                )
                return {
                    "status": "VALID",
                    "attempts": 0,
                    "response": deterministic_fallback,
                    "validation_errors": [],
                    "deterministic": True,
                    "deterministic_first": True,
                    "fallback": "DETERMINISTIC_GROUNDED_EPISODE_TEXT",
                }
        return {
            "status": "REJECTED",
            "attempts": 0,
            "response": None,
            "validation_errors": [
                "deterministic-first: el episodio es genuinamente interpretativo "
                "y Python no puede reconstruir el contrato de forma segura"
            ],
        }

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

        try:
            raw = deepseek_chat(
                EPISODE_SYSTEM_PROMPT,
                prompt,
            )
        except Exception as exc:
            errors = [f"transporte LLM falló: {exc}"]
            print(
                f"    Episodio {episode_id}: backend no disponible "
                f"(intento {attempt})."
            )
            continue
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

    grounded_fallback = build_deterministic_grounded_episode_fallback(episode)
    if grounded_fallback is not None:
        grounded_errors = validate_single_episode_llm_response(
            grounded_fallback,
            episode,
        )
        if not grounded_errors:
            print(
                f"    Episodio {episode_id}: fallback factual mínimo "
                "v3.10.8.5.4 aplicado tras backend no disponible."
            )
            return {
                "status": "VALID",
                "attempts": MAX_LLM_VALIDATION_ATTEMPTS,
                "response": grounded_fallback,
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

    if not llm_ranker_enabled():
        try:
            deterministic_response = (
                build_product_priority_ranker_response(episode_catalog)
            )
        except Exception as exc:
            return {
                "status": "REJECTED",
                "attempts": 0,
                "response": None,
                "validation_errors": [
                    f"Ranker determinista D2.9: {exc}"
                ],
            }
        deterministic_errors = validate_comparison_ranker_response(
            deterministic_response,
            episode_catalog,
        )
        if deterministic_errors:
            return {
                "status": "REJECTED",
                "attempts": 0,
                "response": None,
                "validation_errors": [
                    f"Ranker determinista D2.9: {error}"
                    for error in deterministic_errors
                ],
            }
        print(
            "    Ranker: modo determinista D2.9 (product policy); "
            "sin llamada LLM."
        )
        return {
            "status": "VALID",
            "attempts": 0,
            "response": deterministic_response,
            "validation_errors": [],
            "deterministic": True,
            "deterministic_first": True,
            "ranker_source": "D2_9_PRODUCT_POLICY",
        }

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

    deterministic_first = deterministic_first_enabled(
        "RACE_ENGINEER_SUMMARY_DETERMINISTIC"
    )
    if deterministic_first:
        deterministic_summary = build_deterministic_comparison_summary(
            episode_assessments,
            episode_catalog,
        )
        if deterministic_summary is None:
            return {
                "status": "REJECTED",
                "attempts": 0,
                "response": None,
                "validation_errors": [
                    "deterministic-first: no hay resumen determinista disponible"
                ],
            }
        print(
            "    Resumen: modo deterministic-first "
            "(default); sin llamada LLM."
        )
        return {
            "status": "VALID",
            "attempts": 0,
            "response": deterministic_summary,
            "validation_errors": [],
            "deterministic": True,
            "deterministic_first": True,
        }

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

        try:
            raw = deepseek_chat(
                COMPARISON_SUMMARY_SYSTEM_PROMPT,
                prompt,
            )
        except Exception as exc:
            errors = [f"transporte LLM falló: {exc}"]
            print(
                f"    Resumen: backend no disponible (intento {attempt})."
            )
            continue
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
    return build_validated_comparison_response(
        metadata,
        comparison,
        episode_catalog,
        output_dir,
        get_episode_response=get_validated_episode_response,
        get_ranker_response=get_validated_comparison_ranker_response,
        build_ranker_shadow=build_deterministic_ranker_shadow_audit,
        apply_classifications=apply_priority_classifications,
        get_summary_response=get_validated_comparison_summary_response,
        validate_response=validate_comparison_llm_response,
        derive_classifications=derive_priority_classifications,
    )


# ============================================================
# FORMATEO DETERMINISTA
# ============================================================

# ============================================================
# RENDER DE COMPARACIÓN
# ============================================================

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
    return _render_comparison_analysis(
        comparison,
        episode_catalog,
        structured_response,
    )


# ============================================================
# AGREGACIÓN DETERMINISTA DE COACHING DE SESIÓN v3.8.18
# ============================================================





















# ============================================================
# PERFIL DE ACCIÓN DE REFERENCIA v3.10.8
# ============================================================

REFERENCE_ACTION_PROFILE_VERSION = "1.1"
REFERENCE_THROTTLE_GAP_MIN_M = 8.0
REFERENCE_THROTTLE_BRIEF_APPLICATION_MAX_M = 20.0
REFERENCE_BRAKE_GAP_MIN_M = 8.0





























































BRAKING_POINT_SESSION_MIN_DELTA_M = 8.0
BRAKING_POINT_PATTERN_ONSET_TOLERANCE_M = 8.0
BRAKE_RELEASE_SESSION_MIN_DELTA_M = 8.0
BRAKE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M = 8.0







THROTTLE_ONSET_SESSION_MIN_DELTA_M = 8.0
THROTTLE_ONSET_PATTERN_REFERENCE_TOLERANCE_M = 12.0
THROTTLE_RELEASE_SESSION_MIN_DELTA_M = 8.0
THROTTLE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M = 12.0























# ============================================================
# PRIORIDAD DE SESIÓN POR RECURRENCIA v3.10.8
# ============================================================

SESSION_PRIORITY_POLICY_VERSION = "1.9"



















# ============================================================
# CALIDAD GLOBAL DE COMPARACIÓN v3.10.8
# ============================================================

SESSION_COMPARISON_QUALITY_GATE_VERSION = "1.1"
SESSION_COMPARISON_QUALITY_MIN_COUNT = 3
SESSION_COMPARISON_QUALITY_MAD_SIGMA_MULTIPLIER = 6.0
SESSION_COMPARISON_QUALITY_MIN_MARGIN_S = 1.0
SESSION_COMPARISON_QUALITY_RATIO_MULTIPLIER = 3.0






SESSION_COMPARISON_LOCAL_SEVERITY_SIGMA_MULTIPLIER = 8.0
SESSION_COMPARISON_LOCAL_SEVERITY_MIN_MARGIN_S = 1.0









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

    deterministic_first = deterministic_first_enabled(
        "RACE_ENGINEER_GLOBAL_DETERMINISTIC"
    )
    if deterministic_first:
        validated_response = build_validated_deterministic_global_response(
            session_coaching_facts,
            valid_comparison_results,
            validate_response=validate_global_llm_response,
            build_priorities=build_deterministic_next_session_priorities,
        )
        print(
            "Síntesis global: modo deterministic-first (default); "
            "sin llamada LLM."
        )
        return validated_response

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

        try:
            raw = deepseek_chat(
                GLOBAL_SYSTEM_PROMPT,
                prompt,
                temperature=0.0,
                seed=3815,
                format_schema=GLOBAL_RESPONSE_SCHEMA,
            )
        except Exception as exc:
            errors = [f"transporte LLM falló: {exc}"]
            print(
                f"Síntesis global: backend no disponible (intento {attempt})."
            )
            continue

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
    lines.append("## Resumen de la sesión")
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

    # ----------------------------------------------------------
    # Foco principal driver-facing.
    #
    # P11 es la autoridad de presentación cuando está disponible. El foco
    # determinista legacy queda únicamente como fallback para debriefs o
    # payloads anteriores que todavía no traigan P11.
    # ----------------------------------------------------------
    next_stint_focus = session_coaching_facts.get("next_stint_focus", {}) or {}
    focus_items = (
        next_stint_focus.get("items", []) or []
        if next_stint_focus.get("status") == "ACTIVE"
        else []
    )

    rendered_focus = False

    if focus_items:
        focus_lines = []

        for focus_item in focus_items[:2]:
            if not isinstance(focus_item, dict):
                continue

            label = str(focus_item.get("plan_label") or "").strip()
            location = track_location_label(focus_item)

            prefix = ""
            if label and location:
                prefix = f"Zona {label} — {location}: "
            elif label:
                prefix = f"Zona {label}: "
            elif location:
                prefix = f"{location}: "

            cues = [
                cue
                for cue in (focus_item.get("driver_cues", []) or [])
                if isinstance(cue, dict)
                and str(cue.get("text") or "").strip()
            ]

            if not cues:
                continue

            cue_text = "; ".join(
                str(cue.get("text") or "").strip()
                for cue in cues[:2]
            )

            if cue_text:
                focus_lines.append(f"- {prefix}{prose(cue_text)}")

        if focus_lines:
            lines.append("")
            lines.append("## Foco principal")
            lines.append("")
            lines.extend(focus_lines)
            rendered_focus = True

    if not rendered_focus:
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

    # Los objetivos físicos repetidos ya están presentados en el plan principal
    # o, si quedaron fuera del foco, en "Patrón repetido fuera del foco principal".
    # El respaldo técnico evita volver a enumerar las mismas acciones.
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
    output_path_value, output_dir_value = compatible_debrief_output_path(
        input_path,
        model_name=MODEL_NAME,
    )
    output_path = str(output_path_value)
    output_dir = str(output_dir_value)

    result = build_debrief_document(
        input_path=input_path,
        metadata=metadata,
        comparison_results=comparison_results,
        session_coaching_facts=session_coaching_facts,
        global_structured=global_structured,
        global_analysis=global_analysis,
        global_validation_audit=global_validation_audit,
        analysis_timestamp=datetime.now(timezone.utc).isoformat(),
        model_name=MODEL_NAME,
        usage_summary=deepseek_usage_summary(),
        context_size=CONTEXT_SIZE,
        temperature=TEMPERATURE,
        anomaly_gate_config=ANOMALY_GATE_CONFIG,
    )
    write_debrief_document(output_path, result)

    return (
        output_path,
        output_dir,
    )


# ============================================================
# MAIN
# ============================================================

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    reset_deepseek_usage()

    print_header(
        "RACE ENGINEER - LLM ANALYSIS v3.10.8.5.4 / DeepSeek provisional v2"
    )

    input_path = find_json_file()

    prepared_input = prepare_debrief_input(
        input_path,
        load_json=load_json,
        validate_data_model=validate_data_model,
        validate_lap_times=validate_lap_times,
        build_dataset=build_llm_dataset,
        load_track_location_context=load_track_location_context,
    )
    data = prepared_input.source_data
    metadata = prepared_input.metadata
    comparisons = prepared_input.comparisons
    track_location_context = prepared_input.track_location_context

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
        prepared_comparison = prepare_comparison(
            comparison,
            comparison_quality=pre_session_quality_by_key.get(comparison_key, {}),
            track_location_context=track_location_context,
            build_episode_catalog=build_episode_catalog,
            enrich_track_location=enrich_items_with_track_location,
            split_for_coaching=split_episode_catalog_for_coaching,
        )
        comparison_quality = prepared_comparison.comparison_quality
        session_plan_eligible = prepared_comparison.session_plan_eligible
        detected_episode_catalog = prepared_comparison.detected_episode_catalog
        episode_catalog = prepared_comparison.episode_catalog
        excluded_anomalies = prepared_comparison.excluded_anomalies

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

        require_detected_episodes(comparison, detected_episode_catalog)

        print()

        if not session_plan_eligible:
            print(
                "Comparación excluida por el gate global de calidad; se conserva el ground truth "
                "pero no se llama al LLM ni al ranker."
            )
        elif episode_catalog:
            print(
                "Solicitando interpretación aislada + ranking comparativo v3.10.8.5.4..."
            )
        else:
            print(
                "Todos los episodios fueron excluidos por el gate de anomalías; "
                "no se llama al LLM ni al ranker para esta comparación."
            )

        validated, _comparison_route = resolve_comparison_response(
            session_plan_eligible=session_plan_eligible,
            episode_catalog=episode_catalog,
            eligible_response=lambda: get_validated_comparison_response(
                metadata,
                comparison,
                episode_catalog,
                output_dir,
            ),
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

        comparison_result = build_comparison_result(
            comparison=comparison,
            comparison_quality=comparison_quality,
            session_plan_eligible=session_plan_eligible,
            detected_episode_catalog=detected_episode_catalog,
            episode_catalog=episode_catalog,
            excluded_anomalies=excluded_anomalies,
            validated=validated,
            rendered=rendered,
        )

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

    (
        global_structured,
        global_validation_audit,
        global_analysis,
    ) = finalize_validated_global_debrief(
        global_validated=global_validated,
        metadata=metadata,
        comparison_results=comparison_results,
        session_coaching_facts=session_coaching_facts,
        track_location_context=track_location_context,
        render_global=render_global_analysis,
        render_track_reference=render_track_reference_section,
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
