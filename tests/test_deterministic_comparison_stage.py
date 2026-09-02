from __future__ import annotations

import deterministic_comparison_stage as stage


def test_prepare_runtime_comparison_preserves_established_order(monkeypatch):
    calls = []
    comparison = {"reference_lap": 1, "comparison_lap": 2}
    quality = {"session_plan_eligible": False, "reason": "outlier"}
    detected = [{"episode_id": 1}]
    eligible = [{"episode_id": 1, "localized": True}]
    excluded = [{"episode_id": 2}]

    monkeypatch.setattr(stage, "_session_comparison_key", lambda item: "1:2")
    monkeypatch.setattr(
        stage,
        "build_episode_catalog",
        lambda item: calls.append("catalog") or detected,
    )

    def localize(items, context):
        calls.append("location")
        assert items is detected
        assert context == {"status": "ACTIVE"}

    monkeypatch.setattr(stage, "enrich_items_with_track_location", localize)

    def split(item, items):
        calls.append("split")
        assert item is comparison
        assert items is detected
        return eligible, excluded

    monkeypatch.setattr(stage, "split_episode_catalog_for_coaching", split)
    prepared = stage.prepare_runtime_comparison(
        comparison,
        {"1:2": quality},
        {"status": "ACTIVE"},
    )
    assert calls == ["catalog", "location", "split"]
    assert prepared.comparison_quality is quality
    assert prepared.session_plan_eligible is False
    assert prepared.detected_episode_catalog is detected
    assert prepared.episode_catalog is eligible
    assert prepared.excluded_anomalies is excluded


def test_prepare_runtime_comparison_defaults_missing_quality_to_eligible(monkeypatch):
    monkeypatch.setattr(stage, "_session_comparison_key", lambda item: "missing")
    monkeypatch.setattr(stage, "build_episode_catalog", lambda item: [])
    monkeypatch.setattr(
        stage, "enrich_items_with_track_location", lambda items, context: None
    )
    monkeypatch.setattr(
        stage, "split_episode_catalog_for_coaching", lambda item, items: ([], [])
    )
    prepared = stage.prepare_runtime_comparison({}, {}, {})
    assert prepared.comparison_quality == {}
    assert prepared.session_plan_eligible is True
