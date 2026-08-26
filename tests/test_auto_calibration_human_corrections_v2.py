from __future__ import annotations

import json
from pathlib import Path

import auto_calibrate_matcher as auto


def _write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _batch(root: Path, name: str, label: str, reviewed_at: str):
    batch = root / name
    pair_id = "stable-pair"
    features = {
        "track": "Autódromo José Carlos Pace",
        "track_layout": "Autódromo José Carlos Pace",
        "vehicle_variant": "LMP2_ELMS",
        "session_a": 1,
        "session_b": 2,
        "center_distance_abs_diff_m": 2.0,
        "overlap_over_shorter": 1.0,
        "overlap_over_union": 0.8,
        "shared_channels": ["brake"],
    }

    _write(batch / "pair_review_queue.json", {
        "queue": [{
            "pair_id": pair_id,
            "features": features,
            "selected_by": [],
        }]
    })
    _write(batch / "pair_labels.json", {
        "labels": [{
            "pair_id": pair_id,
            "human_label": label,
            "reviewed_at_utc": reviewed_at,
        }]
    })
    _write(batch / "BATCH_STATUS.json", {
        "track": features["track"],
        "track_layout": features["track_layout"],
        "vehicle_variant": features["vehicle_variant"],
        "batch_id": name,
        "batch_dir": str(batch),
        "steps": {
            "review_queue": {"path": str(batch / "pair_review_queue.json")},
            "human_labels": {"labels_path": str(batch / "pair_labels.json")},
        },
    })


def test_newer_human_correction_supersedes_old_label(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "validate_pair_labels", lambda *args: ([], [], {}))
    _batch(tmp_path, "older", "DIFFERENT", "2026-08-26T03:00:00+00:00")
    _batch(tmp_path, "newer", "SAME", "2026-08-26T04:00:00+00:00")

    grouped, conflicts = auto.collect_records(tmp_path)
    key = (
        "Autódromo José Carlos Pace",
        "Autódromo José Carlos Pace",
        "LMP2_ELMS",
    )
    assert conflicts.get(key) in (None, [])
    assert len(grouped[key]) == 1
    assert grouped[key][0]["human_label"] == "SAME"
    assert grouped[key][0]["reviewed_at_utc"] == "2026-08-26T04:00:00+00:00"


def test_equal_timestamp_conflict_stays_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "validate_pair_labels", lambda *args: ([], [], {}))
    _batch(tmp_path, "a", "DIFFERENT", "2026-08-26T04:00:00+00:00")
    _batch(tmp_path, "b", "SAME", "2026-08-26T04:00:00+00:00")

    _grouped, conflicts = auto.collect_records(tmp_path)
    key = (
        "Autódromo José Carlos Pace",
        "Autódromo José Carlos Pace",
        "LMP2_ELMS",
    )
    assert conflicts[key] == ["stable-pair"]
