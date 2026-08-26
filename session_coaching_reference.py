"""Deterministic reference action profile construction."""

from deterministic_coaching import safe_float, safe_int

REFERENCE_ACTION_PROFILE_VERSION = "1.1"

REFERENCE_BRAKE_GAP_MIN_M = 8.0

REFERENCE_THROTTLE_BRIEF_APPLICATION_MAX_M = 20.0

REFERENCE_THROTTLE_GAP_MIN_M = 8.0

def _attach_reference_action_profiles(
    regions,
    source_data,
):
    """
    v3.10.8: throttle/brake sólo se convierten en acción si Python puede
    describir concretamente la secuencia física de la vuelta de referencia.

    La dirección genérica de porcentaje (más/menos) permanece observacional.
    Steering no genera target directo.
    """
    if not isinstance(regions, list):
        return regions

    for region in regions:
        if not isinstance(region, dict):
            continue

        throttle_profile = _reference_throttle_profile_for_region(region, source_data)
        brake_profile = _reference_brake_profile_for_region(region, source_data)

        for repeated in region.get("repeated_differences", []) or []:
            if not isinstance(repeated, dict):
                continue

            channel = repeated.get("channel")
            repeated["target"] = None
            repeated["actionability"] = "observation_only"
            repeated["target_source"] = "observation_only_channel_difference"

            if channel == "throttle":
                profile = throttle_profile
                target = _reference_throttle_profile_target_text(profile)
            elif channel == "brake":
                profile = brake_profile
                target = _reference_brake_profile_target_text(profile)
            else:
                profile = None
                target = None

            if channel in {"throttle", "brake"}:
                repeated["reference_action_profile"] = profile
                if target:
                    repeated["target"] = target
                    repeated["actionability"] = "actionable_reference_profile"
                    repeated["target_source"] = "reference_action_profile"
                else:
                    repeated["target_source"] = "unavailable_reference_action_profile"

        if throttle_profile is not None:
            region["reference_throttle_profile"] = throttle_profile
        if brake_profile is not None:
            region["reference_brake_profile"] = brake_profile

    return regions

def _reference_brake_event_catalog(
    source_data,
    reference_lap=None,
):
    """
    Reconstruye los eventos físicos de freno de la vuelta de referencia.

    analyze_telemetry 3.8 no expone todavía un catálogo top-level equivalente
    a throttle_physical_point_profiles. Por eso el catálogo se deduplica desde
    driver_action_episode_ranking, usando exclusivamente braking_point_comparison
    y brake_release_point_comparison ya calculados por Python.
    """
    if not isinstance(source_data, dict):
        return []

    by_event_id = {}

    for comparison in source_data.get("comparisons", []) or []:
        if not isinstance(comparison, dict):
            continue

        comparison_reference_lap = safe_int(comparison.get("reference_lap"))
        if (
            reference_lap is not None
            and comparison_reference_lap is not None
            and comparison_reference_lap != reference_lap
        ):
            continue

        objective = comparison.get("objective_analysis") or {}
        ranking = (
            objective.get("driver_action_episode_ranking", [])
            if isinstance(objective, dict)
            else []
        )

        for episode in ranking or []:
            if not isinstance(episode, dict):
                continue

            onset_cmp = episode.get("braking_point_comparison") or {}
            release_cmp = episode.get("brake_release_point_comparison") or {}
            if not isinstance(onset_cmp, dict):
                onset_cmp = {}
            if not isinstance(release_cmp, dict):
                release_cmp = {}

            event_id = str(
                onset_cmp.get("reference_event_id")
                or release_cmp.get("reference_event_id")
                or ""
            ).strip()
            if not event_id:
                continue

            onset_event = onset_cmp.get("reference_event") or {}
            release_event = release_cmp.get("reference_event") or {}
            if not isinstance(onset_event, dict):
                onset_event = {}
            if not isinstance(release_event, dict):
                release_event = {}

            item = by_event_id.setdefault(
                event_id,
                {
                    "event_id": event_id,
                    "reference_lap": comparison_reference_lap,
                },
            )

            candidates = {
                "onset_distance_m": onset_cmp.get("reference_onset_m"),
                "confirmation_distance_m": (
                    onset_event.get("confirmation_distance_m")
                    if onset_event
                    else release_event.get("confirmation_distance_m")
                ),
                "release_distance_m": (
                    release_cmp.get("reference_release_m")
                    if release_cmp.get("reference_release_m") is not None
                    else onset_event.get("release_distance_m")
                ),
                "peak_brake_percent": (
                    onset_event.get("peak_brake_percent")
                    if onset_event.get("peak_brake_percent") is not None
                    else release_event.get("peak_brake_percent")
                ),
            }

            for key, value in candidates.items():
                numeric = safe_float(value)
                if numeric is not None:
                    item[key] = numeric

    events = [
        item
        for item in by_event_id.values()
        if safe_float(item.get("onset_distance_m")) is not None
    ]

    return sorted(
        events,
        key=lambda item: (
            item.get("onset_distance_m")
            if item.get("onset_distance_m") is not None
            else 999999.0,
            item.get("event_id") or "",
        ),
    )

def _reference_brake_level_label(peak_percent):
    peak_percent = safe_float(peak_percent)
    if peak_percent is None:
        return "aplicación de freno"
    if peak_percent < 30.0:
        return "aplicación ligera de freno"
    if peak_percent < 60.0:
        return "aplicación media de freno"
    if peak_percent < 85.0:
        return "aplicación alta de freno"
    return "aplicación muy alta de freno"

def _reference_brake_profile_for_region(
    region,
    source_data,
):
    """
    Describe la secuencia física de freno de la vuelta de referencia.

    No infiere trail braking, progresividad, balance ni dinámica. Sólo resume
    onset, release, nivel pico y separaciones entre eventos ya detectados por
    Python. Los metros/porcentajes son respaldo descriptivo y no nuevos targets.
    """
    if not isinstance(region, dict):
        return None

    start = safe_float(region.get("start_distance_m"))
    end = safe_float(region.get("end_distance_m"))
    if start is None or end is None:
        return None
    if end < start:
        start, end = end, start

    reference_lap = _reference_lap_for_region(region)
    events = []
    for event in _reference_brake_event_catalog(
        source_data,
        reference_lap=reference_lap,
    ):
        onset = safe_float(event.get("onset_distance_m"))
        release = safe_float(event.get("release_distance_m"))
        if onset is None:
            continue
        effective_release = release if release is not None else onset
        if onset <= end and effective_release >= start:
            events.append(event)

    if not events:
        return None

    steps = []
    previous_release = None

    for event in events:
        onset = safe_float(event.get("onset_distance_m"))
        release = safe_float(event.get("release_distance_m"))
        peak = safe_float(event.get("peak_brake_percent"))

        if (
            previous_release is not None
            and onset is not None
            and onset > previous_release
        ):
            gap = onset - previous_release
            if gap >= REFERENCE_BRAKE_GAP_MIN_M:
                steps.append({
                    "kind": "released_gap",
                    "start_distance_m": previous_release,
                    "end_distance_m": onset,
                    "length_m": gap,
                    "shape": (
                        "liberación breve del freno"
                        if gap <= 20.0
                        else "freno liberado"
                    ),
                    "descriptive_only": True,
                })

        duration = (
            release - onset
            if onset is not None
            and release is not None
            and release >= onset
            else None
        )
        steps.append({
            "kind": "application",
            "event_id": event.get("event_id"),
            "shape": _reference_brake_level_label(peak),
            "onset_distance_m": onset,
            "confirmation_distance_m": safe_float(event.get("confirmation_distance_m")),
            "release_distance_m": release,
            "duration_m": duration,
            "peak_brake_percent": peak,
            "descriptive_only": True,
        })

        if release is not None:
            previous_release = release

    # Si el último evento termina claramente antes del final de la región y no
    # hay otra aplicación, esa ausencia de freno también forma parte de la forma.
    if previous_release is not None and end > previous_release:
        trailing_gap = end - previous_release
        if trailing_gap >= REFERENCE_BRAKE_GAP_MIN_M:
            steps.append({
                "kind": "released_gap",
                "start_distance_m": previous_release,
                "end_distance_m": end,
                "length_m": trailing_gap,
                "shape": "freno liberado hasta salir de la zona",
                "descriptive_only": True,
            })

    shape_sequence = [
        str(step.get("shape") or "").strip()
        for step in steps
        if str(step.get("shape") or "").strip()
    ]
    if not shape_sequence:
        return None

    detailed_sequence = []
    for step in steps:
        shape = str(step.get("shape") or "").strip()
        if not shape:
            continue

        if step.get("kind") == "released_gap":
            gap_start = safe_float(step.get("start_distance_m"))
            gap_end = safe_float(step.get("end_distance_m"))
            if gap_start is not None and gap_end is not None:
                detailed_sequence.append(
                    f"{shape} (~{gap_start:.0f}–{gap_end:.0f} m)"
                )
            else:
                detailed_sequence.append(shape)
            continue

        onset = safe_float(step.get("onset_distance_m"))
        release = safe_float(step.get("release_distance_m"))
        peak = safe_float(step.get("peak_brake_percent"))
        detail = shape
        if onset is not None:
            if release is not None:
                detail += f" (~{onset:.0f}–{release:.0f} m"
                if peak is not None:
                    detail += f"; pico ~{peak:.0f}%"
                detail += ")"
            else:
                detail += f" desde ~{onset:.0f} m"
        detailed_sequence.append(detail)

    return {
        "version": REFERENCE_ACTION_PROFILE_VERSION,
        "channel": "brake",
        "reference_lap": reference_lap,
        "region_start_m": start,
        "region_end_m": end,
        "event_count": len(events),
        "steps": steps,
        "shape_sequence": shape_sequence,
        "shape_summary": " → ".join(shape_sequence),
        "shape_summary_detailed": " → ".join(detailed_sequence),
        "source": "driver_action_episode_ranking.braking_point_comparison+brake_release_point_comparison",
        "descriptive_only": True,
        "numeric_coaching_authorized": False,
    }

def _reference_brake_profile_target_text(profile):
    if not isinstance(profile, dict):
        return None
    summary = str(profile.get("shape_summary") or "").strip()
    if not summary:
        return None
    return "replicar la secuencia de freno de la referencia: " + summary

def _reference_lap_for_region(region):
    if not isinstance(region, dict):
        return None

    findings = [
        item
        for item in (region.get("findings", []) or [])
        if isinstance(item, dict)
    ]
    reference_laps = sorted({
        safe_int(item.get("reference_lap"))
        for item in findings
        if safe_int(item.get("reference_lap")) is not None
    })
    return reference_laps[0] if len(reference_laps) == 1 else None

def _reference_throttle_event_catalog(
    source_data,
    reference_lap=None,
):
    """
    Extrae eventos físicos de acelerador de la vuelta de referencia.

    La fuente es throttle_physical_point_profiles producida por Python.
    No consulta al LLM y no convierte full-throttle attainment en coaching
    numérico: ese dato conserva su política observacional.
    """
    if not isinstance(source_data, dict):
        return []

    container = source_data.get("throttle_physical_point_profiles") or {}
    profiles = container.get("profiles", []) if isinstance(container, dict) else []
    by_event_id = {}

    for profile in profiles or []:
        if not isinstance(profile, dict):
            continue

        profile_reference_lap = safe_int(profile.get("reference_lap"))
        if (
            reference_lap is not None
            and profile_reference_lap is not None
            and profile_reference_lap != reference_lap
        ):
            continue

        event = profile.get("reference_event") or {}
        if not isinstance(event, dict):
            continue

        event_id = str(
            event.get("event_id")
            or profile.get("reference_event_id")
            or ""
        ).strip()
        onset = safe_float(event.get("onset_distance_m"))
        if not event_id or onset is None:
            continue

        by_event_id[event_id] = {
            "event_id": event_id,
            "reference_lap": profile_reference_lap,
            "onset_distance_m": onset,
            "confirmation_distance_m": safe_float(event.get("confirmation_distance_m")),
            "release_distance_m": safe_float(event.get("release_distance_m")),
            "release_confirmed": bool(event.get("release_confirmed")),
            "peak_throttle_percent": safe_float(event.get("peak_throttle_percent")),
            "peak_distance_m": safe_float(event.get("peak_distance_m")),
            "full_throttle_attainment_confirmed": bool(
                event.get("full_throttle_attainment_confirmed")
            ),
            "full_throttle_attainment_distance_m": safe_float(
                event.get("full_throttle_attainment_distance_m")
            ),
            "distance_from_onset_to_full_throttle_m": safe_float(
                event.get("distance_from_onset_to_full_throttle_m")
            ),
            "partial_lift_count": safe_int(event.get("partial_lift_count")) or 0,
        }

    return sorted(
        by_event_id.values(),
        key=lambda item: (
            item.get("onset_distance_m")
            if item.get("onset_distance_m") is not None
            else 999999.0,
            item.get("event_id") or "",
        ),
    )

def _reference_throttle_level_label(peak_percent):
    peak_percent = safe_float(peak_percent)
    if peak_percent is None:
        return "aplicación"
    if peak_percent < 60.0:
        return "aplicación parcial"
    if peak_percent < 85.0:
        return "aplicación media"
    return "aplicación alta"

def _reference_throttle_profile_for_region(
    region,
    source_data,
):
    """
    Describe la forma observada del acelerador de la vuelta de referencia.

    Sólo usa eventos cuyo onset cae dentro de la región. Los metros y
    porcentajes quedan en steps como respaldo descriptivo; el target textual
    usa categorías de forma, no nuevos objetivos numéricos no calibrados.
    """
    if not isinstance(region, dict):
        return None

    start = safe_float(region.get("start_distance_m"))
    end = safe_float(region.get("end_distance_m"))
    if start is None or end is None:
        return None
    if end < start:
        start, end = end, start

    reference_lap = _reference_lap_for_region(region)

    events = [
        event
        for event in _reference_throttle_event_catalog(
            source_data,
            reference_lap=reference_lap,
        )
        if (
            event.get("onset_distance_m") is not None
            and start <= event["onset_distance_m"] <= end
        )
    ]
    if not events:
        return None

    steps = []
    previous_release = None

    for event in events:
        onset = safe_float(event.get("onset_distance_m"))
        release = safe_float(event.get("release_distance_m"))
        peak = safe_float(event.get("peak_throttle_percent"))

        if (
            previous_release is not None
            and onset is not None
            and onset > previous_release
        ):
            gap = onset - previous_release
            if gap >= REFERENCE_THROTTLE_GAP_MIN_M:
                steps.append({
                    "kind": "released_gap",
                    "start_distance_m": previous_release,
                    "end_distance_m": onset,
                    "length_m": gap,
                    "shape": (
                        "liberación breve"
                        if gap <= 20.0
                        else "acelerador liberado"
                    ),
                    "descriptive_only": True,
                })

        duration = (
            release - onset
            if onset is not None
            and release is not None
            and release >= onset
            else None
        )

        level = _reference_throttle_level_label(peak)
        if event.get("full_throttle_attainment_confirmed"):
            shape = (
                "reaplicación sostenida sin volver a soltar dentro de la zona"
                if release is not None and release > end
                else "reaplicación sostenida"
            )
        elif duration is not None and duration <= REFERENCE_THROTTLE_BRIEF_APPLICATION_MAX_M:
            shape = f"{level} breve"
        else:
            shape = level

        steps.append({
            "kind": "application",
            "event_id": event.get("event_id"),
            "shape": shape,
            "onset_distance_m": onset,
            "release_distance_m": release,
            "duration_m": duration,
            "peak_throttle_percent": peak,
            "peak_distance_m": safe_float(event.get("peak_distance_m")),
            "full_throttle_attainment_confirmed": bool(
                event.get("full_throttle_attainment_confirmed")
            ),
            "full_throttle_attainment_distance_m": safe_float(
                event.get("full_throttle_attainment_distance_m")
            ),
            "distance_from_onset_to_full_throttle_m": safe_float(
                event.get("distance_from_onset_to_full_throttle_m")
            ),
            "descriptive_only": True,
        })

        if release is not None:
            previous_release = release

    shape_sequence = [
        str(step.get("shape") or "").strip()
        for step in steps
        if str(step.get("shape") or "").strip()
    ]
    if not shape_sequence:
        return None

    detailed_sequence = []
    for step in steps:
        shape = str(step.get("shape") or "").strip()
        if not shape:
            continue

        if step.get("kind") == "released_gap":
            gap_start = safe_float(step.get("start_distance_m"))
            gap_end = safe_float(step.get("end_distance_m"))
            if gap_start is not None and gap_end is not None:
                detailed_sequence.append(
                    f"{shape} (~{gap_start:.0f}–{gap_end:.0f} m)"
                )
            else:
                detailed_sequence.append(shape)
            continue

        onset = safe_float(step.get("onset_distance_m"))
        release = safe_float(step.get("release_distance_m"))
        peak = safe_float(step.get("peak_throttle_percent"))

        detail = shape
        if onset is not None:
            if release is not None and release <= end:
                detail += f" (~{onset:.0f}–{release:.0f} m"
                if peak is not None and not step.get("full_throttle_attainment_confirmed"):
                    detail += f"; pico ~{peak:.0f}%"
                detail += ")"
            else:
                detail += f" desde ~{onset:.0f} m"

        detailed_sequence.append(detail)

    return {
        "version": REFERENCE_ACTION_PROFILE_VERSION,
        "channel": "throttle",
        "reference_lap": reference_lap,
        "region_start_m": start,
        "region_end_m": end,
        "event_count": len(events),
        "steps": steps,
        "shape_sequence": shape_sequence,
        "shape_summary": " → ".join(shape_sequence),
        "shape_summary_detailed": " → ".join(detailed_sequence),
        "source": "throttle_physical_point_profiles.reference_event",
        "descriptive_only": True,
        "numeric_coaching_authorized": False,
    }

def _reference_throttle_profile_target_text(profile):
    if not isinstance(profile, dict):
        return None
    summary = str(profile.get("shape_summary") or "").strip()
    if not summary:
        return None
    return "replicar la secuencia de acelerador de la referencia: " + summary
