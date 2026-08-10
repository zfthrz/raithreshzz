from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "prepare_calibration_batch.py"

    spec = importlib.util.spec_from_file_location(
        "prepare_calibration_batch_test_target",
        path,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_slugify_is_filesystem_safe():
    module = load_module()

    assert (
        module.slugify(
            "Autodromo Nazionale Monza"
        )
        ==
        "autodromo-nazionale-monza"
    )

    assert (
        module.slugify(
            "Circuit de Spa-Francorchamps"
        )
        ==
        "circuit-de-spa-francorchamps"
    )


def test_session_signature_is_order_independent():
    module = load_module()

    rows = [
        {
            "session_id": 2,
            "track": "Track",
            "source_json_sha256": "bbb",
            "source_analysis_version": "3.8",
            "timestamp_utc": "b",
        },
        {
            "session_id": 1,
            "track": "Track",
            "source_json_sha256": "aaa",
            "source_analysis_version": "3.8",
            "timestamp_utc": "a",
        },
    ]

    assert (
        module.session_signature(
            rows
        )
        ==
        module.session_signature(
            list(
                reversed(
                    rows
                )
            )
        )
    )


def test_new_session_creates_new_batch_id(
    tmp_path,
):
    module = load_module()

    rows_a = [
        {
            "session_id": 1,
            "track": "Track",
            "source_json_sha256": "aaa",
            "source_analysis_version": "3.8",
            "timestamp_utc": "a",
        },
        {
            "session_id": 2,
            "track": "Track",
            "source_json_sha256": "bbb",
            "source_analysis_version": "3.8",
            "timestamp_utc": "b",
        },
    ]

    rows_b = rows_a + [
        {
            "session_id": 3,
            "track": "Track",
            "source_json_sha256": "ccc",
            "source_analysis_version": "3.8",
            "timestamp_utc": "c",
        }
    ]

    sig_a = module.session_signature(
        rows_a
    )

    sig_b = module.session_signature(
        rows_b
    )

    assert sig_a != sig_b

    path_a = module.build_batch_paths(
        tmp_path,
        "Track",
        sig_a,
    )[
        "batch_dir"
    ]

    path_b = module.build_batch_paths(
        tmp_path,
        "Track",
        sig_b,
    )[
        "batch_dir"
    ]

    assert path_a != path_b


def test_choose_track_auto_selects_single_eligible():
    module = load_module()

    grouped = {
        "Monza": [
            {"session_id": 1},
            {"session_id": 2},
        ],
        "Spa": [
            {"session_id": 3},
        ],
    }

    track, reason = module.choose_track(
        grouped,
        None,
    )

    assert track == "Monza"
    assert reason is None


def test_choose_track_blocks_multiple_eligible():
    module = load_module()

    grouped = {
        "Monza": [
            {"session_id": 1},
            {"session_id": 2},
        ],
        "Spa": [
            {"session_id": 3},
            {"session_id": 4},
        ],
    }

    track, reason = module.choose_track(
        grouped,
        None,
    )

    assert track is None
    assert reason is not None
    assert "multiple_eligible_tracks" in reason


def test_choose_track_blocks_when_no_track_has_two_sessions():
    module = load_module()

    grouped = {
        "Monza": [
            {"session_id": 1},
        ],
        "Spa": [
            {"session_id": 2},
        ],
    }

    track, reason = module.choose_track(
        grouped,
        None,
    )

    assert track is None
    assert reason is not None
    assert "insufficient_cross_session_data" in reason


def write_queue(
    path: Path,
    pair_ids: list[str],
):
    path.write_text(
        json.dumps(
            {
                "metadata": {},
                "queue": [
                    {
                        "pair_id": pair_id,
                        "features": {},
                    }
                    for pair_id in pair_ids
                ],
            }
        ),
        encoding="utf-8",
    )


def write_labels(
    path: Path,
    pair_ids: list[str],
):
    path.write_text(
        json.dumps(
            {
                "metadata": {},
                "labels": [
                    {
                        "pair_id": pair_id,
                        "human_label": "SAME",
                    }
                    for pair_id in pair_ids
                ],
            }
        ),
        encoding="utf-8",
    )


def test_label_progress_detects_missing_file(
    tmp_path,
):
    module = load_module()

    queue = tmp_path / "queue.json"
    labels = tmp_path / "labels.json"

    write_queue(
        queue,
        [
            "a",
            "b",
        ],
    )

    progress = module.label_progress(
        queue,
        labels,
    )

    assert progress == {
        "exists": False,
        "queue_pairs": 2,
        "labeled_pairs": 0,
        "unreviewed_pairs": 2,
        "complete": False,
    }


def test_label_progress_detects_incomplete_and_complete(
    tmp_path,
):
    module = load_module()

    queue = tmp_path / "queue.json"
    labels = tmp_path / "labels.json"

    write_queue(
        queue,
        [
            "a",
            "b",
            "c",
        ],
    )

    write_labels(
        labels,
        [
            "a",
            "b",
        ],
    )

    incomplete = module.label_progress(
        queue,
        labels,
    )

    assert incomplete[
        "complete"
    ] is False

    assert incomplete[
        "unreviewed_pairs"
    ] == 1

    write_labels(
        labels,
        [
            "a",
            "b",
            "c",
        ],
    )

    complete = module.label_progress(
        queue,
        labels,
    )

    assert complete[
        "complete"
    ] is True

    assert complete[
        "unreviewed_pairs"
    ] == 0


def test_dataset_readiness_flags_empty_evaluation(
    tmp_path,
):
    module = load_module()

    dataset = tmp_path / "dataset.json"

    dataset.write_text(
        json.dumps(
            {
                "counts": {
                    "calibration_pairs": 5,
                    "evaluation_pairs": 0,
                    "cross_split_pairs_excluded": 7,
                }
            }
        ),
        encoding="utf-8",
    )

    readiness = module.dataset_readiness(
        dataset
    )

    assert readiness[
        "calibration_ready"
    ] is True

    assert readiness[
        "evaluation_ready"
    ] is False

    assert readiness[
        "cross_split_pairs_excluded"
    ] == 7


def test_status_round_trip(
    tmp_path,
):
    module = load_module()

    status = module.new_status(
        project_root=tmp_path,
        input_dir=tmp_path,
        db_path=tmp_path / "history.duckdb",
    )

    module.set_step(
        status,
        "history_validation",
        "PASS",
        warnings=0,
    )

    path = (
        tmp_path
        /
        "BATCH_STATUS.json"
    )

    module.write_status(
        path,
        status,
    )

    loaded = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert loaded[
        "steps"
    ][
        "history_validation"
    ][
        "status"
    ] == "PASS"

    assert loaded[
        "matcher"
    ][
        "status"
    ] == "BLOCKED_BY_REAL_DATA"
