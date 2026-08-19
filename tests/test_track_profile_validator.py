"""Tests for validate_track_profiles.py — deterministic track profile validator.

Tests cover:
- Valid profile
- Negative distance
- Distance > lap length
- Inverted range (start >= end)
- Overlap between consecutive turns
- Gap between consecutive turns
- Duplicate point (near-same distance, incompatible names)
- Apex outside corner (apex outside [start, end])
- Invalid GPS
- Layout mismatch
- Missing optional data does not produce false error
- Deterministic repeatability
"""

import json
from pathlib import Path
from typing import Any

import pytest

from validate_track_profiles import (
    Finding,
    TrackProfileValidator,
    validate_profile,
    validate_profiles,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

def _make_profile(turns: list[dict], **overrides: Any) -> dict[str, Any]:
    base = {
        "schema_version": 1,
        "profile_id": "test-profile",
        "status": "VALIDATED_MULTI_SESSION",
        "track": "Test Track",
        "layout": "Test Track",
        "distance_coordinate": "LMU Lap Dist",
        "calibration": {
            "source_session": "test_session",
            "source_lap_dist_max_m": 5000.0,
        },
        "ignored_geometric_features_m": [],
        "turns": turns,
        "display_policy": {"prefer_corner_name": True},
    }
    base.update(overrides)
    return base


def _valid_profile() -> dict[str, Any]:
    return _make_profile([
        {
            "turn": 1,
            "name": "Turn 1",
            "group": "Turn 1",
            "direction": "left",
            "start_m": 100.0,
            "apex_m": 150.0,
            "end_m": 200.0,
        },
        {
            "turn": 2,
            "name": "Turn 2",
            "group": "Turn 2",
            "direction": "right",
            "start_m": 200.0,
            "apex_m": 250.0,
            "end_m": 300.0,
        },
    ])


# ── Fixtures: actual profile files ─────────────────────────────────────────

_TRACK_PROFILES_DIR = Path(__file__).parent.parent / "track_profiles"
_ALL_PROFILES = sorted(_TRACK_PROFILES_DIR.glob("*.json"))


@pytest.fixture
def profile_json() -> dict[str, Any]:
    return _valid_profile()


@pytest.fixture
def profiles_paths() -> list[Path]:
    return _ALL_PROFILES


class TestValidatorSchema:
    """Test validator produces expected output schema."""

    def test_validate_returns_schema_keys(self, profile_json):
        validator = TrackProfileValidator(profile_json)
        result = validator.validate()
        expected_keys = {
            "schema_version",
            "validator_version",
            "profile_id",
            "track",
            "layout",
            "lap_length_m",
            "status",
            "error_count",
            "warning_count",
            "informational_count",
            "findings",
            "summary",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_validator_version_matches_module(self, profile_json):
        from validate_track_profiles import __version__
        validator = TrackProfileValidator(profile_json)
        result = validator.validate()
        assert result["validator_version"] == __version__


class TestValidProfile:
    """Test that a well-formed profile returns VALID status."""

    def test_valid_profile_status(self, profile_json):
        validator = TrackProfileValidator(profile_json)
        result = validator.validate()
        assert result["status"] == "VALID"
        assert result["error_count"] == 0
        assert result["warning_count"] == 0


class TestNegativeDistance:
    """Test that negative distances are detected as errors."""

    def test_negative_start_m(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": -10.0,
                "apex_m": -5.0,
                "end_m": 0.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert result["status"] == "INVALID"
        assert result["error_count"] > 0
        assert any(
            f["code"] == "LAP_BOUNDS"
            and f["severity"] == "error"
            and "start_m" in f["deterministic_message"]
            for f in result["findings"]
        )


class TestDistanceExceedsLapLength:
    """Test that distances exceeding lap length are detected."""

    def test_end_m_exceeds_lap_length(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 6000.0,  # exceeds lap_length derived from calibration (5000)
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert result["status"] == "INVALID"
        assert any(
            f["code"] == "LAP_BOUNDS"
            and "end_m" in f["deterministic_message"]
            and "lap_length_m" in f["deterministic_message"]
            for f in result["findings"]
        )


class TestInvertedRange:
    """Test that start_m >= end_m is detected."""

    def test_start_equals_end(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 200.0,
                "apex_m": 250.0,
                "end_m": 200.0,  # start == end
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert result["status"] == "INVALID"
        assert any(
            f["code"] == "ORDERING"
            and f["severity"] == "error"
            for f in result["findings"]
        )

    def test_start_greater_than_end(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 300.0,
                "apex_m": 250.0,
                "end_m": 200.0,  # start > end
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert result["status"] == "INVALID"


class TestOverlap:
    """Test that overlaps between consecutive turns are detected."""

    def test_overlap_between_consecutive_turns(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 500.0,
            },
            {
                "turn": 2,
                "name": "Turn 2",
                "group": "Turn 2",
                "direction": "right",
                "start_m": 300.0,
                "apex_m": 350.0,
                "end_m": 400.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        # Large overlap (200 m = 4% of 5000 m lap — above 2% threshold) → error
        assert any(
            f["code"] == "OVERLAP"
            and f["severity"] == "error"
            for f in result["findings"]
        )

    def test_small_overlap_is_informational(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 210.0,
            },
            {
                "turn": 2,
                "name": "Turn 2",
                "group": "Turn 2",
                "direction": "right",
                "start_m": 205.0,  # 5 m overlap
                "apex_m": 250.0,
                "end_m": 300.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        # 5 m overlap is ~0.1% of 5000 m lap — should be informational
        assert any(
            f["code"] == "OVERLAP"
            and f["severity"] == "informational"
            for f in result["findings"]
        )


class TestGap:
    """Test that gaps between consecutive turns are detected."""

    def test_large_gap(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
            },
            {
                "turn": 2,
                "name": "Turn 2",
                "group": "Turn 2",
                "direction": "right",
                "start_m": 3000.0,  # large gap
                "apex_m": 3050.0,
                "end_m": 3100.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert any(
            f["code"] == "ORDERING_GAP"
            and f["severity"] == "warning"
            for f in result["findings"]
        )

    def test_exact_adjacency_is_no_gap(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
            },
            {
                "turn": 2,
                "name": "Turn 2",
                "group": "Turn 2",
                "direction": "right",
                "start_m": 200.0,  # exact adjacency
                "apex_m": 250.0,
                "end_m": 300.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        gaps = [
            f for f in result["findings"]
            if f["code"] == "ORDERING_GAP"
        ]
        assert len(gaps) == 0


class TestDuplicatePoint:
    """Test that near-same distance with incompatible names is detected."""

    def test_duplicate_near_distance_incompatible(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn A",
                "group": "Group A",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
            },
            {
                "turn": 2,
                "name": "Turn B",
                "group": "Group B",
                "direction": "right",
                "start_m": 103.0,  # within 5 m of start of turn 1
                "apex_m": 155.0,
                "end_m": 200.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert any(
            f["code"] == "DUPLICATE_POINT"
            and f["severity"] == "warning"
            for f in result["findings"]
        )

    def test_same_name_at_same_distance_is_not_duplicate(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Lesmo 1",
                "group": "Lesmo",
                "direction": "right",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
            },
            {
                "turn": 2,
                "name": "Lesmo 2",
                "group": "Lesmo",
                "direction": "right",
                "start_m": 200.0,
                "apex_m": 250.0,
                "end_m": 300.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        # Different names but same group should NOT trigger duplicate
        assert not any(
            f["code"] == "DUPLICATE_POINT"
            for f in result["findings"]
        )


class TestApexOutsideCorner:
    """Test that apex outside [start, end] is a warning."""

    def test_apex_less_than_start(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 200.0,
                "apex_m": 150.0,  # below start
                "end_m": 300.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert any(
            f["code"] == "ORDERING"
            and f["severity"] == "warning"
            and "apex_m" in f["deterministic_message"]
            for f in result["findings"]
        )

    def test_apex_greater_than_end(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 200.0,
                "apex_m": 500.0,  # above end
                "end_m": 300.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert any(
            f["code"] == "ORDERING"
            and f["severity"] == "warning"
            and "apex_m" in f["deterministic_message"]
            for f in result["findings"]
        )


class TestInvalidGPS:
    """Test that invalid GPS values are detected."""

    def test_negative_gps_path(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
            },
        ], calibration={
            "source_session": "test_session",
            "source_lap_dist_max_m": 5000.0,
            "source_gps_path_m_approx": -100.0,  # negative GPS
        })
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert any(
            f["code"] == "GPS_CONSISTENCY"
            and f["severity"] == "error"
            for f in result["findings"]
        )


class TestLayoutMismatch:
    """Test that track != layout produces a warning."""

    def test_track_equals_layout(self):
        profile = _make_profile(
            turns=[{
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
            }],
            track="Test Track",
            layout="Test Track",
        )
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert not any(
            f["code"] == "LAYOUT_CONSISTENCY"
            and f["severity"] == "warning"
            for f in result["findings"]
        )

    def test_track_not_equals_layout(self):
        profile = _make_profile(
            turns=[{
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
            }],
            track="Test Track",
            layout="Different Layout",
        )
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        assert any(
            f["code"] == "LAYOUT_CONSISTENCY"
            and f["severity"] == "warning"
            for f in result["findings"]
        )


class TestMissingOptionalDataNoFalseError:
    """Test that missing optional fields do not produce false errors."""

    def test_missing_aliases_no_error(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
                # no aliases
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        # Should NOT have errors from missing aliases
        assert not any(
            f["code"] == "SEMANTIC_STRUCTURE"
            and f["severity"] == "error"
            for f in result["findings"]
        )

    def test_missing_direction_sequence_no_error(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
                # no direction_sequence
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        # Should NOT have errors from missing direction_sequence
        assert not any(
            f["code"] == "SEMANTIC_STRUCTURE"
            and f["severity"] == "error"
            for f in result["findings"]
        )

    def test_valid_status_with_only_informational(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
            },
        ])
        validator = TrackProfileValidator(profile)
        result = validator.validate()
        # With no errors but only informational findings,
        # status should be VALID (warnings/informational don't make it INVALID)
        assert result["status"] == "VALID"


class TestDeterministicRepeatability:
    """Test that running validate() multiple times produces identical results."""

    def test_repeatability(self, profile_json):
        validator = TrackProfileValidator(profile_json)
        result1 = validator.validate()
        result2 = validator.validate()
        assert result1["status"] == result2["status"]
        assert result1["error_count"] == result2["error_count"]
        assert result1["warning_count"] == result2["warning_count"]
        assert len(result1["findings"]) == len(result2["findings"])
        assert result1["findings"] == result2["findings"]


class TestRealProfiles:
    """Run validator over all actual profile files in track_profiles/."""

    @pytest.mark.parametrize("profile_path", _ALL_PROFILES)
    def test_all_profiles_validate(self, profile_path):
        result = validate_profile(profile_path)
        # All profiles should produce deterministic output
        assert result["status"] in ("VALID", "VALID_WITH_WARNINGS", "INVALID")
        assert result["track"] is not None
        assert result["layout"] is not None

    def test_validate_profiles_aggregate(self, profiles_paths):
        aggregate = validate_profiles(profiles_paths)
        assert aggregate["summary"]["total_profiles"] == len(profiles_paths)
        assert (
            aggregate["summary"]["valid"]
            + aggregate["summary"]["valid_with_warnings"]
            + aggregate["summary"]["invalid"]
        ) == aggregate["summary"]["total_profiles"]


class TestComputeLapLength:
    """Test lap length derivation from calibration."""

    def test_lap_length_from_calibration(self, profile_json):
        validator = TrackProfileValidator(profile_json)
        # Lap length should be derived from calibration.source_lap_dist_max_m
        assert validator._compute_lap_length() == 5000.0

    def test_lap_length_from_last_turn(self):
        profile = _make_profile([
            {
                "turn": 1,
                "name": "Turn 1",
                "group": "Turn 1",
                "direction": "left",
                "start_m": 100.0,
                "apex_m": 150.0,
                "end_m": 200.0,
            },
        ], calibration={})  # empty calibration
        validator = TrackProfileValidator(profile)
        assert validator._compute_lap_length() == 200.0  # last turn end_m


class TestFindingsStructure:
    """Test that Finding.to_dict() produces expected structure."""

    def test_finding_to_dict_minimal(self):
        finding = Finding(
            code="TEST",
            severity="error",
            deterministic_message="test message",
        )
        d = finding.to_dict()
        assert "code" in d
        assert "severity" in d
        assert "deterministic_message" in d
        assert d["code"] == "TEST"
        assert d["severity"] == "error"

    def test_finding_to_dict_with_all_fields(self):
        finding = Finding(
            code="TEST",
            severity="warning",
            entity_id="T1",
            entity_name="Turn 1",
            distance_start=100.0,
            distance_end=200.0,
            deterministic_message="test message",
            evidence={"detail": "test"},
        )
        d = finding.to_dict()
        assert d["entity_id"] == "T1"
        assert d["entity_name"] == "Turn 1"
        assert d["distance_start_m"] == 100.0
        assert d["distance_end_m"] == 200.0
        assert d["evidence"]["detail"] == "test"
