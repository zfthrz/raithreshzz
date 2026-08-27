"""Read-only session catalogue used by the Race Engineer desktop interface."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from session_change_tracking import (
    CHANGE_NEW,
    CHANGE_REPEATED,
    CHANGE_RESOLVED,
    MATCH_BASIS_PHYSICAL,
    MATCH_BASIS_QUALITATIVE,
    MATCH_BASIS_REFERENCE_PROFILE,
    MATCH_BASIS_STEERING,
    STATUS_AVAILABLE,
    analysis_context,
    build_session_change_tracking,
)


PROJECT_ROOT = Path(__file__).resolve().parent
UI_MODEL_VERSION = "0.5"
READY_STAGE_STATUSES = {"RUN", "REUSED"}
FAILED_STAGE_STATUSES = {"FAILED"}
SESSION_FILTERS = {"ALL", "DEBRIEF_READY", "HISTORY_READY", "FAILED"}


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
    reference_selection_path: Path | None
    cross_session_path: Path | None
    historical_llm_path: Path | None
    database_path: Path | None
    stages: tuple[tuple[str, str], ...]

    @property
    def has_validated_debrief(self) -> bool:
        return (
            self.debrief_path is not None
            and dict(self.stages).get("llm_validator") in READY_STAGE_STATUSES
        )


@dataclass(frozen=True)
class SessionDetail:
    record: SessionRecord
    debrief_markdown: str
    plan_text: str
    laps_text: str
    pipeline_text: str
    historical_reference_text: str
    historical_comparison_text: str
    warnings: tuple[str, ...]
    historical_comparison_view: dict = field(default_factory=dict)
    session_change_view: dict = field(default_factory=dict)
    plan_items: tuple[dict[str, Any], ...] = ()
    focus_plan_labels: tuple[str, ...] = ()


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


def _calibration_artifact_paths(
    status_path: Path,
    payload: dict[str, Any],
    steps: dict[str, Any],
) -> tuple[Path, Path]:
    review_queue = _dict(steps.get("review_queue"))
    human = _dict(steps.get("human_labels"))

    batch_dir_value = payload.get("batch_dir")
    batch_dir = (
        Path(batch_dir_value)
        if isinstance(batch_dir_value, str) and batch_dir_value.strip()
        else status_path.parent
    )
    if not batch_dir.is_absolute():
        batch_dir = (status_path.parent / batch_dir).resolve()

    queue_value = review_queue.get("path")
    queue_path = (
        Path(queue_value)
        if isinstance(queue_value, str) and queue_value.strip()
        else batch_dir / "pair_review_queue.json"
    )
    if not queue_path.is_absolute():
        queue_path = (batch_dir / queue_path).resolve()

    labels_value = human.get("labels_path")
    labels_path = (
        Path(labels_value)
        if isinstance(labels_value, str) and labels_value.strip()
        else batch_dir / "pair_labels.json"
    )
    if not labels_path.is_absolute():
        labels_path = (batch_dir / labels_path).resolve()

    return queue_path, labels_path


def _live_calibration_label_counts(
    status_path: Path,
    payload: dict[str, Any],
    steps: dict[str, Any],
    covered_pair_ids: set[str] | None = None,
) -> tuple[int | None, int | None]:
    queue_path, labels_path = _calibration_artifact_paths(status_path, payload, steps)
    queue_pairs = None
    labeled_pairs = None
    queue_ids: set[str] = set()

    try:
        queue_payload = _json(queue_path)
        queue = queue_payload.get("queue")
        if isinstance(queue, list):
            queue_pairs = len(queue)
            queue_ids = {
                item.get("pair_id")
                for item in queue
                if isinstance(item, dict)
                and isinstance(item.get("pair_id"), str)
                and item.get("pair_id")
            }
    except Exception:
        pass

    try:
        labels_payload = _json(labels_path)
        labels = labels_payload.get("labels")
        if isinstance(labels, list):
            seen = set()
            count = 0
            for item in labels:
                if not isinstance(item, dict):
                    continue
                pair_id = item.get("pair_id")
                human_label = item.get("human_label")
                if (
                    isinstance(pair_id, str)
                    and pair_id
                    and pair_id not in seen
                    and human_label in {"SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"}
                ):
                    seen.add(pair_id)
                    count += 1
            labeled_pairs = count
    except Exception:
        pass

    if covered_pair_ids is not None and queue_pairs is not None:
        labeled_pairs = len(queue_ids & covered_pair_ids)

    return queue_pairs, labeled_pairs


def load_calibration_summary(
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Resumen determinista del estado de calibración H2 por contexto.

    Lee los BATCH_STATUS.json de calibration_batches/ (runtime trackeado) y el
    status del matcher por contexto ya resuelto por el orquestador. Es
    presentación read-only: no consulta DuckDB ni modifica nada.
    """
    batches_root = base_dir or (PROJECT_ROOT / "calibration_batches")
    rows: list[dict[str, Any]] = []
    if batches_root.is_dir():
        statuses: list[tuple[Path, dict[str, Any]]] = []
        coverage: dict[tuple[str, str, str], set[str]] = {}
        for status_path in sorted(batches_root.glob("*/BATCH_STATUS.json")):
            try:
                payload = _json(status_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            statuses.append((status_path, payload))
            steps = _dict(payload.get("steps"))
            _queue_path, labels_path = _calibration_artifact_paths(
                status_path, payload, steps
            )
            try:
                labels = _json(labels_path).get("labels")
            except Exception:
                continue
            if not isinstance(labels, list):
                continue
            key = (
                str(payload.get("track") or "—"),
                str(payload.get("track_layout") or "—"),
                str(payload.get("vehicle_variant") or "—"),
            )
            covered = coverage.setdefault(key, set())
            for item in labels:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("pair_id"), str)
                    and item.get("human_label") in {"SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"}
                ):
                    covered.add(item["pair_id"])

        for status_path, payload in statuses:
            steps = _dict(payload.get("steps"))
            context_sel = _dict(steps.get("vehicle_context_selection"))
            human = _dict(steps.get("human_labels"))
            context_key = (
                str(payload.get("track") or "—"),
                str(payload.get("track_layout") or "—"),
                str(payload.get("vehicle_variant") or "—"),
            )
            live_queue_pairs, live_labeled_pairs = _live_calibration_label_counts(
                status_path,
                payload,
                steps,
                coverage.get(context_key, set()),
            )
            eval_step = _dict(steps.get("evaluation_readiness"))
            dataset = _dict(steps.get("calibration_dataset"))
            matcher = _dict(payload.get("matcher"))
            matcher_status = str(matcher.get("status") or "NO_MATCHER_STATUS")
            legacy_refreshed = False
            # El registro del matcher es la fuente de verdad del status por
            # contexto; el campo del BATCH_STATUS es un snapshot (puede ser
            # legacy BLOCKED_BY_REAL_DATA o anterior al registro).
            try:
                from episode_pair_matcher import CALIBRATIONS
            except Exception:
                CALIBRATIONS = {}
            registry_status = CALIBRATIONS.get(
                (
                    str(payload.get("track") or ""),
                    str(payload.get("track_layout") or ""),
                    str(payload.get("vehicle_variant") or ""),
                )
            )
            if registry_status is not None:
                matcher_status = str(registry_status.get("status") or matcher_status)
                legacy_refreshed = True
            rows.append(
                {
                    "track": str(payload.get("track") or "—"),
                    "track_layout": str(payload.get("track_layout") or "—"),
                    "vehicle_variant": str(payload.get("vehicle_variant") or "—"),
                    "sessions": _integer(context_sel.get("session_count")) or 0,
                    "labeled_pairs": (
                        live_labeled_pairs
                        if live_labeled_pairs is not None
                        else (_integer(human.get("labeled_pairs")) or 0)
                    ),
                    "queue_pairs": (
                        live_queue_pairs
                        if live_queue_pairs is not None
                        else (_integer(human.get("queue_pairs")) or 0)
                    ),
                    "evaluation_status": str(
                        eval_step.get("status") or "NO_EVALUATION"
                    ),
                    "evaluation_pairs": _integer(eval_step.get("evaluation_pairs"))
                    or 0,
                    "dataset_ready": dataset.get("calibration_ready") is True,
                    "matcher_status": matcher_status,
                    "legacy_status_refreshed": legacy_refreshed,
                    "batch_id": str(
                        payload.get("batch_id") or status_path.parent.name
                    ),
                }
            )
    # Por contexto, conservar primero una revisión humana pendiente; a igualdad
    # de estado, gana el batch con más sesiones (el que supersede).
    by_context: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["track"], row["track_layout"], row["vehicle_variant"])
        current = by_context.get(key)
        row_pending = row["queue_pairs"] > row["labeled_pairs"]
        current_pending = (
            current is not None
            and current["queue_pairs"] > current["labeled_pairs"]
        )
        if current is None or (
            row_pending,
            row["sessions"],
            row["batch_id"],
        ) > (
            current_pending,
            current["sessions"],
            current["batch_id"],
        ):
            by_context[key] = row
    rows = sorted(
        by_context.values(),
        key=lambda row: (row["track"], row["vehicle_variant"]),
    )
    calibrated = sum(
        1 for row in rows if "CALIBRATED" in row["matcher_status"]
    )
    ready_datasets = sum(1 for row in rows if row["dataset_ready"])
    return {
        "rows": rows,
        "calibrated_contexts": calibrated,
        "ready_datasets": ready_datasets,
    }


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
        return "HISTORY_READY", "Guardada en History; debrief automático pendiente"
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
    reference_selection_stage = _dict(stages_payload.get("h4"))
    cross_session_stage = _dict(stages_payload.get("h5_2"))
    historical_llm_stage = _dict(stages_payload.get("h5_2_llm"))

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
        reference_selection_path=_existing_path(reference_selection_stage.get("output")),
        cross_session_path=_existing_path(cross_session_stage.get("output")),
        historical_llm_path=_existing_path(historical_llm_stage.get("output")),
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


def filter_sessions(
    sessions: list[SessionRecord],
    *,
    query: str = "",
    status_filter: str = "ALL",
) -> list[SessionRecord]:
    if status_filter not in SESSION_FILTERS:
        raise ValueError(f"Filtro de sesión no soportado: {status_filter}")
    terms = [term.casefold() for term in query.split() if term.strip()]
    result = []
    for session in sessions:
        if status_filter != "ALL" and session.status != status_filter:
            continue
        haystack = " ".join(
            (
                session.session_key,
                session.timestamp_utc,
                format_timestamp(session.timestamp_utc, session.modified_timestamp),
                session.track,
                session.session_type,
                session.vehicle,
                session.status,
                session.status_detail,
            )
        ).casefold()
        if all(term in haystack for term in terms):
            result.append(session)
    return result


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
    focus = _dict(facts.get("next_stint_focus"))
    focus_items = (
        _list(focus.get("items"))
        if focus.get("status") == "ACTIVE"
        else []
    )
    plan_labels = {
        str(_dict(item).get("plan_label"))
        for item in items
        if _dict(item).get("plan_label") is not None
    }
    focus_labels = [
        str(_dict(item).get("plan_label"))
        for item in focus_items
        if _dict(item).get("plan_label") is not None
    ]
    focus_is_consistent = (
        1 <= len(focus_items) <= 2
        and _integer(focus.get("focus_count")) == len(focus_items)
        and len(focus_labels) == len(focus_items)
        and len(set(focus_labels)) == len(focus_labels)
        and set(focus_labels).issubset(plan_labels)
    )
    if focus_is_consistent:
        focus_text = _plan_items_text(focus_items[:2])
        complete_text = _plan_items_text(items[:3])
        return (
            "FOCO DEL PILOTO\n"
            "Trabajá primero estas dos zonas:\n\n"
            f"{focus_text}\n\n"
            "PLAN COMPLETO VALIDADO\n\n"
            f"{complete_text}"
        )
    return _plan_items_text(items[:3])


def _plan_items_text(items: list[Any]) -> str:
    sections = []
    for index, value in enumerate(items, start=1):
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


def _laps_text(analysis: dict[str, Any]) -> str:
    metadata = _dict(analysis.get("metadata"))
    reference_lap = _integer(metadata.get("reference_lap"))
    valid_laps = {_integer(value) for value in _list(metadata.get("valid_laps"))}
    discarded_laps = {_integer(value) for value in _list(metadata.get("discarded_laps"))}
    ignored_laps = {_integer(value) for value in _list(metadata.get("ignored_initial_laps"))}
    lap_times = _dict(metadata.get("lap_times_s"))
    reference_time = _number(lap_times.get(str(reference_lap)))
    rows = []
    for value in _list(analysis.get("laps")):
        lap = _dict(value)
        number = _integer(lap.get("lap"))
        if number is None:
            continue
        duration = _number(lap.get("duration"))
        if duration is None:
            duration = _number(lap_times.get(str(number)))
        flags = []
        if number == reference_lap:
            flags.append("REFERENCIA")
        if number in valid_laps:
            flags.append("válida")
        if number in discarded_laps:
            flags.append("descartada/incompleta")
        if number in ignored_laps:
            flags.append("inicial ignorada")
        delta = ""
        if (
            number in valid_laps
            and number != reference_lap
            and duration is not None
            and reference_time is not None
        ):
            delta = f" · {duration - reference_time:+.3f} s vs referencia"
        rows.append(
            (
                number,
                f"Vuelta {number}: {format_lap_time(duration)}{delta}"
                f" · {', '.join(flags) or 'sin clasificación'}",
            )
        )
    if not rows:
        return "No hay tiempos de vuelta disponibles en el análisis determinista."
    rows.sort(key=lambda item: item[0])
    return "\n".join(text for _, text in rows)


def _pipeline_text(record: SessionRecord) -> str:
    lines = [
        f"Estado general: {record.status_detail}",
        f"State: {record.state_path}",
        f"Telemetría: {record.database_path or '—'}",
        f"Análisis: {record.analysis_path or '—'}",
        f"Debrief: {record.debrief_path or '—'}",
        f"Histórico H5.3: {record.historical_path or '—'}",
        f"Selección H4: {record.reference_selection_path or '—'}",
        f"Comparación H5.2: {record.cross_session_path or '—'}",
        f"Lectura H5.2 LLM: {record.historical_llm_path or '—'}",
        "",
        "Etapas:",
    ]
    lines.extend(f"  {name:<18} {status}" for name, status in record.stages)
    return "\n".join(lines)


def _historical_reference_text(path: Path | None) -> str:
    if path is None:
        return "Esta sesión todavía no tiene una selección H4 disponible."
    payload = _json(path)
    status = str(payload.get("selection_status") or "UNKNOWN")
    target = _dict(payload.get("target_session"))
    target_reference = _dict(target.get("session_reference"))
    summary = _dict(payload.get("candidate_summary"))
    selected = _dict(payload.get("selected_historical_reference"))
    lines = [
        f"Estado H4: {status}",
        "",
        f"Referencia de la sesión: vuelta {target_reference.get('lap', '—')} / "
        f"{format_lap_time(_number(target_reference.get('duration_s')))}",
        f"Contexto: {target.get('track', '—')} / {target.get('track_layout', '—')}",
        f"Vehículo: {target.get('vehicle_variant', '—')} / {target.get('car_name_raw', '—')}",
        f"Candidatas consideradas: {summary.get('candidate_sessions_considered', 0)} · "
        f"elegibles: {summary.get('eligible', 0)} · rechazadas: {summary.get('rejected', 0)}",
    ]
    if selected:
        delta = _number(selected.get("historical_minus_session_reference_s"))
        delta_text = f"{delta:+.3f} s" if delta is not None else "—"
        lines.extend(
            (
                "",
                "Referencia histórica seleccionada:",
                f"  History #{selected.get('session_id', '—')} · vuelta {selected.get('lap', '—')}",
                f"  Tiempo: {format_lap_time(_number(selected.get('duration_s')))}",
                f"  Histórico - sesión: {delta_text}",
                f"  Fecha: {selected.get('timestamp_utc', '—')}",
            )
        )
    else:
        lines.extend(("", "No existe una referencia histórica compatible bajo los gates H4."))
    lines.extend(("", "Autoridad: observacional; no reemplaza la referencia de la sesión."))
    return "\n".join(lines)


def _historical_comparison_text(
    raw: dict[str, Any],
    historical_llm: dict[str, Any],
    *,
    stage_status: str,
) -> str:
    if not raw:
        return (
            "Esta sesión no tiene una comparación histórica H5.2 disponible.\n\n"
            f"Estado de la etapa H5.2: {stage_status}.\n"
            "Consultá Referencia histórica para ver si H4 encontró una vuelta compatible."
        )

    status = str(raw.get("status") or "UNKNOWN")
    context = _dict(raw.get("context"))
    historical = _dict(raw.get("historical_reference"))
    current = _dict(raw.get("current_session_reference"))
    temporal = _dict(raw.get("temporal_validation"))
    spatial = _dict(raw.get("spatial_comparison"))
    localization = _dict(spatial.get("localization"))
    delta = _number(temporal.get("calculated_current_minus_historical_s"))
    if delta is None:
        current_time = _number(current.get("duration_s"))
        historical_time = _number(historical.get("duration_s"))
        if current_time is not None and historical_time is not None:
            delta = current_time - historical_time
    delta_text = f"{delta:+.3f} s" if delta is not None else "—"
    lines = [
        f"Estado H5.2: {status}",
        f"Contexto: {context.get('track', '—')} / {context.get('vehicle_variant', '—')}",
        "",
        "Vueltas comparadas:",
        f"  Histórica: History #{historical.get('session_id', '—')} · "
        f"vuelta {historical.get('lap', '—')} · "
        f"{format_lap_time(_number(historical.get('duration_s')))}",
        f"  Sesión actual: History #{current.get('session_id', '—')} · "
        f"vuelta {current.get('lap', '—')} · "
        f"{format_lap_time(_number(current.get('duration_s')))}",
        f"  Actual - histórica: {delta_text}",
        "",
        f"Localización: {localization.get('mode', 'sin perfil')} · "
        f"{localization.get('profile_status', '—')}",
    ]

    rendered = str(historical_llm.get("rendered_analysis") or "").strip()
    if rendered:
        metadata = _dict(historical_llm.get("metadata"))
        lines.extend(
            (
                "",
                "Lectura histórica validada:",
                f"  Backend/modelo: {metadata.get('backend', '—')} / "
                f"{metadata.get('model', '—')}",
                "",
                rendered,
            )
        )
    else:
        zones = [_dict(value) for value in _list(spatial.get("zone_summaries"))]
        zones.sort(key=lambda item: _number(item.get("start_distance")) or 0.0)
        lines.extend(("", f"Zonas deterministas ({len(zones)}), en orden de pista:"))
        for zone in zones:
            location = _dict(zone.get("location"))
            start = _number(zone.get("start_distance"))
            end = _number(zone.get("end_distance"))
            change = _number(zone.get("delta_change"))
            distance_text = (
                f"{start:.0f}-{end:.0f} m"
                if start is not None and end is not None
                else "distancia no disponible"
            )
            change_text = f"{change:+.3f} s" if change is not None else "—"
            lines.append(
                f"  • {location.get('label') or distance_text}: "
                f"{zone.get('type', 'observación')} · cambio {change_text}"
            )

    lines.extend(
        (
            "",
            "Autoridad: comparación observacional. No autoriza acciones y no reemplaza "
            "la referencia de la sesión.",
        )
    )
    return "\n".join(lines)


def _historical_comparison_structured(
    raw: dict[str, Any],
    historical_llm: dict[str, Any],
    *,
    stage_status: str,
) -> dict[str, Any]:
    if not raw:
        return {
            "available": False,
            "stage_status": stage_status,
            "historical": None,
            "current": None,
            "delta_s": None,
            "delta_text": "—",
            "localization": {},
            "zones": [],
            "llm": {"rendered": "", "backend": "—", "model": "—"},
        }

    context = _dict(raw.get("context"))
    historical = _dict(raw.get("historical_reference"))
    current = _dict(raw.get("current_session_reference"))
    temporal = _dict(raw.get("temporal_validation"))
    spatial = _dict(raw.get("spatial_comparison"))
    localization = _dict(spatial.get("localization"))
    delta = _number(temporal.get("calculated_current_minus_historical_s"))
    if delta is None:
        current_time = _number(current.get("duration_s"))
        historical_time = _number(historical.get("duration_s"))
        if current_time is not None and historical_time is not None:
            delta = current_time - historical_time
    delta_text = f"{delta:+.3f} s" if delta is not None else "—"

    zones = [
        {
            "label": str(_dict(zone.get("location")).get("label") or "Zona sin nombre"),
            "type": str(zone.get("type") or "observación"),
            "delta_change_s": _number(zone.get("delta_change")),
            "start_distance_m": _number(zone.get("start_distance")),
            "end_distance_m": _number(zone.get("end_distance")),
        }
        for zone in _list(spatial.get("zone_summaries"))
        if isinstance(zone, dict)
    ]
    zones.sort(
        key=lambda item: abs(item["delta_change_s"])
        if item["delta_change_s"] is not None
        else 0.0,
        reverse=True,
    )
    zones = zones[:3]

    llm_rendered = str(historical_llm.get("rendered_analysis") or "").strip()
    llm_metadata = _dict(historical_llm.get("metadata"))
    return {
        "available": True,
        "stage_status": stage_status,
        "status": str(raw.get("status") or "UNKNOWN"),
        "context": {
            "track": context.get("track"),
            "vehicle_variant": context.get("vehicle_variant"),
        },
        "historical": {
            "session_id": historical.get("session_id"),
            "lap": historical.get("lap"),
            "duration_s": _number(historical.get("duration_s")),
            "duration_text": format_lap_time(_number(historical.get("duration_s"))),
        },
        "current": {
            "session_id": current.get("session_id"),
            "lap": current.get("lap"),
            "duration_s": _number(current.get("duration_s")),
            "duration_text": format_lap_time(_number(current.get("duration_s"))),
        },
        "delta_s": delta,
        "delta_text": delta_text,
        "localization": {
            "mode": localization.get("mode"),
            "profile_status": localization.get("profile_status"),
        },
        "zones": zones,
        "llm": {
            "rendered": llm_rendered,
            "backend": llm_metadata.get("backend"),
            "model": llm_metadata.get("model"),
        },
    }


_PHYSICAL_CHANGE_LABELS = {
    ("braking_point", "later"): "frenada más tarde",
    ("braking_point", "earlier"): "frenada más temprano",
    ("brake_release", "later"): "liberación de freno más tarde",
    ("brake_release", "earlier"): "liberación de freno más temprano",
    ("throttle_onset", "later"): "reaplicación de acelerador más tarde",
    ("throttle_onset", "earlier"): "reaplicación de acelerador más temprano",
    ("throttle_release", "later"): "levantada de acelerador más tarde",
    ("throttle_release", "earlier"): "levantada de acelerador más temprano",
}

_CHANNEL_LABELS = {
    "brake": "freno",
    "throttle": "acelerador",
    "steering_magnitude": "volante",
}


def _change_presentation_label(change: dict[str, Any]) -> str:
    action = _dict(change.get("action"))
    basis = change.get("match_basis")
    status = change.get("status")

    if basis == MATCH_BASIS_PHYSICAL:
        identity = (action.get("family"), action.get("coaching_direction"))
        return _PHYSICAL_CHANGE_LABELS.get(identity, "acción física observada")

    channel = _CHANNEL_LABELS.get(
        str(action.get("channel") or ""),
        "freno/acelerador",
    )
    if basis == MATCH_BASIS_REFERENCE_PROFILE:
        labels = {
            CHANGE_REPEATED: f"patrón de {channel} repetido",
            CHANGE_NEW: f"nuevo patrón de {channel}",
            CHANGE_RESOLVED: f"patrón de {channel} ya no observado",
        }
        return labels.get(status, f"patrón de {channel}")
    if basis == MATCH_BASIS_QUALITATIVE:
        labels = {
            CHANGE_REPEATED: f"acción cualitativa de {channel} repetida",
            CHANGE_NEW: f"nueva acción cualitativa de {channel}",
            CHANGE_RESOLVED: f"acción cualitativa de {channel} ya no observada",
        }
        return labels.get(status, f"acción cualitativa de {channel}")
    if basis == MATCH_BASIS_STEERING:
        labels = {
            CHANGE_REPEATED: "acción de volante repetida",
            CHANGE_NEW: "nueva acción de volante",
            CHANGE_RESOLVED: "acción de volante ya no observada",
        }
        return labels.get(status, "acción de volante")
    return "cambio observacional"


def _change_location(change: dict[str, Any]) -> tuple[tuple[Any, ...], str]:
    item = _dict(change.get("current_item")) or _dict(change.get("previous_item"))
    track_location = _dict(item.get("track_location"))
    start = _number(item.get("start_distance_m"))
    end = _number(item.get("end_distance_m"))
    if start is None or end is None:
        start = _number(track_location.get("start_m"))
        end = _number(track_location.get("end_m"))
    if start is not None and end is not None and end < start:
        start, end = end, start

    label = str(track_location.get("label") or "").strip()
    if not label and start is not None and end is not None:
        label = f"{start:.0f}–{end:.0f} m"
    if not label:
        label = "Ubicación sin etiqueta"
    return (start, end), label


def _change_presentation_order(change: dict[str, Any]) -> tuple[int, str, str]:
    basis = change.get("match_basis")
    status = change.get("status")
    if basis == MATCH_BASIS_PHYSICAL:
        rank = {
            CHANGE_REPEATED: 0,
            CHANGE_NEW: 1,
            CHANGE_RESOLVED: 2,
        }.get(status, 2)
    else:
        rank = 3 if status == CHANGE_REPEATED else 4
    identity = ":".join(
        str(change.get(field) or "")
        for field in (
            "action_family",
            "channel",
            "coaching_direction",
            "presentation_label",
        )
    )
    return rank, str(basis or ""), identity


def build_session_change_view(
    record: SessionRecord,
    sessions: list[SessionRecord],
) -> dict[str, Any]:
    result = build_session_change_tracking(record, sessions)
    view = {
        "status": result.get("status"),
        "reason": result.get("reason"),
        "previous_session_key": result.get("previous_session_key"),
        "previous_timestamp_utc": None,
        "previous_timestamp_label": None,
        "title": "Cambios vs. última sesión comparable",
        "change_counts": dict(_dict(result.get("change_counts"))),
        "grouped_changes": [],
        "observational_only": bool(result.get("observational_only", True)),
        "affects_next_stint_plan": bool(
            result.get("affects_next_stint_plan", False)
        ),
        "historical_actions_authorized": bool(
            result.get("historical_actions_authorized", False)
        ),
    }
    if result.get("status") != STATUS_AVAILABLE:
        return view

    previous = next(
        (
            candidate
            for candidate in sessions
            if candidate.session_key == result.get("previous_session_key")
        ),
        None,
    )
    if previous is not None and previous.analysis_path is not None:
        try:
            context = analysis_context(previous.analysis_path)
            timestamp_utc = context.get("timestamp_utc")
            view["previous_timestamp_utc"] = timestamp_utc
            view["previous_timestamp_label"] = format_timestamp(
                str(timestamp_utc or ""),
                previous.modified_timestamp,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            pass
    if view["previous_timestamp_label"]:
        view["title"] += f" — {view['previous_timestamp_label']}"

    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw_change in _list(result.get("changes")):
        if not isinstance(raw_change, dict):
            continue
        location_key, location_label = _change_location(raw_change)
        group = groups.setdefault(
            location_key,
            {
                "location_label": location_label,
                "start_distance_m": location_key[0],
                "end_distance_m": location_key[1],
                "changes": [],
            },
        )
        action = _dict(raw_change.get("action"))
        group["changes"].append({
            "status": raw_change.get("status"),
            "match_basis": raw_change.get("match_basis"),
            "action_family": action.get("family"),
            "coaching_direction": (
                action.get("coaching_direction")
                or action.get("steering_direction")
            ),
            "channel": action.get("channel"),
            "presentation_label": _change_presentation_label(raw_change),
        })

    grouped_changes = list(groups.values())
    for group in grouped_changes:
        group["changes"].sort(key=_change_presentation_order)
    view["grouped_changes"] = grouped_changes
    return view


def unavailable_session_change_view(
    reason: str = "session_catalog_not_provided",
) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "reason": reason,
        "previous_session_key": None,
        "previous_timestamp_utc": None,
        "previous_timestamp_label": None,
        "title": "Cambios vs. última sesión comparable",
        "change_counts": {},
        "grouped_changes": [],
        "observational_only": True,
        "affects_next_stint_plan": False,
        "historical_actions_authorized": False,
    }


def load_session_detail(
    record: SessionRecord,
    sessions: list[SessionRecord] | None = None,
) -> SessionDetail:
    warnings = []
    debrief = "Esta sesión todavía no tiene un debrief LLM validado."
    plan = "No hay un plan de próxima tanda disponible."
    plan_items: tuple[dict[str, Any], ...] = ()
    focus_plan_labels: tuple[str, ...] = ()
    laps = "No hay tiempos de vuelta disponibles en el análisis determinista."
    historical_reference = "Esta sesión todavía no tiene una selección H4 disponible."
    historical_comparison_raw: dict[str, Any] = {}
    historical_comparison_llm: dict[str, Any] = {}
    if record.debrief_path:
        try:
            payload = _json(record.debrief_path)
            debrief = str(payload.get("global_analysis") or debrief)
            coaching_facts = _dict(payload.get("session_coaching_facts"))
            plan = _plan_text(coaching_facts)

            raw_plan_items = [
                _dict(item)
                for item in _list(coaching_facts.get("next_stint_plan"))
                if isinstance(item, dict)
            ]
            plan_items = tuple(raw_plan_items[:3])

            focus = _dict(coaching_facts.get("next_stint_focus"))
            if focus.get("status") == "ACTIVE":
                focus_plan_labels = tuple(
                    str(_dict(item).get("plan_label"))
                    for item in _list(focus.get("items"))
                    if _dict(item).get("plan_label") is not None
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"No se pudo leer el debrief: {exc}")
    if record.analysis_path:
        laps = _laps_text(_json(record.analysis_path))
    try:
        historical_reference = _historical_reference_text(record.reference_selection_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        warnings.append(f"No se pudo leer la selección H4: {exc}")
    if record.cross_session_path:
        try:
            historical_comparison_raw = _json(record.cross_session_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"No se pudo leer la comparación H5.2: {exc}")
    if record.historical_llm_path:
        try:
            historical_comparison_llm = _json(record.historical_llm_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"No se pudo leer la lectura H5.2 LLM: {exc}")
    stage_status = dict(record.stages).get("h5_2", "NO_EJECUTADA")
    historical_comparison = _historical_comparison_text(
        historical_comparison_raw,
        historical_comparison_llm,
        stage_status=stage_status,
    )
    historical_comparison_view = _historical_comparison_structured(
        historical_comparison_raw,
        historical_comparison_llm,
        stage_status=stage_status,
    )
    session_change_view = (
        build_session_change_view(record, sessions)
        if sessions is not None
        else unavailable_session_change_view()
    )
    return SessionDetail(
        record=record,
        debrief_markdown=debrief,
        plan_text=plan,
        laps_text=laps,
        pipeline_text=_pipeline_text(record),
        historical_reference_text=historical_reference,
        historical_comparison_text=historical_comparison,
        historical_comparison_view=historical_comparison_view,
        session_change_view=session_change_view,
        warnings=tuple(warnings),
    )
