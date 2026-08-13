import math

import numpy as np
import pandas as pd

from throttle_point_v1_2_1 import (
    PARTIAL_LIFT_MAX_EVENT_DISTANCE_M,
    PARTIAL_LIFT_MIN_THROTTLE_PERCENT,
    THROTTLE_POINT_ASSOCIATION_TOLERANCE_M,
    THROTTLE_RELEASE_THRESHOLD_PERCENT,
    detect_throttle_events,
    pair_throttle_events,
)


THROTTLE_SUSTAINED_MODULATION_VERSION = "1.0"
THROTTLE_SUSTAINED_MODULATION_SCHEMA_VERSION = "1.0"

SUSTAINED_MODULATION_MIN_PRE_LEVEL_PERCENT = 60.0
SUSTAINED_MODULATION_MIN_DROP_PP = 20.0
SUSTAINED_MODULATION_MIN_DISTANCE_M = 30.0
SUSTAINED_MODULATION_RECOVERY_TOLERANCE_PP = 8.0
SUSTAINED_MODULATION_MAX_DISTANCE_M = 250.0

# A modulation is admitted only if it is outside the partial-lift envelope:
# - deeper than the partial-lift floor, OR
# - longer than the partial-lift max duration.
SUSTAINED_MODULATION_DEEP_FLOOR_PERCENT = (
    PARTIAL_LIFT_MIN_THROTTLE_PERCENT
)
SUSTAINED_MODULATION_LONG_DISTANCE_M = (
    PARTIAL_LIFT_MAX_EVENT_DISTANCE_M
)


# ============================================================
# THROTTLE SUSTAINED MODULATION v1.0
# DETERMINISTIC / OBSERVATIONAL
# ============================================================
#
# Detects a recovered down-up throttle excursion inside one already-confirmed
# physical throttle event when that excursion is too deep and/or too long to
# be labelled a partial_lift by throttle_point_v1_2_1.
#
# It does NOT:
# - redefine throttle onset/release;
# - alter physical event pairing;
# - create driver_action_episodes;
# - alter ranking/session priority;
# - authorize coaching;
# - infer lift-and-coast, traction, wheelspin, balance, line or intent.
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


def sustained_modulation_config_summary():
    return {
        "enabled": True,
        "version": THROTTLE_SUSTAINED_MODULATION_VERSION,
        "schema_version": THROTTLE_SUSTAINED_MODULATION_SCHEMA_VERSION,
        "source_detector": "throttle_point_v1_2_1",
        "min_pre_level_percent":
            SUSTAINED_MODULATION_MIN_PRE_LEVEL_PERCENT,
        "min_drop_pp":
            SUSTAINED_MODULATION_MIN_DROP_PP,
        "min_distance_m":
            SUSTAINED_MODULATION_MIN_DISTANCE_M,
        "recovery_tolerance_pp":
            SUSTAINED_MODULATION_RECOVERY_TOLERANCE_PP,
        "max_distance_m":
            SUSTAINED_MODULATION_MAX_DISTANCE_M,
        "deep_floor_percent":
            SUSTAINED_MODULATION_DEEP_FLOOR_PERCENT,
        "long_distance_m":
            SUSTAINED_MODULATION_LONG_DISTANCE_M,
        "release_floor_percent":
            THROTTLE_RELEASE_THRESHOLD_PERCENT,
        "classification_rule":
            "recovered_excursion_and_(deeper_than_partial_lift_or_longer_than_partial_lift)",
        "observational_only": True,
        "affects_ranking": False,
        "authorizes_coaching": False,
    }


def _extract_signal(comparison, throttle_column):
    if not isinstance(comparison, pd.DataFrame):
        return None, None

    if (
        "distance" not in comparison.columns
        or throttle_column not in comparison.columns
    ):
        return None, None

    distance = pd.to_numeric(
        comparison["distance"],
        errors="coerce",
    ).to_numpy(dtype=float)

    throttle = pd.to_numeric(
        comparison[throttle_column],
        errors="coerce",
    ).to_numpy(dtype=float)

    valid = np.isfinite(distance) & np.isfinite(throttle)
    if not np.any(valid):
        return None, None

    return distance[valid], throttle[valid]


def _event_index_bounds(distance, event):
    if distance is None or not isinstance(event, dict):
        return None

    start_m = _safe_float(
        event.get("confirmation_distance_m")
    )
    end_m = _safe_float(
        event.get("release_distance_m")
    )

    if start_m is None or end_m is None or end_m <= start_m:
        return None

    indexes = np.flatnonzero(
        (distance >= start_m)
        & (distance <= end_m)
    )

    if len(indexes) < 2:
        return None

    return int(indexes[0]), int(indexes[-1])


def _classification(minimum_percent, length_m):
    deep = (
        minimum_percent
        < SUSTAINED_MODULATION_DEEP_FLOOR_PERCENT
    )
    long_ = (
        length_m
        > SUSTAINED_MODULATION_LONG_DISTANCE_M
    )

    if deep and long_:
        return "deep_and_long"
    if deep:
        return "deep"
    if long_:
        return "long"
    return None


def detect_sustained_modulations_in_event(
    comparison,
    throttle_column,
    event,
):
    """
    Detect recovered sustained throttle reductions within one physical event.

    Candidate:
    - running pre-level >=60 %;
    - drop >=20 pp;
    - never reaches confirmed-release floor (<=2 %);
    - recovers to within 8 pp of its pre-level;
    - duration >=30 m and <=250 m;
    - additionally: minimum <20 % OR duration >60 m.

    The last rule keeps this category disjoint from partial_lift v1.2.1.
    """
    distance, throttle = _extract_signal(
        comparison,
        throttle_column,
    )

    if distance is None or throttle is None:
        return []

    bounds = _event_index_bounds(
        distance,
        event,
    )
    if bounds is None:
        return []

    start_index, end_index = bounds

    running_peak_value = float(throttle[start_index])
    running_peak_index = start_index
    candidate = None
    result = []

    for index in range(start_index + 1, end_index + 1):
        value = float(throttle[index])
        d = float(distance[index])

        if candidate is None:
            if value > running_peak_value:
                running_peak_value = value
                running_peak_index = index

            if (
                running_peak_value
                >= SUSTAINED_MODULATION_MIN_PRE_LEVEL_PERCENT
                and (
                    running_peak_value - value
                    >= SUSTAINED_MODULATION_MIN_DROP_PP
                )
                and value > THROTTLE_RELEASE_THRESHOLD_PERCENT
            ):
                candidate = {
                    "baseline_percent": running_peak_value,
                    "baseline_distance_m":
                        float(distance[running_peak_index]),
                    "start_index": index,
                    "start_distance_m": d,
                    "min_index": index,
                    "min_percent": value,
                }
            continue

        # A confirmed-release-like floor terminates the candidate.
        if value <= THROTTLE_RELEASE_THRESHOLD_PERCENT:
            candidate = None
            running_peak_value = value
            running_peak_index = index
            continue

        if value < candidate["min_percent"]:
            candidate["min_percent"] = value
            candidate["min_index"] = index

        length_m = d - candidate["start_distance_m"]

        if length_m > SUSTAINED_MODULATION_MAX_DISTANCE_M:
            candidate = None
            running_peak_value = value
            running_peak_index = index
            continue

        recovery_level = (
            candidate["baseline_percent"]
            - SUSTAINED_MODULATION_RECOVERY_TOLERANCE_PP
        )

        if value >= recovery_level:
            classification = _classification(
                candidate["min_percent"],
                length_m,
            )

            if (
                length_m >= SUSTAINED_MODULATION_MIN_DISTANCE_M
                and classification is not None
            ):
                min_index = candidate["min_index"]

                result.append({
                    "sustained_modulation_id":
                        f"sustained_modulation:{len(result) + 1:02d}",
                    "classification": classification,
                    "baseline_distance_m":
                        _safe_float(
                            candidate["baseline_distance_m"]
                        ),
                    "start_distance_m":
                        _safe_float(
                            candidate["start_distance_m"]
                        ),
                    "minimum_distance_m":
                        _safe_float(distance[min_index]),
                    "recovery_distance_m":
                        _safe_float(d),
                    "length_m":
                        _safe_float(length_m),
                    "pre_modulation_percent":
                        _safe_float(
                            candidate["baseline_percent"]
                        ),
                    "minimum_throttle_percent":
                        _safe_float(
                            candidate["min_percent"]
                        ),
                    "depth_pp":
                        _safe_float(
                            candidate["baseline_percent"]
                            - candidate["min_percent"]
                        ),
                    "recovered": True,
                    "observational_only": True,
                })

            candidate = None
            running_peak_value = value
            running_peak_index = index

    return result


def detect_sustained_modulations_by_event(
    comparison,
    throttle_column,
    events,
):
    result = {}

    for event in events or []:
        if not isinstance(event, dict):
            continue
        event_id = event.get("throttle_event_id")
        if not event_id:
            continue

        result[event_id] = (
            detect_sustained_modulations_in_event(
                comparison,
                throttle_column,
                event,
            )
        )

    return result


def _interval_overlap_m(a0, a1, b0, b1):
    values = tuple(
        _safe_float(value)
        for value in (a0, a1, b0, b1)
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


def _modulation_associated_with_episode(modulation, episode):
    if not isinstance(modulation, dict) or not isinstance(episode, dict):
        return False

    episode_start = _safe_float(
        episode.get("start_distance_m")
    )
    episode_end = _safe_float(
        episode.get("end_distance_m")
    )
    modulation_start = _safe_float(
        modulation.get("start_distance_m")
    )
    modulation_end = _safe_float(
        modulation.get("recovery_distance_m")
    )

    if None in (
        episode_start,
        episode_end,
        modulation_start,
        modulation_end,
    ):
        return False

    if _interval_overlap_m(
        episode_start,
        episode_end,
        modulation_start,
        modulation_end,
    ) > 0.0:
        return True

    distances = [
        _distance_to_interval(
            modulation_start,
            episode_start,
            episode_end,
        ),
        _distance_to_interval(
            modulation_end,
            episode_start,
            episode_end,
        ),
    ]
    distances = [
        value for value in distances
        if value is not None
    ]

    return bool(
        distances
        and min(distances)
        <= THROTTLE_POINT_ASSOCIATION_TOLERANCE_M
    )


def build_sustained_modulation_comparison(
    episode,
    reference_events,
    comparison_events,
    paired_events,
    reference_modulations_by_event,
    comparison_modulations_by_event,
):
    if not isinstance(episode, dict):
        return None

    if "throttle" not in set(
        episode.get("action_channels", []) or []
    ):
        return None

    ref_event_map = {
        event.get("throttle_event_id"): event
        for event in reference_events or []
        if isinstance(event, dict)
        and event.get("throttle_event_id")
    }
    cmp_event_map = {
        event.get("throttle_event_id"): event
        for event in comparison_events or []
        if isinstance(event, dict)
        and event.get("throttle_event_id")
    }

    reference_records = []
    comparison_records = []

    for event_id, modulations in (
        reference_modulations_by_event or {}
    ).items():
        for modulation in modulations or []:
            if _modulation_associated_with_episode(
                modulation,
                episode,
            ):
                record = dict(modulation)
                record["throttle_event_id"] = event_id
                reference_records.append(record)

    for event_id, modulations in (
        comparison_modulations_by_event or {}
    ).items():
        for modulation in modulations or []:
            if _modulation_associated_with_episode(
                modulation,
                episode,
            ):
                record = dict(modulation)
                record["throttle_event_id"] = event_id
                comparison_records.append(record)

    if not reference_records and not comparison_records:
        return None

    pair_context = []
    ref_ids = {
        item["throttle_event_id"]
        for item in reference_records
    }
    cmp_ids = {
        item["throttle_event_id"]
        for item in comparison_records
    }

    for pair in paired_events or []:
        if not isinstance(pair, dict):
            continue

        ref_id = pair.get("reference_event_id")
        cmp_id = pair.get("comparison_event_id")

        if ref_id not in ref_ids and cmp_id not in cmp_ids:
            continue

        pair_context.append({
            "throttle_pair_id": pair.get("throttle_pair_id"),
            "reference_event_id": ref_id,
            "comparison_event_id": cmp_id,
            "reference_modulation_count": sum(
                1
                for item in reference_records
                if item["throttle_event_id"] == ref_id
            ),
            "comparison_modulation_count": sum(
                1
                for item in comparison_records
                if item["throttle_event_id"] == cmp_id
            ),
            "pair_cost": _safe_float(pair.get("pair_cost")),
        })

    reference_records.sort(
        key=lambda item: (
            item.get("start_distance_m", float("inf")),
            item.get("recovery_distance_m", float("inf")),
        )
    )
    comparison_records.sort(
        key=lambda item: (
            item.get("start_distance_m", float("inf")),
            item.get("recovery_distance_m", float("inf")),
        )
    )

    return {
        "status": "VALID",
        "reference_modulation_count": len(reference_records),
        "comparison_modulation_count": len(comparison_records),
        "count_difference": (
            len(comparison_records) - len(reference_records)
        ),
        "comparison_has_additional_sustained_modulation": (
            len(comparison_records) > len(reference_records)
        ),
        "comparison_has_fewer_sustained_modulations": (
            len(comparison_records) < len(reference_records)
        ),
        "reference_modulations": reference_records,
        "comparison_modulations": comparison_records,
        "paired_event_context": pair_context,
        "observational_only": True,
        "affects_ranking": False,
        "authorized_coaching": False,
    }


def _episode_key(episode):
    if not isinstance(episode, dict):
        return None
    return (
        episode.get("zone_id"),
        _safe_float(episode.get("start_distance_m")),
        _safe_float(episode.get("end_distance_m")),
    )


def enrich_objective_with_sustained_throttle_modulations(
    comparison,
    objective_analysis,
):
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

    reference_by_event = detect_sustained_modulations_by_event(
        comparison,
        "throttle_a",
        reference_events,
    )
    comparison_by_event = detect_sustained_modulations_by_event(
        comparison,
        "throttle_b",
        comparison_events,
    )

    ranking = objective_analysis.get(
        "driver_action_episode_ranking",
        [],
    )

    by_key = {}
    throttle_episode_count = 0
    episodes_with_modulation = 0

    if isinstance(ranking, list):
        for episode in ranking:
            if not isinstance(episode, dict):
                continue

            if "throttle" not in set(
                episode.get("action_channels", []) or []
            ):
                continue

            throttle_episode_count += 1

            result = build_sustained_modulation_comparison(
                episode,
                reference_events,
                comparison_events,
                paired_events,
                reference_by_event,
                comparison_by_event,
            )

            if result is None:
                continue

            episodes_with_modulation += 1
            episode[
                "throttle_sustained_modulation_comparison"
            ] = result

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
                zone.get("driver_action_episodes", []) or []
            ):
                key = _episode_key(episode)
                if key in by_key:
                    episode[
                        "throttle_sustained_modulation_comparison"
                    ] = dict(by_key[key])

    objective_analysis[
        "throttle_sustained_modulation_detection"
    ] = {
        "version": THROTTLE_SUSTAINED_MODULATION_VERSION,
        "schema_version":
            THROTTLE_SUSTAINED_MODULATION_SCHEMA_VERSION,
        "config": sustained_modulation_config_summary(),
        "reference_event_count": len(reference_events),
        "comparison_event_count": len(comparison_events),
        "paired_event_count": len(paired_events),
        "reference_modulation_count": sum(
            len(items)
            for items in reference_by_event.values()
        ),
        "comparison_modulation_count": sum(
            len(items)
            for items in comparison_by_event.values()
        ),
        "throttle_episode_count": throttle_episode_count,
        "episodes_with_sustained_modulation":
            episodes_with_modulation,
        "policy": "observational_only_no_ranking_no_coaching",
    }

    return objective_analysis
