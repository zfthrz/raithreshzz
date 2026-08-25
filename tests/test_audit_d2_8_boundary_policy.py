from __future__ import annotations

from pathlib import Path

from audit_d2_7_residual_disagreements import ComparisonSample
from audit_d2_8_boundary_policy import (
    build_candidate,
    evaluate,
    evidence_aware_no_actionable_start_rank,
    evidence_channel_priority_cut_rank,
)


def _episode(
    episode_id: int,
    loss: float,
    *,
    evidence: str = "strong",
    channels: int = 1,
) -> dict:
    return {
        "episode_id": episode_id,
        "action_time_loss_s": loss,
        "evidence_strength": evidence,
        "action_channel_count": channels,
        "action_channels": ["brake"] * channels,
    }


def _sample(
    episodes: list[dict],
    llm_order: list[int],
    llm_cut: int,
    llm_na: int,
) -> ComparisonSample:
    return ComparisonSample(
        source_path=Path("x.json"),
        track="Test",
        comparison="1->2",
        llm_order=tuple(llm_order),
        llm_priority_cut_rank=llm_cut,
        llm_no_actionable_start_rank=llm_na,
        baseline_order=tuple(episode["episode_id"] for episode in episodes),
        baseline_priority_cut_rank=1,
        baseline_no_actionable_start_rank=len(episodes),
        episodes_by_id={episode["episode_id"]: episode for episode in episodes},
    )


def test_priority_cut_extends_for_strong_multi_channel_boundary():
    episodes = [
        _episode(1, 0.60),
        _episode(2, 0.10, channels=2),
        _episode(3, 0.05),
    ]
    # 55% se alcanza en rank 1; el siguiente (2) es strong + 2 canales → extiende.
    cut = evidence_channel_priority_cut_rank(
        [1, 2, 3],
        {episode["episode_id"]: episode for episode in episodes},
    )
    assert cut == 2


def test_priority_cut_does_not_extend_on_weak_or_single_channel():
    weak = [
        _episode(1, 0.60),
        _episode(2, 0.10, evidence="weak"),
        _episode(3, 0.05),
    ]
    single = [
        _episode(1, 0.60),
        _episode(2, 0.10, channels=1),
        _episode(3, 0.05),
    ]
    by_id = lambda episodes: {episode["episode_id"]: episode for episode in episodes}
    assert evidence_channel_priority_cut_rank([1, 2, 3], by_id(weak)) == 1
    assert evidence_channel_priority_cut_rank([1, 2, 3], by_id(single)) == 1


def test_no_actionable_only_weak_tail():
    episodes = [
        _episode(1, 0.90),
        _episode(2, 0.03, evidence="moderate"),
        _episode(3, 0.02, evidence="weak"),
    ]
    start = evidence_aware_no_actionable_start_rank(
        [1, 2, 3],
        {episode["episode_id"]: episode for episode in episodes},
        priority_cut_rank=1,
    )
    # Ep 3 weak (share 0.021) → NO_ACCIONABLE; ep 2 moderate → se detiene.
    assert start == 3


def test_no_actionable_keeps_moderate_and_strong_actionable():
    episodes = [
        _episode(1, 0.90),
        _episode(2, 0.03, evidence="moderate"),
        _episode(3, 0.02, evidence="strong"),
    ]
    start = evidence_aware_no_actionable_start_rank(
        [1, 2, 3],
        {episode["episode_id"]: episode for episode in episodes},
        priority_cut_rank=1,
    )
    assert start == 4


def test_build_candidate_and_evaluate_work_end_to_end():
    episodes = [
        _episode(1, 0.45),
        _episode(2, 0.10, channels=2),
        _episode(3, 0.05, evidence="weak"),
    ]
    sample = _sample(episodes, llm_order=[1, 2, 3], llm_cut=2, llm_na=4)

    candidate = build_candidate(sample)
    report = evaluate([sample])

    assert candidate["priority_cut_rank"] == 2
    assert candidate["no_actionable_start_rank"] == 4
    assert report["rates"]["full"]["count"] == 1
