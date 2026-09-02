from __future__ import annotations

import pytest

import llm_analysis_deepseek as legacy
from deterministic_summary_validation import validate_comparison_summary_response


CATALOG = [
    {
        "episode_id": 1,
        "action_channels": ["brake", "steering_magnitude"],
        "concurrent_speed_events": [{"direction": "lower_in_comparison_lap"}],
        "action_evidence_by_channel": {
            "steering_magnitude": {
                "events": [{"direction": "higher_in_comparison_lap"}]
            }
        },
    }
]


@pytest.mark.parametrize(
    "response",
    [
        {
            "comparison_observations": ["La velocidad fue menor junto al freno."],
            "limitations": [],
            "conclusion": "Reducí el freno hacia la referencia.",
        },
        {
            "comparison_observations": ["El motor causó la pérdida en curva dos."],
            "limitations": ["Falta conocer la temperatura."],
            "conclusion": "Aumentá la velocidad hacia la vuelta comparada.",
        },
        {"comparison_observations": [], "conclusion": "Replicá el freno."},
        {
            "comparison_observations": "no es lista",
            "limitations": [3],
            "conclusion": None,
            "extra": True,
        },
        {
            "comparison_observations": [],
            "limitations": [],
            "conclusion": "Aumentá el volante hacia la referencia.",
        },
    ],
)
def test_neutral_summary_validator_matches_legacy_contract(response):
    assert validate_comparison_summary_response(response, CATALOG) == (
        legacy.validate_comparison_summary_llm_response(response, CATALOG)
    )


def test_runtime_summary_stage_bypasses_legacy_summary_validator(monkeypatch):
    monkeypatch.setattr(
        legacy,
        "validate_comparison_summary_llm_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy summary validator reached")
        ),
    )
    response = legacy.build_deterministic_summary_response(
        [
            {
                "episode_id": 1,
                "classification": "PRIORITARIO",
                "interpretation": "El freno fue mayor.",
                "recommendation": "Reducí el freno hacia la referencia.",
            }
        ],
        CATALOG,
        build_summary=lambda assessments, catalog: legacy.build_neutral_comparison_summary(
            assessments,
            catalog,
            validate_summary=legacy.validate_neutral_comparison_summary_response,
        ),
    )
    assert response["status"] == "VALID"
    assert response["response"]["conclusion"] == "Reducí el freno hacia la referencia."
