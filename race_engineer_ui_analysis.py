"""Safe subprocess plan for launching Race Engineer analysis from the GUI."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


UI_ANALYSIS_VERSION = "0.1"
SUPPORTED_BACKENDS = ("deepseek", "llamacpp", "ollama")


@dataclass(frozen=True)
class AnalysisLaunchPlan:
    database_path: Path
    backend: str
    project_root: Path
    python_executable: Path
    command: tuple[str, ...]


def console_python_executable(executable: str | Path = sys.executable) -> Path:
    """Prefer python.exe when the GUI itself was launched through pythonw.exe."""

    path = Path(executable).resolve()
    if path.name.casefold() == "pythonw.exe":
        console = path.with_name("python.exe")
        if console.is_file():
            return console
    return path


def build_analysis_plan(
    database_path: Path,
    *,
    backend: str,
    project_root: Path,
    python_executable: str | Path = sys.executable,
) -> AnalysisLaunchPlan:
    root = Path(project_root).resolve()
    launcher = root / "analyze_telemetry_file.py"
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"Backend no soportado: {backend}")
    if not launcher.is_file():
        raise FileNotFoundError(launcher)
    database = Path(database_path).expanduser().resolve()
    python = console_python_executable(python_executable)
    command = (
        str(python),
        "-u",
        str(launcher),
        str(database),
        "--backend",
        backend,
    )
    return AnalysisLaunchPlan(
        database_path=database,
        backend=backend,
        project_root=root,
        python_executable=python,
        command=command,
    )


def validate_analysis_candidate(database_path: Path) -> Path:
    """Validate only GUI usability; the safe launcher remains authoritative."""

    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if database.suffix.casefold() != ".duckdb":
        raise ValueError("La sesión no apunta a un archivo DuckDB.")
    return database


def stream_analysis(
    plan: AnalysisLaunchPlan,
    on_line: Callable[[str], None],
    *,
    popen_factory=subprocess.Popen,
) -> int:
    """Run the existing safe launcher and stream merged UTF-8 output."""

    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    # Windows GUI launches do not necessarily inherit a UTF-8 console.  These
    # variables propagate through the safe launcher and every Python child it
    # creates, so deterministic renders containing arrows or accented text can
    # be printed without failing after the result has already been saved.
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    process = popen_factory(
        list(plan.command),
        cwd=plan.project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=environment,
    )
    if process.stdout is None:
        raise RuntimeError("No se pudo capturar la salida del launcher seguro.")
    for line in process.stdout:
        on_line(line.rstrip("\r\n"))
    return int(process.wait())
