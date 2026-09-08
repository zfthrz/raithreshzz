"""Presentation-only localization for the public desktop interface."""

from __future__ import annotations

from debrief_language import require_language


PUBLIC_SECTION_LABELS = {
    "es": {
        "Resumen": "Resumen",
        "Telemetría": "Telemetría",
        "Historial": "Historial",
        "Estadísticas": "Estadísticas",
    },
    "en": {
        "Resumen": "Summary",
        "Telemetría": "Telemetry",
        "Historial": "History",
        "Estadísticas": "Statistics",
    },
}

PUBLIC_SECTION_DESCRIPTIONS = {
    "es": {
        "Resumen": "Debrief, plan de próxima tanda y vueltas clave de la sesión seleccionada.",
        "Telemetría": "Mapa del circuito y canales de telemetría de la sesión seleccionada.",
        "Historial": "Referencia histórica y comparación contextual validada.",
        "Estadísticas": "Uso acumulado y mensual calculado desde History.",
    },
    "en": {
        "Resumen": "Debrief, next-stint plan, and key laps for the selected session.",
        "Telemetría": "Track map and telemetry channels for the selected session.",
        "Historial": "Historical reference and validated contextual comparison.",
        "Estadísticas": "Overall and monthly usage calculated from History.",
    },
}


def ui_text(language: str, spanish: str, english: str) -> str:
    return english if require_language(language) == "en" else spanish


def public_section_label(section: str, language: str) -> str:
    require_language(language)
    return PUBLIC_SECTION_LABELS[language].get(section, section)


def public_section_description(section: str, language: str) -> str:
    require_language(language)
    return PUBLIC_SECTION_DESCRIPTIONS[language].get(section, "")
