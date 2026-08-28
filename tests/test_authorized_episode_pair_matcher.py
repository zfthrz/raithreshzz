from __future__ import annotations

from pathlib import Path

import authorized_episode_pair_matcher as authorized
import episode_pair_matcher as matcher


def _thresholds():
    return {
        "match_center_max_m": 5.0,
        "match_overlap_shorter_min": 0.9,
        "match_overlap_union_min": 0.4,
        "match_shared_channel_min": 1,
        "extended_match_center_max_m": None,
        "shape_conflict_mean_sim_max": 0.2,
        "shape_conflict_coverage_diff_min": 0.5,
        "shape_conflict_impact_sim_max": 0.45,
        "reject_center_gt_m": 100.0,
        "reject_overlap_union_max": 0.0,
    }


def _calibration():
    return {
        "status": "CALIBRATED_PROVISIONAL_LOW_EVIDENCE",
        "human_labels": 24,
        "thresholds": _thresholds(),
    }


def _pair(*, variant="GT3", center=0.0, union=1.0, shorter=1.0):
    return {
        "track": "Track",
        "track_layout": "Layout",
        "vehicle_variant": variant,
        "session_a": 1,
        "session_b": 2,
        "episode_pk_a": 10,
        "episode_pk_b": 20,
        "center_distance_abs_diff_m": center,
        "overlap_over_union": union,
        "overlap_over_shorter": shorter,
        "shared_channels": ["brake"],
        "per_channel_metrics": {},
    }


def _promoted():
    return {
        "status": "COVERED_BY_TRACK_MATCH_BASELINE",
        "eligible": True,
        "production_match_authorized": True,
        "production_reject_authorized": False,
        "confirmed_automatic_matches": 4,
        "source_variants": ["LMP2_ELMS"],
        "batch_id": "batch123",
    }


def _shadow_baseline():
    return {
        "status": "TRACK_MATCH_BASELINE_SHADOW",
        "production_authorized": False,
        "match": {
            "status": "AVAILABLE",
            "source_variants": ["LMP2_ELMS"],
        },
        "reject": {
            "status": "AVAILABLE",
            "production_authorized": False,
        },
        "calibration": _calibration(),
    }


def test_exact_calibration_preserves_match_and_full_authority(monkeypatch):
    monkeypatch.setattr(
        matcher,
        "CALIBRATIONS",
        {("Track", "Layout", "GT3"): _calibration()},
    )
    result = authorized.classify_pair_authorized(
        _pair(),
        batches_root=Path("."),
        target_variant_sessions=2,
    )
    assert result["decision"] == "MATCH"
    assert result["authority"]["calibration_scope"] == "EXACT_VARIANT_CALIBRATION"
    assert result["authority"]["production_match_authorized"] is True
    assert result["authority"]["production_reject_authorized"] is True


def test_exact_calibration_preserves_reject(monkeypatch):
    monkeypatch.setattr(
        matcher,
        "CALIBRATIONS",
        {("Track", "Layout", "GT3"): _calibration()},
    )
    result = authorized.classify_pair_authorized(
        _pair(center=500.0, union=0.0, shorter=0.0),
        batches_root=Path("."),
        target_variant_sessions=2,
    )
    assert result["decision"] == "REJECT"
    assert result["automatic"] is True


def test_promoted_inherited_match_becomes_production_match(monkeypatch):
    monkeypatch.setattr(matcher, "CALIBRATIONS", {})
    monkeypatch.setattr(
        authorized,
        "discover_promotion_for_context",
        lambda **kwargs: _promoted(),
    )
    monkeypatch.setattr(
        authorized,
        "resolve_track_baseline",
        lambda **kwargs: _shadow_baseline(),
    )
    result = authorized.classify_pair_authorized(
        _pair(),
        batches_root=Path("."),
        target_variant_sessions=2,
    )
    assert result["decision"] == "MATCH"
    assert result["automatic"] is True
    assert result["authority"]["calibration_scope"] == "COVERED_BY_TRACK_MATCH_BASELINE"
    assert result["authority"]["production_match_authorized"] is True
    assert result["authority"]["production_reject_authorized"] is False
    assert result["authority"]["promotion_batch_id"] == "batch123"


def test_promoted_far_pair_never_inherits_reject(monkeypatch):
    monkeypatch.setattr(matcher, "CALIBRATIONS", {})
    monkeypatch.setattr(
        authorized,
        "discover_promotion_for_context",
        lambda **kwargs: _promoted(),
    )
    monkeypatch.setattr(
        authorized,
        "resolve_track_baseline",
        lambda **kwargs: _shadow_baseline(),
    )
    result = authorized.classify_pair_authorized(
        _pair(center=500.0, union=0.0, shorter=0.0),
        batches_root=Path("."),
        target_variant_sessions=2,
    )
    assert result["decision"] == "AMBIGUOUS"
    assert result["automatic"] is False
    assert result["authority"]["production_reject_authorized"] is False


def test_non_promoted_variant_stays_original_ambiguous(monkeypatch):
    monkeypatch.setattr(matcher, "CALIBRATIONS", {})
    monkeypatch.setattr(
        authorized,
        "discover_promotion_for_context",
        lambda **kwargs: {
            "status": "TRACK_MATCH_BASELINE_SHADOW",
            "production_match_authorized": False,
            "production_reject_authorized": False,
            "source_variants": ["LMP2_ELMS"],
            "reasons": ["insufficient_evidence"],
        },
    )
    result = authorized.classify_pair_authorized(
        _pair(),
        batches_root=Path("."),
        target_variant_sessions=2,
    )
    assert result["decision"] == "AMBIGUOUS"
    assert result["rule_id"] == "NO_CALIBRATION_FOR_CONTEXT"
    assert result["authority"]["production_match_authorized"] is False


def test_promotion_error_fails_closed(monkeypatch):
    monkeypatch.setattr(matcher, "CALIBRATIONS", {})

    def explode(**kwargs):
        raise ValueError("bad evidence")

    monkeypatch.setattr(authorized, "discover_promotion_for_context", explode)
    result = authorized.classify_pair_authorized(
        _pair(),
        batches_root=Path("."),
        target_variant_sessions=2,
    )
    assert result["decision"] == "AMBIGUOUS"
    assert result["automatic"] is False
    assert result["authority"]["calibration_scope"] == "PROMOTION_EVIDENCE_ERROR"


def test_context_session_count_uses_independent_session_ids():
    pairs = [
        _pair(),
        {**_pair(), "session_a": 2, "session_b": 3},
        {**_pair(variant="HYPER"), "session_a": 9, "session_b": 10},
    ]
    assert authorized.context_session_count(
        pairs,
        context=("Track", "Layout", "GT3"),
    ) == 3
