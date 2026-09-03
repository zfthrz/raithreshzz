"""Minimal structural tests for gui_theme.py centralized theme constants.

Verifies:
- Essential COLORS tokens are present
- Helper factories return deterministic dicts (no shared mutable state)
- No mutable default arguments or module-level side effects
"""

from __future__ import annotations

import copy
import pytest

import gui_theme


# ── Essential COLORS tokens ────────────────────────────────────────

ESSENTIAL_COLORS = [
    "app", "workspace", "panel", "sidebar", "tree", "tree_heading",
    "border", "border_light", "text_primary", "text_body", "text_muted",
    "text_card_label", "text_heading", "text_success", "text_error",
    "text_disabled", "h53_label", "priority_card", "inspector",
    "scrollbar_trough", "scrollbar_thumb", "scrollbar_hover",
]


@pytest.mark.parametrize("token", ESSENTIAL_COLORS)
def test_essential_color_tokens_present(token: str) -> None:
    """Each essential token key must exist in COLORS and be a 7-char hex string."""
    assert token in gui_theme.COLORS, f"{token} missing from COLORS"
    value = gui_theme.COLORS[token]
    assert isinstance(value, str), f"{token} is not a string"
    assert value.startswith("#") and len(value) == 7, \
        f"{token} value '{value}' is not a 7-character hex string"


# ── FONTS and TAG_FONTS structure ──────────────────────────────────

def test_fonts_are_tuples() -> None:
    """All FONTS values must be (family, size, weight) tuples or (family, size) tuples."""
    for name, spec in gui_theme.FONTS.items():
        assert isinstance(spec, tuple), f"FONTS[{name}] is not a tuple"
        assert len(spec) >= 2, f"FONTS[{name}] has fewer than 2 elements"
        assert isinstance(spec[0], str), f"FONTS[{name}].family is not a string"
        assert isinstance(spec[1], int), f"FONTS[{name}].size is not an int"


def test_tag_fonts_are_tuples() -> None:
    """All TAG_FONTS values must be (family, size) tuples."""
    for name, spec in gui_theme.TAG_FONTS.items():
        assert isinstance(spec, tuple), f"TAG_FONTS[{name}] is not a tuple"
        assert len(spec) == 2, f"TAG_FONTS[{name}] does not have exactly 2 elements"
        assert isinstance(spec[0], str), f"TAG_FONTS[{name}].family is not a string"
        assert isinstance(spec[1], int), f"TAG_FONTS[{name}].size is not an int"


# ── Helper determinism (no shared mutable state) ───────────────────

@pytest.mark.parametrize("fn", [
    gui_theme.text_defaults,
    gui_theme.text_accent_defaults,
    gui_theme.readonly_defaults,
    gui_theme.comparison_defaults,
])
def test_helper_returns_fresh_dict(fn) -> None:
    """Each helper call must return a new dict (no shared mutable state across calls)."""
    result1 = fn()
    result2 = fn()
    assert result1 is not result2, f"{fn.__name__} returns the same dict object"
    # Mutating one must not affect the other
    result1["test_key"] = True
    assert "test_key" not in result2, \
        f"{fn.__name__} shares mutable state between calls"


@pytest.mark.parametrize("fn", [
    gui_theme.text_defaults,
    gui_theme.text_accent_defaults,
])
def test_helper_compact_mode(fn) -> None:
    """Helpers must respect compact=True flag."""
    normal = fn(compact=False)
    compact = fn(compact=True)
    assert normal["padx"] > compact["padx"], \
        f"{fn.__name__}(compact=True) did not reduce padx"
    assert normal["pady"] > compact["pady"], \
        f"{fn.__name__}(compact=True) did not reduce pady"


# ── COLORS immutability check ──────────────────────────────────────

def test_colors_dict_is_not_mutated_by_helpers() -> None:
    """Helper factories must not mutate COLORS themselves."""
    import gui_theme
    # Take a snapshot of COLORS keys
    keys_before = set(gui_theme.COLORS.keys())
    # Call all helpers
    gui_theme.text_defaults()
    gui_theme.text_accent_defaults()
    gui_theme.readonly_defaults()
    gui_theme.comparison_defaults()
    keys_after = set(gui_theme.COLORS.keys())
    assert keys_before == keys_after, \
        "Helper calls mutated COLORS keys"


# ── race_engineer_gui imports theme ────────────────────────────────

def test_gui_imports_colors() -> None:
    """race_engineer_gui must import COLORS from gui_theme."""
    import race_engineer_gui as gui_module
    assert hasattr(gui_module, "COLORS"), \
        "race_engineer_gui does not import COLORS from gui_theme"
    assert isinstance(gui_module.COLORS, dict), \
        "COLORS in race_engineer_gui is not a dict"


# ── Regression: gui_theme helpers must be importable by race_engineer_gui ──

REQUIRED_GUI_THEME_NAMES = [
    "COLORS",
    "FONTS",
    "FONT_FAMILY",
    "FONT_FAMILY_BOLD",
    "TAG_FONTS",
    "text_defaults",
    "text_accent_defaults",
    "readonly_defaults",
    "comparison_defaults",
]


def test_gui_theme_names_available_in_gui_module() -> None:
    """Every gui_theme export used by race_engineer_gui must be importable.

    This test catches the exact crash that v1.60 introduced:
    ``NameError: name 'text_defaults' is not defined`` inside
    ``_summary_text_panel()`` when ``RaceEngineerApp.__init__`` calls
    ``self._summary_text_panel(...)``.

    It also prevents future regressions when a new helper or token is
    added to gui_theme.py and forgotten in the race_engineer_gui import.
    """
    import race_engineer_gui as gui_module

    missing: list[str] = []
    for name in REQUIRED_GUI_THEME_NAMES:
        if not hasattr(gui_module, name):
            missing.append(name)

    assert not missing, \
        f"race_engineer_gui missing gui_theme imports: {', '.join(missing)}"


def test_gui_theme_names_match_gui_theme_exports() -> None:
    """The gui_module namespace must actually contain the helpers, not just
    the name (catches ``from gui_theme import X`` when X is not callable)."""
    import race_engineer_gui as gui_module

    for name in ("text_defaults", "text_accent_defaults", "readonly_defaults",
                 "comparison_defaults"):
        fn = getattr(gui_module, name, None)
        assert callable(fn), \
            f"{name} in race_engineer_gui is not callable (expected gui_theme helper)"

    for name in ("COLORS", "FONTS", "TAG_FONTS"):
        val = getattr(gui_module, name, None)
        assert isinstance(val, dict), \
            f"{name} in race_engineer_gui is not a dict"
