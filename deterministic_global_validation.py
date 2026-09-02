"""Backend-independent guardrails for deterministic global debrief text."""

from __future__ import annotations

import re

from deterministic_coaching import normalize_grounding_text
CROSS_CHANNEL_TEMPORAL_PATTERNS = (
    r"\bsecuencia\s+(?:de|entre)\s+(?:el\s+)?freno\s*(?:y|con|->|→)\s*(?:el\s+)?acelerador\b",
    r"\bsecuencia\s+(?:de|entre)\s+(?:el\s+)?acelerador\s*(?:y|con|->|→)\s*(?:el\s+)?freno\b",
    r"\bsolap(?:amiento|ar|ados?|ada)?\b.{0,50}\bfreno\b.{0,50}\bacelerador\b",
    r"\bsolap(?:amiento|ar|ados?|ada)?\b.{0,50}\bacelerador\b.{0,50}\bfreno\b",
    r"\bfreno\b.{0,50}\bacelerador\b.{0,30}\bsin\s+solapamiento\b",
    r"\bacelerador\b.{0,50}\bfreno\b.{0,30}\bsin\s+solapamiento\b",
    r"\bprimero\s+(?:el\s+)?freno\b.{0,60}\bdespues\s+(?:el\s+)?acelerador\b",
    r"\bprimero\s+(?:el\s+)?acelerador\b.{0,60}\bdespues\s+(?:el\s+)?freno\b",
    r"\bfreno\s+primero\b.{0,60}\bacelerador\s+despues\b",
    r"\bacelerador\s+primero\b.{0,60}\bfreno\s+despues\b",
    r"\bfreno\s*(?:->|→)\s*acelerador\b",
    r"\bacelerador\s*(?:->|→)\s*freno\b",
    r"\bsepar(?:ar|a|e|á)\b.{0,60}\bfreno\b.{0,60}\bacelerador\b",
    r"\bsepar(?:ar|a|e|á)\b.{0,60}\bacelerador\b.{0,60}\bfreno\b",
    r"\bevit(?:ar|a|e|á)\b.{0,40}\bsolap",
    r"\bno\s+solap",
)


def zone_labels_in_text(value):
    if not isinstance(value, str):
        return set()
    return {
        label.upper()
        for label in re.findall(
            r"\bzona(?:\s+prioritaria)?\s+([a-z])\b",
            normalize_grounding_text(value),
        )
    }


def validate_temporal_observation_not_action_target(value, field_name, plan, errors):
    """Reject cross-channel temporal coaching unless Python authorized it."""
    if not isinstance(value, str):
        return
    normalized = normalize_grounding_text(value)
    if not any(re.search(pattern, normalized) for pattern in CROSS_CHANNEL_TEMPORAL_PATTERNS):
        return
    plan_by_label = {
        str(item.get("plan_label") or "").strip().upper(): item
        for item in (plan or [])[:3]
        if isinstance(item, dict) and item.get("plan_label")
    }
    labels = zone_labels_in_text(value)
    if labels and all(
        bool((plan_by_label.get(label) or {}).get("temporal_target"))
        for label in labels
    ):
        return
    errors.append(
        f"{field_name}: convierte una observación temporal de freno/acelerador "
        "en coaching sin temporal_target autorizado por Python."
    )
