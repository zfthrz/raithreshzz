"""Read-only Tk History browser used by the Race Engineer desktop GUI."""

from __future__ import annotations

from pathlib import Path

from race_engineer_history_model import (
    HistorySession,
    filter_history_sessions,
    load_history_detail,
    load_history_sessions,
)
from race_engineer_ui_model import format_lap_time, format_timestamp


def _flag_text(lap) -> str:
    flags = []
    if lap.is_reference:
        flags.append("REFERENCIA")
    if lap.is_valid:
        flags.append("válida")
    if lap.is_discarded:
        flags.append("descartada")
    if lap.is_ignored_initial:
        flags.append("inicial ignorada")
    return ", ".join(flags) or "sin clasificación"


class HistoryBrowser:
    def __init__(self, parent, database_path: Path, preferred_database: Path | None = None):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.database_path = Path(database_path).resolve()
        self.preferred_database = preferred_database
        self.sessions: list[HistorySession] = []
        self.filtered: list[HistorySession] = []

        self.window = tk.Toplevel(parent)
        self.window.title("Race Engineer — History")
        self.window.geometry("1180x720")
        self.window.minsize(900, 560)
        self.window.configure(background="#101010")

        header = ttk.Frame(self.window, style="App.TFrame", padding=(18, 16, 18, 10))
        header.pack(fill="x")
        ttk.Label(header, text="HISTORY", style="Title.TLabel").pack(side="left")
        self.query = tk.StringVar()
        search = ttk.Entry(header, textvariable=self.query, width=38)
        search.pack(side="right", padx=(8, 0))
        ttk.Label(header, text="Buscar:", style="Subtitle.TLabel").pack(side="right")
        self.query.trace_add("write", lambda *_: self._apply_filter())

        body = ttk.Panedwindow(self.window, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        left = ttk.Frame(body, style="Panel.TFrame", padding=10)
        right = ttk.Frame(body, style="Panel.TFrame", padding=12)
        body.add(left, weight=7)
        body.add(right, weight=5)

        self.count = tk.StringVar(value="Leyendo History…")
        ttk.Label(left, textvariable=self.count, style="Metric.TLabel").pack(anchor="w", pady=(0, 8))
        columns = ("id", "date", "track", "vehicle", "laps", "reference")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        labels = {
            "id": "ID", "date": "Fecha", "track": "Circuito",
            "vehicle": "Vehículo", "laps": "Válidas", "reference": "Referencia",
        }
        widths = {"id": 48, "date": 120, "track": 210, "vehicle": 210, "laps": 60, "reference": 90}
        for name in columns:
            self.tree.heading(name, text=labels[name])
            self.tree.column(name, width=widths[name], minwidth=40, stretch=name in {"track", "vehicle"})
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.title = tk.StringVar(value="Seleccioná una sesión histórica")
        ttk.Label(right, textvariable=self.title, style="Metric.TLabel").pack(anchor="w", pady=(0, 8))
        self.detail = tk.Text(
            right, wrap="word", background="#15181c", foreground="#dce7ef",
            insertbackground="#55decf", selectbackground="#315b60",
            selectforeground="#f4fbff", relief="flat", borderwidth=0,
            highlightthickness=0, padx=16, pady=14, font=("Segoe UI", 10),
            spacing1=2, spacing3=4,
        )
        detail_scroll = ttk.Scrollbar(right, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side="right", fill="y")
        self.detail.pack(fill="both", expand=True)
        self.detail.configure(state="disabled")

        self.footer = tk.StringVar(value=str(self.database_path))
        ttk.Label(
            self.window, textvariable=self.footer, style="Subtitle.TLabel", anchor="w"
        ).pack(fill="x", padx=18, pady=(0, 10))
        self.refresh()
        search.focus_set()

    def _set_detail(self, value: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", value)
        self.detail.configure(state="disabled")
        self.detail.yview_moveto(0)

    def refresh(self) -> None:
        from tkinter import messagebox

        try:
            self.sessions = load_history_sessions(self.database_path)
        except Exception as exc:
            self.sessions = []
            messagebox.showerror("Race Engineer — History", str(exc), parent=self.window)
        self._apply_filter()

    def _apply_filter(self) -> None:
        self.filtered = filter_history_sessions(self.sessions, self.query.get())
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, session in enumerate(self.filtered):
            self.tree.insert(
                "", "end", iid=str(index),
                values=(
                    session.session_id,
                    format_timestamp(session.timestamp_utc, 0),
                    session.track,
                    session.car_name,
                    session.valid_lap_count,
                    format_lap_time(session.reference_time_s),
                ),
                tags=("row_even" if index % 2 == 0 else "row_odd",),
            )
        self.tree.tag_configure("row_even", background="#171717")
        self.tree.tag_configure("row_odd", background="#1b1f23")
        self.count.set(f"{len(self.filtered)} de {len(self.sessions)} sesiones")
        target = self._preferred_index()
        if target is None and self.filtered:
            target = 0
        if target is not None:
            iid = str(target)
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
            self._show(self.filtered[target])
        else:
            self.title.set("Sin sesiones para este filtro")
            self._set_detail("")

    def _preferred_index(self) -> int | None:
        if self.preferred_database is None:
            return None
        preferred = str(self.preferred_database).casefold()
        for index, session in enumerate(self.filtered):
            if session.source_database_path and str(session.source_database_path).casefold() == preferred:
                self.preferred_database = None
                return index
        return None

    def _on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        try:
            session = self.filtered[int(selected[0])]
        except (IndexError, ValueError):
            return
        self._show(session)

    def _show(self, session: HistorySession) -> None:
        from tkinter import messagebox

        try:
            detail = load_history_detail(self.database_path, session)
        except Exception as exc:
            messagebox.showerror("Race Engineer — History", str(exc), parent=self.window)
            return
        self.title.set(f"History #{session.session_id} · {session.track}")
        lines = [
            f"Fecha: {format_timestamp(session.timestamp_utc, 0)}",
            f"Contexto: {session.track} / {session.track_layout}",
            f"Vehículo: {session.vehicle_variant} / {session.car_name}",
            f"Sesión: {session.session_type} / clima: {session.weather}",
            f"Referencia: vuelta {session.reference_lap or '—'} / {format_lap_time(session.reference_time_s)}",
            f"Vueltas válidas: {session.valid_lap_count} / comparaciones: {session.comparison_count}",
            "",
            "Vueltas almacenadas:",
        ]
        for lap in detail.laps:
            lines.append(
                f"  Vuelta {lap.lap}: {format_lap_time(lap.duration_s)} · {_flag_text(lap)}"
            )
        lines.extend(("", f"Análisis fuente: {session.source_json_path or '—'}", f"DuckDB fuente: {session.source_database_path or '—'}"))
        self._set_detail("\n".join(lines))


def open_history_browser(parent, database_path: Path, preferred_database: Path | None = None):
    return HistoryBrowser(parent, database_path, preferred_database)
