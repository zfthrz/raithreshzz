from __future__ import annotations

import json
from pathlib import Path

import maintain_h5_3_action_review as maintenance


def _write_pair(root: Path, revision: int, queue: dict, labels: dict) -> tuple[Path, Path]:
    queue_path = root / f"action_review_queue_v{revision}.json"
    labels_path = root / f"action_review_labels_v{revision}.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    return queue_path, labels_path


def test_no_source_artifacts_is_safe_without_existing_review(tmp_path: Path):
    input_root = tmp_path / "shadow"
    input_root.mkdir()
    result = maintenance.maintain(
        input_root=input_root,
        output_root=tmp_path / "h5_3",
        state_path=tmp_path / "state.json",
    )
    assert result == {
        "status": "NO_SOURCE_ARTIFACTS",
        "updated_at_utc": result["updated_at_utc"],
        "source_artifact_count": 0,
        "pending_review_count": 0,
        "historical_actions_authorized": False,
    }


def test_unchanged_queue_with_pending_labels_remains_review_required(
    tmp_path: Path,
    monkeypatch,
):
    input_root = tmp_path / "shadow"
    output_root = tmp_path / "h5_3"
    input_root.mkdir()
    output_root.mkdir()
    artifact = input_root / "historical_actions.json"
    artifact.write_text("{}", encoding="utf-8")
    queue = {"review_items": [{"review_id": "one"}]}
    _write_pair(output_root, 5, queue, {"labels": []})
    monkeypatch.setattr(maintenance, "build_queue", lambda paths, input_root: queue)
    monkeypatch.setattr(
        maintenance,
        "validate_labels",
        lambda queue_path, labels_path: ([], [], {"queue_items": 1, "unreviewed": 1}),
    )
    state = tmp_path / "state.json"
    result = maintenance.maintain(
        input_root=input_root,
        output_root=output_root,
        state_path=state,
    )
    assert result["status"] == "NEW_REVIEW_REQUIRED"
    assert result["pending_review_count"] == 1
    assert result["current_revision"] == 5
    assert not (output_root / "action_review_queue_v6.json").exists()
    assert result["downstream_status"] == "WAITING_FOR_HUMAN_REVIEW"


def test_changed_queue_creates_next_revision_and_migrates_exact_labels(
    tmp_path: Path, monkeypatch,
):
    input_root = tmp_path / "shadow"
    output_root = tmp_path / "h5_3"
    input_root.mkdir()
    output_root.mkdir()
    artifact = input_root / "historical_actions.json"
    artifact.write_text("{}", encoding="utf-8")
    old_queue = {"review_items": [{"review_id": "old"}]}
    old_queue_path, old_labels_path = _write_pair(
        output_root, 5, old_queue, {"labels": [{"review_id": "old"}]}
    )
    new_queue = {"review_items": [{"review_id": "old"}, {"review_id": "new"}]}
    monkeypatch.setattr(maintenance, "build_queue", lambda paths, input_root: new_queue)
    monkeypatch.setattr(
        maintenance,
        "validate_labels",
        lambda queue_path, labels_path: (
            [], [],
            {"queue_items": 1, "unreviewed": 0}
            if Path(queue_path) == old_queue_path
            else {"queue_items": 2, "unreviewed": 1},
        ),
    )
    monkeypatch.setattr(
        maintenance,
        "migrate_labels",
        lambda old_queue, old_labels, new_queue: {
            "metadata": {"migration": {"preserved_label_count": 1, "dropped_label_count": 0}},
            "labels": [{"review_id": "old"}],
        },
    )
    result = maintenance.maintain(
        input_root=input_root,
        output_root=output_root,
        state_path=tmp_path / "state.json",
    )
    assert result["status"] == "NEW_REVIEW_REQUIRED"
    assert result["current_revision"] == 6
    assert result["pending_review_count"] == 1
    assert (output_root / "action_review_queue_v6.json").is_file()
    assert (output_root / "action_review_labels_v6.json").is_file()
    assert result["downstream_status"] == "WAITING_FOR_HUMAN_REVIEW"


def test_complete_review_rebuilds_downstream_audits(tmp_path: Path, monkeypatch):
    input_root = tmp_path / "shadow"
    output_root = tmp_path / "h5_3"
    input_root.mkdir()
    output_root.mkdir()
    (input_root / "historical_actions.json").write_text("{}", encoding="utf-8")
    queue = {"review_items": [{"review_id": "one"}]}
    _write_pair(output_root, 5, queue, {"labels": [{"review_id": "one"}]})
    monkeypatch.setattr(maintenance, "build_queue", lambda paths, input_root: queue)
    monkeypatch.setattr(
        maintenance,
        "validate_labels",
        lambda queue_path, labels_path: ([], [], {"queue_items": 1, "unreviewed": 0}),
    )
    calls = []

    def rebuild(**kwargs):
        calls.append(kwargs)
        return {
            "downstream_status": "AUDITS_CURRENT",
            "downstream_revision": kwargs["revision"],
        }

    monkeypatch.setattr(maintenance, "_rebuild_downstream", rebuild)
    result = maintenance.maintain(
        input_root=input_root,
        output_root=output_root,
        state_path=tmp_path / "state.json",
    )
    assert result["downstream_status"] == "AUDITS_CURRENT"
    assert calls[0]["revision"] == 5
    assert calls[0]["pending_review_count"] == 0
