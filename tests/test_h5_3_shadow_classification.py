from __future__ import annotations

import copy

from audit_h5_3_real_sessions import classify_historical_action_vs_p11


def _action(
    *,
    candidate_id: str = "candidate_1",
    location: str = "T5 Variante",
    actions: list[str] | None = None,
    observation_codes: list[str] | None = None,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "location_label": location,
        "actions": actions or [],
        "authorization": {"observation_codes": observation_codes or []},
    }


def _p11(
    *,
    location: str = "T5 Variante",
    actions: list[str] | None = None,
    cues: list[str] | None = None,
    channels: list[str] | None = None,
) -> dict:
    return {
        "location_label": location,
        "actions": actions or [],
        "driver_cues": cues or [],
        "channels": channels or [],
    }


def test_shadow_classifies_matching_historical_signal_as_support_without_authority():
    result = classify_historical_action_vs_p11(
        _action(actions=["increase_brake"]),
        [_p11(actions=["increase_brake"])],
        [],
    )

    assert result["classification"] == "SUPPORTS_CURRENT"
    assert set(result) == {"classification", "rationale"}


def test_shadow_classifies_repeated_cue_as_duplicate_without_new_action():
    result = classify_historical_action_vs_p11(
        _action(actions=["increase_brake"]),
        [_p11(cues=["increase_brake"])],
        [],
    )

    assert result["classification"] == "DUPLICATES_CURRENT"
    assert "duplicates" in result["rationale"]


def test_shadow_classifies_opposite_action_as_conflict_without_replacing_current():
    result = classify_historical_action_vs_p11(
        _action(actions=["increase_brake"]),
        [_p11(actions=["reduce_brake"])],
        [],
    )

    assert result["classification"] == "CONFLICTS_WITH_CURRENT"
    assert "increase_brake" in result["rationale"]
    assert "reduce_brake" in result["rationale"]


def test_shadow_classifies_consistent_channel_evidence_as_support():
    result = classify_historical_action_vs_p11(
        _action(actions=["increase_throttle"]),
        [_p11(cues=["aumentar el acelerador"])],
        [],
    )

    assert result["classification"] == "DUPLICATES_CURRENT"


def test_shadow_classifies_consistent_additional_channel_as_support():
    result = classify_historical_action_vs_p11(
        _action(actions=["increase_brake", "increase_throttle"]),
        [_p11(cues=["aumentar el freno"])],
        [],
    )

    assert result["classification"] == "SUPPORTS_CURRENT"


def test_shadow_classifies_unmatched_location_as_low_value():
    result = classify_historical_action_vs_p11(
        _action(location="T2 Tamburello", actions=["increase_brake"]),
        [_p11(location="T5 Variante", actions=["increase_brake"])],
        [],
    )

    assert result["classification"] == "LOW_VALUE"


def test_shadow_classifies_different_location_as_low_value_not_new_coaching():
    historical = _action(location="T2 Tamburello", actions=["increase_brake"])
    p11 = [_p11(location="T5 Variante", actions=["reduce_throttle"])]

    result = classify_historical_action_vs_p11(historical, p11, [])

    assert result["classification"] == "LOW_VALUE"
    assert "actions" not in result
    assert "next_stint_plan" not in result


def test_speed_only_historical_observation_does_not_become_a_driving_action():
    result = classify_historical_action_vs_p11(
        _action(
            location="T5 Variante",
            actions=[],
            observation_codes=["speed_higher_than_current"],
        ),
        [_p11(location="T5 Variante", cues=["frenar más tarde"])],
        [],
    )

    assert result["classification"] == "SUPPORTS_CURRENT"
    assert "actions" not in result
    assert "increase_speed" not in result["rationale"]
    assert "km/h" not in result["rationale"]


def test_shadow_requires_p11_and_fails_closed_when_unavailable():
    result = classify_historical_action_vs_p11(
        _action(actions=["increase_brake"]),
        [],
        [],
    )

    assert result == {
        "classification": "P11_UNAVAILABLE",
        "rationale": "P11 status is not ACTIVE or no focus items available",
    }


def test_shadow_classification_is_deterministic_and_action_order_independent():
    historical = _action(actions=["increase_brake", "reduce_throttle"])
    p11 = [_p11(cues=["aumentar el freno", "reducir el acelerador"])]

    first = classify_historical_action_vs_p11(historical, p11, [])
    second = classify_historical_action_vs_p11(
        _action(actions=["reduce_throttle", "increase_brake"]),
        p11,
        [],
    )

    assert first == second


def test_shadow_classification_does_not_mutate_authorized_plan_or_add_actions():
    plan = {
        "next_stint_plan": [
            {"label": "A", "actions": ["increase_brake"]},
        ],
        "historical_actions_authorized": False,
    }
    before = copy.deepcopy(plan)

    result = classify_historical_action_vs_p11(
        _action(actions=["reduce_brake"]),
        [_p11(actions=["increase_brake"])],
        plan["next_stint_plan"],
    )

    assert result["classification"] == "CONFLICTS_WITH_CURRENT"
    assert plan == before
    assert plan["historical_actions_authorized"] is False
    assert result.get("actions") is None


def test_shadow_provenance_rationale_uses_existing_location_and_action_ids_only():
    result = classify_historical_action_vs_p11(
        _action(candidate_id="candidate_authorized", actions=["increase_brake"]),
        [_p11(location="T5 Variante", actions=["increase_brake"])],
        [],
    )

    assert result["classification"] == "SUPPORTS_CURRENT"
    assert "candidate_authorized" not in result["rationale"]
    assert "T5 Variante" in result["rationale"]
    assert "increase_brake" in result["rationale"]


def test_shadow_unknown_action_id_is_not_promoted_to_coaching():
    result = classify_historical_action_vs_p11(
        _action(actions=["invented_action"]),
        [_p11(location="T5 Variante", cues=["frenar más tarde"])],
        [],
    )

    assert result["classification"] in {"LOW_VALUE", "USEFUL_SECONDARY_CONTEXT", "AMBIGUOUS"}
    assert "invented_action" in result["rationale"]
    assert "increase_speed" not in result["rationale"]
