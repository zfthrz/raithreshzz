"""Centralized visual theme constants for Race Engineer GUI.

All hex colors, font specifications, padding values, and spacing scales
used by race_engineer_gui.py are defined here so that consistency
improvements (GUI v1.60) can audit and update every visual contract
in a single pass.

Public API
----------
COLORS — mapping of named palette entries to hex strings.
FONTS — dict of named font specs ``(family, size, weight)``.
PAD_NORMAL, PAD_COMPACT — ``(y, x)`` tuples for panel/card padding.
SPACING — normal/compact spacing tuples for margins between elements.
TEXT_WIDGET_DEFAULTS — keyword-argument dict for Text widget creation.
"""

from __future__ import annotations

# ── Color palette ──────────────────────────────────────────────────
# Backgrounds are ordered by depth: darker → lighter.

COLORS: dict[str, str] = {
    # Surface depths
    "sidebar":           "#071018",
    "app":               "#0b1116",
    "workspace":         "#0b1116",
    "workspace_nav":     "#0f161d",
    "panel":             "#111820",
    "summary_card":      "#141c23",
    "inspector":         "#14191c",
    "summary_accent":    "#14211f",
    "summary_change":    "#151d24",
    "readonly_pane":     "#15181c",
    "track_map":         "#0b0e10",
    "comparison_pane":   "#0d141a",
    "statistics_canvas": "#11171a",
    # Cards
    "metric_card":       "#171a1d",
    "priority_card":     "#172421",
    "inspector_card":    "#14191c",
    "h53_label":         "#1c1c1c",
    # Textures
    "tree":              "#171717",
    "tree_odd":          "#1b1f23",
    "tree_heading":      "#2a2a2a",
    # Borders
    "border":            "#343b42",
    "border_light":      "#27323a",
    "border_priority":   "#28403b",
    "border_accent":     "#24413d",
    "border_summary":    "#26343d",
    "border_map":        "#2d343a",
    # Scrollbar troughs
    "scrollbar_trough":  "#15181c",
    "scrollbar_thumb":   "#39434b",
    # Interactive states
    "scrollbar_hover":   "#53616b",
    "scrollbar_active":  "#00FFA6",
    "nav_hover":         "#20262b",
    "nav_pressed":       "#252c31",
    "nav_active_bg":     "#123138",
    "nav_active_hover":  "#2b3a40",
    "sidebar_hover":     "#101c24",
    "sidebar_pressed":   "#14242c",
    "sidebar_active_bg": "#0a3338",
    "sidebar_active_hover": "#104148",
    "button_disabled":   "#1f2225",
    # Text colors
    "text_primary":      "#f2f7fb",
    "text_body":         "#dce7ef",
    "text_muted":        "#91a6b8",
    "text_secondary":    "#8fa5b8",
    "text_subtle":       "#8399a8",
    "text_subaccent":    "#8eaaa5",
    "text_success":      "#00FFA6",
    "text_warning":      "#f0c674",
    "text_error":        "#ff7b72",
    "text_disabled":     "#69747d",
    "text_card_label":   "#7f929f",
    "text_heading":      "#9fb3c8",
    "text_tree_selected_bg":    "#315b60",
    "text_tree_selected_fg":    "#f4fbff",
    "text_carbon":       "#c5d3da",
    "text_highlight":    "#7af1df",
}

# ── Font hierarchy ─────────────────────────────────────────────────
# Families use system defaults; weights use named constants.

FONT_FAMILY = "Segoe UI"
FONT_FAMILY_BOLD = "Segoe UI Semibold"

# ``(family, size, weight)`` specs used by style.configure / Text tag.
FONTS = {
    "title_large":    (FONT_FAMILY_BOLD, 18),
    "title":          (FONT_FAMILY_BOLD, 16),
    "title_workspace":(FONT_FAMILY_BOLD, 17),
    "title_inspector":(FONT_FAMILY_BOLD, 13),
    "title_summary":  (FONT_FAMILY_BOLD, 11),
    "title_priority": (FONT_FAMILY_BOLD, 11),
    "heading":        (FONT_FAMILY_BOLD, 10),
    "heading_small":  (FONT_FAMILY_BOLD, 8),
    "heading_nav":    (FONT_FAMILY_BOLD, 10),
    "body":           (FONT_FAMILY, 10),
    "body_small":     (FONT_FAMILY, 9),
    "body_xs":        (FONT_FAMILY, 8),
    "button":         (FONT_FAMILY_BOLD, 10),
}

# ── Padding / spacing scale ────────────────────────────────────────
# Normal (non-compact) defaults.

PAD_NORMAL_Y = 12
PAD_NORMAL_X = 16
PAD_COMPACT_Y = 11
PAD_COMPACT_X = 14

PAD_NORMAL = (PAD_NORMAL_X, PAD_NORMAL_Y)
PAD_COMPACT = (PAD_COMPACT_X, PAD_COMPACT_Y)

# Text widget internal padding — ``(x, y)`` for ``padx``/``pady`` kwargs.
TEXT_PAD_NORMAL = (14, 12)
TEXT_PAD_COMPACT = (10, 8)
TEXT_PAD_LARGE = (18, 16)

# Spacing between child widgets inside a card (``pady`` tuples).
SPACING_CARD_HEADER = (0, 8)
SPACING_CARD_SUBTITLE = (2, 0)
SPACING_CARD_BODY_NORMAL = (0, 12)
SPACING_CARD_BODY_COMPACT = (0, 8)
SPACING_CARD_SECTION = (0, 10)
SPACING_CARD_SECTION_SMALL = (0, 8)

# ── Text tag font specs ────────────────────────────────────────────
# ``(family, size)`` tuples for text.tag_configure.

TAG_FONTS = {
    "h1":     (FONT_FAMILY_BOLD, 18),
    "h2":     (FONT_FAMILY_BOLD, 14),
    "h2_compact": (FONT_FAMILY_BOLD, 12),
    "h3":     (FONT_FAMILY_BOLD, 11),
}

# ── Text widget defaults ──────────────────────────────────────────
# Keyword arguments reused across all Text widget instances.

def text_defaults(
    *,
    compact: bool = False,
    h2_size: int | None = None,
) -> dict:
    """Build keyword-argument dict for Text widget creation.

    Parameters
    ----------
    compact : bool
        When ``True`` reduces font size, padding and spacing.
    h2_size : int or None
        Override the heading-2 font size (defaults to 12 when compact,
        14 otherwise).

    Returns
    -------
    dict
        Ready-to-apply keyword arguments.
    """
    pad_x, pad_y = (TEXT_PAD_COMPACT if compact else TEXT_PAD_NORMAL)
    return {
        "wrap": "word",
        "background": COLORS["summary_card"],
        "foreground": COLORS["text_body"],
        "insertbackground": COLORS["text_success"],
        "selectbackground": COLORS["text_tree_selected_bg"],
        "selectforeground": COLORS["text_tree_selected_fg"],
        "relief": "flat",
        "borderwidth": 0,
        "highlightthickness": 0,
        "padx": pad_x,
        "pady": pad_y,
        "font": (FONT_FAMILY, 9 if compact else 10),
        "spacing1": 1 if compact else 2,
        "spacing3": 3 if compact else 4,
        "_h2_size": h2_size if h2_size is not None else (12 if compact else 14),
    }


# ── Accent text widget defaults ────────────────────────────────────
def text_accent_defaults(
    *,
    compact: bool = False,
) -> dict:
    """Text widget defaults for accent (green-tinted) cards."""
    defaults = text_defaults(compact=compact)
    defaults["background"] = COLORS["summary_accent"]
    return defaults


# ── Readonly pane defaults ────────────────────────────────────────
def readonly_defaults() -> dict:
    """Text widget defaults for the standalone readonly pane."""
    return {
        "wrap": "word",
        "background": COLORS["readonly_pane"],
        "foreground": COLORS["text_body"],
        "insertbackground": COLORS["text_success"],
        "selectbackground": COLORS["text_tree_selected_bg"],
        "selectforeground": COLORS["text_tree_selected_fg"],
        "relief": "flat",
        "borderwidth": 0,
        "highlightthickness": 0,
        "padx": TEXT_PAD_LARGE[0],
        "pady": TEXT_PAD_LARGE[1],
        "font": (FONT_FAMILY, 10),
        "spacing1": 2,
        "spacing3": 4,
    }


# ── Comparison pane defaults ──────────────────────────────────────
def comparison_defaults() -> dict:
    """Text widget defaults for the comparison pane."""
    return {
        "wrap": "word",
        "background": COLORS["comparison_pane"],
        "foreground": COLORS["text_body"],
        "insertbackground": COLORS["text_success"],
        "selectbackground": COLORS["text_tree_selected_bg"],
        "selectforeground": COLORS["text_tree_selected_fg"],
        "relief": "flat",
        "borderwidth": 0,
        "highlightthickness": 0,
        "padx": TEXT_PAD_LARGE[0],
        "pady": TEXT_PAD_LARGE[1],
        "font": (FONT_FAMILY, 10),
        "spacing1": 2,
        "spacing3": 4,
    }
