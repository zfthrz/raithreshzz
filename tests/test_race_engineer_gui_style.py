from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
import race_engineer_gui as gui
from race_engineer_gui import (
    GUI_VERSION,
    GLOBAL_SHORTCUTS,
    PRIMARY_SECTIONS,
    SECTION_VIEWS,
    RaceEngineerApp,
    calibration_files_fingerprint,
    calibration_status_color,
    calibration_status_tag,
    calibration_status_tooltip,
    file_fingerprint,
    format_comparison_columns,
    historical_steering_zone_text,
    load_session_sort_preference,
    load_primary_section_preference,
    navigation_button_label,
    save_primary_section_preference,
    save_session_sort_preference,
    session_status_color,
    session_status_tooltip,
    sort_session_records,
    session_change_rows,
    session_summary_values,
    state_files_fingerprint,
    status_wraplength,
    telemetry_canvas_ready,
)
from race_engineer_track_map import TrackMapPoint, TrackMapZone


def test_historical_steering_zone_text_is_observational_and_exact():
    zone = TrackMapZone(
        "zone_001",
        "T1",
        "loss",
        100.0,
        200.0,
        0.2,
        "corner",
        140.0,
        100.0,
        2,
        1,
    )

    text = historical_steering_zone_text(zone)

    assert "observacional" in text
    assert "140.0/100.0 p.p./100 m" in text
    assert "cruces de signo 2/1" in text
    assert historical_steering_zone_text(
        TrackMapZone("zone_002", "T2", "gain", 200.0, 250.0, -0.1)
    ) == ""


def test_session_catalog_sorting_supports_visible_columns_and_missing_values():
    def record(key, timestamp, track, status, best):
        return SimpleNamespace(
            session_key=key,
            timestamp_utc=timestamp,
            modified_timestamp=1.0,
            track=track,
            status_detail=status,
            status=status,
            vehicle="Oreca 07",
            valid_lap_count=2,
            reference_time_s=best,
        )

    sessions = [
        record("b", "2026-08-30T10:00:00Z", "Spa", "Debrief", 130.0),
        record("a", "2026-08-31T10:00:00Z", "Monza", "Guardada", None),
        record("c", "2026-08-29T10:00:00Z", "Fuji", "Falló", 90.0),
    ]

    assert [item.session_key for item in sort_session_records(
        sessions, column="date", descending=True
    )] == ["a", "b", "c"]
    assert [item.session_key for item in sort_session_records(
        sessions, column="track", descending=False
    )] == ["c", "a", "b"]
    assert [item.session_key for item in sort_session_records(
        sessions, column="status", descending=False
    )] == ["b", "c", "a"]
    assert [item.session_key for item in sort_session_records(
        sessions, column="best", descending=False
    )] == ["c", "b", "a"]


def test_session_catalog_sort_preference_round_trip_and_fails_closed(tmp_path):
    path = tmp_path / "gui_preferences.json"

    assert load_session_sort_preference(path) == ("date", True)

    save_session_sort_preference(path, "track", False)
    assert load_session_sort_preference(path) == ("track", False)

    path.write_text(
        '{"session_sort_column": "unknown", "session_sort_descending": false}',
        encoding="utf-8",
    )
    assert load_session_sort_preference(path) == ("date", True)

    path.write_text("not json", encoding="utf-8")
    assert load_session_sort_preference(path) == ("date", True)

    with pytest.raises(ValueError):
        save_session_sort_preference(path, "unknown", False)


def test_workspace_preference_preserves_catalog_sort_and_fails_closed(tmp_path):
    path = tmp_path / "gui_preferences.json"
    save_session_sort_preference(path, "track", False)
    save_primary_section_preference(path, "Telemetría")

    assert load_primary_section_preference(path) == "Telemetría"
    assert load_session_sort_preference(path) == ("track", False)
    assert "Ctrl+1" in navigation_button_label("Resumen")
    assert "Ctrl+7" in navigation_button_label("Calibración")

    path.write_text('{"primary_section":"unknown"}', encoding="utf-8")
    assert load_primary_section_preference(path) == "Resumen"
    with pytest.raises(ValueError):
        save_primary_section_preference(path, "unknown")


def test_telemetry_pointer_selects_nearest_map_point_on_visible_axis():
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.current_track_map = SimpleNamespace(
        points=tuple(
            TrackMapPoint(0.0, 0.0, distance)
            for distance in (25.0, 75.0, 125.0)
        )
    )
    app.telemetry_zoom_range = (25.0, 125.0)
    app.track_telemetry_canvas = SimpleNamespace(winfo_width=lambda: 200)
    selected = []
    app._apply_track_point_selection = selected.append

    assert app._select_telemetry_point(128.0) is True
    assert selected == [1]
    assert app._select_telemetry_point(40.0) is False
    assert selected == [1]


def test_playback_tick_uses_wall_clock_independent_from_render_rate(monkeypatch):
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.track_playback_active = True
    app.track_playback_after_id = "pending"
    app.track_playback_started_at = 100.0
    app.track_playback_anchor_elapsed_s = 0.0
    app.track_playback_elapsed_s = 0.0
    app.current_track_map = SimpleNamespace(
        duration_s=0.100,
        points=(
            TrackMapPoint(0.0, 0.0, 0.0, elapsed_s=0.000),
            TrackMapPoint(1.0, 0.0, 1.0, elapsed_s=0.020),
            TrackMapPoint(2.0, 0.0, 2.0, elapsed_s=0.040),
            TrackMapPoint(3.0, 0.0, 3.0, elapsed_s=0.100),
        ),
    )
    selected = []
    displayed_times = []
    scheduled = []
    app._apply_track_point_selection = selected.append
    app._set_playback_time_status = displayed_times.append
    app._schedule_track_playback = lambda: scheduled.append(True)
    app._stop_track_playback = lambda: None
    monkeypatch.setattr(gui.time, "perf_counter", lambda: 100.027)

    app._tick_track_playback()

    assert selected == [1]
    assert app.track_playback_elapsed_s == pytest.approx(0.027)
    assert displayed_times == pytest.approx([0.027])
    assert scheduled == [True]


def test_playback_tick_stops_exactly_at_authoritative_lap_duration(monkeypatch):
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.track_playback_active = True
    app.track_playback_after_id = "pending"
    app.track_playback_started_at = 50.0
    app.track_playback_anchor_elapsed_s = 0.0
    app.track_playback_elapsed_s = 0.0
    app.current_track_map = SimpleNamespace(
        duration_s=1.234,
        points=(
            TrackMapPoint(0.0, 0.0, 0.0, elapsed_s=0.000),
            TrackMapPoint(1.0, 0.0, 1.0, elapsed_s=1.220),
        ),
    )
    selected = []
    displayed_times = []
    stopped = []
    app._apply_track_point_selection = selected.append
    app._set_playback_time_status = displayed_times.append
    app._schedule_track_playback = lambda: None
    app._stop_track_playback = lambda: stopped.append(True)
    monkeypatch.setattr(gui.time, "perf_counter", lambda: 51.500)

    app._tick_track_playback()

    assert selected == [1]
    assert app.track_playback_elapsed_s == 1.234
    assert displayed_times == [1.234]
    assert stopped == [True]


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
        self.scheduled = []
        self.cancelled = []
        self.destroyed = False

    def option_add(self, pattern, value):
        self.options[pattern] = value

    def after(self, delay, callback):
        self.scheduled.append((delay, callback))
        return f"after-{len(self.scheduled)}"

    def after_cancel(self, identifier):
        self.cancelled.append(identifier)

    def destroy(self):
        self.destroyed = True


class FakeTtk:
    def __init__(self, style):
        self.style = style

    def Style(self, _root):
        return self.style


def test_gui_applies_sidebar_dashboard_chrome_without_opening_window():
    style = FakeStyle()
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.root = FakeRoot()
    app.ttk = FakeTtk(style)

    app._configure_style()

    assert style.configurations["App.TFrame"]["background"] == "#0b1116"
    assert style.configurations["Panel.TFrame"]["background"] == "#111820"
    assert style.configurations["Sidebar.TFrame"]["background"] == "#071018"
    assert style.configurations["SidebarNavActive.TButton"]["foreground"] == "#00FFA6"
    assert style.configurations["WorkspaceTitle.TLabel"]["font"] == ("Segoe UI Semibold", 17)
    assert style.theme == "clam"
    assert style.configurations["TEntry"]["fieldbackground"] == "#15181c"
    assert style.configurations["TCombobox"]["borderwidth"] == 0
    assert style.configurations["DialogTitle.TLabel"]["font"] == ("Segoe UI Semibold", 16)
    assert style.configurations["TSeparator"]["background"] == "#343b42"
    assert style.configurations["Vertical.TScrollbar"]["width"] == 10
    assert style.configurations["Horizontal.TScrollbar"]["width"] == 10
    assert style.configurations["Treeview"]["rowheight"] == 30
    assert style.configurations["Treeview.Heading"]["relief"] == "flat"
    assert style.configurations["Treeview.Heading"]["foreground"] == "#9fb3c8"
    assert style.configurations["Horizontal.TProgressbar"]["thickness"] == 5
    assert style.configurations["H53Ready.TLabel"]["foreground"] == "#00FFA6"
    assert style.configurations["H53Pending.TLabel"]["foreground"] == "#f0c674"
    assert style.configurations["H53Error.TLabel"]["foreground"] == "#ff7b72"
    assert ("selected", "#315b60") in style.maps["Treeview"]["background"]
    assert ("selected", "#00FFA6") in style.maps["TNotebook.Tab"]["foreground"]
    assert ("selected", "#22282e") in style.maps["TNotebook.Tab"]["background"]
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
        "Estadísticas",
        "Circuitos",
        "Diagnóstico",
        "Calibración",
    )
    assert SECTION_VIEWS["Resumen"] == ("Debrief", "Próxima tanda", "Vueltas")
    assert SECTION_VIEWS["Historial"] == ("Referencia", "Comparación")
    assert SECTION_VIEWS["Estadísticas"] == ("General", "Mensual")
    assert SECTION_VIEWS["Circuitos"] == ("Readiness",)
    assert SECTION_VIEWS["Diagnóstico"] == ("Pipeline", "Ejecución")
    assert SECTION_VIEWS["Calibración"] == ("Calibración",)


def test_global_shortcuts_cover_navigation_search_refresh_and_escape():
    class BindingRoot:
        def __init__(self):
            self.bindings = {}

        def bind_all(self, sequence, callback):
            self.bindings[sequence] = callback

    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.root = BindingRoot()

    app._bind_global_shortcuts()

    for index in range(1, len(PRIMARY_SECTIONS) + 1):
        assert f"<Control-Key-{index}>" in app.root.bindings
    assert "<Control-f>" in app.root.bindings
    assert "<Control-r>" in app.root.bindings
    assert "<Escape>" in app.root.bindings
    assert "<F1>" in app.root.bindings


def test_shortcut_help_documents_every_global_action():
    assert GLOBAL_SHORTCUTS == (
        ("Ctrl+1 … Ctrl+7", "Cambiar de sección"),
        ("Ctrl+F", "Buscar una sesión"),
        ("Ctrl+R", "Actualizar la vista actual"),
        ("Esc", "Cerrar ayuda, inspector o tooltip"),
        ("F1", "Mostrar esta ayuda"),
    )
    build_source = inspect.getsource(RaceEngineerApp._build_layout)
    help_source = inspect.getsource(RaceEngineerApp._show_shortcut_help)
    dismiss_source = inspect.getsource(RaceEngineerApp._dismiss_transient_ui)

    assert 'text="Atajos de teclado · F1"' in build_source
    assert "for row, (shortcut, description) in enumerate(GLOBAL_SHORTCUTS" in help_source
    assert "self._hide_shortcut_help()" in dismiss_source


def test_contextual_refresh_shortcut_uses_current_workspace():
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    calls = []
    app.primary_section_var = SimpleNamespace(get=lambda: "Circuitos")
    app._refresh_track_readiness = lambda: calls.append("circuits")
    app._refresh_statistics = lambda: calls.append("statistics")
    app.refresh = lambda: calls.append("catalog")

    assert app._refresh_from_shortcut() == "break"
    assert calls == ["circuits"]

    app.primary_section_var = SimpleNamespace(get=lambda: "Estadísticas")
    app._refresh_from_shortcut()
    assert calls[-1] == "statistics"

    app.primary_section_var = SimpleNamespace(get=lambda: "Resumen")
    app._refresh_from_shortcut()
    assert calls[-1] == "catalog"


def test_layout_uses_fixed_sidebar_and_workspace_header():
    build_source = inspect.getsource(RaceEngineerApp._build_layout)
    show_source = inspect.getsource(RaceEngineerApp._show_primary_section)

    assert 'style="Sidebar.TFrame"' in build_source
    assert "sidebar.pack_propagate(False)" in build_source
    assert 'displaycolumns=("date", "track", "status")' in build_source
    assert "Threshzz's Telemetry" in build_source
    assert "Analysis Tool" in build_source
    assert 'self.workspace_title_var = tk.StringVar(value="Resumen")' in build_source
    assert 'self._calibration_panel(calibration_frame)' in build_source
    assert '"SidebarNavActive.TButton"' in show_source
    assert 'self.workspace_title_var.set(section)' in show_source


def test_summary_uses_one_vertical_scroll_container_for_all_blocks():
    build_source = inspect.getsource(RaceEngineerApp._build_layout)
    resize_source = inspect.getsource(RaceEngineerApp._on_summary_canvas_configure)
    content_source = inspect.getsource(RaceEngineerApp._on_summary_content_configure)

    assert "self.summary_canvas = tk.Canvas" in build_source
    assert "command=self.summary_canvas.yview" in build_source
    assert "window=summary_content" in build_source
    assert "width=event.width" in resize_source
    assert 'scrollregion=self.summary_canvas.bbox("all")' in content_source


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
    assert session_status_color("DEBRIEF_READY") == "#00FFA6"
    assert session_status_color("FAILED") == "#ff7b72"
    assert session_status_color("UNKNOWN") == "#9aa5ad"
    assert "Debrief validado" in session_status_tooltip("DEBRIEF_READY")
    assert "Falló en alguna etapa" in session_status_tooltip("FAILED")
    assert "no clasificado" in session_status_tooltip("UNKNOWN")
    assert "scheduler" in session_status_tooltip("HISTORY_READY")


def test_available_session_change_view_preserves_model_order_and_labels():
    view = {
        "status": "AVAILABLE",
        "grouped_changes": [{
            "location_label": "T1 — La Source",
            "changes": [
                {
                    "status": "REPEATED",
                    "match_basis": "physical_action_atom",
                    "presentation_label": "frenada mÃƒÂ¡s tarde",
                },
                {
                    "status": "NEW",
                    "match_basis": "physical_action_atom",
                    "presentation_label": "liberaciÃƒÂ³n de freno mÃƒÂ¡s temprano",
                },
                {
                    "status": "RESOLVED",
                    "match_basis": "physical_action_atom",
                    "presentation_label": "liberaciÃƒÂ³n de freno mÃƒÂ¡s tarde",
                },
                {
                    "status": "REPEATED",
                    "match_basis": "reference_action_profile",
                    "presentation_label": "patrÃƒÂ³n de acelerador repetido",
                },
            ],
        }],
    }

    rows = session_change_rows(view)

    assert rows == [{
        "location_label": "T1 — La Source",
        "changes": [
            {
                "status_label": "Se mantiene",
                "presentation_label": "frenada mÃƒÂ¡s tarde",
                "structured": False,
            },
            {
                "status_label": "Nuevo",
                "presentation_label": "liberaciÃƒÂ³n de freno mÃƒÂ¡s temprano",
                "structured": False,
            },
            {
                "status_label": "Ya no aparece",
                "presentation_label": "liberaciÃƒÂ³n de freno mÃƒÂ¡s tarde",
                "structured": False,
            },
            {
                "status_label": "Se mantiene",
                "presentation_label": "patrÃƒÂ³n de acelerador repetido",
                "structured": True,
            },
        ],
    }]
    rendered = " ".join(
        change["presentation_label"]
        for change in rows[0]["changes"]
    )
    assert "IMPROVED" not in rendered
    assert "WORSENED" not in rendered


def test_unavailable_session_change_view_has_no_visual_rows():
    assert session_change_rows({
        "status": "UNAVAILABLE",
        "reason": "no_previous_compatible_session",
        "grouped_changes": [{"location_label": "must not render"}],
    }) == []


def test_detail_defers_change_tracking_and_reuses_existing_full_catalog():
    source = inspect.getsource(RaceEngineerApp._show_detail)
    request_source = inspect.getsource(RaceEngineerApp._request_session_change_view)
    double_click_source = inspect.getsource(RaceEngineerApp._on_session_double_click)

    assert "load_session_detail(record)" in source
    assert "_request_session_change_view(record)" in source
    assert "discover_sessions" not in source
    assert "_render_session_changes(detail.session_change_view)" in source
    assert "list(self.all_sessions)" in request_source
    assert "discover_sessions" not in request_source
    assert "_cancel_session_change_request()" in double_click_source


def test_state_files_fingerprint_changes_only_for_run_state_files(tmp_path):
    runs = tmp_path / "runs"
    first = runs / "session-a" / "state.json"
    first.parent.mkdir(parents=True)
    first.write_text("{}", encoding="utf-8")

    baseline = state_files_fingerprint(runs)
    assert len(baseline) == 1
    assert baseline[0][0] == "session-a/state.json"

    unrelated = runs / "session-a" / "notes.txt"
    unrelated.write_text("ignored", encoding="utf-8")
    assert state_files_fingerprint(runs) == baseline

    second = runs / "session-b" / "state.json"
    second.parent.mkdir(parents=True)
    second.write_text("{}", encoding="utf-8")
    with_second = state_files_fingerprint(runs)
    assert with_second != baseline

    first.write_text('{"updated": true}', encoding="utf-8")
    assert state_files_fingerprint(runs) != with_second

    second.unlink()
    assert state_files_fingerprint(runs) != with_second


def test_optional_local_state_fingerprint_tracks_mtime_and_size(tmp_path):
    path = tmp_path / "telemetry_auto_ingest.json"
    assert file_fingerprint(path) is None
    path.write_text("{}", encoding="utf-8")
    baseline = file_fingerprint(path)
    assert baseline is not None
    path.write_text('{"files": {}}', encoding="utf-8")
    assert file_fingerprint(path) != baseline


def test_calibration_fingerprint_tracks_only_batch_status_files(tmp_path):
    batch = tmp_path / "batch-a"
    batch.mkdir()
    assert calibration_files_fingerprint(tmp_path) == ()
    (batch / "ignored.json").write_text("{}", encoding="utf-8")
    assert calibration_files_fingerprint(tmp_path) == ()
    (batch / "BATCH_STATUS.json").write_text("{}", encoding="utf-8")
    assert len(calibration_files_fingerprint(tmp_path)) == 1


def test_analysis_start_no_longer_warns_about_model_or_remote_cost():
    source = inspect.getsource(RaceEngineerApp._confirm_analysis)
    assert "Confirmar anÃƒÂ¡lisis" not in source
    assert "DeepSeek usa la API" not in source
    assert "Modelo:" not in source

def test_state_check_refreshes_only_after_change_and_reschedules(tmp_path):
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.root = FakeRoot()
    app.runs_root = tmp_path / "runs"
    app.runs_root.mkdir()
    app._closing = False
    app.analysis_running = False
    app._state_refresh_after_id = "current-check"
    app._state_files_fingerprint = state_files_fingerprint(app.runs_root)
    app.telemetry_ingest_state_path = tmp_path / "telemetry_auto_ingest.json"
    app.scheduler_runtime_path = tmp_path / "telemetry_scheduler_runtime.json"
    app.h3_import_maintenance_path = tmp_path / "h3_import_maintenance.json"
    app.h3_materialization_readiness_path = tmp_path / "h3_materialization.json"
    app.h3_automation_status_path = tmp_path / "h3_automation_status.json"
    app._scheduler_state_fingerprint = None
    app._refresh_scheduler_status = lambda: None
    app.calibration_batches_root = tmp_path / "calibration_batches"
    app._calibration_state_fingerprint = ()
    app._refresh_calibration_summary = lambda: None
    refreshes = []
    app.refresh = lambda: refreshes.append(True)

    app._check_for_state_updates()

    assert refreshes == []
    assert app._state_refresh_after_id == "after-1"

    state_path = app.runs_root / "new-session" / "state.json"
    state_path.parent.mkdir()
    state_path.write_text("{}", encoding="utf-8")
    app._state_refresh_after_id = "current-check"

    app._check_for_state_updates()

    assert refreshes == [True]
    assert app._state_refresh_after_id == "after-2"


def test_state_check_does_not_refresh_during_gui_analysis(tmp_path):
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.root = FakeRoot()
    app.runs_root = tmp_path / "runs"
    app.runs_root.mkdir()
    app._closing = False
    app.analysis_running = True
    app._state_refresh_after_id = "current-check"
    app._state_files_fingerprint = ()
    app.telemetry_ingest_state_path = tmp_path / "telemetry_auto_ingest.json"
    app.scheduler_runtime_path = tmp_path / "telemetry_scheduler_runtime.json"
    app.h3_import_maintenance_path = tmp_path / "h3_import_maintenance.json"
    app.h3_materialization_readiness_path = tmp_path / "h3_materialization.json"
    app._scheduler_state_fingerprint = None
    app._refresh_scheduler_status = lambda: None
    app.calibration_batches_root = tmp_path / "calibration_batches"
    app._calibration_state_fingerprint = ()
    app._refresh_calibration_summary = lambda: None
    refreshes = []
    app.refresh = lambda: refreshes.append(True)

    (app.runs_root / "session").mkdir()
    (app.runs_root / "session" / "state.json").write_text("{}", encoding="utf-8")
    app._check_for_state_updates()

    assert refreshes == []
    assert app._state_refresh_after_id == "after-1"


def test_scheduler_state_change_updates_badge_without_full_refresh(tmp_path):
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.root = FakeRoot()
    app.runs_root = tmp_path / "runs"
    app.runs_root.mkdir()
    app.telemetry_ingest_state_path = tmp_path / "telemetry_auto_ingest.json"
    app.scheduler_runtime_path = tmp_path / "telemetry_scheduler_runtime.json"
    app.h3_import_maintenance_path = tmp_path / "h3_import_maintenance.json"
    app.h3_materialization_readiness_path = tmp_path / "h3_materialization.json"
    app.telemetry_ingest_state_path.write_text('{"files": {}}', encoding="utf-8")
    app._closing = False
    app.analysis_running = False
    app._state_refresh_after_id = "current-check"
    app._state_files_fingerprint = state_files_fingerprint(app.runs_root)
    app._scheduler_state_fingerprint = None
    full_refreshes = []
    badge_refreshes = []
    app.refresh = lambda: full_refreshes.append(True)
    app._refresh_scheduler_status = lambda: badge_refreshes.append(True)
    app.calibration_batches_root = tmp_path / "calibration_batches"
    app._calibration_state_fingerprint = ()
    app._refresh_calibration_summary = lambda: None

    app._check_for_state_updates()

    assert full_refreshes == []
    assert badge_refreshes == [True]
    assert app._scheduler_state_fingerprint == (
        file_fingerprint(app.telemetry_ingest_state_path),
        None,
        None,
        None,
        None,
    )


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


def test_calibration_status_colors_and_tags():
    assert calibration_status_tag("CALIBRATED_PROVISIONAL_LOW_EVIDENCE") == "PROVISIONAL"
    assert calibration_status_tag("CALIBRATED_PROVISIONAL_SINGLE_CONTEXT") == "PROVISIONAL"
    assert calibration_status_tag("NO_CALIBRATION_FOR_CONTEXT") == "NO_CALIBRATION"
    assert calibration_status_tag("BLOCKED_BY_REAL_DATA") == "LEGACY"
    assert calibration_status_color("CALIBRATED_PROVISIONAL_LOW_EVIDENCE") == "#f0c674"
    assert calibration_status_color("NO_CALIBRATION_FOR_CONTEXT") == "#9aa5ad"
    assert calibration_status_color("BLOCKED_BY_REAL_DATA") == "#9aa5ad"
    assert "provisional" in calibration_status_tooltip(
        "CALIBRATED_PROVISIONAL_LOW_EVIDENCE"
    ).lower()
    assert "labelar" in calibration_status_tooltip("NO_CALIBRATION_FOR_CONTEXT")
    assert "legacy" in calibration_status_tooltip("BLOCKED_BY_REAL_DATA").lower()


def test_summary_dashboard_uses_three_simultaneous_columns_before_change_tracking():
    build_source = inspect.getsource(RaceEngineerApp._build_layout)
    assert 'summary_dashboard = ttk.Frame' in build_source
    assert 'debrief_column = ttk.Frame' in build_source
    assert 'plan_column = ttk.Frame' in build_source
    assert 'laps_column = ttk.Frame' in build_source
    assert '"VUELTAS CLAVE"' in build_source
    assert 'compact=True' in build_source
    assert build_source.index('self.debrief_text =') < build_source.index('self.session_change_panel =')
    assert build_source.index('self.plan_cards_frame =') < build_source.index('self.session_change_panel =')
    assert build_source.index('self.laps_text =') < build_source.index('self.session_change_panel =')


def test_initial_session_catalog_is_deferred_until_tk_mainloop():
    init_source = inspect.getsource(RaceEngineerApp.__init__)
    worker_source = inspect.getsource(RaceEngineerApp._start_initial_catalog_load)

    assert 'self.count_var.set("Cargando catálogo de sesiones…")' in init_source
    assert "self.root.after(" in init_source
    assert "self.refresh()" not in init_source
    assert "threading.Thread(" in worker_source
    assert "metadata_cache_path=self.session_metadata_cache_path" in worker_source


def test_track_readiness_is_lazy_and_runs_outside_tk_thread():
    panel_source = inspect.getsource(RaceEngineerApp._track_readiness_panel)
    refresh_source = inspect.getsource(RaceEngineerApp._refresh_track_readiness)
    poll_source = inspect.getsource(RaceEngineerApp._poll_track_readiness)

    assert "self._refresh_track_readiness()" not in panel_source
    assert "threading.Thread(" in refresh_source
    assert "build_track_readiness(project_root=PROJECT_ROOT)" in refresh_source
    assert "self._apply_track_readiness_payload(payload)" in poll_source


def test_history_statistics_are_lazy_read_only_and_run_outside_tk_thread():
    build_source = inspect.getsource(RaceEngineerApp._build_layout)
    show_source = inspect.getsource(RaceEngineerApp._show_primary_section)
    refresh_source = inspect.getsource(RaceEngineerApp._refresh_statistics)
    poll_source = inspect.getsource(RaceEngineerApp._poll_statistics)

    assert "self._refresh_statistics()" not in build_source
    assert 'section == "Estadísticas"' in show_source
    assert "threading.Thread(" in refresh_source
    assert "load_history_statistics(history_db)" in refresh_source
    assert "self._apply_statistics(statistics)" in poll_source
    panel_source = inspect.getsource(RaceEngineerApp._statistics_panel)
    assert 'style="MetricCard.TFrame"' in panel_source
    assert 'self.statistics_tree.bind("<Double-1>", self._open_statistics_month)' in panel_source
    detail_source = inspect.getsource(RaceEngineerApp._open_statistics_month)
    assert 'self.statistics_sessions_by_month.get(month, ())' in detail_source
    chart_source = inspect.getsource(RaceEngineerApp._redraw_statistics_chart)
    assert 'canvas.create_arc(' in chart_source
    assert 'text=f"{title} · POR VUELTAS VÁLIDAS"' in chart_source



