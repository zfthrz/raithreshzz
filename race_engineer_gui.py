#!/usr/bin/env python3
"""Race Engineer desktop session hub and read-only History browser."""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
from pathlib import Path

from race_engineer_history_gui import open_history_browser
from race_engineer_gui_settings import (
    backend_environment,
    backend_model_label,
    default_settings,
    load_settings,
    save_settings,
)
from race_engineer_settings_gui import edit_settings
from runtime_paths import history_db_default_path

from race_engineer_ui_model import (
    SessionDetail,
    SessionRecord,
    discover_sessions,
    filter_sessions,
    format_lap_time,
    format_timestamp,
    load_session_detail,
)
from race_engineer_ui_analysis import (
    build_analysis_plan,
    classify_analysis_completion,
    stream_analysis,
    validate_analysis_candidate,
)
from race_engineer_track_map import (
    TrackMapData,
    TrackMapPriority,
    TrackMapPoint,
    TrackTelemetrySummary,
    TrackMapZone,
    build_track_telemetry_chart,
    fit_track_points,
    load_track_map,
    load_track_priorities,
    load_track_zones,
    nearest_fitted_point_index,
    priority_for_distance,
    summarize_track_interval,
    telemetry_chart_x_for_distance,
    zone_for_distance,
    zone_point_ranges,
)


GUI_VERSION = "1.2"
DEFAULT_RUNS_ROOT = Path(__file__).resolve().parent / "data" / "generated" / "runs"
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_LABELS = {
    "DeepSeek (remoto)": "deepseek",
    "llama.cpp (local)": "llamacpp",
    "Ollama / ingenierov3 (local)": "ollama",
}
SESSION_FILTER_LABELS = {
    "Todas": "ALL",
    "Con debrief": "DEBRIEF_READY",
    "Sólo History": "HISTORY_READY",
    "Fallidas": "FAILED",
}


def _open_path(path: Path) -> None:
    target = path if path.is_dir() else path.parent
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    raise RuntimeError("Abrir carpetas desde la GUI sólo está soportado en Windows.")


def _clean_markdown_line(line: str) -> str:
    return line.replace("**", "").replace("_", "")


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
        self.analysis_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.track_map_queue: queue.Queue[tuple[int, str, object]] = queue.Queue()
        self.track_map_token = 0
        self.track_map_loading = False
        self.current_track_map: TrackMapData | None = None
        self.current_track_zones: tuple[TrackMapZone, ...] = ()
        self.current_track_priorities: tuple[TrackMapPriority, ...] = ()
        self.current_fitted_track_points: tuple[tuple[float, float], ...] = ()
        self.selected_track_overlay: tuple[str, str] | None = None
        self.selected_track_point_index: int | None = None
        self.track_map_dragging = False
        self.track_map_cache: dict[
            tuple[str, int, int | None, int | None], TrackMapData
        ] = {}
        self.analysis_running = False
        self.analysis_database: Path | None = None
        self.analysis_model: str | None = None
        self.settings_path = PROJECT_ROOT / "data" / "local" / "race_engineer_gui_settings.json"
        try:
            self.settings = load_settings(self.settings_path)
            self.settings_warning = ""
        except (OSError, ValueError, TypeError) as exc:
            self.settings = default_settings()
            self.settings_warning = f"Configuración local inválida; se usan defaults: {exc}"

        root.title(f"Race Engineer — Session Hub v{GUI_VERSION}")
        root.geometry("1320x820")
        root.minsize(1020, 650)
        root.configure(background="#101010")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_style()
        self._build_layout()
        self.refresh()

    def _configure_style(self):
        style = self.ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background="#101010")
        style.configure("Panel.TFrame", background="#1c1c1c")
        style.configure(
            "Title.TLabel",
            background="#101010",
            foreground="#f2f7fb",
            font=("Segoe UI Semibold", 22),
        )
        style.configure(
            "Subtitle.TLabel",
            background="#101010",
            foreground="#8fa5b8",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Metric.TLabel",
            background="#1c1c1c",
            foreground="#e8f1f7",
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "Muted.TLabel",
            background="#1c1c1c",
            foreground="#91a6b8",
            font=("Segoe UI", 9),
        )
        style.configure(
            "Accent.TButton",
            font=("Segoe UI Semibold", 10),
            foreground="#061014",
            background="#45d4c2",
            padding=(12, 7),
        )
        style.map("Accent.TButton", background=[("active", "#67e5d5")])
        style.configure(
            "Analyze.TButton",
            font=("Segoe UI Semibold", 10),
            foreground="#fff4f4",
            background="#7d2938",
            padding=(12, 7),
        )
        style.map("Analyze.TButton", background=[("active", "#9b3548")])
        style.configure(
            "TCheckbutton",
            background="#101010",
            foreground="#c9c9c9",
            font=("Segoe UI", 9),
        )
        style.map("TCheckbutton", background=[("active", "#101010")])
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 7))
        style.configure(
            "Treeview",
            background="#171717",
            fieldbackground="#171717",
            foreground="#dce7ef",
            rowheight=29,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#2a2a2a",
            foreground="#dce7ef",
            font=("Segoe UI Semibold", 9),
            padding=(5, 8),
        )
        style.map("Treeview", background=[("selected", "#3b3b3b")])
        style.configure("TNotebook", background="#1c1c1c", borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#2a2a2a",
            foreground="#b8c7d3",
            padding=(14, 8),
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#1c1c1c")],
            foreground=[("selected", "#55decf")],
        )

    def _build_layout(self):
        ttk = self.ttk
        tk = self.tk

        header = ttk.Frame(self.root, style="App.TFrame", padding=(22, 18, 22, 12))
        header.pack(fill="x")
        title_box = ttk.Frame(header, style="App.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="RACE ENGINEER", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="Sesiones, History y debriefs en un solo lugar · interfaz de solo lectura",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        actions = ttk.Frame(header, style="App.TFrame")
        actions.pack(side="right")
        self.backend_var = tk.StringVar(value="DeepSeek (remoto)")
        self.backend_combo = ttk.Combobox(
            actions,
            textvariable=self.backend_var,
            values=tuple(BACKEND_LABELS),
            state="readonly",
            width=27,
        )
        self.backend_combo.pack(side="left", padx=(0, 8))
        self.skip_stability_var = tk.BooleanVar(value=False)
        self.skip_stability_check = ttk.Checkbutton(
            actions,
            text="Omitir espera 10 min",
            variable=self.skip_stability_var,
        )
        self.skip_stability_check.pack(side="left", padx=(0, 8))
        self.analyze_button = ttk.Button(
            actions,
            text="Elegir archivo…",
            style="Analyze.TButton",
            command=self._choose_analysis_file,
        )
        self.analyze_button.pack(side="left", padx=(0, 8))
        self.refresh_button = ttk.Button(actions, text="Actualizar", command=self.refresh)
        self.refresh_button.pack(side="left")
        self.history_button = ttk.Button(actions, text="History", command=self._open_history)
        self.history_button.pack(side="left", padx=(8, 0))
        self.settings_button = ttk.Button(actions, text="Configuración", command=self._edit_settings)
        self.settings_button.pack(side="left", padx=(8, 0))

        content = ttk.Panedwindow(self.root, orient="horizontal")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        left = ttk.Frame(content, style="Panel.TFrame", padding=12)
        right = ttk.Frame(content, style="Panel.TFrame", padding=14)
        content.add(left, weight=5)
        content.add(right, weight=7)

        session_tools = ttk.Frame(left, style="Panel.TFrame")
        session_tools.pack(fill="x", pady=(0, 8))
        self.count_var = tk.StringVar(value="Buscando sesiones…")
        ttk.Label(session_tools, textvariable=self.count_var, style="Metric.TLabel").pack(
            side="left"
        )
        self.session_filter_var = tk.StringVar(value="Todas")
        self.session_filter_combo = ttk.Combobox(
            session_tools,
            textvariable=self.session_filter_var,
            values=tuple(SESSION_FILTER_LABELS),
            state="readonly",
            width=15,
        )
        self.session_filter_combo.pack(side="right", padx=(8, 0))
        self.session_query_var = tk.StringVar()
        self.session_query_entry = ttk.Entry(
            session_tools,
            textvariable=self.session_query_var,
            width=24,
        )
        self.session_query_entry.pack(side="right")
        ttk.Label(session_tools, text="Buscar:", style="Muted.TLabel").pack(
            side="right", padx=(0, 6)
        )
        self.session_filter_combo.bind("<<ComboboxSelected>>", self._apply_session_filters)
        self.session_query_var.trace_add("write", lambda *_: self._apply_session_filters())

        columns = ("date", "track", "vehicle", "laps", "best", "status")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        headings = {
            "date": "Fecha",
            "track": "Circuito",
            "vehicle": "Vehículo",
            "laps": "Vueltas",
            "best": "Referencia",
            "status": "Estado",
        }
        widths = {"date": 120, "track": 190, "vehicle": 190, "laps": 55, "best": 80, "status": 120}
        for name in columns:
            self.tree.heading(name, text=headings[name])
            self.tree.column(name, width=widths[name], minwidth=45, stretch=name in {"track", "vehicle"})
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_session_double_click)
        ttk.Label(
            left,
            text="Doble clic: analizar el DuckDB de esa sesión con el backend seleccionado",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(8, 0))

        detail_header = ttk.Frame(right, style="Panel.TFrame")
        detail_header.pack(fill="x", pady=(0, 10))
        labels = ttk.Frame(detail_header, style="Panel.TFrame")
        labels.pack(side="left", fill="x", expand=True)
        self.detail_title = tk.StringVar(value="Seleccioná una sesión")
        self.detail_subtitle = tk.StringVar(value="")
        ttk.Label(labels, textvariable=self.detail_title, style="Metric.TLabel").pack(anchor="w")
        ttk.Label(labels, textvariable=self.detail_subtitle, style="Muted.TLabel").pack(
            anchor="w", pady=(3, 0)
        )
        self.open_button = ttk.Button(
            detail_header,
            text="Abrir carpeta",
            command=self._open_selected_folder,
            state="disabled",
        )
        self.open_button.pack(side="right")

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)
        self.debrief_text = self._text_tab(self.notebook, "Debrief")
        self.plan_text = self._text_tab(self.notebook, "Próxima tanda")
        self.laps_text = self._text_tab(self.notebook, "Vueltas")
        self.historical_reference_text = self._text_tab(self.notebook, "Referencia histórica")
        self.historical_comparison_text = self._text_tab(self.notebook, "Comparación histórica")
        self.track_map_canvas = self._track_map_tab(self.notebook)
        self.pipeline_text = self._text_tab(self.notebook, "Pipeline")
        self.execution_text = self._text_tab(self.notebook, "Ejecución")

        execution_bar = ttk.Frame(right, style="Panel.TFrame")
        execution_bar.pack(fill="x", pady=(10, 0))
        self.execution_status = tk.StringVar(value="Sin análisis en ejecución")
        ttk.Label(
            execution_bar,
            textvariable=self.execution_status,
            style="Muted.TLabel",
        ).pack(side="left")
        self.progress = ttk.Progressbar(execution_bar, mode="indeterminate", length=180)
        self.progress.pack(side="right")

        footer = str(self.runs_root)
        if self.settings_warning:
            footer += " · " + self.settings_warning
        self.footer_var = tk.StringVar(value=footer)
        ttk.Label(
            self.root,
            textvariable=self.footer_var,
            style="Subtitle.TLabel",
            anchor="w",
        ).pack(fill="x", padx=22, pady=(0, 10))

    def _text_tab(self, notebook, label):
        frame = self.ttk.Frame(notebook, style="Panel.TFrame", padding=5)
        notebook.add(frame, text=label)
        text = self.tk.Text(
            frame,
            wrap="word",
            background="#151515",
            foreground="#dce7ef",
            insertbackground="#dce7ef",
            selectbackground="#3b3b3b",
            relief="flat",
            padx=18,
            pady=16,
            font=("Segoe UI", 10),
            spacing1=2,
            spacing3=4,
        )
        text.tag_configure("h1", font=("Segoe UI Semibold", 18), foreground="#f2f7fb", spacing3=12)
        text.tag_configure("h2", font=("Segoe UI Semibold", 14), foreground="#55decf", spacing1=12, spacing3=7)
        text.tag_configure("h3", font=("Segoe UI Semibold", 11), foreground="#f2f7fb", spacing1=8)
        text.tag_configure("bullet", lmargin1=18, lmargin2=32)
        scrollbar = self.ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.configure(state="disabled")
        return text

    def _track_map_tab(self, notebook):
        frame = self.ttk.Frame(notebook, style="Panel.TFrame", padding=8)
        notebook.add(frame, text="Mapa")
        self.track_map_status = self.tk.StringVar(
            value="Seleccioná una sesión para reconstruir el mapa GPS."
        )
        self.ttk.Label(
            frame,
            textvariable=self.track_map_status,
            style="Muted.TLabel",
        ).pack(fill="x", padx=8, pady=(4, 8))
        canvas = self.tk.Canvas(
            frame,
            background="#0d0d0d",
            highlightthickness=1,
            highlightbackground="#333333",
        )
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Configure>", lambda _event: self._render_track_map())
        canvas.configure(cursor="crosshair")
        canvas.bind("<ButtonPress-1>", self._on_track_map_press)
        canvas.bind("<B1-Motion>", self._on_track_map_drag)
        canvas.bind("<ButtonRelease-1>", self._on_track_map_release)
        self.track_map_zone_status = self.tk.StringVar(
            value="Sin zonas H5.2 para esta sesión."
        )
        self.ttk.Label(
            frame,
            textvariable=self.track_map_zone_status,
            style="Muted.TLabel",
        ).pack(fill="x", padx=8, pady=(8, 4))
        self.track_map_telemetry_status = self.tk.StringVar(
            value="Hacé clic en el trazado para inspeccionar velocidad, freno y acelerador."
        )
        self.ttk.Label(
            frame,
            textvariable=self.track_map_telemetry_status,
            style="Muted.TLabel",
            wraplength=960,
            justify="left",
        ).pack(fill="x", padx=8, pady=(0, 4))
        telemetry_canvas = self.tk.Canvas(
            frame,
            height=180,
            background="#111111",
            highlightthickness=1,
            highlightbackground="#333333",
        )
        telemetry_canvas.pack(fill="x", padx=0, pady=(4, 0))
        telemetry_canvas.bind(
            "<Configure>", lambda _event: self._render_track_telemetry_chart()
        )
        self.track_telemetry_canvas = telemetry_canvas
        return canvas

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
        previous = self.selected_record()
        previous_key = previous.session_key if previous else None
        self.all_sessions, errors = discover_sessions(self.runs_root)
        self.session_read_errors = errors
        self._populate_session_tree(
            errors=errors,
            preferred_database=preferred_database,
            previous_key=previous_key,
        )

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
                tags=(session.status,),
            )
        self.tree.tag_configure("DEBRIEF_READY", foreground="#67e5d5")
        self.tree.tag_configure("HISTORY_READY", foreground="#f0c674")
        self.tree.tag_configure("FAILED", foreground="#ff7b72")
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
        self._set_text(self.debrief_text, detail.debrief_markdown, markdown=True)
        self._set_text(self.plan_text, detail.plan_text)
        self._set_text(self.laps_text, detail.laps_text)
        self._set_text(self.historical_reference_text, detail.historical_reference_text)
        self._set_text(self.historical_comparison_text, detail.historical_comparison_text)
        self._request_track_map(record)
        pipeline = detail.pipeline_text
        if detail.warnings:
            pipeline += "\n\nAdvertencias:\n" + "\n".join(detail.warnings)
        self._set_text(self.pipeline_text, pipeline)
        self.open_button.configure(state="normal")

    def _clear_detail(self):
        self.detail_title.set("No hay sesiones disponibles")
        self.detail_subtitle.set("Ejecutá un análisis o verificá el directorio configurado.")
        for widget in (
            self.debrief_text,
            self.plan_text,
            self.laps_text,
            self.historical_reference_text,
            self.historical_comparison_text,
            self.pipeline_text,
        ):
            self._set_text(widget, "")
        self.track_map_token += 1
        self.track_map_loading = False
        self.current_track_map = None
        self.current_track_zones = ()
        self.current_track_priorities = ()
        self.current_fitted_track_points = ()
        self.selected_track_overlay = None
        self.selected_track_point_index = None
        self.track_map_dragging = False
        self.track_map_canvas.delete("all")
        self.track_telemetry_canvas.delete("all")
        self.track_map_status.set("Seleccioná una sesión para reconstruir el mapa GPS.")
        self.track_map_zone_status.set("Sin capas de zonas para esta sesión.")
        self.track_map_telemetry_status.set(
            "Hacé clic en el trazado para inspeccionar velocidad, freno y acelerador."
        )
        self.open_button.configure(state="disabled")

    def _request_track_map(self, record: SessionRecord):
        self.track_map_token += 1
        token = self.track_map_token
        self.track_map_loading = False
        self.current_track_map = None
        self.current_track_zones = ()
        self.current_track_priorities = ()
        self.current_fitted_track_points = ()
        self.selected_track_overlay = None
        self.selected_track_point_index = None
        self.track_map_dragging = False
        self.track_map_canvas.delete("all")
        self.track_telemetry_canvas.delete("all")
        self.track_map_zone_status.set("Buscando zonas H5.2 y prioridades del debrief…")
        self.track_map_telemetry_status.set(
            "Hacé clic en el trazado para inspeccionar velocidad, freno y acelerador."
        )
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
        cache_key = (str(resolved), modified_ns, record.reference_lap, duration_key)
        cached = self.track_map_cache.get(cache_key)
        if cached is not None:
            self.current_track_map = cached
            layer_errors = []
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
            self.track_map_status.set(self._track_map_status_text(cached))
            self._render_track_map()
            return

        self.track_map_loading = True
        self.track_map_status.set("Reconstruyendo vuelta GPS en segundo plano…")

        def worker():
            try:
                data = load_track_map(
                    resolved,
                    preferred_lap=record.reference_lap,
                    preferred_duration_s=record.reference_time_s,
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
                self.track_map_queue.put(
                    (
                        token,
                        "done",
                        (cache_key, data, zones, priorities, tuple(layer_errors)),
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
            current_completed = True
            self.track_map_loading = False
            if kind == "done":
                cache_key, data, zones, priorities, layer_errors = value
                self.track_map_cache[cache_key] = data
                self.current_track_map = data
                self.current_track_zones = zones
                self.current_track_priorities = priorities
                self.track_map_status.set(self._track_map_status_text(data))
                self._set_track_zone_summary(layer_errors=list(layer_errors))
                self._render_track_map()
            else:
                self.current_track_map = None
                self.current_track_zones = ()
                self.current_track_priorities = ()
                self.current_fitted_track_points = ()
                self.selected_track_point_index = None
                self.track_map_canvas.delete("all")
                self.track_telemetry_canvas.delete("all")
                self.track_map_status.set(f"Mapa GPS no disponible: {value}")
                self.track_map_zone_status.set("Sin mapa GPS para superponer zonas.")
        if self.track_map_loading and not current_completed:
            self.root.after(100, self._poll_track_map_queue)

    @staticmethod
    def _track_map_status_text(data: TrackMapData) -> str:
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
        return (
            f"{data.track} · {lap_text} · {len(data.points)} puntos · "
            f"{data.width_m:.0f} × {data.height_m:.0f} m"
        )

    def _set_track_zone_summary(self, *, layer_errors: list[str] | None = None):
        zones = self.current_track_zones
        priorities = self.current_track_priorities
        errors = layer_errors or []
        if not zones and not priorities:
            suffix = f" · {'; '.join(errors)}" if errors else ""
            self.track_map_zone_status.set(
                "Sin zonas H5.2 ni prioridades validadas para esta sesión." + suffix
            )
            return
        losses = sum(zone.kind == "loss" for zone in zones)
        gains = sum(zone.kind == "gain" for zone in zones)
        text = (
            f"Zonas H5.2: {len(zones)} · pérdidas: {losses} · ganancias: {gains} · "
            f"prioridades: {len(priorities)} · hacé clic en un tramo para ver el detalle."
        )
        if errors:
            text += " · " + "; ".join(errors)
        self.track_map_zone_status.set(text)

    def _on_track_map_press(self, event):
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
        point = data.points[index]
        self.selected_track_point_index = index
        priority = priority_for_distance(
            self.current_track_priorities, point.lap_distance_m
        )
        if priority is not None:
            self.selected_track_overlay = ("priority", priority.priority_id)
            cue_text = "; ".join(priority.cues) or "sin cue textual disponible"
            self.track_map_zone_status.set(
                f"Prioridad {priority.priority_id} · {priority.label} · "
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
            return True
        zone = zone_for_distance(self.current_track_zones, point.lap_distance_m)
        if zone is None:
            self.selected_track_overlay = None
            distance_text = (
                "—" if point.lap_distance_m is None else f"{point.lap_distance_m:.0f} m"
            )
            self.track_map_zone_status.set(
                f"Punto {distance_text}: fuera de las zonas comparativas H5.2."
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
        return True

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
        label = "Telemetría · " if prefix else ""
        return (
            f"{label}{distance} · velocidad {speed} · "
            f"freno {brake} · acelerador {throttle}"
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
        fitted = fit_track_points(data.points, width_px=width, height_px=height)
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
                    fill="#f4f7fb" if selected else "#4da3ff",
                    width=9 if selected else 7,
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
                legend_rows.append(("#4da3ff", 7, "Prioridad"))
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

    def _render_track_telemetry_chart(self):
        canvas = self.track_telemetry_canvas
        canvas.delete("all")
        data = self.current_track_map
        if data is None:
            return
        width = max(canvas.winfo_width(), 180)
        height = max(canvas.winfo_height(), 120)
        chart = build_track_telemetry_chart(
            data.points,
            width_px=width,
            height_px=height,
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

        lane_height = (height - 24) / 3.0
        for lane in (1, 2):
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

        for values, color in (
            (chart.speed, "#55b7e8"),
            (chart.throttle, "#45c98c"),
            (chart.brake, "#e45a5a"),
        ):
            if len(values) >= 2:
                coordinates = [coordinate for point in values for coordinate in point]
                canvas.create_line(
                    *coordinates,
                    fill=color,
                    width=2,
                    joinstyle="round",
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

    def _selected_track_interval(self) -> tuple[float, float] | None:
        selected = self.selected_track_overlay
        if selected is None:
            return None
        kind, identifier = selected
        values = (
            self.current_track_priorities
            if kind == "priority"
            else self.current_track_zones
        )
        for value in values:
            value_id = (
                value.priority_id
                if isinstance(value, TrackMapPriority)
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

    def _edit_settings(self):
        from tkinter import messagebox

        if self.analysis_running:
            messagebox.showinfo(
                "Race Engineer",
                "Esperá a que termine el análisis antes de cambiar el modelo.",
                parent=self.root,
            )
            return
        updated = edit_settings(self.root, self.settings)
        if updated is None:
            return
        try:
            self.settings = save_settings(self.settings_path, updated)
            self.settings_warning = ""
        except (OSError, ValueError) as exc:
            messagebox.showerror("Race Engineer", str(exc), parent=self.root)
            return
        messagebox.showinfo(
            "Race Engineer",
            "Configuración guardada localmente. Se aplicará al próximo análisis.",
            parent=self.root,
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
        backend_label = self.backend_var.get()
        backend = BACKEND_LABELS[backend_label]
        model = backend_model_label(self.settings, backend)
        skip_stability_wait = bool(self.skip_stability_var.get())
        remote_note = (
            "\n\nDeepSeek usa la API remota y puede generar un costo."
            if backend == "deepseek"
            else "\n\nEl servidor/modelo local debe estar iniciado."
        )
        stability_note = (
            "\n\nATENCIÓN: se omitirá la espera de estabilidad de 10 minutos. "
            "LMU debe estar cerrado y los demás controles siguen activos."
            if skip_stability_wait
            else ""
        )
        if not messagebox.askyesno(
            "Confirmar análisis",
            f"Archivo:\n{database}\n\nBackend: {backend_label}\nModelo: {model}"
            f"{remote_note}{stability_note}\n\n"
            "El launcher volverá a comprobar LMU, tamaño y vueltas válidas; "
            "la estabilidad se omite sólo con este override.\n"
            "¿Continuar?",
            parent=self.root,
        ):
            return
        try:
            plan = build_analysis_plan(
                database,
                backend=backend,
                project_root=PROJECT_ROOT,
                environment_overrides=backend_environment(self.settings, backend),
                skip_stability_wait=skip_stability_wait,
            )
        except (ValueError, FileNotFoundError, OSError) as exc:
            messagebox.showerror("Race Engineer", str(exc), parent=self.root)
            return
        self.analysis_model = model
        self._start_analysis(plan)

    def _start_analysis(self, plan):
        self.analysis_running = True
        self.analysis_database = plan.database_path
        self.analyze_button.configure(state="disabled")
        self.backend_combo.configure(state="disabled")
        self.skip_stability_check.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.progress.start(12)
        self.execution_status.set(f"Analizando con {plan.backend}…")
        self._set_text(
            self.execution_text,
            "RACE ENGINEER — EJECUCIÓN DESDE GUI\n"
            f"Archivo: {plan.database_path}\nBackend: {plan.backend}\n"
            f"Modelo: {self.analysis_model or '—'}\n"
            f"Override espera 10 min: {'SÍ' if plan.skip_stability_wait else 'NO'}\n",
        )
        self.notebook.select(self.execution_text.master)

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
        self.backend_combo.configure(state="readonly")
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
            self.notebook.select(self.debrief_text.master)
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
            self.notebook.select(self.debrief_text.master)
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
        self.analysis_model = None

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
