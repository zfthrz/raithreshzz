from types import SimpleNamespace

import pytest

from public_ui_locale import (
    public_section_description,
    public_section_label,
    ui_text,
)
from race_engineer_gui import (
    RaceEngineerApp,
    compact_laps_text,
    format_comparison_columns,
    global_shortcuts,
    navigation_button_label,
    session_change_rows,
    plan_item_traceability_lines,
    session_status_detail_text,
    session_summary_values,
    session_status_tooltip,
    secondary_view_label,
    secondary_view_value,
    statistics_month_label,
    telemetry_choice_label,
    telemetry_choice_value,
    telemetry_comparison_sample_text,
    track_zone_summary_text,
    ui_state_message,
)
from race_engineer_ui_model import _historical_reference_text


def test_public_sections_translate_without_changing_internal_keys():
    assert public_section_label("Resumen", "en") == "Summary"
    assert public_section_label("Telemetría", "en") == "Telemetry"
    assert public_section_label("Historial", "en") == "History"
    assert public_section_label("Estadísticas", "en") == "Statistics"
    assert navigation_button_label("Telemetría", "en") == "Telemetry    Ctrl+2"
    assert navigation_button_label("Telemetría") == "Telemetría    Ctrl+2"


def test_public_section_descriptions_have_both_languages():
    assert "selected session" in public_section_description("Resumen", "en")
    assert "sesión seleccionada" in public_section_description("Resumen", "es")


def test_ui_text_validates_language_and_falls_back_only_by_explicit_choice():
    assert ui_text("es", "Actualizar", "Refresh") == "Actualizar"
    assert ui_text("en", "Actualizar", "Refresh") == "Refresh"
    with pytest.raises(ValueError, match="Unsupported debrief language"):
        ui_text("fr", "Actualizar", "Refresh")


def test_public_empty_states_have_complete_english_actions():
    assert ui_state_message("DEBRIEF_UNAVAILABLE", language="en") == (
        "No debrief is available.\n\nAnalyze the session again to generate one."
    )
    assert "Diagnóstico" not in ui_state_message(
        "LOAD_FAILED", compact=True, language="en"
    )


def test_summary_build_and_dynamic_readers_expose_english_variants():
    import inspect

    build = inspect.getsource(RaceEngineerApp._build_layout)
    cards = inspect.getsource(RaceEngineerApp._render_next_stint_cards)
    inspector = inspect.getsource(RaceEngineerApp._show_plan_inspector)
    dialogs = inspect.getsource(RaceEngineerApp._show_action_debrief)
    for expected in (
        "Executive session summary",
        "Actions only",
        "View full debrief",
        "KEY LAPS",
        "TRACK MAP",
        "TELEMETRY COMPARISON",
    ):
        assert expected in build
    assert "No next-stint plan is available" in cards
    assert "No authorized driving cue is available" in cards
    assert "WHY IT IS A PRIORITY" in inspector
    assert "Debrief · Actions only" in dialogs


def test_summary_statuses_are_rendered_from_codes_in_english():
    assert session_status_detail_text("FAILED", "Falló: analyze", "en") == (
        "Analysis failed"
    )
    assert session_summary_values(
        reference_time_s=90.0,
        valid_lap_count=4,
        has_historical_reference=True,
        has_historical_comparison=False,
        status="DEBRIEF_READY",
        language="en",
    )[2:] == ("Reference available", "Debrief ready")


def test_historical_changes_are_reconstructed_from_codes_in_english():
    rows = session_change_rows(
        {
            "status": "AVAILABLE",
            "grouped_changes": [
                {
                    "location_label": "T1 — First Corner",
                    "changes": [
                        {
                            "status": "REPEATED",
                            "match_basis": "physical_action_atom",
                            "action_family": "braking_point",
                            "coaching_direction": "later",
                            "presentation_label": "frenada más tarde",
                        },
                        {
                            "status": "NEW",
                            "match_basis": "reference_action_profile",
                            "channel": "throttle",
                            "presentation_label": "nuevo patrón de acelerador",
                        },
                    ],
                }
            ],
        },
        language="en",
    )
    assert rows[0]["changes"] == [
        {
            "status_label": "Still present",
            "presentation_label": "later braking point",
            "structured": False,
        },
        {
            "status_label": "New",
            "presentation_label": "new throttle pattern",
            "structured": True,
        },
    ]


def test_priority_traceability_is_reconstructed_in_english():
    assert plan_item_traceability_lines(
        {
            "comparisons": ["lap 2 vs 3"],
            "driver_cues": [
                {
                    "precision_evidence": [
                        {"reference_lap": 2, "supporting_laps": [3, 4]}
                    ]
                }
            ],
        },
        language="en",
    ) == (
        "Comparisons: lap 2 vs 3",
        "Cue evidence: reference lap 2; support lap 3, lap 4",
    )


def test_telemetry_choices_localize_without_changing_persisted_keys():
    assert telemetry_choice_label("Referencia sesión", "en") == "Session reference"
    assert telemetry_choice_label("Volante", "en") == "Steering"
    assert telemetry_choice_value("No comparison", "en") == "Sin comparación"
    assert telemetry_choice_value("Gear", "en") == "Marcha"
    assert telemetry_choice_value("Referencia sesión", "es") == "Referencia sesión"


def test_public_track_summary_has_complete_english_states():
    assert track_zone_summary_text(
        zone_count=0,
        loss_count=0,
        gain_count=0,
        focus_count=0,
        priority_count=0,
        profile_id=None,
        public_release=True,
        language="en",
    ).startswith("This track or layout is not available")
    assert track_zone_summary_text(
        zone_count=2,
        loss_count=1,
        gain_count=1,
        focus_count=1,
        priority_count=3,
        profile_id="spa_2022",
        public_release=True,
        language="en",
    ) == (
        "Comparison: 2 zones · losses: 1 · gains: 1 · focus areas: 1 · "
        "full plan: 3 · click a section for details."
    )


def test_point_comparison_has_an_explicit_english_rendering():
    sample = SimpleNamespace(
        current_speed_kmh=151.2,
        reference_speed_kmh=148.4,
        speed_delta_kmh=2.8,
        current_brake_percent=42.0,
        reference_brake_percent=51.0,
        brake_delta_percent=-9.0,
        current_throttle_percent=18.0,
        reference_throttle_percent=12.0,
        throttle_delta_percent=6.0,
        current_gear=4,
        reference_gear=3,
        current_steering_percent=-21.0,
        reference_steering_percent=-18.0,
        steering_delta_percent=-3.0,
        accumulated_delta_s=0.0842,
    )
    assert telemetry_comparison_sample_text(
        sample, "History H4", language="en"
    ) == (
        "Point comparison · current/History H4 · "
        "speed 151.2/148.4 km/h (+2.8 km/h) · "
        "brake 42.0/51.0% (-9.0%) · throttle 18.0/12.0% (+6.0%) · "
        "gear 4/3 · steering -21.0/-18.0% (-3.0%) · accumulated delta +0.084 s"
    )


def test_telemetry_workspace_uses_the_active_interface_language():
    import inspect

    build = inspect.getsource(RaceEngineerApp._track_map_tab)
    render = inspect.getsource(RaceEngineerApp._render_track_telemetry_chart)
    preferences = inspect.getsource(RaceEngineerApp._save_telemetry_preferences)
    for expected in ("Select a session", "Choose corner", "Compare with", "Reset view"):
        assert expected in build
    assert "Local delta · green gains time" in render
    assert "telemetry_choice_value(" in preferences


def test_secondary_view_labels_round_trip_to_stable_preference_keys():
    assert secondary_view_label("Referencia", "en") == "Reference"
    assert secondary_view_label("Mensual", "en") == "Monthly"
    assert secondary_view_value("Comparison", "en") == "Comparación"
    assert secondary_view_value("Overview", "en") == "General"
    assert statistics_month_label("Sin fecha", "en") == "No date"
    assert statistics_month_label("2026-09", "en") == "2026-09"


def test_main_history_comparison_has_explicit_english_chrome():
    summary, historical, current, detail = format_comparison_columns(
        {
            "available": True,
            "delta_text": "+0.120 s",
            "historical": {"session_id": 4, "lap": 2, "duration_text": "1:31.000"},
            "current": {"session_id": 8, "lap": 3, "duration_text": "1:31.120"},
            "zones": [],
        },
        language="en",
    )
    assert summary == "Current − historical delta: +0.120 s"
    assert historical.startswith("Historical session: #4\nLap: 2")
    assert current.startswith("Current session: #8\nLap: 3")
    assert detail == "No deterministic areas are available."
    assert _historical_reference_text(None, language="en") == (
        "This session does not have a historical reference yet."
    )


def test_main_statistics_workspace_uses_active_language_and_stable_month_key():
    import inspect

    panel = inspect.getsource(RaceEngineerApp._statistics_panel)
    apply = inspect.getsource(RaceEngineerApp._apply_statistics)
    month = inspect.getsource(RaceEngineerApp._open_statistics_month)
    navigation = inspect.getsource(RaceEngineerApp._remember_secondary_view)
    for expected in ("VALID LAPS", "FAVORITE TRACK", "MONTHLY HISTORY"):
        assert expected in panel
    assert "statistics_month_label(" in apply
    assert "self.statistics_month_keys.get(" in month
    assert "secondary_view_value(" in navigation


def test_public_shortcut_help_has_complete_english_descriptions():
    shortcuts = global_shortcuts(public_release=True, language="en")
    assert shortcuts[0] == ("Ctrl+1 … Ctrl+4", "Switch section")
    assert shortcuts[-1] == ("Ctrl+0", "Reset the Telemetry view")
    assert session_status_tooltip("FAILED", "en") == "A processing stage failed."
    assert "more laps in details" in compact_laps_text(
        "lap 1\nlap 2\nlap 3\nlap 4\nlap 5", max_rows=2, language="en"
    )


def test_public_dialogs_and_analysis_outcomes_have_english_variants():
    import inspect
    import race_engineer_gui

    picker = inspect.getsource(RaceEngineerApp._choose_analysis_file)
    finish = inspect.getsource(RaceEngineerApp._finish_analysis)
    close = inspect.getsource(RaceEngineerApp._on_close)
    help_dialog = inspect.getsource(RaceEngineerApp._show_shortcut_help)
    onboarding = inspect.getsource(race_engineer_gui._complete_public_first_run)
    assert "Select LMU telemetry" in picker
    assert "Analysis completed successfully" in finish
    assert "The analysis failed" in finish
    assert "An operation is running" in close
    assert "Keyboard shortcuts" in help_dialog
    assert "Use English for the application and new debriefs?" in onboarding
    assert "Select LMU telemetry folder" in onboarding
