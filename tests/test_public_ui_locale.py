import pytest

from public_ui_locale import (
    public_section_description,
    public_section_label,
    ui_text,
)
from race_engineer_gui import RaceEngineerApp, navigation_button_label, ui_state_message


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
