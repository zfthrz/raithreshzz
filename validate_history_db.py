import argparse
import math
import os
import sys

import duckdb


# ============================================================
# RACE ENGINEER - HISTORY DB VALIDATOR v1.0
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

EXPECTED_SCHEMA_VERSION = 1

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
    )

    for table_name in expected:
        if not table_exists(
            connection,
            table_name,
        ):
            errors.append(
                f"Falta tabla: {table_name}"
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

        net_components = safe_float(
            net_components
        )

        if (
            gross_loss is not None
            and
            gross_gain is not None
            and
            net_components is not None
        ):
            expected_net = (
                gross_loss
                -
                gross_gain
            )

            if not approx_equal(
                expected_net,
                net_components,
                tolerance=1e-6,
            ):
                errors.append(
                    f"comparison {comparison_id}: "
                    "gross_loss - gross_gain "
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
        "RACE ENGINEER - HISTORY DB VALIDATOR v1.0"
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
