from __future__ import annotations

from audit_h5_3_real_sessions import classify_historical_action_vs_p11


def _historical(
    *,
    location: str = "T5 Variante",
    actions: list[str] | None = None,
    candidate_id: str = "candidate_1",
) -> dict:
    return {
        "candidate_id": candidate_id,
        "location_label": location,
        "actions": actions or [],
        "authorization": {"observation_codes": []},
    }


def _focus(
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


def test_exact_same_action_without_repeated_cue_supports_current():
    result = classify_historical_action_vs_p11(
        _historical(actions=["increase_brake"]),
        [_focus(actions=["increase_brake"])],
        [],
    )

    assert result["classification"] == "SUPPORTS_CURRENT"


def test_exact_same_action_and_repeated_cue_is_duplicate_not_support():
    result = classify_historical_action_vs_p11(
        _historical(actions=["increase_brake"]),
        [_focus(actions=["increase_brake"], cues=["increase_brake"])],
        [],
    )

    assert result["classification"] == "DUPLICATES_CURRENT"


def test_conflict_wins_over_superficial_matching_cue():
    result = classify_historical_action_vs_p11(
        _historical(actions=["increase_brake"]),
        [_focus(actions=["reduce_brake"], cues=["increase_brake"])],
        [],
    )

    assert result["classification"] == "CONFLICTS_WITH_CURRENT"


def test_compatible_different_actions_do_not_become_duplicate_or_support():
    result = classify_historical_action_vs_p11(
        _historical(actions=["increase_brake"]),
        [_focus(actions=["increase_throttle"], cues=["increase_brake"])],
        [],
    )

    assert result["classification"] not in {"DUPLICATES_CURRENT", "SUPPORTS_CURRENT"}


def test_exact_same_action_without_cue_is_support():
    result = classify_historical_action_vs_p11(
        _historical(actions=["increase_brake"]),
        [_focus(actions=["increase_brake"], cues=[])],
        [],
    )

    assert result["classification"] == "SUPPORTS_CURRENT"


def test_empty_actions_never_support_or_duplicate():
    result = classify_historical_action_vs_p11(
        _historical(actions=[]),
        [_focus(actions=[], cues=[])],
        [],
    )

    assert result["classification"] not in {"SUPPORTS_CURRENT", "DUPLICATES_CURRENT"}


def test_same_location_unrelated_action_does_not_become_support():
    result = classify_historical_action_vs_p11(
        _historical(actions=["increase_throttle"]),
        [_focus(actions=["increase_brake"], cues=["frenar más tarde"])],
        [],
    )

    assert result["classification"] != "SUPPORTS_CURRENT"
    assert result["classification"] in {"USEFUL_SECONDARY_CONTEXT", "CONFLICTS_WITH_CURRENT", "AMBIGUOUS"}


def test_same_location_unknown_action_does_not_become_support():
    result = classify_historical_action_vs_p11(
        _historical(actions=["invented_action"]),
        [_focus(cues=["frenar más tarde"])],
        [],
    )

    assert result["classification"] != "SUPPORTS_CURRENT"


def test_speed_only_same_location_does_not_become_support():
    result = classify_historical_action_vs_p11(
        _historical(),
        [_focus(cues=["frenar más tarde"])],
        [],
    )

    assert result["classification"] != "SUPPORTS_CURRENT"
    assert result["classification"] in {"LOW_VALUE", "USEFUL_SECONDARY_CONTEXT", "AMBIGUOUS"}


def test_opposite_action_wins_over_any_surface_location_match():
    result = classify_historical_action_vs_p11(
        _historical(actions=["increase_brake"]),
        [_focus(actions=["reduce_brake"], cues=["aumentar el freno"])],
        [],
    )

    assert result["classification"] == "CONFLICTS_WITH_CURRENT"


def test_different_location_is_not_equivalent_by_nearby_distance_or_zone_text():
    result = classify_historical_action_vs_p11(
        _historical(location="T5 Variante", actions=["increase_brake"]),
        [_focus(location="T6 Variante", actions=["increase_brake"])],
        [],
    )

    assert result["classification"] == "LOW_VALUE"


def test_unknown_location_fails_closed_without_support():
    result = classify_historical_action_vs_p11(
        _historical(location="", actions=["increase_brake"]),
        [_focus(location="T5 Variante", actions=["increase_brake"])],
        [],
    )

    assert result["classification"] != "SUPPORTS_CURRENT"


def test_support_and_duplicate_are_deterministic_for_same_input():
    historical = _historical(actions=["increase_brake", "increase_throttle"])
    focus = [_focus(cues=["aumentar el freno"])]

    first = classify_historical_action_vs_p11(historical, focus, [])
    second = classify_historical_action_vs_p11(historical, focus, [])

    assert first == second
    assert first["classification"] == "SUPPORTS_CURRENT"
