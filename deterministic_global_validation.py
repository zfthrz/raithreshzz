"""Backend-independent guardrails for deterministic global debrief text."""

from __future__ import annotations

import re

from deterministic_coaching import (
    _channels_mentioned_in_text,
    _explicit_command_direction_map,
    _steering_direct_action_present,
    normalize_grounding_text,
)
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


def validate_global_secondary_steering_text(value, field_name, plan, errors):
    if not _steering_direct_action_present(value):
        return
    labels = zone_labels_in_text(value)
    if len(labels) != 1:
        errors.append(
            f"{field_name}: steering_magnitude directo debe quedar anclado a una única zona A/B/C."
        )
        return
    label = next(iter(labels))
    item = next((item for item in (plan or [])[:3] if isinstance(item, dict) and str(item.get("plan_label") or "").strip().upper() == label), None)
    observed = set()
    for text in (item or {}).get("observed_differences", []) or []:
        observed.update(_channels_mentioned_in_text(text))
    cue_channels = {cue.get("channel") for cue in (item or {}).get("driver_cues", []) or [] if isinstance(cue, dict)}
    allowed = "steering_magnitude" in observed and "steering_magnitude" in cue_channels
    explicit = _explicit_command_direction_map(value).get("steering_magnitude")
    expected = None
    directions = set()
    for text in (item or {}).get("observed_differences", []) or []:
        normalized = normalize_grounding_text(text)
        if "direccion" in normalized or "volante" in normalized or "steering" in normalized:
            if "menor" in normalized or "menos" in normalized:
                directions.add("increase")
            if "mayor" in normalized or "mas" in normalized:
                directions.add("decrease")
    if len(directions) == 1:
        expected = next(iter(directions))
    if not allowed or (explicit is not None and explicit != expected):
        errors.append(
            f"{field_name}: steering_magnitude sólo puede convertirse en acción de zona {label} si Python lo incluyó explícitamente en driver_cues y la dirección respeta la evidencia observada."
        )


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
