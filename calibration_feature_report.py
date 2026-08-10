from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA_VERSION = "1.0"
LABELS = ("SAME", "DIFFERENT", "AMBIGUOUS")


FEATURE_ROLES = {
    # Absolute spatial
    "center_distance_abs_diff_m": "spatial_absolute",
    "start_distance_abs_diff_m": "spatial_absolute",
    "end_distance_abs_diff_m": "spatial_absolute",
    "overlap_m": "spatial_absolute",
    "union_m": "spatial_absolute",

    # Normalized spatial
    "center_fraction_abs_diff": "spatial_normalized",
    "start_fraction_abs_diff": "spatial_normalized",
    "end_fraction_abs_diff": "spatial_normalized",
    "overlap_over_union": "spatial_normalized",
    "overlap_over_shorter": "spatial_normalized",
    "overlap_over_longer": "spatial_normalized",
    "length_similarity": "spatial_normalized",
    "fraction_overlap": "spatial_normalized",
    "fraction_overlap_over_union": "spatial_normalized",
    "fraction_overlap_over_shorter": "spatial_normalized",

    # Channel identity
    "channel_jaccard": "channel_identity",
    "shared_channel_count": "channel_identity",
    "channel_symmetric_difference_count": "channel_identity",

    # Aggregated channel shape
    "channel_coverage_abs_diff_mean": "channel_shape",
    "channel_coverage_abs_diff_max": "channel_shape",
    "channel_onset_offset_abs_diff_m_mean": "channel_shape",
    "channel_onset_offset_abs_diff_m_max": "channel_shape",
    "channel_end_offset_abs_diff_m_mean": "channel_shape",
    "channel_end_offset_abs_diff_m_max": "channel_shape",
    "channel_mean_difference_similarity_mean": "channel_shape",
    "channel_mean_difference_similarity_min": "channel_shape",
    "channel_peak_difference_similarity_mean": "channel_shape",
    "channel_peak_difference_similarity_min": "channel_shape",
    "channel_direction_agreement_ratio": "channel_shape",

    # Secondary evidence only
    "action_time_loss_similarity": "secondary_impact",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(result):
        return None

    return result


def percentile(
    values: list[float],
    q: float,
) -> float | None:
    if not values:
        return None

    if not 0.0 <= q <= 1.0:
        raise ValueError(
            "q debe estar entre 0 y 1."
        )

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        (len(ordered) - 1)
        *
        q
    )

    lower = math.floor(
        position
    )

    upper = math.ceil(
        position
    )

    if lower == upper:
        return ordered[
            lower
        ]

    weight = (
        position
        -
        lower
    )

    return (
        ordered[lower]
        *
        (1.0 - weight)
        +
        ordered[upper]
        *
        weight
    )


def distribution_summary(
    raw_values: list[Any],
) -> dict[str, Any]:
    values = [
        value
        for value in (
            safe_float(item)
            for item in raw_values
        )
        if value is not None
    ]

    total = len(
        raw_values
    )

    valid = len(
        values
    )

    if not values:
        return {
            "total_rows": total,
            "valid_n": 0,
            "missing_n": total,
            "min": None,
            "p10": None,
            "p25": None,
            "median": None,
            "mean": None,
            "p75": None,
            "p90": None,
            "max": None,
            "iqr": None,
        }

    p25 = percentile(
        values,
        0.25,
    )

    p75 = percentile(
        values,
        0.75,
    )

    return {
        "total_rows": total,
        "valid_n": valid,
        "missing_n": total - valid,
        "min": min(values),
        "p10": percentile(
            values,
            0.10,
        ),
        "p25": p25,
        "median": statistics.median(
            values
        ),
        "mean": statistics.fmean(
            values
        ),
        "p75": p75,
        "p90": percentile(
            values,
            0.90,
        ),
        "max": max(values),
        "iqr": (
            None
            if p25 is None
            or p75 is None
            else p75 - p25
        ),
    }


def aggregate_numeric_metric(
    per_channel_metrics: dict[str, Any],
    key: str,
    mode: str,
) -> float | None:
    values = []

    for metrics in per_channel_metrics.values():
        if not isinstance(
            metrics,
            dict,
        ):
            continue

        value = safe_float(
            metrics.get(key)
        )

        if value is not None:
            values.append(
                value
            )

    if not values:
        return None

    if mode == "mean":
        return statistics.fmean(
            values
        )

    if mode == "max":
        return max(
            values
        )

    if mode == "min":
        return min(
            values
        )

    raise ValueError(
        f"mode inválido: {mode}"
    )


def direction_agreement_ratio(
    per_channel_metrics: dict[str, Any],
) -> float | None:
    comparable = 0
    equal = 0

    for metrics in per_channel_metrics.values():
        if not isinstance(
            metrics,
            dict,
        ):
            continue

        a = metrics.get(
            "direction_consistency_a"
        )

        b = metrics.get(
            "direction_consistency_b"
        )

        if (
            a is None
            or
            b is None
        ):
            continue

        comparable += 1

        if a == b:
            equal += 1

    if comparable == 0:
        return None

    return (
        equal
        /
        comparable
    )


def extract_feature_vector(
    features: dict[str, Any],
) -> dict[str, float | None]:
    vector: dict[str, float | None] = {}

    for feature_name in FEATURE_ROLES:
        if feature_name.startswith(
            "channel_"
        ) and feature_name != "channel_jaccard":
            continue

        vector[feature_name] = safe_float(
            features.get(
                feature_name
            )
        )

    channels_a = features.get(
        "channels_a",
        [],
    )

    channels_b = features.get(
        "channels_b",
        [],
    )

    shared_channels = features.get(
        "shared_channels",
        [],
    )

    if not isinstance(
        channels_a,
        list,
    ):
        channels_a = []

    if not isinstance(
        channels_b,
        list,
    ):
        channels_b = []

    if not isinstance(
        shared_channels,
        list,
    ):
        shared_channels = []

    set_a = {
        str(item)
        for item in channels_a
    }

    set_b = {
        str(item)
        for item in channels_b
    }

    vector[
        "shared_channel_count"
    ] = float(
        len(
            {
                str(item)
                for item in shared_channels
            }
        )
    )

    vector[
        "channel_symmetric_difference_count"
    ] = float(
        len(
            set_a
            ^
            set_b
        )
    )

    per_channel = features.get(
        "per_channel_metrics",
        {},
    )

    if not isinstance(
        per_channel,
        dict,
    ):
        per_channel = {}

    vector[
        "channel_coverage_abs_diff_mean"
    ] = aggregate_numeric_metric(
        per_channel,
        "coverage_abs_diff",
        "mean",
    )

    vector[
        "channel_coverage_abs_diff_max"
    ] = aggregate_numeric_metric(
        per_channel,
        "coverage_abs_diff",
        "max",
    )

    vector[
        "channel_onset_offset_abs_diff_m_mean"
    ] = aggregate_numeric_metric(
        per_channel,
        "onset_offset_abs_diff_m",
        "mean",
    )

    vector[
        "channel_onset_offset_abs_diff_m_max"
    ] = aggregate_numeric_metric(
        per_channel,
        "onset_offset_abs_diff_m",
        "max",
    )

    vector[
        "channel_end_offset_abs_diff_m_mean"
    ] = aggregate_numeric_metric(
        per_channel,
        "end_offset_abs_diff_m",
        "mean",
    )

    vector[
        "channel_end_offset_abs_diff_m_max"
    ] = aggregate_numeric_metric(
        per_channel,
        "end_offset_abs_diff_m",
        "max",
    )

    vector[
        "channel_mean_difference_similarity_mean"
    ] = aggregate_numeric_metric(
        per_channel,
        "mean_difference_similarity",
        "mean",
    )

    vector[
        "channel_mean_difference_similarity_min"
    ] = aggregate_numeric_metric(
        per_channel,
        "mean_difference_similarity",
        "min",
    )

    vector[
        "channel_peak_difference_similarity_mean"
    ] = aggregate_numeric_metric(
        per_channel,
        "peak_difference_similarity",
        "mean",
    )

    vector[
        "channel_peak_difference_similarity_min"
    ] = aggregate_numeric_metric(
        per_channel,
        "peak_difference_similarity",
        "min",
    )

    vector[
        "channel_direction_agreement_ratio"
    ] = direction_agreement_ratio(
        per_channel
    )

    # Restore channel_jaccard because the generic branch above includes it.
    vector[
        "channel_jaccard"
    ] = safe_float(
        features.get(
            "channel_jaccard"
        )
    )

    return vector


def median_contrast(
    a: dict[str, Any],
    b: dict[str, Any],
) -> dict[str, Any]:
    median_a = safe_float(
        a.get(
            "median"
        )
    )

    median_b = safe_float(
        b.get(
            "median"
        )
    )

    iqr_a = safe_float(
        a.get(
            "iqr"
        )
    )

    iqr_b = safe_float(
        b.get(
            "iqr"
        )
    )

    raw_gap = None

    if (
        median_a is not None
        and
        median_b is not None
    ):
        raw_gap = (
            median_a
            -
            median_b
        )

    pooled_iqr = None

    if (
        iqr_a is not None
        and
        iqr_b is not None
    ):
        pooled_iqr = (
            iqr_a
            +
            iqr_b
        ) / 2.0

    normalized = None

    if (
        raw_gap is not None
        and
        pooled_iqr is not None
        and
        pooled_iqr > 0
    ):
        normalized = (
            raw_gap
            /
            pooled_iqr
        )

    return {
        "median_a_minus_b": raw_gap,
        "pooled_iqr": pooled_iqr,
        "median_gap_over_pooled_iqr": normalized,
        "interpretation_policy": (
            "Descriptive contrast only. "
            "Not a matcher weight, threshold, probability, or decision rule."
        ),
    }


def analyze_partition(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    by_label: dict[
        str,
        list[dict[str, float | None]],
    ] = defaultdict(list)

    for record in records:
        label = record.get(
            "human_label"
        )

        if label not in LABELS:
            continue

        features = record.get(
            "features",
            {},
        )

        if not isinstance(
            features,
            dict,
        ):
            features = {}

        by_label[
            label
        ].append(
            extract_feature_vector(
                features
            )
        )

    feature_reports = {}

    for feature_name, role in FEATURE_ROLES.items():
        label_stats = {}

        for label in LABELS:
            vectors = by_label[
                label
            ]

            label_stats[
                label
            ] = distribution_summary([
                vector.get(
                    feature_name
                )
                for vector in vectors
            ])

        feature_reports[
            feature_name
        ] = {
            "role": role,
            "by_label": label_stats,
            "contrasts": {
                "SAME_vs_DIFFERENT":
                    median_contrast(
                        label_stats["SAME"],
                        label_stats["DIFFERENT"],
                    ),
                "SAME_vs_AMBIGUOUS":
                    median_contrast(
                        label_stats["SAME"],
                        label_stats["AMBIGUOUS"],
                    ),
                "DIFFERENT_vs_AMBIGUOUS":
                    median_contrast(
                        label_stats["DIFFERENT"],
                        label_stats["AMBIGUOUS"],
                    ),
            },
        }

    return {
        "pair_count": len(
            records
        ),
        "label_counts": {
            label: len(
                by_label[
                    label
                ]
            )
            for label in LABELS
        },
        "features": feature_reports,
    }


def build_report(
    dataset: dict[str, Any],
) -> dict[str, Any]:
    calibration = dataset.get(
        "calibration",
        [],
    )

    evaluation = dataset.get(
        "evaluation",
        [],
    )

    if not isinstance(
        calibration,
        list,
    ):
        raise ValueError(
            "dataset.calibration inválido."
        )

    if not isinstance(
        evaluation,
        list,
    ):
        raise ValueError(
            "dataset.evaluation inválido."
        )

    return {
        "metadata": {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_dataset_schema_version": (
                dataset
                .get(
                    "metadata",
                    {}
                )
                .get(
                    "dataset_schema_version"
                )
            ),
            "purpose": (
                "Describe feature distributions by human label "
                "without selecting matcher thresholds or weights."
            ),
            "evaluation_policy": (
                "Evaluation statistics are reported separately and "
                "must not be used to tune matcher decisions."
            ),
            "impact_policy": (
                "secondary_impact features are descriptive only and "
                "must not dominate future matching."
            ),
            "matcher_status": (
                "NO_THRESHOLDS_NO_MATCH_SCORE_NO_AUTOMATIC_MATCHING"
            ),
        },
        "feature_roles": FEATURE_ROLES,
        "calibration": analyze_partition(
            calibration
        ),
        "evaluation": analyze_partition(
            evaluation
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resume distribuciones de features por label humano "
            "sin entrenar ni decidir un matcher."
        )
    )

    parser.add_argument(
        "dataset_json",
    )

    parser.add_argument(
        "--output",
        default="calibration_feature_report.json",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    dataset_path = Path(
        args.dataset_json
    ).resolve()

    output_path = Path(
        args.output
    ).resolve()

    if not dataset_path.exists():
        raise FileNotFoundError(
            dataset_path
        )

    dataset = json.loads(
        dataset_path.read_text(
            encoding="utf-8"
        )
    )

    report = build_report(
        dataset
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("RACE ENGINEER - CALIBRATION FEATURE REPORT v1.0")
    print("=" * 72)
    print()

    for partition in (
        "calibration",
        "evaluation",
    ):
        summary = report[
            partition
        ]

        print(
            f"{partition}: "
            f"pairs={summary['pair_count']} "
            f"labels={summary['label_counts']}"
        )

    print()
    print(
        f"Output: {output_path}"
    )

    print(
        "No thresholds, weights, probabilities, "
        "or automatic match decisions were created."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
