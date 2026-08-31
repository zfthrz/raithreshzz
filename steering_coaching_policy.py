"""Conservative production policy for repeated steering coaching."""

from __future__ import annotations

from typing import Any


STEERING_COACHING_POLICY_VERSION = "1.0"

_TEXT_BY_ACTION = {
    "reduce_steering_magnitude_toward_reference": (
        "reducí la magnitud del volante hacia la referencia"
    ),
    "increase_steering_magnitude_toward_reference": (
        "aumentá la magnitud del volante hacia la referencia"
    ),
}


def _overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    values = (
        left.get("start_distance_m"),
        left.get("end_distance_m"),
        right.get("start_distance_m"),
        right.get("end_distance_m"),
    )
    if not all(isinstance(value, (int, float)) for value in values):
        return False
    left_start, left_end, right_start, right_end = values
    return min(left_end, right_end) >= max(left_start, right_start)


def attach_repeated_steering_secondary(
    next_stint_plan: list[dict[str, Any]],
    candidate: dict[str, Any] | None,
    *,
    max_cues: int = 2,
) -> dict[str, Any]:
    """Append steering only to an existing zone with a free secondary slot."""
    base = {
        "version": STEERING_COACHING_POLICY_VERSION,
        "status": "NOT_APPLICABLE",
        "plan_mutated": False,
        "ranking_changed": False,
        "existing_cue_displaced": False,
        "reason_code": None,
    }
    if not isinstance(candidate, dict):
        base["reason_code"] = "no_repeated_candidate"
        return base
    if candidate.get("status") != "REPEATED_DIRECTION_CANDIDATE":
        base["status"] = "WITHHELD"
        base["reason_code"] = "candidate_not_authorized_for_promotion"
        return base

    action = candidate.get("action_toward_reference")
    text = _TEXT_BY_ACTION.get(action)
    if text is None:
        base["status"] = "WITHHELD"
        base["reason_code"] = "unsupported_action"
        return base

    overlapping = [
        item
        for item in next_stint_plan or []
        if isinstance(item, dict) and _overlaps(item, candidate)
    ]
    if not overlapping:
        base["status"] = "WITHHELD"
        base["reason_code"] = "no_existing_plan_zone_overlap"
        return base

    target = next(
        (
            item
            for item in overlapping
            if len(item.get("driver_cues", []) or []) < max_cues
        ),
        None,
    )
    if target is None:
        base["status"] = "WITHHELD"
        base["reason_code"] = "stronger_cues_fill_zone_limit"
        return base

    cues = target.setdefault("driver_cues", [])
    cues.append({
        "channel": "steering_magnitude",
        "kind": "repeated_steering_secondary",
        "text": text,
        "source": "deterministic_repeated_steering_recurrence",
        "point_comparison_count": 0,
        "region_comparison_count": candidate.get("comparison_count") or 0,
        "secondary_only": True,
        "causal_claim": False,
    })
    target["actionable_cue_count"] = len(cues)
    target["steering_direction"] = candidate.get("python_direction")

    return {
        **base,
        "status": "AUTHORIZED_SECONDARY",
        "plan_mutated": True,
        "reason_code": "repeated_direction_existing_zone_free_slot",
        "plan_label": target.get("plan_label"),
        "python_direction": candidate.get("python_direction"),
        "comparison_count": candidate.get("comparison_count"),
    }
