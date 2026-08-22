from __future__ import annotations

import io
from pathlib import Path

import pytest

from race_engineer_ui_analysis import (
    build_analysis_plan,
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
        backend="llamacpp",
        project_root=root,
        python_executable=tmp_path / "python.exe",
    )

    assert plan.command == (
        str((tmp_path / "python.exe").resolve()),
        "-u",
        str((root / "analyze_telemetry_file.py").resolve()),
        str(database.resolve()),
        "--backend",
        "llamacpp",
    )
    assert "race_engineer.py" not in plan.command


def test_plan_rejects_unknown_backend(tmp_path: Path):
    with pytest.raises(ValueError, match="Backend no soportado"):
        build_analysis_plan(
            tmp_path / "file.duckdb",
            backend="unsafe",
            project_root=project(tmp_path),
        )


def test_pythonw_is_replaced_by_console_sibling_when_available(tmp_path: Path):
    pythonw = tmp_path / "pythonw.exe"
    python = tmp_path / "python.exe"
    pythonw.write_bytes(b"")
    python.write_bytes(b"")

    assert console_python_executable(pythonw) == python.resolve()


def test_stream_analysis_forwards_output_and_returns_exit_code(tmp_path: Path):
    plan = build_analysis_plan(
        tmp_path / "Fuji.duckdb",
        backend="deepseek",
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
