from __future__ import annotations

import json
from pathlib import Path

import llm_analysis_deepseek as ranker_module
from audit_d2_9_product_policy import (
    apply_tie_break,
    build_candidate,
    derive_d21_order,
    evaluate,
    has_direct_authorized_target,
    load_all_samples,
    product_no_actionable_start_rank,
    product_priority_cut_rank,
)
from audit_d2_7_residual_disagreements import ComparisonSample


def _episode(
    episode_id: int,
    loss: float,
    *,
    evidence: str = "strong",
    channels: tuple[str, ...] = ("brake",),
    with_events: bool = True,
    zone_delta: float | None = None,
) -> dict:
    evidence_by_channel: dict = {}
    if with_events:
        for channel in channels:
            if channel in {"brake", "throttle"}:
                evidence_by_channel[channel] = {
                    "events": [{"direction": "lower_in_comparison_lap"}]
                }
    return {
        "episode_id": episode_id,
        "action_time_loss_s": loss,
        "evidence_strength": evidence,
        "action_channels": list(channels),
        "action_evidence_by_channel": evidence_by_channel,
        "parent_zone_delta_loss_s": zone_delta,
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


def _by_id(episodes: list[dict]) -> dict[int, dict]:
    return {episode["episode_id"]: episode for episode in episodes}


def test_has_direct_authorized_target():
    assert has_direct_authorized_target(_episode(1, 0.1, channels=("brake",))) is True
    assert has_direct_authorized_target(
        _episode(1, 0.1, channels=("steering_magnitude",))
    ) is False
    assert has_direct_authorized_target(
        _episode(1, 0.1, channels=("brake",), with_events=False)
    ) is False


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
    assert product_priority_cut_rank([1, 2, 3], _by_id(strong_observational)) == 1


def test_priority_cap_limits_extension():
    episodes = [
        _episode(1, 0.50),
        _episode(2, 0.05, channels=("brake",)),
        _episode(3, 0.03, channels=("brake",)),
        _episode(4, 0.02, channels=("brake",)),
    ]
    cut = product_priority_cut_rank(
        [1, 2, 3, 4],
        _by_id(episodes),
        cap=3,
    )
    assert cut == 3


def test_no_actionable_never_discards_moderate_or_strong_actionable():
    episodes = [
        _episode(1, 0.6),
        _episode(2, 0.02, evidence="moderate", channels=("brake",)),
        _episode(3, 0.01, evidence="weak", channels=("steering_magnitude",)),
    ]
    start = product_no_actionable_start_rank(
        [1, 2, 3],
        _by_id(episodes),
        priority_cut_rank=1,
    )
    # Ep 3 observacional -> NO_ACCIONABLE; ep 2 moderate accionable -> se detiene.
    assert start == 3


def test_no_actionable_marks_weak_actionable_negligible_and_observational():
    episodes = [
        _episode(1, 0.9),
        _episode(2, 0.01, evidence="weak", channels=("brake",)),
        _episode(3, 0.01, evidence="strong", channels=("steering_magnitude",)),
    ]
    start = product_no_actionable_start_rank(
        [1, 2, 3],
        _by_id(episodes),
        priority_cut_rank=1,
    )
    # Ep3 observacional (aunque strong) y ep2 weak+negligible -> ambos NO_ACCIONABLE.
    assert start == 2


def test_tie_break_only_on_near_ties_by_parent_zone_delta():
    episodes = [
        _episode(1, 0.100, zone_delta=0.5),
        _episode(2, 0.104, zone_delta=2.0),
        _episode(3, 0.200, zone_delta=5.0),
    ]
    order = apply_tie_break([1, 2, 3], _by_id(episodes))
    # 1 y 2 son near-tie (diff 3.8% <= 5%) -> mayor zone_delta (2) primero.
    assert order == (2, 1, 3)

    episodes_far = [
        _episode(1, 0.10, zone_delta=2.0),
        _episode(2, 0.20, zone_delta=0.5),
    ]
    # Diff 50% > 5%: no se reordena.
    assert apply_tie_break([1, 2], _by_id(episodes_far)) == (1, 2)


def test_priority_cap_applies_to_final_cut_including_base_prefix():
    episodes = [
        _episode(1, 0.30),
        _episode(2, 0.20),
        _episode(3, 0.10),
        _episode(4, 0.05),
    ]
    # Base 55% ya llega a rank 3; con cap=2 debe quedar clamp a 2.
    cut = product_priority_cut_rank(
        [1, 2, 3, 4],
        _by_id(episodes),
        cap=2,
    )
    assert cut == 2


def test_build_candidate_and_evaluate_end_to_end():
    episodes = [
        _episode(1, 0.60),
        _episode(2, 0.10, channels=("brake",)),
        _episode(3, 0.02, evidence="weak", channels=("steering_magnitude",)),
    ]
    sample = _sample(episodes, llm_order=[1, 2, 3], llm_cut=2, llm_na=3)

    candidate = build_candidate(sample)
    report = evaluate([sample])

    assert candidate["priority_cut_rank"] == 2
    assert candidate["no_actionable_start_rank"] == 3
    assert report["rates"]["full"]["count"] == 1


def test_derive_d21_order_by_global_rank():
    episodes = [
        _episode(1, 0.1, zone_delta=0.0),
        _episode(2, 0.2, zone_delta=0.0),
        _episode(3, 0.3, zone_delta=0.0),
    ]
    episodes[0]["global_rank"] = 2
    episodes[1]["global_rank"] = 1
    episodes[2]["global_rank"] = 3

    assert derive_d21_order(episodes) == (2, 1, 3)


def test_derive_d21_order_fallback_by_loss():
    episodes = [
        _episode(1, 0.1),
        _episode(2, 0.3),
        _episode(3, 0.2),
    ]
    assert derive_d21_order(episodes) == (2, 3, 1)


def _ranking_comparison(
    reference_lap: int,
    comparison_lap: int,
    episodes: list[dict],
    llm_order: list[int],
    llm_cut: int,
    llm_na: int,
    shadow: dict | None,
) -> dict:
    ranking: dict = {
        "ordered_episode_ids": llm_order,
        "priority_cut_rank": llm_cut,
        "no_actionable_start_rank": llm_na,
    }
    if shadow is not None:
        ranking["deterministic_shadow"] = shadow
    return {
        "reference_lap": reference_lap,
        "comparison_lap": comparison_lap,
        "episode_ground_truth": episodes,
        "llm_validation_audit": {"priority_ranking": ranking},
    }


def test_load_all_samples_uses_shadow_or_derived_baseline(tmp_path: Path):
    episodes = [
        _episode(1, 0.4),
        _episode(2, 0.3),
        _episode(3, 0.2),
    ]
    with_shadow = _ranking_comparison(
        1,
        2,
        episodes,
        llm_order=[1, 2, 3],
        llm_cut=2,
        llm_na=4,
        shadow={
            "status": "VALID",
            "response": {
                "ordered_episode_ids": [1, 2, 3],
                "priority_cut_rank": 2,
                "no_actionable_start_rank": 4,
            },
        },
    )
    derived = _ranking_comparison(
        2,
        3,
        episodes,
        llm_order=[1, 2, 3],
        llm_cut=2,
        llm_na=4,
        shadow={"status": "INVALID", "response": {}},
    )
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps(
            {"metadata": {"track": "Test"}, "comparisons": [with_shadow, derived]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    samples = load_all_samples([path])

    assert len(samples) == 2
    assert samples[0].baseline_order == (1, 2, 3)
    assert samples[0].baseline_priority_cut_rank == 2
    assert samples[1].baseline_order == (1, 2, 3)
    assert samples[1].baseline_priority_cut_rank == 0


def test_d29_candidate_passes_ranker_validator():
    episodes = [
        _episode(1, 0.6),
        _episode(2, 0.10, channels=("brake",)),
        _episode(3, 0.02, evidence="weak", channels=("steering_magnitude",)),
    ]
    sample = _sample(episodes, llm_order=[1, 2, 3], llm_cut=2, llm_na=3)
    candidate = build_candidate(sample)

    errors = ranker_module.validate_comparison_ranker_response(
        candidate,
        episodes,
    )

    assert errors == []
