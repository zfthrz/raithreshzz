import math
import statistics
from collections import Counter, defaultdict


THROTTLE_MODULATION_RECURRENCE_VERSION = "1.0"
THROTTLE_MODULATION_RECURRENCE_SCHEMA_VERSION = "1.0"
THROTTLE_MODULATION_RECURRENCE_MIN_SUPPORT_COUNT = 2

STATE_ADDITIONAL = "additional_in_comparison"
STATE_FEWER = "fewer_in_comparison"
STATE_SAME = "same_count"

DEVIATION_STATES = (
    STATE_ADDITIONAL,
    STATE_FEWER,
)

SUSTAINED_CLASSIFICATIONS = (
    "deep",
    "long",
    "deep_and_long",
)


# ============================================================
# THROTTLE MODULATION RECURRENCE v1.0
# DETERMINISTIC / SESSION-LEVEL / OBSERVATIONAL
# ============================================================
#
# Aggregates two already-detected objective facts across comparison laps:
#
# 1) partial_lift recurrence
#    source:
#      throttle_partial_lift_comparison
#
# 2) sustained throttle modulation recurrence
#    source:
#      throttle_sustained_modulation_comparison
#
# Physical identity:
# - the reference lap is fixed for one analysis;
# - reference_event_id identifies the physical throttle event;
# - episode labels/zones are context only and never define identity.
#
# Recurrence rule:
# - minimum 2 comparison laps supporting the same deviation state;
# - one observation maximum per physical reference event per comparison lap;
# - missing/null/unavailable evidence is not a contradiction;
# - equal counts are preserved as neutral evidence but are never promoted as
#   a repeated deviation.
#
# This module NEVER:
# - changes throttle detection or pairing;
# - changes driver_action_episodes;
# - changes ranking/session priority;
# - authorizes coaching;
# - infers causality, traction, wheelspin, line, balance or intent.
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


def _safe_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _median(values):
    clean = []
    for value in values:
        value = _safe_float(value)
        if value is not None:
            clean.append(value)
    if not clean:
        return None
    return float(statistics.median(clean))


def _state_from_counts(reference_count, comparison_count):
    reference_count = _safe_int(reference_count)
    comparison_count = _safe_int(comparison_count)

    if reference_count is None or comparison_count is None:
        return None

    if comparison_count > reference_count:
        return STATE_ADDITIONAL
    if comparison_count < reference_count:
        return STATE_FEWER
    return STATE_SAME


def throttle_modulation_recurrence_config_summary():
    return {
        "enabled": True,
        "version": THROTTLE_MODULATION_RECURRENCE_VERSION,
        "schema_version": THROTTLE_MODULATION_RECURRENCE_SCHEMA_VERSION,
        "min_support_count": THROTTLE_MODULATION_RECURRENCE_MIN_SUPPORT_COUNT,
        "physical_identity": "reference_lap_plus_reference_event_id",
        "missing_observations_are_contradictions": False,
        "unavailable_observations_are_contradictions": False,
        "same_count_is_repeated_deviation": False,
        "deduplication":
            "one_physical_reference_event_per_comparison_lap",
        "observational_only": True,
        "affects_ranking": False,
        "affects_session_priority": False,
        "authorizes_coaching": False,
    }


def _episode_ranking(comparison_output):
    if not isinstance(comparison_output, dict):
        return []

    objective = comparison_output.get("objective_analysis")
    if not isinstance(objective, dict):
        return []

    ranking = objective.get("driver_action_episode_ranking", [])
    return ranking if isinstance(ranking, list) else []


def _candidate_selection_key(candidate):
    status_score = 1 if candidate.get("status") == "VALID" else 0

    global_rank = candidate.get("episode_global_rank")
    try:
        global_rank = int(global_rank)
    except (TypeError, ValueError):
        global_rank = 10**9

    action_loss = _safe_float(candidate.get("action_time_loss_s")) or 0.0

    return (
        -status_score,
        global_rank,
        -action_loss,
    )


def _base_candidate(comparison_output, episode):
    return {
        "reference_lap": _safe_int(
            comparison_output.get("reference_lap")
        ),
        "comparison_lap": _safe_int(
            comparison_output.get("comparison_lap")
        ),
        "episode_id": episode.get("episode_id"),
        "episode_global_rank": episode.get("global_rank"),
        "zone_id": episode.get("zone_id"),
        "episode_start_m": _safe_float(
            episode.get("start_distance_m")
        ),
        "episode_end_m": _safe_float(
            episode.get("end_distance_m")
        ),
        "action_time_loss_s": _safe_float(
            episode.get("action_time_loss_s")
        ),
        "observational_only": True,
    }


def _deduplicate_candidates(candidates):
    """
    One observation per:
      (reference_lap, comparison_lap, reference_event_id)

    Conflicting duplicate episode assignments are preserved as CONFLICT and
    excluded from recurrence support.
    """
    buckets = defaultdict(list)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        reference_event_id = candidate.get("reference_event_id")
        if not reference_event_id:
            continue

        key = (
            candidate.get("reference_lap"),
            candidate.get("comparison_lap"),
            str(reference_event_id),
        )
        buckets[key].append(candidate)

    result = []

    for key in sorted(
        buckets,
        key=lambda item: (
            item[0] if item[0] is not None else 10**9,
            item[1] if item[1] is not None else 10**9,
            item[2],
        ),
    ):
        rows = buckets[key]
        signatures = {
            (
                row.get("status"),
                row.get("deviation_state"),
                row.get("reference_count"),
                row.get("comparison_count"),
                tuple(sorted(row.get("focus_classifications") or [])),
            )
            for row in rows
        }

        winner = dict(
            sorted(rows, key=_candidate_selection_key)[0]
        )
        winner["duplicate_episode_count"] = max(0, len(rows) - 1)
        winner["duplicate_conflict"] = len(signatures) > 1

        if winner["duplicate_conflict"]:
            winner["status"] = "CONFLICT"
            winner["deviation_state"] = None
            winner["reason"] = (
                "conflicting_duplicate_episode_assignments"
            )

        result.append(winner)

    return result


# ============================================================
# PARTIAL LIFT
# ============================================================


def _partial_lift_candidates(comparisons):
    candidates = []

    for comparison_output in comparisons:
        if not isinstance(comparison_output, dict):
            continue

        for episode in _episode_ranking(comparison_output):
            if not isinstance(episode, dict):
                continue

            result = episode.get(
                "throttle_partial_lift_comparison"
            )
            if not isinstance(result, dict):
                continue

            reference_event_id = result.get("reference_event_id")
            if not reference_event_id:
                continue

            row = _base_candidate(
                comparison_output,
                episode,
            )
            row.update({
                "status": result.get("status"),
                "throttle_pair_id":
                    result.get("throttle_pair_id"),
                "reference_event_id":
                    reference_event_id,
                "comparison_event_id":
                    result.get("comparison_event_id"),
                "reference_count": _safe_int(
                    result.get("reference_partial_lift_count")
                ),
                "comparison_count": _safe_int(
                    result.get("comparison_partial_lift_count")
                ),
                "count_difference": _safe_int(
                    result.get("count_difference")
                ),
                "deviation_state": (
                    _state_from_counts(
                        result.get("reference_partial_lift_count"),
                        result.get("comparison_partial_lift_count"),
                    )
                    if result.get("status") == "VALID"
                    else None
                ),
                "reason": result.get("reason"),
            })
            candidates.append(row)

    return _deduplicate_candidates(candidates)


def _count_recurrence_pattern(
    reference_lap,
    reference_event_id,
    rows,
    total_comparisons,
    physical_prefix,
):
    valid_rows = [
        row
        for row in rows
        if row.get("status") == "VALID"
        and row.get("deviation_state") in (
            STATE_ADDITIONAL,
            STATE_FEWER,
            STATE_SAME,
        )
    ]
    conflict_rows = [
        row for row in rows
        if row.get("status") == "CONFLICT"
    ]
    unavailable_rows = [
        row for row in rows
        if row.get("status") == "UNAVAILABLE"
    ]

    deviation_counts = Counter(
        row.get("deviation_state")
        for row in valid_rows
        if row.get("deviation_state") in DEVIATION_STATES
    )
    neutral_count = sum(
        1
        for row in valid_rows
        if row.get("deviation_state") == STATE_SAME
    )

    selected_state = None
    selected_count = 0

    if deviation_counts:
        selected_count = max(deviation_counts.values())
        top_states = sorted(
            state
            for state, count in deviation_counts.items()
            if count == selected_count
        )
        if len(top_states) == 1:
            selected_state = top_states[0]

    is_repeated = bool(
        selected_state
        and selected_count
        >= THROTTLE_MODULATION_RECURRENCE_MIN_SUPPORT_COUNT
    )

    distinct_deviation_states = len(deviation_counts)

    if not is_repeated:
        recurrence_status = "NOT_REPEATED"
    elif distinct_deviation_states == 1:
        recurrence_status = "REPEATED_CONSISTENT"
    else:
        recurrence_status = "REPEATED_WITH_MIXED_EVIDENCE"

    support_rows = (
        [
            row
            for row in valid_rows
            if row.get("deviation_state") == selected_state
        ]
        if selected_state
        else []
    )

    observed_laps = sorted({
        row.get("comparison_lap")
        for row in rows
        if row.get("comparison_lap") is not None
    })
    support_laps = sorted({
        row.get("comparison_lap")
        for row in support_rows
        if row.get("comparison_lap") is not None
    })

    valid_deviation_count = sum(deviation_counts.values())
    support_fraction = (
        selected_count / valid_deviation_count
        if selected_state and valid_deviation_count > 0
        else None
    )

    direction_counts = {
        state: deviation_counts.get(state, 0)
        for state in DEVIATION_STATES
        if deviation_counts.get(state, 0) > 0
    }
    if neutral_count:
        direction_counts[STATE_SAME] = neutral_count

    return {
        "physical_point_id":
            f"{physical_prefix}:{reference_event_id}",
        "reference_lap": reference_lap,
        "reference_event_id": reference_event_id,
        "selected_state": selected_state,
        "recurrence_status": recurrence_status,
        "is_repeated": is_repeated,
        "is_consistent":
            recurrence_status == "REPEATED_CONSISTENT",
        "support_count":
            selected_count if selected_state else 0,
        "valid_observation_count": len(valid_rows),
        "valid_deviation_observation_count":
            valid_deviation_count,
        "neutral_same_count_observation_count":
            neutral_count,
        "unavailable_observation_count":
            len(unavailable_rows),
        "conflict_observation_count":
            len(conflict_rows),
        "observed_comparison_count":
            len(observed_laps),
        "missing_comparison_count":
            max(0, total_comparisons - len(observed_laps)),
        "support_fraction_of_deviations":
            _safe_float(support_fraction),
        "state_counts": direction_counts,
        "support_comparison_laps": support_laps,
        "observed_comparison_laps": observed_laps,
        "reference_count_median": _median(
            row.get("reference_count")
            for row in support_rows
        ),
        "comparison_count_median": _median(
            row.get("comparison_count")
            for row in support_rows
        ),
        "count_difference_median": _median(
            row.get("count_difference")
            for row in support_rows
        ),
        "observations": sorted(
            rows,
            key=lambda row: (
                row.get("comparison_lap")
                if row.get("comparison_lap") is not None
                else 10**9,
                row.get("episode_global_rank")
                if isinstance(
                    row.get("episode_global_rank"),
                    int,
                )
                else 10**9,
            ),
        ),
        "observational_only": True,
        "affects_ranking": False,
        "affects_session_priority": False,
        "authorized_coaching": False,
    }


def build_partial_lift_recurrence(comparisons):
    comparisons = comparisons if isinstance(comparisons, list) else []
    occurrences = _partial_lift_candidates(comparisons)

    groups = defaultdict(list)
    for row in occurrences:
        reference_event_id = row.get("reference_event_id")
        if not reference_event_id:
            continue

        groups[
            (
                row.get("reference_lap"),
                reference_event_id,
            )
        ].append(row)

    patterns = []
    for (reference_lap, reference_event_id), rows in sorted(
        groups.items(),
        key=lambda item: (
            item[0][0] if item[0][0] is not None else 10**9,
            item[0][1],
        ),
    ):
        patterns.append(
            _count_recurrence_pattern(
                reference_lap,
                reference_event_id,
                rows,
                len(comparisons),
                "partial_lift",
            )
        )

    repeated = [
        pattern
        for pattern in patterns
        if pattern.get("is_repeated")
    ]

    return {
        "source_field": "throttle_partial_lift_comparison",
        "comparison_count": len(comparisons),
        "physical_point_count": len(patterns),
        "repeated_pattern_count": len(repeated),
        "consistent_repeated_pattern_count": sum(
            1
            for pattern in repeated
            if pattern.get("recurrence_status")
            == "REPEATED_CONSISTENT"
        ),
        "additional_repeated_pattern_count": sum(
            1
            for pattern in repeated
            if pattern.get("selected_state")
            == STATE_ADDITIONAL
        ),
        "fewer_repeated_pattern_count": sum(
            1
            for pattern in repeated
            if pattern.get("selected_state")
            == STATE_FEWER
        ),
        "patterns": patterns,
        "observational_only": True,
        "affects_ranking": False,
        "affects_session_priority": False,
        "authorized_coaching": False,
    }


# ============================================================
# SUSTAINED THROTTLE MODULATION
# ============================================================


def _classifications_for_event(records, event_id):
    result = []

    for record in records or []:
        if not isinstance(record, dict):
            continue
        if record.get("throttle_event_id") != event_id:
            continue

        classification = record.get("classification")
        if classification in SUSTAINED_CLASSIFICATIONS:
            result.append(classification)

    return sorted(result)


def _sustained_candidates(comparisons):
    candidates = []
    unanchored_count = 0

    for comparison_output in comparisons:
        if not isinstance(comparison_output, dict):
            continue

        for episode in _episode_ranking(comparison_output):
            if not isinstance(episode, dict):
                continue

            result = episode.get(
                "throttle_sustained_modulation_comparison"
            )
            if not isinstance(result, dict):
                continue

            if result.get("status") != "VALID":
                continue

            pair_context = result.get("paired_event_context", [])
            if not isinstance(pair_context, list):
                pair_context = []

            if not pair_context:
                unanchored_count += 1
                continue

            reference_records = result.get(
                "reference_modulations",
                [],
            )
            comparison_records = result.get(
                "comparison_modulations",
                [],
            )

            for context in pair_context:
                if not isinstance(context, dict):
                    continue

                reference_event_id = context.get(
                    "reference_event_id"
                )
                comparison_event_id = context.get(
                    "comparison_event_id"
                )

                if not reference_event_id:
                    unanchored_count += 1
                    continue

                reference_count = _safe_int(
                    context.get("reference_modulation_count")
                )
                comparison_count = _safe_int(
                    context.get("comparison_modulation_count")
                )

                state = _state_from_counts(
                    reference_count,
                    comparison_count,
                )

                if state == STATE_ADDITIONAL:
                    focus = _classifications_for_event(
                        comparison_records,
                        comparison_event_id,
                    )
                elif state == STATE_FEWER:
                    focus = _classifications_for_event(
                        reference_records,
                        reference_event_id,
                    )
                else:
                    focus = []

                row = _base_candidate(
                    comparison_output,
                    episode,
                )
                row.update({
                    "status": "VALID",
                    "throttle_pair_id":
                        context.get("throttle_pair_id"),
                    "reference_event_id":
                        reference_event_id,
                    "comparison_event_id":
                        comparison_event_id,
                    "reference_count":
                        reference_count,
                    "comparison_count":
                        comparison_count,
                    "count_difference": (
                        comparison_count - reference_count
                        if reference_count is not None
                        and comparison_count is not None
                        else None
                    ),
                    "deviation_state": state,
                    "focus_classifications": focus,
                    "pair_cost": _safe_float(
                        context.get("pair_cost")
                    ),
                })
                candidates.append(row)

    return (
        _deduplicate_candidates(candidates),
        unanchored_count,
    )


def _add_sustained_classification_summary(pattern):
    support_rows = [
        row
        for row in pattern.get("observations", [])
        if row.get("status") == "VALID"
        and row.get("deviation_state")
        == pattern.get("selected_state")
    ]

    comparison_counts = Counter()

    for row in support_rows:
        # A classification can count at most once per comparison lap.
        for classification in set(
            row.get("focus_classifications") or []
        ):
            if classification in SUSTAINED_CLASSIFICATIONS:
                comparison_counts[classification] += 1

    ordered = {
        classification:
            comparison_counts.get(classification, 0)
        for classification in SUSTAINED_CLASSIFICATIONS
        if comparison_counts.get(classification, 0) > 0
    }

    dominant = None
    dominant_support = 0

    if comparison_counts:
        dominant_support = max(comparison_counts.values())
        top = sorted(
            classification
            for classification, count
            in comparison_counts.items()
            if count == dominant_support
        )
        if len(top) == 1:
            dominant = top[0]

    pattern["classification_comparison_counts"] = ordered
    pattern["dominant_classification"] = dominant
    pattern["dominant_classification_support_count"] = (
        dominant_support if dominant else 0
    )
    pattern["repeated_classification"] = bool(
        dominant
        and dominant_support
        >= THROTTLE_MODULATION_RECURRENCE_MIN_SUPPORT_COUNT
    )
    pattern["classification_consistent"] = (
        bool(ordered)
        and len(ordered) == 1
    )

    return pattern


def build_sustained_throttle_modulation_recurrence(
    comparisons,
):
    comparisons = comparisons if isinstance(comparisons, list) else []

    occurrences, unanchored_count = _sustained_candidates(
        comparisons
    )

    groups = defaultdict(list)
    for row in occurrences:
        reference_event_id = row.get("reference_event_id")
        if not reference_event_id:
            continue

        groups[
            (
                row.get("reference_lap"),
                reference_event_id,
            )
        ].append(row)

    patterns = []
    for (reference_lap, reference_event_id), rows in sorted(
        groups.items(),
        key=lambda item: (
            item[0][0] if item[0][0] is not None else 10**9,
            item[0][1],
        ),
    ):
        pattern = _count_recurrence_pattern(
            reference_lap,
            reference_event_id,
            rows,
            len(comparisons),
            "sustained_throttle_modulation",
        )
        patterns.append(
            _add_sustained_classification_summary(
                pattern
            )
        )

    repeated = [
        pattern
        for pattern in patterns
        if pattern.get("is_repeated")
    ]

    return {
        "source_field":
            "throttle_sustained_modulation_comparison",
        "comparison_count": len(comparisons),
        "physical_point_count": len(patterns),
        "unanchored_observation_count": unanchored_count,
        "repeated_pattern_count": len(repeated),
        "consistent_repeated_pattern_count": sum(
            1
            for pattern in repeated
            if pattern.get("recurrence_status")
            == "REPEATED_CONSISTENT"
        ),
        "additional_repeated_pattern_count": sum(
            1
            for pattern in repeated
            if pattern.get("selected_state")
            == STATE_ADDITIONAL
        ),
        "fewer_repeated_pattern_count": sum(
            1
            for pattern in repeated
            if pattern.get("selected_state")
            == STATE_FEWER
        ),
        "repeated_classification_pattern_count": sum(
            1
            for pattern in repeated
            if pattern.get("repeated_classification")
        ),
        "patterns": patterns,
        "observational_only": True,
        "affects_ranking": False,
        "affects_session_priority": False,
        "authorized_coaching": False,
    }


# ============================================================
# SESSION ENRICHMENT
# ============================================================


def build_throttle_modulation_recurrence(comparisons):
    comparisons = comparisons if isinstance(comparisons, list) else []

    return {
        "version": THROTTLE_MODULATION_RECURRENCE_VERSION,
        "schema_version":
            THROTTLE_MODULATION_RECURRENCE_SCHEMA_VERSION,
        "config":
            throttle_modulation_recurrence_config_summary(),
        "partial_lift":
            build_partial_lift_recurrence(comparisons),
        "sustained_throttle_modulation":
            build_sustained_throttle_modulation_recurrence(
                comparisons
            ),
        "policy":
            "observational_only_no_ranking_no_session_priority_no_coaching",
    }


def enrich_analysis_with_throttle_modulation_recurrence(
    analysis_output,
):
    """Session-level in-place enrichment after all comparisons are built."""
    if not isinstance(analysis_output, dict):
        return analysis_output

    comparisons = analysis_output.get("comparisons", [])
    analysis_output["throttle_modulation_recurrence"] = (
        build_throttle_modulation_recurrence(comparisons)
    )
    return analysis_output
