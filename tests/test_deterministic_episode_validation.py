from __future__ import annotations

import pytest

import llm_analysis_deepseek as legacy
from deterministic_episode_validation import validate_single_episode_response


EPISODE = {
    "episode_id": 7,
    "action_channels": ["brake", "steering_magnitude"],
    "concurrent_speed_events": [{"direction": "lower_in_comparison_lap"}],
    "action_evidence_by_channel": {
        "brake": {"events": [{"direction": "higher_in_comparison_lap"}]},
        "steering_magnitude": {
            "events": [{"direction": "lower_in_comparison_lap"}]
        },
    },
}


@pytest.mark.parametrize(
    "response",
    [
        {
            "episode_id": 7,
            "interpretation": "El freno fue mayor respecto de la referencia.",
            "hypotheses": [],
            "recommendation": "Reducí el freno hacia la referencia.",
        },
        {
            "episode_id": 8,
            "interpretation": "El freno fue menor en curva dos.",
            "hypotheses": ["La temperatura causó la pérdida."],
            "recommendation": "Aumentá el freno y la velocidad hacia la vuelta comparada.",
        },
        {"episode_id": 7, "interpretation": "Freno mayor."},
        {
            "episode_id": "7",
            "interpretation": None,
            "hypotheses": "ninguna",
            "recommendation": 3,
            "extra": True,
        },
        {
            "episode_id": 7,
            "interpretation": "La dirección fue menor.",
            "hypotheses": [],
            "recommendation": "Aumentá el volante hacia la referencia.",
        },
    ],
)
def test_neutral_episode_validator_matches_legacy_contract(response):
    assert validate_single_episode_response(response, EPISODE) == (
        legacy.validate_single_episode_llm_response(response, EPISODE)
    )


def test_runtime_episode_provider_bypasses_legacy_validator(monkeypatch):
    monkeypatch.setattr(
        legacy,
        "validate_single_episode_llm_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy episode validator reached")
        ),
    )
    result = legacy.build_deterministic_episode_response(
        EPISODE,
        build_fallback=legacy.build_grounded_episode_response,
        validate_response=legacy.validate_neutral_single_episode_response,
        emit=lambda message: None,
    )
    assert result["status"] == "VALID"
    assert result["response"]["episode_id"] == 7
