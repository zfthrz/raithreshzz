from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

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


# ── Versioned duplicate resolution ───────────────────────────────────────────


class TestVersionedDuplicateResolution:
    """When multiple VALIDATED profiles share exact track + layout,
    the resolver must select the highest contractual version."""

    def test_v02_and_v03_same_track_layout_selects_v03(self, tmp_path: Path):
        """v0.2 + v0.3 with same track/layout → selects v0.3."""
        (tmp_path / "profile_v0_2.json").write_text(
            json.dumps({
                "profile_id": "test-v0.2",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        (tmp_path / "profile_v0_3.json").write_text(
            json.dumps({
                "profile_id": "test-v0.3",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        selected, _ = find_validated_track_profile(
            tmp_path,
            track="Test Track",
            layout="Test Layout",
        )
        assert selected["profile_id"] == "test-v0.3"

    def test_v09_and_v010_same_track_layout_selects_v010(self, tmp_path: Path):
        """v0.9 + v0.10 with same track/layout → selects v0.10 (semantic, not lex)."""
        (tmp_path / "profile_v0_9.json").write_text(
            json.dumps({
                "profile_id": "test-v0.9",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        (tmp_path / "profile_v0_10.json").write_text(
            json.dumps({
                "profile_id": "test-v0.10",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        selected, _ = find_validated_track_profile(
            tmp_path,
            track="Test Track",
            layout="Test Layout",
        )
        assert selected["profile_id"] == "test-v0.10"

    def test_one_exact_match_unchanged(self, tmp_path: Path):
        """Single exact match → no version disambiguation needed."""
        (tmp_path / "profile.json").write_text(
            json.dumps({
                "profile_id": "single-match",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        selected, _ = find_validated_track_profile(
            tmp_path,
            track="Test Track",
            layout="Test Layout",
        )
        assert selected["profile_id"] == "single-match"

    def test_same_highest_version_twice_fails_ambiguity(self, tmp_path: Path):
        """Two distinct profiles with identical highest version → fail closed."""
        (tmp_path / "profile_a.json").write_text(
            json.dumps({
                "profile_id": "test-a-v0.3",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1a", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        (tmp_path / "profile_b.json").write_text(
            json.dumps({
                "profile_id": "test-b-v0.3",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1b", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Múltiples perfiles distintos"):
            find_validated_track_profile(
                tmp_path,
                track="Test Track",
                layout="Test Layout",
            )

    def test_malformed_duplicate_versions_fail_closed(self, tmp_path: Path):
        """Profiles without parseable version in duplicate → fail closed."""
        (tmp_path / "profile_bad1.json").write_text(
            json.dumps({
                "profile_id": "nover",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1a", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        (tmp_path / "profile_bad2.json").write_text(
            json.dumps({
                "profile_id": "also-nover",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1b", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="No se pudo determinar la versión"):
            find_validated_track_profile(
                tmp_path,
                track="Test Track",
                layout="Test Layout",
            )

    def test_different_layout_never_compete(self, tmp_path: Path):
        """Profiles with different layout must never compete regardless of version."""
        (tmp_path / "profile_layout1.json").write_text(
            json.dumps({
                "profile_id": "test-v0.5",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Layout A",
                "turns": [
                    {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        (tmp_path / "profile_layout2.json").write_text(
            json.dumps({
                "profile_id": "test-v0.9",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Layout B",
                "turns": [
                    {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        selected, _ = find_validated_track_profile(
            tmp_path,
            track="Test Track",
            layout="Layout A",
        )
        assert selected["profile_id"] == "test-v0.5"

        selected_b, _ = find_validated_track_profile(
            tmp_path,
            track="Test Track",
            layout="Layout B",
        )
        assert selected_b["profile_id"] == "test-v0.9"

    def test_shadow_v2_subdir_never_production_candidate(self, tmp_path: Path):
        """Profiles inside shadow_v2/ must never be production candidates."""
        shadow_dir = tmp_path / "shadow_v2"
        shadow_dir.mkdir()
        (shadow_dir / "profile_shadow.json").write_text(
            json.dumps({
                "profile_id": "shadow-v0.3",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        (tmp_path / "profile_main.json").write_text(
            json.dumps({
                "profile_id": "main-v0.2",
                "status": "VALIDATED_MULTI_SESSION",
                "track": "Test Track",
                "layout": "Test Layout",
                "turns": [
                    {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                ],
            }),
            encoding="utf-8",
        )
        selected, _ = find_validated_track_profile(
            tmp_path,
            track="Test Track",
            layout="Test Layout",
        )
        # shadow_v2 is a subdirectory, so glob("*.json") only matches profile_main.json
        assert selected["profile_id"] == "main-v0.2"
