from __future__ import annotations

import llm_analysis_deepseek as legacy
from deterministic_episode_response import (
    build_grounded_episode_response,
    channel_direction_contract,
)


def episode(*, channels, events):
    return {
        "episode_id": 7,
        "action_channels": channels,
        "action_evidence_by_channel": {
            channel: {"events": channel_events}
            for channel, channel_events in events.items()
        },
    }


def test_grounded_response_matches_legacy_for_single_direction():
    item = episode(
        channels=["brake", "throttle"],
        events={
            "brake": [{"direction": "higher_in_comparison_lap"}],
            "throttle": [{"direction": "lower_in_comparison_lap"}],
        },
    )
    assert channel_direction_contract(item) == legacy.channel_direction_contract_for_llm(
        item
    )
    assert build_grounded_episode_response(item) == (
        legacy.build_deterministic_grounded_episode_fallback(item)
    )


def test_grounded_response_matches_legacy_for_mixed_direction():
    item = episode(
        channels=["brake"],
        events={
            "brake": [
                {"direction": "higher_in_comparison_lap"},
                {"direction": "lower_in_comparison_lap"},
            ]
        },
    )
    assert build_grounded_episode_response(item) == (
        legacy.build_deterministic_grounded_episode_fallback(item)
    )
    assert "replicar la secuencia" in build_grounded_episode_response(item)[
        "recommendation"
    ]


def test_grounded_response_fails_closed_without_direction_phrase():
    item = episode(channels=[], events={})
    assert build_grounded_episode_response(item) is None
    assert legacy.build_deterministic_grounded_episode_fallback(item) is None
