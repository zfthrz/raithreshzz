from __future__ import annotations

from pathlib import Path

import llm_analysis_deepseek as ranker_module
from audit_d2_7_residual_disagreements import ComparisonSample
from audit_d2_9_product_policy import build_candidate as audit_build_candidate
from audit_d2_9_product_policy import derive_d21_order as audit_derive_d21_order
from product_priority_ranker import (
    apply_tie_break,
    build_product_priority_ranker_response,
    derive_d21_order,
    has_direct_authorized_target,
    product_no_actionable_start_rank,
    product_priority_cut_rank,
)


def _episode(
    episode_id: int,
    loss: float,
    *,
    evidence: str = "strong",
    channels: tuple[str, ...] = ("brake",),
    with_events: bool = True,
    zone_delta: float | None = None,
    global_rank: int | None = None,
) -> dict:
    evidence_by_channel: dict = {}
    if with_events:
        for channel in channels:
            if channel in {"brake", "throttle"}:
                evidence_by_channel[channel] = {
                    "events": [{"direction": "lower_in_comparison_lap"}]
                }
    episode = {
        "episode_id": episode_id,
        "action_time_loss_s": loss,
        "evidence_strength": evidence,
        "action_channels": list(channels),
        "action_evidence_by_channel": evidence_by_channel,
        "parent_zone_delta_loss_s": zone_delta,
    }
    if global_rank is not None:
        episode["global_rank"] = global_rank
    return episode


def _by_id(episodes: list[dict]) -> dict[int, dict]:
    return {episode["episode_id"]: episode for episode in episodes}


def test_has_direct_authorized_target_matches_audit_rule():
    assert has_direct_authorized_target(_episode(1, 0.1, channels=("brake",)))
    assert not has_direct_authorized_target(
        _episode(1, 0.1, channels=("steering_magnitude",))
    )
    assert not has_direct_authorized_target(
        _episode(1, 0.1, channels=("brake",), with_events=False)
    )


def test_direct_target_rejects_unknown_nonpersistent_and_mixed_directions():
    episode = _episode(1, 0.1, channels=("brake",))
    events = episode["action_evidence_by_channel"]["brake"]["events"]

    events[:] = [{"direction": "unknown_direction"}]
    assert not has_direct_authorized_target(episode)

    events[:] = [{"direction": "lower_in_comparison_lap", "persistent": False}]
    assert not has_direct_authorized_target(episode)

    events[:] = [
        {"direction": "lower_in_comparison_lap"},
        {"direction": "higher_in_comparison_lap"},
    ]
    assert not has_direct_authorized_target(episode)

    events[:] = [
        {"direction": "lower_in_comparison_lap"},
        {"direction": "lower_in_comparison_lap"},
    ]
    assert has_direct_authorized_target(episode)


def test_direct_target_malformed_evidence_fails_closed():
    episode = _episode(1, 0.1, channels=("brake",))

    episode["action_evidence_by_channel"] = ["invalid"]
    assert not has_direct_authorized_target(episode)

    episode["action_evidence_by_channel"] = {"brake": "invalid"}
    assert not has_direct_authorized_target(episode)

    episode["action_evidence_by_channel"] = {"brake": {"events": "invalid"}}
    assert not has_direct_authorized_target(episode)

    episode["action_channels"] = "brake"
    assert not has_direct_authorized_target(episode)


def test_priority_cut_extends_only_for_strong_direct_target():
    strong_target = [
        _episode(1, 0.6),
        _episode(2, 0.10, channels=("brake",)),
        _episode(3, 0.05),
    ]
    weak_target = [
        _episode(1, 0.6),
        _episode(2, 0.10, evidence="weak", channels=("brake",)),
        _episode(3, 0.05),
    ]
    strong_observational = [
        _episode(1, 0.6),
        _episode(2, 0.10, channels=("steering_magnitude",)),
        _episode(3, 0.05),
    ]
    assert product_priority_cut_rank([1, 2, 3], _by_id(strong_target)) == 2
    assert product_priority_cut_rank([1, 2, 3], _by_id(weak_target)) == 1
    assert (
        product_priority_cut_rank([1, 2, 3], _by_id(strong_observational))
        == 1
    )


def test_priority_cap_limits_extension():
    episodes = [
        _episode(1, 0.50),
        _episode(2, 0.05, channels=("brake",)),
        _episode(3, 0.03, channels=("brake",)),
        _episode(4, 0.02, channels=("brake",)),
    ]
    assert product_priority_cut_rank([1, 2, 3, 4], _by_id(episodes)) == 3


def test_no_actionable_never_discards_moderate_or_strong_actionable():
    episodes = [
        _episode(1, 0.6),
        _episode(2, 0.02, evidence="moderate", channels=("brake",)),
        _episode(3, 0.01, evidence="weak", channels=("steering_magnitude",)),
    ]
    assert (
        product_no_actionable_start_rank(
            [1, 2, 3],
            _by_id(episodes),
            priority_cut_rank=1,
        )
        == 3
    )


def test_no_actionable_marks_weak_negligible_and_observational():
    episodes = [
        _episode(1, 0.9),
        _episode(2, 0.01, evidence="weak", channels=("brake",)),
        _episode(3, 0.01, evidence="strong", channels=("steering_magnitude",)),
    ]
    assert (
        product_no_actionable_start_rank(
            [1, 2, 3],
            _by_id(episodes),
            priority_cut_rank=1,
        )
        == 2
    )


def test_tie_break_only_on_near_ties_by_parent_zone_delta():
    episodes = [
        _episode(1, 0.100, zone_delta=0.5),
        _episode(2, 0.104, zone_delta=2.0),
        _episode(3, 0.200, zone_delta=5.0),
    ]
    assert apply_tie_break([1, 2, 3], _by_id(episodes)) == (2, 1, 3)

    episodes_far = [
        _episode(1, 0.10, zone_delta=2.0),
        _episode(2, 0.20, zone_delta=0.5),
    ]
    assert apply_tie_break([1, 2], _by_id(episodes_far)) == (1, 2)


def test_derive_d21_order_by_global_rank_and_fallback():
    episodes = [
        _episode(1, 0.1, global_rank=2),
        _episode(2, 0.2, global_rank=1),
        _episode(3, 0.3, global_rank=3),
    ]
    assert derive_d21_order(episodes) == (2, 1, 3)

    fallback = [
        _episode(1, 0.1),
        _episode(2, 0.3),
        _episode(3, 0.2),
    ]
    assert derive_d21_order(fallback) == (2, 3, 1)


def test_build_response_matches_audited_policy_and_contract():
    episodes = [
        _episode(1, 0.60),
        _episode(2, 0.10, channels=("brake",)),
        _episode(3, 0.02, evidence="weak", channels=("steering_magnitude",)),
    ]

    response = build_product_priority_ranker_response(episodes)

    assert ranker_module.validate_comparison_ranker_response(
        response,
        episodes,
    ) == []
    sample = ComparisonSample(
        source_path=Path("x.json"),
        track="Test",
        comparison="1->2",
        llm_order=tuple(response["ordered_episode_ids"]),
        llm_priority_cut_rank=response["priority_cut_rank"],
        llm_no_actionable_start_rank=response["no_actionable_start_rank"],
        baseline_order=audit_derive_d21_order(episodes),
        baseline_priority_cut_rank=1,
        baseline_no_actionable_start_rank=len(episodes) + 1,
        episodes_by_id=_by_id(episodes),
    )
    audit_candidate = audit_build_candidate(sample)

    assert response == audit_candidate
    assert response["priority_cut_rank"] == 2
    assert response["no_actionable_start_rank"] == 3


def test_build_response_requires_episodes_and_valid_ids():
    try:
        build_product_priority_ranker_response([])
    except ValueError:
        pass
    else:
        raise AssertionError("debería rechazar un catálogo vacío")

    try:
        build_product_priority_ranker_response([{"episode_id": "x"}])
    except ValueError:
        pass
    else:
        raise AssertionError("debería rechazar episode_id no entero")
