#!/usr/bin/env python3
"""Race Engineer desktop session browser v0.1 (read-only)."""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
from pathlib import Path

from race_engineer_ui_model import (
    SessionDetail,
    SessionRecord,
    discover_sessions,
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


GUI_VERSION = "0.2"
DEFAULT_RUNS_ROOT = Path(__file__).resolve().parent / "data" / "generated" / "runs"
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_LABELS = {
    "DeepSeek (remoto)": "deepseek",
    "llama.cpp (local)": "llamacpp",
    "Ollama / ingenierov3 (local)": "ollama",
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
        self.analysis_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.analysis_running = False
        self.analysis_database: Path | None = None

        root.title(f"Race Engineer — Session Hub v{GUI_VERSION}")
        root.geometry("1320x820")
        root.minsize(1020, 650)
        root.configure(background="#10151b")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_style()
        self._build_layout()
        self.refresh()

    def _configure_style(self):
        style = self.ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background="#10151b")
        style.configure("Panel.TFrame", background="#18212b")
        style.configure(
            "Title.TLabel",
            background="#10151b",
            foreground="#f2f7fb",
            font=("Segoe UI Semibold", 22),
        )
        style.configure(
            "Subtitle.TLabel",
            background="#10151b",
            foreground="#8fa5b8",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Metric.TLabel",
            background="#18212b",
            foreground="#e8f1f7",
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "Muted.TLabel",
            background="#18212b",
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
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 7))
        style.configure(
            "Treeview",
            background="#141c24",
            fieldbackground="#141c24",
            foreground="#dce7ef",
            rowheight=29,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#24313e",
            foreground="#dce7ef",
            font=("Segoe UI Semibold", 9),
            padding=(5, 8),
        )
        style.map("Treeview", background=[("selected", "#256b73")])
        style.configure("TNotebook", background="#18212b", borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#24313e",
            foreground="#b8c7d3",
            padding=(14, 8),
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#18212b")],
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
        self.analyze_button = ttk.Button(
            actions,
            text="Elegir archivo…",
            style="Accent.TButton",
            command=self._choose_analysis_file,
        )
        self.analyze_button.pack(side="left", padx=(0, 8))
        self.refresh_button = ttk.Button(actions, text="Actualizar", command=self.refresh)
        self.refresh_button.pack(side="left")

        content = ttk.Panedwindow(self.root, orient="horizontal")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        left = ttk.Frame(content, style="Panel.TFrame", padding=12)
        right = ttk.Frame(content, style="Panel.TFrame", padding=14)
        content.add(left, weight=5)
        content.add(right, weight=7)

        self.count_var = tk.StringVar(value="Buscando sesiones…")
        ttk.Label(left, textvariable=self.count_var, style="Metric.TLabel").pack(
            anchor="w", pady=(0, 8)
        )

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

        self.footer_var = tk.StringVar(value=str(self.runs_root))
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
            background="#111820",
            foreground="#dce7ef",
            insertbackground="#dce7ef",
            selectbackground="#256b73",
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
        self.sessions, errors = discover_sessions(self.runs_root)
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
        self.count_var.set(f"{len(self.sessions)} sesiones · {len(errors)} errores de lectura")
        self.footer_var.set(str(self.runs_root) + (f" · {errors[0]}" if errors else ""))

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
        pipeline = detail.pipeline_text
        if detail.warnings:
            pipeline += "\n\nAdvertencias:\n" + "\n".join(detail.warnings)
        self._set_text(self.pipeline_text, pipeline)
        self.open_button.configure(state="normal")

    def _clear_detail(self):
        self.detail_title.set("No hay sesiones disponibles")
        self.detail_subtitle.set("Ejecutá un análisis o verificá el directorio configurado.")
        for widget in (self.debrief_text, self.plan_text, self.pipeline_text):
            self._set_text(widget, "")
        self.open_button.configure(state="disabled")

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
        remote_note = (
            "\n\nDeepSeek usa la API remota y puede generar un costo."
            if backend == "deepseek"
            else "\n\nEl servidor/modelo local debe estar iniciado."
        )
        if not messagebox.askyesno(
            "Confirmar análisis",
            f"Archivo:\n{database}\n\nBackend: {backend_label}{remote_note}\n\n"
            "El launcher volverá a comprobar LMU, tamaño, estabilidad y vueltas válidas.\n"
            "¿Continuar?",
            parent=self.root,
        ):
            return
        try:
            plan = build_analysis_plan(
                database,
                backend=backend,
                project_root=PROJECT_ROOT,
            )
        except (ValueError, FileNotFoundError, OSError) as exc:
            messagebox.showerror("Race Engineer", str(exc), parent=self.root)
            return
        self._start_analysis(plan)

    def _start_analysis(self, plan):
        self.analysis_running = True
        self.analysis_database = plan.database_path
        self.analyze_button.configure(state="disabled")
        self.backend_combo.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.progress.start(12)
        self.execution_status.set(f"Analizando con {plan.backend}…")
        self._set_text(
            self.execution_text,
            "RACE ENGINEER — EJECUCIÓN DESDE GUI\n"
            f"Archivo: {plan.database_path}\nBackend: {plan.backend}\n",
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
