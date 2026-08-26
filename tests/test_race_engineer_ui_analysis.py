from __future__ import annotations

import io
from pathlib import Path

import pytest

from race_engineer_ui_analysis import (
    build_analysis_plan,
    classify_analysis_completion,
    console_python_executable,
    stream_analysis,
    validate_analysis_candidate,
)


def project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "analyze_telemetry_file.py").write_text("# launcher", encoding="utf-8")
    return root


def test_plan_invokes_only_the_existing_safe_launcher(tmp_path: Path):
    root = project(tmp_path)
    database = tmp_path / "Telemetry" / "Fuji.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"duckdb")

    plan = build_analysis_plan(
        database,
        project_root=root,
        python_executable=tmp_path / "python.exe",
    )

    assert plan.command == (
        str((tmp_path / "python.exe").resolve()),
        "-u",
        str((root / "analyze_telemetry_file.py").resolve()),
        str(database.resolve()),
        "--deterministic-debrief",
    )
    assert "race_engineer.py" not in plan.command
    assert plan.skip_stability_wait is False


def test_plan_can_skip_only_the_stability_wait(tmp_path: Path):
    root = project(tmp_path)
    plan = build_analysis_plan(
        tmp_path / "file.duckdb",
        project_root=root,
        skip_stability_wait=True,
    )
    assert plan.command[-1] == "--skip-stability-wait"
    assert "--deterministic-debrief" in plan.command
    assert plan.skip_stability_wait is True


def test_pythonw_is_replaced_by_console_sibling_when_available(tmp_path: Path):
    pythonw = tmp_path / "pythonw.exe"
    python = tmp_path / "python.exe"
    pythonw.write_bytes(b"")
    python.write_bytes(b"")

    assert console_python_executable(pythonw) == python.resolve()


def test_stream_analysis_forwards_output_and_returns_exit_code(tmp_path: Path):
    plan = build_analysis_plan(
        tmp_path / "Fuji.duckdb",
        project_root=project(tmp_path),
        python_executable=tmp_path / "python.exe",
    )
    observed = {}

    class Process:
        stdout = io.StringIO("Etapa 1/2\nRESULT: PASS\n")

        def wait(self):
            return 0

    def factory(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return Process()

    lines = []
    result = stream_analysis(plan, lines.append, popen_factory=factory)

    assert result == 0
    assert lines == ["Etapa 1/2", "RESULT: PASS"]
    assert observed["command"] == list(plan.command)
    assert observed["kwargs"]["stderr"] is not None
    assert observed["kwargs"]["env"]["PYTHONUNBUFFERED"] == "1"
    assert observed["kwargs"]["env"]["PYTHONUTF8"] == "1"
    assert observed["kwargs"]["env"]["PYTHONIOENCODING"] == "utf-8"


def test_gui_candidate_requires_an_existing_duckdb(tmp_path: Path):
    database = tmp_path / "existing.duckdb"
    database.write_bytes(b"duckdb")

    assert validate_analysis_candidate(database) == database.resolve()
    with pytest.raises(FileNotFoundError):
        validate_analysis_candidate(tmp_path / "missing.duckdb")
    text = tmp_path / "not-telemetry.json"
    text.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="DuckDB"):
        validate_analysis_candidate(text)


def test_completion_preserves_a_valid_debrief_after_late_failure():
    assert classify_analysis_completion(0) == "PASS"
    assert classify_analysis_completion(2, validated_debrief_available=True) == "BLOCKED"
    assert (
        classify_analysis_completion(1, validated_debrief_available=True)
        == "RECOVERED_VALID_DEBRIEF"
    )
    assert classify_analysis_completion(1) == "FAILED"
