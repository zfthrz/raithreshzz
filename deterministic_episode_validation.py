"""Backend-independent validation for one deterministic episode response."""

from __future__ import annotations

import re

from deterministic_coaching import (
    CHANNEL_LANGUAGE_PATTERNS,
    _explicit_directional_clauses,
    _single_objective_channel_direction,
    _steering_direct_action_present,
    normalize_grounding_text,
    safe_int,
)
from deterministic_summary_validation import (
    validate_grounded_text,
    validate_grounded_text_list,
    validate_reference_lap_is_action_target,
    validate_speed_not_action_target,
    validate_text_list,
)
from deterministic_text_validation import text_contains_forbidden_numeric_content


FACTUAL_HIGHER_SIGNAL_RE = re.compile(
    r"\b(?:mayor|superior|elevad[oa]s?|aumento|aumentad[oa]s?|"
    r"incremento|incrementad[oa]s?|mas(?!\s+(?:tarde|temprano|antes|despues)))\b"
)
FACTUAL_LOWER_SIGNAL_RE = re.compile(
    r"\b(?:menor|inferior|reducid[oa]s?|reduccion|disminuid[oa]s?|disminucion|menos)\b"
)


def explicit_factual_direction_by_channel(value):
    """Extract only unambiguous one-channel, one-direction assertions."""
    if not isinstance(value, str):
        return {}
    normalized = normalize_grounding_text(value)
    parts = re.split(
        r"(?:[.;:\n]+|,\s*(?:mientras(?:\s+que)?|pero|aunque|luego|despues|posteriormente)\s+|"
        r"\s+\b(?:mientras(?:\s+que)?|pero|aunque|luego|despues|posteriormente)\b\s+|\s+\by\b\s+)",
        normalized,
    )
    assertions = {}
    for phrase in (part.strip(" ,") for part in parts if part.strip(" ,")):
        channels = {
            channel
            for channel, patterns in CHANNEL_LANGUAGE_PATTERNS.items()
            if any(re.search(pattern, phrase) for pattern in patterns)
        }
        directions = set()
        if FACTUAL_HIGHER_SIGNAL_RE.search(phrase):
            directions.add("higher_in_comparison_lap")
        if FACTUAL_LOWER_SIGNAL_RE.search(phrase):
            directions.add("lower_in_comparison_lap")
        if len(channels) == 1 and len(directions) == 1:
            assertions.setdefault(next(iter(channels)), set()).add(
                next(iter(directions))
            )
    return {
        channel: next(iter(directions))
        for channel, directions in assertions.items()
        if len(directions) == 1
    }


def validate_episode_interpretation_direction(interpretation, episode, errors):
    if not isinstance(interpretation, str):
        return
    for channel, asserted in explicit_factual_direction_by_channel(interpretation).items():
        observed = _single_objective_channel_direction(episode, channel)
        if observed is None or asserted == observed:
            continue
        human = {
            "brake": "freno",
            "throttle": "acelerador",
            "steering_magnitude": "magnitud de dirección/volante",
        }.get(channel, channel)
        asserted_human = "mayor" if asserted == "higher_in_comparison_lap" else "menor"
        observed_human = "mayor" if observed == "higher_in_comparison_lap" else "menor"
        errors.append(
            f"interpretation: dirección factual invertida para {human}; el texto afirma "
            f"{asserted_human}, pero Python observó {observed_human} en la vuelta comparada."
        )


def validate_episode_steering_contract(
    recommendation, episode, errors, field_name="recommendation"
):
    if not _steering_direct_action_present(recommendation):
        return
    channels = set(episode.get("action_channels", []) or [])
    if "steering_magnitude" not in channels:
        errors.append(
            f"{field_name}: introduce steering_magnitude como acción, pero ese canal no está observado en el episodio."
        )
        return
    observed = _single_objective_channel_direction(episode, "steering_magnitude")
    for clause in _explicit_directional_clauses(recommendation):
        if "steering_magnitude" in clause.get("channels", set()) and observed is None:
            errors.append(
                f"{field_name}: steering_magnitude es mixed/ambiguo; debe formularse como replicar/acompañar la referencia, no como aumentar o reducir."
            )
            return


def validate_episode_coaching_direction(recommendation, episode, errors):
    if not isinstance(recommendation, str):
        return
    for clause in _explicit_directional_clauses(recommendation):
        commanded = clause["direction"]
        for channel in clause["channels"]:
            observed = _single_objective_channel_direction(episode, channel)
            if observed is None:
                continue
            expected = "increase" if observed == "lower_in_comparison_lap" else "decrease"
            if commanded == expected:
                continue
            human = {
                "brake": "freno",
                "throttle": "acelerador",
                "steering_magnitude": "magnitud de dirección/volante",
            }.get(channel, channel)
            observed_human = (
                "menor en la vuelta comparada"
                if observed == "lower_in_comparison_lap"
                else "mayor en la vuelta comparada"
            )
            expected_human = "aumentar" if expected == "increase" else "reducir"
            errors.append(
                f"recommendation: dirección de coaching invertida para {human}; Python observó "
                f"{observed_human}, por lo que la orden explícita debe ser {expected_human} "
                "o formularse como replicar/ajustar hacia la referencia."
            )


def validate_single_episode_response(response, episode):
    """Validate the established deterministic per-episode response contract."""
    errors = []
    expected = {"episode_id", "interpretation", "hypotheses", "recommendation"}
    actual = set(response.keys())
    if actual != expected:
        missing = expected - actual
        extra = actual - expected
        if missing:
            errors.append("Faltan claves del episodio: " + ", ".join(sorted(missing)))
        if extra:
            errors.append("Sobran claves del episodio: " + ", ".join(sorted(extra)))
    if safe_int(response.get("episode_id")) != safe_int(episode.get("episode_id")):
        errors.append("episode_id no coincide con el episodio solicitado.")

    allowed_channels = set(episode.get("action_channels", []) or [])
    speed_context = bool(episode.get("concurrent_speed_events")) or bool(
        episode.get("speed_propagation")
    )
    interpretation = response.get("interpretation")
    if not isinstance(interpretation, str):
        errors.append("interpretation debe ser texto.")
    else:
        if text_contains_forbidden_numeric_content(interpretation):
            errors.append("interpretation contiene cifras.")
        validate_grounded_text(
            interpretation, "interpretation", allowed_channels, speed_context, errors
        )
        validate_episode_interpretation_direction(interpretation, episode, errors)

    hypotheses = response.get("hypotheses")
    validate_text_list(hypotheses, "hypotheses", errors)
    validate_grounded_text_list(
        hypotheses, "hypotheses", allowed_channels, speed_context, errors
    )

    recommendation = response.get("recommendation")
    if not isinstance(recommendation, str):
        errors.append("recommendation debe ser texto.")
    else:
        if text_contains_forbidden_numeric_content(recommendation):
            errors.append("recommendation contiene cifras.")
        validate_grounded_text(
            recommendation, "recommendation", allowed_channels, speed_context, errors
        )
        validate_speed_not_action_target(recommendation, "recommendation", errors)
        validate_episode_steering_contract(recommendation, episode, errors)
        validate_episode_coaching_direction(recommendation, episode, errors)
        validate_reference_lap_is_action_target(recommendation, "recommendation", errors)
    return errors
