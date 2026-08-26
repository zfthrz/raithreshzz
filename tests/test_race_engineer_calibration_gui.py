from __future__ import annotations

import json
from pathlib import Path

import pytest

from race_engineer_calibration_gui import (
    CalibrationLabelingTarget,
    build_calibration_labeling_powershell_command,
    resolve_calibration_labeling_target,
)


def _write_batch(
    root: Path,
    name: str,
    *,
    batch_id: str,
    complete: bool = False,
    queue_pairs: int = 24,
    labeled_pairs: int = 0,
) -> Path:
    batch = root / name
    batch.mkdir(parents=True)
    queue = batch / "pair_review_queue.json"
    queue.write_text('{"metadata": {}, "queue": []}', encoding="utf-8")
    labels = batch / "pair_labels.json"
    payload = {
        "batch_id": batch_id,
        "batch_dir": str(batch),
        "steps": {
            "review_queue": {
                "status": "PASS",
                "path": str(queue),
                "queue_pairs": queue_pairs,
            },
            "human_labels": {
                "status": "PASS" if complete else "WAITING",
                "labels_path": str(labels),
                "queue_pairs": queue_pairs,
                "labeled_pairs": labeled_pairs,
                "complete": complete,
            },
        },
    }
    (batch / "BATCH_STATUS.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return batch


def test_resolves_exact_batch_id_to_queue_and_labels(tmp_path: Path):
    batch = _write_batch(
        tmp_path, "fuji--lmp2-elms-abc", batch_id="abc", labeled_pairs=7
    )
    target = resolve_calibration_labeling_target(tmp_path, batch_id="abc")
    assert target.batch_dir == batch.resolve()
    assert target.queue_path == (batch / "pair_review_queue.json").resolve()
    assert target.labels_path == (batch / "pair_labels.json").resolve()
    assert target.labeled_pairs == 7
    assert target.complete is False


def test_complete_batch_is_reported_without_launching(tmp_path: Path):
    batch = _write_batch(
        tmp_path,
        "spa--lmp2-elms-def",
        batch_id="def",
        complete=True,
        labeled_pairs=24,
    )
    (batch / "pair_review_queue.json").write_text(
        json.dumps({"queue": [{"pair_id": "pair-a"}]}),
        encoding="utf-8",
    )
    (batch / "pair_labels.json").write_text(
        json.dumps({
            "labels": [{"pair_id": "pair-a", "human_label": "SAME"}]
        }),
        encoding="utf-8",
    )
    target = resolve_calibration_labeling_target(tmp_path, batch_id="def")
    assert target.complete is True


def test_live_labels_override_stale_status_counts(tmp_path: Path):
    batch = _write_batch(tmp_path, "monza", batch_id="live", labeled_pairs=0)
    (batch / "pair_review_queue.json").write_text(
        json.dumps({"queue": [{"pair_id": "a"}, {"pair_id": "b"}]}),
        encoding="utf-8",
    )
    (batch / "pair_labels.json").write_text(
        json.dumps({"labels": [{"pair_id": "a", "human_label": "DIFFERENT"}]}),
        encoding="utf-8",
    )

    target = resolve_calibration_labeling_target(tmp_path, batch_id="live")

    assert target.queue_pairs == 2
    assert target.labeled_pairs == 1
    assert target.complete is False


def test_duplicate_batch_id_fails_closed(tmp_path: Path):
    _write_batch(tmp_path, "batch-a", batch_id="same")
    _write_batch(tmp_path, "batch-b", batch_id="same")
    with pytest.raises(ValueError, match="ambiguo"):
        resolve_calibration_labeling_target(tmp_path, batch_id="same")


def test_powershell_command_uses_existing_labeler_contract(tmp_path: Path):
    (tmp_path / "label_episode_pairs.py").write_text("", encoding="utf-8")
    queue = tmp_path / "queue.json"
    labels = tmp_path / "labels.json"
    target = CalibrationLabelingTarget(
        batch_id="x",
        batch_dir=tmp_path,
        queue_path=queue,
        labels_path=labels,
        queue_pairs=24,
        labeled_pairs=0,
        complete=False,
    )
    command = build_calibration_labeling_powershell_command(tmp_path, target)
    joined = " ".join(command)
    assert "powershell.exe" in command[0]
    assert "label_episode_pairs.py" in joined
    assert str(queue) in joined
    assert "--labels" in joined
    assert str(labels) in joined
