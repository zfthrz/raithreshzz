from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from cross_session_zone_localization import (
    build_trend_zone_summaries,
    find_validated_track_profile,
    localize_trend_zones,
    profile_boundaries,
    unlocalized_zone_summaries,
)


class StubSector:
    def summarize_zone(self, comparison, zone):
        data = comparison.iloc[zone["start_index"] : zone["end_index"] + 1]
        delta_change = float(data["time_delta"].iloc[-1] - data["time_delta"].iloc[0])
        return {
            "type": zone["type"],
            "start_distance": float(data["distance"].iloc[0]),
            "end_distance": float(data["distance"].iloc[-1]),
            "distance": float(data["distance"].iloc[-1] - data["distance"].iloc[0]),
            "delta_change": delta_change,
            "speed_delta_avg": 1.0,
            "throttle_delta_avg": 0.0,
            "brake_delta_avg": 0.0,
        }


def profile() -> dict:
    return {
        "profile_id": "test-profile",
        "status": "VALIDATED_MULTI_SESSION",
        "track": "Test Track",
        "layout": "Test Layout",
        "calibration": {"numbering_scheme": "test"},
        "turns": [
            {
                "turn": 1,
                "name": "First",
                "group": "First",
                "start_m": 80.0,
                "apex_m": 100.0,
                "end_m": 120.0,
            },
            {
                "turn": 2,
                "name": "Second",
                "group": "Second",
                "start_m": 200.0,
                "apex_m": 220.0,
                "end_m": 240.0,
            },
        ],
    }


def comparison() -> pd.DataFrame:
    distance = np.arange(0.0, 301.0, 1.0)
    return pd.DataFrame(
        {
            "distance": distance,
            "time_delta": -distance * 0.001,
        }
    )


def test_validated_profile_boundaries_localize_a_broad_delta_trend():
    data = comparison()
    sector = StubSector()
    trend_zones = [
        {
            "type": "gain",
            "start_index": 0,
            "end_index": 300,
        }
    ]

    localized = localize_trend_zones(
        sector,
        data,
        trend_zones,
        profile(),
        threshold=0.05,
        min_zone_distance=10.0,
    )

    assert profile_boundaries(profile()) == [80.0, 120.0, 200.0, 240.0]
    assert [
        (zone["start_distance"], zone["end_distance"])
        for zone in localized
    ] == [(0.0, 80.0), (120.0, 200.0), (240.0, 300.0)]
    assert all(zone["scope"] == "track_profile_segment" for zone in localized)
    assert all(zone["source_trend_zone_id"] == "trend_001" for zone in localized)
    assert all(zone["location"]["profile_id"] == "test-profile" for zone in localized)


def test_profile_resolver_requires_exact_validated_track_and_layout(tmp_path: Path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile()), encoding="utf-8")

    selected, selected_path = find_validated_track_profile(
        tmp_path,
        track="Test Track",
        layout="Test Layout",
    )
    assert selected["profile_id"] == "test-profile"
    assert selected_path == profile_path.resolve()

    missing, missing_path = find_validated_track_profile(
        tmp_path,
        track="Test Track",
        layout="Different Layout",
    )
    assert missing is None
    assert missing_path is None


def test_unlocalized_fallback_preserves_trend_for_audit():
    sector = StubSector()
    trends = build_trend_zone_summaries(
        sector,
        comparison(),
        [{"type": "gain", "start_index": 0, "end_index": 300}],
    )

    fallback = unlocalized_zone_summaries(trends)

    assert trends[0]["scope"] == "delta_trend"
    assert fallback[0]["scope"] == "unlocalized_delta_trend"
    assert fallback[0]["source_trend_zone_id"] == "trend_001"
    assert fallback[0]["location"] is None
