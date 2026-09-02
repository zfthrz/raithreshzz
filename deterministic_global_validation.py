"""Backend-independent validation for the global debrief response."""

from __future__ import annotations

import re

from deterministic_coaching import (
    CHANNEL_LANGUAGE_PATTERNS,
    _channels_mentioned_in_text,
    _explicit_command_direction_map,
    _steering_direct_action_present,
    normalize_grounding_text,
)
from deterministic_text_validation import text_contains_forbidden_numeric_content

SPEED_PATTERNS = (r"\bvelocidad\b", r"\brapidez\b", r"\bspeed\b")
EXTERNAL_PATTERNS = (
    (r"\bobstacul", "obstáculos"), (r"\bcamara\b|\bimagenes?\b|\bvideo\b", "cámara/imágenes"),
    (r"\btopograf", "topografía"), (r"\bpendient", "pendiente"), (r"\bbache", "baches"),
    (r"\birregularidad", "irregularidades de pista"), (r"\bsuperficie de (?:la )?pista\b", "superficie de pista"),
    (r"\badheren", "adherencia"), (r"\bhumedad\b|\bclima\b|\bmeteorolog", "clima/humedad"),
    (r"\bneumatic", "neumáticos"), (r"\bpresion (?:de|del|en) (?:los? )?neumatic", "presión de neumáticos"),
    (r"\bvibracion", "vibraciones"), (r"\baveria|\bfallo mecanic|\bproblema mecanic", "avería mecánica"),
    (r"\bmotor\b", "motor"), (r"\bpotencia\b", "potencia"), (r"\btransmision\b", "transmisión"),
    (r"\bpropulsion\b", "propulsión"), (r"\baerodinam", "aerodinámica"),
    (r"\bgestion de energia\b|\benergia\b", "gestión de energía"), (r"\bcombustible\b", "combustible"),
    (r"\btemperatura", "temperatura"), (r"\bcarga del vehiculo\b", "carga del vehículo"),
    (r"\bdano del vehiculo\b|\bdanos del vehiculo\b", "daño del vehículo"),
    (r"\bestabilidad\b|\binestabilidad\b|\bdinamic(?:a|o|as|os)\b", "estabilidad/dinámica del vehículo"),
    (r"\btrayector(?:ia|ias)\b", "trayectoria no observada"), (r"\btraccion\b", "tracción no observada"),
    (r"\bagarre\b|\bgrip\b", "agarre/grip no observado"), (r"\bbalance\b", "balance del vehículo no observado"),
    (r"\btransferencia de carga\b", "transferencia de carga no observada"),
    (r"\bsubviraje\b|\bsobreviraje\b", "balance dinámico no observado"),
    (r"\btrayectoria optima\b|\blinea ideal\b|\blinea de carrera\b", "línea/ trayectoria óptima"),
    (r"\bapice\b|\bvertice\b", "ápice/vértice no observado"),
)
CAUSAL_PATTERNS = (
    (r"\bcauso\b|\bcausar\b|\bcausad[oa]s?\b|\bcausan\b|\bcausa (?=(?:un|una|el|la|perdida|reduccion|aumento|cambio|diferencia|velocidad|tiempo))", "causalidad afirmada"),
    (r"\bprovoc(?:o|a|ar|ado|ada|an)\b", "causalidad afirmada"), (r"\bgener(?:o|a|ar|ado|ada|an)\b", "causalidad afirmada"),
    (r"\bproduj(?:o|eron)\b|\bproduce\b|\bproduc(?:ir|ido|ida)\b", "causalidad afirmada"),
    (r"\bocasion(?:o|a|ar|ado|ada)\b", "causalidad afirmada"), (r"\bderiv(?:o|a|ar) en\b", "causalidad afirmada"),
    (r"\bdio lugar a\b", "causalidad afirmada"), (r"\bresult(?:o|a) en\b", "causalidad afirmada"),
    (r"\bcomo consecuencia directa\b", "consecuencia directa no demostrada"),
    (r"\bse debe a\b|\bdebido a\b", "atribución causal no demostrada"),
)
SPEED_TARGET_PATTERNS = (
    (r"\b(?:aumenta|aumentar|incrementa|incrementar|subi|subir|reduci|reducir|disminui|disminuir|baja|bajar|recupera|recuperar|iguala|igualar)\b[^.;:\n]{0,60}\bvelocidad\b", "velocidad usada como acción del piloto"),
    (r"\bpara\s+(?:acercar|igualar|llevar|recuperar|mejorar)\b[^.;:\n]{0,50}\bvelocidad\b", "velocidad usada como objetivo de coaching"),
    (r"\bpara\s+que\b[^.;:\n]{0,50}\bvelocidad\b[^.;:\n]{0,40}\b(?:se\s+acerque|aumente|suba|baje|disminuya|mejore)\b", "velocidad usada como objetivo de coaching"),
)
COMPARISON_LAP_RE = re.compile(r"\bvuelta\s+(?:de\s+)?comparad[ao]\b|\bvuelta\s+de\s+comparaci[oó]n\b", re.I)
ACTION_VERB_RE = re.compile(r"\b(?:replic\w*|reproduc\w*|acompan\w*|ajust\w*|manten\w*|segu\w*|imit\w*|copi\w*|igual\w*|modul\w*|acerc\w*|orient\w*|tom(?:a|ar|ando)\w*|usa|usar|usando|busc\w*|llev\w*)\b")
HIGHER_RE = re.compile(r"\b(?:mayor|superior|elevad[oa]s?|aumento|aumentad[oa]s?|incremento|incrementad[oa]s?|mas(?!\s+(?:tarde|temprano|antes|despues)))\b")
LOWER_RE = re.compile(r"\b(?:menor|inferior|reducid[oa]s?|reduccion|disminuid[oa]s?|disminucion|menos)\b")
TEMPORAL_PATTERNS = (
    r"\bsecuencia\s+(?:de|entre)\s+(?:el\s+)?freno\s*(?:y|con|->|→)\s*(?:el\s+)?acelerador\b", r"\bsecuencia\s+(?:de|entre)\s+(?:el\s+)?acelerador\s*(?:y|con|->|→)\s*(?:el\s+)?freno\b",
    r"\bsolap(?:amiento|ar|ados?|ada)?\b.{0,50}\bfreno\b.{0,50}\bacelerador\b", r"\bsolap(?:amiento|ar|ados?|ada)?\b.{0,50}\bacelerador\b.{0,50}\bfreno\b",
    r"\bfreno\b.{0,50}\bacelerador\b.{0,30}\bsin\s+solapamiento\b", r"\bacelerador\b.{0,50}\bfreno\b.{0,30}\bsin\s+solapamiento\b",
    r"\bprimero\s+(?:el\s+)?freno\b.{0,60}\bdespues\s+(?:el\s+)?acelerador\b", r"\bprimero\s+(?:el\s+)?acelerador\b.{0,60}\bdespues\s+(?:el\s+)?freno\b",
    r"\bfreno\s+primero\b.{0,60}\bacelerador\s+despues\b", r"\bacelerador\s+primero\b.{0,60}\bfreno\s+despues\b",
    r"\bfreno\s*(?:->|→)\s*acelerador\b", r"\bacelerador\s*(?:->|→)\s*freno\b",
    r"\bsepar(?:ar|a|e|á)\b.{0,60}\bfreno\b.{0,60}\bacelerador\b", r"\bsepar(?:ar|a|e|á)\b.{0,60}\bacelerador\b.{0,60}\bfreno\b",
    r"\bevit(?:ar|a|e|á)\b.{0,40}\bsolap", r"\bno\s+solap",
)


def zone_labels_in_text(value):
    return {x.upper() for x in re.findall(r"\bzona(?:\s+prioritaria)?\s+([a-z])\b", normalize_grounding_text(value))} if isinstance(value, str) else set()


def _factual_map(value):
    result = {}
    for part in re.split(r"(?:[.;:\n]+|,\s*|\s+\by\b\s+)", normalize_grounding_text(value)) if isinstance(value, str) else []:
        channels = {c for c, patterns in CHANNEL_LANGUAGE_PATTERNS.items() if any(re.search(p, part) for p in patterns)}
        directions = ({"higher_in_comparison_lap"} if HIGHER_RE.search(part) else set()) | ({"lower_in_comparison_lap"} if LOWER_RE.search(part) else set())
        if len(channels) == len(directions) == 1: result.setdefault(next(iter(channels)), set()).add(next(iter(directions)))
    return {c: next(iter(v)) for c, v in result.items() if len(v) == 1}


def _expected_map(item):
    result = {}
    for text in (item or {}).get("targets", []) or []:
        if isinstance(text, str):
            for channel, direction in _explicit_command_direction_map(text).items(): result.setdefault(channel, set()).add(direction)
    return {c: next(iter(v)) for c, v in result.items() if len(v) == 1}


def _observed_map(item):
    result = {}
    for text in (item or {}).get("observed_differences", []) or []:
        for channel, direction in _factual_map(text).items(): result.setdefault(channel, set()).add(direction)
    return {c: next(iter(v)) for c, v in result.items() if len(v) == 1}


def _observed_channels(item):
    result = set()
    for text in (item or {}).get("observed_differences", []) or []: result.update(_channels_mentioned_in_text(text))
    return result


def _steering_allowed(text, item):
    if not _steering_direct_action_present(text): return True
    if not isinstance(item, dict) or "steering_magnitude" not in _observed_channels(item): return False
    if "steering_magnitude" not in {cue.get("channel") for cue in item.get("driver_cues", []) or [] if isinstance(cue, dict)}: return False
    explicit = _explicit_command_direction_map(text).get("steering_magnitude")
    expected = {"lower_in_comparison_lap": "increase", "higher_in_comparison_lap": "decrease"}.get(_observed_map(item).get("steering_magnitude"))
    return explicit is None or (expected is not None and explicit == expected)


def validate_global_secondary_steering_text(value, field_name, plan, errors):
    if not _steering_direct_action_present(value): return
    labels = zone_labels_in_text(value)
    if len(labels) != 1: errors.append(f"{field_name}: steering_magnitude directo debe quedar anclado a una única zona A/B/C."); return
    label = next(iter(labels)); item = next((x for x in (plan or [])[:3] if isinstance(x, dict) and str(x.get("plan_label") or "").strip().upper() == label), None)
    if not _steering_allowed(value, item): errors.append(f"{field_name}: steering_magnitude sólo puede convertirse en acción de zona {label} si Python lo incluyó explícitamente en driver_cues y la dirección respeta la evidencia observada.")


def validate_temporal_observation_not_action_target(value, field_name, plan, errors):
    if not isinstance(value, str) or not any(re.search(p, normalize_grounding_text(value)) for p in TEMPORAL_PATTERNS): return
    by_label = {str(x.get("plan_label") or "").strip().upper(): x for x in (plan or [])[:3] if isinstance(x, dict) and x.get("plan_label")}; labels = zone_labels_in_text(value)
    if labels and all(bool((by_label.get(label) or {}).get("temporal_target")) for label in labels): return
    errors.append(f"{field_name}: convierte una observación temporal de freno/acelerador en coaching sin temporal_target autorizado por Python.")


def validate_global_zone_list_consistency(response, plan, errors):
    if not isinstance(response, dict): return
    by_label = {str(x.get("plan_label") or "").strip().upper(): x for x in (plan or [])[:3] if isinstance(x, dict) and x.get("plan_label")}; human = {"brake": "freno", "throttle": "acelerador", "steering_magnitude": "magnitud de dirección/volante"}
    for index, text in enumerate(response.get("opportunities") or []):
        labels = zone_labels_in_text(text)
        if not isinstance(text, str) or len(labels) != 1: continue
        label = next(iter(labels)); item = by_label.get(label)
        if not isinstance(item, dict): errors.append(f"opportunities[{index}]: referencia zona {label} que no existe en next_stint_plan."); continue
        expected, actual = _expected_map(item), _explicit_command_direction_map(text)
        for channel in sorted(set(actual) - set(expected)):
            if channel == "steering_magnitude" and _steering_allowed(text, item): continue
            errors.append(f"opportunities[{index}]: convierte una observación en orden no autorizada para {human.get(channel, channel)} en zona {label}.")
        for channel in set(expected) & set(actual):
            if expected[channel] != actual[channel]: errors.append(f"opportunities[{index}]: contradice el coaching determinista de zona {label} para {human.get(channel, channel)}; Python requiere {'aumentar' if expected[channel] == 'increase' else 'reducir'}.")
    for index, text in enumerate(response.get("repeated_observations") or []):
        labels = zone_labels_in_text(text)
        if not isinstance(text, str) or len(labels) != 1: continue
        label = next(iter(labels)); item = by_label.get(label)
        if not isinstance(item, dict): errors.append(f"repeated_observations[{index}]: referencia zona {label} que no existe en next_stint_plan."); continue
        for channel in sorted(_channels_mentioned_in_text(text) - _observed_channels(item)): errors.append(f"repeated_observations[{index}]: menciona {human.get(channel, channel)} en zona {label}, pero ese canal no forma parte de observed_differences de esa zona.")
        expected, actual = _observed_map(item), _factual_map(text)
        for channel in set(expected) & set(actual):
            if expected[channel] != actual[channel]: errors.append(f"repeated_observations[{index}]: dirección factual invertida en zona {label} para {human.get(channel, channel)}; Python observó {'mayor' if expected[channel] == 'higher_in_comparison_lap' else 'menor'}.")


def validate_global_direction_consistency(response, plan, errors):
    if not isinstance(response, dict): return
    expected = {str(x.get("plan_label") or "").strip().upper(): _expected_map(x) for x in (plan or [])[:3] if isinstance(x, dict) and x.get("plan_label")}
    conclusion = response.get("conclusion")
    for part in re.split(r"(?<=[.;])|\b(?:luego|despues|finalmente|por ultimo|a continuacion)\b", normalize_grounding_text(conclusion)) if isinstance(conclusion, str) else []:
        labels = zone_labels_in_text(part)
        if len(labels) != 1: continue
        label = next(iter(labels)); actual = _explicit_command_direction_map(part)
        for channel in set(expected.get(label, {})) & set(actual):
            if expected[label][channel] != actual[channel]:
                human = {"brake": "freno", "throttle": "acelerador", "steering_magnitude": "magnitud de dirección/volante"}.get(channel, channel)
                errors.append(f"conclusion global: contradice el coaching determinista de zona {label} para {human}; Python requiere {'aumentar' if expected[label][channel] == 'increase' else 'reducir'}.")


def _grounded(text, field, channels, speed, errors):
    normalized = normalize_grounding_text(text)
    for pattern, label in EXTERNAL_PATTERNS:
        if re.search(pattern, normalized): errors.append(f"{field}: menciona dominio no observado ({label}).")
    for pattern, label in CAUSAL_PATTERNS:
        if re.search(pattern, normalized): errors.append(f"{field}: usa lenguaje causal asertivo ({label}).")
    for channel, patterns in CHANNEL_LANGUAGE_PATTERNS.items():
        if channel not in channels and any(re.search(p, normalized) for p in patterns): errors.append(f"{field}: menciona {channel} pero ese canal no está autorizado por action_channels.")
    if not speed and any(re.search(p, normalized) for p in SPEED_PATTERNS): errors.append(f"{field}: menciona velocidad sin speed_context autorizado por Python.")


def _action_targets(text, field, errors):
    normalized = normalize_grounding_text(text)
    for pattern, label in SPEED_TARGET_PATTERNS:
        if re.search(pattern, normalized): errors.append(f"{field}: {label}; la velocidad es sólo contexto/propagación, no un input ni un objetivo de acción."); break
    for match in COMPARISON_LAP_RE.finditer(text):
        prefix = text[max(0, match.start() - 180):match.start()]; boundary = max(prefix.rfind("."), prefix.rfind(";"), prefix.rfind(":"), prefix.rfind("\n")); prefix = prefix[boundary + 1:] if boundary >= 0 else prefix
        normalized_prefix = normalize_grounding_text(prefix)
        if ACTION_VERB_RE.search(normalized_prefix) or re.search(r"\b(?:hacia|como|segun)\s+(?:la\s+)?$", normalized_prefix): errors.append(f"{field}: usa la vuelta comparada como objetivo de coaching; la acción debe orientarse a la vuelta de referencia."); break


def validate_global_response(response, valid_comparison_results=None, session_coaching_facts=None):
    errors = []
    if not isinstance(response, dict): return ["La respuesta global debe ser un objeto JSON."]
    required = {"opportunities", "repeated_observations", "hypotheses", "limitations", "conclusion"}; actual = set(response)
    if required - actual: errors.append("Faltan claves globales: " + ", ".join(sorted(required - actual)))
    if actual - required: errors.append("Sobran claves globales: " + ", ".join(sorted(actual - required)))
    episodes = [e for r in (valid_comparison_results or []) if isinstance(r, dict) for e in (r.get("episode_ground_truth", []) or []) if isinstance(e, dict)]
    channels = {c for e in episodes for c in (e.get("action_channels", []) or []) if isinstance(c, str)}; speed = any(e.get("concurrent_speed_events") or e.get("speed_propagation") for e in episodes)
    plan = session_coaching_facts.get("next_stint_plan", []) if isinstance(session_coaching_facts, dict) else []
    unsupported = re.compile(r"\b(entrada\s+a\s+curva|salida\s+de\s+curva|curvas?\s+cr[ií]ticas?|punto\s+de\s+frenada|[aá]pice|v[eé]rtice|trail\s*brak(?:e|ing)|fase\s+de\s+entrada|fase\s+de\s+salida)\b", re.I)
    for field, maximum in (("opportunities", 4), ("repeated_observations", 4), ("hypotheses", 3), ("limitations", 2)):
        value = response.get(field)
        if not isinstance(value, list): errors.append(f"{field}: debe ser lista."); continue
        if len(value) > maximum: errors.append(f"{field}: demasiados elementos; máximo {maximum}.")
        for index, text in enumerate(value):
            name = f"{field}[{index}]"
            if not isinstance(text, str): errors.append(f"{name}: debe ser texto."); continue
            if text_contains_forbidden_numeric_content(text): errors.append(f"{name}: contiene cifras.")
            _grounded(text, name, channels, speed, errors)
            if field == "opportunities":
                if re.search(r"^\s*(analizar|explorar|evaluar|monitorear|investigar|estudiar)\b", text, re.I): errors.append(f"{name}: recomendación demasiado vaga.")
                if unsupported.search(text): errors.append(f"{name}: inventa una fase/nombre de curva no suministrado por Python.")
                _action_targets(text, name, errors); validate_global_secondary_steering_text(text, name, plan, errors); validate_temporal_observation_not_action_target(text, name, plan, errors)
    conclusion = response.get("conclusion")
    if not isinstance(conclusion, str): errors.append("conclusion global debe ser texto.")
    else:
        if text_contains_forbidden_numeric_content(conclusion): errors.append("conclusion global contiene cifras.")
        _grounded(conclusion, "conclusion global", channels, speed, errors); _action_targets(conclusion, "conclusion global", errors)
        validate_global_secondary_steering_text(conclusion, "conclusion global", plan, errors); validate_temporal_observation_not_action_target(conclusion, "conclusion global", plan, errors)
        if unsupported.search(conclusion): errors.append("conclusion global inventa una fase/nombre de curva no suministrado por Python.")
    validate_global_direction_consistency(response, plan, errors); validate_global_zone_list_consistency(response, plan, errors)
    return errors
