from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = ROOT / relative

    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def record(
    label: str,
    center_diff: float,
    overlap: float,
    jaccard: float,
    impact_similarity: float,
):
    return {
        "pair_id": f"{label}-{center_diff}",
        "human_label": label,
        "features": {
            "center_distance_abs_diff_m": center_diff,
            "start_distance_abs_diff_m": center_diff,
            "end_distance_abs_diff_m": center_diff,
            "center_fraction_abs_diff": center_diff / 10000.0,
            "start_fraction_abs_diff": center_diff / 10000.0,
            "end_fraction_abs_diff": center_diff / 10000.0,
            "overlap_m": overlap * 100.0,
            "union_m": 100.0,
            "overlap_over_union": overlap,
            "overlap_over_shorter": overlap,
            "overlap_over_longer": overlap,
            "length_similarity": 0.9,
            "fraction_overlap": overlap / 100.0,
            "fraction_overlap_over_union": overlap,
            "fraction_overlap_over_shorter": overlap,
            "channel_jaccard": jaccard,
            "channels_a": ["brake", "throttle"],
            "channels_b": ["brake", "throttle"],
            "shared_channels": ["brake", "throttle"],
            "action_time_loss_similarity": impact_similarity,
            "per_channel_metrics": {
                "brake": {
                    "coverage_abs_diff": 0.1,
                    "onset_offset_abs_diff_m": 5.0,
                    "end_offset_abs_diff_m": 6.0,
                    "mean_difference_similarity": 0.8,
                    "peak_difference_similarity": 0.7,
                    "direction_consistency_a": "positive",
                    "direction_consistency_b": "positive",
                },
                "throttle": {
                    "coverage_abs_diff": 0.2,
                    "onset_offset_abs_diff_m": 10.0,
                    "end_offset_abs_diff_m": 12.0,
                    "mean_difference_similarity": 0.6,
                    "peak_difference_similarity": 0.5,
                    "direction_consistency_a": "negative",
                    "direction_consistency_b": "positive",
                },
            },
        },
    }


def test_feature_vector_aggregates_channel_shape():
    module = load_module(
        "calibration_feature_report",
        "calibration_feature_report.py",
    )

    vector = module.extract_feature_vector(
        record(
            "SAME",
            10.0,
            0.8,
            1.0,
            0.9,
        )["features"]
    )

    assert vector[
        "shared_channel_count"
    ] == 2.0

    assert vector[
        "channel_symmetric_difference_count"
    ] == 0.0

    assert abs(
        vector[
            "channel_coverage_abs_diff_mean"
        ]
        -
        0.15
    ) < 1e-12

    assert vector[
        "channel_onset_offset_abs_diff_m_max"
    ] == 10.0

    assert vector[
        "channel_direction_agreement_ratio"
    ] == 0.5


def test_report_keeps_partitions_separate():
    module = load_module(
        "calibration_feature_report",
        "calibration_feature_report.py",
    )

    dataset = {
        "metadata": {
            "dataset_schema_version": "1.0",
        },
        "calibration": [
            record(
                "SAME",
                5.0,
                0.9,
                1.0,
                0.8,
            ),
            record(
                "DIFFERENT",
                100.0,
                0.1,
                0.0,
                0.2,
            ),
            record(
                "AMBIGUOUS",
                30.0,
                0.5,
                0.5,
                0.5,
            ),
        ],
        "evaluation": [
            record(
                "SAME",
                8.0,
                0.85,
                1.0,
                0.75,
            ),
        ],
    }

    report = module.build_report(
        dataset
    )

    assert report[
        "calibration"
    ][
        "pair_count"
    ] == 3

    assert report[
        "evaluation"
    ][
        "pair_count"
    ] == 1

    assert report[
        "calibration"
    ][
        "label_counts"
    ] == {
        "SAME": 1,
        "DIFFERENT": 1,
        "AMBIGUOUS": 1,
    }

    assert report[
        "evaluation"
    ][
        "label_counts"
    ] == {
        "SAME": 1,
        "DIFFERENT": 0,
        "AMBIGUOUS": 0,
    }


def test_secondary_impact_is_explicitly_tagged():
    module = load_module(
        "calibration_feature_report",
        "calibration_feature_report.py",
    )

    assert module.FEATURE_ROLES[
        "action_time_loss_similarity"
    ] == "secondary_impact"


def test_median_contrast_is_descriptive_not_decision_rule():
    module = load_module(
        "calibration_feature_report",
        "calibration_feature_report.py",
    )

    same = module.distribution_summary([
        1.0,
        2.0,
        3.0,
    ])

    different = module.distribution_summary([
        10.0,
        11.0,
        12.0,
    ])

    contrast = module.median_contrast(
        same,
        different,
    )

    assert contrast[
        "median_a_minus_b"
    ] == -9.0

    assert (
        "Not a matcher weight"
        in
        contrast[
            "interpretation_policy"
        ]
    )


def test_distribution_summary_handles_missing_values():
    module = load_module(
        "calibration_feature_report",
        "calibration_feature_report.py",
    )

    summary = module.distribution_summary([
        1.0,
        None,
        float("nan"),
        3.0,
    ])

    assert summary[
        "total_rows"
    ] == 4

    assert summary[
        "valid_n"
    ] == 2

    assert summary[
        "missing_n"
    ] == 2

    assert summary[
        "median"
    ] == 2.0
