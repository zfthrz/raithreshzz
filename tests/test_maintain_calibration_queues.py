from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import maintain_calibration_queues as maintenance


NOW = datetime(2026, 8, 26, 2, 0, tzinfo=timezone.utc)
CONTEXT = ("Test Track", "Test Layout", "LMP2_ELMS")


def rows(*ids):
    return [
        {
            "session_id": session_id,
            "track": CONTEXT[0],
            "lmu_track_layout": CONTEXT[1],
            "vehicle_variant": CONTEXT[2],
            "vehicle_supported_domain": True,
        }
        for session_id in ids
    ]


def write_existing_batch(root, ids):
    batch = root / "existing"
    batch.mkdir(parents=True)
    (batch / "BATCH_STATUS.json").write_text(json.dumps({
        "track": CONTEXT[0],
        "track_layout": CONTEXT[1],
        "vehicle_variant": CONTEXT[2],
        "steps": {"vehicle_context_selection": {"session_ids": list(ids)}},
    }), encoding="utf-8")


def test_existing_exact_batch_is_baselined_without_running(tmp_path):
    batches = tmp_path / "batches"
    write_existing_batch(batches, [1, 2])
    calls = []

    result = maintenance.maintain(
        db_path=tmp_path / "history.duckdb",
        analysis_dir=tmp_path / "analysis",
        batches_root=batches,
        state_path=tmp_path / "state.json",
        project_root=tmp_path,
        history_loader=lambda path: rows(1, 2),
        runner=lambda *args, **kwargs: calls.append(args),
        now=NOW,
    )

    assert result == 0
    assert calls == []
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["contexts"][maintenance.context_key(CONTEXT)]["status"] == "QUEUE_ALREADY_PREPARED"


def test_changed_context_prepares_queue_without_import_or_llm(tmp_path):
    batches = tmp_path / "batches"
    write_existing_batch(batches, [1, 2])
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    result = maintenance.maintain(
        db_path=tmp_path / "history.duckdb",
        analysis_dir=tmp_path / "analysis",
        batches_root=batches,
        state_path=tmp_path / "state.json",
        project_root=tmp_path,
        history_loader=lambda path: rows(1, 2, 3),
        runner=runner,
        now=NOW,
    )

    assert result == 0
    command = calls[0][0]
    assert "--skip-import" in command
    assert "--track" in command
    assert "--track-layout" in command
    assert "--vehicle-variant" in command
    assert all("llm" not in argument.casefold() for argument in command)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["contexts"][maintenance.context_key(CONTEXT)]["session_ids"] == [1, 2, 3]
    assert state["contexts"][maintenance.context_key(CONTEXT)]["status"] == "QUEUE_PREPARED"


def test_context_requires_two_supported_sessions(tmp_path):
    calls = []
    result = maintenance.maintain(
        db_path=tmp_path / "history.duckdb",
        batches_root=tmp_path / "batches",
        state_path=tmp_path / "state.json",
        history_loader=lambda path: rows(1),
        runner=lambda *args, **kwargs: calls.append(args),
        now=NOW,
    )

    assert result == 0
    assert calls == []


def test_prepare_restores_shared_bootstrap_files(tmp_path):
    batches = tmp_path / "batches"
    batches.mkdir()
    bootstrap = batches / "BATCH_STATUS.json"
    bootstrap.write_text("original\n", encoding="utf-8")

    def runner(command, **kwargs):
        bootstrap.write_text("generated\n", encoding="utf-8")
        (batches / "00_history_init.log").write_text("temporary", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    assert maintenance.maintain(
        db_path=tmp_path / "history.duckdb",
        analysis_dir=tmp_path / "analysis",
        batches_root=batches,
        state_path=tmp_path / "state.json",
        project_root=tmp_path,
        history_loader=lambda path: rows(1, 2),
        runner=runner,
        now=NOW,
    ) == 0

    assert bootstrap.read_text(encoding="utf-8") == "original\n"
    assert not (batches / "00_history_init.log").exists()


def test_unchanged_failed_context_does_not_block_future_cycles(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "version": "0.1",
        "contexts": {
            maintenance.context_key(CONTEXT): {
                "session_ids": [1, 2],
                "status": "PREPARATION_FAILED",
            }
        },
    }), encoding="utf-8")
    calls = []

    assert maintenance.maintain(
        db_path=tmp_path / "history.duckdb",
        batches_root=tmp_path / "batches",
        state_path=state_path,
        history_loader=lambda path: rows(1, 2),
        runner=lambda *args, **kwargs: calls.append(args),
        now=NOW,
    ) == 0

    assert calls == []
