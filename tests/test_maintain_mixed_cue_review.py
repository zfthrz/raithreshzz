from __future__ import annotations

import json
from pathlib import Path

import maintain_mixed_cue_review as maintenance
from label_mixed_cue_review_queue import load_labels, save, upsert
from prepare_mixed_cue_review_queue import build_queue
from tests.test_mixed_cue_review_queue import debrief


def seed(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = debrief(tmp_path / "source.json")
    queue = build_queue([source])
    queue_path = tmp_path / "seed_queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    labels_path = tmp_path / "seed_labels.json"
    labels = load_labels(labels_path, queue_path)
    upsert(labels, queue["review_items"][0], "FOCUSED_PLUS_PROFILE_BETTER", "")
    save(labels_path, labels)
    return source, queue_path, labels_path


def test_first_revision_migrates_only_exact_seed_label(tmp_path: Path, monkeypatch):
    source, queue_path, labels_path = seed(tmp_path)
    monkeypatch.setattr(
        maintenance,
        "current_validated_debrief_paths",
        lambda _: [source],
    )
    output = tmp_path / "revisions"

    result = maintenance.maintain(
        tmp_path,
        output,
        seed_queue_path=queue_path,
        seed_labels_path=labels_path,
    )

    assert result["status"] == "REVIEW_COMPLETE"
    assert result["revision"] == 1
    assert result["migrated_labels"] == 1
    assert result["reviewed"] == 1
    assert result["new_labels_invented"] == 0


def test_changed_queue_creates_revision_and_preserves_exact_labels(tmp_path: Path, monkeypatch):
    source, queue_path, labels_path = seed(tmp_path)
    output = tmp_path / "revisions"
    monkeypatch.setattr(maintenance, "current_validated_debrief_paths", lambda _: [source])
    maintenance.maintain(
        tmp_path,
        output,
        seed_queue_path=queue_path,
        seed_labels_path=labels_path,
    )
    document = json.loads(source.read_text(encoding="utf-8"))
    document["session_coaching_facts"]["next_stint_plan"][0]["track_location"]["label"] = "T2"
    source.write_text(json.dumps(document), encoding="utf-8")
    changed = maintenance.maintain(tmp_path, output)

    assert changed["revision"] == 2
    assert changed["pending"] == 1
    assert changed["migrated_labels"] == 0


def test_new_case_creates_pending_without_inventing_label(tmp_path: Path, monkeypatch):
    first_source, queue_path, labels_path = seed(tmp_path)
    second_source = debrief(tmp_path / "second.json")
    second_document = json.loads(second_source.read_text(encoding="utf-8"))
    second_document["session_coaching_facts"]["next_stint_plan"][0]["track_location"]["label"] = "T2"
    second_source.write_text(json.dumps(second_document), encoding="utf-8")
    output = tmp_path / "revisions"
    monkeypatch.setattr(
        maintenance,
        "current_validated_debrief_paths",
        lambda _: [first_source, second_source],
    )

    result = maintenance.maintain(
        tmp_path,
        output,
        seed_queue_path=queue_path,
        seed_labels_path=labels_path,
    )

    assert result["status"] == "WAITING_FOR_HUMAN_REVIEW"
    assert result["review_items"] == 2
    assert result["migrated_labels"] == 1
    assert result["pending"] == 1
    assert result["new_labels_invented"] == 0


def test_unchanged_revision_is_reused(tmp_path: Path, monkeypatch):
    source = debrief(tmp_path / "source.json")
    monkeypatch.setattr(maintenance, "current_validated_debrief_paths", lambda _: [source])
    output = tmp_path / "revisions"

    first = maintenance.maintain(tmp_path, output)
    second = maintenance.maintain(tmp_path, output)

    assert first["revision"] == 1
    assert second["status"] == "UP_TO_DATE"
    assert second["revision"] == 1
