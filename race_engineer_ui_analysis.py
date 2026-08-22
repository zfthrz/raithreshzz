"""Safe subprocess plan for launching Race Engineer analysis from the GUI."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


UI_ANALYSIS_VERSION = "0.2"
SUPPORTED_BACKENDS = ("deepseek", "llamacpp", "ollama")
ALLOWED_ENVIRONMENT_OVERRIDES = {
    "DEEPSEEK_MODEL",
    "LLAMACPP_MODEL",
    "LLAMACPP_API_URL",
}


@dataclass(frozen=True)
class AnalysisLaunchPlan:
    database_path: Path
    backend: str
    project_root: Path
    python_executable: Path
    command: tuple[str, ...]
    environment_overrides: tuple[tuple[str, str], ...]
    skip_stability_wait: bool


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
    environment_overrides: Mapping[str, str] | None = None,
    skip_stability_wait: bool = False,
) -> AnalysisLaunchPlan:
    root = Path(project_root).resolve()
    launcher = root / "analyze_telemetry_file.py"
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"Backend no soportado: {backend}")
    if not launcher.is_file():
        raise FileNotFoundError(launcher)
    database = Path(database_path).expanduser().resolve()
    python = console_python_executable(python_executable)
    command_parts = [
        str(python),
        "-u",
        str(launcher),
        str(database),
        "--backend",
        backend,
    ]
    if skip_stability_wait:
        command_parts.append("--skip-stability-wait")
    command = tuple(command_parts)
    overrides = tuple(sorted((environment_overrides or {}).items()))
    unknown = {name for name, _ in overrides} - ALLOWED_ENVIRONMENT_OVERRIDES
    if unknown:
        raise ValueError("Variables de entorno GUI no autorizadas: " + ", ".join(sorted(unknown)))
    return AnalysisLaunchPlan(
        database_path=database,
        backend=backend,
        project_root=root,
        python_executable=python,
        command=command,
        environment_overrides=overrides,
        skip_stability_wait=skip_stability_wait,
    )


def validate_analysis_candidate(database_path: Path) -> Path:
    """Validate only GUI usability; the safe launcher remains authoritative."""

    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if database.suffix.casefold() != ".duckdb":
        raise ValueError("La sesión no apunta a un archivo DuckDB.")
    return database


def classify_analysis_completion(
    return_code: int,
    *,
    validated_debrief_available: bool = False,
) -> str:
    """Classify completion without hiding a valid debrief saved before failure."""

    if return_code == 0:
        return "PASS"
    if return_code == 2:
        return "BLOCKED"
    if validated_debrief_available:
        return "RECOVERED_VALID_DEBRIEF"
    return "FAILED"


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
    environment.update(dict(plan.environment_overrides))
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
