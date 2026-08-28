from __future__ import annotations

import json
from pathlib import Path

import run_h3_pipeline as pipeline


def _features():
    return [
        {
            "track": "Track",
            "track_layout": "Layout",
            "vehicle_variant": "HYPER",
            "vehicle_family": "HYPERCAR",
            "session_a": 1,
            "session_b": 2,
            "episode_pk_a": 10,
            "episode_pk_b": 20,
            "episode_id_a": 1,
            "episode_id_b": 1,
            "start_distance_a_m": 100.0,
            "end_distance_a_m": 120.0,
            "center_distance_a_m": 110.0,
            "start_distance_b_m": 101.0,
            "end_distance_b_m": 121.0,
            "center_distance_b_m": 111.0,
            "channels_a": ["brake"],
            "channels_b": ["brake"],
        }
    ]


def _authorized_decisions():
    return [
        {
            "pair_index": 0,
            "pair_id": "p1",
            "session_a": 1,
            "session_b": 2,
            "episode_pk_a": 10,
            "episode_pk_b": 20,
            "decision": "MATCH",
            "automatic": True,
            "rule_id": "CORE_SPATIAL_MATCH",
            "authority": {
                "calibration_scope": "COVERED_BY_TRACK_MATCH_BASELINE",
                "production_match_authorized": True,
                "production_reject_authorized": False,
            },
        }
    ]


def test_pipeline_writes_normal_batch_outputs_without_history(tmp_path, monkeypatch):
    features_path = tmp_path / "episode_pair_features.json"
    features_path.write_text(json.dumps(_features()), encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "classify_features_authorized",
        lambda features, batches_root: (
            _authorized_decisions(),
            {
                "matcher_version": "0.3",
                "matcher_status": "CALIBRATED_PROVISIONAL",
                "authorized_matcher_version": "0.1",
                "decision_counts": {"MATCH": 1, "AMBIGUOUS": 0, "REJECT": 0},
                "authority_scope_counts": {"COVERED_BY_TRACK_MATCH_BASELINE": 1},
            },
        ),
    )

    report, code = pipeline.run_h3_pipeline(
        features_path,
        batches_root=tmp_path / "calibration_batches",
    )

    assert code == 0
    assert report["result"] == "PASS"
    assert report["history_imported"] is False
    assert report["history_mutated"] is False
    assert report["h3_summary"]["cross_session_repeat_count"] == 1

    matches = json.loads((tmp_path / "episode_pair_matches.json").read_text())
    patterns = json.loads((tmp_path / "persistent_patterns.json").read_text())
    saved_report = json.loads((tmp_path / "h3_pipeline_report.json").read_text())

    assert matches["counts"]["MATCH"] == 1
    assert matches["metadata"]["matcher_version"] == "0.3"
    assert matches["decisions"][0]["authority"]["production_match_authorized"] is True
    assert patterns["summary"]["cross_session_repeat_count"] == 1
    assert patterns["metadata"]["history_imported"] is False
    assert saved_report["history_mutated"] is False


def test_pipeline_defaults_outputs_next_to_features(tmp_path, monkeypatch):
    batch = tmp_path / "batch"
    batch.mkdir()
    features_path = batch / "episode_pair_features.json"
    features_path.write_text(json.dumps(_features()), encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "classify_features_authorized",
        lambda features, batches_root: (
            _authorized_decisions(),
            {
                "matcher_version": "0.3",
                "matcher_status": "TEST",
                "authorized_matcher_version": "0.1",
                "decision_counts": {"MATCH": 1, "AMBIGUOUS": 0, "REJECT": 0},
                "authority_scope_counts": {"COVERED_BY_TRACK_MATCH_BASELINE": 1},
            },
        ),
    )

    report, code = pipeline.run_h3_pipeline(features_path, batches_root=tmp_path)
    assert code == 0
    assert Path(report["outputs"]["episode_pair_matches"]).parent == batch.resolve()
    assert Path(report["outputs"]["persistent_patterns"]).parent == batch.resolve()


def test_pipeline_surfaces_h3_conflict_exit_code(tmp_path, monkeypatch):
    features_path = tmp_path / "episode_pair_features.json"
    features_path.write_text(json.dumps(_features()), encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "classify_features_authorized",
        lambda features, batches_root: (
            _authorized_decisions(),
            {
                "matcher_version": "0.3",
                "matcher_status": "TEST",
                "authorized_matcher_version": "0.1",
                "decision_counts": {"MATCH": 1, "AMBIGUOUS": 0, "REJECT": 0},
                "authority_scope_counts": {"COVERED_BY_TRACK_MATCH_BASELINE": 1},
            },
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "build_patterns",
        lambda features, decisions, persistent_min_sessions: (
            [],
            {
                "pattern_count": 1,
                "state_counts": {"conflict_review_required": 1},
                "conflict_review_required_count": 1,
            },
        ),
    )

    report, code = pipeline.run_h3_pipeline(features_path, batches_root=tmp_path)
    assert code == 2
    assert report["result"] == "REVIEW_REQUIRED"
    assert report["history_imported"] is False
