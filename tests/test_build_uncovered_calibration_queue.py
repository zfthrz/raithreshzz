import hashlib
import json
from pathlib import Path

import pytest

from build_uncovered_calibration_queue import (
    build_documents,
    collect_uncovered,
    write_documents,
)
from race_engineer_ui_model import load_calibration_summary


CONTEXT = ("Test Track", "Test Layout", "LMP2_ELMS")


def write_batch(root: Path, name: str, pairs: list[str], labels: dict[str, str], sessions: list[int]):
    batch = root / name
    batch.mkdir()
    queue_path = batch / "pair_review_queue.json"
    queue = {
        "metadata": {"queue_schema_version": "1.1"},
        "queue": [
            {"pair_id": pair_id, "features": {"track": CONTEXT[0], "session_a": 1, "session_b": 2}}
            for pair_id in pairs
        ],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    labels_path = batch / "pair_labels.json"
    if labels:
        labels_path.write_text(json.dumps({"labels": [
            {"pair_id": pair_id, "human_label": label} for pair_id, label in labels.items()
        ]}), encoding="utf-8")
    status = {
        "track": CONTEXT[0], "track_layout": CONTEXT[1], "vehicle_variant": CONTEXT[2],
        "batch_id": name,
        "steps": {
            "vehicle_context_selection": {"session_count": len(sessions), "session_ids": sessions},
            "review_queue": {"path": str(queue_path)},
            "human_labels": {"labels_path": str(labels_path)},
        },
    }
    (batch / "BATCH_STATUS.json").write_text(json.dumps(status), encoding="utf-8")


def test_collects_only_uncovered_and_deduplicates(tmp_path: Path):
    write_batch(tmp_path, "old", ["a", "b"], {"a": "SAME"}, [1, 2])
    write_batch(tmp_path, "new", ["b", "c"], {}, [1, 2, 3])
    result = collect_uncovered(tmp_path, CONTEXT)
    assert [item["pair_id"] for item in result["queue"]] == ["b", "c"]
    assert [item["queue_position"] for item in result["queue"]] == [1, 2]
    assert result["session_ids"] == [1, 2, 3]


def test_conflicting_duplicate_fails_closed(tmp_path: Path):
    write_batch(tmp_path, "one", ["a"], {}, [1, 2])
    write_batch(tmp_path, "two", ["a"], {}, [1, 2])
    queue_path = tmp_path / "two" / "pair_review_queue.json"
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    data["queue"][0]["features"]["session_b"] = 9
    queue_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="conflictiva"):
        collect_uncovered(tmp_path, CONTEXT)


def test_documents_are_stable_and_labeler_compatible(tmp_path: Path):
    write_batch(tmp_path, "one", ["a"], {}, [1, 2])
    result = collect_uncovered(tmp_path, CONTEXT)
    batch_dir, queue, status = build_documents(result, tmp_path)
    assert batch_dir.name.endswith(status["batch_id"])
    assert queue["metadata"]["selection_policy"] == "uncovered_human_evidence_v0.1"
    assert queue["queue"][0]["features"]["session_a"] != queue["queue"][0]["features"]["session_b"]
    assert status["steps"]["human_labels"]["unreviewed_pairs"] == 1
    assert not batch_dir.exists()


def test_rewrite_preserves_queue_hash_and_rejects_change_after_labels(tmp_path: Path):
    write_batch(tmp_path, "one", ["a"], {}, [1, 2])
    result = collect_uncovered(tmp_path, CONTEXT)
    batch_dir, queue, status = build_documents(result, tmp_path)
    write_documents(batch_dir, queue, status)
    queue_path = batch_dir / "pair_review_queue.json"
    first_hash = hashlib.sha256(queue_path.read_bytes()).hexdigest()

    queue["metadata"]["created_at_utc"] = "later"
    write_documents(batch_dir, queue, status)
    assert hashlib.sha256(queue_path.read_bytes()).hexdigest() == first_hash

    (batch_dir / "pair_labels.json").write_text('{"labels": []}', encoding="utf-8")
    queue["queue"][0]["features"]["session_b"] = 99
    with pytest.raises(ValueError, match="no se sobrescribe"):
        write_documents(batch_dir, queue, status)


def test_gui_prefers_pending_batch_for_same_context(tmp_path: Path):
    write_batch(tmp_path, "complete", ["a"], {"a": "SAME"}, [1, 2, 3])
    result = collect_uncovered(tmp_path, CONTEXT)
    batch_dir, queue, status = build_documents(result, tmp_path)
    # Add a genuinely uncovered pair after collecting coverage from the old batch.
    queue["queue"] = [{"pair_id": "b", "features": {"track": CONTEXT[0]}}]
    status["steps"]["review_queue"]["queue_pairs"] = 1
    status["steps"]["human_labels"].update(
        {"queue_pairs": 1, "labeled_pairs": 0, "unreviewed_pairs": 1, "complete": False}
    )
    write_documents(batch_dir, queue, status)
    row = load_calibration_summary(tmp_path)["rows"][0]
    assert row["batch_id"].startswith("uncovered-")
    assert (row["labeled_pairs"], row["queue_pairs"]) == (0, 1)


def test_fully_covered_context_has_empty_queue(tmp_path: Path):
    write_batch(tmp_path, "complete", ["a"], {"a": "DIFFERENT"}, [1, 2])
    result = collect_uncovered(tmp_path, CONTEXT)
    assert result["queue"] == []


def test_gui_counts_labels_from_newer_batch_as_global_context_coverage(tmp_path: Path):
    write_batch(tmp_path, "old", ["a", "b"], {}, [1, 2])
    write_batch(tmp_path, "new", ["a", "b"], {"a": "SAME", "b": "DIFFERENT"}, [1, 2])
    rows = load_calibration_summary(tmp_path)["rows"]
    assert len(rows) == 1
    assert (rows[0]["labeled_pairs"], rows[0]["queue_pairs"]) == (2, 2)
