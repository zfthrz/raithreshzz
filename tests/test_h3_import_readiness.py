from __future__ import annotations

import json
from pathlib import Path

import duckdb

import h3_import_readiness as readiness
import session_history


def setup_function():
    readiness.clear_h3_import_readiness_cache()


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _batch(root: Path, *, sessions=(1, 2)) -> Path:
    batch = root / "spa--lmp2-elms"
    _write(batch / "episode_pair_features.json", [{
        "track": "Spa", "track_layout": "Spa", "vehicle_variant": "LMP2_ELMS",
        "session_a": sessions[0], "session_b": sessions[1],
    }])
    return batch


def _history(path: Path) -> None:
    duckdb.connect(str(path)).close()


def test_unmaterialized_batch_is_not_applicable(tmp_path: Path):
    batch = _batch(tmp_path / "batches")
    history = tmp_path / "history.duckdb"
    _history(history)
    row = next(iter(readiness.discover_h3_import_readiness(
        batches_root=batch.parent, history_db=history,
    ).values()))
    assert row["status"] == readiness.H3_NOT_APPLICABLE
    assert row["read_only"] is True
    assert row["historical_actions_authorized"] is False


def test_partial_materialization_fails_closed(tmp_path: Path):
    batch = _batch(tmp_path / "batches")
    _write(batch / "episode_pair_matches.json", {})
    history = tmp_path / "history.duckdb"
    _history(history)
    row = next(iter(readiness.discover_h3_import_readiness(
        batches_root=batch.parent, history_db=history,
    ).values()))
    assert row["status"] == readiness.H3_FAILED
    assert "incompleta" in row["reason"]


def test_conflict_blocks_before_history_inspection(tmp_path: Path, monkeypatch):
    batch = _batch(tmp_path / "batches")
    _write(batch / "episode_pair_matches.json", {})
    _write(batch / "persistent_patterns.json", {
        "summary": {"conflict_review_required_count": 2},
    })
    history = tmp_path / "history.duckdb"
    _history(history)
    monkeypatch.setattr(session_history, "inspect_pattern_run_import", lambda *_args: (
        (_ for _ in ()).throw(AssertionError("must not inspect"))
    ))
    row = next(iter(readiness.discover_h3_import_readiness(
        batches_root=batch.parent, history_db=history,
    ).values()))
    assert row["status"] == readiness.H3_CONFLICT
    assert row["conflict_count"] == 2


def test_valid_bundle_distinguishes_ready_and_imported(tmp_path: Path, monkeypatch):
    batch = _batch(tmp_path / "batches")
    _write(batch / "episode_pair_matches.json", {})
    _write(batch / "persistent_patterns.json", {
        "summary": {"conflict_review_required_count": 0},
    })
    history = tmp_path / "history.duckdb"
    _history(history)
    monkeypatch.setattr(session_history, "inspect_pattern_run_import", lambda *_args: {
        "status": "READY_TO_IMPORT", "pattern_count": 4,
        "observational_only": True, "historical_actions_authorized": False,
    })
    first = next(iter(readiness.discover_h3_import_readiness(
        batches_root=batch.parent, history_db=history,
    ).values()))
    assert first["status"] == readiness.H3_READY_TO_IMPORT

    readiness.clear_h3_import_readiness_cache()
    monkeypatch.setattr(session_history, "inspect_pattern_run_import", lambda *_args: {
        "status": "IMPORTED", "pattern_run_id": 7,
        "observational_only": True, "historical_actions_authorized": False,
    })
    second = next(iter(readiness.discover_h3_import_readiness(
        batches_root=batch.parent, history_db=history,
    ).values()))
    assert second["status"] == readiness.H3_IMPORTED
    assert second["pattern_run_id"] == 7


def test_largest_batch_is_selected_per_exact_context(tmp_path: Path):
    root = tmp_path / "batches"
    _batch(root)
    newer = root / "spa--lmp2-elms-new"
    _write(newer / "episode_pair_features.json", [
        {"track": "Spa", "track_layout": "Spa", "vehicle_variant": "LMP2_ELMS", "session_a": 1, "session_b": 3},
        {"track": "Spa", "track_layout": "Spa", "vehicle_variant": "LMP2_ELMS", "session_a": 2, "session_b": 4},
    ])
    history = tmp_path / "history.duckdb"
    _history(history)
    row = next(iter(readiness.discover_h3_import_readiness(
        batches_root=root, history_db=history,
    ).values()))
    assert row["batch_id"] == newer.name
    assert row["session_count"] == 4
