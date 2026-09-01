"""Canonical pipeline stage names with read-only legacy compatibility."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEBRIEF_STAGE = "debrief"
DEBRIEF_VALIDATOR_STAGE = "debrief_validator"

LEGACY_TO_CANONICAL = {
    "llm": DEBRIEF_STAGE,
    "llm_validator": DEBRIEF_VALIDATOR_STAGE,
}
CANONICAL_TO_LEGACY = {
    canonical: legacy for legacy, canonical in LEGACY_TO_CANONICAL.items()
}


def canonical_stage_name(name: str) -> str:
    """Return the product name for a current or historical stage name."""
    return LEGACY_TO_CANONICAL.get(name, name)


def stage_payload(stages: Any, name: str) -> dict[str, Any]:
    """Read a canonical stage, falling back to its historical key.

    A present canonical payload always wins. This prevents a stale legacy entry
    from overriding a newer v0.4 result when both coexist in a state document.
    """
    if not isinstance(stages, Mapping):
        return {}
    canonical = stages.get(name)
    if isinstance(canonical, dict):
        return canonical
    legacy_name = CANONICAL_TO_LEGACY.get(name)
    legacy = stages.get(legacy_name) if legacy_name else None
    return legacy if isinstance(legacy, dict) else {}


def canonical_stage_names(*sources: Any) -> tuple[str, ...]:
    """Return stable, de-duplicated product names from ordered mappings."""
    names: list[str] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for raw_name in source:
            name = canonical_stage_name(str(raw_name))
            if name not in names:
                names.append(name)
    return tuple(names)
