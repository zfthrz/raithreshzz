from __future__ import annotations

import pytest

from deterministic_comparison_preparation import (
    prepare_comparison,
    require_detected_episodes,
)


def test_prepare_comparison_preserves_order_gates_and_catalogs():
    calls = []
    detected = [{"episode_id": 1}, {"episode_id": 2}]

    def build(comparison):
        calls.append("build")
        return detected

    def enrich(items, context):
        calls.append("enrich")
        items[0]["location"] = context["profile_id"]

    def split(comparison, items):
        calls.append("split")
        return items[:1], items[1:]

    result = prepare_comparison(
        {"reference_lap": 1, "comparison_lap": 2},
        comparison_quality={"session_plan_eligible": False},
        track_location_context={"profile_id": "spa"},
        build_episode_catalog=build,
        enrich_track_location=enrich,
        split_for_coaching=split,
    )
    assert calls == ["build", "enrich", "split"]
    assert result.session_plan_eligible is False
    assert result.detected_episode_catalog is detected
    assert result.episode_catalog == [{"episode_id": 1, "location": "spa"}]
    assert result.excluded_anomalies == [{"episode_id": 2}]


def test_prepare_comparison_defaults_session_plan_to_eligible():
    result = prepare_comparison(
        {"reference_lap": 1, "comparison_lap": 2},
        comparison_quality={},
        track_location_context={},
        build_episode_catalog=lambda comparison: [{"episode_id": 1}],
        enrich_track_location=lambda items, context: None,
        split_for_coaching=lambda comparison, items: (items, []),
    )
    assert result.session_plan_eligible is True


def test_prepare_comparison_fails_closed_without_detected_episodes():
    result = prepare_comparison(
        {"reference_lap": 1, "comparison_lap": 2},
        comparison_quality={},
        track_location_context={},
        build_episode_catalog=lambda comparison: [],
        enrich_track_location=lambda items, context: None,
        split_for_coaching=lambda comparison, items: ([], []),
    )
    with pytest.raises(RuntimeError, match="1 -> 2"):
        require_detected_episodes(
            {"reference_lap": 1, "comparison_lap": 2},
            result.detected_episode_catalog,
        )
