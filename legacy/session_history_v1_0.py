import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import duckdb


# ============================================================
# RACE ENGINEER - SESSION HISTORY v1.0
# ============================================================
#
# Historial persistente de sesiones analizadas por
# analyze_telemetry.py v3.8+.
#
# NO llama a Ollama.
# NO modifica los JSON fuente.
# NO hace matching entre sesiones todavía.
# NO decide patrones todavía.
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
#   list
#       lista sesiones importadas
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

SCHEMA_VERSION = 1

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
        base_dir(),
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
            "session_history v1.0 requiere "
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
"""


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


def insert_session(
    connection,
    source_path,
    source_hash,
    metadata,
    laps,
    comparisons,
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
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?
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
        log_import(
            connection,
            source_path,
            source_hash,
            existing_session,
            "SKIPPED_DUPLICATE",
            "El mismo contenido ya fue importado.",
        )

        return {
            "status":
                "SKIPPED_DUPLICATE",

            "session_id":
                existing_session,

            "source_hash":
                source_hash,
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
        f"Reference lap: {session[4]}"
    )

    print(
        f"Reference distance: {session[5]}"
    )

    print(
        f"Analyze version: {session[6]}"
    )

    print(
        f"Source: {session[7]}"
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

    subparsers.add_parser(
        "list",
        help="Listar sesiones.",
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

        elif args.command == "list":
            list_sessions(
                connection
            )

        elif args.command == "inspect":
            inspect_session(
                connection,
                args.session_id,
            )

    finally:
        connection.close()


if __name__ == "__main__":
    main()
