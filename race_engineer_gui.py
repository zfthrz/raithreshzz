#!/usr/bin/env python3
"""Race Engineer desktop session browser v0.1 (read-only)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from race_engineer_ui_model import (
    SessionDetail,
    SessionRecord,
    discover_sessions,
    format_lap_time,
    format_timestamp,
    load_session_detail,
)


GUI_VERSION = "0.1"
DEFAULT_RUNS_ROOT = Path(__file__).resolve().parent / "data" / "generated" / "runs"


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

        root.title(f"Race Engineer — Session Hub v{GUI_VERSION}")
        root.geometry("1320x820")
        root.minsize(1020, 650)
        root.configure(background="#10151b")

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
        ttk.Button(header, text="Actualizar", style="Accent.TButton", command=self.refresh).pack(
            side="right"
        )

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

        notebook = ttk.Notebook(right)
        notebook.pack(fill="both", expand=True)
        self.debrief_text = self._text_tab(notebook, "Debrief")
        self.plan_text = self._text_tab(notebook, "Próxima tanda")
        self.pipeline_text = self._text_tab(notebook, "Pipeline")

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

    def refresh(self):
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

        target = next(
            (str(i) for i, session in enumerate(self.sessions) if session.session_key == previous_key),
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
