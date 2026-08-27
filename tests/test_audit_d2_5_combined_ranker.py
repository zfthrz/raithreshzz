from __future__ import annotations

from pathlib import Path

import audit_d2_5_combined_ranker as audit


def _sample():
    return audit.ComparisonSample(
        source_path=Path("sample.json"),
        track="Track",
        comparison="1->2",
        episode_ids=(1, 2, 3, 4),
        llm_order=(1, 2, 3, 4),
        llm_priority_cut_rank=2,
        llm_no_actionable_start_rank=4,
        baseline_order=(1, 2, 3, 4),
        baseline_priority_cut_rank=3,
        baseline_no_actionable_start_rank=5,
        losses_by_episode_id={
            1: 0.40,
            2: 0.20,
            3: 0.08,
            4: 0.02,
        },
        facts_by_episode_id={
            1: audit.EpisodeFacts(1, 0.40, "strong"),
            2: audit.EpisodeFacts(2, 0.20, "strong"),
            3: audit.EpisodeFacts(3, 0.08, "moderate"),
            4: audit.EpisodeFacts(4, 0.02, "weak"),
        },
    )


def test_combined_candidate_uses_d2_1_order_d2_3_priority_and_d2_4_tail():
    candidate = audit.build_combined_candidate(_sample())

    assert candidate["ordered_episode_ids"] == [1, 2, 3, 4]
    assert candidate["priority_cut_rank"] == 1
    assert candidate["no_actionable_start_rank"] == 4


def test_evaluate_reports_component_and_full_agreement():
    sample = _sample()
    report = audit.evaluate([sample])

    assert report["comparison_count"] == 1
    assert report["combined_candidate"]["order"]["count"] == 1
    assert report["combined_candidate"]["full"]["count"] in (0, 1)
    assert report["baseline"]["full"]["count"] in (0, 1)
