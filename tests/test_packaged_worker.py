from __future__ import annotations

import sys
from pathlib import Path

import pytest

import RaceEngineerWorker as worker
from race_engineer import packaged_worker_command


def test_packaged_command_routes_python_stage_to_closed_worker(tmp_path):
    executable = tmp_path / "RaceEngineerWorker.exe"
    command = packaged_worker_command(
        [sys.executable, str(tmp_path / "analyze_telemetry.py"), "session.duckdb"],
        env={"RACE_ENGINEER_WORKER_EXECUTABLE": str(executable)},
    )
    assert command == [str(executable), "analyze_telemetry", "session.duckdb"]


def test_packaged_command_preserves_source_mode():
    command = [sys.executable, "analyze_telemetry.py", "session.duckdb"]
    assert packaged_worker_command(command, env={}) == command


def test_worker_rejects_module_outside_public_allowlist(capsys):
    assert worker.main(["llm_analysis_deepseek", "input.json"]) == 2
    assert "unsupported packaged worker module" in capsys.readouterr().err


def test_worker_dispatches_allowed_module(monkeypatch):
    called = {}

    def fake_run_module(module, *, run_name, alter_sys):
        called.update(module=module, run_name=run_name, alter_sys=alter_sys)

    monkeypatch.setattr(worker.runpy, "run_module", fake_run_module)
    assert worker.main(["deterministic_debrief", "analysis.json"]) == 0
    assert called == {
        "module": "deterministic_debrief",
        "run_name": "__main__",
        "alter_sys": False,
    }
