from __future__ import annotations

from copy import deepcopy

import pytest

import llm_analysis_deepseek as legacy
from deterministic_priority_shadow import build_deterministic_ranker_shadow_audit


def _episode(episode_id, rank, evidence, loss):
    return {
        "episode_id": episode_id,
        "global_rank": rank,
        "evidence_strength": evidence,
        "action_time_loss_s": loss,
        "action_channel_count": 1,
        "length_m": 25.0,
    }


@pytest.mark.parametrize(
    "episodes,response",
    [
        (
            [_episode(1, 1, "strong", 0.5), _episode(2, 2, "moderate", 0.1)],
            {"ordered_episode_ids": [1, 2], "priority_cut_rank": 1, "no_actionable_start_rank": 3},
        ),
        (
            [_episode(1, 2, "weak", 0.01), _episode(2, 1, "strong", 0.8), _episode(3, 3, "moderate", 0.02)],
            {"ordered_episode_ids": [2, 1, 3], "priority_cut_rank": 1, "no_actionable_start_rank": 4},
        ),
        (
            [_episode(1, None, "moderate", 0.2), _episode(2, None, "weak", 0.0)],
            {"ordered_episode_ids": [1, 2], "priority_cut_rank": 1, "no_actionable_start_rank": 2},
        ),
    ],
)
def test_neutral_priority_shadow_is_exactly_legacy_compatible(episodes, response):
    assert build_deterministic_ranker_shadow_audit(
        deepcopy(episodes), deepcopy(response)
    ) == legacy.build_deterministic_ranker_shadow_audit(
        deepcopy(episodes), deepcopy(response)
    )
