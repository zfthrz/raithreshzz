from __future__ import annotations

import llm_analysis_deepseek as legacy
from deterministic_comparison_summary import (
    build_deterministic_comparison_summary,
)


def build(assessments, catalog):
    return build_deterministic_comparison_summary(
        assessments,
        catalog,
        validate_summary=legacy.validate_comparison_summary_llm_response,
    )


def test_summary_matches_legacy_for_priority_ordering():
    catalog = [
        {
            "episode_id": 1,
            "action_channels": ["brake"],
            "action_evidence_by_channel": {"brake": {}},
        },
        {
            "episode_id": 2,
            "action_channels": ["throttle"],
            "action_evidence_by_channel": {"throttle": {}},
        },
    ]
    assessments = [
        {
            "episode_id": 1,
            "classification": "SECUNDARIO",
            "interpretation": "frená más tarde",
            "recommendation": "frená más tarde",
        },
        {
            "episode_id": 2,
            "classification": "PRIORITARIO",
            "interpretation": "reaplicá acelerador más tarde",
            "recommendation": "reaplicá acelerador más tarde",
        },
    ]
    assert build(assessments, catalog) == (
        legacy.build_deterministic_comparison_summary(assessments, catalog)
    )


def test_summary_matches_legacy_for_missing_content():
    assert build([], []) == legacy.build_deterministic_comparison_summary([], [])
    assert build(None, []) is None


def test_summary_uses_only_validated_assessment_content():
    catalog = [
        {
            "episode_id": 1,
            "action_channels": ["brake"],
            "action_evidence_by_channel": {"brake": {}},
        }
    ]
    assessments = [
        {
            "episode_id": 1,
            "classification": "PRIORITARIO",
            "interpretation": "frená más tarde",
            "recommendation": "frená más tarde",
        }
    ]
    summary = build(assessments, catalog)
    assert summary == {
        "comparison_observations": ["frená más tarde"],
        "limitations": [],
        "conclusion": "frená más tarde",
    }
