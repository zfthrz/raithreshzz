from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import auto_ingest_telemetry as ingest


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def make_db(directory: Path, name: str = "session.duckdb") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"duckdb-test")
    return path.resolve()


def read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_baseline_registers_existing_files_without_running_analysis(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"

    assert ingest.baseline(telemetry, state_path, now=NOW) == 0

    entry = read_state(state_path)["files"][str(database)]
    assert entry["status"] == ingest.STATUS_BASELINED
    assert "history_ready_at" not in entry


def test_migrate_source_preserves_exact_match_and_registers_only_new_file(
    tmp_path: Path,
):
    old_source = tmp_path / "old"
    new_source = tmp_path / "lmu"
    old_match = make_db(old_source, "shared.duckdb")
    new_source.mkdir(parents=True)
    new_match = new_source / old_match.name
    new_match.write_bytes(old_match.read_bytes())
    old_stat = old_match.stat()
    os.utime(new_match, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    new_match = new_match.resolve()
    new_file = make_db(new_source, "new.duckdb")
    state_path = tmp_path / "state.json"
    state = ingest.empty_state()
    state["files"][str(old_match)] = {
        "status": ingest.STATUS_HISTORY_READY,
        "signature": ingest.signature(old_match),
        "history_ready_at": "2026-08-17T11:00:00Z",
    }
    ingest.save_state(state_path, state)

    assert ingest.migrate_source(new_source, state_path, now=NOW) == 0

    updated = read_state(state_path)
    assert str(old_match) not in updated["files"]
    assert updated["files"][str(new_match)]["status"] == ingest.STATUS_HISTORY_READY
    assert updated["files"][str(new_match)]["migrated_from"] == str(old_match)
    assert updated["files"][str(new_file)]["status"] == (
        ingest.STATUS_PENDING_STABILITY
    )
    assert updated["last_source_migration"]["migrated"] == 1
    assert updated["last_source_migration"]["registered_new"] == 1


def test_scan_waits_for_stability_then_imports_history_without_llm(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"
    calls: list[tuple[Path, list[str]]] = []

    def runner(path: Path, args: list[str]) -> None:
        calls.append((path, args))

    assert ingest.scan(
        telemetry,
        state_path,
        settle_seconds=600,
        now=NOW,
        runner=runner,
        probe=lambda path: None,
    ) == 0
    assert calls == []
    assert read_state(state_path)["files"][str(database)]["status"] == (
        ingest.STATUS_PENDING_STABILITY
    )

    assert ingest.scan(
        telemetry,
        state_path,
        settle_seconds=600,
        now=NOW + timedelta(minutes=10),
        runner=runner,
        probe=lambda path: None,
    ) == 0
    assert calls == [(
        database,
        ["--no-llm", "--no-historical-context"],
    )]
    assert read_state(state_path)["files"][str(database)]["status"] == (
        ingest.STATUS_HISTORY_READY
    )


def test_backfill_next_processes_only_newest_large_baseline(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    small = make_db(telemetry, "small.duckdb")
    older = make_db(telemetry, "older.duckdb")
    newest = make_db(telemetry, "newest.duckdb")
    state_path = tmp_path / "state.json"
    calls: list[tuple[Path, list[str]]] = []
    state = ingest.empty_state()
    state["files"] = {
        str(small): {
            "status": ingest.STATUS_BASELINED,
            "signature": {"size": 4 * 1024 * 1024, "mtime_ns": 300},
        },
        str(older): {
            "status": ingest.STATUS_BASELINED,
            "signature": {"size": 7 * 1024 * 1024, "mtime_ns": 100},
        },
        str(newest): {
            "status": ingest.STATUS_BASELINED,
            "signature": {"size": 8 * 1024 * 1024, "mtime_ns": 200},
        },
    }
    ingest.save_state(state_path, state)

    assert ingest.backfill_next(
        state_path,
        min_size_mb=5,
        now=NOW,
        runner=lambda path, args: calls.append((path, args)),
        probe=lambda path: None,
        pipeline_status_reader=lambda path: None,
    ) == 0

    assert calls == [(
        newest,
        ["--no-llm", "--no-historical-context"],
    )]
    updated = read_state(state_path)["files"]
    assert updated[str(newest)]["status"] == ingest.STATUS_HISTORY_READY
    assert updated[str(older)]["status"] == ingest.STATUS_BASELINED
    assert updated[str(small)]["status"] == ingest.STATUS_BASELINE_SKIPPED_SMALL


def test_failed_backfill_is_terminal_for_automatic_scan(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"
    state = ingest.empty_state()
    state["files"][str(database)] = {
        "status": ingest.STATUS_BASELINED,
        "signature": ingest.signature(database),
    }
    ingest.save_state(state_path, state)

    def fail(path: Path, args: list[str]) -> None:
        raise RuntimeError("invalid telemetry")

    assert ingest.backfill_next(
        state_path,
        min_size_mb=0,
        now=NOW,
        runner=fail,
        probe=lambda path: None,
        pipeline_status_reader=lambda path: None,
        analysis_reader=lambda path: None,
    ) == 1
    assert read_state(state_path)["files"][str(database)]["status"] == (
        ingest.STATUS_BACKFILL_FAILED
    )

    calls: list[Path] = []
    assert ingest.scan(
        telemetry,
        state_path,
        settle_seconds=0,
        now=NOW + timedelta(minutes=5),
        runner=lambda path, args: calls.append(path),
        probe=lambda path: None,
    ) == 0
    assert calls == []


def test_backfill_reconciles_existing_history_and_validated_debrief(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    history_only = make_db(telemetry, "history.duckdb")
    complete = make_db(telemetry, "complete.duckdb")
    pending = make_db(telemetry, "pending.duckdb")
    state_path = tmp_path / "state.json"
    state = ingest.empty_state()
    state["files"] = {
        str(history_only): {
            "status": ingest.STATUS_BASELINED,
            "signature": {"size": 8 * 1024 * 1024, "mtime_ns": 300},
        },
        str(complete): {
            "status": ingest.STATUS_HISTORY_READY,
            "signature": {"size": 8 * 1024 * 1024, "mtime_ns": 200},
        },
        str(pending): {
            "status": ingest.STATUS_BASELINED,
            "signature": {"size": 8 * 1024 * 1024, "mtime_ns": 100},
        },
    }
    ingest.save_state(state_path, state)
    existing = {
        history_only: (ingest.STATUS_HISTORY_READY, 20),
        complete: (ingest.STATUS_DEBRIEF_READY, 19),
    }
    calls: list[Path] = []

    assert ingest.backfill_next(
        state_path,
        min_size_mb=0,
        now=NOW,
        runner=lambda path, args: calls.append(path),
        probe=lambda path: None,
        pipeline_status_reader=lambda path: existing.get(path),
    ) == 0

    assert calls == [pending]
    updated = read_state(state_path)["files"]
    assert updated[str(history_only)]["status"] == ingest.STATUS_HISTORY_READY
    assert updated[str(history_only)]["reconciled_session_id"] == 20
    assert updated[str(complete)]["status"] == ingest.STATUS_DEBRIEF_READY
    assert updated[str(complete)]["reconciled_session_id"] == 19


def test_repeated_scan_does_not_reimport_unchanged_database(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"
    calls: list[Path] = []
    runner = lambda path, args: calls.append(path)

    ingest.scan(
        telemetry,
        state_path,
        settle_seconds=0,
        now=NOW,
        runner=runner,
        probe=lambda path: None,
    )
    ingest.scan(
        telemetry,
        state_path,
        settle_seconds=0,
        now=NOW + timedelta(minutes=5),
        runner=runner,
        probe=lambda path: None,
    )

    assert calls == [database]


def test_maintenance_prioritizes_new_pending_file_over_backfill(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"
    calls: list[Path] = []

    assert ingest.maintenance(
        telemetry,
        state_path,
        settle_seconds=600,
        min_size_mb=5,
        backfill_minutes=30,
        now=NOW,
        runner=lambda path, args: calls.append(path),
        probe=lambda path: None,
        pipeline_status_reader=lambda path: None,
        game_running=lambda: False,
    ) == 0

    assert calls == []
    assert read_state(state_path)["last_scan"]["pending"] == 1
    assert read_state(state_path)["files"][str(database)]["status"] == (
        ingest.STATUS_PENDING_STABILITY
    )


def test_maintenance_runs_one_backfill_when_scan_is_idle_and_cooldown_elapsed(
    tmp_path: Path,
):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"
    state = ingest.empty_state()
    state["files"][str(database)] = {
        "status": ingest.STATUS_BASELINED,
        "signature": ingest.signature(database),
    }
    ingest.save_state(state_path, state)
    calls: list[tuple[Path, list[str]]] = []

    assert ingest.maintenance(
        telemetry,
        state_path,
        settle_seconds=600,
        min_size_mb=0,
        backfill_minutes=30,
        now=NOW,
        runner=lambda path, args: calls.append((path, args)),
        probe=lambda path: None,
        pipeline_status_reader=lambda path: None,
        game_running=lambda: False,
    ) == 0
    assert calls == [(
        database,
        ["--no-llm", "--no-historical-context"],
    )]

    assert ingest.maintenance(
        telemetry,
        state_path,
        settle_seconds=600,
        min_size_mb=0,
        backfill_minutes=30,
        now=NOW + timedelta(minutes=5),
        runner=lambda path, args: calls.append((path, args)),
        probe=lambda path: None,
        pipeline_status_reader=lambda path: None,
        game_running=lambda: False,
    ) == 0
    assert len(calls) == 1


def test_maintenance_does_nothing_while_le_mans_ultimate_is_running(
    tmp_path: Path,
):
    telemetry = tmp_path / "telemetria"
    make_db(telemetry)
    state_path = tmp_path / "state.json"
    calls: list[Path] = []

    assert ingest.maintenance(
        telemetry,
        state_path,
        settle_seconds=0,
        min_size_mb=0,
        backfill_minutes=30,
        now=NOW,
        runner=lambda path, args: calls.append(path),
        probe=lambda path: calls.append(path),
        pipeline_status_reader=lambda path: None,
        game_running=lambda: True,
    ) == 0

    assert calls == []
    state = read_state(state_path)
    assert state["files"] == {}
    assert state["last_maintenance"] == {
        "at": "2026-08-17T12:00:00Z",
        "status": "SKIPPED_GAME_RUNNING",
        "process_image": "Le Mans Ultimate.exe",
    }
    assert state["last_game_seen_at"] == "2026-08-17T12:00:00Z"


def test_maintenance_waits_full_settle_window_after_game_closes(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    make_db(telemetry)
    state_path = tmp_path / "state.json"
    state = ingest.empty_state()
    state["last_game_seen_at"] = "2026-08-17T12:00:00Z"
    ingest.save_state(state_path, state)
    calls: list[Path] = []

    assert ingest.maintenance(
        telemetry,
        state_path,
        settle_seconds=600,
        min_size_mb=0,
        backfill_minutes=30,
        now=NOW + timedelta(minutes=5),
        runner=lambda path, args: calls.append(path),
        probe=lambda path: calls.append(path),
        pipeline_status_reader=lambda path: None,
        game_running=lambda: False,
    ) == 0

    assert calls == []
    updated = read_state(state_path)
    assert updated["files"] == {}
    assert updated["last_maintenance"]["status"] == "POST_GAME_SETTLE"
    assert updated["last_maintenance"]["remaining_seconds"] == 300.0


def test_game_running_detection_handles_tasklist_no_match(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            returncode=1,
            stdout="INFO: No tasks are running which match the specified criteria.\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert ingest.le_mans_ultimate_is_running() is False


def test_game_running_detection_handles_tasklist_match(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            returncode=0,
            stdout='"Le Mans Ultimate.exe","1234","Console","1","10,000 K"\n',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert ingest.le_mans_ultimate_is_running() is True


def test_game_running_detection_blocks_on_unverifiable_state(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("tasklist unavailable")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert ingest.le_mans_ultimate_is_running() is True


def test_changed_imported_database_requires_review_instead_of_reprocessing(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"
    calls: list[Path] = []
    runner = lambda path, args: calls.append(path)

    ingest.scan(
        telemetry,
        state_path,
        settle_seconds=0,
        now=NOW,
        runner=runner,
        probe=lambda path: None,
    )
    database.write_bytes(b"duckdb-test-changed")
    ingest.scan(
        telemetry,
        state_path,
        settle_seconds=0,
        now=NOW + timedelta(minutes=5),
        runner=runner,
        probe=lambda path: None,
    )

    assert calls == [database]
    assert read_state(state_path)["files"][str(database)]["status"] == (
        ingest.STATUS_CHANGED_REVIEW_REQUIRED
    )


def test_debrief_next_processes_only_oldest_history_ready_session(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    first = make_db(telemetry, "first.duckdb")
    second = make_db(telemetry, "second.duckdb")
    state_path = tmp_path / "state.json"
    calls: list[tuple[Path, list[str]]] = []

    state = ingest.empty_state()
    state["files"] = {
        str(second): {
            "status": ingest.STATUS_HISTORY_READY,
            "history_ready_at": "2026-08-17T12:02:00Z",
        },
        str(first): {
            "status": ingest.STATUS_HISTORY_READY,
            "history_ready_at": "2026-08-17T12:01:00Z",
        },
    }
    ingest.save_state(state_path, state)

    result = ingest.debrief_next(
        state_path,
        backend="deepseek",
        now=NOW,
        runner=lambda path, args: calls.append((path, args)),
    )

    assert result == 0
    assert calls == [(first, ["--backend", "deepseek"])]
    updated = read_state(state_path)["files"]
    assert updated[str(first)]["status"] == ingest.STATUS_DEBRIEF_READY
    assert updated[str(second)]["status"] == ingest.STATUS_HISTORY_READY


def test_failed_debrief_keeps_history_ready_for_later_retry(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"
    state = ingest.empty_state()
    state["files"][str(database)] = {
        "status": ingest.STATUS_HISTORY_READY,
        "history_ready_at": "2026-08-17T12:00:00Z",
    }
    ingest.save_state(state_path, state)

    def fail(path: Path, args: list[str]) -> None:
        raise RuntimeError("API unavailable")

    assert ingest.debrief_next(
        state_path,
        backend="deepseek",
        now=NOW,
        runner=fail,
    ) == 1
    entry = read_state(state_path)["files"][str(database)]
    assert entry["status"] == ingest.STATUS_HISTORY_READY
    assert "API unavailable" in entry["last_debrief_error"]


def test_debrief_latest_selects_newest_and_does_not_drain_older_sessions(
    tmp_path: Path,
):
    telemetry = tmp_path / "telemetria"
    older = make_db(telemetry, "older.duckdb")
    newest = make_db(telemetry, "newest.duckdb")
    state_path = tmp_path / "state.json"
    calls: list[tuple[Path, list[str]]] = []
    state = ingest.empty_state()
    state["files"] = {
        str(older): {
            "status": ingest.STATUS_HISTORY_READY,
            "signature": {"size": 7 * 1024 * 1024, "mtime_ns": 100},
        },
        str(newest): {
            "status": ingest.STATUS_HISTORY_READY,
            "signature": {"size": 8 * 1024 * 1024, "mtime_ns": 200},
        },
    }
    ingest.save_state(state_path, state)

    assert ingest.debrief_latest(
        state_path,
        backend="deepseek",
        min_size_mb=5,
        min_valid_laps=2,
        now=NOW,
        runner=lambda path, args: calls.append((path, args)),
        lap_counter=lambda path: 3,
    ) == 0

    assert calls == [(newest, ["--backend", "deepseek"])]
    updated = read_state(state_path)["files"]
    assert updated[str(newest)]["status"] == ingest.STATUS_DEBRIEF_READY
    assert updated[str(older)]["status"] == ingest.STATUS_HISTORY_ONLY_SUPERSEDED
    assert updated[str(older)]["superseded_by"] == str(newest)

    assert ingest.debrief_latest(
        state_path,
        backend="deepseek",
        min_size_mb=5,
        min_valid_laps=2,
        now=NOW + timedelta(minutes=5),
        runner=lambda path, args: calls.append((path, args)),
        lap_counter=lambda path: 3,
    ) == 0
    assert calls == [(newest, ["--backend", "deepseek"])]


def test_debrief_latest_requires_size_and_deterministic_valid_laps(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    small = make_db(telemetry, "small.duckdb")
    one_lap = make_db(telemetry, "one-lap.duckdb")
    valid = make_db(telemetry, "valid.duckdb")
    state_path = tmp_path / "state.json"
    calls: list[Path] = []
    state = ingest.empty_state()
    state["files"] = {
        str(small): {
            "status": ingest.STATUS_HISTORY_READY,
            "signature": {"size": 4 * 1024 * 1024, "mtime_ns": 300},
        },
        str(one_lap): {
            "status": ingest.STATUS_HISTORY_READY,
            "signature": {"size": 8 * 1024 * 1024, "mtime_ns": 200},
        },
        str(valid): {
            "status": ingest.STATUS_HISTORY_READY,
            "signature": {"size": 8 * 1024 * 1024, "mtime_ns": 100},
        },
    }
    ingest.save_state(state_path, state)

    lap_counts = {small: 4, one_lap: 1, valid: 2}
    assert ingest.debrief_latest(
        state_path,
        backend="ollama",
        min_size_mb=5,
        min_valid_laps=2,
        now=NOW,
        runner=lambda path, args: calls.append(path),
        lap_counter=lambda path: lap_counts[path],
    ) == 0

    assert calls == [valid]
    updated = read_state(state_path)["files"]
    assert updated[str(small)]["status"] == ingest.STATUS_HISTORY_ONLY_INELIGIBLE
    assert updated[str(one_lap)]["status"] == ingest.STATUS_HISTORY_ONLY_INELIGIBLE
    assert updated[str(valid)]["status"] == ingest.STATUS_DEBRIEF_READY


def test_backfill_insufficient_valid_laps_is_skipped_not_failed(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"
    state = ingest.empty_state()
    state["files"][str(database)] = {
        "status": ingest.STATUS_BASELINED,
        "signature": ingest.signature(database),
    }
    ingest.save_state(state_path, state)

    def fail(path: Path, args: list[str]) -> None:
        raise RuntimeError("VALIDATION_FAILED")

    assert ingest.backfill_next(
        state_path,
        min_size_mb=0,
        now=NOW,
        runner=fail,
        probe=lambda path: None,
        pipeline_status_reader=lambda path: None,
        analysis_reader=lambda path: {
            "comparisons": [],
            "metadata": {"valid_laps": [1]},
        },
    ) == 0
    entry = read_state(state_path)["files"][str(database)]
    assert entry["status"] == (
        ingest.STATUS_BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS
    )
    assert "insuficientes" in entry["last_error"]


def test_scan_skips_backfill_skipped_insufficient_valid_laps(tmp_path: Path):
    telemetry = tmp_path / "telemetria"
    database = make_db(telemetry)
    state_path = tmp_path / "state.json"
    state = ingest.empty_state()
    state["files"][str(database)] = {
        "status": ingest.STATUS_BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS,
        "signature": ingest.signature(database),
    }
    ingest.save_state(state_path, state)
    calls: list[Path] = []

    assert ingest.scan(
        telemetry,
        state_path,
        settle_seconds=0,
        now=NOW,
        runner=lambda path, args: calls.append(path),
        probe=lambda path: None,
    ) == 0
    assert calls == []
