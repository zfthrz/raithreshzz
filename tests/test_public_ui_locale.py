import pytest

from public_ui_locale import (
    public_section_description,
    public_section_label,
    ui_text,
)
from race_engineer_gui import (
    RaceEngineerApp,
    navigation_button_label,
    session_change_rows,
    plan_item_traceability_lines,
    session_status_detail_text,
    session_summary_values,
    ui_state_message,
)


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
