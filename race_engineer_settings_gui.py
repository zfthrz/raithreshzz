"""Modal editor for Race Engineer non-secret GUI backend settings."""

from __future__ import annotations

from race_engineer_gui_settings import GuiSettings, validate_settings


def edit_settings(parent, current: GuiSettings) -> GuiSettings | None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    result: list[GuiSettings] = []
    window = tk.Toplevel(parent)
    window.title("Race Engineer — Configuración")
    window.geometry("620x390")
    window.resizable(False, False)
    window.configure(background="#101010")
    window.transient(parent)
    window.grab_set()

    frame = ttk.Frame(window, style="Panel.TFrame", padding=22)
    frame.pack(fill="both", expand=True, padx=16, pady=16)
    ttk.Label(frame, text="BACKENDS Y MODELOS", style="Metric.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 18)
    )
    deepseek_model = tk.StringVar(value=current.deepseek_model)
    llamacpp_model = tk.StringVar(value=current.llamacpp_model)
    llamacpp_url = tk.StringVar(value=current.llamacpp_api_url)
    fields = (
        ("Modelo DeepSeek", deepseek_model),
        ("Modelo llama.cpp", llamacpp_model),
        ("URL local llama.cpp", llamacpp_url),
    )
    for row, (label, variable) in enumerate(fields, start=1):
        ttk.Label(frame, text=label, style="Muted.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 14), pady=8
        )
        ttk.Entry(frame, textvariable=variable, width=51).grid(
            row=row, column=1, sticky="ew", pady=8
        )
    ttk.Label(
        frame,
        text=(
            "Ollama permanece fijo en ingenierov3. Las API keys no se muestran ni "
            "se guardan aquí. llama.cpp sólo acepta localhost."
        ),
        style="Muted.TLabel",
        wraplength=545,
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(18, 12))
    buttons = ttk.Frame(frame, style="Panel.TFrame")
    buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(14, 0))

    def save() -> None:
        try:
            settings = validate_settings(
                GuiSettings(
                    deepseek_model=deepseek_model.get(),
                    llamacpp_model=llamacpp_model.get(),
                    llamacpp_api_url=llamacpp_url.get(),
                )
            )
        except ValueError as exc:
            messagebox.showerror("Race Engineer", str(exc), parent=window)
            return
        result.append(settings)
        window.destroy()

    ttk.Button(buttons, text="Cancelar", command=window.destroy).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Guardar", style="Accent.TButton", command=save).pack(side="left")
    frame.columnconfigure(1, weight=1)
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.wait_window()
    return result[0] if result else None
