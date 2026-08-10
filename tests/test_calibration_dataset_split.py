from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = ROOT / relative

    root_str = str(ROOT)

    if root_str not in sys.path:
        sys.path.insert(
            0,
            root_str,
        )

    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    sha.update(
        path.read_bytes()
    )
    return sha.hexdigest()


def feature(
    session_a: int,
    session_b: int,
    *,
    track: str = "Test Track",
    center_diff: float = 10.0,
    overlap: float = 0.5,
    channel_jaccard: float = 0.5,
):
    return {
        "track": track,
        "session_a": session_a,
        "session_b": session_b,
        "episode_pk_a": session_a * 100 + session_b,
        "episode_pk_b": session_b * 100 + session_a,
        "episode_id_a": 1,
        "episode_id_b": 1,
        "center_distance_abs_diff_m": center_diff,
        "start_distance_abs_diff_m": center_diff,
        "end_distance_abs_diff_m": center_diff,
        "center_fraction_abs_diff": center_diff / 10000.0,
        "start_fraction_abs_diff": center_diff / 10000.0,
        "end_fraction_abs_diff": center_diff / 10000.0,
        "overlap_m": 50.0,
        "union_m": 100.0,
        "overlap_over_union": overlap,
        "overlap_over_shorter": overlap,
        "overlap_over_longer": overlap,
        "length_similarity": 0.9,
        "fraction_overlap": 0.01,
        "fraction_overlap_over_union": overlap,
        "fraction_overlap_over_shorter": overlap,
        "channel_jaccard": channel_jaccard,
        "channels_a": ["brake", "throttle"],
        "channels_b": ["brake", "throttle"],
        "shared_channels": ["brake", "throttle"],
        "channels_only_a": [],
        "channels_only_b": [],
        "action_time_loss_a_s": 0.2,
        "action_time_loss_b_s": 0.3,
        "action_time_loss_similarity": 2.0 / 3.0,
        "per_channel_metrics": {},
    }


def snapshot_from_feature(features):
    keys = [
        "track",
        "session_a",
        "session_b",
        "episode_pk_a",
        "episode_pk_b",
    ]

    return {
        key: features.get(key)
        for key in keys
    }


def write_queue_and_labels(
    tmp_path: Path,
    pairs: list[tuple[str, str, dict]],
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"

    queue_items = []

    for pair_id, label, features in pairs:
        queue_items.append({
            "pair_id": pair_id,
            "queue_position": len(queue_items) + 1,
            "selected_by": [],
            "features": features,
        })

    queue_data = {
        "metadata": {
            "queue_schema_version": "1.0",
        },
        "queue": queue_items,
    }

    queue_path.write_text(
        json.dumps(
            queue_data,
            indent=2,
        ),
        encoding="utf-8",
    )

    label_items = []

    for pair_id, label, features in pairs:
        label_items.append({
            "pair_id": pair_id,
            "human_label": label,
            "review_notes": "",
            "reviewed_at_utc": "2026-08-10T00:00:00+00:00",
            "selected_by": [],
            "feature_snapshot": snapshot_from_feature(
                features
            ),
        })

    labels_data = {
        "metadata": {
            "label_schema_version": "1.1",
            "source_queue_sha256": file_sha256(
                queue_path
            ),
        },
        "labels": label_items,
    }

    labels_path.write_text(
        json.dumps(
            labels_data,
            indent=2,
        ),
        encoding="utf-8",
    )

    return (
        queue_path,
        labels_path,
    )


def test_session_assignment_is_deterministic():
    module = load_module(
        "build_calibration_dataset",
        "build_calibration_dataset.py",
    )

    sessions = [
        {
            "session_key": f'["Track",{session_id}]',
            "track": "Track",
            "session_id": session_id,
        }
        for session_id in range(
            1,
            9,
        )
    ]

    a = module.assign_sessions(
        sessions,
        evaluation_fraction=0.25,
        seed=123,
    )

    b = module.assign_sessions(
        list(reversed(sessions)),
        evaluation_fraction=0.25,
        seed=123,
    )

    assert a == b


def test_no_session_leakage_and_cross_pairs_are_excluded(
    tmp_path,
):
    module = load_module(
        "build_calibration_dataset",
        "build_calibration_dataset.py",
    )

    pairs = [
        (
            "p12",
            "SAME",
            feature(1, 2),
        ),
        (
            "p34",
            "DIFFERENT",
            feature(3, 4),
        ),
        (
            "p13",
            "AMBIGUOUS",
            feature(1, 3),
        ),
        (
            "p24",
            "SAME",
            feature(2, 4),
        ),
    ]

    queue_path, labels_path = write_queue_and_labels(
        tmp_path,
        pairs,
    )

    dataset = module.build_dataset(
        queue_path,
        labels_path,
        evaluation_fraction=0.5,
        seed=7,
    )

    calibration_sessions = {
        (
            row["track"],
            row["session_id"],
        )
        for row in dataset["session_assignment"]
        if row["partition"] == "calibration"
    }

    evaluation_sessions = {
        (
            row["track"],
            row["session_id"],
        )
        for row in dataset["session_assignment"]
        if row["partition"] == "evaluation"
    }

    assert (
        calibration_sessions
        &
        evaluation_sessions
    ) == set()

    for record in dataset["calibration"]:
        f = record["features"]

        assert (
            f["track"],
            f["session_a"],
        ) in calibration_sessions

        assert (
            f["track"],
            f["session_b"],
        ) in calibration_sessions

    for record in dataset["evaluation"]:
        f = record["features"]

        assert (
            f["track"],
            f["session_a"],
        ) in evaluation_sessions

        assert (
            f["track"],
            f["session_b"],
        ) in evaluation_sessions

    for record in dataset["excluded_cross_split"]:
        assert (
            record["partition_a"]
            !=
            record["partition_b"]
        )


def test_skip_is_excluded_and_ambiguous_is_preserved(
    tmp_path,
):
    module = load_module(
        "build_calibration_dataset",
        "build_calibration_dataset.py",
    )

    pairs = [
        (
            "same",
            "SAME",
            feature(1, 2),
        ),
        (
            "amb",
            "AMBIGUOUS",
            feature(1, 2),
        ),
        (
            "skip",
            "SKIP",
            feature(1, 2),
        ),
    ]

    queue_path, labels_path = write_queue_and_labels(
        tmp_path,
        pairs,
    )

    dataset = module.build_dataset(
        queue_path,
        labels_path,
        evaluation_fraction=0.5,
        seed=1,
    )

    usable_labels = {
        record["human_label"]
        for record in (
            dataset["calibration"]
            +
            dataset["evaluation"]
            +
            [
                {
                    "human_label":
                    item["human_label"]
                }
                for item in dataset[
                    "excluded_cross_split"
                ]
            ]
        )
    }

    assert "AMBIGUOUS" in usable_labels
    assert "SKIP" not in usable_labels

    assert dataset[
        "ignored_skip"
    ] == [
        {
            "pair_id": "skip",
            "human_label": "SKIP",
        }
    ]


def test_split_is_reproducible_for_same_seed(
    tmp_path,
):
    module = load_module(
        "build_calibration_dataset",
        "build_calibration_dataset.py",
    )

    pairs = []

    for a, b, label in [
        (1, 2, "SAME"),
        (1, 3, "DIFFERENT"),
        (1, 4, "AMBIGUOUS"),
        (2, 3, "SAME"),
        (2, 4, "DIFFERENT"),
        (3, 4, "AMBIGUOUS"),
    ]:
        pairs.append(
            (
                f"p{a}{b}",
                label,
                feature(a, b),
            )
        )

    queue_path, labels_path = write_queue_and_labels(
        tmp_path,
        pairs,
    )

    a = module.build_dataset(
        queue_path,
        labels_path,
        evaluation_fraction=0.5,
        seed=42,
    )

    b = module.build_dataset(
        queue_path,
        labels_path,
        evaluation_fraction=0.5,
        seed=42,
    )

    assert (
        a["session_assignment"]
        ==
        b["session_assignment"]
    )

    assert [
        item["pair_id"]
        for item in a["calibration"]
    ] == [
        item["pair_id"]
        for item in b["calibration"]
    ]

    assert [
        item["pair_id"]
        for item in a["evaluation"]
    ] == [
        item["pair_id"]
        for item in b["evaluation"]
    ]


def test_invalid_evaluation_fraction_is_rejected():
    module = load_module(
        "build_calibration_dataset",
        "build_calibration_dataset.py",
    )

    sessions = [{
        "session_key": '["Track",1]',
        "track": "Track",
        "session_id": 1,
    }]

    for value in (
        0.0,
        1.0,
        -0.1,
        1.1,
    ):
        try:
            module.assign_sessions(
                sessions,
                evaluation_fraction=value,
                seed=1,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"Expected ValueError for {value}"
            )
