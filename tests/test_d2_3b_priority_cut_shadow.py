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
    evidence="strong",
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


def test_calibrated_cut_uses_smallest_loss_coverage_prefix():
    module = _module()
    episodes = [
        _episode(1, global_rank=1, loss=0.40),
        _episode(2, global_rank=2, loss=0.20),
        _episode(3, global_rank=3, loss=0.15),
        _episode(4, global_rank=4, loss=0.10),
    ]

    cut = module.build_calibrated_priority_cut_rank(
        episodes,
        [1, 2, 3, 4],
        coverage_target=0.55,
    )

    assert cut == 2


def test_calibrated_cut_never_marks_all_multi_episode_items_priority():
    module = _module()
    episodes = [
        _episode(1, global_rank=1, loss=0.50),
        _episode(2, global_rank=2, loss=0.50),
    ]

    assert module.build_calibrated_priority_cut_rank(
        episodes,
        [1, 2],
        coverage_target=0.99,
    ) == 1


def test_calibrated_response_preserves_deterministic_order():
    module = _module()
    episodes = [
        _episode(1, global_rank=1, loss=0.40),
        _episode(2, global_rank=2, loss=0.20),
        _episode(3, global_rank=3, loss=0.15),
        _episode(4, global_rank=4, loss=0.10),
    ]
    baseline = module.build_deterministic_comparison_ranker_response(
        episodes
    )

    calibrated = module.build_calibrated_comparison_ranker_response(
        episodes,
        deterministic_response=baseline,
        coverage_target=0.55,
    )

    assert (
        calibrated["ordered_episode_ids"]
        == baseline["ordered_episode_ids"]
    )
    assert calibrated["priority_cut_rank"] == 2
    assert calibrated["no_actionable_start_rank"] >= 3
    assert module.validate_comparison_ranker_response(
        calibrated,
        episodes,
    ) == []


def test_shadow_audit_contains_calibrated_candidate_without_changing_llm():
    module = _module()
    episodes = [
        _episode(1, global_rank=1, loss=0.40),
        _episode(2, global_rank=2, loss=0.20),
        _episode(3, global_rank=3, loss=0.15),
        _episode(4, global_rank=4, loss=0.10),
    ]
    llm = {
        "ordered_episode_ids": [1, 2, 3, 4],
        "priority_cut_rank": 2,
        "no_actionable_start_rank": 5,
    }

    audit = module.build_deterministic_ranker_shadow_audit(
        episodes,
        llm,
    )

    calibrated = audit["calibrated_candidate"]
    assert calibrated["coverage_target"] == 0.55
    assert calibrated["response"]["priority_cut_rank"] == 2
    assert calibrated["agreement"]["priority_cut_rank"] is True

    assert llm == {
        "ordered_episode_ids": [1, 2, 3, 4],
        "priority_cut_rank": 2,
        "no_actionable_start_rank": 5,
    }
