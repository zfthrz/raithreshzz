from __future__ import annotations

import track_match_baseline_promotion as promotion


def _report(*, matches=4, ambiguous_auto=0, contradictions=0, false_matches=0):
    pairs = []
    for index in range(matches):
        pairs.append({
            "pair_id": f"s{index}",
            "human_label": "SAME",
            "shadow_decision": "MATCH",
            "automatic": True,
        })
    for index in range(false_matches):
        pairs.append({
            "pair_id": f"f{index}",
            "human_label": "DIFFERENT",
            "shadow_decision": "MATCH",
            "automatic": True,
        })
    return {
        "baseline": {
            "status": "TRACK_MATCH_BASELINE_SHADOW",
            "match": {
                "status": "AVAILABLE",
                "source_variants": ["LMP2_ELMS"],
            },
        },
        "pairs": pairs,
        "contradictions": [{"x": 1}] * contradictions,
        "automatic_on_human_ambiguous": [{"x": 1}] * ambiguous_auto,
    }


def test_promotes_clean_match_evidence():
    result = promotion.evaluate_match_promotion(
        _report(matches=4),
        target_variant_sessions=2,
    )
    assert result["status"] == "COVERED_BY_TRACK_MATCH_BASELINE"
    assert result["production_match_authorized"] is True
    assert result["production_reject_authorized"] is False


def test_requires_four_confirmed_matches():
    result = promotion.evaluate_match_promotion(
        _report(matches=3),
        target_variant_sessions=5,
    )
    assert result["eligible"] is False
    assert "confirmed_automatic_matches_below_4" in result["reasons"]


def test_requires_two_target_sessions():
    result = promotion.evaluate_match_promotion(
        _report(matches=6),
        target_variant_sessions=1,
    )
    assert result["eligible"] is False
    assert "target_variant_sessions_below_2" in result["reasons"]


def test_human_ambiguous_blocks_promotion():
    result = promotion.evaluate_match_promotion(
        _report(matches=6, ambiguous_auto=1),
        target_variant_sessions=5,
    )
    assert result["eligible"] is False
    assert "automatic_decision_on_human_ambiguous" in result["reasons"]


def test_false_match_blocks_promotion():
    result = promotion.evaluate_match_promotion(
        _report(matches=6, false_matches=1),
        target_variant_sessions=5,
    )
    assert result["eligible"] is False
    assert "automatic_match_disagrees_with_human_label" in result["reasons"]


def test_decisive_contradiction_blocks_promotion():
    result = promotion.evaluate_match_promotion(
        _report(matches=6, contradictions=1),
        target_variant_sessions=5,
    )
    assert result["eligible"] is False
    assert "decisive_human_contradictions_present" in result["reasons"]
