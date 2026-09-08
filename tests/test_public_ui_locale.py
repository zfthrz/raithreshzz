import pytest

from public_ui_locale import (
    public_section_description,
    public_section_label,
    ui_text,
)
from race_engineer_gui import navigation_button_label


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
