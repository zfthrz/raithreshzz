"""Backend-independent byte-compatible global debrief renderer."""

from deterministic_coaching import (
    _render_speed_context_fact,
    build_driver_cues_for_plan_item,
    safe_float,
    safe_int,
)
from deterministic_comparison_render import format_lap_time, signed_seconds
from session_coaching_location import track_location_label
from session_coaching_quality import _session_comparison_key
from session_coaching_recurrence import _comparison_quality_map



def _render_action_delta_fact(
    value,
):
    value = safe_float(
        value
    )

    if value is None:
        return "variación de delta N/D"

    if value >= 0:
        return (
            f"+{value:.4f} s de pérdida "
            "durante la acción"
        )

    return (
        f"{abs(value):.4f} s de ganancia "
        "durante la acción"
    )


def _render_precision_evidence_lines(cue):
    if not isinstance(cue, dict):
        return []
    evidence_rows = [
        row
        for row in (cue.get("precision_evidence", []) or [])
        if isinstance(row, dict)
    ]
    if not evidence_rows:
        return []

    # El primer punto del cue es el ancla principal. Si el cue contiene onset
    # y release, los detalles completos permanecen en el JSON.
    evidence = evidence_rows[0]
    reference_lap = safe_int(evidence.get("reference_lap"))
    supporting_laps = [
        safe_int(value)
        for value in (evidence.get("supporting_laps", []) or [])
        if safe_int(value) is not None
    ]
    anchor = evidence.get("corner_relative_reference")
    anchor_label = (
        str(anchor.get("driver_label") or "").strip()
        if isinstance(anchor, dict)
        else ""
    )

    lines = []
    reference_parts = []
    if reference_lap is not None:
        reference_parts.append(f"vuelta {reference_lap}")
    if anchor_label:
        reference_parts.append(f"punto de referencia {anchor_label}")
    if reference_parts:
        lines.append("**Referencia del cue:** " + "; ".join(reference_parts) + ".")

    if supporting_laps:
        if len(supporting_laps) == 1:
            laps_text = f"la vuelta {supporting_laps[0]}"
        else:
            laps_text = "las vueltas " + ", ".join(str(v) for v in supporting_laps[:-1]) + f" y {supporting_laps[-1]}"
        evidence_parts = [f"el mismo desvío apareció en {laps_text}"]
        low = safe_float(evidence.get("observed_delta_min_m"))
        high = safe_float(evidence.get("observed_delta_max_m"))
        representative = safe_int(evidence.get("representative_delta_m"))
        if low is not None and high is not None:
            low_i = int(round(low))
            high_i = int(round(high))
            if low_i == high_i:
                evidence_parts.append(f"diferencia observada ~{low_i} m")
            else:
                evidence_parts.append(f"rango observado {low_i}–{high_i} m")
        if representative is not None:
            evidence_parts.append(f"valor representativo {representative} m")
        lines.append("**Evidencia entre vueltas:** " + "; ".join(evidence_parts) + ".")

    return lines


def _deterministic_session_focus(plan):
    parts = []
    for item in (plan or [])[:3]:
        cues = item.get("driver_cues") or build_driver_cues_for_plan_item(item)
        if not cues:
            continue
        label = str(item.get("plan_label") or "?")
        location = track_location_label(item)
        where = f"zona {label}"
        if location:
            where += f" ({location})"
        parts.append(where)
    if not parts:
        return "No apareció un cue de conducción suficientemente respaldado para la próxima tanda."
    return (
        "Priorizá " + "; ".join(parts) + ". "
        "Las acciones completas están en el plan."
    )



def render_global_analysis(
    metadata,
    comparison_results,
    session_coaching_facts,
    global_structured,
):
    """
    Presentación v1.4 del debrief de sesión.

    El detalle granular sigue disponible en session_coaching_facts y en cada
    comparación. El texto visible prioriza lectura, plan y respaldo.
    """
    lines = []

    track = metadata.get("track") or "Sesión"
    session_type = metadata.get("session_type")
    title_suffix = f" · {session_type}" if session_type else ""

    lines.append(f"# Debrief de ingeniería — {track}{title_suffix}")
    lines.append("")

    lap_times = metadata.get("lap_times_s", {}) or {}
    reference_lap = safe_int(metadata.get("reference_lap"))
    reference_time = safe_float(lap_times.get(str(reference_lap)))

    plan = session_coaching_facts.get("next_stint_plan", []) or []

    # Repeated physical patterns are shared by both the narrative section
    # and the technical appendix. Initialize them before either section.
    braking_patterns = (
        session_coaching_facts.get("repeated_braking_point_patterns", []) or []
    )
    brake_release_patterns = (
        session_coaching_facts.get("repeated_brake_release_patterns", []) or []
    )
    throttle_onset_patterns = (
        session_coaching_facts.get("repeated_throttle_onset_patterns", []) or []
    )
    throttle_release_patterns = (
        session_coaching_facts.get("repeated_throttle_release_patterns", []) or []
    )

    def prose(value):
        value = str(value or "").strip()
        if not value:
            return ""
        value = value[0].upper() + value[1:]
        if value[-1] not in ".!?":
            value += "."
        return value

    if reference_time is None and comparison_results:
        reference_time = safe_float(
            comparison_results[0].get("reference_time_s")
        )

    # ----------------------------------------------------------
    # Lectura primero: debe poder entenderse sin mirar el apéndice.
    # ----------------------------------------------------------
    lines.append("## Resumen de la sesión")
    lines.append("")

    if reference_lap is not None and reference_time is not None:
        lines.append(
            f"La referencia de trabajo fue la vuelta {reference_lap}, "
            f"con {format_lap_time(reference_time)}."
        )
    elif reference_lap is not None:
        lines.append(f"La referencia de trabajo fue la vuelta {reference_lap}.")

    if plan:
        def item_has_repeated_evidence(item):
            if item.get("kind") == "repeated_region":
                return True

            return any(
                (
                    safe_int(pattern.get("comparison_count"))
                    or 0
                )
                >= 2
                for field in (
                    "braking_point_patterns",
                    "brake_release_patterns",
                    "throttle_onset_patterns",
                    "throttle_release_patterns",
                )
                for pattern in (item.get(field, []) or [])
                if isinstance(pattern, dict)
            )

        repeated_count = sum(
            1 for item in plan
            if item_has_repeated_evidence(item)
        )
        zone_word = "zona prioritaria" if len(plan) == 1 else "zonas prioritarias"
        if repeated_count == len(plan) and repeated_count > 0:
            lines.append(
                f"El plan de la próxima tanda queda concentrado en "
                f"{len(plan)} {zone_word}, todas respaldadas por patrones "
                "repetidos entre comparaciones."
            )
        elif repeated_count:
            if repeated_count == 1:
                lines.append(
                    f"El plan de la próxima tanda queda concentrado en "
                    f"{len(plan)} {zone_word}; una de ellas cuenta con "
                    "patrones repetidos entre comparaciones."
                )
            else:
                lines.append(
                    f"El plan de la próxima tanda queda concentrado en "
                    f"{len(plan)} {zone_word}; {repeated_count} cuentan con "
                    "patrones repetidos entre comparaciones."
                )
        else:
            lines.append(
                f"El plan de la próxima tanda queda concentrado en "
                f"{len(plan)} {zone_word}."
            )

    # ----------------------------------------------------------
    # Foco principal driver-facing.
    #
    # P11 es la autoridad de presentación cuando está disponible. El foco
    # determinista legacy queda únicamente como fallback para debriefs o
    # payloads anteriores que todavía no traigan P11.
    # ----------------------------------------------------------
    next_stint_focus = session_coaching_facts.get("next_stint_focus", {}) or {}
    focus_items = (
        next_stint_focus.get("items", []) or []
        if next_stint_focus.get("status") == "ACTIVE"
        else []
    )

    rendered_focus = False

    if focus_items:
        focus_lines = []

        for focus_item in focus_items[:2]:
            if not isinstance(focus_item, dict):
                continue

            label = str(focus_item.get("plan_label") or "").strip()
            location = track_location_label(focus_item)

            prefix = ""
            if label and location:
                prefix = f"Zona {label} — {location}: "
            elif label:
                prefix = f"Zona {label}: "
            elif location:
                prefix = f"{location}: "

            cues = [
                cue
                for cue in (focus_item.get("driver_cues", []) or [])
                if isinstance(cue, dict)
                and str(cue.get("text") or "").strip()
            ]

            if not cues:
                continue

            focus_label = prefix.rstrip(": ") or "Zona prioritaria"
            focus_lines.append(
                f"- {focus_label}: foco seleccionado; "
                "ver acciones completas en el plan."
            )

        if focus_lines:
            lines.append("")
            lines.append("## Foco principal")
            lines.append("")
            lines.extend(focus_lines)
            rendered_focus = True

    if not rendered_focus:
        session_focus = _deterministic_session_focus(plan)
        if session_focus:
            lines.append("")
            lines.append(session_focus)

    quality_gate = session_coaching_facts.get("comparison_quality_gate", {}) or {}
    excluded_comparisons = quality_gate.get("excluded_comparisons", []) or []
    if excluded_comparisons:
        lines.append("")
        if len(excluded_comparisons) == 1:
            lines.append(
                "Una comparación globalmente no representativa quedó fuera del agregado "
                "de coaching de esta sesión; permanece disponible en el JSON."
            )
        else:
            lines.append(
                f"{len(excluded_comparisons)} comparaciones globalmente no representativas "
                "quedaron fuera del agregado de coaching de esta sesión; permanecen disponibles en el JSON."
            )

    # ----------------------------------------------------------
    # Plan accionable
    # ----------------------------------------------------------
    lines.append("")
    lines.append("## Plan para la próxima tanda")
    lines.append("")

    priorities = global_structured.get("next_session_priorities", []) or []

    def clean_priority(text_value, label):
        value = str(text_value or "").strip()
        prefix = f"Zona prioritaria {label}:"
        if value.lower().startswith(prefix.lower()):
            value = value[len(prefix):].strip()
        if value and value[-1] not in ".!?":
            value += "."
        return value

    for index, item in enumerate(plan[:3], start=1):
        label = str(item.get("plan_label") or "?")
        location = track_location_label(item)
        heading = f"Zona {label}"
        if location:
            heading += f" — {location}"

        lines.append(f"### {index}. {heading}")
        lines.append("")

        driver_cues = item.get("driver_cues") or build_driver_cues_for_plan_item(item)
        if driver_cues:
            primary_cue = driver_cues[0]
            sequence = primary_cue.get("coaching_sequence") or {}
            sequence_steps = [
                str(event.get("text") or "").strip()
                for event in (sequence.get("events", []) or [])
                if isinstance(event, dict) and str(event.get("text") or "").strip()
            ]
            if (
                primary_cue.get("kind") == "combined_spatial_sequence"
                and sequence.get("status") == "COMBINED"
                and len(sequence_steps) >= 2
            ):
                lines.append("**Qué cambiar — secuencia:**")
                lines.append("")
                for step_index, step_text in enumerate(sequence_steps, start=1):
                    lines.append(f"{step_index}. {prose(step_text)}")
                lines.append("")
            else:
                first_cue = str(primary_cue.get("text") or "").strip()
                if first_cue:
                    lines.append(f"**Qué cambiar:** {prose(first_cue)}")
                    lines.append("")
            if len(driver_cues) > 1:
                second_cue = str(driver_cues[1].get("text") or "").strip()
                if second_cue:
                    lines.append(f"**Segundo cue:** {prose(second_cue)}")
                    lines.append("")

            precision_lines = _render_precision_evidence_lines(driver_cues[0])
            for precision_line in precision_lines:
                lines.append(precision_line)
            if precision_lines:
                lines.append("")

        reference_profiles = [
            profile
            for profile in (item.get("reference_action_profiles", []) or [])
            if isinstance(profile, dict) and profile.get("shape_summary")
        ]
        if reference_profiles:
            channel_labels = {
                "throttle": "Acelerador",
                "brake": "Freno",
            }
            profile_texts = []
            for profile in reference_profiles[:2]:
                summary = str(
                    profile.get("shape_summary_detailed")
                    or profile.get("shape_summary")
                    or ""
                ).strip()
                if not summary:
                    continue
                channel = str(profile.get("channel") or "").strip()
                prefix = channel_labels.get(channel, channel.capitalize() if channel else "Input")
                profile_texts.append(f"{prefix}: {summary}")

            if profile_texts:
                lines.append("**Forma observada en la referencia:**")
                for profile_text in profile_texts:
                    lines.append(f"- {prose(profile_text)}")
            lines.append(
                "_Descripción de forma; los puntos numéricos de coaching siguen "
                "siendo únicamente los autorizados por los detectores de eventos._"
            )
            lines.append("")

        comparisons = [
            str(v) for v in (item.get("comparisons", []) or []) if v
        ]
        comparison_count = item.get("comparison_count")
        observed = [
            str(v) for v in (item.get("observed_differences", []) or []) if v
        ]

        support_parts = []
        primary_cue_point_count = 0
        if driver_cues:
            primary_cue_point_count = (
                safe_int(driver_cues[0].get("point_comparison_count"))
                or 0
            )

        if primary_cue_point_count >= 2:
            support_parts.append(
                f"el punto físico que genera este cue se repitió en "
                f"{primary_cue_point_count} comparaciones"
            )
            if (
                item.get("kind") == "repeated_region"
                and comparison_count
                and comparison_count != primary_cue_point_count
            ):
                support_parts.append(
                    f"la región completa apareció en {comparison_count} comparaciones"
                )
        elif item.get("kind") == "repeated_region" and comparison_count:
            support_parts.append(
                f"la región apareció en {comparison_count} comparaciones"
            )
        elif item.get("kind") == "repeated_point_pattern" and comparison_count:
            support_parts.append(
                f"el punto de input se repitió en {comparison_count} comparaciones"
            )
        elif comparisons:
            support_parts.append("es el hallazgo individual mejor priorizado")

        repeated_point_counts = [
            safe_int(pattern.get("comparison_count")) or 0
            for field in (
                "braking_point_patterns",
                "brake_release_patterns",
                "throttle_onset_patterns",
                "throttle_release_patterns",
            )
            for pattern in (item.get(field, []) or [])
            if isinstance(pattern, dict)
        ]
        repeated_point_count = max(repeated_point_counts, default=0)

        if (
            item.get("kind")
            not in {
                "repeated_region",
                "repeated_point_pattern",
            }
            and repeated_point_count >= 2
        ):
            support_parts.append(
                f"además, un punto de input se repitió en "
                f"{repeated_point_count} comparaciones"
            )

        speed_fact = _render_speed_context_fact(item)
        if speed_fact:
            support_parts.append(f"el contexto mostró {speed_fact}")

        if support_parts:
            sentence = "; ".join(support_parts)
            sentence = sentence[0].upper() + sentence[1:] + "."
            lines.append(f"**Por qué está en el plan:** {sentence}")
            lines.append("")

        if observed:
            lines.append("**Qué observamos:** " + prose(", ".join(observed)))
            lines.append("")

        if primary_cue_point_count >= 2:
            lines.append(
                f"**Confianza del cue:** punto físico repetido en "
                f"{primary_cue_point_count} comparaciones válidas para el plan."
            )
            lines.append("")
        elif item.get("kind") == "repeated_region" and comparison_count:
            lines.append(
                f"**Confianza:** región repetida en {comparison_count} comparaciones válidas para el plan."
            )
            lines.append("")

        temporal = [
            str(v)
            for v in (item.get("temporal_relationships", []) or [])
            if v
        ]
        if temporal:
            lines.append(
                "**Secuencia medida:** " + "; ".join(temporal[:2]) + "."
            )
            lines.append("")

    if not plan:
        lines.append(
            "No hay evidencia suficiente para construir un plan de conducción "
            "priorizado en esta sesión."
        )
        lines.append("")

    # ----------------------------------------------------------
    # Patrones repetidos: lectura, no inventario completo.
    # ----------------------------------------------------------
    repeated = global_structured.get("repeated_observations", []) or []
    if repeated:
        lines.append("## Patrón que deja la sesión")
        lines.append("")
        for item in repeated[:4]:
            clauses = [
                clause.strip()
                for clause in str(item or "").split("; ")
                if clause.strip()
            ]
            if not clauses:
                continue
            lines.append(f"- {prose(clauses[0])}")
            for clause in clauses[1:]:
                lines.append(f"  - {prose(clause)}")
        lines.append("")

    # Patrones físicos repetidos que no entraron en el top 3.
    attached_signatures = set()
    for item in plan:
        for field in (
            "braking_point_patterns",
            "brake_release_patterns",
            "throttle_onset_patterns",
            "throttle_release_patterns",
        ):
            for pattern in (item.get(field, []) or []):
                if not isinstance(pattern, dict):
                    continue
                attached_signatures.add((
                    field,
                    pattern.get("region_label"),
                    pattern.get("reference_onset_m"),
                    pattern.get("reference_release_m"),
                    pattern.get("coaching_direction"),
                    pattern.get("coaching_magnitude_m"),
                ))

    secondary_point_patterns = []

    def collect_secondary(patterns, field, action_name):
        for pattern in patterns or []:
            if (
                not isinstance(pattern, dict)
                or pattern.get("status") != "REPEATED"
            ):
                continue

            signature = (
                field,
                pattern.get("region_label"),
                pattern.get("reference_onset_m"),
                pattern.get("reference_release_m"),
                pattern.get("coaching_direction"),
                pattern.get("coaching_magnitude_m"),
            )
            if signature in attached_signatures:
                continue

            magnitude = safe_int(pattern.get("coaching_magnitude_m"))
            if magnitude is None:
                continue

            direction = pattern.get("coaching_direction")
            move = "más tarde" if direction == "later" else "más temprano"
            location = track_location_label(pattern)
            prefix = location or (
                f"Zona {pattern.get('region_label')}"
                if pattern.get("region_label")
                else "Otra zona"
            )
            comparison_count = safe_int(pattern.get("comparison_count")) or 0

            secondary_point_patterns.append(
                f"{prefix}: {action_name} aproximadamente {magnitude} m "
                f"{move}; patrón repetido en {comparison_count} comparaciones"
            )

    collect_secondary(
        braking_patterns,
        "braking_point_patterns",
        "iniciar la frenada",
    )
    collect_secondary(
        brake_release_patterns,
        "brake_release_patterns",
        "soltar el freno",
    )
    collect_secondary(
        throttle_onset_patterns,
        "throttle_onset_patterns",
        "reaplicar el acelerador",
    )
    collect_secondary(
        throttle_release_patterns,
        "throttle_release_patterns",
        "soltar el acelerador",
    )

    if secondary_point_patterns:
        lines.append("## Patrón repetido fuera del foco principal")
        lines.append("")
        lines.append(
            "No lo subiría por encima de las tres prioridades actuales, "
            "pero conviene tenerlo presente:"
        )
        lines.append("")
        for item in secondary_point_patterns[:3]:
            lines.append(f"- {item}.")
        lines.append("")

    # opportunities queda disponible en global_structured; el render evita
    # repetir el plan con un segundo listado casi equivalente.

    hypotheses = global_structured.get("hypotheses", []) or []
    if hypotheses:
        lines.append("## Hipótesis prudentes")
        lines.append("")
        for item in hypotheses[:3]:
            lines.append(f"- {prose(item)}")
        lines.append("")

    limitations = global_structured.get("limitations", []) or []
    if limitations:
        lines.append("## Límites de la lectura")
        lines.append("")
        for item in limitations[:2]:
            lines.append(f"- {prose(item)}")
        lines.append("")

    # ----------------------------------------------------------
    # Apéndice técnico compacto. La información exhaustiva permanece
    # en el JSON y no hace falta repetirla toda en la narrativa.
    # ----------------------------------------------------------
    lines.append("## Respaldo técnico")
    lines.append("")

    if comparison_results:
        quality_by_key = _comparison_quality_map(
            session_coaching_facts.get("comparison_quality_gate", {}) or {}
        )
        comparison_parts = []
        for r in comparison_results:
            key = _session_comparison_key(r)
            suffix = ""
            quality = quality_by_key.get(key, {})
            if quality and not quality.get("session_plan_eligible", True):
                suffix = " [excluida del plan]"
            elif (
                quality
                and quality.get("quality_status")
                == "STATISTICAL_OUTLIER_RETAINED_FOR_COACHING"
            ):
                suffix = " [outlier estadístico retenido]"
            comparison_parts.append(
                f"{r['reference_lap']}→{r['comparison_lap']} "
                f"{signed_seconds(r['comparison_minus_reference_s'])}{suffix}"
            )
        lines.append("**Comparaciones:**")
        for comparison_part in comparison_parts:
            lines.append(f"- {comparison_part}.")

    # Los objetivos físicos repetidos ya están presentados en el plan principal
    # o, si quedaron fuera del foco, en "Patrón repetido fuera del foco principal".
    # El respaldo técnico evita volver a enumerar las mismas acciones.
    technical_zone_observations = []
    for item in plan[:3]:
        quantitative = [
            str(value)
            for value in (item.get("quantitative_observations", []) or [])
            if value
        ]
        if not quantitative:
            continue
        label = item.get("plan_label") or "?"
        technical_zone_observations.append((label, quantitative[:3]))
    if technical_zone_observations:
        lines.append("")
        lines.append("**Observaciones cuantitativas por zona:**")
        for label, values in technical_zone_observations:
            lines.append(f"- Zona {label}:")
            for value in values:
                clauses = [
                    clause.strip()
                    for clause in value.split("; ")
                    if clause.strip()
                ]
                for clause in clauses:
                    lines.append(f"  - {prose(clause)}")

    findings = session_coaching_facts.get("priority_findings", []) or []
    if findings:
        lines.append("")
        lines.append("**Episodios que más pesan en la priorización:**")
        for finding in findings[:4]:
            location = track_location_label(finding)
            loc = f" · {location}" if location else ""
            lines.append(
                f"- {finding.get('comparison')} · episodio "
                f"#{finding.get('episode_id')}{loc} · "
                f"{_render_action_delta_fact(finding.get('action_time_loss_s'))}."
            )

    excluded = []
    for result in comparison_results:
        for anomaly in (result.get("excluded_anomalies", []) or []):
            if isinstance(anomaly, dict):
                excluded.append(anomaly)
    if excluded:
        lines.append("")
        lines.append(
            f"**Incidencias excluidas:** {len(excluded)} pérdida(s) anómala(s) "
            "quedaron fuera del coaching de técnica."
        )

    lines.append("")
    lines.append(
        "_La evidencia completa, los episodios descartados, las magnitudes por "
        "canal y las asignaciones onset/release permanecen disponibles en el JSON._"
    )

    return "\n".join(lines)
