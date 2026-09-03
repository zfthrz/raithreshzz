"""Unified read-only operational status for the H3 automation chain."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


H3_AUTOMATION_STATUS_VERSION = "0.1"


def _read_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _identity(row: dict[str, Any]) -> tuple[str, str, str] | None:
    identity = (
        row.get("track"),
        row.get("track_layout"),
        row.get("vehicle_variant"),
    )
    return (
        identity
        if all(isinstance(value, str) and value for value in identity)
        else None
    )


def build_h3_automation_status(
    *,
    import_state_path: Path,
    materialization_state_path: Path,
    import_execution: str,
    materialization_execution: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Merge both read-only audits without granting mutation authority."""

    import_state = _read_document(import_state_path)
    materialization_state = _read_document(materialization_state_path)
    import_rows = {
        identity: row
        for row in import_state.get("contexts", [])
        if isinstance(row, dict) and (identity := _identity(row)) is not None
    }
    materialization_rows = {
        identity: row
        for row in materialization_state.get("contexts", [])
        if isinstance(row, dict) and (identity := _identity(row)) is not None
    }
    current = import_execution == "PASS" and materialization_execution == "PASS"
    contexts = []
    for identity in sorted(set(import_rows) | set(materialization_rows)):
        import_status = import_rows.get(identity, {}).get("status")
        materialization_status = materialization_rows.get(identity, {}).get("status")
        if not current:
            next_action = "REFRESH_AUDITS"
        elif import_status == "H3_READY_TO_IMPORT":
            next_action = "IMPORT_EXPLICIT"
        elif materialization_status == "MATERIALIZATION_READY":
            next_action = "MATERIALIZE_EXPLICIT"
        else:
            next_action = "NONE"
        contexts.append(
            {
                "track": identity[0],
                "track_layout": identity[1],
                "vehicle_variant": identity[2],
                "import_status": import_status,
                "materialization_status": materialization_status,
                "next_action": next_action,
            }
        )
    return {
        "version": H3_AUTOMATION_STATUS_VERSION,
        "mode": "STATUS_READ_ONLY",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "freshness": "CURRENT" if current else "STALE",
        "stages": {
            "import_readiness": import_execution,
            "materialization_readiness": materialization_execution,
        },
        "source_fingerprints": {
            "import_readiness": import_state.get("input_fingerprint"),
            "materialization_readiness": materialization_state.get("input_fingerprint"),
        },
        "context_count": len(contexts),
        "contexts": contexts,
        "history_mutated": False,
        "files_written": 0,
        "historical_actions_authorized": False,
    }


def write_h3_automation_status(path: Path, document: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
