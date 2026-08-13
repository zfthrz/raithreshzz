import copy
import math
from collections import defaultdict


THROTTLE_PHYSICAL_POINT_PROFILE_VERSION = "1.0"
THROTTLE_PHYSICAL_POINT_PROFILE_SCHEMA_VERSION = "1.0"

FEATURE_ORDER = (
    "sequence",
    "onset",
    "release",
    "full_throttle_attainment",
    "partial_lift",
    "sustained_throttle_modulation",
)

POINT_RESULT_FIELDS = {
    "onset": "throttle_onset_point_comparison",
    "release": "throttle_release_point_comparison",
    "full_throttle_attainment": (
        "throttle_full_throttle_attainment_comparison"
    ),
    "partial_lift": "throttle_partial_lift_comparison",
}


# ============================================================
# THROTTLE PHYSICAL POINT PROFILE v1.0
# DETERMINISTIC / SESSION-LEVEL / OBSERVATIONAL UNIFICATION
# ============================================================
#
# This module does NOT detect or pair throttle events.
# It only unifies facts already produced by:
# - throttle_point_v1_2_1
# - throttle_episode_sequence_v1_0
# - throttle_sustained_modulation_v1_0
# - full_throttle_recurrence_v1_0
# - throttle_modulation_recurrence_v1_0
#
# Physical identity:
#   reference_lap + reference_event_id
#
# The profile never:
# - changes driver_action_episodes;
# - changes ranking or next_session_priorities;
# - creates new coaching authorization;
# - re-detects onset/release/full throttle/lifts/modulations;
# - infers traction, wheelspin, line, balance, intent or causality.
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


def throttle_physical_point_profile_config_summary():
    return {
        "enabled": True,
        "version": THROTTLE_PHYSICAL_POINT_PROFILE_VERSION,
        "schema_version": THROTTLE_PHYSICAL_POINT_PROFILE_SCHEMA_VERSION,
        "physical_identity": "reference_lap_plus_reference_event_id",
        "source_modules": [
            "throttle_point_v1_2_1",
            "throttle_episode_sequence_v1_0",
            "throttle_sustained_modulation_v1_0",
            "full_throttle_recurrence_v1_0",
            "throttle_modulation_recurrence_v1_0",
        ],
        "source_only_no_redetection": True,
        "duplicate_policy": (
            "one_canonical_feature_observation_per_reference_event_"
            "per_comparison_lap_preserve_conflict_flag"
        ),
        "comparison_only_events_create_reference_profile": False,
        "observational_only": True,
        "affects_ranking": False,
        "affects_session_priority": False,
        "authorizes_new_coaching": False,
    }


def _episode_ranking(comparison_output):
    if not isinstance(comparison_output, dict):
        return []
    objective = comparison_output.get("objective_analysis")
    if not isinstance(objective, dict):
        return []
    ranking = objective.get("driver_action_episode_ranking", [])
    return ranking if isinstance(ranking, list) else []


def _episode_context(episode):
    return {
        "episode_id": episode.get("episode_id"),
        "episode_global_rank": episode.get("global_rank"),
        "zone_id": episode.get("zone_id"),
        "start_distance_m": _safe_float(episode.get("start_distance_m")),
        "end_distance_m": _safe_float(episode.get("end_distance_m")),
        "action_time_loss_s": _safe_float(episode.get("action_time_loss_s")),
    }


def _base_observation(comparison_output, episode):
    row = {
        "reference_lap": _safe_int(comparison_output.get("reference_lap")),
        "comparison_lap": _safe_int(comparison_output.get("comparison_lap")),
    }
    row.update(_episode_context(episode))
    return row


def _selection_key(row):
    rank = row.get("episode_global_rank")
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        rank = 10**9
    action_loss = _safe_float(row.get("action_time_loss_s")) or 0.0
    return (rank, -action_loss)


def _freeze(value):
    if isinstance(value, dict):
        return tuple(
            (key, _freeze(value[key]))
            for key in sorted(value)
            if key not in {
                "episode_id",
                "episode_global_rank",
                "zone_id",
                "start_distance_m",
                "end_distance_m",
                "action_time_loss_s",
                "duplicate_episode_count",
                "duplicate_conflict",
            }
        )
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, 9)
    return value


def _deduplicate_feature_rows(rows):
    """At most one canonical row per feature/event/comparison lap."""
    buckets = defaultdict(list)

    for row in rows:
        if not isinstance(row, dict):
            continue
        reference_event_id = row.get("reference_event_id")
        if not reference_event_id:
            continue
        key = (
            row.get("reference_lap"),
            row.get("comparison_lap"),
            str(reference_event_id),
        )
        buckets[key].append(row)

    output = []
    for key in sorted(
        buckets,
        key=lambda item: (
            item[0] if item[0] is not None else 10**9,
            item[1] if item[1] is not None else 10**9,
            item[2],
        ),
    ):
        candidates = buckets[key]
        winner = dict(sorted(candidates, key=_selection_key)[0])
        signatures = {_freeze(row) for row in candidates}
        winner["duplicate_episode_count"] = max(0, len(candidates) - 1)
        winner["duplicate_conflict"] = len(signatures) > 1
        output.append(winner)

    return output


def _compact_sequence_observation(comparison_output, episode, item):
    reference_event = item.get("reference_event")
    if not isinstance(reference_event, dict):
        return None

    reference_event_id = reference_event.get("event_id")
    if not reference_event_id:
        return None

    comparison_event = item.get("comparison_event")
    comparison_event_id = (
        comparison_event.get("event_id")
        if isinstance(comparison_event, dict)
        else None
    )

    row = _base_observation(comparison_output, episode)
    row.update({
        "reference_event_id": reference_event_id,
        "comparison_event_id": comparison_event_id,
        "pair_status": item.get("pair_status"),
        "throttle_pair_id": item.get("throttle_pair_id"),
        "pair_cost": _safe_float(item.get("pair_cost")),
        "sequence_index": _safe_int(item.get("sequence_index")),
        "reference_event": copy.deepcopy(reference_event),
        "comparison_event": copy.deepcopy(comparison_event),
        "differences": copy.deepcopy(item.get("differences")),
        "observational_only": True,
    })
    return row


def _compact_point_observation(
    feature,
    comparison_output,
    episode,
    result,
):
    reference_event_id = result.get("reference_event_id")
    if not reference_event_id:
        return None

    row = _base_observation(comparison_output, episode)
    row.update({
        "reference_event_id": reference_event_id,
        "comparison_event_id": result.get("comparison_event_id"),
        "throttle_pair_id": result.get("throttle_pair_id"),
        "status": result.get("status"),
        "source_result": copy.deepcopy(result),
        "observational_only": True,
    })

    # Surface a small stable index without changing source semantics.
    if feature == "onset":
        row["reference_point_m"] = _safe_float(result.get("reference_onset_m"))
        row["comparison_point_m"] = _safe_float(result.get("comparison_onset_m"))
        row["comparison_minus_reference_m"] = _safe_float(
            result.get("comparison_minus_reference_m")
        )
        row["relative_direction"] = result.get("relative_direction")
    elif feature == "release":
        row["reference_point_m"] = _safe_float(result.get("reference_release_m"))
        row["comparison_point_m"] = _safe_float(result.get("comparison_release_m"))
        row["comparison_minus_reference_m"] = _safe_float(
            result.get("comparison_minus_reference_m")
        )
        row["relative_direction"] = result.get("relative_direction")
    elif feature == "full_throttle_attainment":
        row["reference_point_m"] = _safe_float(result.get("reference_attainment_m"))
        row["comparison_point_m"] = _safe_float(result.get("comparison_attainment_m"))
        row["comparison_minus_reference_m"] = _safe_float(
            result.get("comparison_minus_reference_m")
        )
        row["relative_direction"] = result.get("relative_direction")
    elif feature == "partial_lift":
        row["reference_count"] = _safe_int(
            result.get("reference_partial_lift_count")
        )
        row["comparison_count"] = _safe_int(
            result.get("comparison_partial_lift_count")
        )
        row["count_difference"] = _safe_int(result.get("count_difference"))

    return row


def _sustained_classifications(records, event_id):
    values = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if record.get("throttle_event_id") != event_id:
            continue
        classification = record.get("classification")
        if classification:
            values.append(classification)
    return sorted(values)


def _compact_sustained_observations(comparison_output, episode, result):
    rows = []
    pair_context = result.get("paired_event_context", [])
    if not isinstance(pair_context, list):
        return rows

    reference_records = result.get("reference_modulations", [])
    comparison_records = result.get("comparison_modulations", [])

    for context in pair_context:
        if not isinstance(context, dict):
            continue
        reference_event_id = context.get("reference_event_id")
        if not reference_event_id:
            continue

        comparison_event_id = context.get("comparison_event_id")
        reference_count = _safe_int(context.get("reference_modulation_count"))
        comparison_count = _safe_int(context.get("comparison_modulation_count"))

        row = _base_observation(comparison_output, episode)
        row.update({
            "reference_event_id": reference_event_id,
            "comparison_event_id": comparison_event_id,
            "throttle_pair_id": context.get("throttle_pair_id"),
            "pair_cost": _safe_float(context.get("pair_cost")),
            "status": result.get("status"),
            "reference_count": reference_count,
            "comparison_count": comparison_count,
            "count_difference": (
                comparison_count - reference_count
                if reference_count is not None and comparison_count is not None
                else None
            ),
            "reference_classifications": _sustained_classifications(
                reference_records,
                reference_event_id,
            ),
            "comparison_classifications": _sustained_classifications(
                comparison_records,
                comparison_event_id,
            ),
            "reference_modulations": [
                copy.deepcopy(record)
                for record in reference_records or []
                if isinstance(record, dict)
                and record.get("throttle_event_id") == reference_event_id
            ],
            "comparison_modulations": [
                copy.deepcopy(record)
                for record in comparison_records or []
                if isinstance(record, dict)
                and record.get("throttle_event_id") == comparison_event_id
            ],
            "observational_only": True,
        })
        rows.append(row)

    return rows


def _collect_raw_feature_rows(comparisons):
    feature_rows = {feature: [] for feature in FEATURE_ORDER}
    comparison_only_sequence_count = 0
    unanchored_sustained_context_count = 0

    for comparison_output in comparisons:
        if not isinstance(comparison_output, dict):
            continue

        for episode in _episode_ranking(comparison_output):
            if not isinstance(episode, dict):
                continue

            sequence = episode.get("throttle_event_sequence")
            if isinstance(sequence, dict):
                for item in sequence.get("sequence_items", []) or []:
                    if not isinstance(item, dict):
                        continue
                    if not isinstance(item.get("reference_event"), dict):
                        if isinstance(item.get("comparison_event"), dict):
                            comparison_only_sequence_count += 1
                        continue
                    row = _compact_sequence_observation(
                        comparison_output,
                        episode,
                        item,
                    )
                    if row is not None:
                        feature_rows["sequence"].append(row)

            for feature, field in POINT_RESULT_FIELDS.items():
                result = episode.get(field)
                if not isinstance(result, dict):
                    continue
                row = _compact_point_observation(
                    feature,
                    comparison_output,
                    episode,
                    result,
                )
                if row is not None:
                    feature_rows[feature].append(row)

            sustained = episode.get(
                "throttle_sustained_modulation_comparison"
            )
            if isinstance(sustained, dict):
                rows = _compact_sustained_observations(
                    comparison_output,
                    episode,
                    sustained,
                )
                if not rows and sustained.get("paired_event_context"):
                    unanchored_sustained_context_count += 1
                feature_rows["sustained_throttle_modulation"].extend(rows)

    deduplicated = {
        feature: _deduplicate_feature_rows(rows)
        for feature, rows in feature_rows.items()
    }

    return (
        deduplicated,
        comparison_only_sequence_count,
        unanchored_sustained_context_count,
    )


def _pattern_index(analysis_output):
    index = {
        "full_throttle_attainment": {},
        "partial_lift": {},
        "sustained_throttle_modulation": {},
    }

    full = analysis_output.get("full_throttle_attainment_recurrence")
    if isinstance(full, dict):
        for pattern in full.get("patterns", []) or []:
            if not isinstance(pattern, dict):
                continue
            ref_id = pattern.get("reference_event_id")
            if ref_id:
                index["full_throttle_attainment"][
                    (pattern.get("reference_lap"), str(ref_id))
                ] = copy.deepcopy(pattern)

    modulation = analysis_output.get("throttle_modulation_recurrence")
    if isinstance(modulation, dict):
        for feature, source_key in (
            ("partial_lift", "partial_lift"),
            (
                "sustained_throttle_modulation",
                "sustained_throttle_modulation",
            ),
        ):
            block = modulation.get(source_key)
            if not isinstance(block, dict):
                continue
            for pattern in block.get("patterns", []) or []:
                if not isinstance(pattern, dict):
                    continue
                ref_id = pattern.get("reference_event_id")
                if ref_id:
                    index[feature][
                        (pattern.get("reference_lap"), str(ref_id))
                    ] = copy.deepcopy(pattern)

    return index


def _reference_snapshot(sequence_rows):
    snapshots = [
        row.get("reference_event")
        for row in sequence_rows
        if isinstance(row.get("reference_event"), dict)
    ]
    if not snapshots:
        return None, None, 0

    signatures = {_freeze(snapshot) for snapshot in snapshots}
    return (
        copy.deepcopy(snapshots[0]),
        len(signatures) == 1,
        len(signatures),
    )


def _feature_block(rows):
    valid_count = sum(
        1
        for row in rows
        if row.get("status") in (None, "VALID")
    )
    conflict_count = sum(
        1 for row in rows if row.get("duplicate_conflict")
    )
    return {
        "observation_count": len(rows),
        "valid_observation_count": valid_count,
        "duplicate_conflict_observation_count": conflict_count,
        "observed_comparison_laps": sorted({
            row.get("comparison_lap")
            for row in rows
            if row.get("comparison_lap") is not None
        }),
        "observations": rows,
    }


def _profile_sort_key(profile):
    snapshot = profile.get("reference_event") or {}
    onset = _safe_float(snapshot.get("onset_distance_m"))
    return (
        onset if onset is not None else float("inf"),
        str(profile.get("reference_event_id") or ""),
    )


def build_throttle_physical_point_profiles(analysis_output):
    if not isinstance(analysis_output, dict):
        analysis_output = {}

    comparisons = analysis_output.get("comparisons", [])
    comparisons = comparisons if isinstance(comparisons, list) else []

    (
        feature_rows,
        comparison_only_sequence_count,
        unanchored_sustained_context_count,
    ) = _collect_raw_feature_rows(comparisons)

    recurrence_index = _pattern_index(analysis_output)

    keys = set()
    for rows in feature_rows.values():
        for row in rows:
            ref_id = row.get("reference_event_id")
            if ref_id:
                keys.add((row.get("reference_lap"), str(ref_id)))
    for feature_index in recurrence_index.values():
        keys.update(feature_index.keys())

    profiles = []

    for reference_lap, reference_event_id in sorted(
        keys,
        key=lambda item: (
            item[0] if item[0] is not None else 10**9,
            item[1],
        ),
    ):
        per_feature = {}
        all_rows = []

        for feature in FEATURE_ORDER:
            rows = [
                copy.deepcopy(row)
                for row in feature_rows[feature]
                if row.get("reference_lap") == reference_lap
                and str(row.get("reference_event_id")) == reference_event_id
            ]
            rows.sort(
                key=lambda row: (
                    row.get("comparison_lap")
                    if row.get("comparison_lap") is not None
                    else 10**9,
                    row.get("episode_global_rank")
                    if isinstance(row.get("episode_global_rank"), int)
                    else 10**9,
                )
            )
            per_feature[feature] = _feature_block(rows)
            all_rows.extend(rows)

        reference_event, ref_consistent, ref_variant_count = _reference_snapshot(
            per_feature["sequence"]["observations"]
        )

        observed_laps = sorted({
            row.get("comparison_lap")
            for row in all_rows
            if row.get("comparison_lap") is not None
        })

        comparison_event_pairs = []
        seen_pairs = set()
        for row in all_rows:
            comparison_event_id = row.get("comparison_event_id")
            comparison_lap = row.get("comparison_lap")
            if comparison_event_id is None:
                continue
            pair_key = (comparison_lap, str(comparison_event_id))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            comparison_event_pairs.append({
                "comparison_lap": comparison_lap,
                "comparison_event_id": comparison_event_id,
            })

        episode_contexts = []
        seen_episode_contexts = set()
        for row in all_rows:
            context = (
                row.get("comparison_lap"),
                row.get("episode_id"),
                row.get("zone_id"),
                row.get("start_distance_m"),
                row.get("end_distance_m"),
            )
            if context in seen_episode_contexts:
                continue
            seen_episode_contexts.add(context)
            episode_contexts.append({
                "comparison_lap": row.get("comparison_lap"),
                "episode_id": row.get("episode_id"),
                "episode_global_rank": row.get("episode_global_rank"),
                "zone_id": row.get("zone_id"),
                "start_distance_m": row.get("start_distance_m"),
                "end_distance_m": row.get("end_distance_m"),
            })

        recurrence = {
            feature: recurrence_index[feature].get(
                (reference_lap, reference_event_id)
            )
            for feature in (
                "full_throttle_attainment",
                "partial_lift",
                "sustained_throttle_modulation",
            )
        }

        repeated_feature_count = sum(
            1
            for pattern in recurrence.values()
            if isinstance(pattern, dict) and pattern.get("is_repeated")
        )

        profiles.append({
            "physical_point_id": f"throttle:{reference_event_id}",
            "reference_lap": reference_lap,
            "reference_event_id": reference_event_id,
            "reference_event": reference_event,
            "reference_event_snapshot_consistent": ref_consistent,
            "reference_event_snapshot_variant_count": ref_variant_count,
            "observed_comparison_count": len(observed_laps),
            "observed_comparison_laps": observed_laps,
            "comparison_event_ids": comparison_event_pairs,
            "episode_contexts": episode_contexts,
            "features": per_feature,
            "recurrence": recurrence,
            "repeated_observational_feature_count": repeated_feature_count,
            "has_repeated_observational_pattern": repeated_feature_count > 0,
            "observational_only": True,
            "affects_ranking": False,
            "affects_session_priority": False,
            "authorized_coaching": False,
        })

    profiles.sort(key=_profile_sort_key)

    return {
        "version": THROTTLE_PHYSICAL_POINT_PROFILE_VERSION,
        "schema_version": THROTTLE_PHYSICAL_POINT_PROFILE_SCHEMA_VERSION,
        "config": throttle_physical_point_profile_config_summary(),
        "comparison_count": len(comparisons),
        "physical_point_count": len(profiles),
        "comparison_only_sequence_event_observation_count": (
            comparison_only_sequence_count
        ),
        "unanchored_sustained_context_count": (
            unanchored_sustained_context_count
        ),
        "profiles": profiles,
        "policy": (
            "unification_only_no_redetection_no_ranking_"
            "no_session_priority_no_new_coaching"
        ),
    }


def enrich_analysis_with_throttle_physical_point_profiles(analysis_output):
    """Session-level in-place unification after recurrence enrichments."""
    if not isinstance(analysis_output, dict):
        return analysis_output

    analysis_output["throttle_physical_point_profiles"] = (
        build_throttle_physical_point_profiles(analysis_output)
    )
    return analysis_output
