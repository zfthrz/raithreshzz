"""Deterministic comparison summary built from validated episode assessments."""

from __future__ import annotations

from collections.abc import Callable

from deterministic_coaching import (
    _channels_mentioned_in_text,
    _single_objective_channel_direction,
    _steering_direct_action_present,
    safe_int,
)


def comparison_secondary_steering_directions(episode_catalog):
    directions = set()
    for episode in episode_catalog or []:
        if not isinstance(episode, dict):
            continue
        if "steering_magnitude" not in set(
            episode.get("action_channels", []) or []
        ):
            continue
        direction = _single_objective_channel_direction(
            episode, "steering_magnitude"
        )
        if direction:
            directions.add(direction)
    return directions


def neutral_summary_recommendation(recommendation):
    if not isinstance(recommendation, str):
        return None
    channels = _channels_mentioned_in_text(recommendation)
    parts = []
    if "brake" in channels:
        parts.append("replicá la aplicación de freno hacia la referencia")
    if "throttle" in channels:
        parts.append("replicá la secuencia de acelerador hacia la referencia")
    if "steering_magnitude" in channels:
        parts.append("acompañá la dirección hacia la referencia")
    if not parts:
        return None
    text = "; ".join(parts).strip()
    if not text:
        return None
    return text[0].upper() + text[1:] + "."


def build_deterministic_comparison_summary(
    episode_assessments,
    episode_catalog,
    *,
    validate_summary: Callable,
):
    """Build the established fail-closed summary without transport or free text."""
    if not isinstance(episode_assessments, list):
        return None
    classification_order = {
        "PRIORITARIO": 0,
        "SECUNDARIO": 1,
        "NO_ACCIONABLE": 2,
    }
    ordered = sorted(
        [item for item in episode_assessments if isinstance(item, dict)],
        key=lambda item: (
            classification_order.get(item.get("classification"), 99),
            safe_int(item.get("episode_id")) or 999999,
        ),
    )
    observations = []
    for item in ordered:
        text = str(item.get("interpretation") or "").strip()
        if text and text not in observations:
            observations.append(text)
        if len(observations) >= 2:
            break

    conclusion = None
    for item in ordered:
        if item.get("classification") == "NO_ACCIONABLE":
            continue
        text = str(item.get("recommendation") or "").strip()
        if text:
            conclusion = text
            break
    if conclusion is None:
        for item in ordered:
            text = str(item.get("recommendation") or "").strip()
            if text:
                conclusion = text
                break
    if conclusion is None:
        for item in ordered:
            text = str(item.get("interpretation") or "").strip()
            if text:
                conclusion = text
                break
    if conclusion is None:
        return None

    candidate = {
        "comparison_observations": observations,
        "limitations": [],
        "conclusion": conclusion,
    }
    if not validate_summary(candidate, episode_catalog):
        return candidate

    directions = comparison_secondary_steering_directions(episode_catalog)
    if _steering_direct_action_present(conclusion) and len(directions) != 1:
        neutral = neutral_summary_recommendation(conclusion)
        if neutral:
            neutral_candidate = dict(candidate)
            neutral_candidate["conclusion"] = neutral
            if not validate_summary(neutral_candidate, episode_catalog):
                return neutral_candidate

    candidate["comparison_observations"] = []
    if not validate_summary(candidate, episode_catalog):
        return candidate
    if _steering_direct_action_present(conclusion) and len(directions) != 1:
        neutral = neutral_summary_recommendation(conclusion)
        if neutral:
            candidate["conclusion"] = neutral
            if not validate_summary(candidate, episode_catalog):
                return candidate
    return None
