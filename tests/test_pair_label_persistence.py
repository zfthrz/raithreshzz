from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def label_module():
    return load_module("label_episode_pairs", "label_episode_pairs.py")


@pytest.fixture()
def validator_module():
    return load_module("validate_pair_labels", "validate_pair_labels.py")


def feature(
    *,
    track: str = "Test Track",
    session_a: int = 1,
    session_b: int = 2,
    episode_pk_a: int = 10,
    episode_pk_b: int = 20,
):
    return {
        "track": track,
        "session_a": session_a,
        "session_b": session_b,
        "episode_pk_a": episode_pk_a,
        "episode_pk_b": episode_pk_b,
        "episode_id_a": 1,
        "episode_id_b": 1,
        "start_distance_a_m": 100.0,
        "end_distance_a_m": 150.0,
        "center_distance_a_m": 125.0,
        "start_distance_b_m": 102.0,
        "end_distance_b_m": 152.0,
        "center_distance_b_m": 127.0,
        "center_distance_abs_diff_m": 2.0,
        "overlap_m": 48.0,
        "overlap_over_union": 48.0 / 52.0,
        "overlap_over_shorter": 48.0 / 50.0,
        "channel_jaccard": 1.0,
        "channels_a": ["throttle"],
        "channels_b": ["throttle"],
        "shared_channels": ["throttle"],
        "channels_only_a": [],
        "channels_only_b": [],
        "action_time_loss_a_s": 0.20,
        "action_time_loss_b_s": 0.25,
        "action_time_loss_similarity": 0.8,
        "per_channel_metrics": {
            "throttle": {
                "coverage_abs_diff": 0.05,
                "onset_offset_abs_diff_m": 2.0,
                "end_offset_abs_diff_m": 2.0,
                "mean_difference_similarity": 0.9,
                "peak_difference_similarity": 0.8,
            }
        },
    }


def queue_item(pair_id: str, **feature_kwargs):
    return {
        "pair_id": pair_id,
        "queue_position": 1,
        "selected_by": [{"lens": "synthetic", "rank": 1}],
        "features": feature(**feature_kwargs),
    }


def write_queue(path: Path, items: list[dict]):
    path.write_text(
        json.dumps(
            {
                "metadata": {"queue_schema_version": "1.0"},
                "queue": items,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "label",
    ["SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"],
)
def test_all_contract_labels_can_be_persisted(
    tmp_path,
    label_module,
    validator_module,
    label,
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"
    item = queue_item("pair-1")
    write_queue(queue_path, [item])

    data = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )
    label_module.upsert_label(
        data,
        item,
        label,
        f"nota {label}",
    )
    label_module.save_labels(
        labels_path,
        data,
    )

    reloaded = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )

    assert len(reloaded["labels"]) == 1
    assert reloaded["labels"][0]["human_label"] == label
    assert reloaded["labels"][0]["review_notes"] == f"nota {label}"

    errors, _, summary = validator_module.validate(
        queue_path,
        labels_path,
    )

    assert errors == []
    assert summary["counts"][label] == 1


def test_upsert_updates_existing_pair_without_duplicate(
    tmp_path,
    label_module,
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"
    item = queue_item("pair-1")
    write_queue(queue_path, [item])

    data = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )

    label_module.upsert_label(
        data,
        item,
        "SAME",
        "primera",
    )
    label_module.upsert_label(
        data,
        item,
        "AMBIGUOUS",
        "revisado",
    )

    assert len(data["labels"]) == 1
    assert data["labels"][0]["human_label"] == "AMBIGUOUS"
    assert data["labels"][0]["review_notes"] == "revisado"


def test_upsert_rejects_invalid_label(
    tmp_path,
    label_module,
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"
    item = queue_item("pair-1")
    write_queue(queue_path, [item])

    data = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )

    with pytest.raises(ValueError, match="human_label inválido"):
        label_module.upsert_label(
            data,
            item,
            "PROBABLY_SAME",
            "",
        )


def test_resume_skips_completed_and_optionally_reopens_skip(
    tmp_path,
    label_module,
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"

    item_same = queue_item(
        "pair-same",
        episode_pk_a=10,
        episode_pk_b=20,
    )
    item_skip = queue_item(
        "pair-skip",
        episode_pk_a=11,
        episode_pk_b=21,
    )
    item_pending = queue_item(
        "pair-pending",
        episode_pk_a=12,
        episode_pk_b=22,
    )

    items = [item_same, item_skip, item_pending]
    write_queue(queue_path, items)

    data = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )
    label_module.upsert_label(data, item_same, "SAME", "")
    label_module.upsert_label(data, item_skip, "SKIP", "")

    normal = label_module.build_pending_items(
        {"queue": items},
        data,
        include_skipped_on_resume=False,
    )
    assert [item["pair_id"] for item in normal] == ["pair-pending"]

    with_skipped = label_module.build_pending_items(
        {"queue": items},
        data,
        include_skipped_on_resume=True,
    )
    assert [item["pair_id"] for item in with_skipped] == [
        "pair-skip",
        "pair-pending",
    ]


def test_load_labels_rejects_changed_queue_hash(
    tmp_path,
    label_module,
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"
    item = queue_item("pair-1")
    write_queue(queue_path, [item])

    data = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )
    label_module.upsert_label(data, item, "SAME", "")
    label_module.save_labels(labels_path, data)

    changed = queue_item(
        "pair-2",
        episode_pk_a=999,
        episode_pk_b=1000,
    )
    write_queue(queue_path, [item, changed])

    with pytest.raises(ValueError, match="otra cola|cola cambió"):
        label_module.load_labels(
            labels_path,
            queue_path,
            "tester",
        )


def test_validator_rejects_duplicate_label_ids(
    tmp_path,
    label_module,
    validator_module,
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"
    item = queue_item("pair-1")
    write_queue(queue_path, [item])

    data = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )
    label_module.upsert_label(data, item, "SAME", "")
    data["labels"].append(dict(data["labels"][0]))
    label_module.save_labels(labels_path, data)

    errors, _, summary = validator_module.validate(
        queue_path,
        labels_path,
    )

    assert any("duplicado en labels" in error for error in errors)
    assert summary["unreviewed"] == 0


def test_validator_rejects_label_outside_queue(
    tmp_path,
    label_module,
    validator_module,
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"
    item = queue_item("pair-1")
    write_queue(queue_path, [item])

    data = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )
    alien = queue_item(
        "alien-pair",
        session_a=9,
        session_b=10,
        episode_pk_a=90,
        episode_pk_b=100,
    )
    label_module.upsert_label(
        data,
        alien,
        "DIFFERENT",
        "",
    )
    label_module.save_labels(labels_path, data)

    errors, _, summary = validator_module.validate(
        queue_path,
        labels_path,
    )

    assert any("fuera de la cola" in error for error in errors)
    assert summary["unreviewed"] == 1


def test_validator_rejects_identity_snapshot_mismatch(
    tmp_path,
    label_module,
    validator_module,
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"
    item = queue_item("pair-1")
    write_queue(queue_path, [item])

    data = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )
    label_module.upsert_label(
        data,
        item,
        "AMBIGUOUS",
        "",
    )
    data["labels"][0]["feature_snapshot"]["episode_pk_a"] = 999999
    label_module.save_labels(labels_path, data)

    errors, _, _ = validator_module.validate(
        queue_path,
        labels_path,
    )

    assert any(
        "snapshot.episode_pk_a" in error
        for error in errors
    )


def test_validator_rejects_same_session_snapshot(
    tmp_path,
    label_module,
    validator_module,
):
    queue_path = tmp_path / "queue.json"
    labels_path = tmp_path / "labels.json"
    item = queue_item("pair-1")
    write_queue(queue_path, [item])

    data = label_module.load_labels(
        labels_path,
        queue_path,
        "tester",
    )
    label_module.upsert_label(
        data,
        item,
        "DIFFERENT",
        "",
    )
    data["labels"][0]["feature_snapshot"]["session_b"] = 1
    label_module.save_labels(labels_path, data)

    errors, _, _ = validator_module.validate(
        queue_path,
        labels_path,
    )

    assert any(
        "no es cross-session" in error
        for error in errors
    )
