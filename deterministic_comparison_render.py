"""Pure formatting primitives for the deterministic comparison debrief."""

from deterministic_coaching import (
    _single_objective_channel_direction,
    _steering_direct_action_present,
    safe_float,
    safe_int,
)
from session_coaching_location import track_location_label


def signed_seconds(value):
    value = safe_float(value)
    if value is None:
        return "N/D"
    return f"{value:+.4f} s"


def format_lap_time(value):
    """Render an absolute lap time as m:ss.mmm."""
    value = safe_float(value)
    if value is None:
        return "N/D"

    sign = "-" if value < 0 else ""
    value = abs(value)
    minutes = int(value // 60)
    seconds = value - (minutes * 60)
    return f"{sign}{minutes}:{seconds:06.3f}"


def meters(value):
    value = safe_float(value)
    if value is None:
        return "N/D"
    return f"{value:.0f} m"


def format_channel_names(channels):
    if not channels:
        return "sin canales de acción"
    names = {
        "throttle": "acelerador",
        "brake": "freno",
        "steering_magnitude": "magnitud de dirección",
    }
    return ", ".join(names.get(channel, channel) for channel in channels)


def render_hypotheses(hypotheses):
    if not hypotheses:
        return "- Sin hipótesis adicional."
    return "\n".join(f"- {item}" for item in hypotheses)


def assessment_map(structured_response):
    return {
        safe_int(item["episode_id"]): item
        for item in structured_response["episode_assessments"]
    }


def episode_authorized_driver_cues(episode, max_cues=2):
    """Return driver cues backed only by authorized physical points."""
    if not isinstance(episode, dict):
        return []

    def point(value, later_text, earlier_text):
        if not isinstance(value, dict):
            return None
        if value.get("status") != "VALID" or not value.get(
            "authorized_numeric_coaching"
        ):
            return None
        magnitude = safe_int(value.get("coaching_magnitude_m"))
        direction = value.get("coaching_direction")
        if magnitude is None:
            return None
        if direction == "later":
            return later_text.format(magnitude=magnitude)
        if direction == "earlier":
            return earlier_text.format(magnitude=magnitude)
        return None

    cues = []
    brake_onset = point(
        episode.get("braking_point_comparison"),
        "frená aproximadamente {magnitude} m más tarde",
        "frená aproximadamente {magnitude} m más temprano",
    )
    brake_release = point(
        episode.get("brake_release_point_comparison"),
        "soltá el freno aproximadamente {magnitude} m más tarde",
        "soltá el freno aproximadamente {magnitude} m más temprano",
    )
    if brake_onset or brake_release:
        cues.append({
            "channel": "brake",
            "text": " y ".join(v for v in (brake_onset, brake_release) if v),
            "source": "authorized_brake_onset_release",
        })

    throttle_onset = point(
        episode.get("throttle_onset_point_comparison"),
        "reaplicá el acelerador aproximadamente {magnitude} m más tarde",
        "reaplicá el acelerador aproximadamente {magnitude} m más temprano",
    )
    throttle_release = point(
        episode.get("throttle_release_point_comparison"),
        "soltá el acelerador aproximadamente {magnitude} m más tarde",
        "soltá el acelerador aproximadamente {magnitude} m más temprano",
    )
    if throttle_onset or throttle_release:
        cues.append({
            "channel": "throttle",
            "text": " y ".join(
                v for v in (throttle_onset, throttle_release) if v
            ),
            "source": "authorized_throttle_onset_release",
        })
    return cues[:max_cues]


def episode_validated_steering_cue(episode, assessment):
    """Render steering only after the existing Python validation contract."""
    if not isinstance(episode, dict) or not isinstance(assessment, dict):
        return None
    if "steering_magnitude" not in set(episode.get("action_channels", []) or []):
        return None
    recommendation = str(assessment.get("recommendation") or "").strip()
    if not recommendation or not _steering_direct_action_present(recommendation):
        return None

    observed = _single_objective_channel_direction(
        episode, "steering_magnitude"
    )
    if observed == "higher_in_comparison_lap":
        text = "reducí la magnitud del volante hacia la referencia"
    elif observed == "lower_in_comparison_lap":
        text = "aumentá la magnitud del volante hacia la referencia"
    else:
        text = "replicá la secuencia de dirección de la referencia"
    return {
        "channel": "steering_magnitude",
        "kind": "validated_llm_steering",
        "text": text,
        "source": "validated_llm_recommendation+python_direction",
    }


def compose_episode_driver_cue_text(physical_cues, steering_cue):
    physical_texts = [
        str(cue.get("text") or "").strip()
        for cue in (physical_cues or [])[:2]
        if isinstance(cue, dict) and str(cue.get("text") or "").strip()
    ]
    if physical_texts:
        text = "; ".join(physical_texts)
        if steering_cue and str(steering_cue.get("text") or "").strip():
            text += "; como ajuste de volante, " + str(steering_cue["text"]).strip()
        return text
    if steering_cue:
        return str(steering_cue.get("text") or "").strip()
    return ""


def comparison_actionable_focus(episode_catalog, structured_response):
    """Build a bounded driver-facing focus from validated deterministic cues."""
    amap = assessment_map(structured_response)
    ranked = []
    for episode in episode_catalog:
        assessment = amap.get(episode.get("episode_id"), {})
        classification = assessment.get("classification")
        class_rank = {"PRIORITARIO": 0, "SECUNDARIO": 1}.get(classification, 2)
        physical_cues = episode_authorized_driver_cues(episode)
        steering_cue = episode_validated_steering_cue(episode, assessment)
        steering_only = bool(steering_cue and not physical_cues)
        if steering_only and classification != "PRIORITARIO":
            continue
        if not physical_cues and not steering_cue:
            continue
        ranked.append((
            1 if steering_only else 0,
            class_rank,
            safe_int(episode.get("global_rank"))
            or safe_int(episode.get("rank"))
            or 999999,
            -abs(safe_float(episode.get("action_time_loss_s")) or 0.0),
            episode,
            physical_cues,
            steering_cue,
        ))

    if not ranked:
        return None
    ranked.sort(key=lambda row: row[:4])
    parts = []
    steering_only_used = False
    for steering_only_rank, _, _, _, episode, physical_cues, steering_cue in ranked:
        steering_only = bool(steering_only_rank)
        if steering_only and steering_only_used:
            continue
        text = compose_episode_driver_cue_text(physical_cues, steering_cue)
        if not text:
            continue
        location = track_location_label(episode)
        prefix = f"{location}: " if location else ""
        parts.append(prefix + text)
        steering_only_used = steering_only_used or steering_only
        if len(parts) >= 2:
            break
    if not parts:
        return None
    return "Para la próxima vuelta, priorizá " + "; ".join(parts) + "."


def episode_spatial_facts(episode):
    """Render measured point and throttle-state facts without adding coaching."""
    facts = []

    point_specs = (
        (
            "braking_point_comparison",
            "inicio de frenada",
            "inicio de frenada dentro de la zona muerta",
        ),
        (
            "brake_release_point_comparison",
            "liberación de freno",
            "liberación de freno dentro de la zona muerta",
        ),
        (
            "throttle_onset_point_comparison",
            "reaplicación de acelerador",
            "reaplicación de acelerador dentro de la zona muerta",
        ),
        (
            "throttle_release_point_comparison",
            "liberación de acelerador",
            "liberación de acelerador dentro de la zona muerta",
        ),
    )
    for key, label, neutral_text in point_specs:
        point = episode.get(key)
        if not isinstance(point, dict) or point.get("status") != "VALID":
            continue
        delta = safe_float(point.get("comparison_minus_reference_m"))
        direction = point.get("relative_direction")
        magnitude = safe_float(point.get("coaching_magnitude_m"))
        coaching_direction = point.get("coaching_direction")
        if direction == "similar_to_reference":
            facts.append(neutral_text)
        elif delta is not None:
            where = "antes" if delta < 0 else "después"
            item = f"{label} {abs(delta):.0f} m {where} de la referencia"
            if point.get("authorized_numeric_coaching") and magnitude is not None:
                move = (
                    "más tarde"
                    if coaching_direction == "later"
                    else "más temprano"
                )
                item += f"; objetivo {magnitude:.0f} m {move}"
            facts.append(item)

    full_throttle = episode.get("throttle_full_throttle_attainment_comparison")
    if isinstance(full_throttle, dict) and full_throttle.get("status") == "VALID":
        relation = full_throttle.get("relative_direction")
        delta = safe_float(full_throttle.get("comparison_minus_reference_m"))
        if relation in {
            "earlier_in_comparison_lap",
            "later_in_comparison_lap",
        } and delta is not None:
            where = "antes" if delta < 0 else "después"
            facts.append(
                "acelerador casi pleno confirmado "
                f"{abs(delta):.0f} m {where} de la referencia (observacional)"
            )
        elif relation == "similar_to_reference":
            facts.append(
                "acelerador casi pleno confirmado en un punto similar a la "
                "referencia (observacional)"
            )
        elif relation == "reference_attained_comparison_not_confirmed":
            facts.append(
                "la referencia alcanzó acelerador casi pleno confirmado; la "
                "vuelta comparada no lo confirmó en el mismo evento "
                "(observacional)"
            )
        elif relation == "comparison_attained_reference_not_confirmed":
            facts.append(
                "la vuelta comparada alcanzó acelerador casi pleno confirmado; "
                "la referencia no lo confirmó en el mismo evento (observacional)"
            )

    partial_lift = episode.get("throttle_partial_lift_comparison")
    if isinstance(partial_lift, dict) and partial_lift.get("status") == "VALID":
        reference_count = safe_int(partial_lift.get("reference_partial_lift_count"))
        comparison_count = safe_int(
            partial_lift.get("comparison_partial_lift_count")
        )
        if reference_count is not None and comparison_count is not None:
            facts.append(
                "lifts parciales recuperados: "
                f"referencia {reference_count}, comparación {comparison_count} "
                "(observacional)"
            )
    return facts


def render_comparison_analysis(comparison, episode_catalog, structured_response):
    """Render the stable comparison debrief Markdown contract."""
    amap = assessment_map(structured_response)
    lines = []
    reference_lap = comparison["reference_lap"]
    comparison_lap = comparison["comparison_lap"]

    def prose(value):
        value = str(value or "").strip()
        if not value:
            return ""
        value = value[0].upper() + value[1:]
        if value[-1] not in ".!?":
            value += "."
        return value

    lines.extend([
        f"# Debrief de vuelta — {reference_lap} → {comparison_lap}",
        "",
        "## Lectura rápida",
        "",
        (
            f"La vuelta {comparison_lap} quedó en "
            f"{format_lap_time(comparison['comparison_time_s'])}, "
            f"{signed_seconds(comparison['comparison_minus_reference_s'])} "
            f"respecto de la referencia de "
            f"{format_lap_time(comparison['reference_time_s'])}."
        ),
    ])
    actionable_focus = comparison_actionable_focus(
        episode_catalog, structured_response
    )
    conclusion = prose(actionable_focus) if actionable_focus else (
        "No hay un punto físico onset/release autorizado para convertir "
        "esta comparación en una instrucción directa; las diferencias de "
        "inputs quedan como observación."
    )
    if conclusion:
        lines.extend(["", conclusion])

    priority_episodes = [
        episode for episode in episode_catalog
        if amap[episode["episode_id"]]["classification"] == "PRIORITARIO"
    ]
    secondary_episodes = [
        episode for episode in episode_catalog
        if amap[episode["episode_id"]]["classification"] == "SECUNDARIO"
    ]
    non_actionable = [
        episode for episode in episode_catalog
        if amap[episode["episode_id"]]["classification"] == "NO_ACCIONABLE"
    ]

    def strength_label(value):
        return {"strong": "alta", "moderate": "media", "weak": "baja"}.get(
            str(value).lower(), str(value) if value else None
        )

    standalone_steering_priority_id = None
    for candidate in priority_episodes:
        candidate_assessment = amap.get(candidate.get("episode_id"), {})
        if episode_authorized_driver_cues(candidate):
            continue
        if episode_validated_steering_cue(candidate, candidate_assessment):
            standalone_steering_priority_id = candidate.get("episode_id")
            break

    def render_episode(episode, ordinal=None):
        episode_id = episode["episode_id"]
        assessment = amap[episode_id]
        location = track_location_label(episode)
        heading = location or f"Episodio #{episode_id}"
        lines.append(
            f"### {ordinal}. {heading}" if ordinal is not None else f"### {heading}"
        )
        lines.append("")
        interpretation = prose(assessment.get("interpretation"))
        if interpretation:
            lines.extend([interpretation, ""])

        driver_cues = episode_authorized_driver_cues(episode)
        steering_cue = episode_validated_steering_cue(episode, assessment)
        classification = assessment.get("classification")
        cue_text = ""
        if driver_cues:
            cue_text = compose_episode_driver_cue_text(driver_cues, steering_cue)
        elif (
            steering_cue
            and classification == "PRIORITARIO"
            and episode_id == standalone_steering_priority_id
        ):
            cue_text = compose_episode_driver_cue_text([], steering_cue)

        if cue_text:
            lines.extend(["**Qué probar:** " + prose(cue_text), ""])
        elif assessment.get("recommendation"):
            lines.extend([
                "**Observación de coaching:** la recomendación validada no "
                "entra en el foco accionable de este debrief; queda como "
                "evidencia secundaria.",
                "",
            ])

        objective_bits = [
            f"cambio de delta {signed_seconds(episode.get('action_time_loss_s'))}",
            f"inputs: {format_channel_names(episode.get('action_channels', []))}",
        ]
        strength = strength_label(episode.get("evidence_strength"))
        if strength:
            objective_bits.append(f"evidencia {strength}")
        lines.append("**Referencia objetiva:** " + "; ".join(objective_bits) + ".")

        points = episode_spatial_facts(episode)
        if points:
            lines.extend(["", "**Puntos medidos:** " + "; ".join(points) + "."])
        if episode.get("speed_propagation"):
            lines.extend([
                "",
                "**Contexto:** la diferencia de velocidad continuó después "
                "de terminar este bloque de acción.",
            ])
        lines.append("")

    lines.extend(["", "## Puntos de trabajo", ""])
    if priority_episodes:
        for ordinal, episode in enumerate(priority_episodes, start=1):
            render_episode(episode, ordinal)
    else:
        lines.extend([
            "No hay episodios prioritarios accionables en esta comparación.",
            "",
        ])

    if secondary_episodes:
        lines.extend(["## Aspectos secundarios", ""])
        for episode in secondary_episodes:
            assessment = amap[episode["episode_id"]]
            location = track_location_label(episode) or (
                f"Episodio #{episode['episode_id']}"
            )
            cues = episode_authorized_driver_cues(episode)
            steering_cue = episode_validated_steering_cue(episode, assessment)
            if cues:
                text = compose_episode_driver_cue_text(cues, steering_cue)
                lines.append(f"- **{location}:** {prose(text)}")
            else:
                observation = prose(assessment.get("interpretation"))
                if observation:
                    lines.append(
                        f"- **{location}:** observación solamente — {observation}"
                    )
        lines.append("")

    lines.extend([
        "## Respaldo técnico",
        "",
        "La clasificación completa se mantiene en el JSON. Resumen de episodios:",
        "",
    ])
    for episode in episode_catalog:
        episode_id = episode["episode_id"]
        assessment = amap[episode_id]
        location = track_location_label(episode)
        location_text = f"{location} · " if location else ""
        lines.append(
            f"- #{episode_id} · {assessment['classification']} · "
            f"{location_text}{meters(episode.get('start_distance_m'))}–"
            f"{meters(episode.get('end_distance_m'))} · "
            f"{signed_seconds(episode.get('action_time_loss_s'))}."
        )

    limitations = structured_response.get("limitations") or []
    if limitations:
        lines.extend(["", "## Límites de esta lectura", ""])
        for item in limitations[:2]:
            lines.append(f"- {prose(item)}")
    if non_actionable:
        lines.extend([
            "",
            "Los episodios no accionables permanecen registrados en el JSON "
            "y no se convierten en instrucciones de conducción.",
        ])
    return "\n".join(lines)
