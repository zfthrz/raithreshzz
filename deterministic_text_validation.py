"""Shared deterministic validation for driver-facing text."""

import re

from deterministic_coaching import normalize_grounding_text


SPANISH_NUMBER_WORD_TOKEN = (
    r"(?:"
    r"cero|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|"
    r"diez|once|doce|trece|catorce|quince|dieciseis|diecisiete|"
    r"dieciocho|diecinueve|veinte|veintiuno|veintidos|veintitres|"
    r"veinticuatro|veinticinco|veintiseis|veintisiete|veintiocho|"
    r"veintinueve|treinta|cuarenta|cincuenta|sesenta|setenta|"
    r"ochenta|noventa|cien|ciento|doscientos|trescientos|"
    r"cuatrocientos|quinientos|seiscientos|setecientos|"
    r"ochocientos|novecientos|mil"
    r")"
)

SPANISH_NUMBER_WORD_SEQUENCE = (
    rf"{SPANISH_NUMBER_WORD_TOKEN}"
    rf"(?:\s+(?:y\s+)?{SPANISH_NUMBER_WORD_TOKEN}){{0,5}}"
)

SPANISH_SPELLED_MEASUREMENT_RE = re.compile(
    rf"\b{SPANISH_NUMBER_WORD_SEQUENCE}\s+"
    r"(?:"
    r"m|metros?|"
    r"s|segundos?|"
    r"por\s+ciento|"
    r"pp|puntos?\s+porcentuales?|"
    r"km/?h|kilometros?\s+por\s+hora|"
    r"unidades?(?:\s+de\s+input)?"
    r")\b"
)

SPANISH_SPELLED_IDENTIFIER_RE = re.compile(
    rf"\b(?:curva|vuelta|lap|episodio)\s+{SPANISH_NUMBER_WORD_SEQUENCE}\b"
)


def text_contains_number_word(value):
    """Detect prohibited written-out measurements and identifiers."""
    if not isinstance(value, str):
        return False

    normalized = normalize_grounding_text(value)
    return bool(
        SPANISH_SPELLED_MEASUREMENT_RE.search(normalized)
        or SPANISH_SPELLED_IDENTIFIER_RE.search(normalized)
    )


def text_contains_forbidden_numeric_content(value):
    """Return whether deterministic-authority numeric content is present."""
    if not isinstance(value, str):
        return False
    return bool(
        re.search(r"\d", value)
        or "%" in value
        or text_contains_number_word(value)
    )
