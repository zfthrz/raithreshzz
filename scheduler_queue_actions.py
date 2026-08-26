"""Explicit, reversible manual actions for the deterministic debrief queue."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from auto_ingest_telemetry import (
    STATUS_DEBRIEF_DEFERRED,
    STATUS_HISTORY_READY,
    isoformat,
    load_state,
    save_state,
)


def _ensure_scheduler_idle(runtime_path: Path | None) -> None:
    if runtime_path is None or not Path(runtime_path).is_file():
        return
    try:
        runtime = json.loads(Path(runtime_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"No se pudo verificar el estado runtime: {exc}") from exc
    if isinstance(runtime, dict) and runtime.get("status") == "RUNNING":
        raise ValueError("El scheduler está ejecutándose; esperá a que termine el ciclo.")


def _state_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def defer_blocking_debrief(
    state_path: Path,
    database_path: str,
    *,
    now: datetime | None = None,
    runtime_path: Path | None = None,
) -> None:
    _ensure_scheduler_idle(runtime_path)
    before = _state_signature(Path(state_path))
    state = load_state(Path(state_path))
    entry = state["files"].get(database_path)
    if not isinstance(entry, dict):
        raise ValueError("La sesión ya no existe en el estado del scheduler.")
    if entry.get("status") != STATUS_HISTORY_READY:
        raise ValueError("La sesión ya no está pendiente de debrief.")
    if int(entry.get("debrief_attempts", 0)) < 3 or not isinstance(
        entry.get("last_debrief_error"), str
    ):
        raise ValueError("La sesión no cumple el contrato de bloqueo confirmado.")
    stamp = isoformat(now or datetime.now(timezone.utc))
    entry["status"] = STATUS_DEBRIEF_DEFERRED
    entry["debrief_deferred_at"] = stamp
    entry["debrief_deferred_reason"] = "manual_queue_release_after_repeated_failure"
    entry["updated_at"] = stamp
    if _state_signature(Path(state_path)) != before:
        raise ValueError("El estado cambió durante la acción; volvé a intentarlo.")
    save_state(Path(state_path), state)


def resume_deferred_debrief(
    state_path: Path,
    database_path: str,
    *,
    now: datetime | None = None,
    runtime_path: Path | None = None,
) -> None:
    _ensure_scheduler_idle(runtime_path)
    before = _state_signature(Path(state_path))
    state = load_state(Path(state_path))
    entry = state["files"].get(database_path)
    if not isinstance(entry, dict):
        raise ValueError("La sesión ya no existe en el estado del scheduler.")
    if entry.get("status") != STATUS_DEBRIEF_DEFERRED:
        raise ValueError("La sesión no está pospuesta.")
    stamp = isoformat(now or datetime.now(timezone.utc))
    entry["status"] = STATUS_HISTORY_READY
    entry["history_ready_at"] = stamp
    entry["updated_at"] = stamp
    entry["debrief_attempts"] = 0
    entry.pop("debrief_deferred_at", None)
    entry.pop("debrief_deferred_reason", None)
    if _state_signature(Path(state_path)) != before:
        raise ValueError("El estado cambió durante la acción; volvé a intentarlo.")
    save_state(Path(state_path), state)
