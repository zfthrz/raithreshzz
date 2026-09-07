"""Per-user data paths for the packaged public application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIRECTORY = "RaceEngineer"


def public_data_root(environ: dict[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    explicit = values.get("RACE_ENGINEER_PUBLIC_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    local_app_data = values.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable; public user data cannot be isolated")
    return (Path(local_app_data) / APP_DIRECTORY).resolve()


def configure_public_runtime(environ: dict[str, str] | None = None) -> Path:
    """Point generated and persistent state at a fresh per-user application root."""
    values = os.environ if environ is None else environ
    root = public_data_root(values)
    values["RACE_ENGINEER_GENERATED_DIR"] = str(root / "generated")
    values["RACE_ENGINEER_LOCAL_DIR"] = str(root / "local")
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        values["RACE_ENGINEER_ANALYZER_EXECUTABLE"] = str(
            executable_dir / "RaceEngineerAnalyze.exe"
        )
        values["RACE_ENGINEER_CLI_EXECUTABLE"] = str(
            executable_dir / "RaceEngineerCLI.exe"
        )
    return root
