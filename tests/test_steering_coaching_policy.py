from copy import deepcopy

from steering_coaching_policy import attach_repeated_steering_secondary
from coaching_precision import enrich_cues_with_deterministic_priority


def _candidate():
    return {
        "status": "REPEATED_DIRECTION_CANDIDATE",
        "start_distance_m": 100.0,
        "end_distance_m": 150.0,
        "python_direction": "higher_in_comparison_lap",
        "action_toward_reference": "reduce_steering_magnitude_toward_reference",
        "comparison_count": 3,
    }


def _plan(cues=None):
    return [{
        "plan_label": "A",
        "start_distance_m": 110.0,
        "end_distance_m": 140.0,
        "driver_cues": list(cues or []),
        "actionable_cue_count": len(cues or []),
    }]


def test_repeated_steering_uses_free_secondary_slot():
    plan = _plan([{
        "channel": "brake",
        "kind": "spatial_points",
        "text": "frená",
    }])

    result = attach_repeated_steering_secondary(plan, _candidate())

    assert result["status"] == "AUTHORIZED_SECONDARY"
    assert result["ranking_changed"] is False
    assert result["existing_cue_displaced"] is False
    assert [cue["channel"] for cue in plan[0]["driver_cues"]] == [
        "brake",
        "steering_magnitude",
    ]
    steering = plan[0]["driver_cues"][1]
    assert steering["kind"] == "repeated_steering_secondary"
    assert steering["secondary_only"] is True
    assert steering["causal_claim"] is False
    assert plan[0]["actionable_cue_count"] == 2

    enriched = enrich_cues_with_deterministic_priority(plan[0]["driver_cues"])
    assert enriched[-1]["kind"] == "repeated_steering_secondary"
    assert enriched[-1]["_p8_priority_rank"] == 5


def test_steering_does_not_displace_two_stronger_cues():
    cues = [
        {"channel": "brake", "text": "frená"},
        {"channel": "throttle", "text": "acelerá"},
    ]
    plan = _plan(cues)
    original = deepcopy(plan)

    result = attach_repeated_steering_secondary(plan, _candidate())

    assert result["status"] == "WITHHELD"
    assert result["reason_code"] == "stronger_cues_fill_zone_limit"
    assert plan == original


def test_steering_does_not_create_a_new_plan_zone():
    plan = _plan()
    candidate = _candidate()
    candidate["start_distance_m"] = 500.0
    candidate["end_distance_m"] = 550.0
    original = deepcopy(plan)

    result = attach_repeated_steering_secondary(plan, candidate)

    assert result["status"] == "WITHHELD"
    assert result["reason_code"] == "no_existing_plan_zone_overlap"
    assert plan == original


def test_steering_cannot_be_the_only_cue_in_an_existing_zone():
    plan = _plan()
    original = deepcopy(plan)

    result = attach_repeated_steering_secondary(plan, _candidate())

    assert result["status"] == "WITHHELD"
    assert result["reason_code"] == "no_stronger_primary_cue"
    assert plan == original


def test_ambiguous_shadow_candidate_fails_closed():
    plan = _plan()
    candidate = _candidate()
    candidate["status"] = "WITHHELD"

    result = attach_repeated_steering_secondary(plan, candidate)

    assert result["status"] == "WITHHELD"
    assert result["plan_mutated"] is False
    assert plan[0]["driver_cues"] == []
