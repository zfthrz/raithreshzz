from __future__ import annotations

import copy

import pytest

import llm_analysis_deepseek as legacy
from deterministic_comparison_validation import validate_comparison_response


CATALOG = [{
    "episode_id": 1,
    "action_channels": ["brake"],
    "action_evidence_by_channel": {
        "brake": {"events": [{"direction": "higher_in_comparison_lap"}]}
    },
}]
VALID = {
    "episode_assessments": [{
        "episode_id": 1,
        "classification": "PRIORITARIO",
        "interpretation": "El freno fue mayor.",
        "hypotheses": [],
        "recommendation": "Reducí el freno hacia la referencia.",
    }],
    "comparison_observations": ["El freno fue mayor."],
    "limitations": [],
    "conclusion": "Reducí el freno hacia la referencia.",
}


@pytest.mark.parametrize("mutation", [
    lambda value: value,
    lambda value: value.update(extra=True) or value,
    lambda value: value.update(episode_assessments="bad") or value,
    lambda value: value["episode_assessments"][0].update(episode_id=2) or value,
    lambda value: value["episode_assessments"][0].update(classification="OTHER") or value,
    lambda value: value["episode_assessments"][0].update(recommendation="Usá el motor en curva dos.") or value,
])
def test_neutral_comparison_validator_matches_legacy(mutation):
    response = mutation(copy.deepcopy(VALID))
    assert validate_comparison_response(response, CATALOG) == (
        legacy.validate_comparison_llm_response(response, CATALOG)
    )


def test_runtime_comparison_bypasses_legacy_comparison_validator(monkeypatch):
    monkeypatch.setattr(
        legacy,
        "validate_comparison_llm_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy comparison validator reached")
        ),
    )
    assert legacy.validate_neutral_comparison_response(VALID, CATALOG) == []
