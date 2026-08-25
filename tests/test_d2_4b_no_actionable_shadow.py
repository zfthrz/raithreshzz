from __future__ import annotations

import importlib


MODULE_NAME = "llm_analysis_deepseek"


def _module():
    return importlib.import_module(MODULE_NAME)


def _episode(
    episode_id,
    *,
    global_rank,
    loss,
    evidence,
    channels=2,
    length_m=50.0,
):
    return {
        "episode_id": episode_id,
        "global_rank": global_rank,
        "action_time_loss_s": loss,
        "evidence_strength": evidence,
        "action_channel_count": channels,
        "length_m": length_m,
    }


def test_calibrated_no_actionable_uses_conditioned_tail():
    module = _module()
    episodes = [
        _episode(1, global_rank=1, loss=0.50, evidence="strong"),
        _episode(2, global_rank=2, loss=0.25, evidence="strong"),
        _episode(3, global_rank=3, loss=0.15, evidence="moderate"),
        _episode(4, global_rank=4, loss=0.04, evidence="weak"),
        _episode(5, global_rank=5, loss=0.03, evidence="weak"),
    ]

    start = module.build_calibrated_no_actionable_start_rank(
        episodes,
        [1, 2, 3, 4, 5],
        priority_cut_rank=2,
    )

    assert start == 4


def test_calibrated_no_actionable_stops_at_non_negligible_tail_item():
    module = _module()
    episodes = [
        _episode(1, global_rank=1, loss=0.50, evidence="strong"),
        _episode(2, global_rank=2, loss=0.25, evidence="strong"),
        _episode(3, global_rank=3, loss=0.08, evidence="weak"),
        _episode(4, global_rank=4, loss=0.03, evidence="weak"),
    ]

    start = module.build_calibrated_no_actionable_start_rank(
        episodes,
        [1, 2, 3, 4],
        priority_cut_rank=1,
    )

    assert start == 4


def test_calibrated_no_actionable_response_preserves_d2_3_order_and_cut():
    module = _module()
    episodes = [
        _episode(1, global_rank=1, loss=0.40, evidence="strong"),
        _episode(2, global_rank=2, loss=0.20, evidence="strong"),
        _episode(3, global_rank=3, loss=0.03, evidence="weak"),
        _episode(4, global_rank=4, loss=0.02, evidence="weak"),
    ]
    calibrated_priority = (
        module.build_calibrated_comparison_ranker_response(
            episodes
        )
    )

    response = (
        module.build_calibrated_no_actionable_comparison_ranker_response(
            episodes,
            calibrated_priority_response=calibrated_priority,
        )
    )

    assert (
        response["ordered_episode_ids"]
        == calibrated_priority["ordered_episode_ids"]
    )
    assert (
        response["priority_cut_rank"]
        == calibrated_priority["priority_cut_rank"]
    )
    assert module.validate_comparison_ranker_response(
        response,
        episodes,
    ) == []


def test_shadow_audit_contains_no_actionable_candidate_without_mutating_llm():
    module = _module()
    episodes = [
        _episode(1, global_rank=1, loss=0.40, evidence="strong"),
        _episode(2, global_rank=2, loss=0.20, evidence="strong"),
        _episode(3, global_rank=3, loss=0.03, evidence="weak"),
        _episode(4, global_rank=4, loss=0.02, evidence="weak"),
    ]
    llm = {
        "ordered_episode_ids": [1, 2, 3, 4],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 3,
    }

    audit = module.build_deterministic_ranker_shadow_audit(
        episodes,
        llm,
    )

    candidate = audit["calibrated_no_actionable_candidate"]
    assert candidate["weak_share_max"] == 0.05
    assert candidate["moderate_share_max"] == 0.04
    assert candidate["strong_share_max"] == 0.01
    assert candidate["response"]["ordered_episode_ids"] == [1, 2, 3, 4]
    assert llm == {
        "ordered_episode_ids": [1, 2, 3, 4],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 3,
    }
