import pytest

import llm_analysis_deepseek as legacy
from deterministic_global_validation import (
    validate_global_direction_consistency,
    validate_global_response,
    validate_global_secondary_steering_text,
    validate_global_zone_list_consistency,
    validate_temporal_observation_not_action_target,
)


@pytest.mark.parametrize("text,plan", [
    ("Zona A: separá freno y acelerador.", [{"plan_label": "A"}]),
    ("Zona A: separá freno y acelerador.", [{"plan_label": "A", "temporal_target": {"kind": "x"}}]),
    ("Zona A: reducí el freno.", [{"plan_label": "A"}]),
])
def test_temporal_guard_matches_legacy(text, plan):
    neutral_errors = []
    legacy_errors = []
    validate_temporal_observation_not_action_target(text, "field", plan, neutral_errors)
    legacy.validate_temporal_observation_not_action_target(text, "field", plan, legacy_errors)
    assert neutral_errors == legacy_errors


@pytest.mark.parametrize("text,cues,expected_valid", [
    ("Zona A: aumentá el volante.", [{"channel": "steering_magnitude"}], True),
    ("Zona A: reducí el volante.", [{"channel": "steering_magnitude"}], False),
    ("Zona A: aumentá el volante.", [], False),
    ("Aumentá el volante.", [{"channel": "steering_magnitude"}], False),
])
def test_global_steering_guard_matches_legacy(text, cues, expected_valid):
    plan = [{"plan_label": "A", "observed_differences": ["dirección menor"], "driver_cues": cues}]
    neutral_errors = []
    legacy_errors = []
    validate_global_secondary_steering_text(text, "field", plan, neutral_errors)
    legacy.validate_global_secondary_steering_text(text, "field", plan, legacy_errors)
    assert neutral_errors == legacy_errors
    assert (not neutral_errors) is expected_valid


def test_remaining_global_guards_match_legacy():
    plan = [{
        "plan_label": "A",
        "targets": ["reducir el freno"],
        "observed_differences": ["más freno"],
    }]
    response = {
        "opportunities": ["Zona A: aumentá el freno."],
        "repeated_observations": ["Zona A: hubo menos freno."],
        "hypotheses": [],
        "limitations": [],
        "conclusion": "Zona A: aumentá el freno.",
    }
    neutral_errors = []
    legacy_errors = []
    validate_global_zone_list_consistency(response, plan, neutral_errors)
    validate_global_direction_consistency(response, plan, neutral_errors)
    legacy.validate_global_zone_list_consistency(response, plan, legacy_errors)
    legacy.validate_global_direction_consistency(response, plan, legacy_errors)
    assert neutral_errors == legacy_errors


def test_complete_neutral_global_validator_is_runtime_contract():
    facts = {"next_stint_plan": [{
        "plan_label": "A",
        "targets": ["reducir el freno"],
        "observed_differences": ["más freno"],
    }]}
    comparisons = [{"episode_ground_truth": [{"action_channels": ["brake"]}]}]
    response = {
        "opportunities": ["Zona A: reducí el freno."],
        "repeated_observations": ["Zona A: hubo más freno."],
        "hypotheses": [],
        "limitations": [],
        "conclusion": "Zona A: reducí el freno.",
    }
    assert validate_global_response(response, comparisons, facts) == []
    assert legacy.validate_global_llm_response is validate_global_response
