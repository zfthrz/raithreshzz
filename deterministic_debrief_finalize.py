"""Backend-neutral finalization of a validated deterministic debrief."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


GLOBAL_AUDIT_FIELDS = (
    "status",
    "attempts",
    "fallback",
    "deterministic_repairs",
    "pruned_global_items",
    "llm_validation_errors",
)


def finalize_validated_global_debrief(
    *,
    global_validated: dict[str, Any],
    metadata: dict[str, Any],
    comparison_results: list[dict[str, Any]],
    session_coaching_facts: dict[str, Any],
    track_location_context: dict[str, Any],
    render_global: Callable[..., str],
    render_track_reference: Callable[..., str],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Return structured payload, compact audit and established final render."""
    if global_validated.get("status") != "VALID":
        raise ValueError("global response must be VALID before finalization")

    structured = global_validated.get("response")
    if not isinstance(structured, dict):
        raise ValueError("validated global response must contain a response object")

    audit = {
        key: global_validated.get(key)
        for key in GLOBAL_AUDIT_FIELDS
        if global_validated.get(key) not in (None, {}, [])
    }
    analysis = render_global(
        metadata,
        comparison_results,
        session_coaching_facts,
        structured,
    )
    track_section = render_track_reference(
        track_location_context.get("profile"),
        session_coaching_facts.get("next_stint_plan"),
    )
    if track_section:
        analysis = analysis.rstrip() + "\n\n" + track_section

    return structured, audit, analysis
