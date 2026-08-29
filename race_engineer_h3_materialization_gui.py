"""Testable GUI adapter for explicit H3 context materialization."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


@dataclass(frozen=True)
class H3MaterializationTarget:
    track: str
    track_layout: str
    vehicle_variant: str
    input_fingerprint: str


def resolve_materialization_target(
    state_path: Path,
    context_row: dict[str, Any],
) -> H3MaterializationTarget | None:
    """Return one exact ready target from the scheduler's read-only snapshot."""

    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    if (
        state.get("mode") != "AUDIT_READ_ONLY"
        or state.get("history_mutated") is not False
        or state.get("files_written") != 0
    ):
        return None
    fingerprint = state.get("input_fingerprint")
    contexts = state.get("contexts")
    if not isinstance(fingerprint, str) or not fingerprint or not isinstance(contexts, list):
        return None
    identity = (
        context_row.get("track"),
        context_row.get("track_layout"),
        context_row.get("vehicle_variant"),
    )
    if not all(isinstance(value, str) and value for value in identity):
        return None
    matches = [
        row
        for row in contexts
        if isinstance(row, dict)
        and row.get("track") == identity[0]
        and row.get("track_layout") == identity[1]
        and row.get("vehicle_variant") == identity[2]
        and row.get("status") == "MATERIALIZATION_READY"
    ]
    if len(matches) != 1:
        return None
    return H3MaterializationTarget(*identity, fingerprint)


def build_materialization_commands(
    target: H3MaterializationTarget,
    *,
    project_root: Path,
    python_executable: Path,
    materialization_state_path: Path,
    import_state_path: Path,
    result_path: Path,
) -> tuple[tuple[str, ...], ...]:
    project_root = Path(project_root).resolve()
    python = str(Path(python_executable).resolve())
    return (
        (
            python,
            str(project_root / "materialize_h3_context.py"),
            "--track",
            target.track,
            "--track-layout",
            target.track_layout,
            "--vehicle-variant",
            target.vehicle_variant,
            "--expected-input-fingerprint",
            target.input_fingerprint,
            "--apply",
            "--output",
            str(Path(result_path).resolve()),
        ),
        (
            python,
            str(project_root / "audit_h3_materialization_readiness.py"),
            "--output",
            str(Path(materialization_state_path).resolve()),
        ),
        (
            python,
            str(project_root / "maintain_h3_imports.py"),
            "--output",
            str(Path(import_state_path).resolve()),
        ),
    )


def stream_commands(
    commands: Sequence[Sequence[str]],
    *,
    project_root: Path,
    on_line: Callable[[str], None],
    popen_factory=subprocess.Popen,
) -> int:
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    for command in commands:
        process = popen_factory(
            list(command),
            cwd=Path(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
        )
        if process.stdout is None:
            raise RuntimeError("No se pudo capturar la salida de materialización H3.")
        for line in process.stdout:
            on_line(line.rstrip("\r\n"))
        code = int(process.wait())
        if code != 0:
            return code
    return 0
