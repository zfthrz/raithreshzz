# GUI v1.60 — Centralized theme constants

**Date:** 2026-09-03
**Author:** Race Engineer repository agent

## Summary

GUI v1.60 introduces centralized theme constants for all widget-level visual
contracts. All hardcoded hex color strings and font tuples in
`race_engineer_gui.py` are replaced with references from the new
`gui_theme.py` module.

## New file

- `gui_theme.py` — single source of truth for:
  - `COLORS` — named palette dict (~60 hex entries)
  - `FONTS` — named font specs `(family, size, weight)`
  - `TAG_FONTS` — `Text.tag_configure` font specs `(family, size)`
  - `PAD_NORMAL`, `PAD_COMPACT` — `(y, x)` padding tuples
  - `SPACING_*` — margin constants
  - `text_defaults()`, `text_accent_defaults()`, `readonly_defaults()`, `comparison_defaults()` — keyword-argument factories for Text widgets

## Changes in `race_engineer_gui.py`

### Widget backgrounds

All widget-level `background` attributes now reference `COLORS["..."]`:

- `root.configure(background=COLORS["app"])`
- Combobox listbox → `COLORS["app"]`
- Summary preview canvas → `COLORS["workspace_nav"]`
- `_summary_text_panel` Text (both accent and normal) → `text_defaults()` / `text_accent_defaults()`
- `_readonly_pane` Text → `readonly_defaults()`
- `_track_map_tab` Canvas → `COLORS["track_map"]`
- Analysis result window → `COLORS["app"]`
- Analysis result panel Text → `COLORS["summary_card"]`
- Session catalog tree → `COLORS["tree"]`
- Scheduler diagnostic Text → `COLORS["tree"]`
- Canvas fill for ignored regions → `COLORS["tree"]`

### Widget fonts

All `Text.tag_configure` calls now reference `FONTS["..."]` or `TAG_FONTS["..."]`:

- `h1` → `TAG_FONTS["h1"]` (bold, 18)
- `h2` → `TAG_FONTS["h2"]` (bold, 14) or `(FONT_FAMILY_BOLD, 12 if compact else 14)`
- `h3` → `TAG_FONTS["h3"]` (bold, 11)
- Section tag in inspector → `FONTS["heading"]`
- Value tag in inspector → `(FONT_FAMILY, 9)`
- Summary panel heading tags → `TAG_FONTS["h1"]` / `FONTS["title"]` / `FONTS["heading"]`

### TStyle font references

- `InspectorClose.TLabel` → `FONTS["title_inspector"]`
- `PriorityFocus.TLabel` → `FONTS["heading_small"]`

### Treeview row tags

- `tree.tag_configure("row_even", background=COLORS["tree"])` — replaced in both statistics and session catalog trees.

## Canvas data visualization colors

Domain-specific encoding colors (speed blue, throttle green, brake red, zone
loss/gain/observation) remain as hex literals — these are data semantics, not
theme colors.

## GUI_VERSION

Updated from `"1.59"` to `"1.60"`.

## Backward compatibility

No behavioral changes. The same widgets, layout, and navigation structure remain.
Only the visual contract source of truth moved from inline literals to
`gui_theme.py`.

## Testing

- `py_compile race_engineer_gui.py` — verify syntax
- `pytest` — verify all existing tests pass
- Regression test: run `race_engineer.py analyze` with a telemetry file and confirm GUI launches with identical appearance

## Files changed

| File | Change |
|---|---|
| `gui_theme.py` | **CREATED** — centralized theme constants |
| `race_engineer_gui.py` | **MODIFIED** — import `COLORS`, `FONTS`, `TAG_FONTS`; replace ~190+ hardcoded hex and font literals |
| `README.md` | Updated with v1.60 checkpoint note |
| `PROJECT_CONTEXT.md` | Updated component table row for GUI |
