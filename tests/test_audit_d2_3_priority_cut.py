from __future__ import annotations

import json

import audit_d2_3_priority_cut as audit


def test_calibrated_priority_cut_uses_smallest_coverage_prefix():
    order = [1, 2, 3, 4]
    losses = {
        1: 0.40,
        2: 0.20,
        3: 0.15,
        4: 0.10,
    }

    assert audit.calibrated_priority_cut_rank(
        order,
        losses,
        coverage_target=0.55,
    ) == 2


def test_calibrated_priority_cut_never_marks_all_multi_episode_items_priority():
    order = [1, 2]
    losses = {1: 0.50, 2: 0.50}

    assert audit.calibrated_priority_cut_rank(
        order,
        losses,
        coverage_target=0.55,
    ) == 1


def test_calibrated_priority_cut_zero_loss_falls_back_to_first():
    assert audit.calibrated_priority_cut_rank(
        [1, 2, 3],
        {1: 0.0, 2: 0.0, 3: 0.0},
    ) == 1


def test_load_samples_reads_only_valid_d2_2_shadow(tmp_path):
    payload = {
        "metadata": {"track": "Test Track"},
        "comparisons": [
            {
                "reference_lap": 4,
                "comparison_lap": 3,
                "episode_ground_truth": [
                    {
                        "episode_id": 1,
                        "action_time_loss_s": 0.20,
                    },
                    {
                        "episode_id": 2,
                        "action_time_loss_s": 0.10,
                    },
                ],
                "llm_validation_audit": {
                    "priority_ranking": {
                        "ordered_episode_ids": [1, 2],
                        "priority_cut_rank": 1,
                        "deterministic_shadow": {
                            "status": "VALID",
                            "response": {
                                "ordered_episode_ids": [1, 2],
                                "priority_cut_rank": 1,
                                "no_actionable_start_rank": 3,
                            },
                        },
                    }
                },
            },
            {
                "reference_lap": 4,
                "comparison_lap": 2,
                "episode_ground_truth": [],
                "llm_validation_audit": {
                    "priority_ranking": {
                        "deterministic_shadow": {
                            "status": "ERROR",
                        }
                    }
                },
            },
        ],
    }
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    samples = audit.load_samples([path])

    assert len(samples) == 1
    assert samples[0].track == "Test Track"
    assert samples[0].comparison == "4->3"


def test_evaluate_baseline_and_candidate_are_separate():
    sample = audit.ComparisonSample(
        source_path=audit.Path("sample.json"),
        track="Track",
        comparison="1->2",
        llm_order=(1, 2, 3),
        deterministic_order=(1, 2, 3),
        llm_priority_cut_rank=2,
        baseline_priority_cut_rank=1,
        losses_by_episode_id={
            1: 0.30,
            2: 0.25,
            3: 0.05,
        },
    )

    baseline = audit.evaluate_baseline([sample])
    candidate = audit.evaluate_coverage_target(
        [sample],
        0.55,
    )

    assert baseline["exact_match_count"] == 0
    assert candidate["exact_match_count"] == 1
