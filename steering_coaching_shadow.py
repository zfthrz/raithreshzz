"""Deterministic, observational steering coaching candidates.

This module deliberately does not authorize driver-facing coaching.  It turns
the already-selected Python priority findings into inspectable steering facts
without consulting or parsing LLM text.
"""

from __future__ import annotations

from typing import Any


STEERING_COACHING_SHADOW_VERSION = "0.1"

_SUPPORTED_DIRECTIONS = {
    "higher_in_comparison_lap": "reduce_steering_magnitude_toward_reference",
    "lower_in_comparison_lap": "increase_steering_magnitude_toward_reference",
}


def _steering_channel(finding: dict[str, Any]) -> dict[str, Any] | None:
    for channel in finding.get("channels", []) or []:
        if (
            isinstance(channel, dict)
            and channel.get("channel") == "steering_magnitude"
        ):
            return channel
    return None


def build_steering_coaching_shadow(
    priority_findings: list[dict[str, Any]],
    recurrence_regions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build fail-closed steering observations without mutating findings."""
    observations = []

    for finding in priority_findings or []:
        if not isinstance(finding, dict):
            continue
        channel = _steering_channel(finding)
        if channel is None:
            continue

        start = finding.get("start_distance_m")
        end = finding.get("end_distance_m")
        direction = channel.get("direction")
        reason_codes = []

        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            reason_codes.append("missing_physical_interval")
        elif end < start:
            reason_codes.append("invalid_physical_interval")
        if direction not in _SUPPORTED_DIRECTIONS:
            reason_codes.append("non_unambiguous_python_direction")

        observed = not reason_codes
        observations.append({
            "status": "OBSERVED_DIRECTION" if observed else "WITHHELD",
            "comparison": finding.get("comparison"),
            "episode_id": finding.get("episode_id"),
            "start_distance_m": start,
            "end_distance_m": end,
            "track_location": finding.get("track_location"),
            "python_direction": direction,
            "action_toward_reference": (
                _SUPPORTED_DIRECTIONS.get(direction) if observed else None
            ),
            "evidence_strength": finding.get("evidence_strength"),
            "quantitative": channel.get("quantitative"),
            "reason_codes": reason_codes,
            "llm_requested_steering": bool(
                finding.get("steering_coaching_requested")
            ),
            "observational_only": True,
            "affects_next_stint_plan": False,
            "steering_action_authorized": False,
        })

    repeated_candidates = []
    for region_index, region in enumerate(recurrence_regions or []):
        if not isinstance(region, dict):
            continue
        for difference in region.get("repeated_differences", []) or []:
            if (
                not isinstance(difference, dict)
                or difference.get("channel") != "steering_magnitude"
            ):
                continue
            direction = difference.get("direction")
            action = _SUPPORTED_DIRECTIONS.get(direction)
            reason_codes = []
            if action is None:
                reason_codes.append("contradictory_or_ambiguous_recurrence")
            repeated_candidates.append({
                "status": (
                    "REPEATED_DIRECTION_CANDIDATE"
                    if action is not None
                    else "WITHHELD"
                ),
                "region_index": region_index,
                "start_distance_m": region.get("start_distance_m"),
                "end_distance_m": region.get("end_distance_m"),
                "track_location": region.get("track_location"),
                "comparisons": list(region.get("comparisons", []) or []),
                "comparison_count": difference.get("comparison_count"),
                "recurrence_episode_count": difference.get(
                    "recurrence_episode_count"
                ),
                "python_direction": direction,
                "action_toward_reference": action,
                "reason_codes": reason_codes,
                "selection_basis": "existing_recurrence_region_exact_direction",
                "observational_only": True,
                "affects_next_stint_plan": False,
                "steering_action_authorized": False,
            })

    selected_secondary_candidate = next(
        (
            dict(item)
            for item in repeated_candidates
            if item["status"] == "REPEATED_DIRECTION_CANDIDATE"
        ),
        None,
    )
    if selected_secondary_candidate is not None:
        selected_secondary_candidate["selection_scope"] = (
            "at_most_one_secondary_candidate_per_session"
        )

    return {
        "version": STEERING_COACHING_SHADOW_VERSION,
        "status": "SHADOW_OBSERVATIONAL_ONLY",
        "source": "python_priority_findings",
        "llm_called": False,
        "next_stint_plan_mutated": False,
        "steering_actions_authorized": False,
        "observation_count": len(observations),
        "observed_direction_count": sum(
            item["status"] == "OBSERVED_DIRECTION" for item in observations
        ),
        "withheld_count": sum(
            item["status"] == "WITHHELD" for item in observations
        ),
        "observations": observations,
        "repeated_candidate_count": sum(
            item["status"] == "REPEATED_DIRECTION_CANDIDATE"
            for item in repeated_candidates
        ),
        "repeated_withheld_count": sum(
            item["status"] == "WITHHELD" for item in repeated_candidates
        ),
        "repeated_candidates": repeated_candidates,
        "selected_secondary_candidate": selected_secondary_candidate,
    }
