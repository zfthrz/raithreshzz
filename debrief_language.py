"""Language of newly generated reports; never migrates existing artifacts."""

from __future__ import annotations

import json
from pathlib import Path

LANGUAGES = {"es": "Español", "en": "English"}
PREFERENCES_PATH = Path(__file__).resolve().parent / "data/local/debrief_preferences.json"


def require_language(value: str) -> str:
    if value not in LANGUAGES:
        raise ValueError(f"Unsupported debrief language: {value!r}")
    return value


def load_debrief_language(path: Path | None = None) -> str:
    try:
        data = json.loads((path or PREFERENCES_PATH).read_text(encoding="utf-8"))
        return require_language(data["language"])
    except (OSError, ValueError, TypeError, KeyError):
        return "es"


def save_debrief_language(language: str, path: Path | None = None) -> None:
    require_language(language)
    destination = path or PREFERENCES_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"language": language}) + "\n", encoding="utf-8")
    temporary.replace(destination)
