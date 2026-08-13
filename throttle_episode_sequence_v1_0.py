import math

from throttle_point_v1_2_1 import (
    THROTTLE_POINT_ASSOCIATION_TOLERANCE_M,
    detect_throttle_events,
    pair_throttle_events,
)


THROTTLE_EPISODE_SEQUENCE_VERSION = "1.0"
THROTTLE_EPISODE_SEQUENCE_SCHEMA_VERSION = "1.0"


# ============================================================
# THROTTLE EPISODE SEQUENCE v1.0 - DETERMINISTIC / OBSERVATIONAL
# ============================================================
#
# Objetivo:
# - conservar throttle_point_v1_2_1 como única fuente de eventos físicos;
# - detectar si un driver_action_episode contiene/toca uno o varios eventos
#   físicos de acelerador;
# - preservar el orden de esos eventos y el pairing monotónico ya resuelto;
# - exponer pares y eventos no emparejados dentro del episodio.
#
# NO:
# - cambia onset/release;
# - cambia el pairing;
# - crea nuevos driver_action_episodes;
# - cambia ranking/prioridad;
# - autoriza coaching;
# - interpreta tracción, wheelspin, línea, balance ni intención.
# ============================================================


def _safe_float(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def throttle_episode_sequence_config_summary():
    return {
        "enabled": True,
        "version": THROTTLE_EPISODE_SEQUENCE_VERSION,
        "schema_version": THROTTLE_EPISODE_SEQUENCE_SCHEMA_VERSION,
        "source_detector": "throttle_point_v1_2_1",
        "event_source": "confirmed_physical_throttle_events",
        "pairing_source": "monotonic_sequence_alignment_from_throttle_point",
        "association_tolerance_m":
            THROTTLE_POINT_ASSOCIATION_TOLERANCE_M,
        "observational_only": True,
        "affects_ranking": False,
        "authorizes_coaching": False,
    }


def _interval_overlap_m(a0, a1, b0, b1):
    values = (
        _safe_float(a0),
        _safe_float(a1),
        _safe_float(b0),
        _safe_float(b1),
    )
    if any(value is None for value in values):
        return 0.0

    a0, a1, b0, b1 = values
    if a1 < a0:
        a0, a1 = a1, a0
    if b1 < b0:
        b0, b1 = b1, b0

    return max(0.0, min(a1, b1) - max(a0, b0))


def _distance_to_interval(value, start_m, end_m):
    value = _safe_float(value)
    start_m = _safe_float(start_m)
    end_m = _safe_float(end_m)

    if None in (value, start_m, end_m):
        return None

    if end_m < start_m:
        start_m, end_m = end_m, start_m

    if start_m <= value <= end_m:
        return 0.0

    return min(
        abs(value - start_m),
        abs(value - end_m),
    )


def _event_association(event, episode):
    if not isinstance(event, dict) or not isinstance(episode, dict):
        return None

    episode_start = _safe_float(
        episode.get("start_distance_m")
    )
    episode_end = _safe_float(
        episode.get("end_distance_m")
    )

    event_start = _safe_float(
        event.get("onset_distance_m")
    )
    event_end = _safe_float(
        event.get("release_distance_m")
    )

    if None in (
        episode_start,
        episode_end,
        event_start,
        event_end,
    ):
        return None

    overlap_m = _interval_overlap_m(
        episode_start,
        episode_end,
        event_start,
        event_end,
    )

    onset_distance = _distance_to_interval(
        event_start,
        episode_start,
        episode_end,
    )
    release_distance = _distance_to_interval(
        event_end,
        episode_start,
        episode_end,
    )

    distances = [
        value
        for value in (
            onset_distance,
            release_distance,
        )
        if value is not None
    ]
    nearest_point_m = min(distances) if distances else None

    if overlap_m > 0.0:
        mode = "interval_overlap"
    elif (
        nearest_point_m is not None
        and nearest_point_m
        <= THROTTLE_POINT_ASSOCIATION_TOLERANCE_M
    ):
        mode = "point_tolerance"
    else:
        return None

    return {
        "mode": mode,
        "overlap_m": _safe_float(overlap_m),
        "nearest_point_distance_m":
            _safe_float(nearest_point_m),
    }


def _compact_event(event, association):
    if not isinstance(event, dict):
        return None

    return {
        "event_id":
            event.get("throttle_event_id"),
        "onset_distance_m":
            _safe_float(
                event.get("onset_distance_m")
            ),
        "confirmation_distance_m":
            _safe_float(
                event.get("confirmation_distance_m")
            ),
        "release_distance_m":
            _safe_float(
                event.get("release_distance_m")
            ),
        "release_confirmed":
            bool(
                event.get("release_confirmed")
            ),
        "peak_throttle_percent":
            _safe_float(
                event.get("peak_throttle_percent")
            ),
        "peak_distance_m":
            _safe_float(
                event.get("peak_distance_m")
            ),
        "full_throttle_attainment_confirmed":
            bool(
                event.get(
                    "full_throttle_attainment_confirmed"
                )
            ),
        "full_throttle_attainment_distance_m":
            _safe_float(
                event.get(
                    "full_throttle_attainment_distance_m"
                )
            ),
        "distance_from_onset_to_full_throttle_m":
            _safe_float(
                event.get(
                    "distance_from_onset_to_full_throttle_m"
                )
            ),
        "partial_lift_count":
            int(
                event.get("partial_lift_count", 0)
                or 0
            ),
        "association":
            dict(association)
            if isinstance(association, dict)
            else None,
    }


def _paired_differences(reference_event, comparison_event):
    ref_onset = _safe_float(
        reference_event.get("onset_distance_m")
    )
    cmp_onset = _safe_float(
        comparison_event.get("onset_distance_m")
    )

    ref_release = _safe_float(
        reference_event.get("release_distance_m")
    )
    cmp_release = _safe_float(
        comparison_event.get("release_distance_m")
    )

    ref_full = _safe_float(
        reference_event.get(
            "full_throttle_attainment_distance_m"
        )
    )
    cmp_full = _safe_float(
        comparison_event.get(
            "full_throttle_attainment_distance_m"
        )
    )

    release_comparable = (
        bool(reference_event.get("release_confirmed"))
        and bool(comparison_event.get("release_confirmed"))
        and ref_release is not None
        and cmp_release is not None
    )

    full_comparable = (
        bool(
            reference_event.get(
                "full_throttle_attainment_confirmed"
            )
        )
        and bool(
            comparison_event.get(
                "full_throttle_attainment_confirmed"
            )
        )
        and ref_full is not None
        and cmp_full is not None
    )

    return {
        "comparison_minus_reference_onset_m":
            (
                _safe_float(cmp_onset - ref_onset)
                if ref_onset is not None
                and cmp_onset is not None
                else None
            ),
        "comparison_minus_reference_release_m":
            (
                _safe_float(cmp_release - ref_release)
                if release_comparable
                else None
            ),
        "comparison_minus_reference_full_throttle_m":
            (
                _safe_float(cmp_full - ref_full)
                if full_comparable
                else None
            ),
    }


def build_throttle_event_sequence_for_episode(
    episode,
    reference_events,
    comparison_events,
    paired_events,
):
    """
    Devuelve la secuencia física de eventos de acelerador asociada a un
    driver_action_episode.

    El resultado es puramente observacional.
    """
    if not isinstance(episode, dict):
        return None

    channels = set(
        episode.get("action_channels", [])
        or []
    )

    if "throttle" not in channels:
        return None

    reference_associated = {}
    comparison_associated = {}

    for event in reference_events or []:
        association = _event_association(
            event,
            episode,
        )
        event_id = event.get("throttle_event_id")
        if association is not None and event_id:
            reference_associated[event_id] = (
                event,
                association,
            )

    for event in comparison_events or []:
        association = _event_association(
            event,
            episode,
        )
        event_id = event.get("throttle_event_id")
        if association is not None and event_id:
            comparison_associated[event_id] = (
                event,
                association,
            )

    if (
        not reference_associated
        and not comparison_associated
    ):
        return {
            "status": "UNAVAILABLE",
            "reason":
                "no_confirmed_throttle_event_associated_with_episode",
            "observational_only": True,
            "affects_ranking": False,
            "authorized_coaching": False,
            "reference_event_count": 0,
            "comparison_event_count": 0,
            "paired_event_count": 0,
            "multiple_physical_events_in_episode": False,
            "sequence_items": [],
        }

    pair_by_reference = {}
    pair_by_comparison = {}

    for pair in paired_events or []:
        if not isinstance(pair, dict):
            continue

        ref_id = pair.get("reference_event_id")
        cmp_id = pair.get("comparison_event_id")

        if ref_id:
            pair_by_reference[ref_id] = pair
        if cmp_id:
            pair_by_comparison[cmp_id] = pair

    used_reference = set()
    used_comparison = set()
    items = []

    # Only call something PAIRED_IN_EPISODE when both physical events
    # independently associate to this episode.
    for pair in paired_events or []:
        if not isinstance(pair, dict):
            continue

        ref_id = pair.get("reference_event_id")
        cmp_id = pair.get("comparison_event_id")

        if (
            ref_id not in reference_associated
            or cmp_id not in comparison_associated
        ):
            continue

        ref_event, ref_assoc = (
            reference_associated[ref_id]
        )
        cmp_event, cmp_assoc = (
            comparison_associated[cmp_id]
        )

        used_reference.add(ref_id)
        used_comparison.add(cmp_id)

        onset_values = [
            _safe_float(
                ref_event.get("onset_distance_m")
            ),
            _safe_float(
                cmp_event.get("onset_distance_m")
            ),
        ]
        onset_values = [
            value
            for value in onset_values
            if value is not None
        ]

        items.append({
            "pair_status":
                "PAIRED_IN_EPISODE",
            "throttle_pair_id":
                pair.get("throttle_pair_id"),
            "pair_cost":
                _safe_float(
                    pair.get("pair_cost")
                ),
            "reference_event":
                _compact_event(
                    ref_event,
                    ref_assoc,
                ),
            "comparison_event":
                _compact_event(
                    cmp_event,
                    cmp_assoc,
                ),
            "differences":
                _paired_differences(
                    ref_event,
                    cmp_event,
                ),
            "_sort_m":
                (
                    sum(onset_values)
                    / len(onset_values)
                    if onset_values
                    else float("inf")
                ),
        })

    # Associated reference event whose global counterpart does not also
    # associate to the episode.
    for ref_id, (
        ref_event,
        ref_assoc,
    ) in reference_associated.items():
        if ref_id in used_reference:
            continue

        pair = pair_by_reference.get(ref_id)

        items.append({
            "pair_status":
                "REFERENCE_ONLY_IN_EPISODE",
            "throttle_pair_id":
                (
                    pair.get("throttle_pair_id")
                    if pair
                    else None
                ),
            "pair_cost":
                (
                    _safe_float(
                        pair.get("pair_cost")
                    )
                    if pair
                    else None
                ),
            "reference_event":
                _compact_event(
                    ref_event,
                    ref_assoc,
                ),
            "comparison_event":
                None,
            "differences":
                None,
            "_sort_m":
                _safe_float(
                    ref_event.get("onset_distance_m")
                )
                or float("inf"),
        })

    # Associated comparison event whose global counterpart does not also
    # associate to the episode.
    for cmp_id, (
        cmp_event,
        cmp_assoc,
    ) in comparison_associated.items():
        if cmp_id in used_comparison:
            continue

        pair = pair_by_comparison.get(cmp_id)

        items.append({
            "pair_status":
                "COMPARISON_ONLY_IN_EPISODE",
            "throttle_pair_id":
                (
                    pair.get("throttle_pair_id")
                    if pair
                    else None
                ),
            "pair_cost":
                (
                    _safe_float(
                        pair.get("pair_cost")
                    )
                    if pair
                    else None
                ),
            "reference_event":
                None,
            "comparison_event":
                _compact_event(
                    cmp_event,
                    cmp_assoc,
                ),
            "differences":
                None,
            "_sort_m":
                _safe_float(
                    cmp_event.get("onset_distance_m")
                )
                or float("inf"),
        })

    items.sort(
        key=lambda item: (
            item.get("_sort_m", float("inf")),
            item.get("pair_status", ""),
            item.get("throttle_pair_id") or "",
        )
    )

    for index, item in enumerate(
        items,
        start=1,
    ):
        item["sequence_index"] = index
        item.pop("_sort_m", None)

    reference_count = len(
        reference_associated
    )
    comparison_count = len(
        comparison_associated
    )
    paired_count = sum(
        1
        for item in items
        if item.get("pair_status")
        == "PAIRED_IN_EPISODE"
    )

    return {
        "status": "VALID",
        "source_detector_version": "1.2.1",
        "source_pairing":
            "monotonic_sequence_alignment",
        "observational_only": True,
        "affects_ranking": False,
        "authorized_coaching": False,
        "association_tolerance_m":
            THROTTLE_POINT_ASSOCIATION_TOLERANCE_M,
        "reference_event_count":
            reference_count,
        "comparison_event_count":
            comparison_count,
        "paired_event_count":
            paired_count,
        "multiple_physical_events_in_episode":
            (
                reference_count >= 2
                or comparison_count >= 2
            ),
        "sequence_items":
            items,
    }


def _episode_key(episode):
    if not isinstance(episode, dict):
        return None

    return (
        episode.get("zone_id"),
        _safe_float(
            episode.get("start_distance_m")
        ),
        _safe_float(
            episode.get("end_distance_m")
        ),
    )


def enrich_objective_with_throttle_event_sequences(
    comparison,
    objective_analysis,
):
    """
    Enriquecimiento in-place, posterior a throttle_point_v1_2_1.

    No modifica ninguna decisión previa.
    """
    if not isinstance(objective_analysis, dict):
        return objective_analysis

    reference_events = detect_throttle_events(
        comparison,
        "throttle_a",
    )
    comparison_events = detect_throttle_events(
        comparison,
        "throttle_b",
    )
    paired_events = pair_throttle_events(
        reference_events,
        comparison_events,
    )

    ranking = objective_analysis.get(
        "driver_action_episode_ranking",
        [],
    )

    by_key = {}
    episodes_with_throttle = 0
    episodes_with_multiple = 0

    if isinstance(ranking, list):
        for episode in ranking:
            if not isinstance(episode, dict):
                continue

            if "throttle" not in set(
                episode.get(
                    "action_channels",
                    [],
                )
                or []
            ):
                continue

            episodes_with_throttle += 1

            result = (
                build_throttle_event_sequence_for_episode(
                    episode,
                    reference_events,
                    comparison_events,
                    paired_events,
                )
            )

            if result is None:
                continue

            episode[
                "throttle_event_sequence"
            ] = result

            if result.get(
                "multiple_physical_events_in_episode"
            ):
                episodes_with_multiple += 1

            key = _episode_key(episode)
            if key is not None:
                by_key[key] = result

    loss_ranking = objective_analysis.get(
        "loss_ranking",
        [],
    )

    if isinstance(loss_ranking, list):
        for zone in loss_ranking:
            if not isinstance(zone, dict):
                continue

            for episode in (
                zone.get(
                    "driver_action_episodes",
                    [],
                )
                or []
            ):
                key = _episode_key(episode)

                if key in by_key:
                    episode[
                        "throttle_event_sequence"
                    ] = dict(
                        by_key[key]
                    )

    objective_analysis[
        "throttle_episode_sequence_detection"
    ] = {
        "version":
            THROTTLE_EPISODE_SEQUENCE_VERSION,
        "schema_version":
            THROTTLE_EPISODE_SEQUENCE_SCHEMA_VERSION,
        "config":
            throttle_episode_sequence_config_summary(),
        "reference_event_count":
            len(reference_events),
        "comparison_event_count":
            len(comparison_events),
        "paired_event_count":
            len(paired_events),
        "throttle_episode_count":
            episodes_with_throttle,
        "episodes_with_multiple_physical_events":
            episodes_with_multiple,
        "policy":
            "observational_only_no_ranking_no_coaching",
    }

    return objective_analysis
