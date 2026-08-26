from __future__ import annotations

import json
from datetime import datetime, timezone

from race_engineer_scheduler_status import diagnostic_report, load_status, project_state


def test_active_queue_projection_counts_ready_pending_and_isolated_failures():
    status = project_state({
        "files": {
            "a": {"status": "HISTORY_READY"},
            "b": {"status": "HISTORY_READY"},
            "c": {"status": "DEBRIEF_READY"},
            "d": {"status": "FAILED"},
            "e": {"status": "BACKFILL_FAILED"},
        },
        "last_scan": {"at": "2026-08-25T23:36:00Z"},
    }, now=datetime(2026, 8, 25, 23, 37, tzinfo=timezone.utc))

    assert status.code == "QUEUE_ACTIVE"
    assert status.text == "Scheduler · 2 pendientes · 1 listos"
    assert status.style == "H53Pending.TLabel"
    assert status.history_ready == 2
    assert status.debrief_ready == 1
    assert status.failed == 2
    assert "Fallos aislados: 2" in status.detail
    assert "2026-08-25T23:36:00Z" in status.detail


def test_idle_queue_projection_is_ready_even_with_isolated_failures():
    status = project_state({
        "files": {
            "ready": {"status": "DEBRIEF_READY"},
            "failed": {"status": "FAILED"},
        }
    })

    assert status.code == "QUEUE_IDLE"
    assert status.text == "Scheduler · al día · 1 listos"
    assert status.style == "H53Ready.TLabel"


def test_missing_or_invalid_scheduler_state_fails_closed(tmp_path):
    missing = load_status(tmp_path / "missing.json")
    assert missing.code == "STATE_UNAVAILABLE"
    assert missing.style == "H53Muted.TLabel"

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps({"files": []}), encoding="utf-8")
    invalid = load_status(invalid_path)
    assert invalid.code == "STATE_INVALID"
    assert invalid.style == "H53Error.TLabel"


NOW = datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc)


def test_old_running_cycle_is_reported_as_stalled():
    status = project_state(
        {"files": {"a": {"status": "HISTORY_READY"}}},
        runtime={"status": "RUNNING", "started_at": "2026-08-25T19:40:00+00:00"},
        now=NOW,
    )

    assert status.code == "SCHEDULER_STALLED"
    assert "posible bloqueo" in status.text
    assert status.style == "H53Error.TLabel"


def test_recent_running_cycle_is_reported_as_processing():
    status = project_state(
        {"files": {"a": {"status": "HISTORY_READY"}}},
        runtime={"status": "RUNNING", "started_at": "2026-08-25T19:59:00+00:00"},
        now=NOW,
    )

    assert status.code == "SCHEDULER_RUNNING"
    assert "procesando" in status.text


def test_repeated_debrief_failure_is_reported_as_blocking_queue():
    status = project_state({
        "files": {
            "C:/telemetry/broken.duckdb": {
                "status": "HISTORY_READY",
                "debrief_attempts": 3,
                "last_debrief_error": "RuntimeError: validator failed",
            },
            "C:/telemetry/waiting.duckdb": {"status": "HISTORY_READY"},
        }
    }, now=NOW)

    assert status.code == "QUEUE_BLOCKED"
    assert "cola bloqueada" in status.text
    assert "broken.duckdb" in status.detail
    assert "validator failed" in status.detail


def test_old_heartbeat_is_reported_as_scheduler_stale():
    status = project_state({
        "files": {},
        "last_scan": {"at": "2026-08-25T19:50:00+00:00"},
    }, now=NOW)

    assert status.code == "SCHEDULER_STALE"
    assert "sin actividad" in status.text


def test_deferred_sessions_are_visible_but_not_counted_as_active_queue():
    status = project_state({
        "files": {
            "C:/telemetry/deferred.duckdb": {"status": "DEBRIEF_DEFERRED"},
            "C:/telemetry/ready.duckdb": {"status": "DEBRIEF_READY"},
        }
    }, now=NOW)

    assert status.code == "QUEUE_IDLE"
    assert status.history_ready == 0
    assert status.deferred_paths == ("C:/telemetry/deferred.duckdb",)
    assert "Pospuestos manualmente: 1" in status.detail


def test_load_status_combines_ingest_and_runtime_files(tmp_path):
    state_path = tmp_path / "ingest.json"
    runtime_path = tmp_path / "runtime.json"
    state_path.write_text(json.dumps({"files": {}}), encoding="utf-8")
    runtime_path.write_text(json.dumps({
        "status": "FAILED",
        "started_at": "2026-08-25T19:59:00+00:00",
        "finished_at": "2026-08-25T19:59:05+00:00",
        "exit_code": 1,
    }), encoding="utf-8")

    status = load_status(state_path, runtime_path)

    assert status.code == "SCHEDULER_FAILED"
    assert "último ciclo falló" in status.text


def test_diagnostic_report_is_copy_friendly_and_read_only(tmp_path):
    state_path = tmp_path / "ingest.json"
    runtime_path = tmp_path / "runtime.json"
    log_path = tmp_path / "task.log"
    state_path.write_text(json.dumps({
        "files": {
            "C:/telemetry/problem.duckdb": {
                "status": "HISTORY_READY",
                "debrief_attempts": 3,
                "last_debrief_error": "validator failed",
            }
        }
    }), encoding="utf-8")
    runtime_path.write_text(json.dumps({
        "status": "PASS",
        "started_at": "2026-08-25T19:59:00+00:00",
        "finished_at": "2026-08-25T19:59:04+00:00",
        "last_successful_at": "2026-08-25T19:59:04+00:00",
        "exit_code": 0,
        "pid": 123,
    }), encoding="utf-8")

    report = diagnostic_report(state_path, runtime_path, log_path)

    assert "QUEUE_BLOCKED" in report
    assert "problem.duckdb" in report
    assert "validator failed" in report
    assert "último éxito: 2026-08-25T19:59:04+00:00" in report
    assert str(log_path) in report
    assert "read-only" in report
