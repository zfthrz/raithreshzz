from pathlib import Path

import audit_d2_6_cross_validation as audit


def _sample(source, llm_order=(1, 2, 3)):
    return audit.ComparisonSample(
        source_path=Path(source),
        track="Track",
        comparison="1->2",
        llm_order=llm_order,
        baseline_order=(1, 2, 3),
        llm_priority_cut_rank=1,
        llm_no_actionable_start_rank=3,
        losses_by_episode_id={1: 0.40, 2: 0.10, 3: 0.01},
        facts_by_episode_id={
            1: audit.EpisodeFacts(1, 0.40, "strong"),
            2: audit.EpisodeFacts(2, 0.10, "moderate"),
            3: audit.EpisodeFacts(3, 0.01, "weak"),
        },
    )


def test_score_requires_order_and_cuts_for_full_agreement():
    exact = audit.score(
        [_sample("a.json")],
        (0.55, 0.05, 0.04, 0.01),
    )
    wrong_order = audit.score(
        [_sample("a.json", llm_order=(2, 1, 3))],
        (0.55, 0.05, 0.04, 0.01),
    )

    assert exact["full"] == 1
    assert wrong_order["full"] == 0


def test_leave_one_file_out_builds_one_fold_per_source():
    samples = [_sample("a.json"), _sample("b.json")]
    folds = audit.leave_one_file_out(samples)

    assert len(folds) == 2
    assert all(fold["test"]["n"] == 1 for fold in folds)
