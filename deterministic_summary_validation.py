"""Backend-independent validation for deterministic comparison summaries."""

from __future__ import annotations

import re

from deterministic_coaching import (
    CHANNEL_LANGUAGE_PATTERNS,
    _explicit_command_direction_map,
    _single_objective_channel_direction,
    _steering_direct_action_present,
    normalize_grounding_text,
)
from deterministic_text_validation import text_contains_forbidden_numeric_content


SPEED_LANGUAGE_PATTERNS = (r"\bvelocidad\b", r"\brapidez\b", r"\bspeed\b")

FORBIDDEN_EXTERNAL_GROUNDING_PATTERNS = (
    (r"\bobstacul", "obstáculos"),
    (r"\bcamara\b|\bimagenes?\b|\bvideo\b", "cámara/imágenes"),
    (r"\btopograf", "topografía"),
    (r"\bpendient", "pendiente"),
    (r"\bbache", "baches"),
    (r"\birregularidad", "irregularidades de pista"),
    (r"\bsuperficie de (?:la )?pista\b", "superficie de pista"),
    (r"\badheren", "adherencia"),
    (r"\bhumedad\b|\bclima\b|\bmeteorolog", "clima/humedad"),
    (r"\bneumatic", "neumáticos"),
    (r"\bpresion (?:de|del|en) (?:los? )?neumatic", "presión de neumáticos"),
    (r"\bvibracion", "vibraciones"),
    (r"\baveria|\bfallo mecanic|\bproblema mecanic", "avería mecánica"),
    (r"\bmotor\b", "motor"),
    (r"\bpotencia\b", "potencia"),
    (r"\btransmision\b", "transmisión"),
    (r"\bpropulsion\b", "propulsión"),
    (r"\baerodinam", "aerodinámica"),
    (r"\bgestion de energia\b|\benergia\b", "gestión de energía"),
    (r"\bcombustible\b", "combustible"),
    (r"\btemperatura", "temperatura"),
    (r"\bcarga del vehiculo\b", "carga del vehículo"),
    (r"\bdano del vehiculo\b|\bdanos del vehiculo\b", "daño del vehículo"),
    (r"\bestabilidad\b|\binestabilidad\b|\bdinamic(?:a|o|as|os)\b", "estabilidad/dinámica del vehículo"),
    (r"\btrayector(?:ia|ias)\b", "trayectoria no observada"),
    (r"\btraccion\b", "tracción no observada"),
    (r"\bagarre\b|\bgrip\b", "agarre/grip no observado"),
    (r"\bbalance\b", "balance del vehículo no observado"),
    (r"\btransferencia de carga\b", "transferencia de carga no observada"),
    (r"\bsubviraje\b|\bsobreviraje\b", "balance dinámico no observado"),
    (r"\btrayectoria optima\b|\blinea ideal\b|\blinea de carrera\b", "línea/ trayectoria óptima"),
    (r"\bapice\b|\bvertice\b", "ápice/vértice no observado"),
)

FORBIDDEN_ASSERTIVE_CAUSAL_PATTERNS = (
    (r"\bcauso\b|\bcausar\b|\bcausad[oa]s?\b|\bcausan\b|\bcausa (?=(?:un|una|el|la|perdida|reduccion|aumento|cambio|diferencia|velocidad|tiempo))", "causalidad afirmada"),
    (r"\bprovoc(?:o|a|ar|ado|ada|an)\b", "causalidad afirmada"),
    (r"\bgener(?:o|a|ar|ado|ada|an)\b", "causalidad afirmada"),
    (r"\bproduj(?:o|eron)\b|\bproduce\b|\bproduc(?:ir|ido|ida)\b", "causalidad afirmada"),
    (r"\bocasion(?:o|a|ar|ado|ada)\b", "causalidad afirmada"),
    (r"\bderiv(?:o|a|ar) en\b", "causalidad afirmada"),
    (r"\bdio lugar a\b", "causalidad afirmada"),
    (r"\bresult(?:o|a) en\b", "causalidad afirmada"),
    (r"\bcomo consecuencia directa\b", "consecuencia directa no demostrada"),
    (r"\bse debe a\b|\bdebido a\b", "atribución causal no demostrada"),
)

SPEED_AS_ACTION_TARGET_PATTERNS = (
    (r"\b(?:aumenta|aumentar|incrementa|incrementar|subi|subir|reduci|reducir|disminui|disminuir|baja|bajar|recupera|recuperar|iguala|igualar)\b[^.;:\n]{0,60}\bvelocidad\b", "velocidad usada como acción del piloto"),
    (r"\bpara\s+(?:acercar|igualar|llevar|recuperar|mejorar)\b[^.;:\n]{0,50}\bvelocidad\b", "velocidad usada como objetivo de coaching"),
    (r"\bpara\s+que\b[^.;:\n]{0,50}\bvelocidad\b[^.;:\n]{0,40}\b(?:se\s+acerque|aumente|suba|baje|disminuya|mejore)\b", "velocidad usada como objetivo de coaching"),
)

COMPARISON_LAP_TARGET_PHRASE_RE = re.compile(
    r"\bvuelta\s+(?:de\s+)?comparad[ao]\b|\bvuelta\s+de\s+comparaci[oó]n\b",
    re.IGNORECASE,
)
ACTION_TARGET_VERB_RE = re.compile(
    r"\b(?:replic\w*|reproduc\w*|acompan\w*|ajust\w*|manten\w*|segu\w*|"
    r"imit\w*|copi\w*|igual\w*|modul\w*|acerc\w*|orient\w*|tom(?:a|ar|ando)\w*|"
    r"usa|usar|usando|busc\w*|llev\w*)\b"
)


def _episode_has_speed_context(episode):
    return bool(episode.get("concurrent_speed_events")) or bool(
        episode.get("speed_propagation")
    )


def grounding_context_from_episodes(episodes):
    channels = set()
    speed_context = False
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        channels.update(
            channel
            for channel in (episode.get("action_channels", []) or [])
            if isinstance(channel, str)
        )
        if _episode_has_speed_context(episode):
            speed_context = True
    return channels, speed_context


def validate_grounded_text(value, field_name, allowed_channels, speed_context, errors):
    if not isinstance(value, str):
        return
    normalized = normalize_grounding_text(value)
    for pattern, label in FORBIDDEN_EXTERNAL_GROUNDING_PATTERNS:
        if re.search(pattern, normalized):
            errors.append(f"{field_name}: menciona dominio no observado ({label}).")
    for pattern, label in FORBIDDEN_ASSERTIVE_CAUSAL_PATTERNS:
        if re.search(pattern, normalized):
            errors.append(f"{field_name}: usa lenguaje causal asertivo ({label}).")
    for channel, patterns in CHANNEL_LANGUAGE_PATTERNS.items():
        if any(re.search(pattern, normalized) for pattern in patterns) and channel not in allowed_channels:
            errors.append(
                f"{field_name}: menciona {channel} pero ese canal no está autorizado por action_channels."
            )
    if any(re.search(pattern, normalized) for pattern in SPEED_LANGUAGE_PATTERNS) and not speed_context:
        errors.append(f"{field_name}: menciona velocidad sin speed_context autorizado por Python.")


def validate_speed_not_action_target(value, field_name, errors):
    if not isinstance(value, str):
        return
    normalized = normalize_grounding_text(value)
    for pattern, label in SPEED_AS_ACTION_TARGET_PATTERNS:
        if re.search(pattern, normalized):
            errors.append(
                f"{field_name}: {label}; la velocidad es sólo contexto/propagación, no un input ni un objetivo de acción."
            )
            break


def _comparison_steering_directions(episodes):
    directions = set()
    for episode in episodes or []:
        if not isinstance(episode, dict) or "steering_magnitude" not in set(episode.get("action_channels", []) or []):
            continue
        direction = _single_objective_channel_direction(episode, "steering_magnitude")
        if direction:
            directions.add(direction)
    return directions


def validate_summary_steering_secondary_contract(conclusion, episodes, errors):
    if not _steering_direct_action_present(conclusion):
        return
    steering_episodes = [
        episode for episode in (episodes or [])
        if isinstance(episode, dict)
        and "steering_magnitude" in set(episode.get("action_channels", []) or [])
    ]
    if not steering_episodes:
        errors.append("conclusion: introduce steering_magnitude como coaching sin evidencia de steering en la comparación.")
        return
    explicit = _explicit_command_direction_map(conclusion).get("steering_magnitude")
    if explicit is None:
        return
    directions = _comparison_steering_directions(episodes)
    if len(directions) != 1:
        errors.append("conclusion: la dirección de steering_magnitude no es unívoca entre los episodios; usá una formulación neutral hacia la referencia.")
        return
    observed = next(iter(directions))
    expected = "increase" if observed == "lower_in_comparison_lap" else "decrease"
    if explicit != expected:
        errors.append("conclusion: dirección de coaching invertida para steering_magnitude respecto de la evidencia agregada.")


def _comparison_lap_used_as_action_target(text):
    if not isinstance(text, str):
        return False
    for match in COMPARISON_LAP_TARGET_PHRASE_RE.finditer(text):
        prefix = text[max(0, match.start() - 180):match.start()]
        boundary = max(prefix.rfind("."), prefix.rfind(";"), prefix.rfind(":"), prefix.rfind("\n"))
        if boundary >= 0:
            prefix = prefix[boundary + 1:]
        normalized = normalize_grounding_text(prefix)
        if ACTION_TARGET_VERB_RE.search(normalized) or re.search(r"\b(?:hacia|como|segun)\s+(?:la\s+)?$", normalized):
            return True
    return False


def validate_reference_lap_is_action_target(text, field_name, errors):
    if _comparison_lap_used_as_action_target(text):
        errors.append(
            f"{field_name}: usa la vuelta comparada como objetivo de coaching; la acción debe orientarse a la vuelta de referencia."
        )


def validate_text_list(value, field_name, errors):
    if not isinstance(value, list):
        errors.append(f"{field_name}: debe ser lista.")
        return
    for index, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"{field_name}[{index}]: debe ser texto.")
        elif text_contains_forbidden_numeric_content(item):
            errors.append(f"{field_name}[{index}]: contiene cifras.")


def validate_grounded_text_list(value, field_name, allowed_channels, speed_context, errors):
    if not isinstance(value, list):
        return
    for index, item in enumerate(value):
        if isinstance(item, str):
            validate_grounded_text(item, f"{field_name}[{index}]", allowed_channels, speed_context, errors)


def validate_comparison_summary_response(response, episode_catalog):
    """Validate the established deterministic comparison-summary contract."""
    errors = []
    expected = {"comparison_observations", "limitations", "conclusion"}
    actual = set(response.keys())
    if actual != expected:
        missing = expected - actual
        extra = actual - expected
        if missing:
            errors.append("Faltan claves del resumen: " + ", ".join(sorted(missing)))
        if extra:
            errors.append("Sobran claves del resumen: " + ", ".join(sorted(extra)))

    allowed_channels, speed_context = grounding_context_from_episodes(episode_catalog)
    for key in ("comparison_observations", "limitations"):
        value = response.get(key)
        validate_text_list(value, key, errors)
        validate_grounded_text_list(value, key, allowed_channels, speed_context, errors)

    conclusion = response.get("conclusion")
    if not isinstance(conclusion, str):
        errors.append("conclusion debe ser texto.")
    else:
        if text_contains_forbidden_numeric_content(conclusion):
            errors.append("conclusion contiene cifras.")
        validate_grounded_text(conclusion, "conclusion", allowed_channels, speed_context, errors)
        validate_speed_not_action_target(conclusion, "conclusion", errors)
        validate_summary_steering_secondary_contract(conclusion, episode_catalog, errors)
        validate_reference_lap_is_action_target(conclusion, "conclusion", errors)
    return errors
