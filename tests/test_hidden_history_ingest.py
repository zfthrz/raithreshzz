from __future__ import annotations

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
    )

    assert result == 7
    assert calls[0][0] == ["python.exe", "worker.py"]
    assert calls[0][1]["stderr"] is subprocess.STDOUT
    assert calls[0][1]["check"] is False
    text = log.read_text(encoding="utf-8")
    assert "START hidden History maintenance" in text
    assert "child output" in text
    assert "END exit_code=7" in text


def test_run_hidden_maintenance_logs_unexpected_exception(tmp_path: Path):
    def runner(command, **kwargs):
        raise RuntimeError("boom")

    log = tmp_path / "task.log"
    result = hidden.run_hidden_maintenance(
        log_path=log,
        command=["python.exe", "worker.py"],
        runner=runner,
    )

    assert result == 1
    text = log.read_text(encoding="utf-8")
    assert "RuntimeError: boom" in text
    assert "END exit_code=1" in text
