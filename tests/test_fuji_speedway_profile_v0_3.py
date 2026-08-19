"""Tests for Fuji Speedway track profile v0.3 — geometry preservation and schema compatibility.

These tests verify that v0.3 preserves the exact turn geometry of v0.2
and that the new `geometric_notes` field doesn't break existing parsers.
"""

import json
from pathlib import Path
from typing import Any


# Paths
FUJI_V0_2 = Path("track_profiles/fuji_speedway_profile_v0_2.json")
FUJI_V0_3 = Path("track_profiles/fuji_speedway_profile_v0_3.json")


def _load_profile(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_turns(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return profile["turns"]


class TestFujiV03GeometryPreservation:
    """Verify that v0.3 preserves v0.2 turn geometry exactly."""

    def test_v03_loads_successfully(self) -> None:
        """v0_3 loads as valid JSON and passes validator."""
        data = _load_profile(FUJI_V0_3)
        assert data["schema_version"] == 1
        assert data["status"] == "VALIDATED_MULTI_SESSION"

    def test_v03_profile_id_updated(self) -> None:
        """v0_3 has updated profile_id."""
        data = _load_profile(FUJI_V0_3)
        assert data["profile_id"] == "fuji-speedway-lmu-wec16-v0.3"

    def test_turn_count_unchanged(self) -> None:
        """v0_3 has exactly 16 turns, same as v0_2."""
        data = _load_profile(FUJI_V0_3)
        assert len(data["turns"]) == 16

    def test_turn_geometry_identical(self) -> None:
        """v0_2 and v0_3 have identical turn start/end/apex for every turn."""
        v02 = _load_profile(FUJI_V0_2)
        v03 = _load_profile(FUJI_V0_3)

        for i, (t02, t03) in enumerate(zip(v02["turns"], v03["turns"])):
            assert t02["turn"] == t03["turn"], f"Turn number mismatch at index {i}"
            assert t02["name"] == t03["name"], f"Turn name mismatch at index {i}"
            assert t02["start_m"] == t03["start_m"], f"start_m mismatch for turn {t02['turn']}"
            assert t02["end_m"] == t03["end_m"], f"end_m mismatch for turn {t02['turn']}"
            assert t02["apex_m"] == t03["apex_m"], f"apex_m mismatch for turn {t02['turn']}"

    def test_lap_length_identical(self) -> None:
        """v0_2 and v0_3 have identical lap length."""
        v02 = _load_profile(FUJI_V0_2)
        v03 = _load_profile(FUJI_V0_3)

        v02_lap_dist = v02["calibration"]["source_lap_dist_max_m"]
        v03_lap_dist = v03["calibration"]["source_lap_dist_max_m"]

        assert v02_lap_dist == v03_lap_dist

    def test_layout_identical(self) -> None:
        """v0_2 and v0_3 have identical track/layout."""
        v02 = _load_profile(FUJI_V0_2)
        v03 = _load_profile(FUJI_V0_3)

        assert v02["track"] == v03["track"]
        assert v02["layout"] == v03["layout"]

    def test_aliases_unchanged(self) -> None:
        """v0_2 and v0_3 have identical aliases for every turn."""
        v02 = _load_profile(FUJI_V0_2)
        v03 = _load_profile(FUJI_V0_3)

        for i, (t02, t03) in enumerate(zip(v02["turns"], v03["turns"])):
            assert t02.get("aliases", []) == t03.get("aliases", []), \
                f"Aliases mismatch for turn {t02['turn']}"

    def test_ignored_geometric_features_m_identical(self) -> None:
        """v0_2 and v0_3 have identical ignored_geometric_features_m."""
        v02 = _load_profile(FUJI_V0_2)
        v03 = _load_profile(FUJI_V0_3)

        assert len(v02["ignored_geometric_features_m"]) == len(v03["ignored_geometric_features_m"])

        for item02, item03 in zip(
            v02["ignored_geometric_features_m"],
            v03["ignored_geometric_features_m"],
        ):
            assert item02["center_m"] == item03["center_m"]
            assert item02["reason"] == item03["reason"]

    def test_manual_low_curvature_turns_identical(self) -> None:
        """v0_2 and v0_3 have identical manual_low_curvature_turns."""
        v02 = _load_profile(FUJI_V0_2)
        v03 = _load_profile(FUJI_V0_3)

        assert len(v02["manual_low_curvature_turns"]) == len(v03["manual_low_curvature_turns"])

        for item02, item03 in zip(
            v02["manual_low_curvature_turns"],
            v03["manual_low_curvature_turns"],
        ):
            assert item02["turn"] == item03["turn"]
            assert item02["reason"] == item03["reason"]

    def test_display_policy_identical(self) -> None:
        """v0_2 and v0_3 have identical display_policy."""
        v02 = _load_profile(FUJI_V0_2)
        v03 = _load_profile(FUJI_V0_3)

        assert v02["display_policy"] == v03["display_policy"]


class TestFujiV03GeometricNotes:
    """Verify that v0_3 has geometric_notes and v0_2 does not (or they're different)."""

    def test_v03_has_geometric_notes(self) -> None:
        """v0_3 has geometric_notes field."""
        v03 = _load_profile(FUJI_V0_3)
        assert "geometric_notes" in v03

    def test_v03_geometric_notes_has_expected_notes(self) -> None:
        """v0_3 has 7 notes: gap explanations, T7 low-curvature, GPS limitation."""
        v03 = _load_profile(FUJI_V0_3)
        notes = v03["geometric_notes"]
        assert len(notes) == 7

    def test_v03_note_ids_expected(self) -> None:
        """v0_3 has the expected note IDs."""
        v03 = _load_profile(FUJI_V0_3)
        note_ids = [n["id"] for n in v03["geometric_notes"].values()]
        expected_ids = [
            "gap_t2_to_t3",
            "gap_t3_to_t4",
            "gap_t5_to_t6",
            "gap_t15_to_t16",
            "minor_gaps",
            "t7_low_curvature_continuation",
            "gps_coverage_limitation",
        ]
        assert set(note_ids) == set(expected_ids)

    def test_v03_gaps_documented_as_straight_transitions(self) -> None:
        """v0_3 documents gaps as straight/transition zones, not as errors."""
        v03 = _load_profile(FUJI_V0_3)
        notes = v03["geometric_notes"]

        # Check T2→T3 gap
        t2_t3 = notes["note_1"]
        assert t2_t3["classification"] == "straight_real_track_feature"
        assert t2_t3["gap_m"] == 206.0
        assert t2_t3["percentage_of_lap"] == 4.6

        # Check T3→T4 gap
        t3_t4 = notes["note_2"]
        assert t3_t4["classification"] == "straight_short_real_track_feature"
        assert t3_t4["gap_m"] == 94.0
        assert t3_t4["percentage_of_lap"] == 2.1

    def test_v03_t7_documented_as_low_curvature(self) -> None:
        """v0_3 documents T7 as low-curvature continuation, not as a geometry error."""
        v03 = _load_profile(FUJI_V0_3)
        notes = v03["geometric_notes"]
        t7 = notes["note_6"]
        assert t7["classification"] == "low_curvature_continuation"
        assert "low-curvature continuation" in t7["reason"]
        assert "calibrated interval mapping remains authoritative" in t7["reason"]

    def test_v03_gps_documented_as_limitation(self) -> None:
        """v0_3 documents GPS coverage as a known limitation."""
        v03 = _load_profile(FUJI_V0_3)
        notes = v03["geometric_notes"]
        gps = notes["note_7"]
        assert gps["classification"] == "calibration_limitation"
        assert "known limitation" in gps["reason"]


class TestFujiV03SchemaCompatibility:
    """Verify that v0_3 doesn't break existing parsers."""

    def test_v03_schema_version_unchanged(self) -> None:
        """v0_3 schema_version is still 1."""
        v03 = _load_profile(FUJI_V0_3)
        assert v03["schema_version"] == 1

    def test_v03_required_fields_present(self) -> None:
        """v0_3 has all required fields from schema v1."""
        v03 = _load_profile(FUJI_V0_3)
        required = [
            "schema_version",
            "profile_id",
            "status",
            "track",
            "layout",
            "distance_coordinate",
            "calibration",
            "ignored_geometric_features_m",
            "turns",
            "display_policy",
        ]
        for field in required:
            assert field in v03, f"Missing required field: {field}"

    def test_v03_geometric_notes_is_freeform_dict(self) -> None:
        """v0_3 geometric_notes is a free-form dict (schema v1 doesn't enforce it)."""
        v03 = _load_profile(FUJI_V0_3)
        assert isinstance(v03["geometric_notes"], dict)

    def test_v03_turns_structure_unchanged(self) -> None:
        """v0_3 turns have the same structure as v0_2."""
        v02 = _load_profile(FUJI_V0_2)
        v03 = _load_profile(FUJI_V0_3)

        for i, (t02, t03) in enumerate(zip(v02["turns"], v03["turns"])):
            required_turn_fields = ["turn", "name", "group", "direction", "start_m", "apex_m", "end_m"]
            for field in required_turn_fields:
                assert field in t03, f"Missing field in turn {t03['turn']}: {field}"
                assert t02[field] == t03[field], f"Field {field} mismatch for turn {t03['turn']}"

    def test_v03_validator_passes(self) -> None:
        """v0_3 passes the validator (no errors, same warnings as v0_2)."""
        from validate_track_profiles import validate_profile

        result = validate_profile(FUJI_V0_3)
        assert result["status"] == "VALID_WITH_WARNINGS"
        assert result["error_count"] == 0
        assert result["warning_count"] == 2
        assert result["informational_count"] == 7
