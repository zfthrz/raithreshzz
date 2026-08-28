from __future__ import annotations

import episode_pair_matcher as matcher
import track_baseline_shadow as baseline


def _calibration(thresholds, *, labels=24):
    return {
        "status": "CALIBRATED_PROVISIONAL_LOW_EVIDENCE",
        "human_labels": labels,
        "thresholds": dict(thresholds),
    }


def _thresholds(*, reject=300.0, match=5.0):
    return {
        "match_center_max_m": match,
        "match_overlap_shorter_min": 0.9,
        "match_overlap_union_min": 0.4,
        "match_shared_channel_min": 1,
        "extended_match_center_max_m": None,
        "shape_conflict_mean_sim_max": 0.2,
        "shape_conflict_coverage_diff_min": 0.5,
        "shape_conflict_impact_sim_max": 0.45,
        "reject_center_gt_m": reject,
        "reject_overlap_union_max": 0.0,
    }


def test_exact_variant_full_authority(monkeypatch):
    monkeypatch.setattr(
        matcher,
        "CALIBRATIONS",
        {("Track", "Layout", "LMP2"): _calibration(_thresholds())},
    )
    result = baseline.resolve_track_baseline(
        track="Track", track_layout="Layout", vehicle_variant="LMP2"
    )
    assert result["status"] == "EXACT_VARIANT_CALIBRATION"
    assert result["match"]["production_authorized"] is True
    assert result["reject"]["production_authorized"] is True


def test_sibling_match_core_available_but_reject_not_inherited(monkeypatch):
    monkeypatch.setattr(
        matcher,
        "CALIBRATIONS",
        {("Track", "Layout", "LMP2"): _calibration(_thresholds())},
    )
    result = baseline.resolve_track_baseline(
        track="Track", track_layout="Layout", vehicle_variant="GT3"
    )
    assert result["status"] == "TRACK_MATCH_BASELINE_SHADOW"
    assert result["match"]["status"] == "AVAILABLE"
    assert result["reject"]["production_authorized"] is False
    assert result["reject"]["inheritance_policy"] == "VARIANT_SPECIFIC_UNTIL_VALIDATED"


def test_reject_threshold_differences_do_not_block_match_baseline(monkeypatch):
    monkeypatch.setattr(
        matcher,
        "CALIBRATIONS",
        {
            ("Track", "Layout", "LMP2"): _calibration(_thresholds(reject=300.0)),
            ("Track", "Layout", "HYPER"): _calibration(_thresholds(reject=900.0)),
        },
    )
    result = baseline.resolve_track_baseline(
        track="Track", track_layout="Layout", vehicle_variant="GT3"
    )
    assert result["status"] == "TRACK_MATCH_BASELINE_SHADOW"
    assert result["match"]["status"] == "AVAILABLE"
    assert result["reject"]["status"] == "CONFLICT"


def test_match_threshold_differences_fail_closed_for_match(monkeypatch):
    monkeypatch.setattr(
        matcher,
        "CALIBRATIONS",
        {
            ("Track", "Layout", "LMP2"): _calibration(_thresholds(match=5.0)),
            ("Track", "Layout", "HYPER"): _calibration(_thresholds(match=50.0)),
        },
    )
    result = baseline.resolve_track_baseline(
        track="Track", track_layout="Layout", vehicle_variant="GT3"
    )
    assert result["status"] == "TRACK_MATCH_BASELINE_CONFLICT"
    assert result["match"]["status"] == "CONFLICT"


def test_match_only_calibration_cannot_reject():
    calibration = _calibration(_thresholds(reject=10.0))
    inherited = baseline.match_only_calibration(calibration)
    pair = {
        "track": "Track",
        "track_layout": "Layout",
        "vehicle_variant": "GT3",
        "center_distance_abs_diff_m": 1000.0,
        "overlap_over_union": 0.0,
        "overlap_over_shorter": 0.0,
        "shared_channels": ["brake"],
        "per_channel_metrics": {},
    }
    decision = matcher.classify_pair(pair, calibration_override=inherited)
    assert decision["decision"] == "AMBIGUOUS"
    assert decision["automatic"] is False
