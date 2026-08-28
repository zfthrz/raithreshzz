#!/usr/bin/env python3
"""Race Engineer desktop session hub and read-only History browser."""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
from pathlib import Path

from race_engineer_history_gui import open_history_browser
from race_engineer_calibration_gui import (
    launch_calibration_labeling_powershell,
    resolve_calibration_labeling_target,
)
from runtime_paths import history_db_default_path
from race_engineer_h5_3_review_status import load_status as load_h5_3_review_status
from race_engineer_scheduler_status import (
    diagnostic_report as scheduler_diagnostic_report,
    load_status as load_scheduler_status,
)
from scheduler_queue_actions import defer_blocking_debrief, resume_deferred_debrief

from race_engineer_ui_model import (
    SessionDetail,
    SessionRecord,
    build_session_change_view,
    discover_sessions,
    filter_sessions,
    format_lap_time,
    format_timestamp,
    load_calibration_summary,
    load_session_detail,
)
from race_engineer_ui_analysis import (
    build_analysis_plan,
    classify_analysis_completion,
    stream_analysis,
    validate_analysis_candidate,
)
from track_readiness import build_track_readiness
from race_engineer_track_map import (
    TrackMapData,
    TrackMapLapOption,
    TrackMapPriority,
    TrackMapPoint,
    TrackMapTurn,
    TrackTelemetrySummary,
    TrackTelemetryChart,
    TrackMapZone,
    build_historical_telemetry_comparison,
    build_track_telemetry_chart,
    fit_track_points,
    focus_track_canvas_view,
    load_track_map,
    list_track_map_laps,
    load_track_profile,
    load_track_priorities,
    load_track_zones,
    nearest_fitted_point_index,
    pan_distance_window,
    pan_track_canvas_view,
    point_index_for_distance,
    profile_location_for_distance,
    profile_turns,
    priority_for_distance,
    summarize_track_interval,
    telemetry_chart_x_for_distance,
    telemetry_chart_distance_for_x,
    telemetry_speed_scale,
    telemetry_gear_scale,
    canvas_polyline_chunks,
    historical_telemetry_sample_at_distance,
    historical_telemetry_uncovered_ranges,
    transform_fitted_track_points,
    turn_for_number,
    zoom_distance_window,
    zoom_track_canvas_view,
    zone_for_distance,
    zone_point_ranges,
)


GUI_VERSION = "1.40"
DEFAULT_RUNS_ROOT = Path(__file__).resolve().parent / "data" / "generated" / "runs"
STATE_REFRESH_INTERVAL_MS = 5_000
PROJECT_ROOT = Path(__file__).resolve().parent
SESSION_FILTER_LABELS = {
    "Todas": "ALL",
    "Con debrief": "DEBRIEF_READY",
    "Sólo History": "HISTORY_READY",
    "Fallidas": "FAILED",
}
PRIMARY_SECTIONS = (
    "Resumen",
    "Telemetría",
    "Historial",
    "Circuitos",
    "Diagnóstico",
    "Calibración",
)
SECTION_VIEWS = {
    "Resumen": ("Debrief", "Próxima tanda", "Vueltas"),
    "Telemetría": ("Mapa y canales",),
    "Historial": ("Referencia", "Comparación"),
    "Circuitos": ("Readiness",),
    "Diagnóstico": ("Pipeline", "Ejecución"),
    "Calibración": ("Calibración",),
}
SECTION_DESCRIPTIONS = {
    "Resumen": "Debrief, plan de próxima tanda y vueltas clave de la sesión seleccionada.",
    "Telemetría": "Mapa del circuito y canales de telemetría de la sesión seleccionada.",
    "Historial": "Referencia histórica y comparación contextual validada.",
    "Circuitos": "Estado de track profiles, sesiones y calibración por circuito/contexto.",
    "Diagnóstico": "Estado del pipeline, ejecución y automatización.",
    "Calibración": "Cobertura y estado de calibración por contexto.",
}

READINESS_STATUS_COLORS = {
    "CURRENT_REQUIREMENTS_SATISFIED": "#00FFA6",
    "COVERED_BY_TRACK_MATCH_BASELINE": "#42d6c7",
    "TRACK_MATCH_BASELINE_SHADOW": "#f0c674",
    "WAITING_FOR_TRACK_BASELINE": "#7fb3e3",
    "CANDIDATE_CALIBRATED": "#f0c674",
    "NEEDS_EVALUATION": "#f0c674",
    "NEEDS_LABELS": "#f0c674",
    "NEEDS_CALIBRATION_QUEUE": "#7fb3e3",
    "NEEDS_SESSIONS": "#7fb3e3",
    "NEEDS_PROFILE": "#ff7b72",
    "MATCH_BASELINE_CONFLICT": "#ff7b72",
    "UNKNOWN": "#9aa5ad",
}

READINESS_STATUS_LABELS = {
    "CURRENT_REQUIREMENTS_SATISFIED": "Calibración exacta vigente",
    "COVERED_BY_TRACK_MATCH_BASELINE": "Cobertura MATCH-only promovida",
    "TRACK_MATCH_BASELINE_SHADOW": "Baseline MATCH en shadow",
    "WAITING_FOR_TRACK_BASELINE": "Esperando baseline de circuito",
    "NEEDS_PROFILE": "Necesita track profile",
    "NEEDS_SESSIONS": "Necesita sesiones",
    "NEEDS_CALIBRATION_QUEUE": "Necesita calibration queue",
    "NEEDS_LABELS": "Necesita labels",
    "NEEDS_EVALUATION": "Necesita evaluación",
    "CANDIDATE_CALIBRATED": "Candidato pendiente de revisión",
    "MATCH_BASELINE_CONFLICT": "Conflicto de baseline MATCH",
    "UNKNOWN": "Estado no resuelto",
}

READINESS_ACTION_LABELS = {
    "CREATE_OR_VALIDATE_TRACK_PROFILE": "Crear / validar track profile",
    "RECORD_MORE_SESSIONS": "Registrar más sesiones",
    "GENERATE_CALIBRATION_QUEUE": "Generar calibration queue",
    "LABEL_CALIBRATION_QUEUE": "Etiquetar calibration queue",
    "COLLECT_EVALUATION_EVIDENCE": "Recolectar evidencia de evaluación",
    "REVIEW_SHADOW_METRICS": "Revisar métricas shadow",
    "NONE_MATCH_ONLY": "Sin acción para MATCH; REJECT sigue específico",
    "COLLECT_MATCH_SHADOW_EVIDENCE": "Recolectar evidencia MATCH shadow",
    "REVIEW_MATCH_BASELINE_CONFLICT": "Revisar conflicto de baseline MATCH",
    "ESTABLISH_TRACK_BASELINE_FIRST": "Establecer primero el baseline del circuito",
    "NONE": "Sin acción pendiente",
    "UNKNOWN": "Revisión manual",
}

H3_IMPORT_STATUS_LABELS = {
    "H3_NOT_APPLICABLE": "No aplicable",
    "H3_READY_TO_IMPORT": "Listo para importar",
    "H3_IMPORTED": "Importado",
    "H3_CONFLICT": "Conflicto",
    "H3_FAILED": "Falló validación",
}

SESSION_CHANGE_STATUS_LABELS = {
    "REPEATED": "Se mantiene",
    "NEW": "Nuevo",
    "RESOLVED": "Ya no aparece",
}


def compact_session_change_rows(view, *, max_groups: int = 3, max_changes: int = 3):
    """Bound historical-change content for the Resumen inspector card."""
    rows = session_change_rows(view)
    compact = []
    hidden_changes = 0
    for group_index, group in enumerate(rows):
        changes = list(group.get("changes") or ())
        if group_index >= max_groups:
            hidden_changes += len(changes)
            continue
        shown = changes[:max_changes]
        hidden_changes += max(0, len(changes) - len(shown))
        compact.append(
            {
                "location_label": group.get("location_label"),
                "changes": shown,
            }
        )
    return compact, hidden_changes


def session_change_rows(view):
    if not isinstance(view, dict) or view.get("status") != "AVAILABLE":
        return []

    rows = []
    for group in view.get("grouped_changes") or []:
        if not isinstance(group, dict):
            continue
        changes = []
        for change in group.get("changes") or []:
            if not isinstance(change, dict):
                continue
            label = str(change.get("presentation_label") or "").strip()
            status_label = SESSION_CHANGE_STATUS_LABELS.get(change.get("status"))
            if not label or status_label is None:
                continue
            changes.append({
                "status_label": status_label,
                "presentation_label": label,
                "structured": change.get("match_basis") != "physical_action_atom",
            })
        if changes:
            rows.append({
                "location_label": str(
                    group.get("location_label") or "Ubicación sin etiqueta"
                ),
                "changes": changes,
            })
    return rows

CALIBRATION_STATUS_COLORS = {
    "CALIBRATED": "#00FFA6",
    "PROVISIONAL": "#f0c674",
    "NO_CALIBRATION": "#9aa5ad",
    "LEGACY": "#9aa5ad",
    "BLOCKED": "#ff7b72",
}
CALIBRATION_STATUS_TOOLTIPS = {
    "CALIBRATED": "Calibrado con labels humanos para este contexto.",
    "PROVISIONAL": (
        "Calibración provisional con labels humanos; requiere más datos "
        "independientes para evaluar."
    ),
    "NO_CALIBRATION": (
        "Sin thresholds calibrados para este contexto; labelar el batch "
        "para calibrar."
    ),
    "LEGACY": (
        "Batch de un orquestador anterior (status legacy); el matcher actual "
        "se resuelve por contexto."
    ),
    "BLOCKED": "Estado legacy o desconocido; revisá el batch de calibración.",
}
SESSION_STATUS_SUMMARY = {
    "DEBRIEF_READY": "Debrief listo",
    "DEBRIEF_UNVALIDATED": "Sin validar",
    "HISTORY_READY": "History listo",
    "ANALYZED": "Analizada",
    "FAILED": "Fallida",
    "INCOMPLETE": "Incompleta",
}


def _open_path(path: Path) -> None:
    target = path if path.is_dir() else path.parent
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    raise RuntimeError("Abrir carpetas desde la GUI sólo está soportado en Windows.")


def _open_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"El archivo todavía no existe: {path}")
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    raise RuntimeError("Abrir archivos desde la GUI sólo está soportado en Windows.")


def _clean_markdown_line(line: str) -> str:
    return line.replace("**", "").replace("_", "")


def compact_debrief_markdown(value: str) -> str:
    """Build a short dashboard view from existing debrief sections only."""
    lines = value.splitlines()
    if not lines:
        return ""

    wanted = ("resumen de la sesión", "foco principal")
    sections: list[list[str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("## ") and line[3:].strip().casefold() in wanted:
            block = [line]
            index += 1
            while index < len(lines) and not lines[index].startswith("## "):
                block.append(lines[index])
                index += 1
            sections.append(block)
            continue
        index += 1

    if not sections:
        # Drop the oversized document title in dashboard mode but preserve source text.
        trimmed = [line for line in lines if not line.startswith("# ")]
        return "\n".join(trimmed[:18]).strip()

    output: list[str] = []
    for block in sections:
        heading = block[0]
        output.extend((heading, ""))
        body = [line for line in block[1:] if line.strip()]
        if heading[3:].strip().casefold() == "foco principal":
            bullets = [line for line in body if line.lstrip().startswith("-")]
            body = bullets[:2] if bullets else body[:4]
        else:
            body = body[:4]
        output.extend(body)
        output.append("")
    return "\n".join(output).strip()


def compact_laps_text(value: str, *, max_rows: int = 4) -> str:
    """Keep the dashboard lap card scannable while preserving the full source elsewhere."""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) <= max_rows:
        return "\n".join(lines)
    reference = [line for line in lines if "REFERENCIA" in line.upper()]
    selected = lines[:max_rows]
    if reference and reference[0] not in selected:
        selected[-1] = reference[0]
    remaining = max(0, len(lines) - len(selected))
    if remaining:
        selected.append(f"+ {remaining} vueltas más en el detalle")
    return "\n".join(selected)


def status_wraplength(container_width_px: int) -> int:
    """Keep map status text inside its current panel without clipping it."""
    return max(240, int(container_width_px) - 24)


def telemetry_canvas_ready(width_px: int, height_px: int) -> bool:
    """Only render three telemetry lanes when the real canvas can contain them."""
    return int(width_px) >= 180 and int(height_px) >= 120


def state_files_fingerprint(runs_root: Path) -> tuple[tuple[str, int, int], ...]:
    """Return a cheap, stable snapshot of orchestrator state files."""
    root = Path(runs_root)
    if not root.is_dir():
        return ()
    items: list[tuple[str, int, int]] = []
    for path in root.rglob("state.json"):
        try:
            stat = path.stat()
            relative = path.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        items.append((relative, stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(items))


def calibration_files_fingerprint(
    batches_root: Path,
) -> tuple[tuple[str, int, int], ...]:
    root = Path(batches_root)
    if not root.is_dir():
        return ()
    items: list[tuple[str, int, int]] = []
    watched_paths = list(root.glob("*/BATCH_STATUS.json"))
    watched_paths.extend(root.glob("*/pair_labels.json"))
    for path in watched_paths:
        try:
            stat = path.stat()
            relative = path.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        items.append((relative, stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(items))


def file_fingerprint(path: Path) -> tuple[int, int] | None:
    """Return mtime/size for one optional local state file."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def session_summary_values(
    *,
    reference_time_s: float | None,
    valid_lap_count: int,
    has_historical_reference: bool,
    has_historical_comparison: bool,
    status: str,
) -> tuple[str, str, str, str]:
    historical = (
        "Comparación lista"
        if has_historical_comparison
        else "Referencia disponible"
        if has_historical_reference
        else "Sin compatible"
    )
    return (
        format_lap_time(reference_time_s),
        str(max(valid_lap_count, 0)),
        historical,
        SESSION_STATUS_SUMMARY.get(status, "Estado desconocido"),
    )


SESSION_STATUS_COLORS = {
    "DEBRIEF_READY": "#00FFA6",
    "DEBRIEF_UNVALIDATED": "#d2b36e",
    "HISTORY_READY": "#f0c674",
    "ANALYZED": "#7fb3e3",
    "PENDING_STABILITY": "#9aa5ad",
    "INCOMPLETE": "#9aa5ad",
    "CHANGED_REVIEW_REQUIRED": "#e6a3f0",
    "FAILED": "#ff7b72",
}

SESSION_STATUS_TOOLTIPS = {
    "DEBRIEF_READY": "Debrief validado y listo para revisar.",
    "DEBRIEF_UNVALIDATED": "Hay debrief, pero el validator no lo confirmó.",
    "HISTORY_READY": (
        "En History; el scheduler puede generar automáticamente el debrief "
        "determinista, o podés iniciarlo manualmente con Analizar."
    ),
    "ANALYZED": "Analizada y validada; falta importarla a History.",
    "PENDING_STABILITY": "Telemetría nueva; esperando estabilidad.",
    "INCOMPLETE": "Sesión incompleta o sin vueltas comparables.",
    "CHANGED_REVIEW_REQUIRED": (
        "El archivo cambió después de procesarse; requiere revisión."
    ),
    "FAILED": "Falló en alguna etapa; revisá Diagnóstico → Pipeline.",
}


def session_status_color(status: str) -> str:
    return SESSION_STATUS_COLORS.get(status, "#9aa5ad")


def session_status_tooltip(status: str) -> str:
    return SESSION_STATUS_TOOLTIPS.get(
        status,
        "Estado no clasificado; revisá Diagnóstico → Pipeline.",
    )


def calibration_status_tag(status: str) -> str:
    if "CALIBRATED_PROVISIONAL" in status:
        return "PROVISIONAL"
    if status.startswith("CALIBRATED"):
        return "CALIBRATED"
    if status == "NO_CALIBRATION_FOR_CONTEXT":
        return "NO_CALIBRATION"
    if status == "BLOCKED_BY_REAL_DATA":
        return "LEGACY"
    return "BLOCKED"


def calibration_status_color(status: str) -> str:
    return CALIBRATION_STATUS_COLORS[calibration_status_tag(status)]


def calibration_status_tooltip(status: str) -> str:
    return CALIBRATION_STATUS_TOOLTIPS[calibration_status_tag(status)]


def track_readiness_status_tooltip(row: dict) -> str:
    status = str(row.get("overall_status") or "UNKNOWN")
    descriptions = {
        "CURRENT_REQUIREMENTS_SATISFIED": (
            "Calibración exacta para esta variante. MATCH y REJECT conservan "
            "únicamente la autoridad definida por esa calibración."
        ),
        "COVERED_BY_TRACK_MATCH_BASELINE": (
            "Cobertura promovida sólo para MATCH desde el baseline del mismo "
            "circuito/layout. REJECT sigue siendo específico de la variante y "
            "permanece fail-closed. No significa fully calibrated."
        ),
        "TRACK_MATCH_BASELINE_SHADOW": (
            "El baseline MATCH del circuito/layout sigue en shadow. No autoriza "
            "MATCH productivo y nunca hereda REJECT."
        ),
        "WAITING_FOR_TRACK_BASELINE": (
            "Este contexto espera que otra variante establezca primero el baseline "
            "MATCH del circuito/layout. REJECT no se comparte."
        ),
    }
    text = descriptions.get(
        status,
        str((row.get("next_action") or {}).get("description") or status),
    )
    source_variants = list(row.get("baseline_source_variants") or [])
    if source_variants and status in {
        "COVERED_BY_TRACK_MATCH_BASELINE",
        "TRACK_MATCH_BASELINE_SHADOW",
    }:
        text += " Variantes fuente: " + ", ".join(map(str, source_variants)) + "."
    h3 = row.get("h3_import") or {}
    h3_status = str(h3.get("status") or "H3_NOT_APPLICABLE")
    h3_text = {
        "H3_NOT_APPLICABLE": "H3: no hay una materialización oficial aplicable.",
        "H3_READY_TO_IMPORT": (
            "H3: bundle oficial validado y listo para importación explícita; "
            "History todavía no fue modificado."
        ),
        "H3_IMPORTED": (
            "H3: este bundle exacto ya está en History como evidencia observacional."
        ),
        "H3_CONFLICT": "H3: conflicto detectado; la importación está bloqueada.",
        "H3_FAILED": "H3: el bundle no superó la validación fail-closed.",
    }.get(h3_status, f"H3: {h3_status}.")
    reason = str(h3.get("reason") or "").strip()
    if reason:
        h3_text += f" Motivo: {reason}."
    text += " " + h3_text
    return text


def format_comparison_columns(view: dict) -> tuple[str, str, str, str]:
    available = bool(view.get("available"))
    hist = view.get("historical") or {}
    current = view.get("current") or {}
    hist_text = (
        (
            f"Sesión histórica: #{hist.get('session_id', '—')}\n"
            f"Vuelta: {hist.get('lap', '—')}\n"
            f"Tiempo: {hist.get('duration_text', '—')}"
        )
        if available
        else "Sin comparación histórica."
    )
    current_text = (
        (
            f"Sesión actual: #{current.get('session_id', '—')}\n"
            f"Vuelta: {current.get('lap', '—')}\n"
            f"Tiempo: {current.get('duration_text', '—')}"
        )
        if available
        else "Sin comparación histórica."
    )
    summary = (
        f"Delta actual − histórica: {view.get('delta_text', '—')}"
        if available
        else f"H5.2: {view.get('stage_status', 'NO_EJECUTADA')}"
    )
    detail_lines: list[str] = []
    if available:
        zones = view.get("zones") or []
        if zones:
            detail_lines.append("Zonas de mayor impacto (top 3):")
            for zone in zones:
                change = zone.get("delta_change_s")
                change_text = f"{change:+.3f} s" if change is not None else "—"
                detail_lines.append(
                    f"• {zone.get('label')}: {zone.get('type')} · cambio {change_text}"
                )
        else:
            detail_lines.append("No hay zonas deterministas disponibles.")
        rendered = (view.get("llm") or {}).get("rendered") or ""
        if rendered:
            detail_lines.extend(("", "Lectura histórica validada:", rendered))
    detail_text = "\n".join(detail_lines) if detail_lines else (
        "Esta sesión no tiene una comparación histórica H5.2 disponible."
    )
    return summary, hist_text, current_text, detail_text


def resolve_historical_telemetry_reference(
    reference_selection_path: Path | None,
    sessions: list[SessionRecord],
) -> dict | None:
    """Resolve H4's selected reference to an existing source DuckDB, read-only."""
    if reference_selection_path is None or not reference_selection_path.is_file():
        return None
    try:
        payload = json.loads(reference_selection_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    selected = payload.get("selected_historical_reference")
    if not isinstance(selected, dict):
        return None
    source_value = selected.get("source_json_path")
    if not isinstance(source_value, str) or not source_value.strip():
        return None
    try:
        source_path = Path(source_value).expanduser().resolve()
    except OSError:
        return None

    database_path = None
    for candidate in sessions:
        analysis_path = candidate.analysis_path
        if analysis_path is None:
            continue
        try:
            same_source = analysis_path.expanduser().resolve() == source_path
        except OSError:
            same_source = False
        if same_source:
            database_path = candidate.database_path
            break

    if database_path is None:
        state_path = source_path.parent / "state.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            value = state.get("database")
            if isinstance(value, str) and value.strip():
                database_path = Path(value)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass

    if database_path is None:
        return None
    try:
        database_path = database_path.expanduser().resolve()
    except OSError:
        return None
    if not database_path.is_file():
        return None

    try:
        lap = int(selected.get("lap"))
    except (TypeError, ValueError):
        lap = None
    try:
        duration_s = float(selected.get("duration_s"))
    except (TypeError, ValueError):
        duration_s = None
    try:
        session_id = int(selected.get("session_id"))
    except (TypeError, ValueError):
        session_id = None

    return {
        "database_path": database_path,
        "lap": lap,
        "duration_s": duration_s,
        "session_id": session_id,
    }


class RaceEngineerApp:
    def __init__(self, root, runs_root: Path):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.runs_root = runs_root
        self.sessions: list[SessionRecord] = []
        self.all_sessions: list[SessionRecord] = []
        self.session_read_errors: list[str] = []
        self._row_tooltip = None
        self.track_playback_active = False
        self.track_playback_after_id = None
        self.track_resolution_hz = 20.0
        self.analysis_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.track_map_queue: queue.Queue[tuple[int, str, object]] = queue.Queue()
        self.session_change_queue: queue.Queue[tuple[int, str, object]] = queue.Queue()
        self.session_change_token = 0
        self.session_change_after_id = None
        self.session_change_cache: dict[str, dict] = {}
        self.track_map_token = 0
        self.track_map_loading = False
        self.current_track_map: TrackMapData | None = None
        self.current_session_reference_track_map: TrackMapData | None = None
        self.current_track_lap_options: tuple[TrackMapLapOption, ...] = ()
        self.track_lap_lookup: dict[str, TrackMapLapOption] = {}
        self.current_track_record: SessionRecord | None = None
        self.manual_track_map_loading = False
        self.current_historical_track_map: TrackMapData | None = None
        self.current_historical_track_label = ""
        self.historical_track_map_loading = False
        self.current_track_zones: tuple[TrackMapZone, ...] = ()
        self.current_track_priorities: tuple[TrackMapPriority, ...] = ()
        self.current_track_profile: dict | None = None
        self.current_track_turns: tuple[TrackMapTurn, ...] = ()
        self.current_fitted_track_points: tuple[tuple[float, float], ...] = ()
        self.selected_track_overlay: tuple[str, str] | None = None
        self.selected_track_point_index: int | None = None
        self.track_map_dragging = False
        self.telemetry_chart_dragging = False
        self.telemetry_zoom_range: tuple[float, float] | None = None
        self.track_map_zoom_scale = 1.0
        self.track_map_zoom_offset = (0.0, 0.0)
        self.track_map_pan_anchor: tuple[float, float] | None = None
        self.track_map_cache: dict[
            tuple[str, int, int | None, int | None], TrackMapData
        ] = {}
        self.analysis_running = False
        self.analysis_database: Path | None = None
        self._state_files_fingerprint: tuple[tuple[str, int, int], ...] = ()
        self._scheduler_state_fingerprint: tuple[tuple[int, int] | None, tuple[int, int] | None] | None = None
        self._calibration_state_fingerprint: tuple[tuple[str, int, int], ...] = ()
        self._state_refresh_after_id = None
        self._closing = False
        self.telemetry_ingest_state_path = (
            PROJECT_ROOT / "data" / "local" / "telemetry_auto_ingest.json"
        )
        self.scheduler_runtime_path = (
            PROJECT_ROOT / "data" / "local" / "telemetry_scheduler_runtime.json"
        )
        self.scheduler_log_path = (
            PROJECT_ROOT / "data" / "local" / "telemetry_auto_ingest_task.log"
        )
        self.scheduler_diagnostic_window = None
        self.calibration_batches_root = PROJECT_ROOT / "calibration_batches"
        self.track_readiness_payload: dict = {}
        self.track_readiness_rows: list[dict] = []
        self.track_readiness_tracks: list[dict] = []
        self.settings_warning = ""

        root.title(f"Threshzz's Telemetry Analysis LMU v{GUI_VERSION}")
        root.geometry("1600x1040")
        root.minsize(1240, 760)
        root.configure(background="#0b1116")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_style()
        self._build_layout()
        self.refresh()
        self._schedule_state_refresh_check()

    def _configure_style(self):
        style = self.ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.root.option_add("*TCombobox*Listbox.background", "#15181c")
        self.root.option_add("*TCombobox*Listbox.foreground", "#dce7ef")
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#315b60")
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#f4fbff")
        style.configure("App.TFrame", background="#0b1116")
        style.configure("Panel.TFrame", background="#111820")
        style.configure("TPanedwindow", background="#0b1116", sashwidth=6)
        style.configure(
            "Title.TLabel",
            background="#0b1116",
            foreground="#f2f7fb",
            font=("Segoe UI Semibold", 16),
        )
        style.configure(
            "Subtitle.TLabel",
            background="#0b1116",
            foreground="#8fa5b8",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Metric.TLabel",
            background="#111820",
            foreground="#e8f1f7",
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "Muted.TLabel",
            background="#111820",
            foreground="#91a6b8",
            font=("Segoe UI", 9),
        )
        style.configure(
            "H53Ready.TLabel",
            background="#1c1c1c",
            foreground="#00FFA6",
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "H53Pending.TLabel",
            background="#1c1c1c",
            foreground="#f0c674",
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "H53Error.TLabel",
            background="#1c1c1c",
            foreground="#ff7b72",
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "H53Muted.TLabel",
            background="#1c1c1c",
            foreground="#91a6b8",
            font=("Segoe UI", 9),
        )
        style.configure(
            "DialogTitle.TLabel",
            background="#1c1c1c",
            foreground="#f2f7fb",
            font=("Segoe UI Semibold", 16),
        )
        style.configure(
            "TSeparator",
            background="#343b42",
            bordercolor="#343b42",
        )
        style.configure(
            "Accent.TButton",
            font=("Segoe UI Semibold", 10),
            foreground="#061014",
            background="#00FFA6",
            padding=(12, 7),
        )
        style.map(
            "Accent.TButton",
            background=[("pressed", "#2aa999"), ("active", "#00FFA6"), ("disabled", "#31504f")],
            foreground=[("disabled", "#809390")],
        )
        style.configure(
            "Analyze.TButton",
            font=("Segoe UI Semibold", 10),
            foreground="#fff4f4",
            background="#7d2938",
            padding=(12, 7),
        )
        style.map(
            "Analyze.TButton",
            background=[("pressed", "#66212e"), ("active", "#9b3548"), ("disabled", "#42262d")],
            foreground=[("disabled", "#8e777c")],
        )
        style.configure(
            "TCheckbutton",
            background="#101010",
            foreground="#c9c9c9",
            font=("Segoe UI", 9),
        )
        style.map(
            "TCheckbutton",
            background=[("active", "#101010")],
            foreground=[("disabled", "#666f77")],
            indicatorcolor=[("selected", "#00FFA6"), ("!selected", "#30363c")],
        )
        style.configure(
            "TButton",
            background="#252a2f",
            foreground="#dce7ef",
            borderwidth=0,
            focusthickness=1,
            focuscolor="#00FFA6",
            padding=(10, 7),
            relief="flat",
            font=("Segoe UI", 10),
        )
        style.map(
            "TButton",
            background=[("pressed", "#202429"), ("active", "#343b42"), ("disabled", "#1f2225")],
            foreground=[("disabled", "#69747d")],
        )
        style.configure(
            "TEntry",
            fieldbackground="#15181c",
            foreground="#e4edf3",
            bordercolor="#343b42",
            lightcolor="#343b42",
            darkcolor="#343b42",
            insertcolor="#00FFA6",
            padding=(8, 7),
            relief="flat",
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", "#00FFA6"), ("disabled", "#252a2f")],
            fieldbackground=[("disabled", "#202327")],
            foreground=[("disabled", "#69747d")],
        )
        style.configure(
            "TCombobox",
            fieldbackground="#15181c",
            background="#252a2f",
            foreground="#e4edf3",
            arrowcolor="#9fb2c1",
            bordercolor="#343b42",
            lightcolor="#343b42",
            darkcolor="#343b42",
            borderwidth=0,
            padding=(8, 6),
            relief="flat",
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#15181c"), ("disabled", "#202327")],
            background=[("active", "#343b42"), ("readonly", "#252a2f"), ("disabled", "#202327")],
            foreground=[("readonly", "#e4edf3"), ("disabled", "#69747d")],
            arrowcolor=[("active", "#00FFA6"), ("disabled", "#69747d")],
            bordercolor=[("focus", "#00FFA6")],
        )
        scrollbar_options = {
            "background": "#39434b",
            "troughcolor": "#15181c",
            "bordercolor": "#15181c",
            "lightcolor": "#39434b",
            "darkcolor": "#39434b",
            "arrowcolor": "#91a6b8",
            "borderwidth": 0,
            "width": 10,
            "relief": "flat",
        }
        for scrollbar_style in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.configure(scrollbar_style, **scrollbar_options)
            style.map(
                scrollbar_style,
                background=[("pressed", "#00FFA6"), ("active", "#53616b")],
                arrowcolor=[("active", "#e4edf3")],
            )
        style.configure(
            "Treeview",
            background="#171717",
            fieldbackground="#171717",
            foreground="#dce7ef",
            rowheight=30,
            borderwidth=0,
            relief="flat",
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#2a2a2a",
            foreground="#9fb3c8",
            font=("Segoe UI Semibold", 9),
            padding=(5, 8),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", "#315b60")],
            foreground=[("selected", "#f4fbff")],
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#343b42")],
            foreground=[("active", "#00FFA6")],
        )
        style.configure(
            "Inspector.TFrame",
            background="#14191c",
        )
        style.configure(
            "InspectorTitle.TLabel",
            background="#14191c",
            foreground="#f2f7fb",
            font=("Segoe UI Semibold", 13),
        )
        style.configure(
            "InspectorMeta.TLabel",
            background="#14191c",
            foreground="#7f929f",
            font=("Segoe UI Semibold", 8),
        )
        style.configure(
            "InspectorClose.TButton",
            background="#14191c",
            foreground="#91a6b8",
            borderwidth=0,
            relief="flat",
            padding=(5, 2),
            font=("Segoe UI Semibold", 12),
        )
        style.map(
            "InspectorClose.TButton",
            background=[
                ("active", "#252d32"),
                ("pressed", "#303940"),
            ],
            foreground=[
                ("active", "#f2f7fb"),
            ],
        )

        style.configure(
            "PriorityCard.TFrame",
            background="#172421",
            borderwidth=1,
            relief="solid",
            bordercolor="#28403b",
        )
        style.configure(
            "PriorityIndex.TLabel",
            background="#172421",
            foreground="#00FFA6",
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "PriorityTitle.TLabel",
            background="#172421",
            foreground="#f2f7fb",
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "PriorityCue.TLabel",
            background="#172421",
            foreground="#c5d3da",
            font=("Segoe UI", 10),
        )
        style.configure(
            "PriorityFocus.TLabel",
            background="#253c39",
            foreground="#7af1df",
            font=("Segoe UI Semibold", 8),
            padding=(7, 3),
        )

        style.configure(
            "SummaryCard.TFrame",
            background="#141c23",
            borderwidth=1,
            relief="solid",
            bordercolor="#26343d",
        )
        style.configure(
            "SummaryAccentCard.TFrame",
            background="#14211f",
            borderwidth=1,
            relief="solid",
            bordercolor="#24413d",
        )
        style.configure(
            "SummaryTitle.TLabel",
            background="#141c23",
            foreground="#00FFA6",
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "SummarySubtitle.TLabel",
            background="#141c23",
            foreground="#8399a8",
            font=("Segoe UI", 9),
        )
        style.configure(
            "SummaryAccentTitle.TLabel",
            background="#14211f",
            foreground="#00FFA6",
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "SummaryAccentSubtitle.TLabel",
            background="#14211f",
            foreground="#8eaaa5",
            font=("Segoe UI", 9),
        )

        style.configure(
            "Workspace.TFrame",
            background="#0d151b",
        )
        style.configure(
            "WorkspaceNav.TFrame",
            background="#0f161d",
        )
        style.configure(
            "WorkspaceNav.TButton",
            background="#0f161d",
            foreground="#91a6b8",
            borderwidth=0,
            relief="flat",
            padding=(14, 8),
            anchor="center",
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "WorkspaceNav.TButton",
            background=[
                ("active", "#20262b"),
                ("pressed", "#252c31"),
            ],
            foreground=[
                ("active", "#e4edf3"),
            ],
        )
        style.configure(
            "WorkspaceNavActive.TButton",
            background="#123138",
            foreground="#00FFA6",
            borderwidth=0,
            relief="flat",
            padding=(14, 8),
            anchor="center",
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "WorkspaceNavActive.TButton",
            background=[
                ("active", "#2b3a40"),
                ("pressed", "#2b3a40"),
            ],
            foreground=[
                ("active", "#00FFA6"),
            ],
        )

        style.configure(
            "Sidebar.TFrame",
            background="#071018",
        )
        style.configure(
            "SidebarBrand.TLabel",
            background="#071018",
            foreground="#f2f7fb",
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "SidebarMeta.TLabel",
            background="#071018",
            foreground="#7f929f",
            font=("Segoe UI", 8),
        )
        style.configure(
            "SidebarStatus.TLabel",
            background="#071018",
            foreground="#00FFA6",
            font=("Segoe UI Semibold", 8),
        )
        style.configure(
            "SidebarSession.TLabel",
            background="#071018",
            foreground="#dce7ef",
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "SidebarNav.TButton",
            background="#071018",
            foreground="#c6d3dc",
            borderwidth=0,
            relief="flat",
            padding=(12, 10),
            anchor="w",
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "SidebarNav.TButton",
            background=[("active", "#101c24"), ("pressed", "#14242c")],
            foreground=[("active", "#f2f7fb")],
        )
        style.configure(
            "SidebarNavActive.TButton",
            background="#0a3338",
            foreground="#00FFA6",
            borderwidth=0,
            relief="flat",
            padding=(12, 10),
            anchor="w",
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "SidebarNavActive.TButton",
            background=[("active", "#104148"), ("pressed", "#104148")],
            foreground=[("active", "#7af1df")],
        )
        style.configure(
            "WorkspaceHeader.TFrame",
            background="#0b1116",
        )
        style.configure(
            "WorkspaceTitle.TLabel",
            background="#0b1116",
            foreground="#f2f7fb",
            font=("Segoe UI Semibold", 17),
        )
        style.configure(
            "WorkspaceSubtitle.TLabel",
            background="#0b1116",
            foreground="#91a6b8",
            font=("Segoe UI", 9),
        )

        style.configure(
            "Link.TButton",
            background="#151d24",
            foreground="#00FFA6",
            borderwidth=0,
            relief="flat",
            padding=(4, 3),
            anchor="e",
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Link.TButton",
            background=[("active", "#151d24"), ("pressed", "#151d24")],
            foreground=[("active", "#8cf5e7")],
        )

        style.configure("TNotebook", background="#1c1c1c", borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#2a2a2a",
            foreground="#b8c7d3",
            padding=(14, 9),
            font=("Segoe UI Semibold", 9),
            borderwidth=0,
            focuscolor="#1c1c1c",
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#22282e"), ("active", "#2c363b"), ("disabled", "#202327")],
            foreground=[("selected", "#00FFA6"), ("active", "#e4edf3"), ("disabled", "#69747d")],
        )
        style.configure(
            "Horizontal.TProgressbar",
            background="#00FFA6",
            troughcolor="#252a2f",
            bordercolor="#252a2f",
            lightcolor="#00FFA6",
            darkcolor="#00FFA6",
            borderwidth=0,
            thickness=5,
        )
        style.configure(
            "MetricCard.TFrame",
            background="#171a1d",
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "CardLabel.TLabel",
            background="#171a1d",
            foreground="#7f929f",
            font=("Segoe UI Semibold", 8),
        )
        style.configure(
            "CardValue.TLabel",
            background="#171a1d",
            foreground="#edf6fa",
            font=("Segoe UI Semibold", 11),
        )

    def _build_layout(self):
        ttk = self.ttk
        tk = self.tk

        shell = ttk.Frame(self.root, style="App.TFrame")
        shell.pack(fill="both", expand=True)

        sidebar = ttk.Frame(shell, style="Sidebar.TFrame", width=258)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        main = ttk.Frame(shell, style="App.TFrame", padding=(22, 16, 20, 10))
        main.pack(side="left", fill="both", expand=True)

        brand = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(16, 16, 14, 10))
        brand.pack(fill="x")
        ttk.Label(
            brand,
            text="Threshzz's Telemetry\nAnalysis Tool",
            style="SidebarBrand.TLabel",
            justify="left",
        ).pack(anchor="w")
        self.scheduler_var = tk.StringVar(value="Sistema · cargando…")
        self.scheduler_label = ttk.Label(brand, textvariable=self.scheduler_var, style="SidebarStatus.TLabel")
        self.scheduler_label.pack(anchor="w", pady=(7, 0))

        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", padx=16, pady=(2, 8))

        self.primary_section_var = tk.StringVar(value="Resumen")
        self.primary_section_frames = {}
        self.primary_section_buttons = {}
        nav = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(8, 0, 8, 6))
        nav.pack(fill="x")
        for section in PRIMARY_SECTIONS:
            button = ttk.Button(
                nav,
                text=section,
                style="SidebarNav.TButton",
                command=lambda name=section: self._show_primary_section(name),
            )
            button.pack(fill="x", pady=1)
            self.primary_section_buttons[section] = button

        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", padx=16, pady=(6, 10))

        selected_box = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(16, 0, 14, 8))
        selected_box.pack(fill="x")
        ttk.Label(selected_box, text="SESIÓN SELECCIONADA", style="SidebarMeta.TLabel").pack(anchor="w")
        self.detail_title = tk.StringVar(value="Seleccioná una sesión")
        self.detail_subtitle = tk.StringVar(value="")
        ttk.Label(
            selected_box,
            textvariable=self.detail_title,
            style="SidebarSession.TLabel",
            wraplength=200,
            justify="left",
        ).pack(anchor="w", pady=(7, 0))
        ttk.Label(
            selected_box,
            textvariable=self.detail_subtitle,
            style="SidebarMeta.TLabel",
            wraplength=200,
            justify="left",
        ).pack(anchor="w", pady=(3, 8))
        self.open_button = ttk.Button(
            selected_box,
            text="Abrir carpeta de la sesión",
            command=self._open_selected_folder,
            state="disabled",
        )
        self.open_button.pack(fill="x")

        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", padx=16, pady=(4, 10))

        browser = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(12, 0, 10, 0))
        browser.pack(fill="both", expand=True)
        self.count_var = tk.StringVar(value="Buscando sesiones…")
        ttk.Label(browser, textvariable=self.count_var, style="SidebarMeta.TLabel").pack(anchor="w")
        self.session_query_var = tk.StringVar()
        self.session_query_entry = ttk.Entry(browser, textvariable=self.session_query_var)
        self.session_query_entry.pack(fill="x", pady=(7, 6))
        self.session_filter_var = tk.StringVar(value="Todas")
        self.session_filter_combo = ttk.Combobox(
            browser,
            textvariable=self.session_filter_var,
            values=tuple(SESSION_FILTER_LABELS),
            state="readonly",
        )
        self.session_filter_combo.pack(fill="x", pady=(0, 8))
        self.session_filter_combo.bind("<<ComboboxSelected>>", self._apply_session_filters)
        self.session_query_var.trace_add("write", lambda *_: self._apply_session_filters())

        columns = ("date", "track", "vehicle", "laps", "best", "status")
        self.tree = ttk.Treeview(
            browser,
            columns=columns,
            displaycolumns=("date", "track", "status"),
            show="headings",
            selectmode="browse",
        )
        for name, text, width, stretch in (
            ("date", "Fecha", 78, False),
            ("track", "Circuito", 104, True),
            ("status", "Estado", 48, False),
        ):
            self.tree.heading(name, text=text)
            self.tree.column(name, width=width, minwidth=40, stretch=stretch)
        for name in ("vehicle", "laps", "best"):
            self.tree.column(name, width=0, minwidth=0, stretch=False)
        tree_scrollbar = ttk.Scrollbar(browser, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)
        tree_scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_session_double_click)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._hide_row_tooltip)

        sidebar_bottom = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(12, 9, 10, 12))
        sidebar_bottom.pack(fill="x")
        self.skip_stability_var = tk.BooleanVar(value=False)
        self.skip_stability_check = ttk.Checkbutton(
            sidebar_bottom,
            text="Omitir espera 10 min",
            variable=self.skip_stability_var,
        )
        self.skip_stability_check.pack(anchor="w", pady=(0, 6))
        side_actions = ttk.Frame(sidebar_bottom, style="Sidebar.TFrame")
        side_actions.pack(fill="x")
        self.refresh_button = ttk.Button(side_actions, text="Actualizar", command=self.refresh)
        self.refresh_button.pack(side="left", fill="x", expand=True)
        self.history_button = ttk.Button(side_actions, text="History", command=self._open_history)
        self.history_button.pack(side="left", fill="x", expand=True, padx=(6, 0))

        header = ttk.Frame(main, style="WorkspaceHeader.TFrame")
        header.pack(fill="x", pady=(0, 14))
        header_labels = ttk.Frame(header, style="WorkspaceHeader.TFrame")
        header_labels.pack(side="left", fill="x", expand=True)
        self.workspace_title_var = tk.StringVar(value="Resumen")
        self.workspace_subtitle_var = tk.StringVar(value=SECTION_DESCRIPTIONS["Resumen"])
        ttk.Label(header_labels, textvariable=self.workspace_title_var, style="WorkspaceTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header_labels,
            textvariable=self.workspace_subtitle_var,
            style="WorkspaceSubtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        self.analyze_button = ttk.Button(
            header,
            text="Analizar sesión…",
            style="Accent.TButton",
            command=self._choose_analysis_file,
        )
        self.analyze_button.pack(side="right")

        # Estas métricas siguen disponibles para estado interno y otras vistas,
        # pero no ocupan una fila propia en Resumen: la sesión seleccionada ya
        # aporta ese contexto en el sidebar y el dashboard prioriza coaching.
        self.summary_reference_var = tk.StringVar(value="—")
        self.summary_laps_var = tk.StringVar(value="—")
        self.summary_history_var = tk.StringVar(value="—")
        self.summary_status_var = tk.StringVar(value="—")

        workspace_body = ttk.Frame(main, style="Workspace.TFrame")
        workspace_body.pack(fill="both", expand=True)
        workspace = ttk.Frame(workspace_body, style="Workspace.TFrame")
        workspace.pack(side="left", fill="both", expand=True)

        self.inspector_frame = ttk.Frame(
            workspace_body,
            style="Inspector.TFrame",
            padding=(16, 14),
            width=290,
        )
        self.inspector_frame.pack_propagate(False)
        self.inspector_visible = False
        inspector_header = ttk.Frame(self.inspector_frame, style="Inspector.TFrame")
        inspector_header.pack(fill="x", pady=(0, 14))
        self.inspector_title_var = tk.StringVar(value="Detalle")
        self.inspector_meta_var = tk.StringVar(value="")
        ttk.Label(inspector_header, textvariable=self.inspector_title_var, style="InspectorTitle.TLabel").pack(side="left")
        ttk.Button(
            inspector_header,
            text="×",
            style="InspectorClose.TButton",
            width=3,
            command=self._hide_plan_inspector,
        ).pack(side="right")
        ttk.Label(
            self.inspector_frame,
            textvariable=self.inspector_meta_var,
            style="InspectorMeta.TLabel",
            wraplength=250,
            justify="left",
        ).pack(fill="x", pady=(0, 10))
        self.inspector_text = tk.Text(
            self.inspector_frame,
            wrap="word",
            background="#11171a",
            foreground="#cbd8df",
            insertbackground="#00FFA6",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=12,
            pady=10,
            font=("Segoe UI", 9),
            spacing1=2,
            spacing3=5,
        )
        self.inspector_text.tag_configure(
            "section",
            font=("Segoe UI Semibold", 9),
            foreground="#00FFA6",
            spacing1=10,
            spacing3=4,
        )
        self.inspector_text.tag_configure("value", font=("Segoe UI", 9), foreground="#dce7ef")
        self.inspector_text.pack(fill="both", expand=True)
        self.inspector_text.configure(state="disabled")

        for section in PRIMARY_SECTIONS:
            self.primary_section_frames[section] = ttk.Frame(workspace, style="Workspace.TFrame")

        summary_frame = self.primary_section_frames["Resumen"]
        self.summary_canvas = tk.Canvas(
            summary_frame,
            background="#0f161d",
            highlightthickness=0,
            borderwidth=0,
        )
        summary_scrollbar = ttk.Scrollbar(summary_frame, orient="vertical", command=self.summary_canvas.yview)
        self.summary_canvas.configure(yscrollcommand=summary_scrollbar.set)
        summary_scrollbar.pack(side="right", fill="y")
        self.summary_canvas.pack(side="left", fill="both", expand=True)
        summary_content = ttk.Frame(self.summary_canvas, style="Workspace.TFrame")
        self.summary_content = summary_content
        self.summary_canvas_window = self.summary_canvas.create_window((0, 0), window=summary_content, anchor="nw")
        summary_content.bind("<Configure>", self._on_summary_content_configure)
        self.summary_canvas.bind("<Configure>", self._on_summary_canvas_configure)
        self.summary_canvas.bind("<MouseWheel>", self._on_summary_mousewheel)

        # v1.28: dashboard principal inspirado en una UI de ingeniería moderna.
        # La fila superior concentra decisión y coaching; la visualización vive
        # en una segunda fila más alta para evitar cuatro columnas de texto
        # compitiendo por el mismo espacio.
        self.summary_dashboard = ttk.Frame(
            summary_content,
            style="Workspace.TFrame",
            height=270,
        )
        summary_dashboard = self.summary_dashboard
        summary_dashboard.pack(fill="x", pady=(0, 10))
        summary_dashboard.pack_propagate(False)
        for column, weight in enumerate((25, 35, 18, 22)):
            summary_dashboard.columnconfigure(
                column,
                weight=weight,
                uniform="summary",
            )
        summary_dashboard.rowconfigure(0, weight=1)

        debrief_column = ttk.Frame(summary_dashboard, style="Workspace.TFrame")
        debrief_column.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        plan_column = ttk.Frame(summary_dashboard, style="Workspace.TFrame")
        plan_column.grid(row=0, column=1, sticky="nsew", padx=5)

        laps_column = ttk.Frame(summary_dashboard, style="Workspace.TFrame")
        laps_column.grid(row=0, column=2, sticky="nsew", padx=5)

        changes_column = ttk.Frame(summary_dashboard, style="Workspace.TFrame")
        changes_column.grid(row=0, column=3, sticky="nsew", padx=(5, 0))

        self.debrief_text = self._summary_text_panel(
            debrief_column,
            "DEBRIEF",
            subtitle="Síntesis ejecutiva de la sesión",
            height=12,
            expand=True,
            compact=True,
        )
        self.current_debrief_markdown = ""
        self.ttk.Button(
            self.debrief_text.master.master,
            text="Ver debrief completo  →",
            style="Link.TButton",
            command=self._show_full_debrief,
        ).pack(anchor="e", pady=(7, 0))

        self.plan_cards_frame = self._build_next_stint_panel(
            plan_column,
            compact=True,
        )

        self.laps_text = self._summary_text_panel(
            laps_column,
            "VUELTAS CLAVE",
            subtitle="Referencia, ritmo y consistencia",
            height=12,
            expand=True,
            compact=True,
        )
        self.laps_panel = self.laps_text.master.master
        self.current_laps_text = ""
        self.ttk.Button(
            self.laps_panel,
            text="Ver vueltas  →",
            style="Link.TButton",
            command=self._show_full_laps,
        ).pack(anchor="e", pady=(7, 0))

        # Inspector contextual: por ahora resume la comparación histórica;
        # las prioridades del plan continúan abriendo el inspector lateral de
        # detalle. En una iteración posterior ambos contextos podrán converger.
        self.session_change_panel = self._build_session_change_panel(
            changes_column,
            compact=True,
        )
        self.session_change_panel.pack(fill="both", expand=True)

        # Segunda fila visual del Resumen. Son previews livianos alimentados por
        # el mismo TrackMapData ya cargado por Telemetría; no existe un segundo
        # pipeline ni una segunda lectura de archivos.
        self.summary_visual_row = ttk.Frame(
            summary_content,
            style="Workspace.TFrame",
            height=420,
        )
        visual_row = self.summary_visual_row
        visual_row.pack(fill="both", expand=True, pady=(0, 0))
        visual_row.pack_propagate(False)
        visual_row.columnconfigure(0, weight=48, uniform="summary_visual")
        visual_row.columnconfigure(1, weight=52, uniform="summary_visual")
        visual_row.rowconfigure(0, weight=1)

        map_preview = self._build_summary_visual_card(
            visual_row,
            title="MAPA DEL CIRCUITO",
            subtitle="Zonas, prioridades y contexto espacial",
            column=0,
            padx=(0, 5),
        )
        self.summary_map_canvas = self._summary_preview_canvas(map_preview)
        self.summary_map_canvas.bind(
            "<Button-1>",
            lambda _event: self._show_primary_section("Telemetría"),
        )

        telemetry_preview = self._build_summary_visual_card(
            visual_row,
            title="TELEMETRÍA COMPARADA",
            subtitle="Velocidad, acelerador y freno · vista rápida",
            column=1,
            padx=(5, 0),
        )
        self.summary_telemetry_canvas = self._summary_preview_canvas(telemetry_preview)
        self.summary_telemetry_canvas.bind(
            "<Button-1>",
            lambda _event: self._show_primary_section("Telemetría"),
        )

        telemetry_frame = self.primary_section_frames["Telemetría"]
        self.track_map_canvas = self._track_map_tab(telemetry_frame, label=None)

        history_frame = self.primary_section_frames["Historial"]
        history_notebook = ttk.Notebook(history_frame)
        history_notebook.pack(fill="both", expand=True)
        self.historical_reference_text = self._text_tab(history_notebook, "Referencia")
        self._comparison_tab(history_notebook)

        readiness_frame = self.primary_section_frames["Circuitos"]
        self._track_readiness_panel(readiness_frame)

        diagnostics_frame = self.primary_section_frames["Diagnóstico"]
        self.diagnostics_notebook = ttk.Notebook(diagnostics_frame)
        self.diagnostics_notebook.pack(fill="both", expand=True)
        self.pipeline_text = self._text_tab(self.diagnostics_notebook, "Pipeline")
        self.execution_text = self._text_tab(self.diagnostics_notebook, "Ejecución")

        calibration_frame = self.primary_section_frames["Calibración"]
        self._calibration_panel(calibration_frame)

        self._show_primary_section("Resumen")

        execution_bar = ttk.Frame(main, style="App.TFrame")
        execution_bar.pack(fill="x", pady=(8, 0))
        self.execution_status = tk.StringVar(value="Sin análisis en ejecución")
        ttk.Label(execution_bar, textvariable=self.execution_status, style="Subtitle.TLabel").pack(side="left")
        self.progress = ttk.Progressbar(execution_bar, mode="indeterminate", length=150)
        self.progress.pack(side="right")

        footer = str(self.runs_root)
        if self.settings_warning:
            footer += " · " + self.settings_warning
        self.footer_var = tk.StringVar(value=footer)
        ttk.Label(self.root, textvariable=self.footer_var, style="Subtitle.TLabel", anchor="w").pack(
            fill="x", padx=18, pady=(0, 7)
        )

        self.h5_3_review_state_path = PROJECT_ROOT / "data" / "local" / "h5_3_review_maintenance.json"
        self.h5_3_review_var = tk.StringVar(value="H5.3 shadow · cargando…")
        self.h5_3_review_label = ttk.Label(
            sidebar,
            textvariable=self.h5_3_review_var,
            style="H53Muted.TLabel",
        )

    def _show_primary_section(self, section):
        if section not in self.primary_section_frames:
            return

        for _name, frame in self.primary_section_frames.items():
            frame.pack_forget()

        frame = self.primary_section_frames[section]
        frame.pack(fill="both", expand=True)
        self.primary_section_var.set(section)
        self.workspace_title_var.set(section)
        self.workspace_subtitle_var.set(SECTION_DESCRIPTIONS.get(section, ""))
        if section == "Circuitos":
            self._refresh_track_readiness()

        for name, button in self.primary_section_buttons.items():
            button.configure(
                style=(
                    "SidebarNavActive.TButton"
                    if name == section
                    else "SidebarNav.TButton"
                )
            )

    def _on_summary_content_configure(self, _event=None):
        self.summary_canvas.configure(
            scrollregion=self.summary_canvas.bbox("all"),
        )

    def _on_summary_canvas_configure(self, event):
        # El frame interno ocupa siempre como mínimo todo el viewport visible.
        # Si la ventana baja de tamaño, conserva un mínimo y el Canvas hace
        # scroll. La fila visual usa pack(expand=True), por lo que absorbe de
        # forma nativa todo el espacio restante sin dejar una franja vacía.
        minimum_content_height = 650
        content_height = max(int(event.height), minimum_content_height)

        self.summary_canvas.itemconfigure(
            self.summary_canvas_window,
            width=event.width,
            height=content_height,
        )

        dashboard = getattr(self, "summary_dashboard", None)
        if dashboard is not None:
            # Coaching: proporcional en ventanas medianas, con límites para no
            # robar espacio al mapa/telemetría.
            dashboard_height = round(content_height * 0.43)
            dashboard_height = max(270, min(dashboard_height, 360))
            dashboard.configure(height=dashboard_height)

        # No fijamos la altura de summary_visual_row: expand=True la hace
        # ocupar exactamente todo lo que queda debajo del dashboard.
        self.summary_canvas.configure(
            scrollregion=self.summary_canvas.bbox("all"),
        )

    def _on_summary_mousewheel(self, event):
        if event.delta == 0:
            return "break"
        self.summary_canvas.yview_scroll(
            -3 if event.delta > 0 else 3,
            "units",
        )
        return "break"

    def _build_summary_visual_card(self, parent, *, title, subtitle, column, padx):
        card = self.ttk.Frame(
            parent,
            style="SummaryCard.TFrame",
            padding=(16, 13),
        )
        card.grid(row=0, column=column, sticky="nsew", padx=padx)
        self.ttk.Label(
            card,
            text=title,
            style="SummaryTitle.TLabel",
        ).pack(anchor="w")
        self.ttk.Label(
            card,
            text=subtitle,
            style="SummarySubtitle.TLabel",
        ).pack(anchor="w", pady=(2, 8))
        return card

    def _summary_preview_canvas(self, parent):
        canvas = self.tk.Canvas(
            parent,
            background="#0d141a",
            highlightthickness=1,
            highlightbackground="#2b3943",
            borderwidth=0,
            cursor="hand2",
        )
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Configure>", lambda _event: self._render_summary_visual_previews())
        return canvas

    def _render_summary_visual_previews(self):
        map_canvas = getattr(self, "summary_map_canvas", None)
        telemetry_canvas = getattr(self, "summary_telemetry_canvas", None)
        if map_canvas is None or telemetry_canvas is None:
            return

        for canvas in (map_canvas, telemetry_canvas):
            canvas.delete("all")

        data = self.current_track_map
        if data is None or len(data.points) < 2:
            for canvas, message in (
                (map_canvas, "Seleccioná una sesión para ver el mapa del circuito."),
                (telemetry_canvas, "La telemetría aparecerá cuando la sesión esté cargada."),
            ):
                width = max(canvas.winfo_width(), 120)
                height = max(canvas.winfo_height(), 80)
                canvas.create_text(
                    width / 2,
                    height / 2,
                    text=message,
                    fill="#7f929f",
                    width=max(width - 48, 80),
                    justify="center",
                    font=("Segoe UI", 9),
                )
            return

        # Preview del mapa: usa exactamente los puntos ya cargados y el helper
        # de fitting del mapa completo. Es deliberadamente no interactivo.
        map_width = max(map_canvas.winfo_width(), 160)
        map_height = max(map_canvas.winfo_height(), 120)
        fitted = fit_track_points(
            data.points,
            width_px=map_width,
            height_px=map_height,
            padding_px=24,
        )
        if len(fitted) >= 2:
            coords = [coordinate for point in fitted for coordinate in point]
            map_canvas.create_line(
                *coords,
                fill="#00FFA6",
                width=3,
                smooth=True,
                capstyle="round",
                joinstyle="round",
            )

            # Reproduce en Resumen la misma lectura visual de zonas que usa
            # Telemetría: pérdida=rojo, ganancia=verde y observación=ámbar.
            # Se dibujan encima de la traza base para identificar rápidamente
            # qué partes del circuito fueron analizadas.
            zone_colors = {
                "loss": "#e45a5a",
                "gain": "#45c98c",
                "observation": "#d5a94f",
            }
            for zone in self.current_track_zones:
                color = zone_colors.get(zone.kind, "#d5a94f")
                for start_index, end_index in zone_point_ranges(data.points, zone):
                    segment = fitted[start_index : end_index + 1]
                    if len(segment) < 2:
                        continue
                    segment_coordinates = [
                        value
                        for point in segment
                        for value in point
                    ]
                    map_canvas.create_line(
                        *segment_coordinates,
                        fill=color,
                        width=6,
                        smooth=True,
                        capstyle="round",
                        joinstyle="round",
                    )

            # Prioridades visibles como puntos cálidos sobre la traza.
            for priority in self.current_track_priorities[:6]:
                distance = getattr(priority, "center_distance_m", None)
                if distance is None:
                    start = getattr(priority, "start_distance_m", None)
                    end = getattr(priority, "end_distance_m", None)
                    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                        distance = (start + end) / 2.0
                if not isinstance(distance, (int, float)):
                    continue
                point_index = point_index_for_distance(data.points, distance)
                if point_index is None or not (0 <= point_index < len(fitted)):
                    continue
                x, y = fitted[point_index]
                radius = 5 if getattr(priority, "is_focus", False) else 4
                map_canvas.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    fill="#f0c674" if not getattr(priority, "is_focus", False) else "#ff7b72",
                    outline="#0d141a",
                    width=1,
                )
        map_canvas.create_text(
            12,
            map_height - 12,
            text="Click para abrir Telemetría",
            fill="#7f929f",
            anchor="sw",
            font=("Segoe UI", 8),
        )

        # Preview de canales: reutiliza build_track_telemetry_chart y reduce los
        # tres canales a lanes compactos para lectura rápida en Resumen.
        tel_width = max(telemetry_canvas.winfo_width(), 180)
        tel_height = max(telemetry_canvas.winfo_height(), 120)
        chart = build_track_telemetry_chart(
            data.points,
            width_px=tel_width,
            height_px=tel_height,
        )
        if chart is None:
            telemetry_canvas.create_text(
                tel_width / 2,
                tel_height / 2,
                text="Canales de telemetría no disponibles.",
                fill="#7f929f",
                font=("Segoe UI", 9),
            )
            return

        lane_height = (tel_height - 28) / 3.0
        for lane in (1, 2):
            y = 10 + lane * lane_height
            telemetry_canvas.create_line(10, y, tel_width - 10, y, fill="#26323b")
        for values, color in (
            (chart.speed, "#55b7e8"),
            (chart.throttle, "#45c98c"),
            (chart.brake, "#e45a5a"),
        ):
            if len(values) >= 2:
                coordinates = [coordinate for point in values for coordinate in point]
                telemetry_canvas.create_line(
                    *coordinates,
                    fill=color,
                    width=2,
                    joinstyle="round",
                )
        telemetry_canvas.create_text(
            12,
            tel_height - 10,
            text="Velocidad  ·  Acelerador  ·  Freno    ·    Click para ampliar",
            fill="#7f929f",
            anchor="sw",
            font=("Segoe UI", 8),
        )

    def _comparison_tab(self, notebook):
        frame = self.ttk.Frame(notebook, style="Panel.TFrame", padding=5)
        notebook.add(frame, text="Comparación")
        self.comparison_summary_var = self.tk.StringVar(value="")
        self.ttk.Label(
            frame,
            textvariable=self.comparison_summary_var,
            style="CardValue.TLabel",
            wraplength=960,
            justify="left",
        ).pack(fill="x", padx=4, pady=(0, 6))

        columns = self.ttk.Frame(frame, style="Panel.TFrame")
        columns.pack(fill="both", expand=True)
        self.comparison_hist_text = self._readonly_pane(
            columns,
            "Histórica",
            side="left",
        )
        self.comparison_current_text = self._readonly_pane(
            columns,
            "Sesión actual",
            side="right",
        )

        detail_holder = self.ttk.Frame(frame, style="Panel.TFrame")
        detail_holder.pack(fill="both", expand=True, pady=(6, 0))
        self.comparison_detail_text = self._readonly_pane(
            detail_holder,
            "Detalle y lectura validada",
            side="top",
        )
        return frame

    def _track_readiness_panel(self, parent):
        frame = self.ttk.Frame(parent, style="Panel.TFrame", padding=8)
        frame.pack(fill="both", expand=True)

        header = self.ttk.Frame(frame, style="Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        self.track_readiness_summary_var = self.tk.StringVar(
            value="Cargando estado de circuitos…"
        )
        self.ttk.Label(
            header,
            textvariable=self.track_readiness_summary_var,
            style="CardValue.TLabel",
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        self.ttk.Button(
            header,
            text="Actualizar estado",
            command=self._refresh_track_readiness,
        ).pack(side="right")

        split = self.ttk.Panedwindow(frame, orient="vertical")
        split.pack(fill="both", expand=True)

        tracks_panel = self.ttk.Frame(split, style="Panel.TFrame")
        contexts_panel = self.ttk.Frame(split, style="Panel.TFrame")
        split.add(tracks_panel, weight=2)
        split.add(contexts_panel, weight=3)

        self.ttk.Label(
            tracks_panel,
            text="CIRCUITOS",
            style="CardLabel.TLabel",
        ).pack(anchor="w", pady=(0, 5))

        track_columns = ("track", "profile", "contexts", "satisfied", "pending", "unresolved")
        self.track_readiness_tree = self.ttk.Treeview(
            tracks_panel,
            columns=track_columns,
            show="headings",
            selectmode="browse",
            height=9,
        )
        track_headings = {
            "track": "Circuito",
            "profile": "Profile",
            "contexts": "Contexts",
            "satisfied": "OK",
            "pending": "Pendientes",
            "unresolved": "Sin resolver",
        }
        track_widths = {
            "track": 360,
            "profile": 130,
            "contexts": 70,
            "satisfied": 55,
            "pending": 80,
            "unresolved": 90,
        }
        for name in track_columns:
            self.track_readiness_tree.heading(name, text=track_headings[name])
            self.track_readiness_tree.column(
                name,
                width=track_widths[name],
                minwidth=50,
                stretch=name == "track",
            )
        track_scroll = self.ttk.Scrollbar(
            tracks_panel, orient="vertical", command=self.track_readiness_tree.yview
        )
        self.track_readiness_tree.configure(yscrollcommand=track_scroll.set)
        track_scroll.pack(side="right", fill="y")
        self.track_readiness_tree.pack(fill="both", expand=True)
        self.track_readiness_tree.bind("<<TreeviewSelect>>", self._on_track_readiness_select)

        self.track_readiness_tree.tag_configure(
            "track_ok",
            foreground=READINESS_STATUS_COLORS["CURRENT_REQUIREMENTS_SATISFIED"],
        )
        self.track_readiness_tree.tag_configure(
            "track_pending",
            foreground=READINESS_STATUS_COLORS["NEEDS_EVALUATION"],
        )
        self.track_readiness_tree.tag_configure(
            "track_profile_missing",
            foreground=READINESS_STATUS_COLORS["NEEDS_PROFILE"],
        )

        context_header = self.ttk.Frame(contexts_panel, style="Panel.TFrame")
        context_header.pack(fill="x", pady=(8, 5))
        self.track_readiness_detail_var = self.tk.StringVar(
            value="Seleccioná un circuito para ver sus contextos."
        )
        self.ttk.Label(
            context_header,
            textvariable=self.track_readiness_detail_var,
            style="CardValue.TLabel",
            justify="left",
        ).pack(anchor="w")

        context_columns = (
            "variant", "sessions", "labels", "matcher", "h3", "historical", "status", "next"
        )
        self.track_context_tree = self.ttk.Treeview(
            contexts_panel,
            columns=context_columns,
            show="headings",
            selectmode="browse",
        )
        context_headings = {
            "variant": "Variant",
            "sessions": "Sesiones",
            "labels": "Labels",
            "matcher": "H2",
            "h3": "H3",
            "historical": "Histórico",
            "status": "Estado",
            "next": "Siguiente acción",
        }
        context_widths = {
            "variant": 110,
            "sessions": 70,
            "labels": 70,
            "matcher": 270,
            "h3": 135,
            "historical": 145,
            "status": 220,
            "next": 250,
        }
        for name in context_columns:
            self.track_context_tree.heading(name, text=context_headings[name])
            self.track_context_tree.column(
                name,
                width=context_widths[name],
                minwidth=55,
                stretch=name in {"matcher", "status", "next"},
            )
        context_scroll = self.ttk.Scrollbar(
            contexts_panel, orient="vertical", command=self.track_context_tree.yview
        )
        self.track_context_tree.configure(yscrollcommand=context_scroll.set)
        context_scroll.pack(side="right", fill="y")
        self.track_context_tree.pack(fill="both", expand=True)
        self.track_context_tree.bind(
            "<Motion>", self._on_track_readiness_context_motion
        )
        self.track_context_tree.bind("<Leave>", self._hide_row_tooltip)

        for status, color in READINESS_STATUS_COLORS.items():
            self.track_context_tree.tag_configure(status, foreground=color)

        self._refresh_track_readiness()
        return frame

    def _refresh_track_readiness(self):
        try:
            payload = build_track_readiness(project_root=PROJECT_ROOT)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.track_readiness_summary_var.set(
                f"No se pudo calcular Track Readiness: {exc}"
            )
            return

        self.track_readiness_payload = payload
        self.track_readiness_rows = list(payload.get("rows") or [])
        self.track_readiness_tracks = list(payload.get("tracks") or [])

        summary = payload.get("summary") or {}
        status_counts = summary.get("status_counts") or {}
        exact = int(status_counts.get("CURRENT_REQUIREMENTS_SATISFIED", 0))
        match_covered = int(
            status_counts.get("COVERED_BY_TRACK_MATCH_BASELINE", 0)
        )
        satisfied = exact + match_covered
        pending = max(0, int(summary.get("contexts", 0)) - satisfied)
        self.track_readiness_summary_var.set(
            f"{summary.get('tracks', 0)} circuitos · "
            f"{summary.get('contexts', 0)} contextos · "
            f"{exact} calibrados exactos · "
            f"{match_covered} con cobertura MATCH-only · "
            f"{pending} pendientes · "
            f"{summary.get('unresolved_sessions', 0)} sesiones sin contexto resoluble"
        )

        selected_track = None
        selection = self.track_readiness_tree.selection()
        if selection:
            try:
                selected_track = self.track_readiness_tracks[int(selection[0])]["track"]
            except (ValueError, IndexError, KeyError):
                selected_track = None

        for iid in self.track_readiness_tree.get_children():
            self.track_readiness_tree.delete(iid)

        selected_iid = None
        for index, track in enumerate(self.track_readiness_tracks):
            if track.get("profile_status") != "VALIDATED":
                tag = "track_profile_missing"
            elif int(track.get("pending_contexts") or 0) > 0:
                tag = "track_pending"
            else:
                tag = "track_ok"

            iid = str(index)
            self.track_readiness_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    track.get("track", "—"),
                    track.get("profile_status", "UNKNOWN"),
                    track.get("context_count", 0),
                    track.get("satisfied_contexts", 0),
                    track.get("pending_contexts", 0),
                    track.get("unresolved_sessions", 0),
                ),
                tags=(tag,),
            )
            if selected_track and track.get("track") == selected_track:
                selected_iid = iid

        if selected_iid is None and self.track_readiness_tracks:
            selected_iid = "0"

        if selected_iid is not None:
            self.track_readiness_tree.selection_set(selected_iid)
            self.track_readiness_tree.focus(selected_iid)
            self.track_readiness_tree.see(selected_iid)
            self._populate_track_readiness_contexts(
                self.track_readiness_tracks[int(selected_iid)]
            )
        else:
            self._populate_track_readiness_contexts(None)

    def _on_track_readiness_select(self, _event=None):
        selection = self.track_readiness_tree.selection()
        if not selection:
            self._populate_track_readiness_contexts(None)
            return
        try:
            track = self.track_readiness_tracks[int(selection[0])]
        except (ValueError, IndexError):
            self._populate_track_readiness_contexts(None)
            return
        self._populate_track_readiness_contexts(track)

    def _populate_track_readiness_contexts(self, track):
        for iid in self.track_context_tree.get_children():
            self.track_context_tree.delete(iid)

        if not isinstance(track, dict):
            self.track_readiness_detail_var.set(
                "Seleccioná un circuito para ver sus contextos."
            )
            return

        unresolved = int(track.get("unresolved_sessions") or 0)
        unresolved_text = (
            f" · {unresolved} sesiones sin layout resoluble" if unresolved else ""
        )
        self.track_readiness_detail_var.set(
            f"{track.get('track', 'Circuito')} · "
            f"profile {track.get('profile_status', 'UNKNOWN')} · "
            f"{track.get('context_count', 0)} contextos"
            f"{unresolved_text}"
        )

        for index, row in enumerate(list(track.get("contexts") or [])):
            action = row.get("next_action") or {}
            action_code = str(action.get("code") or "UNKNOWN")
            action_label = READINESS_ACTION_LABELS.get(action_code, action_code)
            status = str(row.get("overall_status") or "UNKNOWN")
            self.track_context_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    row.get("vehicle_variant", "—"),
                    row.get("sessions", 0),
                    f"{row.get('labeled_pairs', 0)}/{row.get('queue_pairs', 0)}",
                    row.get("matcher_status", "—"),
                    H3_IMPORT_STATUS_LABELS.get(
                        str(row.get("h3_import_status") or "H3_NOT_APPLICABLE"),
                        str(row.get("h3_import_status") or "—"),
                    ),
                    row.get("historical_status", "—"),
                    READINESS_STATUS_LABELS.get(status, status),
                    action_label,
                ),
                tags=(status,),
            )

    def _on_track_readiness_context_motion(self, event):
        iid = self.track_context_tree.identify_row(event.y)
        if not iid:
            self._hide_row_tooltip()
            return
        selection = self.track_readiness_tree.selection()
        if not selection:
            self._hide_row_tooltip()
            return
        try:
            track = self.track_readiness_tracks[int(selection[0])]
            row = list(track.get("contexts") or [])[int(iid)]
        except (ValueError, IndexError, KeyError):
            self._hide_row_tooltip()
            return
        self._show_row_tooltip(
            track_readiness_status_tooltip(row),
            event.x_root,
            event.y_root,
        )

    def _calibration_panel(self, parent):
        frame = self.ttk.Frame(parent, style="Panel.TFrame", padding=5)
        frame.pack(fill="both", expand=True)
        self.calibration_summary_var = self.tk.StringVar(value="")
        self.ttk.Label(
            frame,
            textvariable=self.calibration_summary_var,
            style="CardValue.TLabel",
            wraplength=960,
            justify="left",
        ).pack(fill="x", padx=4, pady=(0, 8))

        columns = ("context", "sessions", "labels", "evaluation", "matcher")
        tree = self.ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "context": "Contexto",
            "sessions": "Sesiones",
            "labels": "Labels",
            "evaluation": "Evaluación",
            "matcher": "Matcher",
        }
        widths = {
            "context": 420,
            "sessions": 70,
            "labels": 70,
            "evaluation": 150,
            "matcher": 260,
        }
        for name in columns:
            tree.heading(name, text=headings[name])
            tree.column(
                name,
                width=widths[name],
                minwidth=45,
                stretch=name in {"context", "matcher"},
            )
        scrollbar = self.ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        tree.bind("<Motion>", self._on_calibration_tree_motion)
        tree.bind("<Leave>", self._hide_row_tooltip)
        tree.bind("<Double-1>", self._on_calibration_tree_double_click)

        tree.tag_configure("row_even", background="#171717")
        tree.tag_configure("row_odd", background="#1b1f23")
        for tag, color in CALIBRATION_STATUS_COLORS.items():
            tree.tag_configure(tag, foreground=color)
        self.calibration_tree = tree
        self._refresh_calibration_summary()

        legend = self.ttk.Frame(frame, style="Panel.TFrame")
        legend.pack(fill="x", pady=(6, 0))
        for label, color in (
            ("Calibrado", CALIBRATION_STATUS_COLORS["CALIBRATED"]),
            ("Provisional", CALIBRATION_STATUS_COLORS["PROVISIONAL"]),
            ("Sin calibración", CALIBRATION_STATUS_COLORS["NO_CALIBRATION"]),
            ("Legacy", CALIBRATION_STATUS_COLORS["LEGACY"]),
            ("Bloqueado", CALIBRATION_STATUS_COLORS["BLOCKED"]),
        ):
            item = self.ttk.Label(
                legend,
                text=f"■ {label}",
                style="Muted.TLabel",
            )
            item.configure(foreground=color)
            item.pack(side="left", padx=(0, 14))
        return frame

    def _refresh_calibration_summary(self):
        tree = self.calibration_tree
        summary = load_calibration_summary(self.calibration_batches_root)
        rows = summary["rows"]
        self.calibration_rows = rows
        self.calibration_summary_var.set(
            f"{summary['calibrated_contexts']} contextos calibrados · "
            f"{summary['ready_datasets']} datasets listos · "
            f"{len(rows)} batches"
        )
        for iid in self.calibration_tree.get_children():
            self.calibration_tree.delete(iid)
        for index, row in enumerate(rows):
            evaluation = (
                f"{row['evaluation_pairs']} pares"
                if row["evaluation_status"] == "PASS"
                else row["evaluation_status"]
            )
            tag = calibration_status_tag(row["matcher_status"])
            tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    f"{row['track']} · {row['vehicle_variant']}",
                    row["sessions"],
                    f"{row['labeled_pairs']}/{row['queue_pairs']}",
                    evaluation,
                    row["matcher_status"],
                ),
                tags=(
                    "row_even" if index % 2 == 0 else "row_odd",
                    tag,
                ),
            )
        self._calibration_state_fingerprint = calibration_files_fingerprint(
            self.calibration_batches_root
        )

    def _on_calibration_tree_double_click(self, event):
        from tkinter import messagebox

        iid = self.calibration_tree.identify_row(event.y)
        if not iid:
            return

        self.calibration_tree.selection_set(iid)
        self.calibration_tree.focus(iid)

        try:
            row = self.calibration_rows[int(iid)]
        except (ValueError, IndexError):
            messagebox.showerror(
                "Race Engineer",
                "No se pudo resolver el batch seleccionado.",
                parent=self.root,
            )
            return

        try:
            target = resolve_calibration_labeling_target(
                self.calibration_batches_root,
                batch_id=str(row.get("batch_id") or ""),
            )
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror(
                "Race Engineer",
                f"No se puede abrir el labeler para este batch:\n\n{exc}",
                parent=self.root,
            )
            return

        if target.complete:
            messagebox.showinfo(
                "Race Engineer",
                (
                    f"El batch {target.batch_id} ya está completamente labelado "
                    f"({target.labeled_pairs}/{target.queue_pairs})."
                ),
                parent=self.root,
            )
            return

        try:
            launch_calibration_labeling_powershell(PROJECT_ROOT, target)
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror(
                "Race Engineer",
                f"No se pudo abrir PowerShell:\n\n{exc}",
                parent=self.root,
            )
            return

        self.footer_var.set(
            f"Labeling batch {target.batch_id}: "
            f"{target.labeled_pairs}/{target.queue_pairs} revisados"
        )

    def _on_calibration_tree_motion(self, event):
        iid = self.calibration_tree.identify_row(event.y)
        if not iid:
            self._hide_row_tooltip()
            return
        try:
            row = self.calibration_rows[int(iid)]
        except (ValueError, IndexError):
            return
        self._show_row_tooltip(
            calibration_status_tooltip(row["matcher_status"]),
            event.x_root,
            event.y_root,
        )

    def _readonly_pane(self, parent, header, *, side):
        pane = self.ttk.Frame(parent, style="Panel.TFrame")
        pane.pack(
            side=side,
            fill="both",
            expand=True,
            padx=(0, 6) if side == "left" else 0,
        )
        self.ttk.Label(pane, text=header, style="CardLabel.TLabel").pack(anchor="w")
        text = self.tk.Text(
            pane,
            wrap="word",
            background="#111418",
            foreground="#d8e3ea",
            insertbackground="#d8e3ea",
            relief="flat",
            padx=8,
            pady=6,
            height=8,
        )
        scroll = self.ttk.Scrollbar(pane, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.configure(state="disabled")
        return text

    def _set_comparison_view(self, view: dict, fallback_text: str):
        if not isinstance(view, dict) or not view.get("available"):
            self.comparison_summary_var.set("Comparación histórica no disponible")
            self._set_text(self.comparison_hist_text, "")
            self._set_text(self.comparison_current_text, "")
            self._set_text(self.comparison_detail_text, fallback_text)
            return
        summary, hist_text, current_text, detail_text = format_comparison_columns(
            view
        )
        self.comparison_summary_var.set(summary)
        self._set_text(self.comparison_hist_text, hist_text)
        self._set_text(self.comparison_current_text, current_text)
        self._set_text(self.comparison_detail_text, detail_text)

    def _on_tree_motion(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            self._hide_row_tooltip()
            return
        try:
            session = self.sessions[int(iid)]
        except (ValueError, IndexError):
            return
        self._show_row_tooltip(
            session_status_tooltip(session.status),
            event.x_root,
            event.y_root,
        )

    def _show_row_tooltip(self, text: str, x_root: int, y_root: int):
        self._hide_row_tooltip()
        tooltip = self.tk.Toplevel(self.root)
        tooltip.wm_overrideredirect(True)
        tooltip.wm_geometry(f"+{x_root + 14}+{y_root + 14}")
        self.ttk.Label(
            tooltip,
            text=text,
            style="CardValue.TLabel",
            padding=(8, 6),
        ).pack()
        self._row_tooltip = tooltip

    def _hide_row_tooltip(self, _event=None):
        if self._row_tooltip is not None:
            try:
                self._row_tooltip.destroy()
            except Exception:
                pass
            self._row_tooltip = None

    def _hide_plan_inspector(self):
        if not getattr(self, "inspector_visible", False):
            return
        self.inspector_frame.pack_forget()
        self.inspector_visible = False

    def _show_plan_inspector(self, item, index, focused=False):
        if not isinstance(item, dict):
            return

        location = item.get("track_location")
        if not isinstance(location, dict):
            location = {}

        title = str(
            location.get("label")
            or item.get("description")
            or f"Prioridad {index}"
        )

        label = str(item.get("plan_label") or index)
        kind = str(item.get("kind") or "plan_item")

        self.inspector_title_var.set(title)

        meta_parts = [f"P{index} · Zona {label}"]

        if focused:
            meta_parts.append("FOCUS")

        if kind == "repeated_region":
            meta_parts.append("PATRÓN REPETIDO")
        else:
            meta_parts.append(kind.replace("_", " ").upper())

        self.inspector_meta_var.set(" · ".join(meta_parts))

        lines = []

        start = item.get("start_distance_m")
        end = item.get("end_distance_m")

        if isinstance(start, (int, float)) or isinstance(end, (int, float)):
            lines.append(("section", "UBICACIÓN"))
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                lines.append(("value", f"{start:.0f}–{end:.0f} m"))
            elif isinstance(start, (int, float)):
                lines.append(("value", f"Desde {start:.0f} m"))
            else:
                lines.append(("value", f"Hasta {end:.0f} m"))

        priority_reason = item.get("priority_reason")
        if not isinstance(priority_reason, dict):
            priority_reason = {}

        comparison_count = priority_reason.get("comparison_count")

        if isinstance(comparison_count, int) and comparison_count > 0:
            lines.append(("section", "POR QUÉ ES PRIORIDAD"))
            provenance = []

            if priority_reason.get("repeated") is True:
                provenance.append("Patrón repetido")

            if comparison_count == 1:
                provenance.append("1 comparación válida")
            else:
                provenance.append(f"{comparison_count} comparaciones válidas")

            physical_anchor_types = priority_reason.get("physical_anchor_types")
            if not isinstance(physical_anchor_types, list):
                physical_anchor_types = []

            anchor_labels = {
                "braking_point": "punto de frenada",
                "brake_release": "liberación de freno",
                "throttle_onset": "inicio de acelerador",
                "throttle_release": "levantada de acelerador",
            }

            rendered_anchors = [
                anchor_labels[value]
                for value in physical_anchor_types
                if value in anchor_labels
            ]

            if rendered_anchors:
                provenance.append(
                    "Anchor físico: " + ", ".join(rendered_anchors)
                )

            for value in provenance:
                lines.append(("value", f"• {value}"))

        cues = item.get("driver_cues")
        if not isinstance(cues, list):
            cues = []

        cue_texts = []
        for cue in cues:
            if isinstance(cue, str):
                value = cue.strip()
            elif isinstance(cue, dict):
                value = str(
                    cue.get("text")
                    or cue.get("description")
                    or ""
                ).strip()
            else:
                value = ""

            if value:
                cue_texts.append(value)

        if cue_texts:
            lines.append(("section", "CUES"))
            for cue in cue_texts:
                lines.append(("value", f"• {cue}"))

        targets = item.get("targets")
        if not isinstance(targets, list):
            targets = []

        physical_targets = [
            item.get("braking_point_target"),
            item.get("brake_release_target"),
            item.get("throttle_onset_target"),
            item.get("throttle_release_target"),
        ]

        all_targets = []
        for target in [*targets, *physical_targets]:
            value = str(target or "").strip()
            if value and value not in all_targets:
                all_targets.append(value)

        if all_targets:
            lines.append(("section", "TARGETS AUTORIZADOS"))
            for target in all_targets:
                lines.append(("value", f"• {target}"))

        observations = item.get("observed_differences")
        if not isinstance(observations, list):
            observations = []

        observations = [
            str(value).strip()
            for value in observations
            if str(value or "").strip()
        ]

        if observations:
            lines.append(("section", "OBSERVADO"))
            for value in observations[:4]:
                lines.append(("value", f"• {value}"))

        physical_anchor_types = priority_reason.get("physical_anchor_types")
        if not isinstance(physical_anchor_types, list):
            physical_anchor_types = []

        if physical_anchor_types:
            lines.append(("section", "PATRONES FÍSICOS"))
            anchor_labels = {
                "braking_point": "Punto de frenada",
                "brake_release": "Liberación de freno",
                "throttle_onset": "Inicio de acelerador",
                "throttle_release": "Levantada de acelerador",
            }
            for value in physical_anchor_types:
                label_text = anchor_labels.get(value)
                if label_text:
                    lines.append(("value", label_text))

        actionable_count = priority_reason.get("actionable_cue_count")

        if isinstance(actionable_count, int):
            lines.append(("section", "COACHING"))
            lines.append(
                (
                    "value",
                    f"{actionable_count} cue autorizado"
                    if actionable_count == 1
                    else f"{actionable_count} cues autorizados",
                )
            )

        profiles = item.get("reference_action_profiles")
        if isinstance(profiles, list) and profiles:
            lines.append(("section", "REFERENCIA"))
            lines.append(
                (
                    "value",
                    f"{len(profiles)} perfil de acción de referencia"
                    if len(profiles) == 1
                    else f"{len(profiles)} perfiles de acción de referencia",
                )
            )

        if not lines:
            lines.append(
                (
                    "value",
                    "No hay metadata adicional para esta prioridad.",
                )
            )

        self.inspector_text.configure(state="normal")
        self.inspector_text.delete("1.0", "end")

        for tag, value in lines:
            self.inspector_text.insert(
                "end",
                value + "\n",
                tag,
            )

        self.inspector_text.configure(state="disabled")
        self.inspector_text.yview_moveto(0)

        if not self.inspector_visible:
            self.inspector_frame.pack(
                side="right",
                fill="y",
                padx=(10, 0),
            )
            self.inspector_visible = True

    def _build_next_stint_panel(self, parent, *, compact=False):
        container = self.ttk.Frame(
            parent,
            style="SummaryAccentCard.TFrame",
            padding=(14, 11) if compact else (16, 12),
        )
        container.pack(
            fill="both" if compact else "x",
            expand=compact,
            pady=(0, 0 if compact else 10),
        )

        self.ttk.Label(
            container,
            text="PRÓXIMA TANDA",
            style="SummaryAccentTitle.TLabel",
        ).pack(anchor="w")

        self.ttk.Label(
            container,
            text="Qué llevar a pista en el próximo stint",
            style="SummaryAccentSubtitle.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        cards = self.ttk.Frame(
            container,
            style="SummaryAccentCard.TFrame",
        )
        cards.pack(fill="x")

        self.plan_cards_host = cards
        self.plan_cards_compact = compact
        return container

    def _build_session_change_panel(self, parent, *, compact=False):
        container = self.ttk.Frame(
            parent,
            style="SummaryCard.TFrame",
            padding=(12, 10) if compact else (16, 12),
        )
        self.session_change_compact = compact
        self.session_change_title_var = self.tk.StringVar(value="INSPECTOR")
        self.ttk.Label(
            container,
            textvariable=self.session_change_title_var,
            style="SummaryTitle.TLabel",
            wraplength=250 if compact else 760,
            justify="left",
        ).pack(anchor="w")
        self.ttk.Label(
            container,
            text=(
                "Cambios vs. sesión comparable"
                if compact
                else "Contexto histórico de la sesión seleccionada"
            ),
            style="SummarySubtitle.TLabel",
            wraplength=250 if compact else 760,
            justify="left",
        ).pack(anchor="w", pady=(2, 8 if compact else 10))

        if compact:
            body = self.ttk.Frame(container, style="SummaryCard.TFrame")
            body.pack(fill="both", expand=True)

            canvas = self.tk.Canvas(
                body,
                background="#151d24",
                highlightthickness=0,
                borderwidth=0,
            )
            scrollbar = self.ttk.Scrollbar(
                body,
                orient="vertical",
                command=canvas.yview,
            )
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)

            host = self.ttk.Frame(canvas, style="SummaryCard.TFrame")
            window = canvas.create_window((0, 0), window=host, anchor="nw")
            host.bind(
                "<Configure>",
                lambda _event: canvas.configure(
                    scrollregion=canvas.bbox("all"),
                ),
            )
            canvas.bind(
                "<Configure>",
                lambda event: canvas.itemconfigure(window, width=event.width),
            )
            self.session_change_canvas = canvas
            self.session_change_host = host
        else:
            self.session_change_canvas = None
            self.session_change_host = self.ttk.Frame(
                container,
                style="SummaryCard.TFrame",
            )
            self.session_change_host.pack(fill="x")

        return container

    def _render_session_changes(self, view):
        for child in self.session_change_host.winfo_children():
            child.destroy()

        if self.session_change_compact:
            rows, hidden_changes = compact_session_change_rows(view)
        else:
            rows = session_change_rows(view)
            hidden_changes = 0
        self.session_change_title_var.set("INSPECTOR")
        self.session_change_panel.pack(
            fill="both" if self.session_change_compact else "x",
            expand=self.session_change_compact,
            pady=(0, 0 if self.session_change_compact else 10),
        )
        if not rows:
            self.ttk.Label(
                self.session_change_host,
                text=(
                    "Seleccioná una prioridad para abrir su detalle.\n\n"
                    "No hay una comparación histórica contextual disponible "
                    "para esta sesión."
                ),
                style="SummarySubtitle.TLabel",
                wraplength=230 if self.session_change_compact else 760,
                justify="left",
            ).pack(anchor="w", pady=(6, 0))
            return

        comparison_title = str(
            view.get("title") or "Cambios vs. última sesión comparable"
        )
        self.ttk.Label(
            self.session_change_host,
            text=comparison_title,
            style="CardValue.TLabel",
            wraplength=230 if self.session_change_compact else 760,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        for group_index, group in enumerate(rows):
            if group_index:
                self.ttk.Separator(
                    self.session_change_host,
                    orient="horizontal",
                ).pack(fill="x", pady=(8, 8))

            self.ttk.Label(
                self.session_change_host,
                text=group["location_label"],
                style="CardValue.TLabel",
            ).pack(anchor="w", pady=(0, 3))

            for change in group["changes"]:
                prefix = change["status_label"]
                label = change["presentation_label"]
                self.ttk.Label(
                    self.session_change_host,
                    text=f"{prefix} · {label}",
                    style=(
                        "Muted.TLabel"
                        if change["structured"]
                        else "SummarySubtitle.TLabel"
                    ),
                    wraplength=230 if self.session_change_compact else 760,
                    justify="left",
                ).pack(
                    anchor="w",
                    padx=(8 if self.session_change_compact else 12, 0),
                    pady=(1, 1),
                )

        if hidden_changes:
            self.ttk.Label(
                self.session_change_host,
                text=f"+ {hidden_changes} cambios más en Historial",
                style="SummaryAccentSubtitle.TLabel",
                justify="left",
            ).pack(anchor="w", pady=(9, 2))

        if self.session_change_canvas is not None:
            self.session_change_canvas.update_idletasks()
            self.session_change_canvas.configure(
                scrollregion=self.session_change_canvas.bbox("all"),
            )
            self.session_change_canvas.yview_moveto(0.0)

    def _cancel_session_change_request(self):
        self.session_change_token += 1
        after_id = self.session_change_after_id
        self.session_change_after_id = None
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass

    def _request_session_change_view(self, record):
        self._cancel_session_change_request()
        cached = self.session_change_cache.get(record.session_key)
        if cached is not None:
            self._render_session_changes(cached)
            return

        token = self.session_change_token
        sessions = list(self.all_sessions)
        self.session_change_after_id = self.root.after(
            180,
            lambda: self._start_session_change_worker(
                token,
                record,
                sessions,
            ),
        )

    def _start_session_change_worker(self, token, record, sessions):
        self.session_change_after_id = None
        if self._closing or token != self.session_change_token:
            return

        def worker():
            try:
                view = build_session_change_view(record, sessions)
                self.session_change_queue.put((token, record.session_key, view))
            except Exception as exc:
                self.session_change_queue.put((token, "error", exc))

        threading.Thread(
            target=worker,
            name="race-engineer-session-change",
            daemon=True,
        ).start()
        self.root.after(50, lambda: self._poll_session_change_queue(token))

    def _poll_session_change_queue(self, token):
        if self._closing or token != self.session_change_token:
            return
        try:
            result_token, session_key, value = self.session_change_queue.get_nowait()
        except queue.Empty:
            self.root.after(50, lambda: self._poll_session_change_queue(token))
            return
        if result_token != token:
            self.root.after(0, lambda: self._poll_session_change_queue(token))
            return
        if session_key == "error":
            self._render_session_changes({"status": "UNAVAILABLE"})
            return
        self.session_change_cache[session_key] = value
        self._render_session_changes(value)

    def _render_next_stint_cards(self, detail):
        self._hide_plan_inspector()

        for child in self.plan_cards_host.winfo_children():
            child.destroy()

        items = tuple(detail.plan_items or ())

        if not items:
            self.ttk.Label(
                self.plan_cards_host,
                text=detail.plan_text or "No hay un plan de próxima tanda disponible.",
                style="SummaryAccentSubtitle.TLabel",
                wraplength=760,
                justify="left",
            ).pack(fill="x", pady=(4, 6))
            return

        focus_labels = set(detail.focus_plan_labels or ())

        for index, item in enumerate(items[:3], start=1):
            label = str(item.get("plan_label") or index)

            location = item.get("track_location")
            if not isinstance(location, dict):
                location = {}

            title = str(
                location.get("label")
                or item.get("description")
                or "Zona sin nombre"
            )

            card = self.ttk.Frame(
                self.plan_cards_host,
                style="PriorityCard.TFrame",
                padding=(
                    (10, 7)
                    if getattr(self, "plan_cards_compact", False)
                    else (12, 10)
                ),
            )
            card.pack(fill="x", pady=(0, 7))

            is_focused = label in focus_labels

            def open_inspector(_event=None, value=item, number=index, focus=is_focused):
                self._show_plan_inspector(
                    value,
                    number,
                    focused=focus,
                )

            card.bind("<Button-1>", open_inspector)
            card.configure(cursor="hand2")

            top = self.ttk.Frame(card, style="PriorityCard.TFrame")
            top.bind("<Button-1>", open_inspector)
            top.configure(cursor="hand2")
            top.pack(fill="x")

            index_label = self.ttk.Label(
                top,
                text=f"P{index}",
                style="PriorityIndex.TLabel",
                cursor="hand2",
            )
            index_label.pack(side="left")
            index_label.bind("<Button-1>", open_inspector)

            title_label = self.ttk.Label(
                top,
                text=title,
                style="PriorityTitle.TLabel",
                cursor="hand2",
            )
            title_label.pack(side="left", padx=(10, 0))
            title_label.bind("<Button-1>", open_inspector)

            if label in focus_labels:
                focus_label = self.ttk.Label(
                    top,
                    text="FOCUS",
                    style="PriorityFocus.TLabel",
                    cursor="hand2",
                )
                focus_label.pack(side="right")
                focus_label.bind("<Button-1>", open_inspector)

            cues = item.get("driver_cues")
            if not isinstance(cues, list):
                cues = []

            cue_texts = []
            cue_limit = 1 if getattr(self, "plan_cards_compact", False) else 2
            for cue in cues[:cue_limit]:
                if isinstance(cue, str):
                    value = cue.strip()
                elif isinstance(cue, dict):
                    value = str(
                        cue.get("text")
                        or cue.get("description")
                        or ""
                    ).strip()
                else:
                    value = ""

                if value:
                    cue_texts.append(value)

            if not cue_texts:
                cue_texts = ["Sin cue de conducción autorizado."]

            for cue in cue_texts:
                cue_label = self.ttk.Label(
                    card,
                    text=f"• {cue}",
                    style="PriorityCue.TLabel",
                    wraplength=760,
                    justify="left",
                    cursor="hand2",
                )
                cue_label.pack(anchor="w", pady=(5, 0))
                cue_label.bind("<Button-1>", open_inspector)

    def _summary_text_panel(
        self,
        parent,
        header,
        *,
        subtitle="",
        height=8,
        expand=False,
        accent=False,
        compact=False,
    ):
        container = self.ttk.Frame(
            parent,
            style=(
                "SummaryAccentCard.TFrame"
                if accent
                else "SummaryCard.TFrame"
            ),
            padding=(14, 11) if compact else (16, 12),
        )
        container.pack(
            fill="both" if expand else "x",
            expand=expand,
            pady=(0, 0 if compact else 10),
        )

        heading = self.ttk.Frame(
            container,
            style=(
                "SummaryAccentCard.TFrame"
                if accent
                else "SummaryCard.TFrame"
            ),
        )
        heading.pack(fill="x", pady=(0, 8))

        self.ttk.Label(
            heading,
            text=header,
            style=(
                "SummaryAccentTitle.TLabel"
                if accent
                else "SummaryTitle.TLabel"
            ),
        ).pack(anchor="w")

        if subtitle:
            self.ttk.Label(
                heading,
                text=subtitle,
                style=(
                    "SummaryAccentSubtitle.TLabel"
                    if accent
                    else "SummarySubtitle.TLabel"
                ),
            ).pack(anchor="w", pady=(2, 0))

        body = self.ttk.Frame(
            container,
            style=(
                "SummaryAccentCard.TFrame"
                if accent
                else "SummaryCard.TFrame"
            ),
        )
        body.pack(fill="both", expand=True)

        text = self.tk.Text(
            body,
            wrap="word",
            height=height,
            background="#141c23" if not accent else "#14211f",
            foreground="#dce7ef",
            insertbackground="#00FFA6",
            selectbackground="#315b60",
            selectforeground="#f4fbff",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=10 if compact else 14,
            pady=8 if compact else 12,
            font=("Segoe UI", 9 if compact else 10),
            spacing1=1 if compact else 2,
            spacing3=3 if compact else 4,
        )

        text.tag_configure(
            "h1",
            font=("Segoe UI Semibold", 18),
            foreground="#f2f7fb",
            spacing3=12,
        )
        text.tag_configure(
            "h2",
            font=("Segoe UI Semibold", 12 if compact else 14),
            foreground="#00FFA6",
            spacing1=9 if compact else 12,
            spacing3=5 if compact else 7,
        )
        text.tag_configure(
            "h3",
            font=("Segoe UI Semibold", 11),
            foreground="#f2f7fb",
            spacing1=8,
        )
        text.tag_configure(
            "bullet",
            lmargin1=18,
            lmargin2=32,
        )

        if not compact:
            scrollbar = self.ttk.Scrollbar(
                body,
                orient="vertical",
                command=text.yview,
            )
            text.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")

        text.pack(side="left", fill="both", expand=True)
        text.configure(state="disabled")

        return text

    def _text_tab(self, notebook, label):
        frame = self.ttk.Frame(notebook, style="Panel.TFrame", padding=5)
        notebook.add(frame, text=label)
        text = self.tk.Text(
            frame,
            wrap="word",
            background="#15181c",
            foreground="#dce7ef",
            insertbackground="#00FFA6",
            selectbackground="#315b60",
            selectforeground="#f4fbff",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=18,
            pady=16,
            font=("Segoe UI", 10),
            spacing1=2,
            spacing3=4,
        )
        text.tag_configure("h1", font=("Segoe UI Semibold", 18), foreground="#f2f7fb", spacing3=12)
        text.tag_configure("h2", font=("Segoe UI Semibold", 14), foreground="#00FFA6", spacing1=12, spacing3=7)
        text.tag_configure("h3", font=("Segoe UI Semibold", 11), foreground="#f2f7fb", spacing1=8)
        text.tag_configure("bullet", lmargin1=18, lmargin2=32)
        scrollbar = self.ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.configure(state="disabled")
        return text

    def _track_map_tab(self, parent, *, label="Mapa"):
        frame = self.ttk.Frame(parent, style="Panel.TFrame", padding=8)
        if label is not None:
            parent.add(frame, text=label)
        else:
            frame.pack(fill="both", expand=True)
        self.track_map_status = self.tk.StringVar(
            value="Seleccioná una sesión para reconstruir el mapa GPS."
        )
        self.ttk.Label(
            frame,
            textvariable=self.track_map_status,
            style="Muted.TLabel",
        ).pack(fill="x", padx=8, pady=(4, 8))
        telemetry_split = self.ttk.Panedwindow(frame, orient="vertical")
        telemetry_split.pack(fill="both", expand=True)
        self.track_telemetry_split = telemetry_split
        map_panel = self.ttk.Frame(telemetry_split, style="Panel.TFrame")
        channels_panel = self.ttk.Frame(telemetry_split, style="Panel.TFrame")
        telemetry_split.add(map_panel, weight=3)
        telemetry_split.add(channels_panel, weight=2)

        canvas = self.tk.Canvas(
            map_panel,
            background="#0b0e10",
            highlightthickness=1,
            highlightbackground="#2d343a",
        )
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Configure>", lambda _event: self._render_track_map())
        canvas.configure(cursor="crosshair")
        canvas.bind("<ButtonPress-1>", self._on_track_map_press)
        canvas.bind("<B1-Motion>", self._on_track_map_drag)
        canvas.bind("<ButtonRelease-1>", self._on_track_map_release)
        canvas.bind("<MouseWheel>", self._on_track_map_mousewheel)
        canvas.bind("<ButtonPress-3>", self._on_track_map_pan_press)
        canvas.bind("<B3-Motion>", self._on_track_map_pan_drag)
        canvas.bind("<ButtonRelease-3>", self._on_track_map_pan_release)
        map_zoom_controls = self.ttk.Frame(map_panel, style="Panel.TFrame")
        map_zoom_controls.pack(fill="x", pady=(4, 0))
        self.track_map_zoom_status = self.tk.StringVar(
            value="Mapa completo · rueda: zoom · botón derecho: desplazar"
        )
        self.ttk.Label(
            map_zoom_controls,
            textvariable=self.track_map_zoom_status,
            style="Muted.TLabel",
        ).pack(side="left")
        self.track_map_zoom_reset_button = self.ttk.Button(
            map_zoom_controls,
            text="Restablecer mapa",
            command=self._reset_track_map_zoom,
            state="disabled",
        )
        self.track_map_zoom_reset_button.pack(side="right")
        turn_controls = self.ttk.Frame(map_panel, style="Panel.TFrame")
        turn_controls.pack(fill="x", pady=(4, 0))
        self.ttk.Label(
            turn_controls,
            text="Navegación:",
            style="Muted.TLabel",
        ).pack(side="left")
        self.show_track_profile_var = self.tk.BooleanVar(value=False)
        self.track_profile_layer_check = self.ttk.Checkbutton(
            turn_controls,
            text="Curvas",
            variable=self.show_track_profile_var,
            command=self._render_track_map,
            state="disabled",
        )
        self.track_profile_layer_check.pack(side="left", padx=(10, 0))
        self.track_turn_selector_var = self.tk.StringVar(value="Elegir curva…")
        self.track_turn_selector = self.ttk.Combobox(
            turn_controls,
            textvariable=self.track_turn_selector_var,
            state="disabled",
            width=24,
        )
        self.track_turn_selector.pack(side="left", padx=(8, 12))
        self.track_turn_selector.bind(
            "<<ComboboxSelected>>",
            self._on_track_turn_selected,
        )
        self.track_plan_selector_var = self.tk.StringVar(
            value="Elegir zona del plan…"
        )
        self.track_plan_selector = self.ttk.Combobox(
            turn_controls,
            textvariable=self.track_plan_selector_var,
            state="disabled",
            width=28,
        )
        self.track_plan_selector.pack(side="left", padx=(0, 8))
        self.track_plan_selector.bind(
            "<<ComboboxSelected>>",
            self._on_track_plan_selected,
        )
        playback_controls = self.ttk.Frame(map_panel, style="Panel.TFrame")
        playback_controls.pack(fill="x", pady=(4, 0))
        self.ttk.Label(
            playback_controls,
            text="Playback:",
            style="Muted.TLabel",
        ).pack(side="left")
        self.track_rewind_button = self.ttk.Button(
            playback_controls,
            text="⏮ Inicio",
            command=self._on_track_rewind,
            state="disabled",
        )
        self.track_rewind_button.pack(side="left", padx=(8, 6))
        self.track_play_button = self.ttk.Button(
            playback_controls,
            text="▶ Play",
            command=self._on_track_play_toggle,
            state="disabled",
            style="Accent.TButton",
        )
        self.track_play_button.pack(side="left", padx=(0, 12))
        self.ttk.Label(
            playback_controls,
            text="Resolución:",
            style="Muted.TLabel",
        ).pack(side="left", padx=(18, 6))
        self.track_resolution_var = self.tk.StringVar(value="20 Hz")
        self.track_resolution_selector = self.ttk.Combobox(
            playback_controls,
            textvariable=self.track_resolution_var,
            values=("20 Hz", "10 Hz", "50 Hz"),
            state="readonly",
            width=7,
        )
        self.track_resolution_selector.pack(side="left")
        self.track_resolution_selector.bind(
            "<<ComboboxSelected>>",
            self._on_track_resolution_changed,
        )
        lap_controls = self.ttk.Frame(channels_panel, style="Panel.TFrame")
        lap_controls.pack(fill="x", padx=8, pady=(8, 2))
        self.ttk.Label(
            lap_controls,
            text="Vuelta mostrada:",
            style="Muted.TLabel",
        ).pack(side="left")
        self.track_lap_selector_var = self.tk.StringVar(value="—")
        self.track_lap_selector = self.ttk.Combobox(
            lap_controls,
            textvariable=self.track_lap_selector_var,
            state="disabled",
            width=20,
        )
        self.track_lap_selector.pack(side="left", padx=(8, 16))
        self.track_lap_selector.bind(
            "<<ComboboxSelected>>",
            self._on_track_lap_selected,
        )
        self.track_reference_lap_var = self.tk.StringVar(value="Referencia: —")
        self.ttk.Label(
            lap_controls,
            textvariable=self.track_reference_lap_var,
            style="Muted.TLabel",
        ).pack(side="left")
        self.ttk.Label(
            lap_controls,
            text="Comparar con:",
            style="Muted.TLabel",
        ).pack(side="left", padx=(24, 6))
        self.track_comparison_var = self.tk.StringVar(value="Referencia sesión")
        self.track_comparison_selector = self.ttk.Combobox(
            lap_controls,
            textvariable=self.track_comparison_var,
            values=("Referencia sesión", "History H4", "Sin comparación"),
            state="readonly",
            width=19,
        )
        self.track_comparison_selector.pack(side="left")
        self.track_comparison_selector.bind(
            "<<ComboboxSelected>>",
            self._on_track_comparison_changed,
        )

        self.track_map_zone_status = self.tk.StringVar(
            value="Sin zonas H5.2 para esta sesión."
        )
        self.track_map_zone_label = self.ttk.Label(
            channels_panel,
            textvariable=self.track_map_zone_status,
            style="Muted.TLabel",
            wraplength=960,
            justify="left",
        )
        self.track_map_zone_label.pack(fill="x", padx=8, pady=(8, 4))
        self.track_map_telemetry_status = self.tk.StringVar(
            value="Hacé clic en el trazado para inspeccionar velocidad, freno y acelerador."
        )
        self.track_map_telemetry_label = self.ttk.Label(
            channels_panel,
            textvariable=self.track_map_telemetry_status,
            style="Muted.TLabel",
            wraplength=960,
            justify="left",
        )
        self.track_map_telemetry_label.pack(fill="x", padx=8, pady=(0, 4))
        frame.bind("<Configure>", self._on_track_detail_resize, add="+")
        telemetry_canvas = self.tk.Canvas(
            channels_panel,
            height=210,
            background="#111418",
            highlightthickness=1,
            highlightbackground="#2d343a",
        )
        telemetry_canvas.pack(fill="both", expand=True, padx=0, pady=(4, 0))
        telemetry_canvas.configure(cursor="crosshair")
        telemetry_canvas.bind(
            "<Configure>", lambda _event: self._render_track_telemetry_chart()
        )
        telemetry_canvas.bind("<ButtonPress-1>", self._on_telemetry_press)
        telemetry_canvas.bind("<B1-Motion>", self._on_telemetry_drag)
        telemetry_canvas.bind("<ButtonRelease-1>", self._on_telemetry_release)
        telemetry_canvas.bind("<MouseWheel>", self._on_telemetry_mousewheel)
        self.track_telemetry_canvas = telemetry_canvas
        zoom_controls = self.ttk.Frame(channels_panel, style="Panel.TFrame")
        zoom_controls.pack(fill="x", pady=(4, 0))
        self.telemetry_zoom_status = self.tk.StringVar(
            value="Gráfico completo · rueda: zoom · Shift+rueda: desplazar"
        )
        self.ttk.Label(
            zoom_controls,
            textvariable=self.telemetry_zoom_status,
            style="Muted.TLabel",
        ).pack(side="left")
        self.telemetry_zoom_reset_button = self.ttk.Button(
            zoom_controls,
            text="Restablecer gráfico",
            command=self._reset_telemetry_zoom,
            state="disabled",
        )
        self.telemetry_zoom_reset_button.pack(side="right")
        return canvas

    def _set_track_lap_options(
        self,
        options: tuple[TrackMapLapOption, ...],
        *,
        reference_lap: int | None,
        selected_lap: int | None = None,
    ) -> None:
        self.current_track_lap_options = tuple(options)
        self.track_lap_lookup = {
            f"V{option.lap} · {format_lap_time(option.duration_s)}": option
            for option in options
        }
        values = tuple(self.track_lap_lookup)
        self.track_lap_selector.configure(
            values=values,
            state="readonly" if values else "disabled",
        )
        target_lap = selected_lap if selected_lap is not None else reference_lap
        selected_label = next(
            (
                label
                for label, option in self.track_lap_lookup.items()
                if option.lap == target_lap
            ),
            values[0] if values else "—",
        )
        self.track_lap_selector_var.set(selected_label)
        reference_option = next(
            (option for option in options if option.lap == reference_lap),
            None,
        )
        if reference_option is None:
            self.track_reference_lap_var.set(
                f"Referencia: V{reference_lap}"
                if reference_lap is not None
                else "Referencia: —"
            )
        else:
            self.track_reference_lap_var.set(
                f"Referencia: V{reference_option.lap} · "
                f"{format_lap_time(reference_option.duration_s)}"
            )

    def _clear_track_lap_options(self) -> None:
        self.current_track_lap_options = ()
        self.track_lap_lookup = {}
        if hasattr(self, "track_lap_selector"):
            self.track_lap_selector.configure(values=(), state="disabled")
            self.track_lap_selector_var.set("—")
            self.track_reference_lap_var.set("Referencia: —")

    def _on_track_comparison_changed(self, _event=None):
        self._render_track_telemetry_chart()

    def _on_track_lap_selected(self, _event=None):
        option = self.track_lap_lookup.get(self.track_lap_selector_var.get())
        record = self.current_track_record
        reference = self.current_session_reference_track_map
        if option is None or record is None or record.database_path is None:
            return
        reference_lap = (
            None
            if reference is None
            else (reference.requested_lap or reference.lap)
        )
        if reference is not None and option.lap == reference_lap:
            self.manual_track_map_loading = False
            self.current_track_map = reference
            self.selected_track_point_index = None
            self.telemetry_zoom_range = None
            self.track_map_zoom_scale = 1.0
            self.track_map_zoom_offset = (0.0, 0.0)
            self._set_telemetry_zoom_status()
            self._set_track_map_zoom_status()
            self.track_map_status.set(
                self._track_map_status_text(
                    reference,
                    resolution_hz=self.track_resolution_hz,
                )
            )
            self._render_track_map()
            return
        self._start_manual_track_lap_request(record, option)

    def _start_manual_track_lap_request(
        self,
        record: SessionRecord,
        option: TrackMapLapOption,
    ) -> None:
        database = record.database_path
        if database is None:
            return
        try:
            resolved = database.expanduser().resolve()
            modified_ns = resolved.stat().st_mtime_ns
        except OSError:
            return
        token = self.track_map_token
        cache_key = (
            str(resolved),
            modified_ns,
            option.lap,
            None,
            self.track_resolution_hz,
        )
        cached = self.track_map_cache.get(cache_key)
        if cached is not None:
            self.track_map_preserve_visual_token = None
            self.current_track_map = cached
            self.manual_track_map_loading = False
            self.selected_track_point_index = None
            self.telemetry_zoom_range = None
            self.track_map_zoom_scale = 1.0
            self.track_map_zoom_offset = (0.0, 0.0)
            self._set_telemetry_zoom_status()
            self._set_track_map_zoom_status()
            self.track_map_status.set(
                f"Vuelta seleccionada V{option.lap} · "
                f"{format_lap_time(cached.duration_s)} · "
                f"{self.track_resolution_hz:.0f} Hz"
            )
            self._render_track_map()
            return

        self.manual_track_map_loading = True
        self.track_map_status.set(
            f"Cargando vuelta V{option.lap} para comparar con la referencia…"
        )

        def worker():
            try:
                data = load_track_map(
                    resolved,
                    preferred_lap=option.lap,
                    preferred_duration_s=None,
                    target_hz=self.track_resolution_hz,
                )
                self.track_map_queue.put(
                    (token, "manual_lap_done", (cache_key, data, option))
                )
            except Exception as exc:
                self.track_map_queue.put(
                    (token, "manual_lap_error", f"{type(exc).__name__}: {exc}")
                )

        threading.Thread(
            target=worker,
            name="race-engineer-manual-track-lap",
            daemon=True,
        ).start()
        self.root.after(100, self._poll_track_map_queue)

    def _on_track_detail_resize(self, event):
        wraplength = status_wraplength(event.width)
        self.track_map_zone_label.configure(wraplength=wraplength)
        self.track_map_telemetry_label.configure(wraplength=wraplength)

    def _show_dashboard_text_detail(self, title: str, value: str, *, markdown: bool = False):
        window = self.tk.Toplevel(self.root)
        window.title(title)
        window.geometry("820x700")
        window.minsize(620, 440)
        window.configure(background="#0b1116")
        frame = self.ttk.Frame(window, style="Panel.TFrame", padding=16)
        frame.pack(fill="both", expand=True)
        self.ttk.Label(frame, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        text = self.tk.Text(
            frame,
            wrap="word",
            background="#141c23",
            foreground="#dce7ef",
            insertbackground="#00FFA6",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=16,
            pady=14,
            font=("Segoe UI", 10),
            spacing1=2,
            spacing3=4,
        )
        text.tag_configure("h1", font=("Segoe UI Semibold", 18), foreground="#f2f7fb", spacing3=12)
        text.tag_configure("h2", font=("Segoe UI Semibold", 14), foreground="#00FFA6", spacing1=12, spacing3=7)
        text.tag_configure("h3", font=("Segoe UI Semibold", 11), foreground="#f2f7fb", spacing1=8)
        text.tag_configure("bullet", lmargin1=18, lmargin2=32)
        scrollbar = self.ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        self._set_text(text, value, markdown=markdown)
        return window

    def _show_full_debrief(self):
        self._show_dashboard_text_detail(
            "Debrief completo",
            self.current_debrief_markdown or "No hay debrief disponible.",
            markdown=True,
        )

    def _show_full_laps(self):
        self._show_dashboard_text_detail(
            "Análisis de vueltas",
            self.current_laps_text or "No hay análisis de vueltas disponible.",
        )

    def _set_text(self, widget, value: str, *, markdown: bool = False):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for line in value.splitlines() or [""]:
            tag = None
            clean = line
            if markdown:
                if line.startswith("### "):
                    tag, clean = "h3", line[4:]
                elif line.startswith("## "):
                    tag, clean = "h2", line[3:]
                elif line.startswith("# "):
                    tag, clean = "h1", line[2:]
                elif line.startswith("- "):
                    tag, clean = "bullet", "• " + line[2:]
                clean = _clean_markdown_line(clean)
            widget.insert("end", clean + "\n", tag)
        widget.configure(state="disabled")
        widget.yview_moveto(0)

    def _append_execution_line(self, value: str):
        self.execution_text.configure(state="normal")
        self.execution_text.insert("end", value + "\n")
        self.execution_text.see("end")
        self.execution_text.configure(state="disabled")

    def refresh(self, *, preferred_database: Path | None = None):
        self._refresh_h5_3_review_status()
        self._refresh_scheduler_status()
        self._refresh_calibration_summary()
        previous = self.selected_record()
        previous_key = previous.session_key if previous else None
        self.all_sessions, errors = discover_sessions(self.runs_root)
        self._cancel_session_change_request()
        self.session_change_cache.clear()
        self.session_read_errors = errors
        self._populate_session_tree(
            errors=errors,
            preferred_database=preferred_database,
            previous_key=previous_key,
        )
        self._state_files_fingerprint = state_files_fingerprint(self.runs_root)
        self._scheduler_state_fingerprint = self._scheduler_fingerprint()

    def _schedule_state_refresh_check(self):
        if self._closing or self._state_refresh_after_id is not None:
            return
        self._state_refresh_after_id = self.root.after(
            STATE_REFRESH_INTERVAL_MS,
            self._check_for_state_updates,
        )

    def _check_for_state_updates(self):
        self._state_refresh_after_id = None
        if self._closing:
            return
        try:
            if not self.analysis_running:
                current = state_files_fingerprint(self.runs_root)
                if current != self._state_files_fingerprint:
                    self.refresh()
                else:
                    scheduler_current = self._scheduler_fingerprint()
                    if scheduler_current != self._scheduler_state_fingerprint:
                        self._refresh_scheduler_status()
                        self._scheduler_state_fingerprint = scheduler_current
                    calibration_current = calibration_files_fingerprint(
                        self.calibration_batches_root
                    )
                    if calibration_current != self._calibration_state_fingerprint:
                        self._refresh_calibration_summary()
        finally:
            self._schedule_state_refresh_check()

    def _refresh_h5_3_review_status(self):
        status = load_h5_3_review_status(self.h5_3_review_state_path)
        self.h5_3_review_var.set(status.text)
        self.h5_3_review_label.configure(style=status.style)
        self.h5_3_review_label.configure(cursor="hand2" if "json" in status.detail else "")
        self.h5_3_review_label.bind(
            "<Button-1>",
            lambda _event, detail=status.detail: self.footer_var.set(detail),
        )

    def _refresh_scheduler_status(self):
        status = load_scheduler_status(
            self.telemetry_ingest_state_path,
            self.scheduler_runtime_path,
        )
        self.scheduler_var.set(status.text)
        self.scheduler_label.configure(style=status.style, cursor="hand2")
        self.scheduler_label.bind(
            "<Button-1>",
            self._show_scheduler_diagnostics,
        )

    def _scheduler_fingerprint(self):
        return (
            file_fingerprint(self.telemetry_ingest_state_path),
            file_fingerprint(self.scheduler_runtime_path),
        )

    def _scheduler_diagnostic_text(self) -> str:
        return scheduler_diagnostic_report(
            self.telemetry_ingest_state_path,
            self.scheduler_runtime_path,
            self.scheduler_log_path,
        )

    def _show_scheduler_diagnostics(self, _event=None):
        existing = self.scheduler_diagnostic_window
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    return
            except self.tk.TclError:
                pass

        window = self.tk.Toplevel(self.root)
        self.scheduler_diagnostic_window = window
        window.title("Diagnóstico del scheduler")
        window.geometry("820x560")
        window.minsize(580, 380)
        window.configure(background="#101010")
        window.transient(self.root)

        container = self.ttk.Frame(window, style="Panel.TFrame", padding=16)
        container.pack(fill="both", expand=True)
        self.ttk.Label(
            container,
            text="Scheduler e ingest automático",
            style="Title.TLabel",
        ).pack(anchor="w")
        self.ttk.Label(
            container,
            text=(
                "Diagnóstico de solo lectura. Ninguna acción de esta ventana "
                "modifica la cola."
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        report = self._scheduler_diagnostic_text()
        scheduler_status = load_scheduler_status(
            self.telemetry_ingest_state_path,
            self.scheduler_runtime_path,
        )
        text_widget = self.tk.Text(
            container,
            wrap="word",
            background="#171717",
            foreground="#e6edf3",
            insertbackground="#e6edf3",
            relief="flat",
            padx=12,
            pady=10,
        )
        text_widget.pack(fill="both", expand=True)
        text_widget.insert("1.0", report)
        text_widget.configure(state="disabled")

        buttons = self.ttk.Frame(container, style="Panel.TFrame")
        buttons.pack(fill="x", pady=(12, 0))
        self.ttk.Button(
            buttons,
            text="Copiar diagnóstico",
            command=lambda: self._copy_scheduler_diagnostics(report),
        ).pack(side="left")
        self.ttk.Button(
            buttons,
            text="Abrir log",
            command=self._open_scheduler_log,
        ).pack(side="left", padx=(8, 0))
        if (
            scheduler_status.blocked_path
            and scheduler_status.code not in {"SCHEDULER_RUNNING", "SCHEDULER_STALLED"}
        ):
            self.ttk.Button(
                buttons,
                text="Posponer sesión bloqueante",
                command=lambda path=scheduler_status.blocked_path: (
                    self._defer_scheduler_session(path, window)
                ),
            ).pack(side="left", padx=(8, 0))
        elif (
            scheduler_status.deferred_paths
            and scheduler_status.code not in {"SCHEDULER_RUNNING", "SCHEDULER_STALLED"}
        ):
            self.ttk.Button(
                buttons,
                text="Reactivar sesión pospuesta",
                command=lambda path=scheduler_status.deferred_paths[0]: (
                    self._resume_scheduler_session(path, window)
                ),
            ).pack(side="left", padx=(8, 0))
        self.ttk.Button(
            buttons,
            text="Cerrar",
            command=window.destroy,
        ).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def _copy_scheduler_diagnostics(self, report: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        self.root.update_idletasks()
        self.footer_var.set("Diagnóstico del scheduler copiado al portapapeles.")

    def _open_scheduler_log(self):
        from tkinter import messagebox

        try:
            _open_file(self.scheduler_log_path)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror("Race Engineer", str(exc), parent=self.root)

    def _defer_scheduler_session(self, database_path: str, window):
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Liberar cola del scheduler",
            (
                f"¿Posponer {Path(database_path).name}?\n\n"
                "La sesión seguirá guardada en History y conservará el error. "
                "El scheduler podrá continuar con la siguiente."
            ),
            parent=window,
        ):
            return
        try:
            defer_blocking_debrief(
                self.telemetry_ingest_state_path,
                database_path,
                runtime_path=self.scheduler_runtime_path,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("Race Engineer", str(exc), parent=window)
            return
        window.destroy()
        self.refresh()
        self.footer_var.set("Sesión pospuesta; la cola puede continuar.")

    def _resume_scheduler_session(self, database_path: str, window):
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Reactivar debrief",
            (
                f"¿Reactivar {Path(database_path).name}?\n\n"
                "Volverá al final de la cola con sus errores anteriores conservados."
            ),
            parent=window,
        ):
            return
        try:
            resume_deferred_debrief(
                self.telemetry_ingest_state_path,
                database_path,
                runtime_path=self.scheduler_runtime_path,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("Race Engineer", str(exc), parent=window)
            return
        window.destroy()
        self.refresh()
        self.footer_var.set("Sesión reactivada al final de la cola.")

    def _apply_session_filters(self, _event=None):
        previous = self.selected_record()
        self._populate_session_tree(
            errors=self.session_read_errors,
            previous_key=previous.session_key if previous else None,
        )

    def _populate_session_tree(
        self,
        *,
        errors: list[str],
        preferred_database: Path | None = None,
        previous_key: str | None = None,
    ):
        status_filter = SESSION_FILTER_LABELS[self.session_filter_var.get()]
        self.sessions = filter_sessions(
            self.all_sessions,
            query=self.session_query_var.get(),
            status_filter=status_filter,
        )
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, session in enumerate(self.sessions):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    format_timestamp(session.timestamp_utc, session.modified_timestamp),
                    session.track,
                    session.vehicle,
                    session.valid_lap_count,
                    format_lap_time(session.reference_time_s),
                    session.status_detail,
                ),
                tags=("row_even" if index % 2 == 0 else "row_odd", session.status),
            )
        self.tree.tag_configure("row_even", background="#171717")
        self.tree.tag_configure("row_odd", background="#1b1f23")
        for status in SESSION_STATUS_COLORS:
            self.tree.tag_configure(status, foreground=session_status_color(status))
        self.count_var.set(
            f"{len(self.sessions)} de {len(self.all_sessions)} sesiones"
            + (f" · {len(errors)} errores" if errors else "")
        )
        footer_parts = [str(self.runs_root)]
        if errors:
            footer_parts.append(errors[0])
        if self.settings_warning:
            footer_parts.append(self.settings_warning)
        self.footer_var.set(" · ".join(footer_parts))

        target = None
        if preferred_database is not None:
            preferred = preferred_database.resolve()
            target = next(
                (
                    str(i)
                    for i, session in enumerate(self.sessions)
                    if session.database_path is not None
                    and session.database_path.resolve() == preferred
                ),
                None,
            )
        if target is None:
            target = next(
                (
                    str(i)
                    for i, session in enumerate(self.sessions)
                    if session.session_key == previous_key
                ),
                "0" if self.sessions else None,
            )
        if target is not None:
            self.tree.selection_set(target)
            self.tree.focus(target)
            self.tree.see(target)
            self._show_detail(self.sessions[int(target)])
        else:
            self._clear_detail()

    def selected_record(self) -> SessionRecord | None:
        selected = self.tree.selection()
        if not selected:
            return None
        try:
            return self.sessions[int(selected[0])]
        except (IndexError, ValueError):
            return None

    def _on_select(self, _event=None):
        record = self.selected_record()
        if record:
            self._show_detail(record)

    def _show_detail(self, record: SessionRecord):
        detail: SessionDetail = load_session_detail(record)
        self.detail_title.set(f"{record.track} · {format_lap_time(record.reference_time_s)}")
        self.detail_subtitle.set(
            f"{record.vehicle} · {record.valid_lap_count} vueltas válidas · {record.status_detail}"
        )
        (
            reference_value,
            laps_value,
            history_value,
            status_value,
        ) = session_summary_values(
            reference_time_s=record.reference_time_s,
            valid_lap_count=record.valid_lap_count,
            has_historical_reference=record.reference_selection_path is not None,
            has_historical_comparison=record.cross_session_path is not None,
            status=record.status,
        )
        self.summary_reference_var.set(reference_value)
        self.summary_laps_var.set(laps_value)
        self.summary_history_var.set(history_value)
        self.summary_status_var.set(status_value)
        self.current_debrief_markdown = detail.debrief_markdown or ""
        self._set_text(
            self.debrief_text,
            compact_debrief_markdown(self.current_debrief_markdown),
            markdown=True,
        )
        self._render_next_stint_cards(detail)
        self._render_session_changes(detail.session_change_view)
        self._request_session_change_view(record)
        self.current_laps_text = detail.laps_text or ""
        self._set_text(self.laps_text, compact_laps_text(self.current_laps_text))
        self._set_text(self.historical_reference_text, detail.historical_reference_text)
        self._set_comparison_view(
            detail.historical_comparison_view,
            detail.historical_comparison_text,
        )
        self._request_track_map(record)
        pipeline = detail.pipeline_text
        if detail.warnings:
            pipeline += "\n\nAdvertencias:\n" + "\n".join(detail.warnings)
        self._set_text(self.pipeline_text, pipeline)
        self.open_button.configure(state="normal")

    def _clear_detail(self):
        self.detail_title.set("No hay sesiones disponibles")
        self.detail_subtitle.set("Ejecutá un análisis o verificá el directorio configurado.")
        self.summary_reference_var.set("—")
        self.summary_laps_var.set("—")
        self.summary_history_var.set("—")
        self.summary_status_var.set("—")
        self.current_debrief_markdown = ""
        self.current_laps_text = ""
        self._cancel_session_change_request()
        self._render_session_changes({"status": "UNAVAILABLE"})
        for widget in (
            self.debrief_text,
            self.laps_text,
            self.historical_reference_text,
            self.pipeline_text,
        ):
            self._set_text(widget, "")
        self.comparison_summary_var.set("")
        self._set_text(self.comparison_hist_text, "")
        self._set_text(self.comparison_current_text, "")
        self._set_text(self.comparison_detail_text, "")
        self.track_map_token += 1
        self.track_map_loading = False
        self.current_track_map = None
        self.current_session_reference_track_map = None
        self.current_track_record = None
        self.manual_track_map_loading = False
        self._clear_track_lap_options()
        self.current_historical_track_map = None
        self.current_historical_track_label = ""
        self.historical_track_map_loading = False
        self.current_track_zones = ()
        self.current_track_priorities = ()
        self.current_track_profile = None
        self.current_track_turns = ()
        self._update_track_turn_controls()
        self._update_track_plan_controls()
        self._set_track_playback_controls(False)
        self.current_fitted_track_points = ()
        self.selected_track_overlay = None
        self.selected_track_point_index = None
        self.track_map_dragging = False
        self.telemetry_zoom_range = None
        self.track_map_zoom_scale = 1.0
        self.track_map_zoom_offset = (0.0, 0.0)
        self.track_map_pan_anchor = None
        self.track_map_canvas.delete("all")
        self.track_telemetry_canvas.delete("all")
        self.track_map_status.set("Seleccioná una sesión para reconstruir el mapa GPS.")
        self.track_map_zone_status.set("Sin capas de zonas para esta sesión.")
        self.track_map_telemetry_status.set(
            "Hacé clic en el trazado para inspeccionar velocidad, freno y acelerador."
        )
        self._set_telemetry_zoom_status()
        self._set_track_map_zoom_status()
        self.open_button.configure(state="disabled")

    def _start_historical_telemetry_request(
        self,
        record: SessionRecord,
        token: int,
    ) -> None:
        request = resolve_historical_telemetry_reference(
            record.reference_selection_path,
            self.all_sessions,
        )
        if request is None:
            return
        database = request["database_path"]
        try:
            modified_ns = database.stat().st_mtime_ns
        except OSError:
            return
        duration = request.get("duration_s")
        duration_key = (
            None if duration is None else int(round(float(duration) * 1000.0))
        )
        cache_key = (
            str(database),
            modified_ns,
            request.get("lap"),
            duration_key,
            self.track_resolution_hz,
        )
        label = (
            f"History #{request['session_id']} · vuelta {request['lap']}"
            if request.get("session_id") is not None and request.get("lap") is not None
            else "Referencia histórica H4"
        )
        cached = self.track_map_cache.get(cache_key)
        if cached is not None:
            self.current_historical_track_map = cached
            self.current_historical_track_label = label
            return

        self.historical_track_map_loading = True

        def worker():
            try:
                data = load_track_map(
                    database,
                    preferred_lap=request.get("lap"),
                    preferred_duration_s=duration,
                    target_hz=self.track_resolution_hz,
                )
                self.track_map_queue.put(
                    (token, "historical_done", (cache_key, data, label))
                )
            except Exception as exc:
                self.track_map_queue.put(
                    (token, "historical_error", f"{type(exc).__name__}: {exc}")
                )

        threading.Thread(
            target=worker,
            name="race-engineer-historical-telemetry",
            daemon=True,
        ).start()

    def _request_track_map(
        self,
        record: SessionRecord,
        *,
        preserve_visual: bool = False,
    ):
        self.track_map_token += 1
        token = self.track_map_token
        self.track_map_preserve_visual_token = token if preserve_visual else None
        self.track_map_loading = False
        self.current_track_record = record
        self.manual_track_map_loading = False
        self.historical_track_map_loading = False
        if not preserve_visual:
            self.current_track_map = None
            self.current_session_reference_track_map = None
            self._clear_track_lap_options()
            self.current_historical_track_map = None
            self.current_historical_track_label = ""
            self.current_track_zones = ()
            self.current_track_priorities = ()
            self.current_track_profile = None
            self.current_track_turns = ()
            self._update_track_turn_controls()
            self._update_track_plan_controls()
            self._set_track_playback_controls(False)
            self.current_fitted_track_points = ()
            self.selected_track_overlay = None
            self.selected_track_point_index = None
            self.track_map_dragging = False
            self.telemetry_zoom_range = None
            self.track_map_zoom_scale = 1.0
            self.track_map_zoom_offset = (0.0, 0.0)
            self.track_map_pan_anchor = None
            self.track_map_canvas.delete("all")
            self.track_telemetry_canvas.delete("all")
            self.track_map_zone_status.set("Buscando zonas H5.2 y prioridades del debrief…")
            self.track_map_telemetry_status.set(
                "Hacé clic en el trazado para inspeccionar velocidad, freno y acelerador."
            )
            self._set_telemetry_zoom_status()
            self._set_track_map_zoom_status()

        # Iniciar la referencia histórica sólo después de limpiar todo el estado.
        self._start_historical_telemetry_request(record, token)

        database = record.database_path
        if database is None:
            self.track_map_status.set("La sesión no registra su DuckDB original.")
            self.track_map_zone_status.set("Sin mapa GPS para superponer zonas.")
            return
        try:
            resolved = database.expanduser().resolve()
            modified_ns = resolved.stat().st_mtime_ns
        except OSError as exc:
            self.track_map_status.set(f"No se puede abrir la telemetría GPS: {exc}")
            self.track_map_zone_status.set("Sin mapa GPS para superponer zonas.")
            return
        duration_key = (
            None
            if record.reference_time_s is None
            else int(round(record.reference_time_s * 1000.0))
        )
        cache_key = (
            str(resolved),
            modified_ns,
            record.reference_lap,
            duration_key,
            self.track_resolution_hz,
        )
        cached = self.track_map_cache.get(cache_key)
        if cached is not None:
            self.track_map_preserve_visual_token = None
            self.current_track_map = cached
            self.current_session_reference_track_map = cached
            try:
                lap_options = list_track_map_laps(
                    resolved,
                    target_hz=self.track_resolution_hz,
                )
            except (OSError, ValueError):
                lap_options = (
                    TrackMapLapOption(
                        lap=int(cached.requested_lap or cached.lap),
                        duration_s=float(cached.duration_s),
                    ),
                )
            self._set_track_lap_options(
                lap_options,
                reference_lap=record.reference_lap,
                selected_lap=record.reference_lap,
            )
            layer_errors = []
            try:
                self.current_track_profile = load_track_profile(
                    PROJECT_ROOT / "track_profiles",
                    track=cached.track,
                    layout=cached.layout,
                )
                self.current_track_turns = profile_turns(self.current_track_profile)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                self.current_track_profile = None
                self.current_track_turns = ()
                layer_errors.append(f"perfil: {exc}")
            self._update_track_turn_controls()
            self._update_track_plan_controls()
            self._set_track_playback_controls(True)
            try:
                self.current_track_zones = load_track_zones(record.cross_session_path)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                self.current_track_zones = ()
                layer_errors.append(f"H5.2: {exc}")
            try:
                priority_path = (
                    record.debrief_path if record.has_validated_debrief else None
                )
                self.current_track_priorities = load_track_priorities(priority_path)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                self.current_track_priorities = ()
                layer_errors.append(f"debrief: {exc}")
            self._set_track_zone_summary(layer_errors=layer_errors)
            self.track_map_status.set(
                self._track_map_status_text(
                    cached,
                    resolution_hz=self.track_resolution_hz,
                )
            )
            self._render_track_map()
            if self.historical_track_map_loading:
                self.root.after(100, self._poll_track_map_queue)
            return

        self.track_map_loading = True
        self.track_map_status.set(
            f"Cargando telemetría a {self.track_resolution_hz:.0f} Hz en segundo plano…"
        )

        def worker():
            try:
                data = load_track_map(
                    resolved,
                    preferred_lap=record.reference_lap,
                    preferred_duration_s=record.reference_time_s,
                    target_hz=self.track_resolution_hz,
                )
                lap_options = list_track_map_laps(
                    resolved,
                    target_hz=self.track_resolution_hz,
                )
                try:
                    zones = load_track_zones(record.cross_session_path)
                    layer_errors = []
                except (OSError, UnicodeDecodeError, ValueError) as exc:
                    zones = ()
                    layer_errors = [f"H5.2: {exc}"]
                try:
                    priority_path = (
                        record.debrief_path if record.has_validated_debrief else None
                    )
                    priorities = load_track_priorities(priority_path)
                except (OSError, UnicodeDecodeError, ValueError) as exc:
                    priorities = ()
                    layer_errors.append(f"debrief: {exc}")
                try:
                    profile = load_track_profile(
                        PROJECT_ROOT / "track_profiles",
                        track=data.track,
                        layout=data.layout,
                    )
                except (OSError, UnicodeDecodeError, ValueError) as exc:
                    profile = None
                    layer_errors.append(f"perfil: {exc}")
                self.track_map_queue.put(
                    (
                        token,
                        "done",
                        (
                            cache_key,
                            data,
                            zones,
                            priorities,
                            profile,
                            tuple(layer_errors),
                            lap_options,
                        ),
                    )
                )
            except Exception as exc:
                self.track_map_queue.put(
                    (token, "error", f"{type(exc).__name__}: {exc}")
                )

        threading.Thread(target=worker, name="race-engineer-track-map", daemon=True).start()
        self.root.after(100, self._poll_track_map_queue)

    def _poll_track_map_queue(self):
        current_completed = False
        while True:
            try:
                token, kind, value = self.track_map_queue.get_nowait()
            except queue.Empty:
                break
            if token != self.track_map_token:
                continue
            if kind == "historical_done":
                cache_key, historical_data, historical_label = value
                self.historical_track_map_loading = False
                self.track_map_cache[cache_key] = historical_data
                self.current_historical_track_map = historical_data
                self.current_historical_track_label = historical_label
                if self.current_track_map is not None:
                    self._render_track_telemetry_chart()
                continue
            if kind == "historical_error":
                self.historical_track_map_loading = False
                self.current_historical_track_map = None
                self.current_historical_track_label = ""
                continue
            if kind == "manual_lap_done":
                cache_key, selected_data, option = value
                self.manual_track_map_loading = False
                self.track_map_cache[cache_key] = selected_data
                self.current_track_map = selected_data
                self.selected_track_point_index = None
                self.telemetry_zoom_range = None
                self.track_map_zoom_scale = 1.0
                self.track_map_zoom_offset = (0.0, 0.0)
                self._set_telemetry_zoom_status()
                self._set_track_map_zoom_status()
                self.track_map_status.set(
                    f"Vuelta seleccionada V{option.lap} · "
                    f"{format_lap_time(selected_data.duration_s)} · "
                    f"{self.track_resolution_hz:.0f} Hz"
                )
                self._render_track_map()
                continue
            if kind == "manual_lap_error":
                self.manual_track_map_loading = False
                self.track_map_status.set(
                    f"No se pudo cargar la vuelta seleccionada: {value}"
                )
                continue
            current_completed = True
            self.track_map_loading = False
            if kind == "done":
                self.track_map_preserve_visual_token = None
                (
                    cache_key,
                    data,
                    zones,
                    priorities,
                    profile,
                    layer_errors,
                    lap_options,
                ) = value
                self.track_map_cache[cache_key] = data
                self.current_track_map = data
                self.current_session_reference_track_map = data
                self._set_track_lap_options(
                    lap_options,
                    reference_lap=self.current_track_record.reference_lap
                    if self.current_track_record is not None
                    else data.requested_lap,
                    selected_lap=data.requested_lap,
                )
                self.current_track_zones = zones
                self.current_track_priorities = priorities
                self.current_track_profile = profile
                self.current_track_turns = profile_turns(profile)
                self._update_track_turn_controls()
                self._update_track_plan_controls()
                self._set_track_playback_controls(True)
                self.track_map_status.set(
                    self._track_map_status_text(
                        data,
                        resolution_hz=self.track_resolution_hz,
                    )
                )
                self._set_track_zone_summary(layer_errors=list(layer_errors))
                self._render_track_map()
            else:
                if getattr(self, "track_map_preserve_visual_token", None) == token:
                    self.track_map_preserve_visual_token = None
                    self.track_map_status.set(
                        f"No se pudo cargar {self.track_resolution_hz:.0f} Hz; "
                        f"se conserva el gráfico anterior: {value}"
                    )
                    continue
                self.current_track_map = None
                self.current_track_zones = ()
                self.current_track_priorities = ()
                self.current_track_profile = None
                self.current_track_turns = ()
                self._update_track_turn_controls()
                self._update_track_plan_controls()
                self._set_track_playback_controls(False)
                self.current_fitted_track_points = ()
                self.selected_track_point_index = None
                self.track_map_canvas.delete("all")
                self.track_telemetry_canvas.delete("all")
                self.track_map_status.set(f"Mapa GPS no disponible: {value}")
                self.track_map_zone_status.set("Sin mapa GPS para superponer zonas.")
        if (
            self.track_map_loading
            or self.historical_track_map_loading
            or self.manual_track_map_loading
        ):
            self.root.after(100, self._poll_track_map_queue)

    @staticmethod
    def _track_map_status_text(
        data: TrackMapData,
        *,
        resolution_hz: float | None = None,
    ) -> str:
        if data.selection_reason == "REFERENCE_DURATION_MATCH":
            requested = data.requested_lap if data.requested_lap is not None else data.lap
            lap_text = (
                f"referencia {requested} · grupo GPS {data.lap} "
                f"alineado por duración {format_lap_time(data.duration_s)}"
            )
        elif data.selection_reason == "EXACT_GPS_LAP":
            lap_text = f"vuelta GPS {data.lap} · trazado completo"
        else:
            lap_text = f"vuelta GPS completa {data.lap} · selección automática"
        resolution = (
            f"{resolution_hz:.0f} Hz · " if resolution_hz is not None else ""
        )
        return (
            f"{data.track} · {lap_text} · {len(data.points)} puntos · "
            f"{resolution}{data.width_m:.0f} × {data.height_m:.0f} m"
        )

    def _set_track_zone_summary(self, *, layer_errors: list[str] | None = None):
        zones = self.current_track_zones
        priorities = self.current_track_priorities
        profile = self.current_track_profile
        errors = layer_errors or []
        if not zones and not priorities:
            suffix = f" · {'; '.join(errors)}" if errors else ""
            if profile is not None:
                self.track_map_zone_status.set(
                    f"Perfil validado {profile.get('profile_id', 'disponible')} · "
                    "hacé clic en el trazado para identificar la curva." + suffix
                )
            else:
                self.track_map_zone_status.set(
                    "Sin zonas H5.2, prioridades ni perfil exacto para esta sesión."
                    + suffix
                )
            return
        losses = sum(zone.kind == "loss" for zone in zones)
        gains = sum(zone.kind == "gain" for zone in zones)
        focuses = sum(priority.is_focus for priority in priorities)
        text = (
            f"Zonas H5.2: {len(zones)} · pérdidas: {losses} · ganancias: {gains} · "
            f"focos: {focuses} · plan completo: {len(priorities)} · "
            "hacé clic en un tramo para ver el detalle."
        )
        if errors:
            text += " · " + "; ".join(errors)
        self.track_map_zone_status.set(text)

    def _update_track_turn_controls(self):
        if not hasattr(self, "track_turn_selector"):
            return
        values = tuple(
            f"T{turn.turn} — {turn.name}" for turn in self.current_track_turns
        )
        self.track_turn_selector.configure(
            values=values,
            state="readonly" if values else "disabled",
        )
        self.track_profile_layer_check.configure(
            state="normal" if values else "disabled"
        )
        self.track_turn_selector_var.set("Elegir curva…")

    def _update_track_plan_controls(self):
        if not hasattr(self, "track_plan_selector"):
            return
        values = tuple(
            (
                f"{'FOCO ' if priority.is_focus else ''}"
                f"{priority.priority_id} · {priority.label} · "
                f"{priority.start_distance_m:.0f}-{priority.end_distance_m:.0f} m"
            )
            for priority in self.current_track_priorities
        )
        self.track_plan_selector.configure(
            values=values,
            state="readonly" if values else "disabled",
        )
        self.track_plan_selector_var.set("Elegir zona del plan…")

    def _on_track_turn_selected(self, _event=None):
        self._stop_track_playback()
        raw = self.track_turn_selector_var.get().strip()
        if not raw.startswith("T") or " — " not in raw:
            return
        try:
            turn_number = int(raw[1:].split(" — ", 1)[0])
        except ValueError:
            return
        turn = turn_for_number(self.current_track_turns, turn_number)
        data = self.current_track_map
        if turn is None or data is None:
            return
        self.show_track_profile_var.set(True)
        self.selected_track_overlay = ("profile_turn", str(turn.turn))
        self.telemetry_zoom_range = (
            turn.start_distance_m,
            turn.end_distance_m,
        )
        apex_index = point_index_for_distance(data.points, turn.apex_distance_m)
        self.selected_track_point_index = apex_index
        width = max(self.track_map_canvas.winfo_width(), 100)
        height = max(self.track_map_canvas.winfo_height(), 100)
        base_fitted = fit_track_points(data.points, width_px=width, height_px=height)
        interval_points = tuple(
            base_fitted[index]
            for start_index, end_index in zone_point_ranges(data.points, turn)
            for index in range(start_index, end_index + 1)
        )
        (
            self.track_map_zoom_scale,
            offset_x,
            offset_y,
        ) = focus_track_canvas_view(
            interval_points,
            width_px=width,
            height_px=height,
        )
        self.track_map_zoom_offset = (offset_x, offset_y)
        self._set_track_map_zoom_status()
        self._set_telemetry_zoom_status()
        if apex_index is not None:
            self._set_interval_telemetry(
                data,
                turn.start_distance_m,
                turn.end_distance_m,
                data.points[apex_index],
            )
        self.track_map_zone_status.set(
            f"T{turn.turn} — {turn.name} · curva validada · "
            f"{turn.start_distance_m:.0f}-{turn.end_distance_m:.0f} m · "
            f"ápice {turn.apex_distance_m:.0f} m"
        )
        self._render_track_map()

    def _on_track_plan_selected(self, _event=None):
        self._stop_track_playback()
        raw = self.track_plan_selector_var.get().strip()
        data = self.current_track_map
        if not raw or data is None:
            return
        key = raw[5:] if raw.startswith("FOCO ") else raw
        priority_id = key.split(" · ", 1)[0].strip()
        priority = next(
            (
                item
                for item in self.current_track_priorities
                if item.priority_id == priority_id
            ),
            None,
        )
        if priority is None:
            return
        self.selected_track_overlay = ("priority", priority.priority_id)
        self.telemetry_zoom_range = (
            priority.start_distance_m,
            priority.end_distance_m,
        )
        center_distance = (
            priority.start_distance_m + priority.end_distance_m
        ) / 2.0
        center_index = point_index_for_distance(data.points, center_distance)
        self.selected_track_point_index = center_index
        width = max(self.track_map_canvas.winfo_width(), 100)
        height = max(self.track_map_canvas.winfo_height(), 100)
        base_fitted = fit_track_points(data.points, width_px=width, height_px=height)
        interval_points = tuple(
            base_fitted[index]
            for start_index, end_index in zone_point_ranges(data.points, priority)
            for index in range(start_index, end_index + 1)
        )
        (
            self.track_map_zoom_scale,
            offset_x,
            offset_y,
        ) = focus_track_canvas_view(
            interval_points,
            width_px=width,
            height_px=height,
        )
        self.track_map_zoom_offset = (offset_x, offset_y)
        self._set_track_map_zoom_status()
        self._set_telemetry_zoom_status()
        if center_index is not None:
            self._set_interval_telemetry(
                data,
                priority.start_distance_m,
                priority.end_distance_m,
                data.points[center_index],
            )
        focus_label = "Foco" if priority.is_focus else "Plan"
        cues = "; ".join(priority.cues[:2]) if priority.cues else "sin cue textual"
        self.track_map_zone_status.set(
            f"{focus_label} {priority.priority_id} · {priority.label} · "
            f"{priority.start_distance_m:.0f}-{priority.end_distance_m:.0f} m · {cues}"
        )
        self._render_track_map()

    def _on_track_play_toggle(self):
        if self.track_playback_active:
            self._stop_track_playback()
            return
        data = self.current_track_map
        if data is None or not data.points:
            return
        self.track_playback_active = True
        self.track_play_button.configure(text="⏸ Pausa")
        self._schedule_track_playback()

    def _schedule_track_playback(self):
        if not self.track_playback_active:
            return
        interval_ms = max(16, int(round(1000.0 / self.track_resolution_hz)))
        self.track_playback_after_id = self.root.after(
            interval_ms,
            self._tick_track_playback,
        )

    def _tick_track_playback(self):
        self.track_playback_after_id = None
        if not self.track_playback_active:
            return
        data = self.current_track_map
        if data is None or not data.points:
            self._stop_track_playback()
            return
        index = (self.selected_track_point_index or 0) + 1
        if index >= len(data.points):
            self._stop_track_playback()
            return
        self._apply_track_point_selection(index)
        self._schedule_track_playback()

    def _stop_track_playback(self):
        self.track_playback_active = False
        if self.track_playback_after_id is not None:
            try:
                self.root.after_cancel(self.track_playback_after_id)
            except Exception:
                pass
            self.track_playback_after_id = None
        if hasattr(self, "track_play_button"):
            self.track_play_button.configure(text="▶ Play")

    def _on_track_rewind(self):
        data = self.current_track_map
        if data is None or not data.points:
            return
        self._stop_track_playback()
        self._apply_track_point_selection(0)
        point = data.points[0]
        distance = (
            "—" if point.lap_distance_m is None else f"{point.lap_distance_m:.0f} m"
        )
        self.track_map_zone_status.set(f"Inicio de la vuelta · {distance}")

    def _on_track_resolution_changed(self, _event=None):
        raw = self.track_resolution_var.get().strip()
        if not raw.endswith("Hz"):
            return
        try:
            hz = float(raw[:-2].strip())
        except ValueError:
            return
        if hz == self.track_resolution_hz:
            return
        self.track_resolution_hz = hz
        record = self.selected_record()
        if record is not None:
            self._request_track_map(record, preserve_visual=True)

    def _set_track_playback_controls(self, enabled: bool):
        if not hasattr(self, "track_play_button"):
            return
        if not enabled:
            self._stop_track_playback()
        state = "normal" if enabled else "disabled"
        self.track_play_button.configure(state=state)
        self.track_rewind_button.configure(state=state)

    def _on_track_map_press(self, event):
        self._stop_track_playback()
        self.track_map_dragging = self._select_track_map_point(
            event.x,
            event.y,
            max_distance_px=18.0,
        )

    def _on_track_map_drag(self, event):
        if self.track_map_dragging:
            self._select_track_map_point(event.x, event.y, max_distance_px=None)

    def _on_track_map_release(self, event):
        if self.track_map_dragging:
            self._select_track_map_point(event.x, event.y, max_distance_px=None)
        self.track_map_dragging = False

    def _select_track_map_point(
        self,
        x_px: float,
        y_px: float,
        *,
        max_distance_px: float | None,
    ) -> bool:
        data = self.current_track_map
        fitted = self.current_fitted_track_points
        if data is None or not fitted:
            return False
        index = nearest_fitted_point_index(
            fitted,
            x_px=x_px,
            y_px=y_px,
            max_distance_px=max_distance_px,
        )
        if index is None:
            self.selected_track_overlay = None
            self.selected_track_point_index = None
            self._set_track_zone_summary()
            self.track_map_telemetry_status.set(
                "Hacé clic en el trazado para inspeccionar velocidad, freno y acelerador."
            )
            self._render_track_map()
            return False
        self._apply_track_point_selection(index)
        return True

    def _apply_track_point_selection(self, index: int) -> None:
        """Aplica un índice de punto del lap (drag, selector o playback)."""
        data = self.current_track_map
        if data is None or not (0 <= index < len(data.points)):
            return
        point = data.points[index]
        self.selected_track_point_index = index
        self._ensure_telemetry_point_visible(point)
        priority = priority_for_distance(
            self.current_track_priorities, point.lap_distance_m
        )
        if priority is not None:
            self.selected_track_overlay = ("priority", priority.priority_id)
            cue_text = "; ".join(priority.cues) or "sin cue textual disponible"
            priority_kind = "Foco" if priority.is_focus else "Plan"
            self.track_map_zone_status.set(
                f"{priority_kind} {priority.priority_id} · {priority.label} · "
                f"{priority.start_distance_m:.0f}-{priority.end_distance_m:.0f} m · "
                f"{cue_text}"
            )
            self._set_interval_telemetry(
                data,
                priority.start_distance_m,
                priority.end_distance_m,
                point,
            )
            self._render_track_map()
            return
        zone = zone_for_distance(self.current_track_zones, point.lap_distance_m)
        if zone is None:
            self.selected_track_overlay = None
            distance_text = (
                "—" if point.lap_distance_m is None else f"{point.lap_distance_m:.0f} m"
            )
            location = profile_location_for_distance(
                self.current_track_profile,
                point.lap_distance_m,
            )
            location_text = (
                f"{location.label} · " if location is not None else ""
            )
            self.track_map_zone_status.set(
                f"{location_text}punto {distance_text} · fuera de las zonas "
                "comparativas H5.2."
            )
            self.track_map_telemetry_status.set(self._point_telemetry_text(point))
        else:
            self.selected_track_overlay = ("h5_2", zone.zone_id)
            delta_text = (
                "—"
                if zone.delta_change_s is None
                else f"{zone.delta_change_s:+.3f} s"
            )
            kind = {"loss": "pérdida", "gain": "ganancia"}.get(
                zone.kind, zone.kind
            )
            self.track_map_zone_status.set(
                f"{zone.label} [{zone.zone_id}] · {kind} · "
                f"{zone.start_distance_m:.0f}-{zone.end_distance_m:.0f} m · "
                f"cambio {delta_text}"
            )
            self._set_interval_telemetry(
                data,
                zone.start_distance_m,
                zone.end_distance_m,
                point,
            )
        self._render_track_map()

    def _set_interval_telemetry(
        self,
        data: TrackMapData,
        start_distance_m: float,
        end_distance_m: float,
        selected_point: TrackMapPoint,
    ) -> None:
        summary = summarize_track_interval(
            data.points,
            start_distance_m,
            end_distance_m,
        )
        if summary is None:
            self.track_map_telemetry_status.set(
                self._point_telemetry_text(selected_point)
            )
            return
        self.track_map_telemetry_status.set(
            self._interval_telemetry_text(summary)
            + " · punto seleccionado: "
            + self._point_telemetry_text(selected_point, prefix=False)
        )

    @staticmethod
    def _point_telemetry_text(
        point: TrackMapPoint,
        *,
        prefix: bool = True,
    ) -> str:
        distance = "—" if point.lap_distance_m is None else f"{point.lap_distance_m:.0f} m"
        speed = "—" if point.speed_kmh is None else f"{point.speed_kmh:.0f} km/h"
        brake = "—" if point.brake_percent is None else f"{point.brake_percent:.0f}%"
        throttle = (
            "—" if point.throttle_percent is None else f"{point.throttle_percent:.0f}%"
        )
        gear = "—" if point.gear is None else ("N" if point.gear == 0 else str(point.gear))
        label = "Telemetría · " if prefix else ""
        return (
            f"{label}{distance} · velocidad {speed} · "
            f"freno {brake} · acelerador {throttle} · marcha {gear}"
        )

    @staticmethod
    def _interval_telemetry_text(summary: TrackTelemetrySummary) -> str:
        def number(value: float | None, suffix: str) -> str:
            return "—" if value is None else f"{value:.0f}{suffix}"

        speed = (
            "—"
            if summary.speed_mean_kmh is None
            else (
                f"{number(summary.speed_min_kmh, '')}-"
                f"{number(summary.speed_max_kmh, '')} km/h "
                f"(media {number(summary.speed_mean_kmh, '')})"
            )
        )
        return (
            f"Telemetría de zona · {summary.start_distance_m:.0f}-"
            f"{summary.end_distance_m:.0f} m · velocidad {speed} · "
            f"freno medio/máx {number(summary.brake_mean_percent, '%')}/"
            f"{number(summary.brake_max_percent, '%')} · acelerador medio/máx "
            f"{number(summary.throttle_mean_percent, '%')}/"
            f"{number(summary.throttle_max_percent, '%')}"
        )

    def _render_track_map(self):
        canvas = self.track_map_canvas
        canvas.delete("all")
        data = self.current_track_map
        if data is None:
            self._render_track_telemetry_chart()
            return
        width = max(canvas.winfo_width(), 100)
        height = max(canvas.winfo_height(), 100)
        base_fitted = fit_track_points(data.points, width_px=width, height_px=height)
        fitted = transform_fitted_track_points(
            base_fitted,
            scale=self.track_map_zoom_scale,
            offset_x_px=self.track_map_zoom_offset[0],
            offset_y_px=self.track_map_zoom_offset[1],
        )
        self.current_fitted_track_points = fitted
        if len(fitted) < 2:
            return
        coordinates = [coordinate for point in fitted for coordinate in point]
        canvas.create_line(
            *coordinates,
            fill=(
                "#59636d"
                if self.current_track_zones or self.current_track_priorities
                else "#57d9d0"
            ),
            width=4,
            capstyle="round",
            joinstyle="round",
        )
        if self.show_track_profile_var.get():
            for turn in self.current_track_turns:
                selected = self.selected_track_overlay == (
                    "profile_turn",
                    str(turn.turn),
                )
                for start_index, end_index in zone_point_ranges(data.points, turn):
                    segment = fitted[start_index : end_index + 1]
                    segment_coordinates = [value for point in segment for value in point]
                    canvas.create_line(
                        *segment_coordinates,
                        fill="#9be7ef" if selected else "#527d83",
                        width=7 if selected else 5,
                        capstyle="round",
                        joinstyle="round",
                    )
                apex_index = point_index_for_distance(
                    data.points,
                    turn.apex_distance_m,
                )
                if apex_index is None:
                    continue
                apex_x, apex_y = fitted[apex_index]
                canvas.create_oval(
                    apex_x - 3,
                    apex_y - 3,
                    apex_x + 3,
                    apex_y + 3,
                    fill="#ffffff" if selected else "#8bd3dd",
                    outline="#101010",
                    width=1,
                )
                canvas.create_text(
                    apex_x + 6,
                    apex_y - 6,
                    text=f"T{turn.turn} · {turn.name}",
                    fill="#ffffff" if selected else "#b8dfe4",
                    anchor="sw",
                    width=130,
                    font=("Segoe UI", 8),
                )
        zone_colors = {
            "loss": "#e45a5a",
            "gain": "#45c98c",
            "observation": "#d5a94f",
        }
        for zone in self.current_track_zones:
            selected = self.selected_track_overlay == ("h5_2", zone.zone_id)
            color = (
                "#ffd166"
                if selected
                else zone_colors.get(zone.kind, "#d5a94f")
            )
            line_width = 7 if selected else 5
            for start_index, end_index in zone_point_ranges(data.points, zone):
                segment = fitted[start_index : end_index + 1]
                segment_coordinates = [value for point in segment for value in point]
                canvas.create_line(
                    *segment_coordinates,
                    fill=color,
                    width=line_width,
                    capstyle="round",
                    joinstyle="round",
                )
        for priority in self.current_track_priorities:
            selected = self.selected_track_overlay == (
                "priority",
                priority.priority_id,
            )
            for start_index, end_index in zone_point_ranges(data.points, priority):
                segment = fitted[start_index : end_index + 1]
                segment_coordinates = [value for point in segment for value in point]
                canvas.create_line(
                    *segment_coordinates,
                    fill=(
                        "#f4f7fb"
                        if selected
                        else "#62b6ff" if priority.is_focus else "#315f8f"
                    ),
                    width=9 if selected else 8 if priority.is_focus else 5,
                    capstyle="round",
                    joinstyle="round",
                )
        start_x, start_y = fitted[0]
        canvas.create_oval(
            start_x - 6,
            start_y - 6,
            start_x + 6,
            start_y + 6,
            fill="#9b263d",
            outline="#f4a6b4",
            width=2,
        )
        canvas.create_text(
            start_x + 10,
            start_y - 10,
            text="Inicio",
            fill="#f2f7fb",
            anchor="sw",
            font=("Segoe UI", 9),
        )
        canvas.create_text(
            width - 18,
            16,
            text="N ↑",
            fill="#8fa5b8",
            anchor="ne",
            font=("Segoe UI Semibold", 10),
        )
        if self.current_track_zones or self.current_track_priorities:
            legend_rows = []
            if self.current_track_zones:
                legend_rows.extend(
                    (("#e45a5a", 5, "Pérdida"), ("#45c98c", 5, "Ganancia"))
                )
            if self.current_track_priorities:
                if any(priority.is_focus for priority in self.current_track_priorities):
                    legend_rows.append(("#62b6ff", 8, "Foco"))
                if any(not priority.is_focus for priority in self.current_track_priorities):
                    legend_rows.append(("#315f8f", 5, "Plan"))
            legend_height = 20 + 19 * len(legend_rows)
            canvas.create_rectangle(
                14, 13, 130, legend_height, fill="#151515", outline="#333333"
            )
            for row_index, (color, line_width, label) in enumerate(legend_rows):
                y = 29 + 19 * row_index
                canvas.create_line(24, y, 47, y, fill=color, width=line_width)
                canvas.create_text(
                    55,
                    y,
                    text=label,
                    fill="#dce7ef",
                    anchor="w",
                    font=("Segoe UI", 9),
                )
        if (
            self.selected_track_point_index is not None
            and 0 <= self.selected_track_point_index < len(fitted)
        ):
            point_x, point_y = fitted[self.selected_track_point_index]
            canvas.create_oval(
                point_x - 5,
                point_y - 5,
                point_x + 5,
                point_y + 5,
                fill="#f2f7fb",
                outline="#101010",
                width=2,
            )
        self._render_track_telemetry_chart()
        self._render_summary_visual_previews()

    def _on_track_map_mousewheel(self, event):
        if self.current_track_map is None or not getattr(event, "delta", 0):
            return "break"
        factor = 1.25 if event.delta > 0 else 0.8
        scale, offset_x, offset_y = zoom_track_canvas_view(
            self.track_map_zoom_scale,
            self.track_map_zoom_offset[0],
            self.track_map_zoom_offset[1],
            anchor_x_px=float(event.x),
            anchor_y_px=float(event.y),
            factor=factor,
        )
        self.track_map_zoom_scale = scale
        self.track_map_zoom_offset = (offset_x, offset_y)
        self._set_track_map_zoom_status()
        self._render_track_map()
        return "break"

    def _on_track_map_pan_press(self, event):
        if self.current_track_map is None or self.track_map_zoom_scale <= 1.001:
            self.track_map_pan_anchor = None
            return "break"
        self.track_map_pan_anchor = (float(event.x), float(event.y))
        self.track_map_canvas.configure(cursor="fleur")
        return "break"

    def _on_track_map_pan_drag(self, event):
        if self.track_map_pan_anchor is None or self.current_track_map is None:
            return "break"
        x = float(event.x)
        y = float(event.y)
        previous_x, previous_y = self.track_map_pan_anchor
        width = max(self.track_map_canvas.winfo_width(), 100)
        height = max(self.track_map_canvas.winfo_height(), 100)
        base_fitted = fit_track_points(
            self.current_track_map.points,
            width_px=width,
            height_px=height,
        )
        self.track_map_zoom_offset = pan_track_canvas_view(
            base_fitted,
            self.track_map_zoom_scale,
            self.track_map_zoom_offset[0],
            self.track_map_zoom_offset[1],
            delta_x_px=x - previous_x,
            delta_y_px=y - previous_y,
            width_px=width,
            height_px=height,
        )
        self.track_map_pan_anchor = (x, y)
        self._render_track_map()
        return "break"

    def _on_track_map_pan_release(self, _event=None):
        self.track_map_pan_anchor = None
        self.track_map_canvas.configure(cursor="crosshair")
        return "break"

    def _reset_track_map_zoom(self):
        self.track_map_zoom_scale = 1.0
        self.track_map_zoom_offset = (0.0, 0.0)
        self.track_map_pan_anchor = None
        self._set_track_map_zoom_status()
        self._render_track_map()

    def _set_track_map_zoom_status(self):
        active = self.track_map_zoom_scale > 1.001
        text = (
            f"Mapa ampliado · {self.track_map_zoom_scale:.2f}× · rueda: zoom · botón derecho: desplazar"
            if active
            else "Mapa completo · rueda: zoom · botón derecho: desplazar"
        )
        if hasattr(self, "track_map_zoom_status"):
            self.track_map_zoom_status.set(text)
        if hasattr(self, "track_map_zoom_reset_button"):
            self.track_map_zoom_reset_button.configure(
                state="normal" if active else "disabled"
            )

    def _render_track_telemetry_chart(self):
        canvas = self.track_telemetry_canvas
        canvas.delete("all")
        data = self.current_track_map
        if data is None:
            return
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if not telemetry_canvas_ready(width, height):
            canvas.create_text(
                max(width // 2, 8),
                max(height // 2, 8),
                text="Ampliá el panel de canales para ver velocidad, acelerador y freno.",
                fill="#8fa5b8",
                anchor="center",
                width=max(width - 24, 80),
                font=("Segoe UI", 9),
            )
            return

        comparison_mode = (
            self.track_comparison_var.get()
            if hasattr(self, "track_comparison_var")
            else "Referencia sesión"
        )
        session_reference = self.current_session_reference_track_map
        reference_overlay = (
            session_reference
            if comparison_mode == "Referencia sesión"
            and session_reference is not None
            and (
                session_reference.database_path != data.database_path
                or session_reference.lap != data.lap
            )
            else None
        )
        historical = (
            self.current_historical_track_map
            if comparison_mode == "History H4"
            else None
        )
        comparison_points = (
            tuple(reference_overlay.points)
            if reference_overlay is not None
            else tuple(historical.points)
            if historical is not None
            else ()
        )
        telemetry_comparison = (
            build_historical_telemetry_comparison(data.points, comparison_points)
            if comparison_points
            else None
        )
        shared_speed_max = telemetry_speed_scale(
            data.points,
            comparison_points,
        )
        shared_gear_max = telemetry_gear_scale(
            data.points,
            comparison_points,
        )
        zoom_start = (
            None if self.telemetry_zoom_range is None else self.telemetry_zoom_range[0]
        )
        zoom_end = (
            None if self.telemetry_zoom_range is None else self.telemetry_zoom_range[1]
        )
        chart = build_track_telemetry_chart(
            data.points,
            width_px=width,
            height_px=height,
            start_distance_m=zoom_start,
            end_distance_m=zoom_end,
            speed_max_kmh=shared_speed_max,
            include_gear=True,
            gear_max=shared_gear_max,
        )
        if chart is None:
            canvas.create_text(
                12,
                12,
                text="Canales de telemetría no disponibles.",
                fill="#8fa5b8",
                anchor="nw",
                font=("Segoe UI", 9),
            )
            return

        reference_chart = None
        if reference_overlay is not None:
            reference_chart = build_track_telemetry_chart(
                reference_overlay.points,
                width_px=width,
                height_px=height,
                start_distance_m=chart.distance_min_m,
                end_distance_m=chart.distance_max_m,
                axis_start_distance_m=chart.distance_min_m,
                axis_end_distance_m=chart.distance_max_m,
                speed_max_kmh=shared_speed_max,
            
                include_gear=True,
                gear_max=shared_gear_max,
)

        historical_chart = None
        if historical is not None:
            historical_chart = build_track_telemetry_chart(
                historical.points,
                width_px=width,
                height_px=height,
                start_distance_m=chart.distance_min_m,
                end_distance_m=chart.distance_max_m,
                axis_start_distance_m=chart.distance_min_m,
                axis_end_distance_m=chart.distance_max_m,
                speed_max_kmh=shared_speed_max,
            
                include_gear=True,
                gear_max=shared_gear_max,
)

        if telemetry_comparison is not None:
            for uncovered_start, uncovered_end in historical_telemetry_uncovered_ranges(
                telemetry_comparison,
                axis_start_distance_m=chart.distance_min_m,
                axis_end_distance_m=chart.distance_max_m,
            ):
                start_x = telemetry_chart_x_for_distance(
                    chart, uncovered_start, width_px=width
                )
                end_x = telemetry_chart_x_for_distance(
                    chart, uncovered_end, width_px=width
                )
                canvas.create_rectangle(
                    start_x,
                    12,
                    end_x,
                    height - 12,
                    fill="#171717",
                    outline="",
                    stipple="gray50",
                )

        lane_height = (height - 24) / 4.0
        for lane in (1, 2, 3):
            y = 12 + lane * lane_height
            canvas.create_line(74, y, width - 18, y, fill="#303030", width=1)

        selected_interval = self._selected_track_interval()
        if selected_interval is not None:
            start_x = telemetry_chart_x_for_distance(
                chart,
                selected_interval[0],
                width_px=width,
            )
            end_x = telemetry_chart_x_for_distance(
                chart,
                selected_interval[1],
                width_px=width,
            )
            canvas.create_rectangle(
                start_x,
                12,
                end_x,
                height - 12,
                fill="#272727",
                outline="",
                stipple="gray25",
            )

        lane_labels = (
            (f"Velocidad\n0–{chart.speed_max_kmh:.0f}", "#55b7e8"),
            ("Acelerador\n0–100%", "#45c98c"),
            ("Freno\n0–100%", "#e45a5a"),
            (f"Marcha\nN–{chart.gear_max}", "#d5a94f"),
        )
        for lane, (label, color) in enumerate(lane_labels):
            canvas.create_text(
                8,
                12 + lane * lane_height + lane_height / 2,
                text=label,
                fill=color,
                anchor="w",
                font=("Segoe UI", 8),
            )

        if historical_chart is not None:
            for values, color in (
                (historical_chart.speed, "#7393a3"),
                (historical_chart.throttle, "#6f9b84"),
                (historical_chart.brake, "#a06f6f"),
                (historical_chart.gear, "#9a8a63"),
            ):
                for chunk in canvas_polyline_chunks(values):
                    coordinates = [
                        coordinate for point in chunk for coordinate in point
                    ]
                    canvas.create_line(
                        *coordinates,
                        fill=color,
                        width=2,
                        dash=(6, 4),
                        joinstyle="round",
                    )

        if reference_chart is not None:
            for values, color in (
                (reference_chart.speed, "#8bcbed"),
                (reference_chart.throttle, "#76d6a8"),
                (reference_chart.brake, "#ea8b8b"),
                (reference_chart.gear, "#e0bf68"),
            ):
                for chunk in canvas_polyline_chunks(values):
                    coordinates = [
                        coordinate for point in chunk for coordinate in point
                    ]
                    canvas.create_line(
                        *coordinates,
                        fill=color,
                        width=1,
                        dash=(2, 4),
                        joinstyle="round",
                    )

        for values, color in (
            (chart.speed, "#55b7e8"),
            (chart.throttle, "#45c98c"),
            (chart.brake, "#e45a5a"),
            (chart.gear, "#d5a94f"),
        ):
            for chunk in canvas_polyline_chunks(values):
                coordinates = [coordinate for point in chunk for coordinate in point]
                canvas.create_line(
                    *coordinates,
                    fill=color,
                    width=2,
                    joinstyle="round",
                )

        if reference_chart is not None:
            reference_legend_x = max(width - 470, 84)
            canvas.create_line(
                reference_legend_x,
                19,
                reference_legend_x + 28,
                19,
                fill="#a9dff5",
                width=1,
                dash=(2, 4),
            )
            reference_label = (
                "Referencia de sesión"
                if session_reference is None
                else f"Referencia sesión · V{session_reference.lap}"
            )
            canvas.create_text(
                reference_legend_x + 35,
                19,
                text=reference_label,
                fill="#a9dff5",
                anchor="w",
                font=("Segoe UI", 8),
            )

        if historical_chart is not None:
            legend_x = max(width - 230, 84)
            canvas.create_line(
                legend_x,
                19,
                legend_x + 28,
                19,
                fill="#9aabb5",
                width=2,
                dash=(6, 4),
            )
            canvas.create_text(
                legend_x + 35,
                19,
                text=(
                    self.current_historical_track_label or "Referencia histórica H4"
                )
                + (
                    f" · cobertura {telemetry_comparison.current_coverage_ratio:.0%}"
                    if telemetry_comparison is not None
                    else ""
                ),
                fill="#9aabb5",
                anchor="w",
                font=("Segoe UI", 8),
            )

        if (
            self.selected_track_point_index is not None
            and 0 <= self.selected_track_point_index < len(data.points)
        ):
            point = data.points[self.selected_track_point_index]
            if point.lap_distance_m is not None:
                marker_x = telemetry_chart_x_for_distance(
                    chart,
                    point.lap_distance_m,
                    width_px=width,
                )
                canvas.create_line(
                    marker_x,
                    8,
                    marker_x,
                    height - 8,
                    fill="#f2f7fb",
                    width=2,
                )
                if telemetry_comparison is not None:
                    aligned_sample = historical_telemetry_sample_at_distance(
                        telemetry_comparison,
                        float(point.lap_distance_m),
                    )
                    if (
                        aligned_sample is not None
                        and aligned_sample.accumulated_delta_s is not None
                    ):
                        canvas.create_text(
                            min(marker_x + 8, width - 10),
                            12 + 2.5 * lane_height,
                            text=f"Delta {aligned_sample.accumulated_delta_s:+.3f} s",
                            fill="#00FFA6",
                            anchor="e" if marker_x > width * 0.75 else "w",
                            font=("Segoe UI", 8, "bold"),
                        )

    def _track_distance_bounds(self) -> tuple[float, float] | None:
        data = self.current_track_map
        if data is None:
            return None
        distances = [
            float(point.lap_distance_m)
            for point in data.points
            if point.lap_distance_m is not None
        ]
        if not distances:
            return None
        start, end = min(distances), max(distances)
        return (start, end) if end > start else None

    def _on_telemetry_mousewheel(self, event):
        bounds = self._track_distance_bounds()
        if bounds is None or event.delta == 0:
            return "break"
        full_start, full_end = bounds
        start, end = self.telemetry_zoom_range or bounds
        if event.state & 0x0001:
            direction = -1.0 if event.delta > 0 else 1.0
            self.telemetry_zoom_range = pan_distance_window(
                start,
                end,
                full_start_m=full_start,
                full_end_m=full_end,
                delta_m=direction * (end - start) * 0.18,
            )
        else:
            canvas_width = max(self.track_telemetry_canvas.winfo_width(), 180)
            ratio = min(max((event.x - 74) / max(canvas_width - 92, 1), 0.0), 1.0)
            anchor = start + ratio * (end - start)
            self.telemetry_zoom_range = zoom_distance_window(
                start,
                end,
                full_start_m=full_start,
                full_end_m=full_end,
                anchor_m=anchor,
                factor=0.78 if event.delta > 0 else 1.28,
            )
            if (
                self.telemetry_zoom_range[0] <= full_start + 0.5
                and self.telemetry_zoom_range[1] >= full_end - 0.5
            ):
                self.telemetry_zoom_range = None
        self._set_telemetry_zoom_status()
        self._render_track_telemetry_chart()
        return "break"

    def _on_telemetry_press(self, event):
        self._stop_track_playback()
        self.telemetry_chart_dragging = self._select_telemetry_point(event.x)

    def _on_telemetry_drag(self, event):
        if self.telemetry_chart_dragging:
            self._select_telemetry_point(event.x)

    def _on_telemetry_release(self, event):
        if self.telemetry_chart_dragging:
            self._select_telemetry_point(event.x)
        self.telemetry_chart_dragging = False

    def _select_telemetry_point(self, x_px: float) -> bool:
        data = self.current_track_map
        bounds = self._track_distance_bounds()
        if data is None or bounds is None:
            return False
        start, end = self.telemetry_zoom_range or bounds
        width = self.track_telemetry_canvas.winfo_width()
        chart_axis = TrackTelemetryChart(
            speed_max_kmh=100.0,
            speed=(),
            throttle=(),
            brake=(),
            distance_min_m=start,
            distance_max_m=end,
        )
        distance = telemetry_chart_distance_for_x(
            chart_axis,
            x_px,
            width_px=width,
        )
        if distance is None:
            return False
        index = point_index_for_distance(data.points, distance)
        if index is None:
            return False
        self._apply_track_point_selection(index)
        return True

    def _reset_telemetry_zoom(self):
        self.telemetry_zoom_range = None
        self._set_telemetry_zoom_status()
        self._render_track_telemetry_chart()

    def _set_telemetry_zoom_status(self):
        if self.telemetry_zoom_range is None:
            text = "Gráfico completo · rueda: zoom · Shift+rueda: desplazar"
            state = "disabled"
        else:
            start, end = self.telemetry_zoom_range
            text = (
                f"Zoom del gráfico {start:.0f}-{end:.0f} m ({end - start:.0f} m) · "
                "rueda: zoom · Shift+rueda: desplazar"
            )
            state = "normal"
        if hasattr(self, "telemetry_zoom_status"):
            self.telemetry_zoom_status.set(text)
        if hasattr(self, "telemetry_zoom_reset_button"):
            self.telemetry_zoom_reset_button.configure(state=state)

    def _ensure_telemetry_point_visible(self, point: TrackMapPoint):
        if self.telemetry_zoom_range is None or point.lap_distance_m is None:
            return
        start, end = self.telemetry_zoom_range
        distance = point.lap_distance_m
        if start <= distance <= end:
            return
        bounds = self._track_distance_bounds()
        if bounds is None:
            return
        midpoint = (start + end) / 2.0
        self.telemetry_zoom_range = pan_distance_window(
            start,
            end,
            full_start_m=bounds[0],
            full_end_m=bounds[1],
            delta_m=distance - midpoint,
        )
        self._set_telemetry_zoom_status()

    def _selected_track_interval(self) -> tuple[float, float] | None:
        selected = self.selected_track_overlay
        if selected is None:
            return None
        kind, identifier = selected
        values = (
            self.current_track_priorities
            if kind == "priority"
            else self.current_track_turns
            if kind == "profile_turn"
            else self.current_track_zones
        )
        for value in values:
            value_id = (
                value.priority_id
                if isinstance(value, TrackMapPriority)
                else str(value.turn)
                if isinstance(value, TrackMapTurn)
                else value.zone_id
            )
            if value_id == identifier:
                return value.start_distance_m, value.end_distance_m
        return None

    def _open_selected_folder(self):
        from tkinter import messagebox

        record = self.selected_record()
        if not record:
            return
        target = record.debrief_path or record.analysis_path or record.state_path
        try:
            _open_path(target)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror("Race Engineer", str(exc), parent=self.root)

    def _open_history(self):
        record = self.selected_record()
        preferred = record.database_path if record else None
        open_history_browser(
            self.root,
            history_db_default_path(),
            preferred_database=preferred,
        )

    def _choose_analysis_file(self):
        from tkinter import filedialog, messagebox

        if self.analysis_running:
            messagebox.showinfo(
                "Race Engineer",
                "Ya hay un análisis en ejecución.",
                parent=self.root,
            )
            return
        lmu_dir = Path(
            r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry"
        )
        initial = lmu_dir if lmu_dir.is_dir() else PROJECT_ROOT / "telemetria"
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Seleccionar telemetría LMU",
            initialdir=str(initial),
            filetypes=(("Telemetría DuckDB", "*.duckdb"), ("Todos los archivos", "*.*")),
        )
        if not selected:
            return
        self._confirm_analysis(Path(selected))

    def _on_session_double_click(self, event):
        from tkinter import messagebox

        self._cancel_session_change_request()
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        try:
            record = self.sessions[int(row)]
        except (IndexError, ValueError):
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        if record.database_path is None:
            messagebox.showerror(
                "Race Engineer",
                "Esta sesión no registra la ruta de su DuckDB original.",
                parent=self.root,
            )
            return
        try:
            database = validate_analysis_candidate(record.database_path)
        except (FileNotFoundError, ValueError, OSError) as exc:
            messagebox.showerror(
                "Race Engineer",
                "El DuckDB original de esta sesión ya no está disponible:\n\n"
                f"{exc}",
                parent=self.root,
            )
            return
        self._confirm_analysis(database)

    def _confirm_analysis(self, database: Path):
        from tkinter import messagebox

        if self.analysis_running:
            messagebox.showinfo(
                "Race Engineer",
                "Ya hay un análisis en ejecución.",
                parent=self.root,
            )
            return
        skip_stability_wait = bool(self.skip_stability_var.get())
        try:
            plan = build_analysis_plan(
                database,
                project_root=PROJECT_ROOT,
                skip_stability_wait=skip_stability_wait,
            )
        except (ValueError, FileNotFoundError, OSError) as exc:
            messagebox.showerror("Race Engineer", str(exc), parent=self.root)
            return
        self._start_analysis(plan)

    def _start_analysis(self, plan):
        self.analysis_running = True
        self.analysis_database = plan.database_path
        self.analyze_button.configure(state="disabled")
        self.skip_stability_check.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.progress.start(12)
        self.execution_status.set("Analizando con Python determinista…")
        self._set_text(
            self.execution_text,
            "RACE ENGINEER — EJECUCIÓN DESDE GUI\n"
            f"Archivo: {plan.database_path}\nMotor: Python determinista\n"
            f"Override espera 10 min: {'SÍ' if plan.skip_stability_wait else 'NO'}\n",
        )
        self._show_primary_section("Diagnóstico")
        self.diagnostics_notebook.select(self.execution_text.master)

        def worker():
            try:
                code = stream_analysis(
                    plan,
                    lambda line: self.analysis_queue.put(("line", line)),
                )
                self.analysis_queue.put(("done", code))
            except Exception as exc:
                self.analysis_queue.put(("error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=worker, name="race-engineer-analysis", daemon=True).start()
        self.root.after(100, self._poll_analysis_queue)

    def _poll_analysis_queue(self):
        finished = False
        while True:
            try:
                kind, value = self.analysis_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self._append_execution_line(str(value))
            elif kind == "done":
                self._finish_analysis(int(value))
                finished = True
            elif kind == "error":
                self._append_execution_line(f"GUI_LAUNCH_FAILED: {value}")
                self._finish_analysis(1)
                finished = True
        if self.analysis_running and not finished:
            self.root.after(100, self._poll_analysis_queue)

    def _finish_analysis(self, return_code: int):
        from tkinter import messagebox

        self.analysis_running = False
        self.progress.stop()
        self.analyze_button.configure(state="normal")
        self.skip_stability_var.set(False)
        self.skip_stability_check.configure(state="normal")
        self.refresh_button.configure(state="normal")
        database = self.analysis_database
        self.refresh(preferred_database=database)
        selected = self.selected_record()
        validated_debrief_available = bool(
            database is not None
            and selected is not None
            and selected.database_path is not None
            and selected.database_path.resolve() == database.resolve()
            and selected.status == "DEBRIEF_READY"
        )
        outcome = classify_analysis_completion(
            return_code,
            validated_debrief_available=validated_debrief_available,
        )
        if outcome == "PASS":
            self.execution_status.set("Análisis terminado correctamente")
            self._append_execution_line("\nGUI RESULT: PASS")
            self.session_query_var.set("")
            self.session_filter_var.set("Todas")
            self.refresh(preferred_database=database)
            self._show_primary_section("Resumen")
            messagebox.showinfo(
                "Race Engineer",
                "El análisis terminó correctamente y la lista fue actualizada.",
                parent=self.root,
            )
        elif outcome == "BLOCKED":
            self.execution_status.set("Análisis bloqueado de forma segura")
            self._append_execution_line("\nGUI RESULT: BLOCKED")
            messagebox.showwarning(
                "Race Engineer",
                "El launcher bloqueó el análisis. Revisá la pestaña Ejecución.",
                parent=self.root,
            )
        elif outcome == "RECOVERED_VALID_DEBRIEF":
            self.execution_status.set("Debrief válido recuperado; pipeline incompleto")
            self._append_execution_line("\nGUI RESULT: RECOVERED_VALID_DEBRIEF")
            self._show_primary_section("Resumen")
            messagebox.showwarning(
                "Race Engineer",
                "El proceso informó un error posterior, pero el debrief ya había sido "
                "guardado y validado. Se muestra el resultado recuperado; revisá Pipeline "
                "para comprobar si quedó alguna etapa posterior pendiente.",
                parent=self.root,
            )
        else:
            self.execution_status.set("El análisis terminó con un error")
            self._append_execution_line("\nGUI RESULT: FAILED")
            messagebox.showerror(
                "Race Engineer",
                "El análisis falló. Revisá la pestaña Ejecución.",
                parent=self.root,
            )
        self.analysis_database = None

    def _on_close(self):
        from tkinter import messagebox

        if self.analysis_running:
            messagebox.showwarning(
                "Race Engineer",
                "Hay un análisis en ejecución. La ventana no se cerrará ni cancelará el proceso.\n\n"
                "Esperá a que termine.",
                parent=self.root,
            )
            return
        self._closing = True
        self._cancel_session_change_request()
        if self._state_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._state_refresh_after_id)
            except Exception:
                pass
            self._state_refresh_after_id = None
        self.root.destroy()


def _print_sessions(runs_root: Path) -> int:
    sessions, errors = discover_sessions(runs_root)
    for session in sessions:
        print(
            f"{format_timestamp(session.timestamp_utc, session.modified_timestamp)} | "
            f"{session.track} | {format_lap_time(session.reference_time_s)} | "
            f"{session.status_detail}"
        )
    for error in errors:
        print(f"WARNING: {error}", file=sys.stderr)
    return 0 if sessions else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--list", action="store_true", help="list sessions without opening a window")
    args = parser.parse_args(argv)
    if args.list:
        return _print_sessions(args.runs_root)

    import tkinter as tk

    root = tk.Tk()
    RaceEngineerApp(root, args.runs_root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
