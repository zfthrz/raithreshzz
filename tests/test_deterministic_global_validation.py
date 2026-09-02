import pytest

import llm_analysis_deepseek as legacy
from deterministic_global_validation import validate_temporal_observation_not_action_target


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
