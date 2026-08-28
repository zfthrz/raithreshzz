import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

import duckdb

from runtime_paths import local_root


# ============================================================
# RACE ENGINEER - SESSION HISTORY v1.4
# ============================================================
#
# Historial persistente de sesiones analizadas por
# analyze_telemetry.py v3.8+.
#
# NO llama a Ollama.
# NO modifica los JSON fuente.
# NO recalcula matching entre sesiones.
# Persiste pattern runs H3 ya decididos por Python.
#
# Funciones actuales:
#
#   init
#       crea/actualiza el esquema DuckDB
#
#   import
#       importa un JSON analyze_telemetry v3.8+
#       de forma idempotente
#
#   import-dir
#       importa una carpeta de JSON de forma idempotente
#
#   list
#       lista sesiones importadas
#
#   stats
#       resume contenido por circuito
#
#   inspect
#       resume una sesión importada
#
# Ejemplos:
#
#   python session_history.py init
#
#   python session_history.py import "Monza.json"
#
#   python session_history.py list
#
#   python session_history.py inspect 1
#
# ============================================================


HISTORY_DB_NAME = "race_engineer_history.duckdb"

SCHEMA_VERSION = 4

MIN_SUPPORTED_ANALYSIS_VERSION = (3, 8)

PRIMARY_INTERPRETATION_UNIT = "driver_action_episode"


# ============================================================
# UTILIDADES
# ============================================================

def safe_int(value):
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def parse_version(value):
    """
    "3.8" -> (3, 8)
    "3.8.1" -> (3, 8, 1)
    """
    if value is None:
        return tuple()

    parts = []

    for raw in str(value).split("."):
        digits = "".join(
            ch
            for ch in raw
            if ch.isdigit()
        )

        if not digits:
            break

        parts.append(
            int(digits)
        )

    return tuple(parts)


def version_at_least(
    current,
    minimum,
):
    current = parse_version(
        current
    )

    if not current:
        return False

    length = max(
        len(current),
        len(minimum),
    )

    current = current + (0,) * (
        length - len(current)
    )

    minimum = tuple(minimum) + (0,) * (
        length - len(minimum)
    )

    return current >= minimum


def json_text(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def utc_now_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


def normalized_path(path):
    return os.path.normcase(
        os.path.abspath(
            path
        )
    )


def file_sha256(path):
    sha = hashlib.sha256()

    with open(
        path,
        "rb",
    ) as file:
        while True:
            chunk = file.read(
                1024 * 1024
            )

            if not chunk:
                break

            sha.update(
                chunk
            )

    return sha.hexdigest()


def base_dir():
    return os.path.dirname(
        os.path.abspath(
            __file__
        )
    )


def default_db_path():
    return os.path.join(
        str(local_root()),
        HISTORY_DB_NAME,
    )


# ============================================================
# CARGA Y VALIDACIÓN DEL JSON
# ============================================================

def load_analysis_json(path):
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            "La raíz del JSON debe ser un objeto."
        )

    return data


def validate_analysis_json(data):
    metadata = data.get(
        "metadata"
    )

    comparisons = data.get(
        "comparisons"
    )

    laps = data.get(
        "laps"
    )

    if not isinstance(
        metadata,
        dict,
    ):
        raise ValueError(
            "metadata ausente o inválida."
        )

    if not isinstance(
        comparisons,
        list,
    ):
        raise ValueError(
            "comparisons ausente o inválida."
        )

    if not isinstance(
        laps,
        list,
    ):
        raise ValueError(
            "laps ausente o inválida."
        )

    analysis_version = metadata.get(
        "analysis_version"
    )

    if not version_at_least(
        analysis_version,
        MIN_SUPPORTED_ANALYSIS_VERSION,
    ):
        raise ValueError(
            "session_history v1.4 requiere "
            "analyze_telemetry v3.8+."
        )

    if metadata.get(
        "same_vehicle"
    ) is not True:
        raise ValueError(
            "El JSON no confirma same_vehicle=true."
        )

    if (
        metadata.get(
            "lap_comparison_model"
        )
        !=
        "same_vehicle_different_laps"
    ):
        raise ValueError(
            "lap_comparison_model inesperado."
        )

    temporal_status = metadata.get(
        "temporal_validation_status"
    )

    objective_status = metadata.get(
        "objective_analysis_validation"
    )

    if temporal_status not in (
        None,
        "OK",
    ):
        raise ValueError(
            f"temporal_validation_status={temporal_status}"
        )

    if objective_status not in (
        None,
        "OK",
    ):
        raise ValueError(
            f"objective_analysis_validation={objective_status}"
        )

    return (
        metadata,
        laps,
        comparisons,
    )


# ============================================================
# ESQUEMA
# ============================================================

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS history_meta (
    schema_version INTEGER NOT NULL,
    created_at_utc VARCHAR NOT NULL,
    updated_at_utc VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id BIGINT PRIMARY KEY,
    source_json_path VARCHAR NOT NULL,
    source_json_sha256 VARCHAR NOT NULL UNIQUE,
    source_database_path VARCHAR,
    source_analysis_version VARCHAR NOT NULL,

    track VARCHAR,
    session_type VARCHAR,
    timestamp_utc VARCHAR,

    vehicle_family VARCHAR,
    vehicle_variant VARCHAR,
    car_class_raw VARCHAR,
    car_name_raw VARCHAR,
    vehicle_identity_source VARCHAR,
    vehicle_supported_domain BOOLEAN,

    weather_conditions VARCHAR,
    setup_sha256 VARCHAR,
    setup_raw_sha256 VARCHAR,
    setup_available BOOLEAN,
    lmu_session_type VARCHAR,
    lmu_track_name VARCHAR,
    lmu_track_layout VARCHAR,

    same_vehicle BOOLEAN NOT NULL,
    vehicle_count INTEGER,
    lap_comparison_model VARCHAR,

    reference_lap INTEGER,
    reference_distance_m DOUBLE,

    temporal_validation_status VARCHAR,
    objective_analysis_validation VARCHAR,

    valid_lap_count INTEGER,
    discarded_lap_count INTEGER,
    comparison_count INTEGER,

    imported_at_utc VARCHAR NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS sessions_seq START 1;

CREATE TABLE IF NOT EXISTS laps (
    session_id BIGINT NOT NULL,
    lap INTEGER NOT NULL,

    start_time_s DOUBLE,
    end_time_s DOUBLE,
    duration_s DOUBLE,
    samples BIGINT,

    max_rpm DOUBLE,
    max_speed_kmh DOUBLE,
    avg_throttle_percent DOUBLE,
    max_throttle_percent DOUBLE,
    max_brake_percent DOUBLE,
    max_steering DOUBLE,
    lap_distance_m DOUBLE,

    is_valid BOOLEAN,
    is_discarded BOOLEAN,
    is_ignored_initial BOOLEAN,
    is_reference BOOLEAN,

    PRIMARY KEY (
        session_id,
        lap
    )
);

CREATE TABLE IF NOT EXISTS comparisons (
    comparison_id BIGINT PRIMARY KEY,
    session_id BIGINT NOT NULL,

    reference_lap INTEGER NOT NULL,
    comparison_lap INTEGER NOT NULL,

    reference_time_s DOUBLE,
    comparison_time_s DOUBLE,
    comparison_minus_reference_s DOUBLE,
    calculated_delta_s DOUBLE,

    distance_m DOUBLE,

    driver_analysis_priority_rank INTEGER,
    recommended_for_driver_analysis BOOLEAN,

    temporal_validation_status VARCHAR,
    temporal_validation_json VARCHAR,

    objective_priority VARCHAR,
    primary_interpretation_unit VARCHAR,

    gross_loss_s DOUBLE,
    gross_gain_s DOUBLE,
    neutral_delta_s DOUBLE,
    net_from_components_s DOUBLE,
    accounting_error_s DOUBLE,

    UNIQUE (
        session_id,
        reference_lap,
        comparison_lap
    )
);

CREATE SEQUENCE IF NOT EXISTS comparisons_seq START 1;

CREATE TABLE IF NOT EXISTS episodes (
    episode_pk BIGINT PRIMARY KEY,
    comparison_id BIGINT NOT NULL,
    session_id BIGINT NOT NULL,

    episode_id INTEGER NOT NULL,
    python_global_rank INTEGER,
    zone_id INTEGER,
    parent_zone_rank INTEGER,

    start_distance_m DOUBLE,
    end_distance_m DOUBLE,
    center_distance_m DOUBLE,
    length_m DOUBLE,

    start_lap_fraction DOUBLE,
    end_lap_fraction DOUBLE,
    center_lap_fraction DOUBLE,

    delta_start_s DOUBLE,
    delta_end_s DOUBLE,
    action_time_loss_s DOUBLE,

    parent_zone_delta_loss_s DOUBLE,
    parent_zone_net_loss_equivalent_percent DOUBLE,

    evidence_strength VARCHAR,
    action_channel_count INTEGER,

    has_speed_propagation BOOLEAN,
    supporting_loss_cluster_count INTEGER,

    interpretation_json VARCHAR,

    UNIQUE (
        comparison_id,
        episode_id
    )
);

CREATE SEQUENCE IF NOT EXISTS episodes_seq START 1;

CREATE TABLE IF NOT EXISTS episode_channels (
    episode_channel_pk BIGINT PRIMARY KEY,
    episode_pk BIGINT NOT NULL,
    comparison_id BIGINT NOT NULL,
    session_id BIGINT NOT NULL,

    channel VARCHAR NOT NULL,

    event_count INTEGER,
    supported_length_m DOUBLE,

    episode_coverage_ratio DOUBLE,

    first_event_start_distance_m DOUBLE,
    last_event_end_distance_m DOUBLE,

    onset_offset_m DOUBLE,
    end_offset_m DOUBLE,

    mean_of_event_mean_differences DOUBLE,
    largest_abs_peak_difference DOUBLE,

    direction_consistency VARCHAR,

    raw_events_json VARCHAR,

    UNIQUE (
        episode_pk,
        channel
    )
);

CREATE SEQUENCE IF NOT EXISTS episode_channels_seq START 1;

CREATE TABLE IF NOT EXISTS speed_propagations (
    speed_propagation_pk BIGINT PRIMARY KEY,
    episode_pk BIGINT NOT NULL,
    comparison_id BIGINT NOT NULL,
    session_id BIGINT NOT NULL,

    propagation_index INTEGER NOT NULL,

    start_distance_m DOUBLE,
    end_distance_m DOUBLE,
    center_distance_m DOUBLE,
    length_m DOUBLE,

    start_lap_fraction DOUBLE,
    end_lap_fraction DOUBLE,
    center_lap_fraction DOUBLE,

    delta_start_s DOUBLE,
    delta_end_s DOUBLE,
    propagated_time_delta_change_s DOUBLE,

    raw_json VARCHAR,

    UNIQUE (
        episode_pk,
        propagation_index
    )
);

CREATE SEQUENCE IF NOT EXISTS speed_propagations_seq START 1;

CREATE TABLE IF NOT EXISTS import_log (
    import_id BIGINT PRIMARY KEY,
    source_json_path VARCHAR,
    source_json_sha256 VARCHAR,
    session_id BIGINT,
    status VARCHAR NOT NULL,
    message VARCHAR,
    imported_at_utc VARCHAR NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS import_log_seq START 1;

CREATE INDEX IF NOT EXISTS idx_sessions_track
ON sessions(track);

CREATE INDEX IF NOT EXISTS idx_sessions_timestamp
ON sessions(timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_comparisons_session
ON comparisons(session_id);

CREATE INDEX IF NOT EXISTS idx_episodes_session
ON episodes(session_id);

CREATE INDEX IF NOT EXISTS idx_episodes_comparison
ON episodes(comparison_id);

CREATE INDEX IF NOT EXISTS idx_episodes_center_fraction
ON episodes(center_lap_fraction);

CREATE INDEX IF NOT EXISTS idx_episode_channels_channel
ON episode_channels(channel);

CREATE TABLE IF NOT EXISTS pattern_runs (
    pattern_run_id BIGINT PRIMARY KEY,
    source_patterns_path VARCHAR NOT NULL,
    source_patterns_sha256 VARCHAR NOT NULL,
    source_matches_path VARCHAR NOT NULL,
    source_matches_sha256 VARCHAR NOT NULL,
    source_bundle_sha256 VARCHAR NOT NULL UNIQUE,

    h3_version VARCHAR NOT NULL,
    pattern_schema_version VARCHAR,
    matcher_version VARCHAR NOT NULL,
    matcher_status VARCHAR,
    persistent_min_independent_sessions INTEGER NOT NULL,

    track VARCHAR,
    track_layout VARCHAR,
    vehicle_variant VARCHAR,

    pattern_count INTEGER NOT NULL,
    episode_count INTEGER NOT NULL,
    single_observation_count INTEGER NOT NULL,
    cross_session_repeat_count INTEGER NOT NULL,
    persistent_pattern_count INTEGER NOT NULL,
    conflict_review_required_count INTEGER NOT NULL,
    match_edge_count INTEGER NOT NULL,
    transitively_resolved_ambiguous_pair_count INTEGER NOT NULL,

    source_created_at_utc VARCHAR,
    imported_at_utc VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS pattern_runs_seq START 1;

CREATE TABLE IF NOT EXISTS persistent_patterns (
    pattern_pk BIGINT PRIMARY KEY,
    pattern_run_id BIGINT NOT NULL,
    pattern_id VARCHAR NOT NULL,
    state VARCHAR NOT NULL,

    track VARCHAR NOT NULL,
    track_layout VARCHAR NOT NULL,
    vehicle_variant VARCHAR NOT NULL,

    observation_count INTEGER NOT NULL,
    independent_session_count INTEGER NOT NULL,

    representative_session_id BIGINT,
    representative_episode_pk BIGINT,

    center_median_m DOUBLE,
    center_min_m DOUBLE,
    center_max_m DOUBLE,
    center_spread_m DOUBLE,
    start_median_m DOUBLE,
    end_median_m DOUBLE,

    action_time_loss_median_s DOUBLE,
    action_time_loss_min_s DOUBLE,
    action_time_loss_max_s DOUBLE,

    direct_match_edge_count INTEGER NOT NULL,
    internal_ambiguous_pair_count INTEGER NOT NULL,
    internal_reject_pair_count INTEGER NOT NULL,
    possible_cross_session_pair_count INTEGER NOT NULL,
    observed_internal_cross_session_pair_count INTEGER NOT NULL,
    missing_internal_cross_session_pair_count INTEGER NOT NULL,
    transitively_resolved_ambiguous_pair_count INTEGER NOT NULL,

    common_action_channels_json VARCHAR NOT NULL,
    union_action_channels_json VARCHAR NOT NULL,
    session_ids_json VARCHAR NOT NULL,
    raw_pattern_json VARCHAR NOT NULL,

    UNIQUE (pattern_run_id, pattern_id)
);

CREATE SEQUENCE IF NOT EXISTS persistent_patterns_seq START 1;

CREATE TABLE IF NOT EXISTS persistent_pattern_members (
    pattern_member_pk BIGINT PRIMARY KEY,
    pattern_pk BIGINT NOT NULL,
    pattern_run_id BIGINT NOT NULL,
    pattern_id VARCHAR NOT NULL,

    session_id BIGINT NOT NULL,
    episode_pk BIGINT NOT NULL,
    episode_id INTEGER,

    timestamp_utc VARCHAR,
    session_type VARCHAR,
    start_distance_m DOUBLE,
    end_distance_m DOUBLE,
    center_distance_m DOUBLE,
    action_time_loss_s DOUBLE,
    channels_json VARCHAR NOT NULL,

    UNIQUE (pattern_pk, session_id, episode_pk)
);

CREATE SEQUENCE IF NOT EXISTS persistent_pattern_members_seq START 1;

CREATE TABLE IF NOT EXISTS persistent_pattern_pair_evidence (
    pattern_pair_evidence_pk BIGINT PRIMARY KEY,
    pattern_pk BIGINT NOT NULL,
    pattern_run_id BIGINT NOT NULL,
    pattern_id VARCHAR NOT NULL,

    pair_index INTEGER NOT NULL,
    pair_id VARCHAR,
    decision VARCHAR NOT NULL,
    rule_id VARCHAR,
    automatic BOOLEAN,

    session_a BIGINT NOT NULL,
    episode_pk_a BIGINT NOT NULL,
    session_b BIGINT NOT NULL,
    episode_pk_b BIGINT NOT NULL,

    raw_decision_json VARCHAR NOT NULL,

    UNIQUE (pattern_run_id, pair_index)
);

CREATE SEQUENCE IF NOT EXISTS persistent_pattern_pair_evidence_seq START 1;

CREATE INDEX IF NOT EXISTS idx_pattern_runs_context
ON pattern_runs(track, track_layout, vehicle_variant);

CREATE INDEX IF NOT EXISTS idx_persistent_patterns_run
ON persistent_patterns(pattern_run_id);

CREATE INDEX IF NOT EXISTS idx_persistent_patterns_context_state
ON persistent_patterns(track, track_layout, vehicle_variant, state);

CREATE INDEX IF NOT EXISTS idx_pattern_members_episode
ON persistent_pattern_members(episode_pk);

CREATE INDEX IF NOT EXISTS idx_pattern_pair_evidence_run
ON persistent_pattern_pair_evidence(pattern_run_id);

"""


VEHICLE_CONTEXT_COLUMNS = {
    "vehicle_family": "VARCHAR",
    "vehicle_variant": "VARCHAR",
    "car_class_raw": "VARCHAR",
    "car_name_raw": "VARCHAR",
    "vehicle_identity_source": "VARCHAR",
    "vehicle_supported_domain": "BOOLEAN",
    "weather_conditions": "VARCHAR",
    "setup_sha256": "VARCHAR",
    "setup_raw_sha256": "VARCHAR",
    "setup_available": "BOOLEAN",
    "lmu_session_type": "VARCHAR",
    "lmu_track_name": "VARCHAR",
    "lmu_track_layout": "VARCHAR",
}


def session_column_names(connection):
    rows = connection.execute(
        "DESCRIBE sessions"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _ensure_session_context_columns(connection):
    columns = session_column_names(connection)

    for name, data_type in VEHICLE_CONTEXT_COLUMNS.items():
        if name in columns:
            continue

        connection.execute(
            f"ALTER TABLE sessions ADD COLUMN {name} {data_type}"
        )


def migrate_schema_v1_to_v2(connection):
    _ensure_session_context_columns(connection)

    connection.execute(
        """
        UPDATE history_meta
        SET schema_version = 2,
            updated_at_utc = ?
        """,
        [utc_now_iso()],
    )


def migrate_schema_v2_to_v3(connection):
    # v3 persiste identidad de layout explícita para que el matcher
    # cross-session no mezcle layouts que compartan nombre de circuito.
    _ensure_session_context_columns(connection)

    connection.execute(
        """
        UPDATE history_meta
        SET schema_version = 3,
            updated_at_utc = ?
        """,
        [utc_now_iso()],
    )





def migrate_schema_v3_to_v4(connection):
    # v4 agrega una capa H3 derivada y versionada. No modifica episodios fuente.
    # SCHEMA_SQL ya creó las tablas nuevas con IF NOT EXISTS.
    connection.execute(
        """
        UPDATE history_meta
        SET schema_version = 4,
            updated_at_utc = ?
        """,
        [utc_now_iso()],
    )


def ensure_vehicle_context_indexes(connection):
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_vehicle_context
        ON sessions(track, lmu_track_layout, vehicle_variant)
        """
    )


def initialize_schema(
    connection,
):
    connection.execute(
        SCHEMA_SQL
    )

    rows = connection.execute(
        """
        SELECT
            schema_version
        FROM history_meta
        LIMIT 1
        """
    ).fetchall()

    now = utc_now_iso()

    if not rows:
        connection.execute(
            """
            INSERT INTO history_meta (
                schema_version,
                created_at_utc,
                updated_at_utc
            )
            VALUES (?, ?, ?)
            """,
            [
                SCHEMA_VERSION,
                now,
                now,
            ],
        )
    else:
        current_version = safe_int(
            rows[0][0]
        )

        if current_version == 1:
            migrate_schema_v1_to_v2(
                connection
            )
            current_version = 2

        if current_version == 2:
            migrate_schema_v2_to_v3(
                connection
            )
            current_version = 3

        if current_version == 3:
            migrate_schema_v3_to_v4(
                connection
            )
            current_version = 4

        if current_version != SCHEMA_VERSION:
            raise RuntimeError(
                "Versión de esquema incompatible: "
                f"DB={current_version}, "
                f"script={SCHEMA_VERSION}"
            )

        connection.execute(
            """
            UPDATE history_meta
            SET updated_at_utc = ?
            """,
            [
                now
            ],
        )

    ensure_vehicle_context_indexes(
        connection
    )


# ============================================================
# HELPERS DE EXTRACCIÓN
# ============================================================

def set_of_ints(value):
    if not isinstance(
        value,
        list,
    ):
        return set()

    result = set()

    for item in value:
        parsed = safe_int(
            item
        )

        if parsed is not None:
            result.add(
                parsed
            )

    return result


def comparison_episode_list(
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
        return []

    episodes = objective.get(
        "driver_action_episode_ranking"
    )

    if not isinstance(
        episodes,
        list,
    ):
        return []

    return [
        episode
        for episode in episodes
        if isinstance(
            episode,
            dict,
        )
    ]


def normalized_speed_propagations(
    episode,
):
    value = episode.get(
        "speed_propagation"
    )

    if value is None:
        return []

    if isinstance(
        value,
        dict,
    ):
        return [
            value
        ]

    if isinstance(
        value,
        list,
    ):
        return [
            item
            for item in value
            if isinstance(
                item,
                dict,
            )
        ]

    return []


def compute_center(
    start,
    end,
):
    start = safe_float(
        start
    )

    end = safe_float(
        end
    )

    if (
        start is None
        or
        end is None
    ):
        return None

    return (
        start + end
    ) / 2.0


def lap_fraction(
    distance,
    reference_distance,
):
    distance = safe_float(
        distance
    )

    reference_distance = safe_float(
        reference_distance
    )

    if (
        distance is None
        or
        reference_distance is None
        or
        reference_distance <= 0
    ):
        return None

    return (
        distance
        /
        reference_distance
    )


def event_bounds(
    events,
):
    if not isinstance(
        events,
        list,
    ):
        return (
            None,
            None,
        )

    starts = []
    ends = []

    for event in events:
        if not isinstance(
            event,
            dict,
        ):
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

        if start is not None:
            starts.append(
                start
            )

        if end is not None:
            ends.append(
                end
            )

    return (
        min(starts)
        if starts
        else None,

        max(ends)
        if ends
        else None,
    )


def direction_consistency(
    events,
):
    if not isinstance(
        events,
        list,
    ):
        return None

    directions = {
        str(
            event.get(
                "direction"
            )
        )
        for event in events
        if isinstance(
            event,
            dict,
        )
        and
        event.get(
            "direction"
        )
        is not None
    }

    if not directions:
        return None

    if len(
        directions
    ) == 1:
        return "consistent"

    return "mixed"


# ============================================================
# IMPORTACIÓN
# ============================================================

def find_existing_session(
    connection,
    source_hash,
):
    row = connection.execute(
        """
        SELECT
            session_id
        FROM sessions
        WHERE source_json_sha256 = ?
        """,
        [
            source_hash
        ],
    ).fetchone()

    if row is None:
        return None

    return safe_int(
        row[0]
    )


def log_import(
    connection,
    path,
    source_hash,
    session_id,
    status,
    message,
):
    connection.execute(
        """
        INSERT INTO import_log (
            import_id,
            source_json_path,
            source_json_sha256,
            session_id,
            status,
            message,
            imported_at_utc
        )
        VALUES (
            nextval('import_log_seq'),
            ?, ?, ?, ?, ?, ?
        )
        """,
        [
            path,
            source_hash,
            session_id,
            status,
            message,
            utc_now_iso(),
        ],
    )


def extract_vehicle_session_context(metadata):
    vehicle = metadata.get(
        "vehicle_identity",
        {},
    )
    context = metadata.get(
        "session_context",
        {},
    )

    if not isinstance(vehicle, dict):
        vehicle = {}

    if not isinstance(context, dict):
        context = {}

    return {
        "vehicle_family": vehicle.get("family"),
        "vehicle_variant": vehicle.get("variant"),
        "car_class_raw": vehicle.get("car_class_raw"),
        "car_name_raw": vehicle.get("car_name_raw"),
        "vehicle_identity_source": vehicle.get("identity_source"),
        "vehicle_supported_domain": (
            bool(vehicle.get("supported_domain"))
            if vehicle.get("supported_domain") is not None
            else None
        ),
        "weather_conditions": context.get("weather_conditions"),
        "setup_sha256": context.get("setup_sha256"),
        "setup_raw_sha256": context.get("setup_raw_sha256"),
        "setup_available": (
            bool(context.get("setup_available"))
            if context.get("setup_available") is not None
            else None
        ),
        "lmu_session_type": context.get("lmu_session_type"),
        "lmu_track_name": context.get("lmu_track_name"),
        "lmu_track_layout": context.get("lmu_track_layout"),
    }


def refresh_missing_session_context(
    connection,
    session_id,
    metadata,
):
    """
    Completa sólo contexto persistente que quedó NULL en imports legacy.

    No modifica laps/comparisons/episodes ni sobreescribe valores existentes.
    Esto permite que un import idempotente refresque lmu_track_layout después
    de migrar schema v2 -> v3.
    """
    context = extract_vehicle_session_context(
        metadata
    )

    connection.execute(
        """
        UPDATE sessions
        SET
            vehicle_family = COALESCE(vehicle_family, ?),
            vehicle_variant = COALESCE(vehicle_variant, ?),
            car_class_raw = COALESCE(car_class_raw, ?),
            car_name_raw = COALESCE(car_name_raw, ?),
            vehicle_identity_source = COALESCE(vehicle_identity_source, ?),
            vehicle_supported_domain = COALESCE(vehicle_supported_domain, ?),
            weather_conditions = COALESCE(weather_conditions, ?),
            setup_sha256 = COALESCE(setup_sha256, ?),
            setup_raw_sha256 = COALESCE(setup_raw_sha256, ?),
            setup_available = COALESCE(setup_available, ?),
            lmu_session_type = COALESCE(lmu_session_type, ?),
            lmu_track_name = COALESCE(lmu_track_name, ?),
            lmu_track_layout = COALESCE(lmu_track_layout, ?)
        WHERE session_id = ?
        """,
        [
            context["vehicle_family"],
            context["vehicle_variant"],
            context["car_class_raw"],
            context["car_name_raw"],
            context["vehicle_identity_source"],
            context["vehicle_supported_domain"],
            context["weather_conditions"],
            context["setup_sha256"],
            context["setup_raw_sha256"],
            context["setup_available"],
            context["lmu_session_type"],
            context["lmu_track_name"],
            context["lmu_track_layout"],
            session_id,
        ],
    )

    return context


def insert_session(
    connection,
    source_path,
    source_hash,
    metadata,
    laps,
    comparisons,
):
    session_context = extract_vehicle_session_context(
        metadata
    )

    valid_laps = set_of_ints(
        metadata.get(
            "valid_laps"
        )
    )

    discarded_laps = set_of_ints(
        metadata.get(
            "discarded_laps"
        )
    )

    session_id = connection.execute(
        """
        SELECT
            nextval('sessions_seq')
        """
    ).fetchone()[0]

    connection.execute(
        """
        INSERT INTO sessions (
            session_id,
            source_json_path,
            source_json_sha256,
            source_database_path,
            source_analysis_version,
            track,
            session_type,
            timestamp_utc,
            vehicle_family,
            vehicle_variant,
            car_class_raw,
            car_name_raw,
            vehicle_identity_source,
            vehicle_supported_domain,
            weather_conditions,
            setup_sha256,
            setup_raw_sha256,
            setup_available,
            lmu_session_type,
            lmu_track_name,
            lmu_track_layout,
            same_vehicle,
            vehicle_count,
            lap_comparison_model,
            reference_lap,
            reference_distance_m,
            temporal_validation_status,
            objective_analysis_validation,
            valid_lap_count,
            discarded_lap_count,
            comparison_count,
            imported_at_utc
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            session_id,
            source_path,
            source_hash,
            metadata.get(
                "database"
            ),
            str(
                metadata.get(
                    "analysis_version"
                )
            ),
            metadata.get(
                "track"
            ),
            metadata.get(
                "session_type"
            ),
            metadata.get(
                "timestamp_utc"
            ),
            session_context["vehicle_family"],
            session_context["vehicle_variant"],
            session_context["car_class_raw"],
            session_context["car_name_raw"],
            session_context["vehicle_identity_source"],
            session_context["vehicle_supported_domain"],
            session_context["weather_conditions"],
            session_context["setup_sha256"],
            session_context["setup_raw_sha256"],
            session_context["setup_available"],
            session_context["lmu_session_type"],
            session_context["lmu_track_name"],
            session_context["lmu_track_layout"],
            bool(
                metadata.get(
                    "same_vehicle"
                )
            ),
            safe_int(
                metadata.get(
                    "vehicle_count"
                )
            ),
            metadata.get(
                "lap_comparison_model"
            ),
            safe_int(
                metadata.get(
                    "reference_lap"
                )
            ),
            safe_float(
                metadata.get(
                    "reference_distance_m"
                )
            ),
            metadata.get(
                "temporal_validation_status"
            ),
            metadata.get(
                "objective_analysis_validation"
            ),
            len(
                valid_laps
            ),
            len(
                discarded_laps
            ),
            len(
                comparisons
            ),
            utc_now_iso(),
        ],
    )

    return safe_int(
        session_id
    )


def insert_laps(
    connection,
    session_id,
    metadata,
    laps,
):
    valid_laps = set_of_ints(
        metadata.get(
            "valid_laps"
        )
    )

    discarded_laps = set_of_ints(
        metadata.get(
            "discarded_laps"
        )
    )

    ignored_laps = set_of_ints(
        metadata.get(
            "ignored_initial_laps"
        )
    )

    reference_lap = safe_int(
        metadata.get(
            "reference_lap"
        )
    )

    for lap_record in laps:
        if not isinstance(
            lap_record,
            dict,
        ):
            continue

        lap = safe_int(
            lap_record.get(
                "lap"
            )
        )

        if lap is None:
            continue

        connection.execute(
            """
            INSERT INTO laps (
                session_id,
                lap,
                start_time_s,
                end_time_s,
                duration_s,
                samples,
                max_rpm,
                max_speed_kmh,
                avg_throttle_percent,
                max_throttle_percent,
                max_brake_percent,
                max_steering,
                lap_distance_m,
                is_valid,
                is_discarded,
                is_ignored_initial,
                is_reference
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            [
                session_id,
                lap,
                safe_float(
                    lap_record.get(
                        "start_time"
                    )
                ),
                safe_float(
                    lap_record.get(
                        "end_time"
                    )
                ),
                safe_float(
                    lap_record.get(
                        "duration"
                    )
                ),
                safe_int(
                    lap_record.get(
                        "samples"
                    )
                ),
                safe_float(
                    lap_record.get(
                        "max_rpm"
                    )
                ),
                safe_float(
                    lap_record.get(
                        "max_speed"
                    )
                ),
                safe_float(
                    lap_record.get(
                        "avg_throttle"
                    )
                ),
                safe_float(
                    lap_record.get(
                        "max_throttle"
                    )
                ),
                safe_float(
                    lap_record.get(
                        "max_brake"
                    )
                ),
                safe_float(
                    lap_record.get(
                        "max_steering"
                    )
                ),
                safe_float(
                    lap_record.get(
                        "lap_distance"
                    )
                ),
                lap in valid_laps,
                lap in discarded_laps,
                lap in ignored_laps,
                lap == reference_lap,
            ],
        )


def insert_comparison(
    connection,
    session_id,
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

    accounting = objective.get(
        "time_accounting",
        {},
    )

    if not isinstance(
        accounting,
        dict,
    ):
        accounting = {}

    temporal = comparison.get(
        "temporal_validation",
        {},
    )

    if not isinstance(
        temporal,
        dict,
    ):
        temporal = {}

    comparison_id = connection.execute(
        """
        SELECT
            nextval('comparisons_seq')
        """
    ).fetchone()[0]

    connection.execute(
        """
        INSERT INTO comparisons (
            comparison_id,
            session_id,
            reference_lap,
            comparison_lap,
            reference_time_s,
            comparison_time_s,
            comparison_minus_reference_s,
            calculated_delta_s,
            distance_m,
            driver_analysis_priority_rank,
            recommended_for_driver_analysis,
            temporal_validation_status,
            temporal_validation_json,
            objective_priority,
            primary_interpretation_unit,
            gross_loss_s,
            gross_gain_s,
            neutral_delta_s,
            net_from_components_s,
            accounting_error_s
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            comparison_id,
            session_id,
            safe_int(
                comparison.get(
                    "reference_lap"
                )
            ),
            safe_int(
                comparison.get(
                    "comparison_lap"
                )
            ),
            safe_float(
                comparison.get(
                    "reference_time_s"
                )
            ),
            safe_float(
                comparison.get(
                    "comparison_time_s"
                )
            ),
            safe_float(
                comparison.get(
                    "comparison_minus_reference_s"
                )
            ),
            safe_float(
                comparison.get(
                    "calculated_delta_s"
                )
            ),
            safe_float(
                comparison.get(
                    "distance_m"
                )
            ),
            safe_int(
                comparison.get(
                    "driver_analysis_priority_rank"
                )
            ),
            comparison.get(
                "recommended_for_driver_analysis"
            ),
            temporal.get(
                "status"
            ),
            json_text(
                temporal
            ),
            objective.get(
                "priority"
            ),
            objective.get(
                "primary_interpretation_unit"
            ),
            safe_float(
                accounting.get(
                    "gross_loss_s"
                )
            ),
            safe_float(
                accounting.get(
                    "gross_gain_s"
                )
            ),
            safe_float(
                accounting.get(
                    "neutral_delta_s"
                )
            ),
            safe_float(
                accounting.get(
                    "net_from_components_s"
                )
            ),
            safe_float(
                accounting.get(
                    "accounting_error_s"
                )
            ),
        ],
    )

    return safe_int(
        comparison_id
    )


def insert_episode(
    connection,
    session_id,
    comparison_id,
    episode_id,
    episode,
    reference_distance_m,
):
    start = safe_float(
        episode.get(
            "start_distance_m"
        )
    )

    end = safe_float(
        episode.get(
            "end_distance_m"
        )
    )

    center = compute_center(
        start,
        end,
    )

    propagations = (
        normalized_speed_propagations(
            episode
        )
    )

    supporting_clusters = episode.get(
        "supporting_loss_clusters",
        [],
    )

    if not isinstance(
        supporting_clusters,
        list,
    ):
        supporting_clusters = []

    episode_pk = connection.execute(
        """
        SELECT
            nextval('episodes_seq')
        """
    ).fetchone()[0]

    connection.execute(
        """
        INSERT INTO episodes (
            episode_pk,
            comparison_id,
            session_id,
            episode_id,
            python_global_rank,
            zone_id,
            parent_zone_rank,
            start_distance_m,
            end_distance_m,
            center_distance_m,
            length_m,
            start_lap_fraction,
            end_lap_fraction,
            center_lap_fraction,
            delta_start_s,
            delta_end_s,
            action_time_loss_s,
            parent_zone_delta_loss_s,
            parent_zone_net_loss_equivalent_percent,
            evidence_strength,
            action_channel_count,
            has_speed_propagation,
            supporting_loss_cluster_count,
            interpretation_json
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            episode_pk,
            comparison_id,
            session_id,
            episode_id,
            safe_int(
                episode.get(
                    "global_rank"
                )
            ),
            safe_int(
                episode.get(
                    "zone_id"
                )
            ),
            safe_int(
                episode.get(
                    "parent_zone_rank"
                )
            ),
            start,
            end,
            center,
            safe_float(
                episode.get(
                    "length_m"
                )
            ),
            lap_fraction(
                start,
                reference_distance_m,
            ),
            lap_fraction(
                end,
                reference_distance_m,
            ),
            lap_fraction(
                center,
                reference_distance_m,
            ),
            safe_float(
                episode.get(
                    "delta_start_s"
                )
            ),
            safe_float(
                episode.get(
                    "delta_end_s"
                )
            ),
            safe_float(
                episode.get(
                    "action_time_loss_s"
                )
            ),
            safe_float(
                episode.get(
                    "parent_zone_delta_loss_s"
                )
            ),
            safe_float(
                episode.get(
                    "parent_zone_net_loss_equivalent_percent"
                )
            ),
            episode.get(
                "evidence_strength"
            ),
            safe_int(
                episode.get(
                    "action_channel_count"
                )
            ),
            bool(
                propagations
            ),
            len(
                supporting_clusters
            ),
            json_text(
                episode.get(
                    "interpretation",
                    {},
                )
            ),
        ],
    )

    return (
        safe_int(
            episode_pk
        ),
        propagations,
    )


def insert_episode_channels(
    connection,
    session_id,
    comparison_id,
    episode_pk,
    episode,
):
    evidence = episode.get(
        "action_evidence_by_channel",
        {},
    )

    if not isinstance(
        evidence,
        dict,
    ):
        return

    episode_start = safe_float(
        episode.get(
            "start_distance_m"
        )
    )

    episode_end = safe_float(
        episode.get(
            "end_distance_m"
        )
    )

    episode_length = safe_float(
        episode.get(
            "length_m"
        )
    )

    for channel, channel_data in evidence.items():
        if not isinstance(
            channel_data,
            dict,
        ):
            continue

        events = channel_data.get(
            "events",
            [],
        )

        if not isinstance(
            events,
            list,
        ):
            events = []

        first_start, last_end = (
            event_bounds(
                events
            )
        )

        supported_length = safe_float(
            channel_data.get(
                "supported_length_m"
            )
        )

        coverage_ratio = None

        if (
            supported_length is not None
            and
            episode_length is not None
            and
            episode_length > 0
        ):
            coverage_ratio = (
                supported_length
                /
                episode_length
            )

        onset_offset = None

        if (
            first_start is not None
            and
            episode_start is not None
        ):
            onset_offset = (
                first_start
                -
                episode_start
            )

        end_offset = None

        if (
            last_end is not None
            and
            episode_end is not None
        ):
            end_offset = (
                episode_end
                -
                last_end
            )

        episode_channel_pk = (
            connection.execute(
                """
                SELECT
                    nextval('episode_channels_seq')
                """
            ).fetchone()[0]
        )

        connection.execute(
            """
            INSERT INTO episode_channels (
                episode_channel_pk,
                episode_pk,
                comparison_id,
                session_id,
                channel,
                event_count,
                supported_length_m,
                episode_coverage_ratio,
                first_event_start_distance_m,
                last_event_end_distance_m,
                onset_offset_m,
                end_offset_m,
                mean_of_event_mean_differences,
                largest_abs_peak_difference,
                direction_consistency,
                raw_events_json
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            [
                episode_channel_pk,
                episode_pk,
                comparison_id,
                session_id,
                str(
                    channel
                ),
                safe_int(
                    channel_data.get(
                        "event_count"
                    )
                ),
                supported_length,
                coverage_ratio,
                first_start,
                last_end,
                onset_offset,
                end_offset,
                safe_float(
                    channel_data.get(
                        "mean_of_event_mean_differences"
                    )
                ),
                safe_float(
                    channel_data.get(
                        "largest_abs_peak_difference"
                    )
                ),
                direction_consistency(
                    events
                ),
                json_text(
                    events
                ),
            ],
        )


def insert_speed_propagations(
    connection,
    session_id,
    comparison_id,
    episode_pk,
    propagations,
    reference_distance_m,
):
    for index, propagation in enumerate(
        propagations,
        start=1,
    ):
        start = safe_float(
            propagation.get(
                "start_distance_m"
            )
        )

        end = safe_float(
            propagation.get(
                "end_distance_m"
            )
        )

        center = compute_center(
            start,
            end,
        )

        row_id = connection.execute(
            """
            SELECT
                nextval('speed_propagations_seq')
            """
        ).fetchone()[0]

        connection.execute(
            """
            INSERT INTO speed_propagations (
                speed_propagation_pk,
                episode_pk,
                comparison_id,
                session_id,
                propagation_index,
                start_distance_m,
                end_distance_m,
                center_distance_m,
                length_m,
                start_lap_fraction,
                end_lap_fraction,
                center_lap_fraction,
                delta_start_s,
                delta_end_s,
                propagated_time_delta_change_s,
                raw_json
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            [
                row_id,
                episode_pk,
                comparison_id,
                session_id,
                index,
                start,
                end,
                center,
                safe_float(
                    propagation.get(
                        "length_m"
                    )
                ),
                lap_fraction(
                    start,
                    reference_distance_m,
                ),
                lap_fraction(
                    end,
                    reference_distance_m,
                ),
                lap_fraction(
                    center,
                    reference_distance_m,
                ),
                safe_float(
                    propagation.get(
                        "delta_start_s"
                    )
                ),
                safe_float(
                    propagation.get(
                        "delta_end_s"
                    )
                ),
                safe_float(
                    propagation.get(
                        "propagated_time_delta_change_s"
                    )
                ),
                json_text(
                    propagation
                ),
            ],
        )


def import_analysis_json(
    connection,
    path,
):
    source_path = normalized_path(
        path
    )

    source_hash = file_sha256(
        source_path
    )

    existing_session = (
        find_existing_session(
            connection,
            source_hash,
        )
    )

    if existing_session is not None:
        data = load_analysis_json(
            source_path
        )

        metadata, _, _ = validate_analysis_json(
            data
        )

        refreshed_context = refresh_missing_session_context(
            connection,
            existing_session,
            metadata,
        )

        log_import(
            connection,
            source_path,
            source_hash,
            existing_session,
            "SKIPPED_DUPLICATE",
            "El mismo contenido ya fue importado; "
            "se completó contexto persistente faltante cuando correspondía.",
        )

        return {
            "status":
                "SKIPPED_DUPLICATE",

            "session_id":
                existing_session,

            "source_hash":
                source_hash,

            "context_refresh":
                refreshed_context,
        }

    data = load_analysis_json(
        source_path
    )

    metadata, laps, comparisons = (
        validate_analysis_json(
            data
        )
    )

    reference_distance_m = safe_float(
        metadata.get(
            "reference_distance_m"
        )
    )

    connection.execute(
        "BEGIN TRANSACTION"
    )

    try:
        session_id = insert_session(
            connection,
            source_path,
            source_hash,
            metadata,
            laps,
            comparisons,
        )

        insert_laps(
            connection,
            session_id,
            metadata,
            laps,
        )

        imported_comparisons = 0
        imported_episodes = 0
        imported_channels = 0
        imported_propagations = 0

        for comparison in comparisons:
            if not isinstance(
                comparison,
                dict,
            ):
                continue

            comparison_id = insert_comparison(
                connection,
                session_id,
                comparison,
            )

            imported_comparisons += 1

            episodes = comparison_episode_list(
                comparison
            )

            for episode_id, episode in enumerate(
                episodes,
                start=1,
            ):
                episode_pk, propagations = (
                    insert_episode(
                        connection,
                        session_id,
                        comparison_id,
                        episode_id,
                        episode,
                        reference_distance_m,
                    )
                )

                imported_episodes += 1

                before_channels = (
                    connection.execute(
                        """
                        SELECT
                            COUNT(*)
                        FROM episode_channels
                        WHERE episode_pk = ?
                        """,
                        [
                            episode_pk
                        ],
                    ).fetchone()[0]
                )

                insert_episode_channels(
                    connection,
                    session_id,
                    comparison_id,
                    episode_pk,
                    episode,
                )

                after_channels = (
                    connection.execute(
                        """
                        SELECT
                            COUNT(*)
                        FROM episode_channels
                        WHERE episode_pk = ?
                        """,
                        [
                            episode_pk
                        ],
                    ).fetchone()[0]
                )

                imported_channels += (
                    after_channels
                    -
                    before_channels
                )

                insert_speed_propagations(
                    connection,
                    session_id,
                    comparison_id,
                    episode_pk,
                    propagations,
                    reference_distance_m,
                )

                imported_propagations += len(
                    propagations
                )

        log_import(
            connection,
            source_path,
            source_hash,
            session_id,
            "IMPORTED",
            (
                f"comparisons={imported_comparisons}; "
                f"episodes={imported_episodes}; "
                f"channels={imported_channels}; "
                f"propagations={imported_propagations}"
            ),
        )

        connection.execute(
            "COMMIT"
        )

    except Exception:
        connection.execute(
            "ROLLBACK"
        )
        raise

    return {
        "status":
            "IMPORTED",

        "session_id":
            session_id,

        "source_hash":
            source_hash,

        "comparisons":
            imported_comparisons,

        "episodes":
            imported_episodes,

        "channels":
            imported_channels,

        "propagations":
            imported_propagations,
    }


# ============================================================
# CONSULTAS
# ============================================================

def list_sessions(
    connection,
):
    rows = connection.execute(
        """
        SELECT
            session_id,
            track,
            session_type,
            timestamp_utc,
            vehicle_family,
            vehicle_variant,
            lmu_track_layout,
            car_name_raw,
            reference_lap,
            valid_lap_count,
            comparison_count,
            source_analysis_version
        FROM sessions
        ORDER BY
            timestamp_utc,
            session_id
        """
    ).fetchall()

    print()
    print(
        "=" * 80
    )

    print(
        "RACE ENGINEER HISTORY - SESSIONS"
    )

    print(
        "=" * 80
    )

    print()

    if not rows:
        print(
            "No hay sesiones importadas."
        )
        return

    for row in rows:
        (
            session_id,
            track,
            session_type,
            timestamp_utc,
            vehicle_family,
            vehicle_variant,
            lmu_track_layout,
            car_name_raw,
            reference_lap,
            valid_lap_count,
            comparison_count,
            analysis_version,
        ) = row

        print(
            f"[{session_id}] "
            f"{track} | "
            f"{session_type} | "
            f"{timestamp_utc}"
        )

        print(
            f"    vehicle={vehicle_family}/{vehicle_variant} | "
            f"layout={lmu_track_layout} | "
            f"car={car_name_raw}"
        )

        print(
            f"    ref lap={reference_lap} | "
            f"valid laps={valid_lap_count} | "
            f"comparisons={comparison_count} | "
            f"analyze={analysis_version}"
        )


def inspect_session(
    connection,
    session_id,
):
    session = connection.execute(
        """
        SELECT
            session_id,
            track,
            session_type,
            timestamp_utc,
            vehicle_family,
            vehicle_variant,
            car_class_raw,
            car_name_raw,
            weather_conditions,
            setup_sha256,
            lmu_session_type,
            lmu_track_layout,
            reference_lap,
            reference_distance_m,
            source_analysis_version,
            source_json_path
        FROM sessions
        WHERE session_id = ?
        """,
        [
            session_id
        ],
    ).fetchone()

    if session is None:
        raise RuntimeError(
            f"No existe session_id={session_id}"
        )

    print()
    print(
        "=" * 80
    )

    print(
        f"SESSION {session_id}"
    )

    print(
        "=" * 80
    )

    print()

    print(
        f"Track: {session[1]}"
    )

    print(
        f"Session type: {session[2]}"
    )

    print(
        f"Timestamp: {session[3]}"
    )

    print(
        f"Vehicle: {session[4]}/{session[5]}"
    )

    print(
        f"Layout: {session[11]}"
    )

    print(
        f"Car class raw: {session[6]}"
    )

    print(
        f"Car name raw: {session[7]}"
    )

    print(
        f"Weather: {session[8]}"
    )

    print(
        f"Setup hash: {session[9]}"
    )

    print(
        f"LMU session type: {session[10]}"
    )

    print(
        f"Reference lap: {session[12]}"
    )

    print(
        f"Reference distance: {session[13]}"
    )

    print(
        f"Analyze version: {session[14]}"
    )

    print(
        f"Source: {session[15]}"
    )

    comparisons = connection.execute(
        """
        SELECT
            comparison_id,
            reference_lap,
            comparison_lap,
            comparison_minus_reference_s,
            driver_analysis_priority_rank
        FROM comparisons
        WHERE session_id = ?
        ORDER BY
            driver_analysis_priority_rank NULLS LAST,
            comparison_id
        """,
        [
            session_id
        ],
    ).fetchall()

    print()
    print(
        "Comparisons:"
    )

    for comparison in comparisons:
        print(
            f"  comparison_id={comparison[0]} | "
            f"{comparison[1]} -> {comparison[2]} | "
            f"delta={comparison[3]} | "
            f"priority_rank={comparison[4]}"
        )

    episodes = connection.execute(
        """
        SELECT
            e.episode_id,
            c.reference_lap,
            c.comparison_lap,
            e.python_global_rank,
            e.start_distance_m,
            e.end_distance_m,
            e.center_lap_fraction,
            e.action_time_loss_s,
            e.evidence_strength,
            e.has_speed_propagation
        FROM episodes e
        JOIN comparisons c
            ON c.comparison_id = e.comparison_id
        WHERE e.session_id = ?
        ORDER BY
            c.driver_analysis_priority_rank NULLS LAST,
            e.python_global_rank NULLS LAST,
            e.episode_id
        """,
        [
            session_id
        ],
    ).fetchall()

    print()
    print(
        "Driver action episodes:"
    )

    for episode in episodes:
        print(
            f"  episode={episode[0]} | "
            f"laps {episode[1]}->{episode[2]} | "
            f"rank={episode[3]} | "
            f"{episode[4]}-{episode[5]} m | "
            f"center_frac={episode[6]} | "
            f"loss={episode[7]} | "
            f"evidence={episode[8]} | "
            f"speed_prop={episode[9]}"
        )

    channels = connection.execute(
        """
        SELECT
            ec.episode_pk,
            ec.channel,
            ec.episode_coverage_ratio,
            ec.onset_offset_m,
            ec.end_offset_m,
            ec.direction_consistency
        FROM episode_channels ec
        WHERE ec.session_id = ?
        ORDER BY
            ec.episode_pk,
            ec.channel
        """,
        [
            session_id
        ],
    ).fetchall()

    print()
    print(
        "Channel metrics:"
    )

    for channel in channels:
        print(
            f"  episode_pk={channel[0]} | "
            f"{channel[1]} | "
            f"coverage={channel[2]} | "
            f"onset={channel[3]} m | "
            f"end_offset={channel[4]} m | "
            f"direction={channel[5]}"
        )



# ============================================================
# IMPORTACIÓN DE DIRECTORIO
# ============================================================

def looks_like_analysis_json_filename(
    filename,
):
    lower = filename.lower()

    if not lower.endswith(
        ".json"
    ):
        return False

    excluded_suffixes = (
        "_llm_analysis.json",
        "_llm_analysis_v3_8_2.json",
        "episode_pair_features.json",
        "lmu_metadata_inventory.json",
    )

    if any(
        lower.endswith(
            suffix
        )
        for suffix in excluded_suffixes
    ):
        return False

    return True


def discover_json_files(
    directory,
    recursive=False,
):
    directory = normalized_path(
        directory
    )

    if not os.path.isdir(
        directory
    ):
        raise NotADirectoryError(
            directory
        )

    result = []

    if recursive:
        for root, _, files in os.walk(
            directory
        ):
            for filename in files:
                if looks_like_analysis_json_filename(
                    filename
                ):
                    result.append(
                        os.path.join(
                            root,
                            filename,
                        )
                    )
    else:
        for filename in os.listdir(
            directory
        ):
            path = os.path.join(
                directory,
                filename,
            )

            if (
                os.path.isfile(
                    path
                )
                and
                looks_like_analysis_json_filename(
                    filename
                )
            ):
                result.append(
                    path
                )

    return sorted(
        normalized_path(
            path
        )
        for path in result
    )


def import_directory(
    connection,
    directory,
    recursive=False,
):
    files = discover_json_files(
        directory,
        recursive=recursive,
    )

    summary = {
        "files_discovered":
            len(files),

        "imported":
            0,

        "duplicates":
            0,

        "skipped_not_analysis":
            0,

        "failed":
            0,

        "results":
            [],
    }

    for path in files:
        try:
            result = import_analysis_json(
                connection,
                path,
            )

            status = result.get(
                "status"
            )

            if status == "IMPORTED":
                summary[
                    "imported"
                ] += 1

            elif status == "SKIPPED_DUPLICATE":
                summary[
                    "duplicates"
                ] += 1

            summary[
                "results"
            ].append({
                "path":
                    path,

                "status":
                    status,

                "session_id":
                    result.get(
                        "session_id"
                    ),
            })

        except ValueError as exc:
            summary[
                "skipped_not_analysis"
            ] += 1

            summary[
                "results"
            ].append({
                "path":
                    path,

                "status":
                    "SKIPPED_NOT_ANALYSIS",

                "message":
                    str(exc),
            })

        except Exception as exc:
            summary[
                "failed"
            ] += 1

            summary[
                "results"
            ].append({
                "path":
                    path,

                "status":
                    "FAILED",

                "message":
                    str(exc),
            })

    return summary


# ============================================================
# ESTADÍSTICAS
# ============================================================

def print_history_stats(
    connection,
):
    print()
    print(
        "=" * 80
    )

    print(
        "RACE ENGINEER HISTORY - STATS"
    )

    print(
        "=" * 80
    )

    totals = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM sessions),
            (SELECT COUNT(*) FROM comparisons),
            (SELECT COUNT(*) FROM episodes),
            (SELECT COUNT(*) FROM episode_channels),
            (SELECT COUNT(*) FROM speed_propagations)
        """
    ).fetchone()

    print()

    print(
        f"Sessions: {totals[0]}"
    )

    print(
        f"Comparisons: {totals[1]}"
    )

    print(
        f"Driver action episodes: {totals[2]}"
    )

    print(
        f"Episode channels: {totals[3]}"
    )

    print(
        f"Speed propagations: {totals[4]}"
    )

    rows = connection.execute(
        """
        SELECT
            s.track,
            s.lmu_track_layout,
            s.vehicle_variant,
            COUNT(DISTINCT s.session_id) AS sessions,
            COUNT(DISTINCT c.comparison_id) AS comparisons,
            COUNT(DISTINCT e.episode_pk) AS episodes,
            MIN(s.timestamp_utc) AS first_seen,
            MAX(s.timestamp_utc) AS last_seen
        FROM sessions s
        LEFT JOIN comparisons c
            ON c.session_id = s.session_id
        LEFT JOIN episodes e
            ON e.session_id = s.session_id
        GROUP BY s.track, s.lmu_track_layout, s.vehicle_variant
        ORDER BY
            sessions DESC,
            s.track,
            s.lmu_track_layout,
            s.vehicle_variant
        """
    ).fetchall()

    print()
    print(
        "By track:"
    )

    if not rows:
        print(
            "  No data."
        )
        return

    for row in rows:
        print()
        print(
            f"  {row[0]} | layout={row[1]} | variant={row[2]}"
        )

        print(
            f"    sessions={row[3]} | "
            f"comparisons={row[4]} | "
            f"episodes={row[5]}"
        )

        print(
            f"    first={row[6]} | "
            f"last={row[7]}"
        )

    channel_rows = connection.execute(
        """
        SELECT
            channel,
            COUNT(*) AS rows,
            AVG(episode_coverage_ratio) AS mean_coverage
        FROM episode_channels
        GROUP BY channel
        ORDER BY rows DESC, channel
        """
    ).fetchall()

    print()
    print(
        "Action channels:"
    )

    for row in channel_rows:
        print(
            f"  {row[0]} | "
            f"rows={row[1]} | "
            f"mean_coverage={row[2]}"
        )




# ============================================================
# H3 PATTERN RUN PERSISTENCE
# ============================================================

H3_EXPECTED_VERSION = "0.1"
H3_EXPECTED_MATCHER_VERSION = "0.3"
H3_ALLOWED_STATES = {
    "single_observation",
    "cross_session_repeat",
    "persistent_pattern",
    "conflict_review_required",
}


def load_json_object(path):
    with open(path, "r", encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root inválido: {path}")
    return value


def _bundle_sha256(patterns_sha, matches_sha):
    return hashlib.sha256(
        f"{patterns_sha}:{matches_sha}".encode("utf-8")
    ).hexdigest()


def _stable_pattern_bundle_sha256(
    patterns_doc,
    matches_doc,
    patterns_sha,
    matches_sha,
):
    """Identify one official H2/H3 materialization without volatile timestamps.

    Legacy standalone H3 artifacts keep their historical byte-hash identity. The
    official pipeline carries a source feature hash and enough structured authority
    provenance to derive an idempotent semantic bundle key.
    """

    metadata = patterns_doc.get("metadata") or {}
    match_metadata = matches_doc.get("metadata") or {}
    if not metadata.get("h3_pipeline_version"):
        return _bundle_sha256(patterns_sha, matches_sha)

    identity = {
        "source_features_sha256": metadata.get("source_features_sha256"),
        "h3_version": metadata.get("h3_version"),
        "pattern_schema_version": metadata.get("schema_version"),
        "h3_pipeline_version": metadata.get("h3_pipeline_version"),
        "matcher_version": metadata.get("matcher_version"),
        "authorized_matcher_version": metadata.get("authorized_matcher_version"),
        "track_baseline_policy_version": metadata.get(
            "track_baseline_policy_version"
        ),
        "match_promotion_policy_version": metadata.get(
            "match_promotion_policy_version"
        ),
        "persistent_min_independent_sessions": metadata.get(
            "persistent_min_independent_sessions"
        ),
        "h2_authority_gate": metadata.get("h2_authority_gate"),
        "summary": patterns_doc.get("summary"),
        "patterns": patterns_doc.get("patterns"),
        "decisions": matches_doc.get("decisions"),
        "production_contract": match_metadata.get("production_contract"),
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _pattern_run_existing(connection, bundle_sha):
    row = connection.execute(
        """
        SELECT pattern_run_id
        FROM pattern_runs
        WHERE source_bundle_sha256 = ?
        """,
        [bundle_sha],
    ).fetchone()
    return safe_int(row[0]) if row else None


def inspect_pattern_run_import(connection, patterns_path, matches_path):
    """Validate an H3 bundle and report whether this exact run is in History.

    This is the read-only counterpart of ``import_pattern_run``.  It applies the
    same source, context and authority validation, but never starts a transaction
    or inserts rows.
    """

    patterns_path = normalized_path(patterns_path)
    matches_path = normalized_path(matches_path)
    if not os.path.exists(patterns_path):
        raise FileNotFoundError(patterns_path)
    if not os.path.exists(matches_path):
        raise FileNotFoundError(matches_path)

    patterns_sha = file_sha256(patterns_path)
    matches_sha = file_sha256(matches_path)
    patterns_doc = load_json_object(patterns_path)
    matches_doc = load_json_object(matches_path)
    metadata, summary, patterns, _, _ = _validate_pattern_import_sources(
        connection,
        patterns_doc,
        matches_doc,
    )
    bundle_sha = _stable_pattern_bundle_sha256(
        patterns_doc,
        matches_doc,
        patterns_sha,
        matches_sha,
    )
    existing = _pattern_run_existing(connection, bundle_sha)
    contexts = {
        (
            str((pattern.get("context") or {}).get("track") or "").strip(),
            str((pattern.get("context") or {}).get("track_layout") or "").strip(),
            str((pattern.get("context") or {}).get("vehicle_variant") or "").strip(),
        )
        for pattern in patterns
    }
    if len(contexts) != 1:
        raise ValueError(
            "Pattern run debe tener un único contexto; "
            f"encontrados={sorted(contexts)!r}"
        )

    return {
        "status": "IMPORTED" if existing is not None else "READY_TO_IMPORT",
        "pattern_run_id": existing,
        "source_bundle_sha256": bundle_sha,
        "context": next(iter(contexts)),
        "pattern_count": len(patterns),
        "state_counts": dict(summary.get("state_counts") or {}),
        "h3_version": metadata.get("h3_version"),
        "matcher_version": metadata.get("matcher_version"),
        "observational_only": True,
        "historical_actions_authorized": False,
    }


def _validate_pattern_import_sources(connection, patterns_doc, matches_doc):
    metadata = patterns_doc.get("metadata")
    summary = patterns_doc.get("summary")
    patterns = patterns_doc.get("patterns")
    match_metadata = matches_doc.get("metadata")
    decisions = matches_doc.get("decisions")

    if not isinstance(metadata, dict):
        raise ValueError("persistent_patterns metadata ausente/inválida.")
    if not isinstance(summary, dict):
        raise ValueError("persistent_patterns summary ausente/inválida.")
    if not isinstance(patterns, list):
        raise ValueError("persistent_patterns patterns ausente/inválida.")
    if not isinstance(match_metadata, dict) or not isinstance(decisions, list):
        raise ValueError("episode_pair_matches inválido.")

    if str(metadata.get("h3_version")) != H3_EXPECTED_VERSION:
        raise ValueError(
            f"H3 version incompatible: {metadata.get('h3_version')!r}; "
            f"esperado {H3_EXPECTED_VERSION}."
        )
    matcher_version = str(metadata.get("matcher_version") or "")
    source_matcher_version = str(match_metadata.get("matcher_version") or "")
    if matcher_version != H3_EXPECTED_MATCHER_VERSION:
        raise ValueError(
            f"H3 source matcher incompatible: {matcher_version!r}; "
            f"esperado {H3_EXPECTED_MATCHER_VERSION}."
        )
    if source_matcher_version != matcher_version:
        raise ValueError(
            "Matcher provenance mismatch entre persistent_patterns y episode_pair_matches."
        )

    _validate_official_h3_authority_provenance(
        metadata,
        match_metadata,
        decisions,
    )

    conflicts = safe_int(summary.get("conflict_review_required_count")) or 0
    if conflicts:
        raise ValueError(
            "No se persiste un H3 run con conflict_review_required_count > 0. "
            "Resolver/auditar la contradicción primero."
        )

    if safe_int(summary.get("pattern_count")) != len(patterns):
        raise ValueError("summary.pattern_count no coincide con patterns.")

    # pattern membership must point to real History episodes and remain context-compatible.
    seen_members = set()
    for pattern in patterns:
        if not isinstance(pattern, dict):
            raise ValueError("Pattern no es objeto.")
        state = pattern.get("state")
        if state not in H3_ALLOWED_STATES:
            raise ValueError(f"Pattern state inválido: {state!r}")
        if state == "conflict_review_required":
            raise ValueError("Run contiene conflict_review_required; no se persiste.")

        context = pattern.get("context") or {}
        track = str(context.get("track") or "").strip()
        layout = str(context.get("track_layout") or "").strip()
        variant = str(context.get("vehicle_variant") or "").strip()
        if not track or not layout or not variant:
            raise ValueError("Pattern con contexto incompleto.")

        members = pattern.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("Pattern sin members.")
        if safe_int(pattern.get("observation_count")) != len(members):
            raise ValueError(f"{pattern.get('pattern_id')}: observation_count inconsistente.")

        sessions = set()
        for member in members:
            if not isinstance(member, dict):
                raise ValueError("Pattern member inválido.")
            session_id = safe_int(member.get("session_id"))
            episode_pk = safe_int(member.get("episode_pk"))
            if session_id is None or episode_pk is None:
                raise ValueError("Pattern member sin session_id/episode_pk.")
            identity = (session_id, episode_pk)
            if identity in seen_members:
                raise ValueError(f"Episode repetido en más de un pattern: {identity}")
            seen_members.add(identity)
            sessions.add(session_id)

            row = connection.execute(
                """
                SELECT
                    e.session_id,
                    s.track,
                    s.lmu_track_layout,
                    s.vehicle_variant
                FROM episodes e
                JOIN sessions s ON s.session_id = e.session_id
                WHERE e.episode_pk = ?
                """,
                [episode_pk],
            ).fetchone()
            if row is None:
                raise ValueError(f"Episode History inexistente: episode_pk={episode_pk}")
            if safe_int(row[0]) != session_id:
                raise ValueError(f"Episode/session mismatch para episode_pk={episode_pk}")
            db_context = (
                str(row[1] or "").strip(),
                str(row[2] or "").strip(),
                str(row[3] or "").strip(),
            )
            if db_context != (track, layout, variant):
                raise ValueError(
                    f"Pattern/member context mismatch {identity}: "
                    f"pattern={(track, layout, variant)!r}, db={db_context!r}"
                )

        if safe_int(pattern.get("independent_session_count")) != len(sessions):
            raise ValueError(f"{pattern.get('pattern_id')}: independent_session_count inconsistente.")

    return metadata, summary, patterns, match_metadata, decisions


def _validate_official_h3_authority_provenance(
    metadata,
    match_metadata,
    decisions,
):
    """Fail closed for official hierarchical H2/H3 pipeline artifacts."""

    if not metadata.get("h3_pipeline_version"):
        return

    sha_pattern = re.compile(r"^[0-9a-f]{64}$")
    patterns_features_sha = str(metadata.get("source_features_sha256") or "")
    matches_features_sha = str(match_metadata.get("source_features_sha256") or "")
    if not sha_pattern.fullmatch(patterns_features_sha):
        raise ValueError("H3 oficial sin source_features_sha256 válido.")
    if matches_features_sha != patterns_features_sha:
        raise ValueError("source_features_sha256 mismatch entre H3 y H2.")

    provenance_fields = (
        "authorized_matcher_version",
        "track_baseline_policy_version",
        "match_promotion_policy_version",
    )
    for field in provenance_fields:
        pattern_value = metadata.get(field)
        match_value = match_metadata.get(field)
        if not pattern_value or pattern_value != match_value:
            raise ValueError(f"Provenance H2/H3 inválida para {field}.")

    gate = metadata.get("h2_authority_gate")
    if not isinstance(gate, dict):
        raise ValueError("H3 oficial sin h2_authority_gate válido.")
    if str(gate.get("matcher_version") or "") != str(metadata.get("matcher_version")):
        raise ValueError("h2_authority_gate matcher_version inconsistente.")
    if safe_int(gate.get("inherited_reject_count")) != 0:
        raise ValueError("H3 oficial contiene inherited REJECT.")
    if safe_int(gate.get("unauthorized_match_count")) != 0:
        raise ValueError("H3 oficial contiene MATCH no autorizado.")

    decision_counts = Counter()
    scope_counts = Counter()
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("Decision H2 oficial inválida.")
        value = str(decision.get("decision") or "AMBIGUOUS")
        authority = decision.get("authority")
        if not isinstance(authority, dict):
            raise ValueError("Decision H2 oficial sin authority.")
        scope = str(authority.get("calibration_scope") or "UNKNOWN")
        decision_counts[value] += 1
        scope_counts[scope] += 1

        for field in provenance_fields:
            if authority.get(field) != metadata.get(field):
                raise ValueError(
                    f"Decision H2 con provenance inconsistente para {field}."
                )

        if value == "MATCH" and authority.get("production_match_authorized") is not True:
            raise ValueError("Decision MATCH sin autoridad productiva.")
        if value == "MATCH" and scope not in {
            "EXACT_VARIANT_CALIBRATION",
            "COVERED_BY_TRACK_MATCH_BASELINE",
        }:
            raise ValueError(f"Decision MATCH con calibration_scope inválido: {scope}.")
        if scope == "EXACT_VARIANT_CALIBRATION" and value == "REJECT":
            if authority.get("production_reject_authorized") is not True:
                raise ValueError("REJECT exacto sin autoridad calibrada.")
        if scope == "COVERED_BY_TRACK_MATCH_BASELINE":
            if value == "REJECT":
                raise ValueError("REJECT heredado no puede persistirse en H3.")
            if authority.get("production_reject_authorized") is not False:
                raise ValueError("Track baseline debe conservar REJECT variant-specific.")

    expected_decisions = {
        str(key): int(value)
        for key, value in (gate.get("decision_counts") or {}).items()
    }
    expected_scopes = {
        str(key): int(value)
        for key, value in (gate.get("authority_scope_counts") or {}).items()
    }
    if dict(sorted(decision_counts.items())) != dict(sorted(expected_decisions.items())):
        raise ValueError("h2_authority_gate decision_counts inconsistente.")
    if dict(sorted(scope_counts.items())) != dict(sorted(expected_scopes.items())):
        raise ValueError("h2_authority_gate authority_scope_counts inconsistente.")


def import_pattern_run(connection, patterns_path, matches_path):
    patterns_path = normalized_path(patterns_path)
    matches_path = normalized_path(matches_path)
    if not os.path.exists(patterns_path):
        raise FileNotFoundError(patterns_path)
    if not os.path.exists(matches_path):
        raise FileNotFoundError(matches_path)

    patterns_sha = file_sha256(patterns_path)
    matches_sha = file_sha256(matches_path)
    patterns_doc = load_json_object(patterns_path)
    matches_doc = load_json_object(matches_path)
    metadata, summary, patterns, match_metadata, decisions = _validate_pattern_import_sources(
        connection, patterns_doc, matches_doc
    )
    bundle_sha = _stable_pattern_bundle_sha256(
        patterns_doc,
        matches_doc,
        patterns_sha,
        matches_sha,
    )

    existing = _pattern_run_existing(connection, bundle_sha)
    if existing is not None:
        return {
            "status": "REUSED",
            "pattern_run_id": existing,
            "source_bundle_sha256": bundle_sha,
        }

    # Infer run context from patterns; a calibration run must have exactly one H2 context.
    contexts = {
        (
            str((p.get("context") or {}).get("track") or "").strip(),
            str((p.get("context") or {}).get("track_layout") or "").strip(),
            str((p.get("context") or {}).get("vehicle_variant") or "").strip(),
        )
        for p in patterns
    }
    if len(contexts) != 1:
        raise ValueError(f"Pattern run debe tener un único contexto; encontrados={sorted(contexts)!r}")
    track, track_layout, vehicle_variant = next(iter(contexts))

    source_state_counts = summary.get("state_counts") or {}
    state_counts = {
        state: sum(1 for p in patterns if p.get("state") == state)
        for state in H3_ALLOWED_STATES
    }
    for state, count in state_counts.items():
        if safe_int(source_state_counts.get(state, 0)) != count:
            raise ValueError(f"summary.state_counts inconsistente para {state}")

    member_to_pattern_id = {}
    for p in patterns:
        pid = str(p.get("pattern_id") or "")
        if not pid:
            raise ValueError("pattern_id ausente.")
        for m in p.get("members") or []:
            member_to_pattern_id[(safe_int(m.get("session_id")), safe_int(m.get("episode_pk")))] = pid

    # Determine internal pair evidence from matcher decisions using H3 membership.
    evidence_by_pattern = {str(p.get("pattern_id")): [] for p in patterns}
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        a = (safe_int(decision.get("session_a")), safe_int(decision.get("episode_pk_a")))
        b = (safe_int(decision.get("session_b")), safe_int(decision.get("episode_pk_b")))
        pa = member_to_pattern_id.get(a)
        pb = member_to_pattern_id.get(b)
        if pa is not None and pa == pb:
            evidence_by_pattern[pa].append(decision)

    connection.execute("BEGIN TRANSACTION")
    try:
        pattern_run_id = connection.execute(
            "SELECT nextval('pattern_runs_seq')"
        ).fetchone()[0]

        connection.execute(
            """
            INSERT INTO pattern_runs (
                pattern_run_id,
                source_patterns_path, source_patterns_sha256,
                source_matches_path, source_matches_sha256,
                source_bundle_sha256,
                h3_version, pattern_schema_version,
                matcher_version, matcher_status,
                persistent_min_independent_sessions,
                track, track_layout, vehicle_variant,
                pattern_count, episode_count,
                single_observation_count, cross_session_repeat_count,
                persistent_pattern_count, conflict_review_required_count,
                match_edge_count, transitively_resolved_ambiguous_pair_count,
                source_created_at_utc, imported_at_utc, metadata_json
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                pattern_run_id,
                patterns_path, patterns_sha,
                matches_path, matches_sha,
                bundle_sha,
                str(metadata.get("h3_version")),
                str(metadata.get("schema_version") or ""),
                str(metadata.get("matcher_version")),
                str(metadata.get("matcher_status") or ""),
                safe_int(metadata.get("persistent_min_independent_sessions")),
                track, track_layout, vehicle_variant,
                len(patterns),
                safe_int(summary.get("episode_count")) or 0,
                state_counts["single_observation"],
                state_counts["cross_session_repeat"],
                state_counts["persistent_pattern"],
                state_counts["conflict_review_required"],
                safe_int(summary.get("match_edge_count")) or 0,
                safe_int(summary.get("transitively_resolved_ambiguous_pair_count")) or 0,
                str(metadata.get("created_at_utc") or ""),
                utc_now_iso(),
                json_text(metadata),
            ],
        )

        pattern_pk_by_id = {}
        for pattern in patterns:
            pid = str(pattern["pattern_id"])
            pattern_pk = connection.execute(
                "SELECT nextval('persistent_patterns_seq')"
            ).fetchone()[0]
            pattern_pk_by_id[pid] = pattern_pk

            spatial = pattern.get("spatial_summary") or {}
            impact = pattern.get("impact_summary") or {}
            channels = pattern.get("channel_summary") or {}
            eq = pattern.get("equivalence_evidence") or {}
            rep = pattern.get("representative_member") or {}
            context = pattern.get("context") or {}

            connection.execute(
                """
                INSERT INTO persistent_patterns (
                    pattern_pk, pattern_run_id, pattern_id, state,
                    track, track_layout, vehicle_variant,
                    observation_count, independent_session_count,
                    representative_session_id, representative_episode_pk,
                    center_median_m, center_min_m, center_max_m, center_spread_m,
                    start_median_m, end_median_m,
                    action_time_loss_median_s, action_time_loss_min_s, action_time_loss_max_s,
                    direct_match_edge_count, internal_ambiguous_pair_count,
                    internal_reject_pair_count, possible_cross_session_pair_count,
                    observed_internal_cross_session_pair_count,
                    missing_internal_cross_session_pair_count,
                    transitively_resolved_ambiguous_pair_count,
                    common_action_channels_json, union_action_channels_json,
                    session_ids_json, raw_pattern_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    pattern_pk, pattern_run_id, pid, pattern.get("state"),
                    str(context.get("track")), str(context.get("track_layout")),
                    str(context.get("vehicle_variant")),
                    safe_int(pattern.get("observation_count")),
                    safe_int(pattern.get("independent_session_count")),
                    safe_int(rep.get("session_id")), safe_int(rep.get("episode_pk")),
                    safe_float(spatial.get("center_median_m")),
                    safe_float(spatial.get("center_min_m")),
                    safe_float(spatial.get("center_max_m")),
                    safe_float(spatial.get("center_spread_m")),
                    safe_float(spatial.get("start_median_m")),
                    safe_float(spatial.get("end_median_m")),
                    safe_float(impact.get("action_time_loss_median_s")),
                    safe_float(impact.get("action_time_loss_min_s")),
                    safe_float(impact.get("action_time_loss_max_s")),
                    safe_int(eq.get("direct_match_edge_count")) or 0,
                    safe_int(eq.get("internal_ambiguous_pair_count")) or 0,
                    safe_int(eq.get("internal_reject_pair_count")) or 0,
                    safe_int(eq.get("possible_cross_session_pair_count")) or 0,
                    safe_int(eq.get("observed_internal_cross_session_pair_count")) or 0,
                    safe_int(eq.get("missing_internal_cross_session_pair_count")) or 0,
                    safe_int(eq.get("transitively_resolved_ambiguous_pair_count")) or 0,
                    json_text(channels.get("common_action_channels") or []),
                    json_text(channels.get("union_action_channels") or []),
                    json_text(pattern.get("session_ids") or []),
                    json_text(pattern),
                ],
            )

            for member in pattern.get("members") or []:
                connection.execute(
                    """
                    INSERT INTO persistent_pattern_members (
                        pattern_member_pk, pattern_pk, pattern_run_id, pattern_id,
                        session_id, episode_pk, episode_id,
                        timestamp_utc, session_type,
                        start_distance_m, end_distance_m, center_distance_m,
                        action_time_loss_s, channels_json
                    ) VALUES (
                        nextval('persistent_pattern_members_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        pattern_pk, pattern_run_id, pid,
                        safe_int(member.get("session_id")), safe_int(member.get("episode_pk")),
                        safe_int(member.get("episode_id")),
                        member.get("timestamp_utc"), member.get("session_type"),
                        safe_float(member.get("start_distance_m")),
                        safe_float(member.get("end_distance_m")),
                        safe_float(member.get("center_distance_m")),
                        safe_float(member.get("action_time_loss_s")),
                        json_text(member.get("channels") or []),
                    ],
                )

        for pid, evidence_rows in evidence_by_pattern.items():
            pattern_pk = pattern_pk_by_id[pid]
            for decision in evidence_rows:
                connection.execute(
                    """
                    INSERT INTO persistent_pattern_pair_evidence (
                        pattern_pair_evidence_pk,
                        pattern_pk, pattern_run_id, pattern_id,
                        pair_index, pair_id, decision, rule_id, automatic,
                        session_a, episode_pk_a, session_b, episode_pk_b,
                        raw_decision_json
                    ) VALUES (
                        nextval('persistent_pattern_pair_evidence_seq'),
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        pattern_pk, pattern_run_id, pid,
                        safe_int(decision.get("pair_index")), decision.get("pair_id"),
                        decision.get("decision"), decision.get("rule_id"),
                        decision.get("automatic"),
                        safe_int(decision.get("session_a")), safe_int(decision.get("episode_pk_a")),
                        safe_int(decision.get("session_b")), safe_int(decision.get("episode_pk_b")),
                        json_text(decision),
                    ],
                )

        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    return {
        "status": "IMPORTED",
        "pattern_run_id": safe_int(pattern_run_id),
        "source_bundle_sha256": bundle_sha,
        "context": {
            "track": track,
            "track_layout": track_layout,
            "vehicle_variant": vehicle_variant,
        },
        "patterns": len(patterns),
        "episodes": safe_int(summary.get("episode_count")) or 0,
        "pair_evidence_rows": sum(len(v) for v in evidence_by_pattern.values()),
    }


def list_pattern_runs(connection):
    rows = connection.execute(
        """
        SELECT
            pattern_run_id, imported_at_utc,
            track, track_layout, vehicle_variant,
            h3_version, matcher_version,
            pattern_count, persistent_pattern_count,
            cross_session_repeat_count, single_observation_count
        FROM pattern_runs
        ORDER BY pattern_run_id DESC
        """
    ).fetchall()
    print()
    print("PATTERN RUNS")
    for row in rows:
        print(
            f"run={row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | "
            f"H3={row[5]} matcher={row[6]} | patterns={row[7]} | "
            f"persistent={row[8]} repeat={row[9]} single={row[10]}"
        )


def list_patterns(connection, pattern_run_id=None):
    if pattern_run_id is None:
        row = connection.execute(
            "SELECT MAX(pattern_run_id) FROM pattern_runs"
        ).fetchone()
        pattern_run_id = safe_int(row[0]) if row else None
    if pattern_run_id is None:
        print("No hay pattern runs persistidos.")
        return
    rows = connection.execute(
        """
        SELECT
            pattern_id, state, independent_session_count, observation_count,
            center_median_m, center_spread_m, common_action_channels_json,
            direct_match_edge_count, internal_ambiguous_pair_count, internal_reject_pair_count
        FROM persistent_patterns
        WHERE pattern_run_id = ?
        ORDER BY
            CASE state
                WHEN 'persistent_pattern' THEN 0
                WHEN 'cross_session_repeat' THEN 1
                WHEN 'single_observation' THEN 2
                ELSE 3
            END,
            independent_session_count DESC,
            observation_count DESC,
            center_median_m
        """,
        [pattern_run_id],
    ).fetchall()
    print()
    print(f"PATTERNS | run={pattern_run_id}")
    for row in rows:
        print(
            f"{row[0]} | {row[1]} | sessions={row[2]} obs={row[3]} | "
            f"center={row[4]} spread={row[5]} | common={row[6]} | "
            f"M/A/R={row[7]}/{row[8]}/{row[9]}"
        )


def inspect_pattern(connection, pattern_id, pattern_run_id=None):
    if pattern_run_id is None:
        row = connection.execute(
            """
            SELECT MAX(pattern_run_id)
            FROM persistent_patterns
            WHERE pattern_id = ?
            """,
            [pattern_id],
        ).fetchone()
        pattern_run_id = safe_int(row[0]) if row else None
    if pattern_run_id is None:
        raise ValueError(f"Pattern no encontrado: {pattern_id}")
    row = connection.execute(
        """
        SELECT raw_pattern_json
        FROM persistent_patterns
        WHERE pattern_run_id = ? AND pattern_id = ?
        """,
        [pattern_run_id, pattern_id],
    ).fetchone()
    if row is None:
        raise ValueError(f"Pattern no encontrado en run {pattern_run_id}: {pattern_id}")
    print(json.dumps(json.loads(row[0]), indent=2, ensure_ascii=False))


# ============================================================
# CLI
# ============================================================

def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Historial persistente para "
            "Race Engineer."
        )
    )

    parser.add_argument(
        "--db",
        default=default_db_path(),
        help=(
            "Ruta a race_engineer_history.duckdb"
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser(
        "init",
        help="Crear/actualizar esquema.",
    )

    import_parser = (
        subparsers.add_parser(
            "import",
            help="Importar JSON analyze_telemetry.",
        )
    )

    import_parser.add_argument(
        "json_file",
        help="JSON generado por analyze_telemetry.py",
    )

    import_dir_parser = (
        subparsers.add_parser(
            "import-dir",
            help="Importar JSON desde una carpeta.",
        )
    )

    import_dir_parser.add_argument(
        "directory",
        help="Carpeta con JSON analyze_telemetry.",
    )

    import_dir_parser.add_argument(
        "--recursive",
        action="store_true",
        help="Buscar también en subcarpetas.",
    )

    subparsers.add_parser(
        "list",
        help="Listar sesiones.",
    )

    subparsers.add_parser(
        "stats",
        help="Mostrar estadísticas del historial.",
    )

    inspect_parser = (
        subparsers.add_parser(
            "inspect",
            help="Inspeccionar una sesión.",
        )
    )

    inspect_parser.add_argument(
        "session_id",
        type=int,
    )

    pattern_import_parser = subparsers.add_parser(
        "import-patterns",
        help="Persistir un H3 pattern run derivado.",
    )
    pattern_import_parser.add_argument(
        "patterns_json",
        help="persistent_patterns.json generado por build_persistent_patterns.py",
    )
    pattern_import_parser.add_argument(
        "matches_json",
        help="episode_pair_matches.json exacto usado por ese H3 run",
    )

    subparsers.add_parser(
        "pattern-runs",
        help="Listar H3 pattern runs persistidos.",
    )

    patterns_parser = subparsers.add_parser(
        "patterns",
        help="Listar patterns de un run; default último run.",
    )
    patterns_parser.add_argument("--run-id", type=int, default=None)

    inspect_pattern_parser = subparsers.add_parser(
        "inspect-pattern",
        help="Inspeccionar un pattern persistido.",
    )
    inspect_pattern_parser.add_argument("pattern_id")
    inspect_pattern_parser.add_argument("--run-id", type=int, default=None)

    return parser


def main():
    parser = build_parser()

    args = parser.parse_args()

    db_path = normalized_path(
        args.db
    )

    os.makedirs(
        os.path.dirname(
            db_path
        ),
        exist_ok=True,
    )

    connection = duckdb.connect(
        db_path
    )

    try:
        initialize_schema(
            connection
        )

        if args.command == "init":
            print()
            print(
                "History DB inicializada:"
            )

            print(
                db_path
            )

            print(
                f"Schema version: "
                f"{SCHEMA_VERSION}"
            )

        elif args.command == "import":
            json_path = normalized_path(
                args.json_file
            )

            if not os.path.exists(
                json_path
            ):
                raise FileNotFoundError(
                    json_path
                )

            result = import_analysis_json(
                connection,
                json_path,
            )

            print()
            print(
                "IMPORT RESULT"
            )

            print(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                )
            )

        elif args.command == "import-dir":
            directory = normalized_path(
                args.directory
            )

            result = import_directory(
                connection,
                directory,
                recursive=args.recursive,
            )

            print()
            print(
                "BATCH IMPORT RESULT"
            )

            print(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                )
            )

        elif args.command == "list":
            list_sessions(
                connection
            )

        elif args.command == "stats":
            print_history_stats(
                connection
            )

        elif args.command == "inspect":
            inspect_session(
                connection,
                args.session_id,
            )

        elif args.command == "import-patterns":
            result = import_pattern_run(
                connection,
                args.patterns_json,
                args.matches_json,
            )
            print()
            print("PATTERN IMPORT RESULT")
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "pattern-runs":
            list_pattern_runs(connection)

        elif args.command == "patterns":
            list_patterns(connection, args.run_id)

        elif args.command == "inspect-pattern":
            inspect_pattern(connection, args.pattern_id, args.run_id)

    finally:
        connection.close()


if __name__ == "__main__":
    main()
