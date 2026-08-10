import argparse
import csv
import json
import math
import os
import sys

import duckdb


# ============================================================
# RACE ENGINEER - EPISODE PAIR FEATURES v1.0
# ============================================================
#
# Extrae features neutrales entre episodios de distintas
# sesiones del mismo circuito.
#
# NO decide si dos episodios son equivalentes.
# NO usa thresholds.
# NO etiqueta patrones.
# NO llama a Ollama.
#
# Objetivo:
# producir un dataset para calibrar posteriormente el matcher.
#
# Uso:
#
#   python episode_pair_features.py
#
#   python episode_pair_features.py --track "Autodromo Nazionale Monza"
#
#   python episode_pair_features.py --format csv --output monza_pairs.csv
#
# ============================================================


DEFAULT_DB_NAME = "race_engineer_history.duckdb"


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


def interval_length(
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

    return max(
        0.0,
        end - start,
    )


def interval_overlap(
    start_a,
    end_a,
    start_b,
    end_b,
):
    values = [
        safe_float(start_a),
        safe_float(end_a),
        safe_float(start_b),
        safe_float(end_b),
    ]

    if any(
        value is None
        for value in values
    ):
        return None

    start_a, end_a, start_b, end_b = values

    return max(
        0.0,
        min(
            end_a,
            end_b,
        )
        -
        max(
            start_a,
            start_b,
        ),
    )


def interval_union(
    start_a,
    end_a,
    start_b,
    end_b,
):
    values = [
        safe_float(start_a),
        safe_float(end_a),
        safe_float(start_b),
        safe_float(end_b),
    ]

    if any(
        value is None
        for value in values
    ):
        return None

    start_a, end_a, start_b, end_b = values

    return max(
        0.0,
        max(
            end_a,
            end_b,
        )
        -
        min(
            start_a,
            start_b,
        ),
    )


def safe_ratio(
    numerator,
    denominator,
):
    numerator = safe_float(
        numerator
    )

    denominator = safe_float(
        denominator
    )

    if (
        numerator is None
        or
        denominator is None
        or
        denominator == 0
    ):
        return None

    return (
        numerator
        /
        denominator
    )


def abs_diff(
    a,
    b,
):
    a = safe_float(
        a
    )

    b = safe_float(
        b
    )

    if (
        a is None
        or
        b is None
    ):
        return None

    return abs(
        a - b
    )


def signed_diff(
    a,
    b,
):
    a = safe_float(
        a
    )

    b = safe_float(
        b
    )

    if (
        a is None
        or
        b is None
    ):
        return None

    return (
        b - a
    )


def symmetric_ratio(
    a,
    b,
):
    """
    min(|a|,|b|) / max(|a|,|b|)
    Rango 0..1 cuando ambos son válidos.
    """
    a = safe_float(
        a
    )

    b = safe_float(
        b
    )

    if (
        a is None
        or
        b is None
    ):
        return None

    a = abs(
        a
    )

    b = abs(
        b
    )

    if a == 0 and b == 0:
        return 1.0

    maximum = max(
        a,
        b,
    )

    if maximum == 0:
        return None

    return (
        min(
            a,
            b,
        )
        /
        maximum
    )


def load_episode_channels(
    connection,
):
    rows = connection.execute(
        """
        SELECT
            episode_pk,
            channel
        FROM episode_channels
        """
    ).fetchall()

    result = {}

    for episode_pk, channel in rows:
        episode_pk = safe_int(
            episode_pk
        )

        if episode_pk is None:
            continue

        result.setdefault(
            episode_pk,
            set(),
        ).add(
            str(channel)
        )

    return result


def load_channel_metrics(
    connection,
):
    rows = connection.execute(
        """
        SELECT
            episode_pk,
            channel,
            episode_coverage_ratio,
            onset_offset_m,
            end_offset_m,
            mean_of_event_mean_differences,
            largest_abs_peak_difference,
            direction_consistency
        FROM episode_channels
        """
    ).fetchall()

    result = {}

    for row in rows:
        episode_pk = safe_int(
            row[0]
        )

        if episode_pk is None:
            continue

        result.setdefault(
            episode_pk,
            {},
        )[str(row[1])] = {
            "coverage_ratio":
                safe_float(
                    row[2]
                ),

            "onset_offset_m":
                safe_float(
                    row[3]
                ),

            "end_offset_m":
                safe_float(
                    row[4]
                ),

            "mean_difference":
                safe_float(
                    row[5]
                ),

            "peak_difference":
                safe_float(
                    row[6]
                ),

            "direction_consistency":
                row[7],
        }

    return result


def load_episodes(
    connection,
    track=None,
):
    params = []

    where = ""

    if track:
        where = (
            "WHERE s.track = ?"
        )

        params.append(
            track
        )

    rows = connection.execute(
        f"""
        SELECT
            e.episode_pk,
            e.session_id,
            e.comparison_id,
            e.episode_id,
            e.python_global_rank,

            s.track,
            s.session_type,
            s.timestamp_utc,
            s.reference_distance_m,

            c.reference_lap,
            c.comparison_lap,
            c.driver_analysis_priority_rank,

            e.start_distance_m,
            e.end_distance_m,
            e.center_distance_m,
            e.length_m,

            e.start_lap_fraction,
            e.end_lap_fraction,
            e.center_lap_fraction,

            e.action_time_loss_s,
            e.evidence_strength,
            e.has_speed_propagation
        FROM episodes e
        JOIN sessions s
            ON s.session_id = e.session_id
        JOIN comparisons c
            ON c.comparison_id = e.comparison_id
        {where}
        ORDER BY
            s.track,
            s.timestamp_utc,
            e.session_id,
            e.episode_pk
        """,
        params,
    ).fetchall()

    result = []

    for row in rows:
        result.append({
            "episode_pk":
                safe_int(row[0]),

            "session_id":
                safe_int(row[1]),

            "comparison_id":
                safe_int(row[2]),

            "episode_id":
                safe_int(row[3]),

            "python_global_rank":
                safe_int(row[4]),

            "track":
                row[5],

            "session_type":
                row[6],

            "timestamp_utc":
                row[7],

            "reference_distance_m":
                safe_float(row[8]),

            "reference_lap":
                safe_int(row[9]),

            "comparison_lap":
                safe_int(row[10]),

            "driver_analysis_priority_rank":
                safe_int(row[11]),

            "start_distance_m":
                safe_float(row[12]),

            "end_distance_m":
                safe_float(row[13]),

            "center_distance_m":
                safe_float(row[14]),

            "length_m":
                safe_float(row[15]),

            "start_lap_fraction":
                safe_float(row[16]),

            "end_lap_fraction":
                safe_float(row[17]),

            "center_lap_fraction":
                safe_float(row[18]),

            "action_time_loss_s":
                safe_float(row[19]),

            "evidence_strength":
                row[20],

            "has_speed_propagation":
                bool(row[21]),
        })

    return result


def jaccard(
    set_a,
    set_b,
):
    union = (
        set_a
        |
        set_b
    )

    if not union:
        return 1.0

    return (
        len(
            set_a
            &
            set_b
        )
        /
        len(
            union
        )
    )


def shared_channels(
    set_a,
    set_b,
):
    return sorted(
        set_a
        &
        set_b
    )


def only_a_channels(
    set_a,
    set_b,
):
    return sorted(
        set_a
        -
        set_b
    )


def only_b_channels(
    set_a,
    set_b,
):
    return sorted(
        set_b
        -
        set_a
    )


def normalized_overlap_features(
    a,
    b,
):
    overlap_m = interval_overlap(
        a["start_distance_m"],
        a["end_distance_m"],
        b["start_distance_m"],
        b["end_distance_m"],
    )

    union_m = interval_union(
        a["start_distance_m"],
        a["end_distance_m"],
        b["start_distance_m"],
        b["end_distance_m"],
    )

    length_a = interval_length(
        a["start_distance_m"],
        a["end_distance_m"],
    )

    length_b = interval_length(
        b["start_distance_m"],
        b["end_distance_m"],
    )

    min_length = None

    if (
        length_a is not None
        and
        length_b is not None
    ):
        min_length = min(
            length_a,
            length_b,
        )

    max_length = None

    if (
        length_a is not None
        and
        length_b is not None
    ):
        max_length = max(
            length_a,
            length_b,
        )

    return {
        "overlap_m":
            overlap_m,

        "union_m":
            union_m,

        "overlap_over_union":
            safe_ratio(
                overlap_m,
                union_m,
            ),

        "overlap_over_shorter":
            safe_ratio(
                overlap_m,
                min_length,
            ),

        "overlap_over_longer":
            safe_ratio(
                overlap_m,
                max_length,
            ),

        "length_similarity":
            symmetric_ratio(
                length_a,
                length_b,
            ),
    }


def fraction_overlap_features(
    a,
    b,
):
    overlap = interval_overlap(
        a["start_lap_fraction"],
        a["end_lap_fraction"],
        b["start_lap_fraction"],
        b["end_lap_fraction"],
    )

    union = interval_union(
        a["start_lap_fraction"],
        a["end_lap_fraction"],
        b["start_lap_fraction"],
        b["end_lap_fraction"],
    )

    length_a = interval_length(
        a["start_lap_fraction"],
        a["end_lap_fraction"],
    )

    length_b = interval_length(
        b["start_lap_fraction"],
        b["end_lap_fraction"],
    )

    shorter = None

    if (
        length_a is not None
        and
        length_b is not None
    ):
        shorter = min(
            length_a,
            length_b,
        )

    return {
        "fraction_overlap":
            overlap,

        "fraction_overlap_over_union":
            safe_ratio(
                overlap,
                union,
            ),

        "fraction_overlap_over_shorter":
            safe_ratio(
                overlap,
                shorter,
            ),
    }


def per_channel_pair_metrics(
    channels_a,
    channels_b,
    metrics_a,
    metrics_b,
):
    common = sorted(
        channels_a
        &
        channels_b
    )

    result = {}

    for channel in common:
        a = metrics_a.get(
            channel,
            {},
        )

        b = metrics_b.get(
            channel,
            {},
        )

        result[
            channel
        ] = {
            "coverage_abs_diff":
                abs_diff(
                    a.get(
                        "coverage_ratio"
                    ),
                    b.get(
                        "coverage_ratio"
                    ),
                ),

            "onset_offset_abs_diff_m":
                abs_diff(
                    a.get(
                        "onset_offset_m"
                    ),
                    b.get(
                        "onset_offset_m"
                    ),
                ),

            "end_offset_abs_diff_m":
                abs_diff(
                    a.get(
                        "end_offset_m"
                    ),
                    b.get(
                        "end_offset_m"
                    ),
                ),

            "mean_difference_similarity":
                symmetric_ratio(
                    a.get(
                        "mean_difference"
                    ),
                    b.get(
                        "mean_difference"
                    ),
                ),

            "peak_difference_similarity":
                symmetric_ratio(
                    a.get(
                        "peak_difference"
                    ),
                    b.get(
                        "peak_difference"
                    ),
                ),

            "direction_consistency_a":
                a.get(
                    "direction_consistency"
                ),

            "direction_consistency_b":
                b.get(
                    "direction_consistency"
                ),
        }

    return result


def build_pair_record(
    a,
    b,
    channel_sets,
    channel_metrics,
):
    channels_a = channel_sets.get(
        a["episode_pk"],
        set(),
    )

    channels_b = channel_sets.get(
        b["episode_pk"],
        set(),
    )

    meter_features = (
        normalized_overlap_features(
            a,
            b,
        )
    )

    fraction_features = (
        fraction_overlap_features(
            a,
            b,
        )
    )

    record = {
        "track":
            a["track"],

        "session_a":
            a["session_id"],

        "session_b":
            b["session_id"],

        "timestamp_a":
            a["timestamp_utc"],

        "timestamp_b":
            b["timestamp_utc"],

        "session_type_a":
            a["session_type"],

        "session_type_b":
            b["session_type"],

        "episode_pk_a":
            a["episode_pk"],

        "episode_pk_b":
            b["episode_pk"],

        "episode_id_a":
            a["episode_id"],

        "episode_id_b":
            b["episode_id"],

        "python_rank_a":
            a["python_global_rank"],

        "python_rank_b":
            b["python_global_rank"],

        "priority_rank_a":
            a[
                "driver_analysis_priority_rank"
            ],

        "priority_rank_b":
            b[
                "driver_analysis_priority_rank"
            ],

        "start_distance_a_m":
            a["start_distance_m"],

        "end_distance_a_m":
            a["end_distance_m"],

        "center_distance_a_m":
            a["center_distance_m"],

        "start_distance_b_m":
            b["start_distance_m"],

        "end_distance_b_m":
            b["end_distance_m"],

        "center_distance_b_m":
            b["center_distance_m"],

        "center_distance_abs_diff_m":
            abs_diff(
                a["center_distance_m"],
                b["center_distance_m"],
            ),

        "start_distance_abs_diff_m":
            abs_diff(
                a["start_distance_m"],
                b["start_distance_m"],
            ),

        "end_distance_abs_diff_m":
            abs_diff(
                a["end_distance_m"],
                b["end_distance_m"],
            ),

        "center_fraction_a":
            a["center_lap_fraction"],

        "center_fraction_b":
            b["center_lap_fraction"],

        "center_fraction_abs_diff":
            abs_diff(
                a["center_lap_fraction"],
                b["center_lap_fraction"],
            ),

        "start_fraction_abs_diff":
            abs_diff(
                a["start_lap_fraction"],
                b["start_lap_fraction"],
            ),

        "end_fraction_abs_diff":
            abs_diff(
                a["end_lap_fraction"],
                b["end_lap_fraction"],
            ),

        "action_time_loss_a_s":
            a["action_time_loss_s"],

        "action_time_loss_b_s":
            b["action_time_loss_s"],

        "action_time_loss_similarity":
            symmetric_ratio(
                a["action_time_loss_s"],
                b["action_time_loss_s"],
            ),

        "evidence_strength_a":
            a["evidence_strength"],

        "evidence_strength_b":
            b["evidence_strength"],

        "speed_propagation_a":
            a["has_speed_propagation"],

        "speed_propagation_b":
            b["has_speed_propagation"],

        "channels_a":
            sorted(
                channels_a
            ),

        "channels_b":
            sorted(
                channels_b
            ),

        "shared_channels":
            shared_channels(
                channels_a,
                channels_b,
            ),

        "channels_only_a":
            only_a_channels(
                channels_a,
                channels_b,
            ),

        "channels_only_b":
            only_b_channels(
                channels_a,
                channels_b,
            ),

        "channel_jaccard":
            jaccard(
                channels_a,
                channels_b,
            ),

        "per_channel_metrics":
            per_channel_pair_metrics(
                channels_a,
                channels_b,
                channel_metrics.get(
                    a["episode_pk"],
                    {},
                ),
                channel_metrics.get(
                    b["episode_pk"],
                    {},
                ),
            ),
    }

    record.update(
        meter_features
    )

    record.update(
        fraction_features
    )

    return record


def build_all_cross_session_pairs(
    episodes,
    channel_sets,
    channel_metrics,
):
    pairs = []

    for i in range(
        len(episodes)
    ):
        a = episodes[i]

        for j in range(
            i + 1,
            len(episodes),
        ):
            b = episodes[j]

            if (
                a["session_id"]
                ==
                b["session_id"]
            ):
                continue

            if (
                a["track"]
                !=
                b["track"]
            ):
                continue

            pairs.append(
                build_pair_record(
                    a,
                    b,
                    channel_sets,
                    channel_metrics,
                )
            )

    return pairs


def flatten_for_csv(
    record,
):
    result = {}

    for key, value in record.items():
        if isinstance(
            value,
            (
                dict,
                list,
            ),
        ):
            result[key] = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        else:
            result[key] = value

    return result


def write_json(
    path,
    pairs,
):
    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            pairs,
            file,
            indent=2,
            ensure_ascii=False,
        )


def write_csv(
    path,
    pairs,
):
    flattened = [
        flatten_for_csv(
            pair
        )
        for pair in pairs
    ]

    if not flattened:
        with open(
            path,
            "w",
            encoding="utf-8",
            newline="",
        ) as file:
            file.write("")
        return

    fieldnames = list(
        flattened[0].keys()
    )

    with open(
        path,
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        writer.writerows(
            flattened
        )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Extrae features neutrales "
            "entre episodios de distintas sesiones."
        )
    )

    parser.add_argument(
        "--db",
        default=default_db_path(),
    )

    parser.add_argument(
        "--track",
        default=None,
    )

    parser.add_argument(
        "--format",
        choices=(
            "json",
            "csv",
        ),
        default="json",
    )

    parser.add_argument(
        "--output",
        default=None,
    )

    return parser


def main():
    parser = build_parser()

    args = parser.parse_args()

    db_path = os.path.abspath(
        args.db
    )

    if not os.path.exists(
        db_path
    ):
        raise FileNotFoundError(
            db_path
        )

    connection = duckdb.connect(
        db_path,
        read_only=True,
    )

    try:
        episodes = load_episodes(
            connection,
            track=args.track,
        )

        channel_sets = (
            load_episode_channels(
                connection
            )
        )

        channel_metrics = (
            load_channel_metrics(
                connection
            )
        )

        pairs = (
            build_all_cross_session_pairs(
                episodes,
                channel_sets,
                channel_metrics,
            )
        )

    finally:
        connection.close()

    print()
    print(
        "=" * 70
    )

    print(
        "RACE ENGINEER - EPISODE PAIR FEATURES v1.0"
    )

    print(
        "=" * 70
    )

    print()

    print(
        f"Episodes loaded: {len(episodes)}"
    )

    print(
        f"Cross-session pairs: {len(pairs)}"
    )

    if args.track:
        print(
            f"Track filter: {args.track}"
        )

    output = args.output

    if output is None:
        suffix = (
            ".json"
            if args.format == "json"
            else ".csv"
        )

        output = os.path.join(
            base_dir(),
            "episode_pair_features"
            + suffix,
        )

    output = os.path.abspath(
        output
    )

    os.makedirs(
        os.path.dirname(
            output
        ),
        exist_ok=True,
    )

    if args.format == "json":
        write_json(
            output,
            pairs,
        )
    else:
        write_csv(
            output,
            pairs,
        )

    print()
    print(
        f"Output: {output}"
    )

    print()
    print(
        "No matching decision was made."
    )

    print(
        "These are calibration features only."
    )


if __name__ == "__main__":
    main()
