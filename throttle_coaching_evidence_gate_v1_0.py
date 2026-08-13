import copy
import math
import statistics
from collections import Counter


THROTTLE_COACHING_EVIDENCE_GATE_VERSION = "1.0"
THROTTLE_COACHING_EVIDENCE_GATE_SCHEMA_VERSION = "1.0"
MIN_SUPPORT_COMPARISONS = 2

POINT_FEATURES = ("onset", "release")
HELD_OUT_FEATURES = (
    "full_throttle_attainment",
    "partial_lift",
    "sustained_throttle_modulation",
)


# ============================================================
# THROTTLE COACHING EVIDENCE GATE v1.0
# DETERMINISTIC / SESSION-LEVEL / SHADOW MODE
# ============================================================
#
# Purpose:
# - centralize whether already-authorized throttle point evidence is
#   sufficiently recurrent/consistent for future session-level coaching;
# - expose newer observational features as explicitly HELD OUT until they
#   pass multi-track validation and receive an explicit coaching contract.
#
# IMPORTANT:
# - This module does NOT detect telemetry facts.
# - This module does NOT alter driver_action_episodes, ranking or priorities.
# - This module does NOT mutate existing per-comparison coaching fields.
# - This module does NOT activate new coaching in v1.0.
# - Onset/release can become SHADOW_AUTHORIZED only when their source result
#   was already authorized by throttle_point_v1_2_1 in >=2 comparison laps,
#   with one coaching direction and no physical-profile conflict.
# - Full-throttle / partial-lift / sustained modulation remain HELD OUT.
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


def throttle_coaching_evidence_gate_config_summary():
    return {
        "enabled": True,
        "version": THROTTLE_COACHING_EVIDENCE_GATE_VERSION,
        "schema_version": THROTTLE_COACHING_EVIDENCE_GATE_SCHEMA_VERSION,
        "mode": "shadow_evaluation",
        "min_support_comparisons": MIN_SUPPORT_COMPARISONS,
        "point_features_evaluated": list(POINT_FEATURES),
        "held_out_features": list(HELD_OUT_FEATURES),
        "point_source_authorization_required": True,
        "point_consistent_coaching_direction_required": True,
        "opposite_authorized_direction_blocks": True,
        "duplicate_conflict_blocks": True,
        "reference_snapshot_conflict_blocks": True,
        "neutral_or_unavailable_observation_is_contradiction": False,
        "full_throttle_coaching_enabled": False,
        "partial_lift_coaching_enabled": False,
        "sustained_modulation_coaching_enabled": False,
        "activates_coaching": False,
        "mutates_existing_coaching": False,
        "affects_ranking": False,
        "affects_session_priority": False,
        "observational_shadow_gate": True,
    }


def _source_result(observation):
    result = observation.get("source_result")
    return result if isinstance(result, dict) else {}


def _valid_point_observations(profile, feature):
    features = profile.get("features")
    if not isinstance(features, dict):
        return []
    block = features.get(feature)
    if not isinstance(block, dict):
        return []
    rows = block.get("observations")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _profile_has_physical_conflict(profile, feature):
    if profile.get("reference_event_snapshot_consistent") is False:
        return True, "reference_event_snapshot_conflict"

    rows = _valid_point_observations(profile, feature)
    if any(bool(row.get("duplicate_conflict")) for row in rows):
        return True, "duplicate_feature_assignment_conflict"

    return False, None


def _point_feature_gate(profile, feature):
    rows = _valid_point_observations(profile, feature)

    physical_conflict, conflict_reason = _profile_has_physical_conflict(
        profile,
        feature,
    )

    valid_rows = []
    source_authorized_rows = []
    neutral_rows = []
    unavailable_rows = []

    for row in rows:
        result = _source_result(row)
        status = result.get("status", row.get("status"))

        if status != "VALID":
            unavailable_rows.append(row)
            continue

        valid_rows.append(row)

        if bool(result.get("authorized_numeric_coaching")):
            coaching_direction = result.get("coaching_direction")
            if coaching_direction in ("earlier", "later"):
                source_authorized_rows.append(row)
                continue

        neutral_rows.append(row)

    direction_counts = Counter(
        _source_result(row).get("coaching_direction")
        for row in source_authorized_rows
    )
    direction_counts = Counter({
        direction: count
        for direction, count in direction_counts.items()
        if direction in ("earlier", "later")
    })

    support_direction = None
    support_count = 0
    if direction_counts:
        max_count = max(direction_counts.values())
        top = sorted(
            direction
            for direction, count in direction_counts.items()
            if count == max_count
        )
        if len(top) == 1:
            support_direction = top[0]
            support_count = max_count

    support_rows = [
        row
        for row in source_authorized_rows
        if _source_result(row).get("coaching_direction") == support_direction
    ] if support_direction else []

    support_laps = sorted({
        row.get("comparison_lap")
        for row in support_rows
        if row.get("comparison_lap") is not None
    })
    authorized_laps = sorted({
        row.get("comparison_lap")
        for row in source_authorized_rows
        if row.get("comparison_lap") is not None
    })
    valid_laps = sorted({
        row.get("comparison_lap")
        for row in valid_rows
        if row.get("comparison_lap") is not None
    })

    opposite_direction_present = len(direction_counts) > 1

    if physical_conflict:
        gate_status = "WITHHELD_PHYSICAL_CONFLICT"
        reason = conflict_reason
    elif opposite_direction_present:
        gate_status = "WITHHELD_MIXED_AUTHORIZED_DIRECTION"
        reason = "opposite_source_authorized_directions_present"
    elif len(support_laps) < MIN_SUPPORT_COMPARISONS:
        gate_status = "WITHHELD_INSUFFICIENT_REPEATED_SUPPORT"
        reason = "fewer_than_minimum_distinct_support_comparisons"
    elif support_direction is None:
        gate_status = "WITHHELD_NO_SOURCE_AUTHORIZED_DIRECTION"
        reason = "no_source_authorized_numeric_point_coaching"
    else:
        gate_status = "SHADOW_AUTHORIZED_EXISTING_POINT_COACHING"
        reason = "repeated_consistent_source_authorized_point_coaching"

    magnitudes = [
        _source_result(row).get("coaching_magnitude_m")
        for row in support_rows
    ]
    deltas = [
        _source_result(row).get("comparison_minus_reference_m")
        for row in support_rows
    ]

    magnitude_median = _median(magnitudes)
    if magnitude_median is not None:
        magnitude_median = int(round(magnitude_median))

    return {
        "feature": feature,
        "gate_status": gate_status,
        "reason": reason,
        "shadow_authorized": (
            gate_status == "SHADOW_AUTHORIZED_EXISTING_POINT_COACHING"
        ),
        "activates_coaching": False,
        "coaching_direction": (
            support_direction
            if gate_status == "SHADOW_AUTHORIZED_EXISTING_POINT_COACHING"
            else None
        ),
        "coaching_magnitude_median_m": (
            magnitude_median
            if gate_status == "SHADOW_AUTHORIZED_EXISTING_POINT_COACHING"
            else None
        ),
        "comparison_minus_reference_m_median": (
            _median(deltas)
            if gate_status == "SHADOW_AUTHORIZED_EXISTING_POINT_COACHING"
            else None
        ),
        "support_count": len(support_laps),
        "support_comparison_laps": support_laps,
        "source_authorized_observation_count": len(source_authorized_rows),
        "source_authorized_comparison_laps": authorized_laps,
        "valid_observation_count": len(valid_rows),
        "valid_comparison_laps": valid_laps,
        "neutral_valid_observation_count": len(neutral_rows),
        "unavailable_or_nonvalid_observation_count": len(unavailable_rows),
        "authorized_direction_counts": dict(sorted(direction_counts.items())),
        "physical_conflict": physical_conflict,
        "observational_shadow_gate": True,
        "affects_ranking": False,
        "affects_session_priority": False,
    }


def _held_out_feature_gate(profile, feature):
    recurrence = profile.get("recurrence")
    pattern = recurrence.get(feature) if isinstance(recurrence, dict) else None
    pattern = pattern if isinstance(pattern, dict) else None

    if pattern is None:
        gate_status = "HELD_OUT_NO_REPEATED_PATTERN"
        reason = "feature_has_no_attached_recurrence_pattern"
        repeated = False
    elif bool(pattern.get("is_repeated")):
        gate_status = "HELD_OUT_PENDING_MULTITRACK_VALIDATION"
        reason = "repeated_objective_pattern_not_yet_coaching_authorized"
        repeated = True
    else:
        gate_status = "HELD_OUT_NOT_REPEATED"
        reason = "objective_pattern_below_recurrence_threshold"
        repeated = False

    return {
        "feature": feature,
        "gate_status": gate_status,
        "reason": reason,
        "is_repeated_objective_pattern": repeated,
        "recurrence_status": (
            pattern.get("recurrence_status") if pattern else None
        ),
        "support_count": _safe_int(pattern.get("support_count")) if pattern else 0,
        "selected_direction": (
            pattern.get("selected_direction") if pattern else None
        ),
        "selected_state": (
            pattern.get("selected_state") if pattern else None
        ),
        "dominant_classification": (
            pattern.get("dominant_classification") if pattern else None
        ),
        "shadow_authorized": False,
        "activates_coaching": False,
        "requires_multitrack_validation": True,
        "requires_explicit_future_coaching_contract": True,
        "observational_shadow_gate": True,
        "affects_ranking": False,
        "affects_session_priority": False,
    }


def _profile_gate(profile):
    feature_gates = {
        feature: _point_feature_gate(profile, feature)
        for feature in POINT_FEATURES
    }
    feature_gates.update({
        feature: _held_out_feature_gate(profile, feature)
        for feature in HELD_OUT_FEATURES
    })

    authorized_features = [
        feature
        for feature in POINT_FEATURES
        if feature_gates[feature].get("shadow_authorized")
    ]
    held_out_repeated_features = [
        feature
        for feature in HELD_OUT_FEATURES
        if feature_gates[feature].get("gate_status")
        == "HELD_OUT_PENDING_MULTITRACK_VALIDATION"
    ]

    return {
        "physical_point_id": profile.get("physical_point_id"),
        "reference_lap": profile.get("reference_lap"),
        "reference_event_id": profile.get("reference_event_id"),
        "shadow_authorized_existing_point_feature_count": len(
            authorized_features
        ),
        "shadow_authorized_existing_point_features": authorized_features,
        "held_out_repeated_feature_count": len(held_out_repeated_features),
        "held_out_repeated_features": held_out_repeated_features,
        "feature_gates": feature_gates,
        "activates_coaching": False,
        "affects_ranking": False,
        "affects_session_priority": False,
    }


def build_throttle_coaching_evidence_gate(analysis_output):
    if not isinstance(analysis_output, dict):
        analysis_output = {}

    profile_block = analysis_output.get("throttle_physical_point_profiles")
    if not isinstance(profile_block, dict):
        profiles = []
    else:
        profiles = profile_block.get("profiles")
        profiles = profiles if isinstance(profiles, list) else []

    gated_profiles = [
        _profile_gate(profile)
        for profile in profiles
        if isinstance(profile, dict)
    ]

    return {
        "version": THROTTLE_COACHING_EVIDENCE_GATE_VERSION,
        "schema_version": THROTTLE_COACHING_EVIDENCE_GATE_SCHEMA_VERSION,
        "config": throttle_coaching_evidence_gate_config_summary(),
        "physical_point_count": len(gated_profiles),
        "shadow_authorized_physical_point_count": sum(
            1
            for profile in gated_profiles
            if profile.get("shadow_authorized_existing_point_feature_count", 0) > 0
        ),
        "shadow_authorized_feature_count": sum(
            profile.get("shadow_authorized_existing_point_feature_count", 0)
            for profile in gated_profiles
        ),
        "held_out_repeated_feature_count": sum(
            profile.get("held_out_repeated_feature_count", 0)
            for profile in gated_profiles
        ),
        "profiles": gated_profiles,
        "policy": (
            "shadow_gate_only_existing_onset_release_source_authorization_"
            "new_observational_features_held_out_pending_multitrack_validation"
        ),
    }


def enrich_analysis_with_throttle_coaching_evidence_gate(analysis_output):
    """Session-level shadow gate after physical point profiles are built."""
    if not isinstance(analysis_output, dict):
        return analysis_output

    analysis_output["throttle_coaching_evidence_gate"] = (
        build_throttle_coaching_evidence_gate(analysis_output)
    )
    return analysis_output
