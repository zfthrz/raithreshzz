from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import hidden_history_ingest as hidden


def test_console_python_executable_replaces_pythonw_when_sibling_exists(
    tmp_path: Path,
):
    pythonw = tmp_path / "pythonw.exe"
    python = tmp_path / "python.exe"
    pythonw.write_bytes(b"")
    python.write_bytes(b"")

    assert hidden.console_python_executable(pythonw) == python.resolve()


def test_build_maintenance_command_preserves_history_first_contract(tmp_path: Path):
    python = tmp_path / "python.exe"
    telemetry = tmp_path / "Telemetry"
    command = hidden.build_maintenance_command(
        python_executable=python,
        telemetry_dir=telemetry,
    )

    assert command == [
        str(python.resolve()),
        str(hidden.PROJECT_ROOT / "auto_ingest_telemetry.py"),
        "--telemetry-dir",
        str(telemetry),
        "maintenance",
        "--min-size-mb",
        "5",
        "--backfill-minutes",
        "30",
    ]


def test_build_h5_3_review_command_uses_hidden_runner_python(tmp_path: Path):
    python = tmp_path / "python.exe"
    assert hidden.build_h5_3_review_command(python_executable=python) == [
        str(python.resolve()),
        str(hidden.PROJECT_ROOT / "maintain_h5_3_action_review.py"),
    ]


def test_hidden_maintenance_runs_nonblocking_review_maintenance_after_success(
    tmp_path: Path,
):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 9)

    result = hidden.run_hidden_maintenance(
        log_path=tmp_path / "task.log",
        command=["python.exe", "history.py"],
        review_command=["python.exe", "review.py"],
        runner=runner,
        runtime_path=tmp_path / "runtime.json",
    )
    assert result == 0
    assert calls == [
        ["python.exe", "history.py"],
        ["python.exe", "review.py"],
    ]
    assert "H5.3 REVIEW WARNING" in (tmp_path / "task.log").read_text(encoding="utf-8")


def test_rotate_log_keeps_one_previous_copy(tmp_path: Path):
    log = tmp_path / "task.log"
    backup = tmp_path / "task.log.1"
    backup.write_text("older", encoding="utf-8")
    log.write_text("current-long-log", encoding="utf-8")

    hidden.rotate_log(log, max_bytes=4)

    assert not log.exists()
    assert backup.read_text(encoding="utf-8") == "current-long-log"


def test_run_hidden_maintenance_redirects_output_and_returns_child_code(
    tmp_path: Path,
):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write("child output\n")
        return SimpleNamespace(returncode=7)

    log = tmp_path / "task.log"
    result = hidden.run_hidden_maintenance(
        log_path=log,
        command=["python.exe", "worker.py"],
        runner=runner,
        runtime_path=tmp_path / "runtime.json",
    )

    assert result == 7
    assert calls[0][0] == ["python.exe", "worker.py"]
    assert calls[0][1]["stderr"] is subprocess.STDOUT
    assert calls[0][1]["check"] is False
    text = log.read_text(encoding="utf-8")
    assert "START hidden History maintenance" in text
    assert "child output" in text
    assert "END exit_code=7" in text
    runtime = (tmp_path / "runtime.json").read_text(encoding="utf-8")
    assert '"status": "FAILED"' in runtime
    assert '"exit_code": 7' in runtime


def test_run_hidden_maintenance_logs_unexpected_exception(tmp_path: Path):
    def runner(command, **kwargs):
        raise RuntimeError("boom")

    log = tmp_path / "task.log"
    result = hidden.run_hidden_maintenance(
        log_path=log,
        command=["python.exe", "worker.py"],
        runner=runner,
        runtime_path=tmp_path / "runtime.json",
    )

    assert result == 1
    text = log.read_text(encoding="utf-8")
    assert "RuntimeError: boom" in text
    assert "END exit_code=1" in text
    assert '"status": "FAILED"' in (
        tmp_path / "runtime.json"
    ).read_text(encoding="utf-8")


def test_runtime_state_preserves_last_success_across_failed_cycle(tmp_path: Path):
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps({
        "status": "PASS",
        "last_successful_at": "2026-08-25T18:00:00+00:00",
    }), encoding="utf-8")

    result = hidden.run_hidden_maintenance(
        log_path=tmp_path / "task.log",
        runtime_path=runtime_path,
        command=["python.exe", "worker.py"],
        runner=lambda command, **kwargs: SimpleNamespace(returncode=4),
    )

    assert result == 4
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert runtime["status"] == "FAILED"
    assert runtime["last_successful_at"] == "2026-08-25T18:00:00+00:00"
