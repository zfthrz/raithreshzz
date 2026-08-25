from __future__ import annotations

import audit_d2_4_no_actionable as audit


def _facts(episode_id, loss, evidence):
    return audit.EpisodeFacts(
        episode_id=episode_id,
        loss=loss,
        evidence_strength=evidence,
    )


def test_candidate_uses_evidence_conditioned_tail_suffix():
    order = [1, 2, 3, 4, 5]
    facts = {
        1: _facts(1, 0.50, "strong"),
        2: _facts(2, 0.25, "strong"),
        3: _facts(3, 0.15, "moderate"),
        4: _facts(4, 0.04, "weak"),
        5: _facts(5, 0.03, "weak"),
    }

    assert audit.calibrated_no_actionable_start_rank(
        order,
        facts,
        priority_cut_rank=2,
        weak_share_max=0.05,
        moderate_share_max=0.04,
        strong_share_max=0.01,
    ) == 4


def test_candidate_stops_at_first_tail_item_above_floor():
    order = [1, 2, 3, 4]
    facts = {
        1: _facts(1, 0.50, "strong"),
        2: _facts(2, 0.25, "strong"),
        3: _facts(3, 0.08, "weak"),
        4: _facts(4, 0.03, "weak"),
    }

    assert audit.calibrated_no_actionable_start_rank(
        order,
        facts,
        priority_cut_rank=1,
        weak_share_max=0.05,
    ) == 4


def test_candidate_never_crosses_priority_cut():
    order = [1, 2]
    facts = {
        1: _facts(1, 0.01, "weak"),
        2: _facts(2, 0.01, "weak"),
    }

    assert audit.calibrated_no_actionable_start_rank(
        order,
        facts,
        priority_cut_rank=1,
        weak_share_max=1.0,
        moderate_share_max=1.0,
        strong_share_max=1.0,
    ) == 2


def test_zero_total_loss_means_no_no_actionable_suffix():
    order = [1, 2, 3]
    facts = {
        1: _facts(1, 0.0, "weak"),
        2: _facts(2, 0.0, "weak"),
        3: _facts(3, 0.0, "weak"),
    }

    assert audit.calibrated_no_actionable_start_rank(
        order,
        facts,
        priority_cut_rank=1,
    ) == 4
