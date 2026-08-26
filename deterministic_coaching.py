"""Shared deterministic coaching primitives.

Backend-independent logic extracted from the historical llm_analysis backend forks.
"""

import re
import unicodedata

BRAKE_RELEASE_SESSION_MIN_DELTA_M = 8.0

BRAKING_POINT_SESSION_MIN_DELTA_M = 8.0

CHANNEL_LANGUAGE_PATTERNS = {
    "brake": (
        r"\bfren",
        r"\bbrake\b",
    ),
    "throttle": (
        r"\baceler",
        r"\bthrottle\b",
        r"\bmodulacion de gas\b",
        r"\bpedal de gas\b",
    ),
    "steering_magnitude": (
        r"\bdireccion\b",
        r"\bvolante\b",
        r"\bgiro\b",
        r"\btrayector",
        r"\bsteering\b",
    ),
}

COACHING_DECREASE_VERB_RE = re.compile(
    r"\b(?:reduci|reducir|disminui|disminuir|baja|bajar)\b"
)

COACHING_DIRECTION_VERB_RE = re.compile(
    r"\b(?:"
    r"aumenta|aumentar|incrementa|incrementar|subi|subir|"
    r"reduci|reducir|disminui|disminuir|baja|bajar"
    r")\b"
)

COACHING_INCREASE_VERB_RE = re.compile(
    r"\b(?:aumenta|aumentar|incrementa|incrementar|subi|subir)\b"
)

COACHING_NEW_ACTION_AFTER_AND_RE = re.compile(
    r"\by\s+(?=(?:"
    r"replica|replicar|ajusta|ajustar|manten|mantener|"
    r"acompan(?:a|ar)|limita|limitar|suaviza|suavizar|"
    r"frena|frenar|solta|soltar|suelta|reaplica|reaplicar|"
    r"aplica|aplicar|modula|modular|"
    r"aumenta|aumentar|incrementa|incrementar|subi|subir|"
    r"reduci|reducir|disminui|disminuir|baja|bajar"
    r")\b)"
)

STEERING_DIRECT_ACTION_RE = re.compile(
    r"\b(?:"
    r"aumenta|aumentar|incrementa|incrementar|subi|subir|"
    r"reduci|reducir|disminui|disminuir|baja|bajar|"
    r"replica|replicar|ajusta|ajustar|manten|mantener|"
    r"modula|modular|acompan(?:a|ar)|limita|limitar|"
    r"suaviza|suavizar"
    r")\b[^.;\n]{0,90}\b(?:"
    r"volante|direccion|magnitud\s+de\s+(?:direccion|volante)"
    r")\b"
)

THROTTLE_ONSET_SESSION_MIN_DELTA_M = 8.0

THROTTLE_RELEASE_SESSION_MIN_DELTA_M = 8.0


def _channel_direction_phrase(channel, evidence):
    """Descripción puramente factual del sentido de los eventos del canal."""
    events = []
    if isinstance(evidence, dict):
        events = [
            item for item in (evidence.get("events", []) or [])
            if isinstance(item, dict)
        ]

    directions = {
        str(item.get("direction"))
        for item in events
        if item.get("direction")
    }

    single_direction = next(iter(directions)) if len(directions) == 1 else None

    if channel == "brake":
        if single_direction == "higher_in_comparison_lap":
            return "una aplicación de freno mayor"
        if single_direction == "lower_in_comparison_lap":
            return "una aplicación de freno menor"
        return "variaciones sostenidas en la aplicación del freno"

    if channel == "throttle":
        if single_direction == "higher_in_comparison_lap":
            return "un uso del acelerador mayor"
        if single_direction == "lower_in_comparison_lap":
            return "un uso del acelerador menor"
        return "variaciones sostenidas en el uso del acelerador"

    if channel == "steering_magnitude":
        if single_direction == "higher_in_comparison_lap":
            return "una magnitud de dirección/volante mayor"
        if single_direction == "lower_in_comparison_lap":
            return "una magnitud de dirección/volante menor"
        return "variaciones sostenidas en la magnitud de dirección/volante"

    return None

def _coaching_target_for_channel_direction(
    channel,
    direction,
):
    """
    v3.10.8.5.4: diferencias deterministas unívocas de NIVEL en brake/throttle
    pueden convertirse en coaching cualitativo hacia la vuelta de referencia.

    Límites:
    - no inventa metros, porcentajes ni causalidad;
    - mixed/ambiguo permanece observacional;
    - steering conserva su vía separada de autorización LLM+Python;
    - los detectores onset/release siguen siendo los únicos dueños de targets
      espaciales numéricos.
    """
    if channel not in {"brake", "throttle"}:
        return None

    label = {
        "brake": "el freno",
        "throttle": "el acelerador",
    }[channel]

    if direction == "higher_in_comparison_lap":
        return f"reducir {label} hacia la referencia"

    if direction == "lower_in_comparison_lap":
        return f"aumentar {label} hacia la referencia"

    return None

def _direct_coaching_target_text(
    value,
):
    """
    Convierte los coaching targets propiedad de Python de infinitivo a una
    instrucción directa. No cambia input, dirección ni contenido factual.
    """
    value = str(
        value or ""
    ).strip()

    if not value:
        return ""

    replacements = (
        (
            "reducir ",
            "reducí ",
        ),
        (
            "aumentar ",
            "aumentá ",
        ),
        (
            "replicar ",
            "replicá ",
        ),
    )

    lowered = value.lower()

    for source, target in replacements:
        if lowered.startswith(
            source
        ):
            value = (
                target
                + value[
                    len(source):
                ]
            )
            break

    value = re.sub(
        r"\s+hacia\s+(?:el\s+punto\s+de\s+)?la\s+referencia\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()

    return value

def _driver_facing_throttle_profile_text(summary):
    """Convierte únicamente formas conocidas en una secuencia driver-facing."""
    value = str(summary or "").strip()
    if not value:
        return ""

    fallback = (
        "replicá la secuencia de acelerador de la referencia: "
        + value
    )
    actions = {
        "aplicación": "replicá la aplicación de acelerador",
        "aplicación parcial": "usá una aplicación parcial de acelerador",
        "aplicación media": "usá una aplicación media de acelerador",
        "aplicación alta": "usá una aplicación alta de acelerador",
        "aplicación parcial breve": "hacé una aplicación parcial y breve de acelerador",
        "aplicación media breve": "hacé una aplicación media y breve de acelerador",
        "aplicación alta breve": "hacé una aplicación alta y breve de acelerador",
        "liberación breve": "hacé una liberación breve del acelerador",
        "acelerador liberado": "soltá el acelerador",
        "reaplicación sostenida": "reaplicá y sostené el acelerador",
        "reaplicación sostenida sin volver a soltar dentro de la zona": (
            "reaplicá y sostené el acelerador"
        ),
    }

    tokens = [part.strip() for part in value.split("→") if part.strip()]
    if not tokens or any(token not in actions for token in tokens):
        return fallback

    return "; después, ".join(actions[token] for token in tokens) + (
        " como en la referencia"
    )

def _episode_speed_context_facts(
    episode,
):
    concurrent = [
        item
        for item in (
            episode.get(
                "concurrent_speed_events",
                [],
            )
            or []
        )
        if isinstance(item, dict)
    ]

    speed_directions = sorted({
        str(item.get("direction"))
        for item in concurrent
        if item.get("direction")
    })

    propagations = [
        item
        for item in (
            episode.get(
                "speed_propagation",
                [],
            )
            or []
        )
        if isinstance(item, dict)
    ]

    propagation_statuses = sorted({
        str(item.get("status"))
        for item in propagations
        if item.get("status")
    })

    return {
        "speed_context_available":
            bool(
                concurrent
                or
                propagations
            ),

        "speed_directions":
            speed_directions,

        "propagation_statuses":
            propagation_statuses,
    }

def _plan_item_primary_driver_cue_channels(plan_item):
    channels = set()

    if not isinstance(plan_item, dict):
        return channels

    for cue in (plan_item.get("driver_cues", []) or []):
        if not isinstance(cue, dict):
            continue

        explicit_channels = cue.get("channels")
        if isinstance(explicit_channels, list):
            for channel in explicit_channels:
                if channel in {"brake", "throttle"}:
                    channels.add(channel)

        channel = cue.get("channel")
        if channel in {"brake", "throttle"}:
            channels.add(channel)

    return channels

def _render_speed_context_fact(
    finding,
):
    parts = []

    speed_directions = set(
        finding.get(
            "speed_directions",
            [],
        )
        or []
    )

    lower_speed_seen = (
        "lower_in_comparison_lap"
        in speed_directions
    )
    higher_speed_seen = (
        "higher_in_comparison_lap"
        in speed_directions
    )

    if lower_speed_seen and higher_speed_seen:
        parts.append(
            "velocidad variable respecto de la referencia "
            "entre comparaciones"
        )
    elif lower_speed_seen:
        parts.append(
            "velocidad inferior a la referencia"
        )
    elif higher_speed_seen:
        parts.append(
            "velocidad superior a la referencia"
        )

    statuses = set(
        finding.get(
            "propagation_statuses",
            [],
        )
        or []
    )

    if (
        "continues_losing_time"
        in statuses
    ):
        parts.append(
            "el delta siguió empeorando después de terminar la acción"
        )

    if not parts:
        return None

    return "; ".join(
        parts
    )

def _single_event_direction(evidence):
    events = []

    if isinstance(evidence, dict):
        events = [
            item
            for item in (evidence.get("events", []) or [])
            if isinstance(item, dict)
        ]

    directions = {
        str(item.get("direction"))
        for item in events
        if item.get("direction")
    }

    if len(directions) == 1:
        return next(iter(directions))

    if directions:
        return "mixed"

    return None

def _single_objective_channel_direction(episode, channel):
    """
    Devuelve higher/lower sólo cuando todos los eventos persistentes del
    canal apuntan en el mismo sentido. Mixed/ambiguo -> None.
    """
    evidence = (
        episode.get("action_evidence_by_channel", {}) or {}
    ).get(channel, {}) or {}

    events = [
        item
        for item in (evidence.get("events", []) or [])
        if isinstance(item, dict)
        and item.get("persistent", True)
        and item.get("direction")
    ]

    directions = {
        str(item.get("direction"))
        for item in events
    }

    if len(directions) != 1:
        return None

    direction = next(iter(directions))
    if direction not in {
        "higher_in_comparison_lap",
        "lower_in_comparison_lap",
    }:
        return None

    return direction

def build_deterministic_repeated_observations(
    session_coaching_facts,
):
    """
    v3.10.8

    repeated_observations is factual session accounting, not narrative model
    judgment. Build one item per selected repeated region from Python-owned
    observed_differences so backends cannot omit or contaminate a zone.
    """
    plan = (
        session_coaching_facts.get("next_stint_plan", [])
        if isinstance(session_coaching_facts, dict)
        else []
    ) or []

    result = []
    for item in plan[:3]:
        if not isinstance(item, dict) or item.get("kind") != "repeated_region":
            continue

        label = str(item.get("plan_label") or "").strip().upper()
        observed = [
            str(value).strip()
            for value in (item.get("observed_differences", []) or [])
            if str(value).strip()
        ]
        if not label or not observed:
            continue

        if len(observed) == 1:
            joined = observed[0]
        elif len(observed) == 2:
            joined = f"{observed[0]} y {observed[1]}"
        else:
            joined = ", ".join(observed[:-1]) + f" y {observed[-1]}"

        result.append(
            f"En la zona {label} se repitió {joined} en la misma región."
        )

    return result


def safe_float(value):
    if value is None:
        return None

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if value != value:
        return None

    if value in (
        float("inf"),
        float("-inf"),
    ):
        return None

    return value

def _aggregate_channel_quantitative_facts(
    channel_facts,
):
    facts = [
        item
        for item in (channel_facts or [])
        if isinstance(item, dict)
    ]

    means = [
        safe_float(item.get("mean_difference"))
        for item in facts
    ]
    means = [value for value in means if value is not None]

    peaks = [
        safe_float(item.get("peak_difference"))
        for item in facts
    ]
    peaks = [value for value in peaks if value is not None]

    event_mins = [
        safe_float(item.get("event_mean_min"))
        for item in facts
    ]
    event_mins = [value for value in event_mins if value is not None]

    event_maxs = [
        safe_float(item.get("event_mean_max"))
        for item in facts
    ]
    event_maxs = [value for value in event_maxs if value is not None]

    unit = next(
        (
            item.get("unit")
            for item in facts
            if item.get("unit")
        ),
        None,
    )

    peak_max_abs = (
        max(peaks, key=lambda value: abs(value))
        if peaks
        else None
    )

    return {
        "mean_difference_min": min(means) if means else None,
        "mean_difference_max": max(means) if means else None,
        "peak_difference_max_abs": peak_max_abs,
        "event_mean_min": min(event_mins) if event_mins else None,
        "event_mean_max": max(event_maxs) if event_maxs else None,
        "sample_count": len(facts),
        "unit": unit,
    }

def _aggregate_region_brake_throttle_relation(
    component,
):
    rows = []

    for finding in (
        component
        or []
    ):
        relation = finding.get(
            "brake_throttle_relation"
        )

        if not isinstance(
            relation,
            dict,
        ):
            continue

        rows.append({
            "comparison":
                finding.get(
                    "comparison"
                ),
            **relation,
        })

    if not rows:
        return None

    comparisons = {
        str(item.get("comparison"))
        for item in rows
        if item.get("comparison")
    }

    raw_kinds = sorted({
        str(item.get("kind"))
        for item in rows
        if item.get("kind")
    })

    def relation_family(kind):
        if kind in {
            "partial_overlap",
            "substantial_overlap",
        }:
            return "overlap"
        return kind

    families = sorted({
        relation_family(kind)
        for kind in raw_kinds
        if kind
    })

    gap_values = [
        safe_float(
            item.get(
                "gap_m"
            )
        )
        for item in rows
        if safe_float(
            item.get(
                "gap_m"
            )
        ) is not None
    ]

    overlap_values = [
        safe_float(
            item.get(
                "overlap_m"
            )
        )
        for item in rows
        if (
            safe_float(
                item.get(
                    "overlap_m"
                )
            )
            is not None
            and
            safe_float(
                item.get(
                    "overlap_m"
                )
            )
            > 0.0
        )
    ]

    result = {
        "comparison_count":
            len(comparisons),
        "kinds":
            raw_kinds,
        "families":
            families,
        "gap_min_m":
            min(gap_values)
            if gap_values
            else None,
        "gap_max_m":
            max(gap_values)
            if gap_values
            else None,
        "overlap_min_m":
            min(overlap_values)
            if overlap_values
            else None,
        "overlap_max_m":
            max(overlap_values)
            if overlap_values
            else None,
        "per_comparison":
            rows,
    }

    if len(families) == 1:
        result["kind"] = families[0]
    else:
        result["kind"] = (
            "mixed_across_comparisons"
        )

    return result

def _session_brake_release_fact(episode):
    """
    Extrae evidencia física de liberación de freno para agregación de sesión.

    VALID puede autorizar coaching individual.
    DUPLICATE conserva la medición física para el agregado entre comparaciones,
    pero nunca autoriza coaching individual.
    """
    if not isinstance(episode, dict):
        return None

    value = episode.get("brake_release_point_comparison")
    if not isinstance(value, dict):
        return None

    source_status = value.get("status")
    if source_status not in {"VALID", "DUPLICATE"}:
        return None

    delta_m = safe_float(value.get("comparison_minus_reference_m"))
    reference_release_m = safe_float(value.get("reference_release_m"))
    comparison_release_m = safe_float(value.get("comparison_release_m"))

    if (
        delta_m is None
        or reference_release_m is None
        or comparison_release_m is None
        or abs(delta_m) < BRAKE_RELEASE_SESSION_MIN_DELTA_M
    ):
        return None

    if delta_m < 0.0:
        coaching_direction = "later"
        relative_direction = "earlier_in_comparison_lap"
    elif delta_m > 0.0:
        coaching_direction = "earlier"
        relative_direction = "later_in_comparison_lap"
    else:
        return None

    return {
        "status": "VALID",
        "source_status": source_status,
        "braking_pair_id": value.get("braking_pair_id"),
        "reference_event_id": value.get("reference_event_id"),
        "comparison_event_id": value.get("comparison_event_id"),
        "reference_release_m": reference_release_m,
        "comparison_release_m": comparison_release_m,
        "comparison_minus_reference_m": delta_m,
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))),
        "authorized_numeric_coaching": bool(
            source_status == "VALID"
            and value.get("authorized_numeric_coaching")
        ),
        "session_aggregation_eligible": True,
    }

def _session_braking_point_fact(episode):
    """
    Extrae evidencia física de punto de frenada para la agregación de sesión.

    Importante:
    - VALID + authorized_numeric_coaching=True puede emitir coaching individual.
    - DUPLICATE NO puede emitir coaching individual, pero sigue representando
      el mismo evento físico medido y por lo tanto puede aportar una muestra
      a la agregación entre comparaciones.
    - la agregación posterior ya conserva como máximo una observación por
      comparación para cada evento físico, por lo que incluir DUPLICATE acá
      no reintroduce doble conteo.
    """
    if not isinstance(episode, dict):
        return None

    value = episode.get("braking_point_comparison")
    if not isinstance(value, dict):
        return None

    source_status = value.get("status")
    if source_status not in {"VALID", "DUPLICATE"}:
        return None

    delta_m = safe_float(value.get("comparison_minus_reference_m"))
    reference_onset_m = safe_float(value.get("reference_onset_m"))
    comparison_onset_m = safe_float(value.get("comparison_onset_m"))

    if (
        delta_m is None
        or reference_onset_m is None
        or comparison_onset_m is None
        or abs(delta_m) < BRAKING_POINT_SESSION_MIN_DELTA_M
    ):
        return None

    if delta_m < 0.0:
        coaching_direction = "later"
        relative_direction = "earlier_in_comparison_lap"
    elif delta_m > 0.0:
        coaching_direction = "earlier"
        relative_direction = "later_in_comparison_lap"
    else:
        return None

    return {
        "status": "VALID",
        "source_status": source_status,
        "braking_pair_id": value.get("braking_pair_id"),
        "reference_event_id": value.get("reference_event_id"),
        "comparison_event_id": value.get("comparison_event_id"),
        "reference_onset_m": reference_onset_m,
        "comparison_onset_m": comparison_onset_m,
        "comparison_minus_reference_m": delta_m,
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))),
        "authorized_numeric_coaching": bool(
            source_status == "VALID"
            and value.get("authorized_numeric_coaching")
        ),
        "session_aggregation_eligible": True,
    }

def _session_throttle_onset_fact(episode):
    """Evidencia física de reaplicación de acelerador para agregado de sesión."""
    if not isinstance(episode, dict):
        return None

    value = episode.get("throttle_onset_point_comparison")
    if not isinstance(value, dict):
        return None

    source_status = value.get("status")
    if source_status not in {"VALID", "DUPLICATE"}:
        return None

    delta_m = safe_float(value.get("comparison_minus_reference_m"))
    reference_onset_m = safe_float(value.get("reference_onset_m"))
    comparison_onset_m = safe_float(value.get("comparison_onset_m"))

    if (
        delta_m is None
        or reference_onset_m is None
        or comparison_onset_m is None
        or abs(delta_m) < THROTTLE_ONSET_SESSION_MIN_DELTA_M
    ):
        return None

    if delta_m < 0.0:
        coaching_direction = "later"
        relative_direction = "earlier_in_comparison_lap"
    elif delta_m > 0.0:
        coaching_direction = "earlier"
        relative_direction = "later_in_comparison_lap"
    else:
        return None

    return {
        "status": "VALID",
        "source_status": source_status,
        "throttle_pair_id": value.get("throttle_pair_id"),
        "reference_event_id": value.get("reference_event_id"),
        "comparison_event_id": value.get("comparison_event_id"),
        "reference_onset_m": reference_onset_m,
        "comparison_onset_m": comparison_onset_m,
        "comparison_minus_reference_m": delta_m,
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))),
        "authorized_numeric_coaching": bool(
            source_status == "VALID"
            and value.get("authorized_numeric_coaching")
        ),
        "session_aggregation_eligible": True,
    }

def _session_throttle_release_fact(episode):
    """Evidencia física de liberación de acelerador para agregado de sesión."""
    if not isinstance(episode, dict):
        return None

    value = episode.get("throttle_release_point_comparison")
    if not isinstance(value, dict):
        return None

    source_status = value.get("status")
    if source_status not in {"VALID", "DUPLICATE"}:
        return None

    delta_m = safe_float(value.get("comparison_minus_reference_m"))
    reference_release_m = safe_float(value.get("reference_release_m"))
    comparison_release_m = safe_float(value.get("comparison_release_m"))

    if (
        delta_m is None
        or reference_release_m is None
        or comparison_release_m is None
        or abs(delta_m) < THROTTLE_RELEASE_SESSION_MIN_DELTA_M
    ):
        return None

    if delta_m < 0.0:
        coaching_direction = "later"
        relative_direction = "earlier_in_comparison_lap"
    elif delta_m > 0.0:
        coaching_direction = "earlier"
        relative_direction = "later_in_comparison_lap"
    else:
        return None

    return {
        "status": "VALID",
        "source_status": source_status,
        "throttle_pair_id": value.get("throttle_pair_id"),
        "reference_event_id": value.get("reference_event_id"),
        "comparison_event_id": value.get("comparison_event_id"),
        "reference_release_m": reference_release_m,
        "comparison_release_m": comparison_release_m,
        "comparison_minus_reference_m": delta_m,
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))),
        "authorized_numeric_coaching": bool(
            source_status == "VALID"
            and value.get("authorized_numeric_coaching")
        ),
        "session_aggregation_eligible": True,
    }

def safe_int(value):
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def normalize_grounding_text(value):
    if not isinstance(value, str):
        return ""

    normalized = unicodedata.normalize(
        "NFKD",
        value.lower(),
    )

    return "".join(
        char
        for char in normalized
        if not unicodedata.combining(char)
    )

def _channels_mentioned_in_text(text):
    normalized = normalize_grounding_text(text)
    found = set()

    for channel, patterns in CHANNEL_LANGUAGE_PATTERNS.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            found.add(channel)

    return found

def _explicit_command_direction_map(
    value,
):
    result = {}

    for clause in _explicit_directional_clauses(
        value
    ):
        direction = clause.get(
            "direction"
        )

        for channel in clause.get(
            "channels",
            set(),
        ):
            result.setdefault(
                channel,
                set(),
            ).add(
                direction
            )

    return {
        channel: next(iter(directions))
        for channel, directions in result.items()
        if len(directions) == 1
    }

def _explicit_directional_clauses(value):
    """
    Extrae órdenes explícitas de aumentar/reducir y sus canales.

    El alcance termina ante:
    - otra orden direccional;
    - puntuación fuerte;
    - "y" seguido por una nueva acción verbal.
    """
    if not isinstance(value, str):
        return []

    normalized = normalize_grounding_text(value)
    matches = list(COACHING_DIRECTION_VERB_RE.finditer(normalized))
    clauses = []

    for index, match in enumerate(matches):
        start = match.start()
        next_start = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(normalized)
        )

        raw_segment = normalized[start:next_start]

        stop_positions = []

        strong_stop = re.search(r"[.;:\n]", raw_segment)
        if strong_stop:
            stop_positions.append(strong_stop.start())

        new_action = COACHING_NEW_ACTION_AFTER_AND_RE.search(raw_segment)
        if new_action:
            stop_positions.append(new_action.start())

        if stop_positions:
            raw_segment = raw_segment[:min(stop_positions)]

        verb = match.group(0)
        if COACHING_INCREASE_VERB_RE.fullmatch(verb):
            coaching_direction = "increase"
        elif COACHING_DECREASE_VERB_RE.fullmatch(verb):
            coaching_direction = "decrease"
        else:
            continue

        channels = _channels_mentioned_in_text(raw_segment)
        if channels:
            clauses.append(
                {
                    "direction": coaching_direction,
                    "channels": channels,
                    "text": raw_segment,
                }
            )

    return clauses

def _steering_direct_action_present(text):
    """
    v3.10.8.5.4

    Distingue una mención descriptiva de steering de una orden directa.
    El steering puede seguir apareciendo en interpretation/observaciones sin
    que eso active el contrato de coaching secundario.
    """
    if not isinstance(text, str):
        return False

    return bool(
        STEERING_DIRECT_ACTION_RE.search(
            normalize_grounding_text(text)
        )
    )

def build_driver_cues_for_plan_item(item, max_cues=2):
    """
    Construye como máximo dos cues driver-facing.

    v3.10.8.5.4:
    1) onset/release conserva máxima prioridad como target físico;
    2) reference_action_profile conserva prioridad sobre diferencias de nivel;
    3) brake/throttle con dirección determinista unívoca pueden producir un cue
       cualitativo hacia la referencia, sin magnitud inventada;
    4) steering puede ser cue único o secundario sólo cuando el LLM validado lo
       eligió explícitamente para un hallazgo PRIORITARIO;
    5) temporal_relationships sigue siendo observación y nunca se convierte en
       target por esta función.
    """
    if not isinstance(item, dict):
        return []

    cues = []

    def first_pattern(field):
        values = item.get(field, []) or []
        return values[0] if values and isinstance(values[0], dict) else None

    def point_phrase(pattern, later_text, earlier_text):
        if not isinstance(pattern, dict):
            return None
        magnitude = safe_int(pattern.get("coaching_magnitude_m"))
        direction = pattern.get("coaching_direction")
        if magnitude is None:
            return None
        if direction == "later":
            return later_text.format(magnitude=magnitude)
        if direction == "earlier":
            return earlier_text.format(magnitude=magnitude)
        return None

    profiles_by_channel = {}
    for profile in (item.get("reference_action_profiles", []) or []):
        if not isinstance(profile, dict):
            continue
        channel = profile.get("channel")
        summary = str(profile.get("shape_summary") or "").strip()
        if channel in {"brake", "throttle"} and summary and channel not in profiles_by_channel:
            profiles_by_channel[channel] = profile

    brake_onset = point_phrase(
        first_pattern("braking_point_patterns"),
        "frená aproximadamente {magnitude} m más tarde",
        "frená aproximadamente {magnitude} m más temprano",
    )
    brake_release = point_phrase(
        first_pattern("brake_release_patterns"),
        "soltá el freno aproximadamente {magnitude} m más tarde",
        "soltá el freno aproximadamente {magnitude} m más temprano",
    )
    if brake_onset or brake_release:
        text = " y ".join(value for value in (brake_onset, brake_release) if value)
        brake_patterns = [
            pattern
            for field in ("braking_point_patterns", "brake_release_patterns")
            for pattern in (item.get(field, []) or [])
            if isinstance(pattern, dict)
        ]
        point_count = max(
            [safe_int(pattern.get("comparison_count")) or 1 for pattern in brake_patterns],
            default=1,
        )
        cue = {
            "channel": "brake",
            "kind": "spatial_points",
            "text": text,
            "source": "authorized_brake_onset_release",
            "point_comparison_count": point_count,
            "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
        }
        precision_evidence = [
            pattern.get("precision_evidence")
            for pattern in brake_patterns
            if isinstance(pattern.get("precision_evidence"), dict)
        ]
        if precision_evidence:
            cue["precision_evidence"] = precision_evidence
        cues.append(cue)

    throttle_onset = point_phrase(
        first_pattern("throttle_onset_patterns"),
        "reaplicá el acelerador aproximadamente {magnitude} m más tarde",
        "reaplicá el acelerador aproximadamente {magnitude} m más temprano",
    )
    throttle_release = point_phrase(
        first_pattern("throttle_release_patterns"),
        "soltá el acelerador aproximadamente {magnitude} m más tarde",
        "soltá el acelerador aproximadamente {magnitude} m más temprano",
    )
    if throttle_onset or throttle_release:
        profile = profiles_by_channel.get("throttle")
        profile_text = (
            _driver_facing_throttle_profile_text(
                profile.get("shape_summary")
            )
            if profile is not None
            else ""
        )

        if throttle_onset and throttle_release:
            text = f"{throttle_onset} y {throttle_release}"
        elif throttle_onset:
            text = throttle_onset
        else:
            text = throttle_release

        throttle_patterns = [
            pattern
            for field in ("throttle_onset_patterns", "throttle_release_patterns")
            for pattern in (item.get(field, []) or [])
            if isinstance(pattern, dict)
        ]
        point_count = max(
            [safe_int(pattern.get("comparison_count")) or 1 for pattern in throttle_patterns],
            default=1,
        )

        cue = {
            "channel": "throttle",
            "kind": "spatial_points",
            "text": text,
            "source": "authorized_throttle_onset_release",
            "point_comparison_count": point_count,
            "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
        }
        if profile is not None:
            cue["reference_action_profile"] = profile
        precision_evidence = [
            pattern.get("precision_evidence")
            for pattern in throttle_patterns
            if isinstance(pattern.get("precision_evidence"), dict)
        ]
        if precision_evidence:
            cue["precision_evidence"] = precision_evidence
        cues.append(cue)
        if profile is not None and profile_text:
            cues.append({
                "channel": "throttle",
                "kind": "reference_action_profile",
                "text": profile_text,
                "source": "reference_action_profile",
                "reference_action_profile": profile,
            })

    existing_channels = {cue.get("channel") for cue in cues}
    for channel in ("brake", "throttle"):
        if channel in existing_channels:
            continue
        profile = profiles_by_channel.get(channel)
        if profile is None:
            continue
        summary = str(profile.get("shape_summary") or "").strip()
        if not summary:
            continue
        prefix = "freno" if channel == "brake" else "acelerador"
        text = (
            _driver_facing_throttle_profile_text(summary)
            if channel == "throttle"
            else f"replicá la secuencia de {prefix} de la referencia: {summary}"
        )
        cues.append({
            "channel": channel,
            "kind": "reference_action_profile",
            "text": text,
            "source": "reference_action_profile",
            "reference_action_profile": profile,
        })
        existing_channels.add(channel)

    # v3.10.8.5.4 — si no existe un cue más específico para el canal, una
    # diferencia de nivel unívoca ya materializada en `targets` por Python
    # puede convertirse en instrucción cualitativa. Cuando brake y throttle
    # aparecen juntos, se combinan en UN cue para no expulsar automáticamente
    # un steering secundario del límite de dos cues.
    level_parts = []
    level_channels = []
    for target in (item.get("targets", []) or []):
        if not isinstance(target, str):
            continue
        direction_map = _explicit_command_direction_map(target)
        for channel in ("brake", "throttle"):
            if channel in existing_channels or channel in level_channels:
                continue
            if channel not in direction_map:
                continue
            direct = _direct_coaching_target_text(target)
            if not direct:
                continue
            level_parts.append(direct)
            level_channels.append(channel)

    if level_parts:
        cues.append({
            "channel": (
                "brake+throttle"
                if set(level_channels) == {"brake", "throttle"}
                else level_channels[0]
            ),
            "channels": list(level_channels),
            "kind": "qualitative_reference_level",
            "text": " y ".join(level_parts),
            "source": "deterministic_observed_level_to_reference",
            "point_comparison_count": 0,
            "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
        })

    sequence = item.get("coaching_sequence")
    if isinstance(sequence, dict) and sequence.get("status") == "COMBINED":
        spatial_indexes = [
            index
            for index, cue in enumerate(cues)
            if cue.get("kind") == "spatial_points"
            and cue.get("channel") in {"brake", "throttle"}
        ]
        if len(spatial_indexes) >= 2:
            first_index = spatial_indexes[0]
            evidence = [
                event.get("precision_evidence")
                for event in (sequence.get("events") or [])
                if isinstance(event, dict)
                and isinstance(event.get("precision_evidence"), dict)
            ]
            combined = {
                "channel": "brake+throttle",
                "channels": ["brake", "throttle"],
                "kind": "combined_spatial_sequence",
                "text": str(sequence.get("driver_summary") or "").strip(),
                "source": "deterministic_coaching_sequence",
                "coaching_sequence": sequence,
                "point_comparison_count": max(
                    [
                        safe_int(cues[i].get("point_comparison_count")) or 0
                        for i in spatial_indexes
                    ],
                    default=0,
                ),
                "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
            }
            if evidence:
                combined["precision_evidence"] = evidence
            cues = [
                cue
                for index, cue in enumerate(cues)
                if index not in spatial_indexes
            ]
            cues.insert(first_index, combined)

    if item.get("steering_coaching_requested"):
        recommendation = str(item.get("validated_recommendation") or "").strip()
        if recommendation and _steering_direct_action_present(recommendation):
            direction = item.get("steering_direction")
            if direction == "higher_in_comparison_lap":
                steering_text = "reducí la magnitud del volante hacia la referencia"
            elif direction == "lower_in_comparison_lap":
                steering_text = "aumentá la magnitud del volante hacia la referencia"
            else:
                steering_text = "replicá la secuencia de dirección de la referencia"
            cues.append({
                "channel": "steering_magnitude",
                "kind": "validated_llm_steering",
                "text": steering_text,
                "source": "validated_llm_recommendation+python_direction",
                "point_comparison_count": 0,
                "region_comparison_count": safe_int(item.get("comparison_count")) or 0,
            })

    return cues[:max_cues]

def deterministic_priority_for_plan_item(
    item,
):
    """v3.10.8: el driver ve como máximo dos cues accionables por zona."""
    if not isinstance(item, dict):
        return None
    label = str(item.get("plan_label") or "?").strip()
    cues = item.get("driver_cues") or build_driver_cues_for_plan_item(item)
    texts = [str(cue.get("text") or "").strip() for cue in cues[:2] if isinstance(cue, dict)]
    texts = [text for text in texts if text]
    if not texts:
        return None
    return f"Zona prioritaria {label}: " + "; ".join(texts)

def build_deterministic_next_session_priorities(
    session_coaching_facts,
):
    plan = (
        session_coaching_facts.get(
            "next_stint_plan",
            [],
        )
        if isinstance(
            session_coaching_facts,
            dict,
        )
        else []
    ) or []

    return [
        value
        for value in (
            deterministic_priority_for_plan_item(
                item
            )
            for item in plan[:3]
        )
        if value
    ]
