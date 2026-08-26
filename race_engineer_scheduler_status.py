"""Read-only GUI projection of automatic telemetry-ingest state."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SchedulerStatus:
    code: str
    text: str
    style: str
    detail: str
    history_ready: int = 0
    debrief_ready: int = 0
    failed: int = 0
    blocked_path: str | None = None
    deferred_paths: tuple[str, ...] = ()


DEFAULT_STALLED_SECONDS = 15 * 60
DEFAULT_STALE_SECONDS = 5 * 60


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, now: datetime) -> float | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now.astimezone(timezone.utc) - parsed).total_seconds())


def _files(document: dict[str, Any]) -> dict[str, Any]:
    files = document.get("files")
    if not isinstance(files, dict):
        raise ValueError("files must be an object")
    return files


def project_state(
    document: dict[str, Any],
    *,
    runtime: dict[str, Any] | None = None,
    now: datetime | None = None,
    stalled_seconds: int = DEFAULT_STALLED_SECONDS,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
) -> SchedulerStatus:
    now = now or datetime.now(timezone.utc)
    counts: Counter[str] = Counter()
    for key, value in _files(document).items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError("each files entry must be an object")
        status = value.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError("each files entry requires status")
        counts[status] += 1

    history_ready = counts["HISTORY_READY"]
    debrief_ready = counts["DEBRIEF_READY"]
    failed = counts["FAILED"] + counts["BACKFILL_FAILED"]
    pending = counts["PENDING_STABILITY"]
    deferred_paths = tuple(sorted(
        path
        for path, entry in _files(document).items()
        if entry.get("status") == "DEBRIEF_DEFERRED"
    ))
    last_scan = document.get("last_scan")
    last_scan_at = last_scan.get("at") if isinstance(last_scan, dict) else None
    detail = (
        f"History pendientes: {history_ready} · Debriefs listos: {debrief_ready} · "
        f"Esperando estabilidad: {pending} · Fallos aislados: {failed}"
        f" · Pospuestos manualmente: {len(deferred_paths)}"
        + (f" · Último scan: {last_scan_at}" if isinstance(last_scan_at, str) else "")
    )
    runtime = runtime or {}
    blocked = [
        (path, entry)
        for path, entry in _files(document).items()
        if entry.get("status") == "HISTORY_READY"
        and int(entry.get("debrief_attempts", 0)) >= 3
        and isinstance(entry.get("last_debrief_error"), str)
    ]
    blocked_path = (
        sorted(blocked, key=lambda item: item[0].casefold())[0][0]
        if blocked else None
    )
    runtime_status = runtime.get("status")
    runtime_started_at = runtime.get("started_at")
    runtime_age = _age_seconds(runtime_started_at, now)
    if runtime_status == "RUNNING" and runtime_age is not None:
        if runtime_age >= stalled_seconds:
            minutes = int(runtime_age // 60)
            return SchedulerStatus(
                code="SCHEDULER_STALLED",
                text=f"Scheduler · posible bloqueo ({minutes} min)",
                style="H53Error.TLabel",
                detail=(
                    f"La ejecución iniciada en {runtime_started_at} sigue marcada "
                    f"RUNNING desde hace {minutes} min. {detail}"
                ),
                history_ready=history_ready,
                debrief_ready=debrief_ready,
                failed=failed,
            )
        return SchedulerStatus(
            code="SCHEDULER_RUNNING",
            text=f"Scheduler · procesando · {history_ready} pendientes",
            style="H53Pending.TLabel",
            detail=f"Ejecución iniciada en {runtime_started_at}. {detail}",
            history_ready=history_ready,
            debrief_ready=debrief_ready,
            failed=failed,
            blocked_path=blocked_path,
            deferred_paths=deferred_paths,
        )

    if runtime_status == "FAILED":
        return SchedulerStatus(
            code="SCHEDULER_FAILED",
            text=f"Scheduler · último ciclo falló · {history_ready} pendientes",
            style="H53Error.TLabel",
            detail=(
                f"Último ciclo fallido: {runtime.get('finished_at') or runtime_started_at}; "
                f"exit_code={runtime.get('exit_code')}. {detail}"
            ),
            history_ready=history_ready,
            debrief_ready=debrief_ready,
            failed=failed,
            blocked_path=blocked_path,
            deferred_paths=deferred_paths,
        )

    if blocked:
        path, entry = sorted(blocked, key=lambda item: item[0].casefold())[0]
        return SchedulerStatus(
            code="QUEUE_BLOCKED",
            text=f"Scheduler · cola bloqueada · {history_ready} pendientes",
            style="H53Error.TLabel",
            detail=(
                f"{Path(path).name} falló {entry.get('debrief_attempts')} veces: "
                f"{entry.get('last_debrief_error')}. {detail}"
            ),
            history_ready=history_ready,
            debrief_ready=debrief_ready,
            failed=failed,
            blocked_path=path,
            deferred_paths=deferred_paths,
        )

    heartbeat_values = [
        (document.get("last_scan") or {}).get("at")
        if isinstance(document.get("last_scan"), dict) else None,
        (document.get("last_maintenance") or {}).get("at")
        if isinstance(document.get("last_maintenance"), dict) else None,
        runtime.get("finished_at"),
    ]
    ages = [age for value in heartbeat_values if (age := _age_seconds(value, now)) is not None]
    if ages and min(ages) >= stale_seconds:
        minutes = int(min(ages) // 60)
        return SchedulerStatus(
            code="SCHEDULER_STALE",
            text=f"Scheduler · sin actividad ({minutes} min)",
            style="H53Error.TLabel",
            detail=f"No se registra actividad reciente del scheduler. {detail}",
            history_ready=history_ready,
            debrief_ready=debrief_ready,
            failed=failed,
            deferred_paths=deferred_paths,
        )
    if history_ready:
        return SchedulerStatus(
            code="QUEUE_ACTIVE",
            text=f"Scheduler · {history_ready} pendientes · {debrief_ready} listos",
            style="H53Pending.TLabel",
            detail=detail,
            history_ready=history_ready,
            debrief_ready=debrief_ready,
            failed=failed,
            deferred_paths=deferred_paths,
        )
    return SchedulerStatus(
        code="QUEUE_IDLE",
        text=f"Scheduler · al día · {debrief_ready} listos",
        style="H53Ready.TLabel",
        detail=detail,
        history_ready=history_ready,
        debrief_ready=debrief_ready,
        failed=failed,
        deferred_paths=deferred_paths,
    )


def load_status(path: Path, runtime_path: Path | None = None) -> SchedulerStatus:
    path = Path(path)
    if not path.is_file():
        return SchedulerStatus(
            code="STATE_UNAVAILABLE",
            text="Scheduler · estado no disponible",
            style="H53Muted.TLabel",
            detail=f"No existe todavía: {path}",
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("JSON root must be an object")
        runtime = None
        if runtime_path is not None and Path(runtime_path).is_file():
            runtime = json.loads(Path(runtime_path).read_text(encoding="utf-8"))
            if not isinstance(runtime, dict):
                raise ValueError("scheduler runtime root must be an object")
        return project_state(document, runtime=runtime)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return SchedulerStatus(
            code="STATE_INVALID",
            text="Scheduler · estado inválido",
            style="H53Error.TLabel",
            detail=str(exc),
        )


def diagnostic_report(
    state_path: Path,
    runtime_path: Path | None = None,
    log_path: Path | None = None,
) -> str:
    """Build a copy-friendly, read-only scheduler diagnostic."""
    status = load_status(state_path, runtime_path)
    lines = [
        "RACE ENGINEER — SCHEDULER DIAGNOSTIC",
        "",
        f"Estado: {status.code}",
        f"Resumen: {status.text}",
        f"History pendientes: {status.history_ready}",
        f"Debriefs listos: {status.debrief_ready}",
        f"Fallos aislados: {status.failed}",
        "",
        status.detail,
    ]
    if status.blocked_path:
        lines.extend(["", f"Sesión bloqueante: {status.blocked_path}"])
    if status.deferred_paths:
        lines.extend([
            "",
            "Sesiones pospuestas:",
            *(f"  - {path}" for path in status.deferred_paths),
        ])
    runtime: dict[str, Any] = {}
    if runtime_path is not None and Path(runtime_path).is_file():
        try:
            loaded = json.loads(Path(runtime_path).read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                runtime = loaded
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    if runtime:
        lines.extend([
            "",
            "Ciclo del scheduler:",
            f"  estado: {runtime.get('status', 'UNKNOWN')}",
            f"  iniciado: {runtime.get('started_at', 'no disponible')}",
            f"  finalizado: {runtime.get('finished_at', 'no disponible')}",
            f"  último éxito: {runtime.get('last_successful_at', 'no disponible')}",
            f"  exit code: {runtime.get('exit_code', 'no disponible')}",
            f"  PID: {runtime.get('pid', 'no disponible')}",
        ])
    lines.extend([
        "",
        f"Estado ingest: {Path(state_path)}",
        f"Estado runtime: {Path(runtime_path) if runtime_path else 'no configurado'}",
        f"Log: {Path(log_path) if log_path else 'no configurado'}",
        "",
        "Diagnóstico read-only: no se modificó ni reordenó la cola.",
    ])
    return "\n".join(lines)
