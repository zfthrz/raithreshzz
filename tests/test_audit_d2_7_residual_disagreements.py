from __future__ import annotations

import json
from pathlib import Path

from audit_d2_7_residual_disagreements import (
    ComparisonSample,
    UNRESOLVED,
    _no_actionable_pattern,
    _order_pattern,
    adjacent_loss_ratio,
    boundary_episodes,
    cumulative_coverage,
    episode_row,
    load_samples,
    pair_inversions,
    relative_metrics,
)


def _episode(
    episode_id: int,
    loss: float,
    *,
    evidence: str = "strong",
    channels: tuple[str, ...] = ("brake",),
    channel_count: int = 1,
    zone_delta: float | None = None,
    speed: bool = False,
) -> dict:
    episode = {
        "episode_id": episode_id,
        "global_rank": episode_id,
        "rank": episode_id,
        "action_time_loss_s": loss,
        "evidence_strength": evidence,
        "action_channel_count": channel_count,
        "action_channels": list(channels),
        "length_m": 50.0,
        "parent_zone_rank": 1,
        "parent_zone_delta_loss_s": zone_delta,
        "parent_zone_net_loss_equivalent_percent": 10.0,
        "zone_id": episode_id,
        "start_distance_m": 100.0 * episode_id,
        "end_distance_m": 100.0 * episode_id + 50.0,
    }
    if speed:
        episode["speed_propagation"] = {"dummy": True}
    return episode


def _sample(
    episodes: list[dict],
    llm_order: list[int],
    llm_cut: int,
    llm_na: int,
    baseline_order: list[int] | None = None,
) -> ComparisonSample:
    baseline_order = baseline_order or [episode["episode_id"] for episode in episodes]
    return ComparisonSample(
        source_path=Path("x.json"),
        track="Test",
        comparison="1->2",
        llm_order=tuple(llm_order),
        llm_priority_cut_rank=llm_cut,
        llm_no_actionable_start_rank=llm_na,
        baseline_order=tuple(baseline_order),
        baseline_priority_cut_rank=1,
        baseline_no_actionable_start_rank=len(episodes),
        episodes_by_id={episode["episode_id"]: episode for episode in episodes},
    )


def test_episode_row_includes_all_deterministic_facts():
    episodes = [
        _episode(1, 0.3, speed=True),
        _episode(2, 0.7, evidence="weak", channels=("brake", "throttle"), channel_count=2),
    ]
    sample = _sample(episodes, [1, 2], 1, 2)
    relative = relative_metrics(episodes)

    row = episode_row(1, sample, relative)

    assert row["episode_id"] == 1
    assert row["objective_rank"] == 1
    assert row["global_rank"] == 1
    assert row["action_time_loss_s"] == 0.3
    assert row["action_loss_vs_max"] == 0.3 / 0.7
    assert row["action_loss_share_of_total"] == 0.3
    assert row["evidence_strength"] == "strong"
    assert row["action_channel_count"] == 1
    assert row["action_channels"] == ["brake"]
    assert row["length_m"] == 50.0
    assert row["parent_zone_rank"] == 1
    assert row["parent_zone_delta_loss_s"] is None
    assert row["zone_id"] == 1
    assert row["start_distance_m"] == 100.0
    assert row["end_distance_m"] == 150.0
    assert row["speed_context_available"] is True


def test_pair_inversions_detected():
    assert pair_inversions([1, 2, 3], [2, 1, 3]) == [(1, 2)]
    assert pair_inversions([1, 2, 3], [3, 2, 1]) == [(1, 2), (1, 3), (2, 3)]
    assert pair_inversions([1, 2, 3], [1, 2, 3]) == []


def test_cumulative_coverage_by_rank():
    rows = cumulative_coverage([1, 2, 3], {1: 50.0, 2: 30.0, 3: 20.0})

    assert [row["coverage"] for row in rows] == [0.5, 0.8, 1.0]
    assert rows[0]["share"] == 0.5
    assert rows[2]["cumulative_loss_s"] == 100.0


def test_adjacent_loss_ratio():
    assert adjacent_loss_ratio(2, [1, 2, 3], {1: 50.0, 2: 30.0, 3: 20.0}) == 20.0 / 30.0
    assert adjacent_loss_ratio(3, [1, 2, 3], {1: 50.0, 2: 30.0, 3: 20.0}) is None
    assert adjacent_loss_ratio(1, [1, 2], {1: 0.0, 2: 20.0}) is None


def test_boundary_episodes_identification():
    assert boundary_episodes([1, 2, 3], 2) == {"before": 2, "after": 3}
    assert boundary_episodes([1, 2, 3], 1) == {"before": 1, "after": 2}


def test_unresolved_pattern_when_no_deterministic_evidence():
    # Inversión sin disparadores: primer episodio con 1 canal y pérdida mayor.
    episodes = [
        _episode(1, 0.5),
        _episode(2, 0.4),
    ]
    sample = _sample(episodes, llm_order=[1, 2], llm_cut=1, llm_na=2)
    relative = relative_metrics(episodes)

    pattern = _order_pattern(sample, (2, 1), relative)

    assert pattern == UNRESOLVED


def test_loader_ignores_non_valid_shadow(tmp_path: Path):
    valid = {
        "reference_lap": 1,
        "comparison_lap": 2,
        "episode_ground_truth": [
            {"episode_id": 1, "action_time_loss_s": 0.5, "evidence_strength": "strong"}
        ],
        "llm_validation_audit": {
            "priority_ranking": {
                "ordered_episode_ids": [1],
                "priority_cut_rank": 1,
                "no_actionable_start_rank": 2,
                "deterministic_shadow": {
                    "status": "VALID",
                    "response": {
                        "ordered_episode_ids": [1],
                        "priority_cut_rank": 1,
                        "no_actionable_start_rank": 2,
                    },
                },
            }
        },
    }
    invalid = json.loads(json.dumps(valid))
    invalid["llm_validation_audit"]["priority_ranking"]["deterministic_shadow"][
        "status"
    ] = "INVALID"
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps({"metadata": {"track": "Test"}, "comparisons": [invalid, valid]}),
        encoding="utf-8",
    )

    samples = load_samples([path])

    assert len(samples) == 1
    assert samples[0].llm_order == (1,)


def test_multi_channel_promotion_pattern_is_deterministic():
    episodes = [
        _episode(1, 0.30, channels=("brake", "throttle"), channel_count=2),
        _episode(2, 0.32),
    ]
    sample = _sample(episodes, llm_order=[1, 2], llm_cut=1, llm_na=2)
    relative = relative_metrics(episodes)

    pattern = _order_pattern(sample, (2, 1), relative)

    assert pattern == "LLM_PROMOTES_MULTI_CHANNEL_OVER_HIGHER_LOSS_SINGLE_CHANNEL"


def test_tiny_loss_kept_actionable_pattern_is_deterministic():
    episodes = [
        _episode(1, 0.6),
        _episode(2, 0.02, evidence="strong"),
        _episode(3, 0.01, evidence="strong"),
    ]
    sample = _sample(
        episodes,
        llm_order=[1, 2, 3],
        llm_cut=1,
        llm_na=4,
    )
    candidate = {
        "ordered_episode_ids": [1, 2, 3],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 3,
    }
    relative = relative_metrics(episodes)

    pattern = _no_actionable_pattern(sample, candidate, relative)

    assert pattern == "LLM_KEEPS_MODERATE_EPISODE_ACTIONABLE_DESPITE_TINY_LOSS"
