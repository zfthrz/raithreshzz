from __future__ import annotations

import json

import audit_track_baseline_shadow as audit
import episode_pair_matcher as matcher


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _thresholds():
    return {
        "reject_center_gt_m": 10.0,
        "reject_overlap_union_max": 0.0,
        "match_center_max_m": 1.0,
        "match_overlap_shorter_min": 0.9,
        "match_overlap_union_min": 0.9,
        "match_shared_channel_min": 1,
        "extended_match_center_max_m": None,
        "shape_conflict_mean_sim_max": 0.2,
        "shape_conflict_coverage_diff_min": 0.5,
        "shape_conflict_impact_sim_max": 0.45,
    }


def _install_baseline(monkeypatch):
    calibration = {
        "status": "CALIBRATED_PROVISIONAL_LOW_EVIDENCE",
        "human_labels": 24,
        "thresholds": _thresholds(),
    }
    monkeypatch.setattr(
        matcher,
        "CALIBRATIONS",
        {("Track", "Layout", "LMP2"): calibration},
    )


def _status(batch):
    _write(
        batch / "BATCH_STATUS.json",
        {
            "track": "Track",
            "track_layout": "Layout",
            "vehicle_variant": "GT3",
            "batch_id": "x",
        },
    )


def test_human_expected_mapping():
    assert audit._human_expected("SAME") == "MATCH"
    assert audit._human_expected("DIFFERENT") == "REJECT"
    assert audit._human_expected("AMBIGUOUS") == "AMBIGUOUS"


def test_far_zero_overlap_is_not_inherited_as_reject(tmp_path, monkeypatch):
    """MATCH-only inheritance must fail closed on the old REJECT boundary."""
    batch = tmp_path / "batch"
    _install_baseline(monkeypatch)
    _status(batch)

    _write(
        batch / "pair_labels.json",
        {
            "labels": [
                {
                    "pair_id": "p1",
                    "human_label": "SAME",
                    "feature_snapshot": {
                        "center_distance_abs_diff_m": 100.0,
                        "overlap_over_union": 0.0,
                        "overlap_over_shorter": 0.0,
                        "shared_channels": ["brake"],
                        "per_channel_metrics": {},
                    },
                }
            ]
        },
    )

    report = audit.audit_batch(batch)
    assert report["observed_status"] == "NO_AUTOMATIC_COVERAGE"
    assert report["contradictions"] == []
    assert report["automatic_decisive_labels"] == 0
    assert report["pairs"][0]["shadow_decision"] == "AMBIGUOUS"
    assert report["pairs"][0]["automatic"] is False
    assert report["production_authorized"] is False


def test_match_core_can_be_observed_without_production_authority(tmp_path, monkeypatch):
    batch = tmp_path / "batch"
    _install_baseline(monkeypatch)
    _status(batch)

    _write(
        batch / "pair_labels.json",
        {
            "labels": [
                {
                    "pair_id": "p1",
                    "human_label": "SAME",
                    "feature_snapshot": {
                        "center_distance_abs_diff_m": 0.0,
                        "overlap_over_union": 1.0,
                        "overlap_over_shorter": 1.0,
                        "shared_channels": ["brake"],
                        "per_channel_metrics": {},
                    },
                }
            ]
        },
    )

    report = audit.audit_batch(batch)
    assert report["observed_status"] == "NO_CONTRADICTIONS_OBSERVED"
    assert report["automatic_decisive_labels"] == 1
    assert report["correct_automatic_decisive_labels"] == 1
    assert report["automatic_precision_on_decisive_labels"] == 1.0
    assert report["pairs"][0]["shadow_decision"] == "MATCH"
    assert report["production_authorized"] is False


def test_audit_never_authorizes_production(tmp_path, monkeypatch):
    batch = tmp_path / "batch"
    _install_baseline(monkeypatch)
    _status(batch)
    _write(batch / "pair_labels.json", {"labels": []})

    report = audit.audit_batch(batch)
    assert report["production_authorized"] is False
