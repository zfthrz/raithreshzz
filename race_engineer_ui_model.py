"""Read-only session catalogue used by the Race Engineer desktop interface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


UI_MODEL_VERSION = "0.1"
READY_STAGE_STATUSES = {"RUN", "REUSED"}
FAILED_STAGE_STATUSES = {"FAILED"}


@dataclass(frozen=True)
class SessionRecord:
    session_key: str
    state_path: Path
    modified_timestamp: float
    timestamp_utc: str
    track: str
    session_type: str
    vehicle: str
    valid_lap_count: int
    reference_lap: int | None
    reference_time_s: float | None
    status: str
    status_detail: str
    analysis_path: Path | None
    debrief_path: Path | None
    historical_path: Path | None
    database_path: Path | None
    stages: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SessionDetail:
    record: SessionRecord
    debrief_markdown: str
    plan_text: str
    pipeline_text: str
    warnings: tuple[str, ...]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root is not an object")
    return payload


def _existing_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_file() else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_lap_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes}:{remainder:06.3f}"


def format_timestamp(value: str, fallback_timestamp: float) -> str:
    if value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed.astimezone().strftime("%d/%m/%Y %H:%M")
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_timestamp).strftime("%d/%m/%Y %H:%M")


def _stage_statuses(state: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    stages = _dict(state.get("stages"))
    summary = _dict(state.get("last_summary"))
    names = list(summary)
    names.extend(name for name in stages if name not in summary)
    return tuple(
        (
            name,
            str(summary.get(name) or _dict(stages.get(name)).get("status") or "UNKNOWN"),
        )
        for name in names
    )


def _overall_status(stages: tuple[tuple[str, str], ...]) -> tuple[str, str]:
    values = {name: status for name, status in stages}
    failed = [name for name, status in stages if status in FAILED_STAGE_STATUSES]
    if failed:
        return "FAILED", "Falló: " + ", ".join(failed)
    if values.get("llm_validator") in READY_STAGE_STATUSES:
        return "DEBRIEF_READY", "Debrief validado"
    if values.get("llm") in READY_STAGE_STATUSES:
        return "DEBRIEF_UNVALIDATED", "Debrief generado; validación no confirmada"
    if values.get("history") in READY_STAGE_STATUSES:
        return "HISTORY_READY", "Guardada en History; sin debrief LLM"
    if values.get("analyze") in READY_STAGE_STATUSES:
        return "ANALYZED", "Análisis determinista disponible"
    return "INCOMPLETE", "Ejecución incompleta"


def _vehicle_label(metadata: dict[str, Any]) -> str:
    identity = _dict(metadata.get("vehicle_identity"))
    return str(
        identity.get("car_name_raw")
        or identity.get("variant")
        or identity.get("family")
        or "Vehículo no informado"
    )


def load_session_record(state_path: Path) -> SessionRecord:
    state_path = Path(state_path).resolve()
    state = _json(state_path)
    stages_payload = _dict(state.get("stages"))
    analyze_stage = _dict(stages_payload.get("analyze"))
    llm_stage = _dict(stages_payload.get("llm"))
    historical_stage = _dict(stages_payload.get("h5_3"))

    analysis_path = _existing_path(analyze_stage.get("output"))
    analysis = _json(analysis_path) if analysis_path else {}
    metadata = _dict(analysis.get("metadata"))
    modified = state_path.stat().st_mtime
    stages = _stage_statuses(state)
    status, status_detail = _overall_status(stages)

    reference_lap = _integer(metadata.get("reference_lap"))
    lap_times = _dict(metadata.get("lap_times_s"))
    reference_time = _number(lap_times.get(str(reference_lap)))
    valid_laps = _list(metadata.get("valid_laps"))
    database = state.get("database")

    return SessionRecord(
        session_key=state_path.parent.name,
        state_path=state_path,
        modified_timestamp=modified,
        timestamp_utc=str(metadata.get("timestamp_utc") or ""),
        track=str(metadata.get("track") or state_path.parent.name.split("_P_", 1)[0]),
        session_type=str(metadata.get("session_type") or "—"),
        vehicle=_vehicle_label(metadata),
        valid_lap_count=len(valid_laps),
        reference_lap=reference_lap,
        reference_time_s=reference_time,
        status=status,
        status_detail=status_detail,
        analysis_path=analysis_path,
        debrief_path=_existing_path(llm_stage.get("output")),
        historical_path=_existing_path(historical_stage.get("output")),
        database_path=Path(database) if isinstance(database, str) and database else None,
        stages=stages,
    )


def discover_sessions(runs_root: Path) -> tuple[list[SessionRecord], list[str]]:
    root = Path(runs_root)
    if not root.is_dir():
        return [], [f"No existe el directorio de ejecuciones: {root.resolve()}"]

    sessions = []
    errors = []
    for state_path in root.rglob("state.json"):
        try:
            sessions.append(load_session_record(state_path))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{state_path}: {exc}")
    sessions.sort(key=lambda item: (-item.modified_timestamp, item.session_key.casefold()))
    return sessions, errors


def _cue_text(cue: Any) -> str:
    if isinstance(cue, str):
        return cue.strip()
    if isinstance(cue, dict):
        return str(cue.get("text") or cue.get("description") or "").strip()
    return ""


def _plan_text(facts: dict[str, Any]) -> str:
    items = _list(facts.get("next_stint_plan"))
    if not items:
        return "No hay un plan de próxima tanda disponible."
    sections = []
    for index, value in enumerate(items[:3], start=1):
        item = _dict(value)
        label = str(item.get("plan_label") or index)
        location = _dict(item.get("track_location"))
        title = str(location.get("label") or item.get("description") or "Zona sin nombre")
        cues = [text for text in (_cue_text(cue) for cue in _list(item.get("driver_cues"))) if text]
        lines = [f"{index}. Zona {label} — {title}"]
        lines.extend(f"   • {cue}" for cue in cues)
        if not cues:
            lines.append("   • Sin cue de conducción autorizado.")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _pipeline_text(record: SessionRecord) -> str:
    lines = [
        f"Estado general: {record.status_detail}",
        f"State: {record.state_path}",
        f"Telemetría: {record.database_path or '—'}",
        f"Análisis: {record.analysis_path or '—'}",
        f"Debrief: {record.debrief_path or '—'}",
        f"Histórico H5.3: {record.historical_path or '—'}",
        "",
        "Etapas:",
    ]
    lines.extend(f"  {name:<18} {status}" for name, status in record.stages)
    return "\n".join(lines)


def load_session_detail(record: SessionRecord) -> SessionDetail:
    warnings = []
    debrief = "Esta sesión todavía no tiene un debrief LLM validado."
    plan = "No hay un plan de próxima tanda disponible."
    if record.debrief_path:
        try:
            payload = _json(record.debrief_path)
            debrief = str(payload.get("global_analysis") or debrief)
            plan = _plan_text(_dict(payload.get("session_coaching_facts")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"No se pudo leer el debrief: {exc}")
    return SessionDetail(
        record=record,
        debrief_markdown=debrief,
        plan_text=plan,
        pipeline_text=_pipeline_text(record),
        warnings=tuple(warnings),
    )
