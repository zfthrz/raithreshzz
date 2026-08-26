from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scheduler_queue_actions import defer_blocking_debrief, resume_deferred_debrief


NOW = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc)


def write_state(path, entry):
    path.write_text(json.dumps({"version": "0.1", "files": {"db": entry}}), encoding="utf-8")


def read_entry(path):
    return json.loads(path.read_text(encoding="utf-8"))["files"]["db"]


def test_defer_and_resume_are_reversible_and_preserve_error(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(state_path, {
        "status": "HISTORY_READY",
        "debrief_attempts": 3,
        "last_debrief_error": "validator failed",
        "history_ready_at": "2026-08-25T20:00:00Z",
    })

    defer_blocking_debrief(state_path, "db", now=NOW)
    deferred = read_entry(state_path)
    assert deferred["status"] == "DEBRIEF_DEFERRED"
    assert deferred["last_debrief_error"] == "validator failed"
    assert deferred["debrief_attempts"] == 3

    resume_deferred_debrief(state_path, "db", now=NOW)
    resumed = read_entry(state_path)
    assert resumed["status"] == "HISTORY_READY"
    assert resumed["debrief_attempts"] == 0
    assert resumed["last_debrief_error"] == "validator failed"
    assert resumed["history_ready_at"] == "2026-08-26T01:00:00Z"


def test_defer_rejects_unconfirmed_failure(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(state_path, {
        "status": "HISTORY_READY",
        "debrief_attempts": 2,
        "last_debrief_error": "validator failed",
    })

    with pytest.raises(ValueError, match="bloqueo confirmado"):
        defer_blocking_debrief(state_path, "db", now=NOW)

    assert read_entry(state_path)["status"] == "HISTORY_READY"


def test_manual_action_rejects_running_scheduler(tmp_path):
    state_path = tmp_path / "state.json"
    runtime_path = tmp_path / "runtime.json"
    write_state(state_path, {
        "status": "HISTORY_READY",
        "debrief_attempts": 3,
        "last_debrief_error": "validator failed",
    })
    runtime_path.write_text(json.dumps({"status": "RUNNING"}), encoding="utf-8")

    with pytest.raises(ValueError, match="está ejecutándose"):
        defer_blocking_debrief(
            state_path,
            "db",
            now=NOW,
            runtime_path=runtime_path,
        )

    assert read_entry(state_path)["status"] == "HISTORY_READY"
