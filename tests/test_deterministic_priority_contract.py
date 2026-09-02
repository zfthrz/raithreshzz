from __future__ import annotations

import copy

import llm_analysis_deepseek as legacy
from deterministic_priority_contract import (
    apply_priority_classifications,
    derive_priority_classifications,
    validate_priority_ranker_response,
)


CATALOG = [
    {"episode_id": 10},
    {"episode_id": 20},
    {"episode_id": 30},
]
RESPONSE = {
    "ordered_episode_ids": [20, 10, 30],
    "priority_cut_rank": 1,
    "no_actionable_start_rank": 3,
}


def test_priority_contract_matches_legacy_exactly():
    assert validate_priority_ranker_response(RESPONSE, CATALOG) == (
        legacy.validate_comparison_ranker_response(RESPONSE, CATALOG)
    )
    assert derive_priority_classifications(RESPONSE, CATALOG) == (
        legacy.derive_priority_classifications(RESPONSE, CATALOG)
    )


def test_priority_application_matches_legacy_without_mutating_assessments():
    assessments = [
        {"episode_id": 10, "interpretation": "A"},
        {"episode_id": 20, "interpretation": "B"},
        {"episode_id": 30, "interpretation": "C"},
    ]
    original = copy.deepcopy(assessments)
    assert apply_priority_classifications(assessments, CATALOG, RESPONSE) == (
        legacy.apply_priority_classifications(assessments, CATALOG, RESPONSE)
    )
    assert assessments == original


def test_priority_validator_preserves_fail_closed_errors():
    invalid = {
        "ordered_episode_ids": [10, 10, 99],
        "priority_cut_rank": 3,
        "no_actionable_start_rank": 1,
    }
    assert validate_priority_ranker_response(invalid, CATALOG) == (
        legacy.validate_comparison_ranker_response(invalid, CATALOG)
    )
    assert validate_priority_ranker_response(invalid, CATALOG)
