import argparse
import json
import math
import os
import re
import sys

import duckdb


# ============================================================
# RACE ENGINEER - HISTORY DB VALIDATOR v1.3
# ============================================================
#
# Valida integridad interna de race_engineer_history.duckdb.
#
# NO usa thresholds de pattern matching.
# NO llama a Ollama.
# NO modifica la base.
#
# Uso:
#
#   python validate_history_db.py
#
#   python validate_history_db.py --db "otra.duckdb"
#
# ============================================================


DEFAULT_DB_NAME = "race_engineer_history.duckdb"

EXPECTED_SCHEMA_VERSION = 4

ALLOWED_ACTION_CHANNELS = {
    "throttle",
    "brake",
    "steering_magnitude",
}

FLOAT_TOLERANCE = 1e-8


def base_dir():
    return os.path.dirname(
        os.path.abspath(
            __file__
        )
    )


def default_db_path():
    return os.path.join(
        base_dir(),
        DEFAULT_DB_NAME,
    )


def safe_float(value):
    if value is None:
        return None

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(
        value
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


def approx_equal(
    a,
    b,
    tolerance=FLOAT_TOLERANCE,
):
    a = safe_float(a)
    b = safe_float(b)

    if (
        a is None
        or
        b is None
    ):
        return False

    return abs(
        a - b
    ) <= tolerance


def table_exists(
    connection,
    table_name,
):
    row = connection.execute(
        """
        SELECT
            COUNT(*)
        FROM information_schema.tables
        WHERE table_name = ?
        """,
        [
            table_name
        ],
    ).fetchone()

    return bool(
        row
        and
        row[0]
    )


def require_tables(
    connection,
    errors,
):
    expected = (
        "history_meta",
        "sessions",
        "laps",
        "comparisons",
        "episodes",
        "episode_channels",
        "speed_propagations",
        "import_log",
        "pattern_runs",
        "persistent_patterns",
        "persistent_pattern_members",
        "persistent_pattern_pair_evidence",
    )

    for table_name in expected:
        if not table_exists(
            connection,
            table_name,
        ):
            errors.append(
                f"Falta tabla: {table_name}"
            )


VEHICLE_CONTEXT_COLUMNS = {
    "vehicle_family",
    "vehicle_variant",
    "car_class_raw",
    "car_name_raw",
    "vehicle_identity_source",
    "vehicle_supported_domain",
    "weather_conditions",
    "setup_sha256",
    "setup_raw_sha256",
    "setup_available",
    "lmu_session_type",
    "lmu_track_name",
    "lmu_track_layout",
}


def validate_vehicle_context_columns(
    connection,
    errors,
):
    rows = connection.execute(
        "DESCRIBE sessions"
    ).fetchall()

    columns = {
        str(row[0])
        for row in rows
    }

    missing = sorted(
        VEHICLE_CONTEXT_COLUMNS
        -
        columns
    )

    for name in missing:
        errors.append(
            f"Falta columna de vehicle context: sessions.{name}"
        )


def validate_vehicle_context(
    connection,
    errors,
    warnings,
):
    rows = connection.execute(
        """
        SELECT
            session_id,
            vehicle_family,
            vehicle_variant,
            car_class_raw,
            car_name_raw,
            vehicle_identity_source,
            vehicle_supported_domain,
            setup_sha256,
            setup_raw_sha256,
            setup_available,
            lmu_track_name,
            lmu_track_layout,
            track
        FROM sessions
        ORDER BY session_id
        """
    ).fetchall()

    sha_pattern = re.compile(
        r"^[0-9a-f]{64}$"
    )

    for row in rows:
        (
            session_id,
            family,
            variant,
            class_raw,
            car_name,
            source,
            supported,
            setup_hash,
            setup_raw_hash,
            setup_available,
            lmu_track_name,
            lmu_track_layout,
            track,
        ) = row

        if not any((
            family,
            variant,
            class_raw,
            car_name,
            source,
        )):
            warnings.append(
                f"session {session_id}: legacy session without vehicle context; "
                "excluded from cross-session matching."
            )
            continue

        if class_raw and not variant:
            errors.append(
                f"session {session_id}: car_class_raw existe pero "
                "vehicle_variant es NULL."
            )

        if variant and not family:
            errors.append(
                f"session {session_id}: vehicle_variant existe pero "
                "vehicle_family es NULL."
            )

        if variant and supported is not True:
            errors.append(
                f"session {session_id}: variante conocida sin "
                "vehicle_supported_domain=true."
            )

        raw_token = (
            str(class_raw).strip().upper()
            if class_raw
            else None
        )

        if raw_token == "LMP2_ELMS":
            if family != "LMP2" or variant != "LMP2_ELMS":
                errors.append(
                    f"session {session_id}: LMP2_ELMS debe conservarse "
                    "como family=LMP2, variant=LMP2_ELMS."
                )

        if raw_token == "LMP2":
            if family != "LMP2" or variant != "LMP2_WEC":
                errors.append(
                    f"session {session_id}: LMP2 raw debe mapear a "
                    "family=LMP2, variant=LMP2_WEC."
                )

        for label, value in (
            ("setup_sha256", setup_hash),
            ("setup_raw_sha256", setup_raw_hash),
        ):
            if value is not None and not sha_pattern.match(str(value)):
                errors.append(
                    f"session {session_id}: {label} inválido."
                )

        if setup_hash is not None and setup_available is not True:
            errors.append(
                f"session {session_id}: setup hash presente pero "
                "setup_available no es true."
            )

        if (
            lmu_track_name
            and
            track
            and
            str(lmu_track_name).strip() != str(track).strip()
        ):
            warnings.append(
                f"session {session_id}: track filename/context difiere: "
                f"track={track!r}, lmu_track_name={lmu_track_name!r}."
            )

        if not lmu_track_layout:
            warnings.append(
                f"session {session_id}: lmu_track_layout ausente; "
                "la sesión queda almacenada pero no es elegible para "
                "matching cross-session H2."
            )


def validate_schema_version(
    connection,
    errors,
):
    if not table_exists(
        connection,
        "history_meta",
    ):
        return

    rows = connection.execute(
        """
        SELECT
            schema_version
        FROM history_meta
        """
    ).fetchall()

    if len(rows) != 1:
        errors.append(
            "history_meta debe contener "
            "exactamente una fila."
        )
        return

    version = safe_int(
        rows[0][0]
    )

    if version != EXPECTED_SCHEMA_VERSION:
        errors.append(
            "Schema version incompatible: "
            f"{version}"
        )


def validate_unique_hashes(
    connection,
    errors,
):
    rows = connection.execute(
        """
        SELECT
            source_json_sha256,
            COUNT(*)
        FROM sessions
        GROUP BY source_json_sha256
        HAVING COUNT(*) > 1
        """
    ).fetchall()

    for source_hash, count in rows:
        errors.append(
            "Hash duplicado en sessions: "
            f"{source_hash} ({count} filas)"
        )


def validate_session_counts(
    connection,
    errors,
):
    sessions = connection.execute(
        """
        SELECT
            session_id,
            valid_lap_count,
            discarded_lap_count,
            comparison_count
        FROM sessions
        """
    ).fetchall()

    for row in sessions:
        (
            session_id,
            declared_valid,
            declared_discarded,
            declared_comparisons,
        ) = row

        actual_valid = connection.execute(
            """
            SELECT
                COUNT(*)
            FROM laps
            WHERE
                session_id = ?
                AND is_valid = TRUE
            """,
            [
                session_id
            ],
        ).fetchone()[0]

        actual_discarded = connection.execute(
            """
            SELECT
                COUNT(*)
            FROM laps
            WHERE
                session_id = ?
                AND is_discarded = TRUE
            """,
            [
                session_id
            ],
        ).fetchone()[0]

        actual_comparisons = connection.execute(
            """
            SELECT
                COUNT(*)
            FROM comparisons
            WHERE session_id = ?
            """,
            [
                session_id
            ],
        ).fetchone()[0]

        if safe_int(
            declared_valid
        ) != safe_int(
            actual_valid
        ):
            errors.append(
                f"session {session_id}: "
                f"valid_lap_count declarado="
                f"{declared_valid}, actual={actual_valid}"
            )

        if safe_int(
            declared_discarded
        ) != safe_int(
            actual_discarded
        ):
            errors.append(
                f"session {session_id}: "
                f"discarded_lap_count declarado="
                f"{declared_discarded}, "
                f"actual={actual_discarded}"
            )

        if safe_int(
            declared_comparisons
        ) != safe_int(
            actual_comparisons
        ):
            errors.append(
                f"session {session_id}: "
                f"comparison_count declarado="
                f"{declared_comparisons}, "
                f"actual={actual_comparisons}"
            )


def validate_reference_laps(
    connection,
    errors,
):
    sessions = connection.execute(
        """
        SELECT
            session_id,
            reference_lap
        FROM sessions
        """
    ).fetchall()

    for session_id, reference_lap in sessions:
        rows = connection.execute(
            """
            SELECT
                lap,
                is_reference,
                is_valid
            FROM laps
            WHERE session_id = ?
            """,
            [
                session_id
            ],
        ).fetchall()

        marked = [
            safe_int(lap)
            for lap, is_reference, _
            in rows
            if is_reference
        ]

        if marked != [
            safe_int(reference_lap)
        ]:
            errors.append(
                f"session {session_id}: "
                f"reference markers={marked}, "
                f"expected={[safe_int(reference_lap)]}"
            )

        ref_rows = [
            row
            for row in rows
            if safe_int(
                row[0]
            )
            ==
            safe_int(
                reference_lap
            )
        ]

        if not ref_rows:
            errors.append(
                f"session {session_id}: "
                "reference_lap no existe en laps."
            )
        elif not bool(
            ref_rows[0][2]
        ):
            errors.append(
                f"session {session_id}: "
                "reference_lap no está marcada válida."
            )


def validate_comparison_temporal_math(
    connection,
    errors,
):
    rows = connection.execute(
        """
        SELECT
            comparison_id,
            reference_time_s,
            comparison_time_s,
            comparison_minus_reference_s,
            calculated_delta_s,
            gross_loss_s,
            gross_gain_s,
            neutral_delta_s,
            net_from_components_s,
            accounting_error_s
        FROM comparisons
        """
    ).fetchall()

    for row in rows:
        (
            comparison_id,
            reference_time,
            comparison_time,
            real_delta,
            calculated_delta,
            gross_loss,
            gross_gain,
            neutral_delta,
            net_components,
            accounting_error,
        ) = row

        reference_time = safe_float(
            reference_time
        )

        comparison_time = safe_float(
            comparison_time
        )

        real_delta = safe_float(
            real_delta
        )

        if (
            reference_time is not None
            and
            comparison_time is not None
            and
            real_delta is not None
        ):
            expected_delta = (
                comparison_time
                -
                reference_time
            )

            if not approx_equal(
                expected_delta,
                real_delta,
                tolerance=1e-6,
            ):
                errors.append(
                    f"comparison {comparison_id}: "
                    f"lap delta inconsistente. "
                    f"expected={expected_delta}, "
                    f"stored={real_delta}"
                )

        calculated_delta = safe_float(
            calculated_delta
        )

        if (
            calculated_delta is not None
            and
            real_delta is not None
            and
            not approx_equal(
                calculated_delta,
                real_delta,
                tolerance=1e-6,
            )
        ):
            errors.append(
                f"comparison {comparison_id}: "
                "calculated_delta_s != "
                "comparison_minus_reference_s."
            )

        gross_loss = safe_float(
            gross_loss
        )

        gross_gain = safe_float(
            gross_gain
        )

        neutral_delta = safe_float(
            neutral_delta
        )

        net_components = safe_float(
            net_components
        )

        if (
            gross_loss is not None
            and
            gross_gain is not None
            and
            neutral_delta is not None
            and
            net_components is not None
        ):
            expected_net = (
                gross_loss
                -
                gross_gain
                +
                neutral_delta
            )

            if not approx_equal(
                expected_net,
                net_components,
                tolerance=1e-6,
            ):
                errors.append(
                    f"comparison {comparison_id}: "
                    "gross_loss - gross_gain + neutral_delta "
                    "no coincide con net_from_components."
                )

        accounting_error = safe_float(
            accounting_error
        )

        if (
            accounting_error is not None
            and
            abs(
                accounting_error
            ) > 1e-6
        ):
            errors.append(
                f"comparison {comparison_id}: "
                f"accounting_error_s="
                f"{accounting_error}"
            )


def validate_orphans(
    connection,
    errors,
):
    checks = [
        (
            "laps -> sessions",
            """
            SELECT COUNT(*)
            FROM laps l
            LEFT JOIN sessions s
                ON s.session_id = l.session_id
            WHERE s.session_id IS NULL
            """,
        ),
        (
            "comparisons -> sessions",
            """
            SELECT COUNT(*)
            FROM comparisons c
            LEFT JOIN sessions s
                ON s.session_id = c.session_id
            WHERE s.session_id IS NULL
            """,
        ),
        (
            "episodes -> comparisons",
            """
            SELECT COUNT(*)
            FROM episodes e
            LEFT JOIN comparisons c
                ON c.comparison_id = e.comparison_id
            WHERE c.comparison_id IS NULL
            """,
        ),
        (
            "episodes -> sessions",
            """
            SELECT COUNT(*)
            FROM episodes e
            LEFT JOIN sessions s
                ON s.session_id = e.session_id
            WHERE s.session_id IS NULL
            """,
        ),
        (
            "episode_channels -> episodes",
            """
            SELECT COUNT(*)
            FROM episode_channels ec
            LEFT JOIN episodes e
                ON e.episode_pk = ec.episode_pk
            WHERE e.episode_pk IS NULL
            """,
        ),
        (
            "speed_propagations -> episodes",
            """
            SELECT COUNT(*)
            FROM speed_propagations sp
            LEFT JOIN episodes e
                ON e.episode_pk = sp.episode_pk
            WHERE e.episode_pk IS NULL
            """,
        ),
    ]

    for label, sql in checks:
        count = connection.execute(
            sql
        ).fetchone()[0]

        if count:
            errors.append(
                f"Orphans {label}: {count}"
            )


def validate_episode_ids(
    connection,
    errors,
):
    comparisons = connection.execute(
        """
        SELECT
            comparison_id
        FROM comparisons
        """
    ).fetchall()

    for (comparison_id,) in comparisons:
        ids = [
            safe_int(
                row[0]
            )
            for row in connection.execute(
                """
                SELECT
                    episode_id
                FROM episodes
                WHERE comparison_id = ?
                ORDER BY episode_id
                """,
                [
                    comparison_id
                ],
            ).fetchall()
        ]

        expected = list(
            range(
                1,
                len(ids) + 1,
            )
        )

        if ids != expected:
            errors.append(
                f"comparison {comparison_id}: "
                f"episode_ids={ids}, "
                f"expected={expected}"
            )


def validate_episode_geometry(
    connection,
    errors,
):
    rows = connection.execute(
        """
        SELECT
            e.episode_pk,
            e.session_id,
            e.start_distance_m,
            e.end_distance_m,
            e.center_distance_m,
            e.length_m,
            e.start_lap_fraction,
            e.end_lap_fraction,
            e.center_lap_fraction,
            s.reference_distance_m
        FROM episodes e
        JOIN sessions s
            ON s.session_id = e.session_id
        """
    ).fetchall()

    for row in rows:
        (
            episode_pk,
            session_id,
            start,
            end,
            center,
            length,
            start_fraction,
            end_fraction,
            center_fraction,
            reference_distance,
        ) = row

        start = safe_float(
            start
        )

        end = safe_float(
            end
        )

        center = safe_float(
            center
        )

        length = safe_float(
            length
        )

        reference_distance = safe_float(
            reference_distance
        )

        if (
            start is None
            or
            end is None
        ):
            errors.append(
                f"episode {episode_pk}: "
                "start/end inválidos."
            )
            continue

        if end < start:
            errors.append(
                f"episode {episode_pk}: "
                "end < start."
            )

        expected_center = (
            start + end
        ) / 2.0

        if (
            center is None
            or
            not approx_equal(
                center,
                expected_center,
                tolerance=1e-8,
            )
        ):
            errors.append(
                f"episode {episode_pk}: "
                "center_distance_m inconsistente."
            )

        expected_length = (
            end - start
        )

        if (
            length is not None
            and
            not approx_equal(
                length,
                expected_length,
                tolerance=1e-6,
            )
        ):
            errors.append(
                f"episode {episode_pk}: "
                "length_m inconsistente."
            )

        if (
            reference_distance is not None
            and
            reference_distance > 0
        ):
            expected_start_fraction = (
                start
                /
                reference_distance
            )

            expected_end_fraction = (
                end
                /
                reference_distance
            )

            expected_center_fraction = (
                expected_center
                /
                reference_distance
            )

            expected = (
                (
                    "start_lap_fraction",
                    start_fraction,
                    expected_start_fraction,
                ),
                (
                    "end_lap_fraction",
                    end_fraction,
                    expected_end_fraction,
                ),
                (
                    "center_lap_fraction",
                    center_fraction,
                    expected_center_fraction,
                ),
            )

            for (
                field,
                stored,
                wanted,
            ) in expected:
                if (
                    safe_float(
                        stored
                    )
                    is None
                    or
                    not approx_equal(
                        stored,
                        wanted,
                        tolerance=1e-8,
                    )
                ):
                    errors.append(
                        f"episode {episode_pk}: "
                        f"{field} inconsistente."
                    )


def validate_episode_channels(
    connection,
    errors,
    warnings,
):
    rows = connection.execute(
        """
        SELECT
            ec.episode_channel_pk,
            ec.episode_pk,
            ec.channel,
            ec.supported_length_m,
            ec.episode_coverage_ratio,
            ec.first_event_start_distance_m,
            ec.last_event_end_distance_m,
            ec.onset_offset_m,
            ec.end_offset_m,
            e.start_distance_m,
            e.end_distance_m,
            e.length_m
        FROM episode_channels ec
        JOIN episodes e
            ON e.episode_pk = ec.episode_pk
        """
    ).fetchall()

    for row in rows:
        (
            row_id,
            episode_pk,
            channel,
            supported_length,
            coverage,
            first_start,
            last_end,
            onset,
            end_offset,
            episode_start,
            episode_end,
            episode_length,
        ) = row

        channel = str(
            channel
        )

        if channel not in (
            ALLOWED_ACTION_CHANNELS
        ):
            errors.append(
                f"episode_channel {row_id}: "
                f"canal no permitido: {channel}"
            )

        supported_length = safe_float(
            supported_length
        )

        coverage = safe_float(
            coverage
        )

        episode_length = safe_float(
            episode_length
        )

        if (
            supported_length is not None
            and
            episode_length is not None
            and
            episode_length > 0
        ):
            expected_coverage = (
                supported_length
                /
                episode_length
            )

            if (
                coverage is None
                or
                not approx_equal(
                    coverage,
                    expected_coverage,
                    tolerance=1e-8,
                )
            ):
                errors.append(
                    f"episode_channel {row_id}: "
                    "coverage inconsistente."
                )

            if coverage > 1.05:
                warnings.append(
                    f"episode_channel {row_id}: "
                    f"coverage > 1 ({coverage}). "
                    "Puede indicar eventos solapados "
                    "sumados en supported_length."
                )

        first_start = safe_float(
            first_start
        )

        episode_start = safe_float(
            episode_start
        )

        onset = safe_float(
            onset
        )

        if (
            first_start is not None
            and
            episode_start is not None
        ):
            expected_onset = (
                first_start
                -
                episode_start
            )

            if (
                onset is None
                or
                not approx_equal(
                    onset,
                    expected_onset,
                    tolerance=1e-8,
                )
            ):
                errors.append(
                    f"episode_channel {row_id}: "
                    "onset_offset_m inconsistente."
                )

        last_end = safe_float(
            last_end
        )

        episode_end = safe_float(
            episode_end
        )

        end_offset = safe_float(
            end_offset
        )

        if (
            last_end is not None
            and
            episode_end is not None
        ):
            expected_end_offset = (
                episode_end
                -
                last_end
            )

            if (
                end_offset is None
                or
                not approx_equal(
                    end_offset,
                    expected_end_offset,
                    tolerance=1e-8,
                )
            ):
                errors.append(
                    f"episode_channel {row_id}: "
                    "end_offset_m inconsistente."
                )


def validate_speed_propagations(
    connection,
    errors,
):
    rows = connection.execute(
        """
        SELECT
            sp.speed_propagation_pk,
            sp.episode_pk,
            sp.start_distance_m,
            sp.end_distance_m,
            sp.center_distance_m,
            sp.length_m,
            sp.start_lap_fraction,
            sp.end_lap_fraction,
            sp.center_lap_fraction,
            s.reference_distance_m
        FROM speed_propagations sp
        JOIN episodes e
            ON e.episode_pk = sp.episode_pk
        JOIN sessions s
            ON s.session_id = e.session_id
        """
    ).fetchall()

    for row in rows:
        (
            row_id,
            episode_pk,
            start,
            end,
            center,
            length,
            start_fraction,
            end_fraction,
            center_fraction,
            reference_distance,
        ) = row

        start = safe_float(
            start
        )

        end = safe_float(
            end
        )

        center = safe_float(
            center
        )

        length = safe_float(
            length
        )

        if (
            start is None
            or
            end is None
        ):
            errors.append(
                f"speed_propagation {row_id}: "
                "start/end inválidos."
            )
            continue

        if end < start:
            errors.append(
                f"speed_propagation {row_id}: "
                "end < start."
            )

        expected_center = (
            start + end
        ) / 2.0

        if (
            center is None
            or
            not approx_equal(
                center,
                expected_center,
                tolerance=1e-8,
            )
        ):
            errors.append(
                f"speed_propagation {row_id}: "
                "center inconsistente."
            )

        if (
            length is not None
            and
            not approx_equal(
                length,
                end - start,
                tolerance=1e-6,
            )
        ):
            errors.append(
                f"speed_propagation {row_id}: "
                "length inconsistente."
            )

        reference_distance = safe_float(
            reference_distance
        )

        if (
            reference_distance is not None
            and
            reference_distance > 0
        ):
            checks = (
                (
                    start_fraction,
                    start / reference_distance,
                    "start fraction",
                ),
                (
                    end_fraction,
                    end / reference_distance,
                    "end fraction",
                ),
                (
                    center_fraction,
                    expected_center
                    / reference_distance,
                    "center fraction",
                ),
            )

            for stored, wanted, label in checks:
                if (
                    safe_float(
                        stored
                    )
                    is None
                    or
                    not approx_equal(
                        stored,
                        wanted,
                        tolerance=1e-8,
                    )
                ):
                    errors.append(
                        f"speed_propagation {row_id}: "
                        f"{label} inconsistente."
                    )





def validate_pattern_layer(connection, errors, warnings):
    allowed_states = {
        "single_observation",
        "cross_session_repeat",
        "persistent_pattern",
        "conflict_review_required",
    }

    # Pattern runs are immutable bundles identified by source hashes.
    dup_runs = connection.execute(
        """
        SELECT source_bundle_sha256, COUNT(*)
        FROM pattern_runs
        GROUP BY source_bundle_sha256
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for bundle_hash, count in dup_runs:
        errors.append(
            f"pattern_runs bundle hash duplicado: {bundle_hash} ({count})"
        )

    sha_pattern = re.compile(r"^[0-9a-f]{64}$")
    run_rows = connection.execute(
        """
        SELECT
            pattern_run_id,
            source_patterns_sha256,
            source_matches_sha256,
            source_bundle_sha256,
            h3_version,
            matcher_version,
            persistent_min_independent_sessions,
            track, track_layout, vehicle_variant,
            pattern_count, episode_count,
            single_observation_count,
            cross_session_repeat_count,
            persistent_pattern_count,
            conflict_review_required_count,
            match_edge_count,
            transitively_resolved_ambiguous_pair_count,
            metadata_json
        FROM pattern_runs
        ORDER BY pattern_run_id
        """
    ).fetchall()

    for row in run_rows:
        (
            run_id, patterns_sha, matches_sha, bundle_sha,
            h3_version, matcher_version, min_sessions,
            track, layout, variant,
            declared_patterns, declared_episodes,
            declared_single, declared_repeat, declared_persistent, declared_conflict,
            declared_match_edges, declared_transitive_ambig,
            metadata_json,
        ) = row

        for label, value in (
            ("source_patterns_sha256", patterns_sha),
            ("source_matches_sha256", matches_sha),
            ("source_bundle_sha256", bundle_sha),
        ):
            if not isinstance(value, str) or not sha_pattern.match(value):
                errors.append(f"pattern_run {run_id}: {label} inválido")

        if not h3_version or not matcher_version:
            errors.append(f"pattern_run {run_id}: provenance version incompleta")
        if safe_int(min_sessions) is None or safe_int(min_sessions) < 3:
            errors.append(f"pattern_run {run_id}: persistent_min_independent_sessions inválido")
        if not track or not layout or not variant:
            errors.append(f"pattern_run {run_id}: contexto incompleto")

        try:
            metadata = json.loads(metadata_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = None
            errors.append(f"pattern_run {run_id}: metadata_json inválido")
        if isinstance(metadata, dict) and metadata.get("h3_pipeline_version"):
            source_features_sha = str(metadata.get("source_features_sha256") or "")
            if not sha_pattern.match(source_features_sha):
                errors.append(
                    f"pattern_run {run_id}: source_features_sha256 oficial inválido"
                )
            for field in (
                "authorized_matcher_version",
                "track_baseline_policy_version",
                "match_promotion_policy_version",
            ):
                if not metadata.get(field):
                    errors.append(
                        f"pattern_run {run_id}: provenance oficial ausente {field}"
                    )
            gate = metadata.get("h2_authority_gate")
            if not isinstance(gate, dict):
                errors.append(f"pattern_run {run_id}: h2_authority_gate inválido")
            else:
                if safe_int(gate.get("inherited_reject_count")) != 0:
                    errors.append(f"pattern_run {run_id}: inherited REJECT persistido")
                if safe_int(gate.get("unauthorized_match_count")) != 0:
                    errors.append(f"pattern_run {run_id}: MATCH no autorizado persistido")

            authority_rows = connection.execute(
                """
                SELECT decision, raw_decision_json
                FROM persistent_pattern_pair_evidence
                WHERE pattern_run_id = ?
                """,
                [run_id],
            ).fetchall()
            for decision, raw_json in authority_rows:
                try:
                    raw = json.loads(raw_json or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    errors.append(
                        f"pattern_run {run_id}: raw_decision_json inválido"
                    )
                    continue
                authority = raw.get("authority") or {}
                scope = authority.get("calibration_scope")
                if scope == "COVERED_BY_TRACK_MATCH_BASELINE":
                    if decision == "REJECT":
                        errors.append(
                            f"pattern_run {run_id}: REJECT heredado persistido"
                        )
                    if authority.get("production_reject_authorized") is not False:
                        errors.append(
                            f"pattern_run {run_id}: baseline elevó autoridad REJECT"
                        )

        actual_patterns = connection.execute(
            "SELECT COUNT(*) FROM persistent_patterns WHERE pattern_run_id = ?",
            [run_id],
        ).fetchone()[0]
        if safe_int(declared_patterns) != actual_patterns:
            errors.append(
                f"pattern_run {run_id}: pattern_count={declared_patterns} actual={actual_patterns}"
            )

        actual_members = connection.execute(
            "SELECT COUNT(*) FROM persistent_pattern_members WHERE pattern_run_id = ?",
            [run_id],
        ).fetchone()[0]
        if safe_int(declared_episodes) != actual_members:
            errors.append(
                f"pattern_run {run_id}: episode_count={declared_episodes} actual_members={actual_members}"
            )

        state_rows = connection.execute(
            """
            SELECT state, COUNT(*)
            FROM persistent_patterns
            WHERE pattern_run_id = ?
            GROUP BY state
            """,
            [run_id],
        ).fetchall()
        state_counts = {str(s): int(c) for s, c in state_rows}
        wanted = {
            "single_observation": safe_int(declared_single) or 0,
            "cross_session_repeat": safe_int(declared_repeat) or 0,
            "persistent_pattern": safe_int(declared_persistent) or 0,
            "conflict_review_required": safe_int(declared_conflict) or 0,
        }
        for state, count in wanted.items():
            if state_counts.get(state, 0) != count:
                errors.append(
                    f"pattern_run {run_id}: state count {state}={state_counts.get(state,0)} declared={count}"
                )

        actual_match_edges = connection.execute(
            """
            SELECT COUNT(*)
            FROM persistent_pattern_pair_evidence
            WHERE pattern_run_id = ? AND decision = 'MATCH'
            """,
            [run_id],
        ).fetchone()[0]
        if safe_int(declared_match_edges) != actual_match_edges:
            errors.append(
                f"pattern_run {run_id}: match_edge_count={declared_match_edges} actual={actual_match_edges}"
            )

        actual_ambig = connection.execute(
            """
            SELECT COUNT(*)
            FROM persistent_pattern_pair_evidence
            WHERE pattern_run_id = ? AND decision = 'AMBIGUOUS'
            """,
            [run_id],
        ).fetchone()[0]
        if safe_int(declared_transitive_ambig) != actual_ambig:
            errors.append(
                f"pattern_run {run_id}: transitive ambiguous={declared_transitive_ambig} actual={actual_ambig}"
            )

    pattern_rows = connection.execute(
        """
        SELECT
            p.pattern_pk, p.pattern_run_id, p.pattern_id, p.state,
            p.track, p.track_layout, p.vehicle_variant,
            p.observation_count, p.independent_session_count,
            p.representative_session_id, p.representative_episode_pk,
            p.direct_match_edge_count, p.internal_ambiguous_pair_count,
            p.internal_reject_pair_count,
            p.missing_internal_cross_session_pair_count,
            r.persistent_min_independent_sessions
        FROM persistent_patterns p
        JOIN pattern_runs r ON r.pattern_run_id = p.pattern_run_id
        ORDER BY p.pattern_pk
        """
    ).fetchall()

    for row in pattern_rows:
        (
            pattern_pk, run_id, pattern_id, state,
            track, layout, variant,
            obs_count, session_count,
            rep_session, rep_episode,
            direct_matches, internal_ambig, internal_reject, missing_internal,
            min_sessions,
        ) = row

        if state not in allowed_states:
            errors.append(f"pattern {pattern_id}: state inválido {state!r}")
            continue

        actual_member_count = connection.execute(
            "SELECT COUNT(*) FROM persistent_pattern_members WHERE pattern_pk = ?",
            [pattern_pk],
        ).fetchone()[0]
        if safe_int(obs_count) != actual_member_count:
            errors.append(
                f"pattern {pattern_id}: observation_count={obs_count} members={actual_member_count}"
            )

        actual_sessions = connection.execute(
            """
            SELECT COUNT(DISTINCT session_id)
            FROM persistent_pattern_members
            WHERE pattern_pk = ?
            """,
            [pattern_pk],
        ).fetchone()[0]
        if safe_int(session_count) != actual_sessions:
            errors.append(
                f"pattern {pattern_id}: independent_session_count={session_count} actual={actual_sessions}"
            )

        if state == "persistent_pattern" and actual_sessions < safe_int(min_sessions):
            errors.append(f"pattern {pattern_id}: persistent_pattern con pocas sesiones")
        if state == "cross_session_repeat" and not (2 <= actual_sessions < safe_int(min_sessions)):
            errors.append(f"pattern {pattern_id}: cross_session_repeat con session_count inválido")
        if state == "single_observation" and actual_member_count != 1:
            errors.append(f"pattern {pattern_id}: single_observation con members != 1")
        if state != "conflict_review_required" and ((safe_int(internal_reject) or 0) or (safe_int(missing_internal) or 0)):
            errors.append(f"pattern {pattern_id}: conflicto/incompletitud sin conflict_review_required")

        actual_evidence = connection.execute(
            """
            SELECT
                SUM(CASE WHEN decision = 'MATCH' THEN 1 ELSE 0 END),
                SUM(CASE WHEN decision = 'AMBIGUOUS' THEN 1 ELSE 0 END),
                SUM(CASE WHEN decision = 'REJECT' THEN 1 ELSE 0 END)
            FROM persistent_pattern_pair_evidence
            WHERE pattern_pk = ?
            """,
            [pattern_pk],
        ).fetchone()
        m = safe_int(actual_evidence[0]) or 0
        a = safe_int(actual_evidence[1]) or 0
        rj = safe_int(actual_evidence[2]) or 0
        if m != (safe_int(direct_matches) or 0):
            errors.append(f"pattern {pattern_id}: direct_match_edge_count inconsistente")
        if a != (safe_int(internal_ambig) or 0):
            errors.append(f"pattern {pattern_id}: internal_ambiguous_pair_count inconsistente")
        if rj != (safe_int(internal_reject) or 0):
            errors.append(f"pattern {pattern_id}: internal_reject_pair_count inconsistente")

        if rep_episode is not None:
            rep = connection.execute(
                """
                SELECT COUNT(*)
                FROM persistent_pattern_members
                WHERE pattern_pk = ? AND session_id = ? AND episode_pk = ?
                """,
                [pattern_pk, rep_session, rep_episode],
            ).fetchone()[0]
            if rep != 1:
                errors.append(f"pattern {pattern_id}: representative_member no pertenece al pattern")

        context_bad = connection.execute(
            """
            SELECT COUNT(*)
            FROM persistent_pattern_members pm
            JOIN sessions s ON s.session_id = pm.session_id
            JOIN episodes e ON e.episode_pk = pm.episode_pk
            WHERE pm.pattern_pk = ?
              AND (
                    e.session_id <> pm.session_id
                 OR s.track <> ?
                 OR s.lmu_track_layout <> ?
                 OR s.vehicle_variant <> ?
              )
            """,
            [pattern_pk, track, layout, variant],
        ).fetchone()[0]
        if context_bad:
            errors.append(f"pattern {pattern_id}: {context_bad} member(s) con contexto/identity inconsistente")

        evidence_bad = connection.execute(
            """
            SELECT COUNT(*)
            FROM persistent_pattern_pair_evidence pe
            WHERE pe.pattern_pk = ?
              AND (
                NOT EXISTS (
                    SELECT 1 FROM persistent_pattern_members ma
                    WHERE ma.pattern_pk = pe.pattern_pk
                      AND ma.session_id = pe.session_a
                      AND ma.episode_pk = pe.episode_pk_a
                )
                OR NOT EXISTS (
                    SELECT 1 FROM persistent_pattern_members mb
                    WHERE mb.pattern_pk = pe.pattern_pk
                      AND mb.session_id = pe.session_b
                      AND mb.episode_pk = pe.episode_pk_b
                )
              )
            """,
            [pattern_pk],
        ).fetchone()[0]
        if evidence_bad:
            errors.append(f"pattern {pattern_id}: pair evidence apunta fuera de members")

    duplicates = connection.execute(
        """
        SELECT pattern_run_id, episode_pk, COUNT(*)
        FROM persistent_pattern_members
        GROUP BY pattern_run_id, episode_pk
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for run_id, episode_pk, count in duplicates:
        errors.append(
            f"pattern_run {run_id}: episode_pk {episode_pk} aparece {count} veces en pattern members"
        )


def print_database_summary(
    connection,
):
    counts = {}

    for table in (
        "sessions",
        "laps",
        "comparisons",
        "episodes",
        "episode_channels",
        "speed_propagations",
        "import_log",
        "pattern_runs",
        "persistent_patterns",
        "persistent_pattern_members",
        "persistent_pattern_pair_evidence",
    ):
        if table_exists(
            connection,
            table,
        ):
            counts[table] = (
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table}
                    """
                ).fetchone()[0]
            )

    print()
    print(
        "DB SUMMARY"
    )

    print(
        "-" * 60
    )

    for table, count in counts.items():
        print(
            f"{table}: {count}"
        )


def validate_database(
    connection,
):
    errors = []
    warnings = []

    require_tables(
        connection,
        errors,
    )

    if errors:
        return errors, warnings

    validate_schema_version(
        connection,
        errors,
    )

    validate_vehicle_context_columns(
        connection,
        errors,
    )

    if errors:
        return errors, warnings

    validate_vehicle_context(
        connection,
        errors,
        warnings,
    )

    validate_unique_hashes(
        connection,
        errors,
    )

    validate_orphans(
        connection,
        errors,
    )

    validate_session_counts(
        connection,
        errors,
    )

    validate_reference_laps(
        connection,
        errors,
    )

    validate_comparison_temporal_math(
        connection,
        errors,
    )

    validate_episode_ids(
        connection,
        errors,
    )

    validate_episode_geometry(
        connection,
        errors,
    )

    validate_episode_channels(
        connection,
        errors,
        warnings,
    )

    validate_speed_propagations(
        connection,
        errors,
    )

    validate_pattern_layer(
        connection,
        errors,
        warnings,
    )

    return errors, warnings


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Valida integridad de "
            "race_engineer_history.duckdb."
        )
    )

    parser.add_argument(
        "--db",
        default=default_db_path(),
    )

    return parser


def main():
    parser = build_parser()

    args = parser.parse_args()

    db_path = os.path.abspath(
        args.db
    )

    print()
    print(
        "=" * 70
    )

    print(
        "RACE ENGINEER - HISTORY DB VALIDATOR v1.3"
    )

    print(
        "=" * 70
    )

    print()

    print(
        f"DB: {db_path}"
    )

    if not os.path.exists(
        db_path
    ):
        print()
        print(
            "FAIL: la base no existe."
        )
        sys.exit(2)

    connection = duckdb.connect(
        db_path,
        read_only=True,
    )

    try:
        errors, warnings = (
            validate_database(
                connection
            )
        )

        print_database_summary(
            connection
        )

    finally:
        connection.close()

    print()

    if warnings:
        print(
            "WARNINGS"
        )

        print(
            "-" * 60
        )

        for warning in warnings:
            print(
                f"- {warning}"
            )

        print()

    if errors:
        print(
            "HISTORY VALIDATION: FAIL"
        )

        print(
            "-" * 60
        )

        for error in errors:
            print(
                f"- {error}"
            )

        print()

        print(
            f"Errors: {len(errors)}"
        )

        sys.exit(1)

    print(
        "HISTORY VALIDATION: PASS"
    )

    print(
        f"Warnings: {len(warnings)}"
    )

    print()

    print(
        "La base es internamente consistente "
        "para continuar con calibración."
    )


if __name__ == "__main__":
    main()
