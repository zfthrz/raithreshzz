"""Testable GUI adapter for explicit, exact H3 History import."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from race_engineer_h3_materialization_gui import stream_commands


@dataclass(frozen=True)
class H3ImportTarget:
    track: str
    track_layout: str
    vehicle_variant: str
    input_fingerprint: str


def resolve_import_target(state_path: Path, context_row: dict[str, Any]) -> H3ImportTarget | None:
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    if state.get("mode") != "AUDIT_READ_ONLY" or state.get("history_mutated") is not False:
        return None
    fingerprint = state.get("input_fingerprint")
    contexts = state.get("contexts")
    identity = (
        context_row.get("track"),
        context_row.get("track_layout"),
        context_row.get("vehicle_variant"),
    )
    if (
        not isinstance(fingerprint, str)
        or not fingerprint
        or not isinstance(contexts, list)
        or not all(isinstance(value, str) and value for value in identity)
    ):
        return None
    matches = [
        row for row in contexts
        if isinstance(row, dict)
        and row.get("track") == identity[0]
        and row.get("track_layout") == identity[1]
        and row.get("vehicle_variant") == identity[2]
        and row.get("status") == "H3_READY_TO_IMPORT"
    ]
    return H3ImportTarget(*identity, fingerprint) if len(matches) == 1 else None


def build_import_commands(
    target: H3ImportTarget,
    *,
    project_root: Path,
    python_executable: Path,
    materialization_state_path: Path,
    import_state_path: Path,
    result_path: Path,
) -> tuple[tuple[str, ...], ...]:
    root = Path(project_root).resolve()
    python = str(Path(python_executable).resolve())
    return (
        (
            python,
            str(root / "import_h3_context.py"),
            "--track", target.track,
            "--track-layout", target.track_layout,
            "--vehicle-variant", target.vehicle_variant,
            "--expected-input-fingerprint", target.input_fingerprint,
            "--apply",
            "--output", str(Path(result_path).resolve()),
        ),
        (
            python,
            str(root / "audit_h3_materialization_readiness.py"),
            "--output", str(Path(materialization_state_path).resolve()),
        ),
        (
            python,
            str(root / "maintain_h3_imports.py"),
            "--output", str(Path(import_state_path).resolve()),
        ),
    )
