"""Grounded deterministic response for one authorized driving episode."""

from __future__ import annotations

from deterministic_coaching import _channel_direction_phrase


def channel_direction_contract(episode):
    result = {}
    for channel in episode.get("action_channels", []) or []:
        info = (episode.get("action_evidence_by_channel", {}) or {}).get(
            channel, {}
        )
        directions = {
            event.get("direction")
            for event in info.get("events", []) or []
            if event.get("direction")
            in {"higher_in_comparison_lap", "lower_in_comparison_lap"}
        }
        if directions == {"higher_in_comparison_lap"}:
            result[channel] = {
                "observed_relation": "higher_in_comparison_lap",
                "interpretation_relation": "higher",
                "coaching_direction": "decrease",
            }
        elif directions == {"lower_in_comparison_lap"}:
            result[channel] = {
                "observed_relation": "lower_in_comparison_lap",
                "interpretation_relation": "lower",
                "coaching_direction": "increase",
            }
        elif len(directions) > 1:
            result[channel] = {
                "observed_relation": "mixed",
                "interpretation_relation": "mixed",
                "coaching_direction": "replicate_sequence",
            }
    return result


def deterministic_episode_recommendation(episode):
    contract = channel_direction_contract(episode)
    labels = {
        ("brake", "increase"): (
            "aumentar la aplicación del freno hacia la referencia"
        ),
        ("brake", "decrease"): (
            "reducir la aplicación del freno hacia la referencia"
        ),
        ("brake", "replicate_sequence"): (
            "replicar la secuencia y modulación del freno de la referencia"
        ),
        ("throttle", "increase"): "aumentar el acelerador hacia la referencia",
        ("throttle", "decrease"): "reducir el acelerador hacia la referencia",
        ("throttle", "replicate_sequence"): (
            "replicar la secuencia y modulación del acelerador de la referencia"
        ),
    }
    parts = []
    for channel in episode.get("action_channels", []) or []:
        info = contract.get(channel, {}) if isinstance(contract, dict) else {}
        text = labels.get((channel, info.get("coaching_direction")))
        if text and text not in parts:
            parts.append(text)
    if not parts:
        return (
            "mantener esta diferencia como observación; "
            "no hay un target directo de input autorizado"
        )
    return "; ".join(parts)


def build_grounded_episode_response(episode):
    channels = list(episode.get("action_channels", []) or [])
    evidence_by_channel = episode.get("action_evidence_by_channel", {}) or {}
    phrases = []
    for channel in channels:
        phrase = _channel_direction_phrase(
            channel,
            evidence_by_channel.get(channel, {}),
        )
        if phrase:
            phrases.append(phrase)
    if not phrases:
        return None
    if len(phrases) == 1:
        observation = phrases[0]
    elif len(phrases) == 2:
        observation = f"{phrases[0]} y {phrases[1]}"
    else:
        observation = ", ".join(phrases[:-1]) + f" y {phrases[-1]}"
    recommendation = deterministic_episode_recommendation(episode)
    if not recommendation:
        return None
    return {
        "episode_id": episode.get("episode_id"),
        "interpretation": (
            f"se observaron {observation} respecto de la vuelta de referencia"
        ),
        "hypotheses": [],
        "recommendation": recommendation,
    }
