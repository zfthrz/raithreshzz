from __future__ import annotations

from race_engineer_gui import (
    GUI_VERSION,
    PRIMARY_SECTIONS,
    SECTION_VIEWS,
    RaceEngineerApp,
    format_comparison_columns,
    session_status_color,
    session_status_tooltip,
    session_summary_values,
    status_wraplength,
    telemetry_canvas_ready,
)


class FakeStyle:
    def __init__(self):
        self.theme = None
        self.configurations: dict[str, dict] = {}
        self.maps: dict[str, dict] = {}

    def theme_names(self):
        return ("default", "clam")

    def theme_use(self, theme):
        self.theme = theme

    def configure(self, name, **options):
        self.configurations[name] = options

    def map(self, name, **options):
        self.maps[name] = options


class FakeRoot:
    def __init__(self):
        self.options: dict[str, str] = {}

    def option_add(self, pattern, value):
        self.options[pattern] = value


class FakeTtk:
    def __init__(self, style):
        self.style = style

    def Style(self, _root):
        return self.style


def test_gui_v1_11_applies_flat_dark_control_chrome_without_opening_window():
    style = FakeStyle()
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.root = FakeRoot()
    app.ttk = FakeTtk(style)

    app._configure_style()

    assert GUI_VERSION == "1.13"
    assert style.theme == "clam"
    assert style.configurations["TEntry"]["fieldbackground"] == "#15181c"
    assert style.configurations["TCombobox"]["borderwidth"] == 0
    assert style.configurations["DialogTitle.TLabel"]["font"] == ("Segoe UI Semibold", 16)
    assert style.configurations["TSeparator"]["background"] == "#343b42"
    assert style.configurations["Vertical.TScrollbar"]["width"] == 10
    assert style.configurations["Horizontal.TScrollbar"]["width"] == 10
    assert style.configurations["Treeview"]["rowheight"] == 30
    assert style.configurations["Treeview.Heading"]["relief"] == "flat"
    assert style.configurations["Horizontal.TProgressbar"]["thickness"] == 5
    assert style.configurations["H53Ready.TLabel"]["foreground"] == "#67e5d5"
    assert style.configurations["H53Pending.TLabel"]["foreground"] == "#f0c674"
    assert style.configurations["H53Error.TLabel"]["foreground"] == "#ff7b72"
    assert ("selected", "#315b60") in style.maps["Treeview"]["background"]
    assert ("selected", "#55decf") in style.maps["TNotebook.Tab"]["foreground"]
    assert app.root.options["*TCombobox*Listbox.background"] == "#15181c"


def test_map_status_wraplength_tracks_panel_width_with_safe_minimum():
    assert status_wraplength(1000) == 976
    assert status_wraplength(500) == 476
    assert status_wraplength(120) == 240


def test_telemetry_chart_requires_real_room_for_all_three_channels():
    assert telemetry_canvas_ready(800, 210) is True
    assert telemetry_canvas_ready(179, 210) is False
    assert telemetry_canvas_ready(800, 119) is False


def test_primary_navigation_groups_technical_views_by_user_task():
    assert PRIMARY_SECTIONS == (
        "Resumen",
        "Telemetría",
        "Historial",
        "Diagnóstico",
    )
    assert SECTION_VIEWS["Resumen"] == ("Debrief", "Próxima tanda", "Vueltas")
    assert SECTION_VIEWS["Historial"] == ("Referencia", "Comparación")
    assert SECTION_VIEWS["Diagnóstico"] == ("Pipeline", "Ejecución")


def test_session_summary_uses_existing_status_and_history_availability_only():
    assert session_summary_values(
        reference_time_s=90.94,
        valid_lap_count=4,
        has_historical_reference=True,
        has_historical_comparison=True,
        status="DEBRIEF_READY",
    ) == ("1:30.940", "4", "Comparación lista", "Debrief listo")
    assert session_summary_values(
        reference_time_s=None,
        valid_lap_count=0,
        has_historical_reference=False,
        has_historical_comparison=False,
        status="UNKNOWN",
    ) == ("—", "0", "Sin compatible", "Estado desconocido")


def test_session_status_badges_have_explicit_color_and_tooltip():
    assert session_status_color("DEBRIEF_READY") == "#67e5d5"
    assert session_status_color("FAILED") == "#ff7b72"
    assert session_status_color("UNKNOWN") == "#9aa5ad"
    assert "Debrief validado" in session_status_tooltip("DEBRIEF_READY")
    assert "Falló en alguna etapa" in session_status_tooltip("FAILED")
    assert "no clasificado" in session_status_tooltip("UNKNOWN")


def test_format_comparison_columns_builds_side_by_side_view():
    view = {
        "available": True,
        "stage_status": "RUN",
        "delta_text": "+1.280 s",
        "historical": {
            "session_id": 7,
            "lap": 8,
            "duration_s": 90.98,
            "duration_text": "1:30.980",
        },
        "current": {
            "session_id": 9,
            "lap": 1,
            "duration_s": 92.26,
            "duration_text": "1:32.260",
        },
        "zones": [
            {
                "label": "Curva 1",
                "type": "frenada",
                "delta_change_s": 0.32,
            },
            {
                "label": "Curva 2",
                "type": "tracção",
                "delta_change_s": 0.21,
            },
        ],
        "llm": {
            "rendered": "Lectura histórica validada.",
            "backend": "deepseek",
            "model": "deepseek-v4-pro",
        },
    }

    summary, hist_text, current_text, detail_text = format_comparison_columns(view)

    assert summary == "Delta actual − histórica: +1.280 s"
    assert "Sesión histórica: #7" in hist_text
    assert "1:30.980" in hist_text
    assert "Sesión actual: #9" in current_text
    assert "1:32.260" in current_text
    assert "Curva 1" in detail_text
    assert "+0.320 s" in detail_text
    assert "Lectura histórica validada" in detail_text


def test_format_comparison_columns_falls_back_when_unavailable():
    view = {"available": False, "stage_status": "NO_EJECUTADA"}

    summary, hist_text, current_text, detail_text = format_comparison_columns(view)

    assert summary == "H5.2: NO_EJECUTADA"
    assert hist_text == "Sin comparación histórica."
    assert current_text == "Sin comparación histórica."
    assert "no tiene una comparación histórica H5.2" in detail_text
