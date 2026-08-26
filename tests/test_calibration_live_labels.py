from __future__ import annotations

import json
from pathlib import Path

from race_engineer_ui_model import load_calibration_summary
from race_engineer_gui import calibration_files_fingerprint


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_calibration_summary_prefers_live_pair_labels_over_stale_batch_status(tmp_path: Path):
    batch = tmp_path / "interlagos--lmp2-elms-test"
    queue = _write_json(
        batch / "pair_review_queue.json",
        {"metadata": {}, "queue": [
            {"pair_id": f"pair-{index}", "features": {}} for index in range(24)
        ]},
    )
    labels = _write_json(
        batch / "pair_labels.json",
        {"metadata": {}, "labels": [
            {"pair_id": f"pair-{index}", "human_label": "SAME"}
            for index in range(24)
        ]},
    )
    _write_json(
        batch / "BATCH_STATUS.json",
        {
            "track": "Autódromo José Carlos Pace",
            "track_layout": "Autódromo José Carlos Pace",
            "vehicle_variant": "LMP2_ELMS",
            "batch_id": "test",
            "batch_dir": str(batch),
            "steps": {
                "vehicle_context_selection": {"session_count": 3},
                "review_queue": {"path": str(queue), "queue_pairs": 24},
                "human_labels": {
                    "labels_path": str(labels),
                    "queue_pairs": 24,
                    "labeled_pairs": 0,
                    "complete": False,
                },
                "evaluation_readiness": {"status": "NO_EVALUATION"},
                "calibration_dataset": {"calibration_ready": False},
            },
            "matcher": {"status": "NO_CALIBRATION_FOR_CONTEXT"},
        },
    )

    row = load_calibration_summary(tmp_path)["rows"][0]
    assert row["queue_pairs"] == 24
    assert row["labeled_pairs"] == 24


def test_calibration_fingerprint_changes_when_pair_labels_changes(tmp_path: Path):
    batch = tmp_path / "batch"
    _write_json(batch / "BATCH_STATUS.json", {})
    before = calibration_files_fingerprint(tmp_path)

    labels = _write_json(batch / "pair_labels.json", {"labels": []})
    after_create = calibration_files_fingerprint(tmp_path)
    assert after_create != before

    labels.write_text(
        '{"labels":[{"pair_id":"a","human_label":"SAME"}]}',
        encoding="utf-8",
    )
    after_write = calibration_files_fingerprint(tmp_path)
    assert after_write != after_create
