from __future__ import annotations

from deterministic_comparison_responses import (
    build_episode_response,
    build_ranker_response,
    build_summary_response,
)


def test_episode_provider_is_deterministic_and_fail_closed():
    emitted = []
    result = build_episode_response(
        {"episode_id": 3},
        build_fallback=lambda episode: {"episode_id": episode["episode_id"]},
        validate_response=lambda response, episode: [],
        emit=emitted.append,
    )
    assert result["status"] == "VALID"
    assert result["attempts"] == 0
    assert result["deterministic_first"] is True
    assert emitted

    rejected = build_episode_response(
        {"episode_id": 3},
        build_fallback=lambda episode: None,
        validate_response=lambda response, episode: [],
    )
    assert rejected["status"] == "REJECTED"


def test_ranker_provider_validates_product_policy_without_transport():
    response = {
        "ordered_episode_ids": [1],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 2,
    }
    result = build_ranker_response(
        [{"episode_id": 1}],
        build_ranker=lambda catalog: response,
        validate_response=lambda value, catalog: [],
        emit=lambda message: None,
    )
    assert result["status"] == "VALID"
    assert result["ranker_source"] == "D2_9_PRODUCT_POLICY"


def test_summary_provider_preserves_deterministic_contract():
    summary = {
        "comparison_observations": [],
        "limitations": [],
        "conclusion": "ok",
    }
    result = build_summary_response(
        [],
        [],
        build_summary=lambda assessments, catalog: summary,
        emit=lambda message: None,
    )
    assert result["status"] == "VALID"
    assert result["response"] is summary
    assert build_summary_response(
        [], [], build_summary=lambda assessments, catalog: None
    )["status"] == "REJECTED"
