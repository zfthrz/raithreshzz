import importlib

import pytest


MODULE_NAME = "llm_analysis_deepseek"


def _module():
    return importlib.import_module(MODULE_NAME)


def _episode(
    episode_id,
    *,
    global_rank=None,
    loss=0.05,
    evidence="moderate",
    channels=1,
    length_m=25.0,
):
    result = {
        "episode_id": episode_id,
        "action_time_loss_s": loss,
        "evidence_strength": evidence,
        "action_channel_count": channels,
        "length_m": length_m,
    }

    if global_rank is not None:
        result["global_rank"] = global_rank

    return result


def _rank(episodes):
    return _module().build_deterministic_comparison_ranker_response(
        episodes
    )


def _classifications(episodes, response):
    module = _module()
    return {
        item["episode_id"]: item["classification"]
        for item in module.derive_priority_classifications(
            response,
            episodes,
        )
    }


def test_single_moderate_episode_is_priority():
    episodes = [
        _episode(1, global_rank=1, evidence="moderate"),
    ]

    response = _rank(episodes)

    assert response == {
        "ordered_episode_ids": [1],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 2,
    }

    assert _classifications(episodes, response) == {
        1: "PRIORITARIO",
    }


def test_strong_then_moderate_becomes_priority_secondary():
    episodes = [
        _episode(1, global_rank=1, evidence="strong"),
        _episode(2, global_rank=2, evidence="moderate"),
    ]

    response = _rank(episodes)

    assert response["ordered_episode_ids"] == [1, 2]
    assert response["priority_cut_rank"] == 1
    assert response["no_actionable_start_rank"] == 3

    assert _classifications(episodes, response) == {
        1: "PRIORITARIO",
        2: "SECUNDARIO",
    }


def test_initial_strong_block_is_priority():
    episodes = [
        _episode(1, global_rank=1, evidence="strong"),
        _episode(2, global_rank=2, evidence="strong"),
        _episode(3, global_rank=3, evidence="moderate"),
    ]

    response = _rank(episodes)

    assert response["priority_cut_rank"] == 2

    assert _classifications(episodes, response) == {
        1: "PRIORITARIO",
        2: "PRIORITARIO",
        3: "SECUNDARIO",
    }


def test_not_all_strong_episodes_can_be_priority():
    episodes = [
        _episode(1, global_rank=1, evidence="strong"),
        _episode(2, global_rank=2, evidence="strong"),
    ]

    response = _rank(episodes)

    assert response["priority_cut_rank"] == 1

    assert _classifications(episodes, response) == {
        1: "PRIORITARIO",
        2: "SECUNDARIO",
    }


def test_final_weak_suffix_becomes_not_actionable():
    episodes = [
        _episode(1, global_rank=1, evidence="moderate"),
        _episode(2, global_rank=2, evidence="moderate"),
        _episode(3, global_rank=3, evidence="weak"),
    ]

    response = _rank(episodes)

    assert response["priority_cut_rank"] == 1
    assert response["no_actionable_start_rank"] == 3

    assert _classifications(episodes, response) == {
        1: "PRIORITARIO",
        2: "SECUNDARIO",
        3: "NO_ACCIONABLE",
    }


def test_only_final_consecutive_weak_suffix_is_not_actionable():
    episodes = [
        _episode(1, global_rank=1, evidence="strong"),
        _episode(2, global_rank=2, evidence="weak"),
        _episode(3, global_rank=3, evidence="moderate"),
        _episode(4, global_rank=4, evidence="weak"),
    ]

    response = _rank(episodes)

    assert response["no_actionable_start_rank"] == 4

    assert _classifications(episodes, response) == {
        1: "PRIORITARIO",
        2: "SECUNDARIO",
        3: "SECUNDARIO",
        4: "NO_ACCIONABLE",
    }


def test_all_weak_keeps_best_episode_priority():
    episodes = [
        _episode(1, global_rank=1, evidence="weak"),
        _episode(2, global_rank=2, evidence="weak"),
    ]

    response = _rank(episodes)

    assert response["priority_cut_rank"] == 1
    assert response["no_actionable_start_rank"] == 2

    assert _classifications(episodes, response) == {
        1: "PRIORITARIO",
        2: "NO_ACCIONABLE",
    }


def test_valid_global_rank_is_independent_of_input_order():
    episodes = [
        _episode(30, global_rank=3, loss=0.03),
        _episode(10, global_rank=1, loss=0.10),
        _episode(20, global_rank=2, loss=0.06),
    ]

    response = _rank(episodes)

    assert response["ordered_episode_ids"] == [
        10,
        20,
        30,
    ]


def test_fallback_order_reproduces_objective_priority_rules():
    episodes = [
        _episode(
            3,
            loss=0.05,
            evidence="strong",
            channels=1,
            length_m=20.0,
        ),
        _episode(
            2,
            loss=0.05,
            evidence="strong",
            channels=2,
            length_m=20.0,
        ),
        _episode(
            1,
            loss=0.08,
            evidence="moderate",
            channels=1,
            length_m=15.0,
        ),
    ]

    response = _rank(episodes)

    assert response["ordered_episode_ids"] == [
        1,
        2,
        3,
    ]


def test_fallback_tie_break_is_stable_by_episode_id():
    episodes = [
        _episode(7),
        _episode(2),
        _episode(5),
    ]

    response = _rank(episodes)

    assert response["ordered_episode_ids"] == [
        2,
        5,
        7,
    ]


def test_empty_catalog_is_rejected():
    with pytest.raises(
        ValueError,
        match="al menos un episodio",
    ):
        _rank([])


def test_duplicate_episode_id_is_rejected():
    episodes = [
        _episode(1),
        _episode(1),
    ]

    with pytest.raises(
        ValueError,
        match="episode_id duplicado",
    ):
        _rank(episodes)
