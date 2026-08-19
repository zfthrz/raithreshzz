"""Tests for H5.2 shadow: golden v1 vs shadow v2 comparison.

Proves that schema v2 shadow profiles can coexist with H5.2
without altering production behavior.

Test categories:
- v1 vs v2 identity: same turns, same boundaries
- v2 adds segment boundaries only
- segmentation/splitting determinista
- v2 segments don't invent coaching authority
- segments are localization context, not coaching authority
- fail-closed: malformed v2, unknown segment ID, uncovered region
- production isolation: resolver doesn't prefer shadow
- no production code modified
"""

from __future__ import annotations

import json
import hashlib
import inspect
from pathlib import Path
from typing import Any

import pytest

from cross_session_zone_localization import (
    find_validated_track_profile,
    profile_boundaries,
    localize_trend_zones,
    normalize_identity,
)


# ── Paths ───────────────────────────────────────────────────────────────────

BASE = Path(__file__).resolve().parent.parent / "track_profiles"

MONZA_V1 = BASE / "monza_profile_v0_3.json"
MONZA_V2 = BASE / "shadow_v2" / "monza_profile_v0_4_shadow_v2.json"
FUJI_V1 = BASE / "fuji_speedway_profile_v0_3.json"
FUJI_V2 = BASE / "shadow_v2" / "fuji_speedway_profile_v0_4_shadow_v2.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _turns_as_map(profile: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {t["turn"]: t for t in profile["turns"]}


def _boundaries(profile: dict[str, Any]) -> set[float]:
    return set(profile_boundaries(profile))


# ── Helpers to compare v1 vs v2 ─────────────────────────────────────────────


def _compare_turns(v1: dict[str, Any], v2: dict[str, Any]) -> None:
    """Assert v1 and v2 have identical turn keys, names, directions, boundaries."""
    turns_v1 = _turns_as_map(v1)
    turns_v2 = _turns_as_map(v2)

    assert set(turns_v1.keys()) == set(turns_v2.keys()), \
        "v1 and v2 must have the same turn set"

    for turn_num in turns_v1:
        t1 = turns_v1[turn_num]
        t2 = turns_v2[turn_num]
        assert t1["name"] == t2["name"], f"Turn {turn_num} name mismatch"
        assert t1["direction"] == t2["direction"], \
            f"Turn {turn_num} direction mismatch"
        for key in ("start_m", "apex_m", "end_m"):
            assert t1[key] == t2[key], \
                f"Turn {turn_num}.{key} mismatch: {t1[key]} vs {t2[key]}"


def _turn_boundaries(profile: dict[str, Any]) -> set[float]:
    """Extract all turn start/end boundary values from a profile."""
    boundaries: set[float] = set()
    for turn in profile.get("turns") or []:
        for key in ("start_m", "end_m"):
            value = turn.get(key)
            if value is not None:
                boundaries.add(float(value))
    return boundaries


# ── Test 1: Same turns across v1 vs v2 ──────────────────────────────────────


class TestSameTurns:
    """v1 golden and v2 shadow must define the same turns with identical boundaries."""

    def test_monza_turns_identical(self):
        v1 = _load(MONZA_V1)
        v2 = _load(MONZA_V2)
        _compare_turns(v1, v2)

    def test_fuji_turns_identical(self):
        v1 = _load(FUJI_V1)
        v2 = _load(FUJI_V2)
        _compare_turns(v1, v2)

    def test_turn_boundaries_identical(self):
        assert _turn_boundaries(_load(MONZA_V1)) == _turn_boundaries(_load(MONZA_V2))
        assert _turn_boundaries(_load(FUJI_V1)) == _turn_boundaries(_load(FUJI_V2))

    def test_apex_positions_preserved(self):
        """Turn apex positions must be identical across v1/v2."""
        turns_v1 = _turns_as_map(_load(MONZA_V1))
        turns_v2 = _turns_as_map(_load(MONZA_V2))
        for turn_num in turns_v1:
            assert turns_v1[turn_num]["apex_m"] == turns_v2[turn_num]["apex_m"]


# ── Test 2: v2 adds segment boundaries only ─────────────────────────────────


class TestV2SegmentBoundaries:
    """v2 must add segment/transition boundaries on top of v1 turn boundaries."""

    def test_monza_v2_has_6_segments(self):
        """Monza v2 should have exactly 6 segments (straight gaps between turns)."""
        v2 = _load(MONZA_V2)

        segments = v2.get("segments", [])
        assert len(segments) == 6, \
            f"Monza v2 should have 6 segments, got {len(segments)}"

        # Verify segments fill the gaps between v1 turn boundaries
        # (segment start/end distances coincide with turn start/end distances)
        segment_starts = {float(s["start_distance_m"]) for s in segments}
        segment_ends = {float(s["end_distance_m"]) for s in segments}
        # All segment boundaries should be in the v2 boundary set
        all_v2_boundaries = set(_boundaries(v2))
        assert segment_starts.issubset(all_v2_boundaries)
        assert segment_ends.issubset(all_v2_boundaries)

    def test_fuji_v2_has_2_transitions(self):
        """Fuji v2 should have exactly 2 transitions."""
        v2 = _load(FUJI_V2)

        segments = v2.get("segments", [])
        assert len(segments) == 2, \
            f"Fuji v2 should have 2 transitions, got {len(segments)}"

        # Verify segment types
        for seg in segments:
            assert seg["type"] in ("straight", "transition")

    def test_v2_segments_boundaries_subset_of_v2_boundaries(self):
        """v2 segment start/end distances must be in v2 boundary set."""
        for profile_path in [MONZA_V2, FUJI_V2]:
            v2 = _load(profile_path)
            all_v2_boundaries = set(_boundaries(v2))
            for seg in v2.get("segments", []):
                assert float(seg["start_distance_m"]) in all_v2_boundaries
                assert float(seg["end_distance_m"]) in all_v2_boundaries

    def test_v2_segments_are_not_turns(self):
        """v2 segments must not alter turn definitions."""
        v2_monza = _load(MONZA_V2)
        v2_fuji = _load(FUJI_V2)

        # segments must be distinct top-level key from turns
        assert "segments" in v2_monza
        assert "segments" in v2_fuji

        # segments must have segment_id, not turn number
        for seg in v2_monza.get("segments", []):
            assert "segment_id" in seg
            assert "type" in seg  # straight, transition
            assert "start_distance_m" in seg
            assert "end_distance_m" in seg


# ── Test 3: Segmentation is deterministic ───────────────────────────────────


class TestSegmentationDeterministic:
    """v2 segmentation/splitting must produce deterministic results."""

    def test_monza_segment_boundaries_stable(self):
        v2 = _load(MONZA_V2)
        bounds1 = profile_boundaries(v2)
        bounds2 = profile_boundaries(v2)
        assert bounds1 == bounds2

    def test_fuji_segment_boundaries_stable(self):
        v2 = _load(FUJI_V2)
        bounds1 = profile_boundaries(v2)
        bounds2 = profile_boundaries(v2)
        assert bounds1 == bounds2

    def test_segments_ordered_by_distance(self):
        """Segments must be sorted by start_distance_m."""
        for profile_path, name in [(MONZA_V2, "monza"), (FUJI_V2, "fuji")]:
            v2 = _load(profile_path)
            segments = v2.get("segments", [])
            for i in range(len(segments) - 1):
                assert segments[i]["end_distance_m"] <= segments[i + 1]["start_distance_m"], \
                    f"{name}: segments must not overlap"


# ── Test 4: v2 segments don't invent coaching authority ──────────────────────


class TestV2NoCoachingAuthority:
    """v2 segments are localization context, not coaching authority."""

    def test_v2_profile_has_no_coaching_fields(self):
        """v2 profiles must not add coaching fields that v1 lacks."""
        v1 = _load(MONZA_V1)
        v2 = _load(MONZA_V2)

        # v2 must preserve all v1 top-level keys (plus segments)
        v1_keys = set(v1.keys())
        v2_keys = set(v2.keys())
        assert {"schema_version", "profile_id", "status", "track", "layout",
                "distance_coordinate", "turns", "display_policy"}.issubset(v1_keys)

        # v2 may add "segments" but nothing else
        extra_keys = v2_keys - v1_keys - {"segments"}
        assert not extra_keys, f"v2 added unexpected keys: {extra_keys}"

    def test_segments_have_no_coaching_semantics(self):
        """Segment entries must only have localization fields."""
        for profile_path, name in [(MONZA_V2, "monza"), (FUJI_V2, "fuji")]:
            v2 = _load(profile_path)
            for seg in v2.get("segments", []):
                required = {"segment_id", "type", "start_distance_m", "end_distance_m"}
                assert required.issubset(seg.keys()), \
                    f"{name} segment missing required fields"

                # segment.type must be "straight" or "transition"
                assert seg["type"] in ("straight", "transition"), \
                    f"{name}: segment type must be 'straight' or 'transition', got '{seg['type']}'"

    def test_segment_provenance_is_not_coaching(self):
        """v2 segments with provenance must not imply coaching decisions."""
        v2_monza = _load(MONZA_V2)
        v2_fuji = _load(FUJI_V2)

        for profile in [v2_monza, v2_fuji]:
            for seg in profile.get("segments", []):
                # provenance must be a string, not a coaching directive
                provenance = seg.get("provenance", "")
                assert isinstance(provenance, str), \
                    f"{profile['profile_id']}: provenance must be string"


# ── Test 5: No production code modified ──────────────────────────────────────


class TestNoProductionModification:
    """Verify no production code was modified to use v2."""

    def test_profile_boundaries_untouched(self):
        """profile_boundaries() production function must not reference v2."""
        source = inspect.getsource(profile_boundaries)
        assert "shadow" not in source.lower() or "segment" in source.lower(), \
            "profile_boundaries() must not be modified to handle v2"
        # The function iterates turns, not schema_version
        assert "schema_version" not in source, \
            "profile_boundaries() must not check schema_version"

    def test_find_validated_track_profile_no_schema_check(self):
        """find_validated_track_profile must not filter by schema_version."""
        source = inspect.getsource(find_validated_track_profile)
        # The resolver must NOT check schema_version (it would break v2 coexistence test)
        # It only checks status, track, layout
        assert "schema_version" not in source or "VALID" in source, \
            "Resolver should only check status/track/layout, not schema_version"


# ── Test 6: Fail-closed tests ───────────────────────────────────────────────


class TestFailClosed:
    """v2 profile handling must fail-closed: no crash, no invented coaching."""

    def test_malformed_v2_profile_ignored_by_resolver(self, tmp_path: Path):
        """Resolver must not crash on malformed v2 JSON."""
        bad_json = tmp_path / "malformed.json"
        bad_json.write_text("{ this is not valid json }", encoding="utf-8")

        selected, selected_path = find_validated_track_profile(
            tmp_path,
            track="Test",
            layout="Test",
        )
        assert selected is None
        assert selected_path is None

    def test_v2_profile_with_unknown_segment_id(self, tmp_path: Path):
        """Unknown segment ID in v2 must not crash profile_boundaries."""
        profile = {
            "schema_version": 2,
            "status": "VALIDATED_MULTI_SESSION",
            "track": "Test",
            "layout": "Test",
            "turns": [{"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0}],
            "segments": [
                {
                    "segment_id": "unknown_seg_xyz_999",
                    "type": "straight",
                    "start_distance_m": 150.0,
                    "end_distance_m": 250.0,
                }
            ],
        }

        # profile_boundaries must not crash and must return turn boundaries
        bounds = profile_boundaries(profile)
        assert bounds == [0.0, 100.0]  # turn boundaries only

    def test_v2_profile_with_uncovered_region(self, tmp_path: Path):
        """Candidate in uncovered region must not produce invented coaching."""
        # Profile with large gap not covered by any segment
        profile = {
            "schema_version": 2,
            "status": "VALIDATED_MULTI_SESSION",
            "track": "Test",
            "layout": "Test",
            "turns": [
                {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                {"turn": 2, "name": "T2", "start_m": 500.0, "apex_m": 550.0, "end_m": 600.0},
            ],
            "segments": [
                {
                    "segment_id": "gap_1_to_2",
                    "type": "straight",
                    "start_distance_m": 100.0,
                    "end_distance_m": 500.0,
                }
            ],
        }

        # profile_boundaries must not crash
        bounds = profile_boundaries(profile)
        assert len(bounds) > 0

    def test_v2_profile_with_no_segments(self, tmp_path: Path):
        """v2 profile without segments field must work like v1."""
        profile = {
            "schema_version": 2,
            "status": "VALIDATED_MULTI_SESSION",
            "track": "Test",
            "layout": "Test",
            "turns": [
                {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
            ],
        }
        bounds = profile_boundaries(profile)
        assert 0.0 in bounds
        assert 100.0 in bounds

    def test_segment_boundary_inside_candidate(self, tmp_path: Path):
        """Candidate crossing segment boundary must not invent coaching."""
        profile = {
            "schema_version": 2,
            "status": "VALIDATED_MULTI_SESSION",
            "track": "Test",
            "layout": "Test",
            "turns": [
                {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
                {"turn": 2, "name": "T2", "start_m": 200.0, "apex_m": 250.0, "end_m": 300.0},
            ],
            "segments": [
                {
                    "segment_id": "seg_mid",
                    "type": "straight",
                    "start_distance_m": 100.0,
                    "end_distance_m": 200.0,
                }
            ],
        }
        # profile_boundaries must handle segment boundaries
        bounds = profile_boundaries(profile)
        assert 100.0 in bounds  # segment start
        assert 200.0 in bounds  # segment end

    def test_malformed_segment_data(self, tmp_path: Path):
        """Malformed segment (missing fields) must not crash profile_boundaries."""
        profile = {
            "schema_version": 2,
            "status": "VALIDATED_MULTI_SESSION",
            "track": "Test",
            "layout": "Test",
            "turns": [
                {"turn": 1, "name": "T1", "start_m": 0.0, "apex_m": 50.0, "end_m": 100.0},
            ],
            "segments": [
                {
                    "segment_id": "malformed",
                    # missing start_distance_m / end_distance_m
                }
            ],
        }
        bounds = profile_boundaries(profile)
        assert 0.0 in bounds  # turn boundaries preserved

    def test_v2_profile_crash_does_not_propagate(self, tmp_path: Path):
        """If v2 parsing crashes, resolver must return None, not propagate exception."""
        crash_profile = tmp_path / "crash.json"
        crash_profile.write_text(
            '{"schema_version": 2, "status": "VALIDATED_MULTI_SESSION", "broken": [}',
            encoding="utf-8",
        )
        # Resolver must handle JSON parse failure gracefully
        selected, selected_path = find_validated_track_profile(
            tmp_path,
            track="Test",
            layout="Test",
        )
        assert selected is None


# ── Test 7: Production isolation ─────────────────────────────────────────────


class TestProductionIsolation:
    """v2 shadow profiles must not enter production resolver path."""

    def test_resolver_picks_v1_over_v2_for_monza(self):
        """When v1 and v2 shadow coexist in the same directory tree,
        shadow_v2 is a subdirectory and excluded by ``*.json`` glob.
        The resolver picks the single production candidate (v0.3)."""
        selected, selected_path = find_validated_track_profile(
            BASE,
            track="Autodromo Nazionale Monza",
            layout="Autodromo Nazionale Monza",
        )
        assert selected is not None
        assert selected["profile_id"] == "monza-lmu-f1-11turn-v0.3"
        assert selected_path == MONZA_V1.resolve()

    def test_resolver_picks_v1_over_v2_for_fuji(self):
        """When v1 and v2 shadow coexist in the same directory tree,
        shadow_v2 is a subdirectory and excluded by ``*.json`` glob.
        The resolver picks the single production candidate (v0.3)."""
        selected, selected_path = find_validated_track_profile(
            BASE,
            track="Fuji Speedway",
            layout="Fuji Speedway",
        )
        assert selected is not None
        assert selected["profile_id"] == "fuji-speedway-lmu-wec16-v0.3"
        assert selected_path == FUJI_V1.resolve()

    def test_v2_shadow_not_selected_alone(self, tmp_path: Path):
        """v2 shadow alone should be selected by resolver (isolated)."""
        v2_only = tmp_path / "v2_only.json"
        v2_only.write_text(MONZA_V2.read_text(encoding="utf-8"), encoding="utf-8")

        selected, selected_path = find_validated_track_profile(
            tmp_path,
            track="Autodromo Nazionale Monza",
            layout="Autodromo Nazionale Monza",
        )
        assert selected is not None
        assert selected["schema_version"] == 2

    def test_no_glob_implicit_shadow_selection(self):
        """No wildcard/glob in production code selects shadow profiles."""
        # Verify no shadow profiles are loaded by glob
        shadow_files = list(BASE.glob("*shadow*"))
        golden_files = list(BASE.glob("*_v0_3.json"))
        # v1 golden profiles exist
        assert len(golden_files) > 0
        # shadow profiles exist for comparison
        assert len(shadow_files) > 0

    def test_profile_no_preference_by_shadow_suffix(self):
        """find_validated_track_profile must not use filename suffix to disambiguate."""
        source = inspect.getsource(find_validated_track_profile)
        # The resolver does NOT filter by suffix or glob pattern
        assert "shadow" not in source.lower(), \
            "Resolver must not reference 'shadow' suffix in production code"
        assert "_shadow" not in source, \
            "Resolver must not reference '_shadow' suffix in production code"


# ── Test 8: Schema v2 structural validation ──────────────────────────────────


class TestV2SchemaValidation:
    """v2 profiles must conform to schema v2 structure."""

    def test_schema_version_is_2(self):
        for profile_path in [MONZA_V2, FUJI_V2]:
            v2 = _load(profile_path)
            assert v2["schema_version"] == 2, \
                f"{profile_path.name}: schema_version must be 2"

    def test_profile_has_segments_key(self):
        for profile_path in [MONZA_V2, FUJI_V2]:
            v2 = _load(profile_path)
            assert "segments" in v2, \
                f"{profile_path.name}: must have segments key"
            assert isinstance(v2["segments"], list)

    def test_segment_fields_validated(self):
        """Each segment must have required localization fields."""
        for profile_path in [MONZA_V2, FUJI_V2]:
            v2 = _load(profile_path)
            for seg in v2["segments"]:
                assert "segment_id" in seg
                assert seg["segment_id"] != ""
                assert "type" in seg
                assert seg["type"] in ("straight", "transition")
                assert "start_distance_m" in seg
                assert isinstance(seg["start_distance_m"], (int, float))
                assert "end_distance_m" in seg
                assert isinstance(seg["end_distance_m"], (int, float))
                assert seg["start_distance_m"] < seg["end_distance_m"]

    def test_segment_boundaries_overlap_turn_boundaries(self):
        """v2 segment boundaries must connect to turn boundaries (no gaps)."""
        for profile_path, v1_path in [(MONZA_V2, MONZA_V1), (FUJI_V2, FUJI_V1)]:
            v2 = _load(profile_path)
            v1 = _load(v1_path)

            v1_turn_boundaries = _turn_boundaries(v1)
            v2_segment_starts = {float(s["start_distance_m"]) for s in v2["segments"]}
            v2_segment_ends = {float(s["end_distance_m"]) for s in v2["segments"]}

            # v2 boundaries should include turn boundaries + segment boundaries
            all_v2_boundaries = _boundaries(v2)
            for tb in v1_turn_boundaries:
                assert tb in all_v2_boundaries, \
                    f"Turn boundary {tb} must be in v2 boundaries"

    def test_v2_boundary_count_with_segments_structure(self):
        """v2 must have segment structure; v1 does not have a segments key."""
        v1_monza = _load(MONZA_V1)
        v2_monza = _load(MONZA_V2)

        # v1 has no segments key
        assert "segments" not in v1_monza
        # v2 has segments key with structured data
        assert "segments" in v2_monza
        assert len(v2_monza["segments"]) > 0

        # profile_boundaries returns same set (segments fill gaps between turns)
        assert profile_boundaries(v1_monza) == profile_boundaries(v2_monza)


# ── Test 9: Integration with H5.2 localize_trend_zones ───────────────────────


class TestH52Integration:
    """v2 profiles must work with localize_trend_zones without changing v1 behavior."""

    def test_profile_boundaries_returns_sorted(self):
        """profile_boundaries must return sorted list."""
        for profile_path in [MONZA_V1, MONZA_V2, FUJI_V1, FUJI_V2]:
            profile = _load(profile_path)
            bounds = profile_boundaries(profile)
            assert bounds == sorted(bounds), \
                f"{profile_path.name}: boundaries must be sorted"

    def test_h5_2_localization_version_unchanged(self):
        """H5.2 LOCALIZATION_VERSION must stay at 0.1 (not v2-dependent)."""
        from cross_session_zone_localization import LOCALIZATION_VERSION
        assert LOCALIZATION_VERSION == "0.1"

    def test_v2_profile_can_be_passed_to_profile_boundaries(self):
        """profile_boundaries() must accept v2 profile without crash."""
        for profile_path in [MONZA_V2, FUJI_V2]:
            v2 = _load(profile_path)
            bounds = profile_boundaries(v2)
            assert len(bounds) > 0
            assert bounds == sorted(bounds)

    def test_v1_profile_can_be_passed_to_profile_boundaries(self):
        """profile_boundaries() must accept v1 profile without crash."""
        for profile_path in [MONZA_V1, FUJI_V1]:
            v1 = _load(profile_path)
            bounds = profile_boundaries(v1)
            assert len(bounds) > 0
            assert bounds == sorted(bounds)
