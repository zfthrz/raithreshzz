"""Deterministic next-stint coaching plan construction."""

from deterministic_coaching import (
    BRAKE_RELEASE_SESSION_MIN_DELTA_M,
    BRAKING_POINT_SESSION_MIN_DELTA_M,
    THROTTLE_ONSET_SESSION_MIN_DELTA_M,
    THROTTLE_RELEASE_SESSION_MIN_DELTA_M,
    _coaching_target_for_channel_direction,
    _steering_direct_action_present,
    safe_float,
    safe_int,
)
from session_coaching_priority import _alpha_label

def _brake_release_target_text(pattern):
    if not isinstance(pattern, dict) or pattern.get("status") != "REPEATED":
        return None
    magnitude = safe_int(pattern.get("coaching_magnitude_m"))
    direction = pattern.get("coaching_direction")
    if magnitude is None or magnitude < BRAKE_RELEASE_SESSION_MIN_DELTA_M:
        return None
    if direction == "later":
        return (
            f"soltar el freno aproximadamente {magnitude} m más tarde "
            "hacia el punto de la referencia"
        )
    if direction == "earlier":
        return (
            f"soltar el freno aproximadamente {magnitude} m más temprano "
            "hacia el punto de la referencia"
        )
    return None

def _braking_point_target_text(pattern):
    if not isinstance(pattern, dict) or pattern.get("status") != "REPEATED":
        return None
    magnitude = safe_int(pattern.get("coaching_magnitude_m"))
    direction = pattern.get("coaching_direction")
    if magnitude is None or magnitude < BRAKING_POINT_SESSION_MIN_DELTA_M:
        return None
    if direction == "later":
        return f"frenar aproximadamente {magnitude} m más tarde hacia el punto de la referencia"
    if direction == "earlier":
        return f"frenar aproximadamente {magnitude} m más temprano hacia el punto de la referencia"
    return None

def _build_next_stint_plan(
    priority_regions,
    priority_findings,
    max_items=3,
):
    plan = []
    consumed_findings = set()

    repeated_regions = [
        region
        for region in priority_regions
        if (
            region.get(
                "comparison_count",
                0,
            )
            >= 2
            and
            _region_has_actionable_coaching(region)
        )
    ]

    for region in repeated_regions:
        if len(plan) >= max_items:
            break

        label = _alpha_label(
            len(plan)
        )

        plan.append({
            "plan_label":
                label,
            "kind":
                "repeated_region",
            "start_distance_m":
                region.get(
                    "start_distance_m"
                ),
            "end_distance_m":
                region.get(
                    "end_distance_m"
                ),
            "comparisons":
                region.get(
                    "comparisons",
                    [],
                ),
            "comparison_count":
                region.get(
                    "comparison_count",
                    0,
                ),
            "observed_differences":
                [
                    item.get(
                        "description"
                    )
                    for item in (
                        region.get(
                            "repeated_differences",
                            [],
                        )
                        or []
                    )
                    if item.get(
                        "description"
                    )
                ],
            "targets":
                [
                    item.get("target")
                    for item in (region.get("repeated_differences", []) or [])
                    if item.get("target")
                ],
            "observation_only_differences":
                [
                    item.get("description")
                    for item in (region.get("repeated_differences", []) or [])
                    if item.get("description") and not item.get("target")
                ],
            "reference_action_profiles":
                [
                    item.get("reference_action_profile")
                    for item in (region.get("repeated_differences", []) or [])
                    if isinstance(item.get("reference_action_profile"), dict)
                ],
            "quantitative_observations":
                [
                    text
                    for text in (
                        _format_aggregate_quantitative_observation(
                            item
                        )
                        for item in (
                            region.get(
                                "repeated_differences",
                                [],
                            )
                            or []
                        )
                    )
                    if text
                ],
            "temporal_relationships":
                [
                    text
                    for text in [
                        _format_region_brake_throttle_relation(
                            region.get(
                                "brake_throttle_relation"
                            )
                        )
                    ]
                    if text
                ],
            "temporal_target":
                None,
            "braking_point_patterns":
                region.get(
                    "braking_point_patterns",
                    [],
                ),
            "braking_point_target":
                (
                    _braking_point_target_text(
                        (region.get("braking_point_patterns", []) or [None])[0]
                    )
                    if region.get("braking_point_patterns")
                    else None
                ),
            "brake_release_patterns":
                region.get(
                    "brake_release_patterns",
                    [],
                ),
            "brake_release_target":
                (
                    _brake_release_target_text(
                        (region.get("brake_release_patterns", []) or [None])[0]
                    )
                    if region.get("brake_release_patterns")
                    else None
                ),
            "throttle_onset_patterns":
                region.get(
                    "throttle_onset_patterns",
                    [],
                ),
            "throttle_onset_target":
                (
                    _throttle_onset_target_text(
                        (region.get("throttle_onset_patterns", []) or [None])[0]
                    )
                    if region.get("throttle_onset_patterns")
                    else None
                ),
            "throttle_release_patterns":
                region.get(
                    "throttle_release_patterns",
                    [],
                ),
            "throttle_release_target":
                (
                    _throttle_release_target_text(
                        (region.get("throttle_release_patterns", []) or [None])[0]
                    )
                    if region.get("throttle_release_patterns")
                    else None
                ),
            "speed_directions":
                region.get(
                    "speed_directions",
                    [],
                ),
            "propagation_statuses":
                region.get(
                    "propagation_statuses",
                    [],
                ),
        })

        for finding in (
            region.get(
                "findings",
                [],
            )
            or []
        ):
            consumed_findings.add(
                (
                    finding.get(
                        "comparison"
                    ),
                    finding.get(
                        "episode_id"
                    ),
                )
            )

    for finding in priority_findings:
        if len(plan) >= max_items:
            break

        key = (
            finding.get(
                "comparison"
            ),
            finding.get(
                "episode_id"
            ),
        )

        if key in consumed_findings:
            continue

        candidate = _single_finding_plan_item(
            finding,
            _alpha_label(len(plan)),
        )
        if _plan_item_has_actionable_coaching(candidate):
            plan.append(candidate)

    return plan

def _format_aggregate_quantitative_observation(
    repeated_difference,
):
    if not isinstance(repeated_difference, dict):
        return None

    description = repeated_difference.get("description") or repeated_difference.get("channel")
    quantitative = repeated_difference.get("quantitative") or {}
    unit = quantitative.get("unit")

    mean_min = safe_float(
        quantitative.get("mean_difference_min")
    )
    mean_max = safe_float(
        quantitative.get("mean_difference_max")
    )
    peak = quantitative.get("peak_difference_max_abs")

    pieces = []

    direction = repeated_difference.get("direction")

    # presentation-only: a steering_magnitude fact describes a magnitude
    # difference, not the sign of the raw steering sample that happened to
    # contain the largest absolute peak. Keep the displayed sign consistent
    # with the already-authoritative repeated direction.
    if unit == "steering_input_units":
        peak_value = safe_float(peak)
        if peak_value is not None:
            if direction == "higher_in_comparison_lap":
                peak = abs(peak_value)
            elif direction == "lower_in_comparison_lap":
                peak = -abs(peak_value)

    if direction == "mixed_across_comparisons":
        event_min = _format_signed_metric(
            quantitative.get("event_mean_min"),
            unit,
        )
        event_max = _format_signed_metric(
            quantitative.get("event_mean_max"),
            unit,
        )
        if event_min and event_max:
            pieces.append(
                f"medias por evento entre {event_min} y {event_max}"
            )
    elif mean_min is not None and mean_max is not None:
        low = _format_signed_metric(mean_min, unit)
        high = _format_signed_metric(mean_max, unit)

        if low == high:
            pieces.append(f"promedio {low}")
        else:
            pieces.append(f"promedio entre {low} y {high}")
    else:
        event_min = _format_signed_metric(
            quantitative.get("event_mean_min"),
            unit,
        )
        event_max = _format_signed_metric(
            quantitative.get("event_mean_max"),
            unit,
        )
        if event_min and event_max:
            pieces.append(
                f"medias por evento entre {event_min} y {event_max}"
            )

    peak_text = _format_signed_metric(peak, unit)
    if peak_text:
        pieces.append(f"pico de mayor magnitud {peak_text}")

    if not pieces:
        return None

    return f"{description}: " + "; ".join(pieces)

def _format_region_brake_throttle_relation(
    relation,
):
    if not isinstance(
        relation,
        dict,
    ):
        return None

    kind = relation.get(
        "kind"
    )
    count = safe_int(
        relation.get(
            "comparison_count"
        )
    ) or 0

    # Una relación temporal regional sólo es un patrón repetido si está
    # respaldada por al menos dos comparaciones distintas. Una observación
    # aislada puede existir en el detalle del episodio, pero no debe escalar
    # al plan repetido de la sesión.
    if count < 2:
        return None

    gap_min = safe_float(
        relation.get(
            "gap_min_m"
        )
    )
    gap_max = safe_float(
        relation.get(
            "gap_max_m"
        )
    )
    overlap_min = safe_float(
        relation.get(
            "overlap_min_m"
        )
    )
    overlap_max = safe_float(
        relation.get(
            "overlap_max_m"
        )
    )

    if kind == "brake_then_throttle":
        suffix = ""
        if (
            gap_min is not None
            and
            gap_max is not None
        ):
            if abs(
                gap_max
                - gap_min
            ) < 0.5:
                suffix = (
                    f"; separación aproximada {gap_min:.0f} m"
                )
            else:
                suffix = (
                    "; separación entre eventos de "
                    f"{gap_min:.0f} a {gap_max:.0f} m"
                )

        return (
            "se repitió la secuencia freno → acelerador "
            f"sin solapamiento en {count} comparaciones"
            + suffix
        )

    if kind == "throttle_then_brake":
        suffix = ""
        if (
            gap_min is not None
            and
            gap_max is not None
        ):
            if abs(
                gap_max
                - gap_min
            ) < 0.5:
                suffix = (
                    f"; separación aproximada {gap_min:.0f} m"
                )
            else:
                suffix = (
                    "; separación entre eventos de "
                    f"{gap_min:.0f} a {gap_max:.0f} m"
                )

        return (
            "se repitió la secuencia acelerador → freno "
            f"sin solapamiento en {count} comparaciones"
            + suffix
        )

    if kind in (
        "overlap",
        "partial_overlap",
        "substantial_overlap",
    ):
        suffix = ""
        if (
            overlap_min is not None
            and
            overlap_max is not None
        ):
            if abs(
                overlap_max
                - overlap_min
            ) < 0.5:
                suffix = (
                    f"; solapamiento aproximado {overlap_min:.0f} m"
                )
            else:
                suffix = (
                    "; solapamiento observado entre "
                    f"{overlap_min:.0f} y {overlap_max:.0f} m"
                )

        return (
            "se repitió solapamiento de freno y acelerador "
            f"en {count} comparaciones"
            + suffix
        )

    if kind == "interleaved_without_overlap":
        return (
            "se repitió una secuencia alternada de freno y acelerador "
            f"sin solapamiento directo en {count} comparaciones"
        )

    if kind == "mixed_across_comparisons":
        return (
            "la relación entre freno y acelerador cambió entre comparaciones; "
            "no se trata como un patrón temporal repetido"
        )

    return None

def _format_signed_metric(
    value,
    unit,
):
    value = safe_float(value)

    if value is None:
        return None

    if unit == "percentage_points":
        return f"{value:+.1f} pp"

    if unit == "steering_input_units":
        return f"{value:+.1f} unidades de input de volante"

    if unit:
        return f"{value:+.1f} {unit}"

    return f"{value:+.1f}"

def _format_single_brake_throttle_relation(
    relation,
):
    if not isinstance(
        relation,
        dict,
    ):
        return None

    kind = relation.get(
        "kind"
    )
    overlap = safe_float(
        relation.get(
            "overlap_m"
        )
    )
    gap = safe_float(
        relation.get(
            "gap_m"
        )
    )

    if kind == "brake_then_throttle":
        if gap is not None:
            return (
                "freno primero y acelerador después, "
                f"sin solapamiento; separación aproximada {gap:.0f} m"
            )
        return (
            "freno primero y acelerador después, "
            "sin solapamiento"
        )

    if kind == "throttle_then_brake":
        if gap is not None:
            return (
                "acelerador primero y freno después, "
                f"sin solapamiento; separación aproximada {gap:.0f} m"
            )
        return (
            "acelerador primero y freno después, "
            "sin solapamiento"
        )

    if kind in (
        "overlap",
        "partial_overlap",
        "substantial_overlap",
    ):
        if overlap is not None:
            return (
                "los eventos de freno y acelerador se solaparon "
                f"durante aproximadamente {overlap:.0f} m de recorrido"
            )
        return (
            "los eventos de freno y acelerador presentaron solapamiento"
        )

    if kind == "interleaved_without_overlap":
        return (
            "los eventos de freno y acelerador se alternaron "
            "dentro de la zona sin solapamiento directo"
        )

    return None

def _format_single_channel_quantitative_observation(
    channel_fact,
):
    if not isinstance(channel_fact, dict):
        return None

    description = channel_fact.get("description") or channel_fact.get("channel")
    quantitative = channel_fact.get("quantitative") or {}
    unit = quantitative.get("unit")
    direction = channel_fact.get("direction")

    if direction == "mixed":
        low = _format_signed_metric(
            quantitative.get("event_mean_min"),
            unit,
        )
        high = _format_signed_metric(
            quantitative.get("event_mean_max"),
            unit,
        )
        peak = _format_signed_metric(
            quantitative.get("peak_difference"),
            unit,
        )

        pieces = []
        if low and high:
            pieces.append(f"medias por evento entre {low} y {high}")
        if peak:
            pieces.append(f"pico de mayor magnitud {peak}")

        if pieces:
            return f"{description}: " + "; ".join(pieces)

        return None

    mean = _format_signed_metric(
        quantitative.get("mean_difference"),
        unit,
    )
    peak = _format_signed_metric(
        quantitative.get("peak_difference"),
        unit,
    )

    pieces = []
    if mean:
        pieces.append(f"promedio {mean}")
    if peak:
        pieces.append(f"pico {peak}")

    if not pieces:
        return None

    return f"{description}: " + "; ".join(pieces)

def _plan_item_has_actionable_coaching(item):
    if not isinstance(item, dict):
        return False
    if any(str(value or "").strip() for value in (item.get("targets", []) or [])):
        return True
    # v3.10.8.5.4: un hallazgo PRIORITARIO puede llegar al plan sólo por
    # steering si el LLM validado lo eligió explícitamente como coaching.
    # Queda en el tier de menor especificidad y nunca desplaza un punto físico
    # repetido/individual ni un reference_action_profile concreto.
    if item.get("steering_coaching_requested"):
        direction = item.get("steering_direction")
        recommendation = str(item.get("validated_recommendation") or "").strip()
        if recommendation and _steering_direct_action_present(recommendation):
            if direction in {
                "higher_in_comparison_lap",
                "lower_in_comparison_lap",
                "mixed",
                None,
            }:
                return True
    for field in (
        "braking_point_patterns",
        "brake_release_patterns",
        "throttle_onset_patterns",
        "throttle_release_patterns",
    ):
        for pattern in (item.get(field, []) or []):
            if not isinstance(pattern, dict):
                continue
            magnitude = safe_int(pattern.get("coaching_magnitude_m"))
            direction = pattern.get("coaching_direction")
            authorized = pattern.get("authorized_numeric_coaching")
            if magnitude is not None and direction in {"later", "earlier"} and authorized is not False:
                return True
    return False

def _region_has_actionable_coaching(region):
    if not isinstance(region, dict):
        return False

    if any(
        isinstance(item, dict) and str(item.get("target") or "").strip()
        for item in (region.get("repeated_differences", []) or [])
    ):
        return True

    point_specs = (
        ("braking_point_patterns", _braking_point_target_text),
        ("brake_release_patterns", _brake_release_target_text),
        ("throttle_onset_patterns", _throttle_onset_target_text),
        ("throttle_release_patterns", _throttle_release_target_text),
    )
    for field, builder in point_specs:
        for pattern in (region.get(field, []) or []):
            if isinstance(pattern, dict) and builder(pattern):
                return True

    return False

def _single_fact_as_plan_pattern(fact, comparison=None):
    if not isinstance(fact, dict):
        return None
    if not fact.get("authorized_numeric_coaching"):
        return None
    magnitude = safe_int(fact.get("coaching_magnitude_m"))
    direction = fact.get("coaching_direction")
    if magnitude is None or direction not in {"later", "earlier"}:
        return None
    value = dict(fact)
    value["status"] = "SINGLE"
    value["comparison_count"] = 1

    # H5.4/P2 — preserve explicit single-comparison provenance so the same
    # deterministic precision helper used by repeated patterns can describe
    # reference/supporting laps and the observed magnitude without inference.
    comparison_text = str(comparison or "").strip()
    signed_delta = safe_float(value.get("comparison_minus_reference_m"))
    if comparison_text:
        value["comparisons"] = [comparison_text]
    if signed_delta is not None:
        value["deltas_m"] = [signed_delta]
        value["median_delta_m"] = signed_delta

    return value

def build_plan_priority_reason(item):
    """Return deterministic provenance for why a plan item is present."""
    if not isinstance(item, dict):
        return {}

    kind = str(item.get("kind") or "unknown")

    comparison_count = item.get("comparison_count")
    if not isinstance(comparison_count, int):
        comparisons = item.get("comparisons")
        comparison_count = len(comparisons) if isinstance(comparisons, list) else 0

    physical_anchor_types = []

    for label, field in (
        ("braking_point", "braking_point_patterns"),
        ("brake_release", "brake_release_patterns"),
        ("throttle_onset", "throttle_onset_patterns"),
        ("throttle_release", "throttle_release_patterns"),
    ):
        patterns = item.get(field)
        if isinstance(patterns, list) and patterns:
            physical_anchor_types.append(label)

    actionable_cue_count = item.get("actionable_cue_count")
    if not isinstance(actionable_cue_count, int):
        cues = item.get("driver_cues")
        actionable_cue_count = len(cues) if isinstance(cues, list) else 0

    return {
        "kind": kind,
        "comparison_count": max(comparison_count, 0),
        "repeated": kind == "repeated_region",
        "has_physical_anchor": bool(physical_anchor_types),
        "physical_anchor_types": physical_anchor_types,
        "actionable_cue_count": max(actionable_cue_count, 0),
    }


def _single_finding_plan_item(
    finding,
    label,
):
    comparison = finding.get("comparison")
    braking = _single_fact_as_plan_pattern(finding.get("braking_point"), comparison)
    brake_release = _single_fact_as_plan_pattern(finding.get("brake_release"), comparison)
    throttle_onset = _single_fact_as_plan_pattern(finding.get("throttle_onset"), comparison)
    throttle_release = _single_fact_as_plan_pattern(finding.get("throttle_release"), comparison)

    channel_rows = [
        item
        for item in (finding.get("channels", []) or [])
        if isinstance(item, dict)
    ]

    qualitative_targets = []
    observation_only = []

    for item in channel_rows:
        description = item.get("description")
        target = _coaching_target_for_channel_direction(
            item.get("channel"),
            item.get("direction"),
        )
        if target:
            qualitative_targets.append(target)
        elif description:
            observation_only.append(description)

    return {
        "plan_label": label,
        "kind": "single_priority_finding",
        "start_distance_m": finding.get("start_distance_m"),
        "end_distance_m": finding.get("end_distance_m"),
        "comparisons": [finding.get("comparison")],
        "comparison_count": 1,
        "observed_differences": [
            item.get("description")
            for item in channel_rows
            if item.get("description")
        ],
        "observation_only_differences": observation_only,
        "targets": qualitative_targets,
        "reference_action_profiles": [],
        "quantitative_observations": [
            text
            for text in (
                _format_single_channel_quantitative_observation(item)
                for item in channel_rows
            )
            if text
        ],
        "temporal_relationships": [
            text
            for text in [
                _format_single_brake_throttle_relation(
                    finding.get("brake_throttle_relation")
                )
            ]
            if text
        ],
        "temporal_target": None,
        "braking_point_patterns": [braking] if braking else [],
        "braking_point_target": None,
        "brake_release_patterns": [brake_release] if brake_release else [],
        "brake_release_target": None,
        "throttle_onset_patterns": [throttle_onset] if throttle_onset else [],
        "throttle_onset_target": None,
        "throttle_release_patterns": [throttle_release] if throttle_release else [],
        "throttle_release_target": None,
        "speed_directions": finding.get("speed_directions", []),
        "propagation_statuses": finding.get("propagation_statuses", []),
        "comparison_priority_rank": finding.get("comparison_priority_rank"),
        "episode_priority_rank": finding.get("relative_priority_rank"),
        "action_time_loss_s": finding.get("action_time_loss_s"),
        "steering_coaching_requested": bool(
            finding.get("steering_coaching_requested")
        ),
        "validated_recommendation": finding.get("validated_recommendation"),
        "steering_direction": next(
            (
                item.get("direction")
                for item in channel_rows
                if item.get("channel") == "steering_magnitude"
            ),
            None,
        ),
        "source_priority": {
            "comparison_priority_rank": finding.get("comparison_priority_rank"),
            "episode_priority_rank": finding.get("relative_priority_rank"),
        },
    }

def _throttle_onset_target_text(pattern):
    if not isinstance(pattern, dict) or pattern.get("status") != "REPEATED":
        return None
    magnitude = safe_int(pattern.get("coaching_magnitude_m"))
    direction = pattern.get("coaching_direction")
    if magnitude is None or magnitude < THROTTLE_ONSET_SESSION_MIN_DELTA_M:
        return None
    if direction == "later":
        return f"reaplicar el acelerador aproximadamente {magnitude} m más tarde hacia el punto de la referencia"
    if direction == "earlier":
        return f"reaplicar el acelerador aproximadamente {magnitude} m más temprano hacia el punto de la referencia"
    return None

def _throttle_release_target_text(pattern):
    if not isinstance(pattern, dict) or pattern.get("status") != "REPEATED":
        return None
    magnitude = safe_int(pattern.get("coaching_magnitude_m"))
    direction = pattern.get("coaching_direction")
    if magnitude is None or magnitude < THROTTLE_RELEASE_SESSION_MIN_DELTA_M:
        return None
    if direction == "later":
        return f"soltar el acelerador aproximadamente {magnitude} m más tarde hacia el punto de la referencia"
    if direction == "earlier":
        return f"soltar el acelerador aproximadamente {magnitude} m más temprano hacia el punto de la referencia"
    return None
