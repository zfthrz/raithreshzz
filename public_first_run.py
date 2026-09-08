"""Persistent, per-user choices for the public application's first run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from runtime_paths import local_root


PREFERENCES_FILENAME = "public_preferences.json"


@dataclass(frozen=True)
class PublicPreferences:
    onboarding_complete: bool = False
    telemetry_directory: Path | None = None


def preferences_path() -> Path:
    return local_root() / PREFERENCES_FILENAME


def load_public_preferences(path: Path | None = None) -> PublicPreferences:
    source = path or preferences_path()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return PublicPreferences()
    if not isinstance(payload, dict):
        return PublicPreferences()
    raw_directory = payload.get("telemetry_directory")
    directory = None
    if isinstance(raw_directory, str) and raw_directory.strip():
        candidate = Path(raw_directory).expanduser()
        if candidate.is_absolute():
            directory = candidate
    return PublicPreferences(
        onboarding_complete=payload.get("onboarding_complete") is True,
        telemetry_directory=directory,
    )


def save_public_preferences(
    preferences: PublicPreferences,
    path: Path | None = None,
) -> None:
    destination = path or preferences_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "onboarding_complete": preferences.onboarding_complete,
        "telemetry_directory": (
            str(preferences.telemetry_directory)
            if preferences.telemetry_directory is not None
            else None
        ),
    }
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def telemetry_picker_directory(
    preferences: PublicPreferences,
    *,
    standard_lmu_directory: Path,
    fallback_directory: Path,
) -> Path:
    candidates = (
        preferences.telemetry_directory,
        standard_lmu_directory,
        fallback_directory,
    )
    return next(
        (path for path in candidates if path is not None and path.is_dir()),
        fallback_directory,
    )
