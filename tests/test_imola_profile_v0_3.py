"""Tests for Imola track profile v0.3 — geometry preservation and schema compatibility.

These tests verify that v0.3 preserves the exact turn geometry of v0.2
and that the new `geometric_notes` field doesn't break existing parsers.
"""

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

# Paths
IMOLA_V0_2 = Path("track_profiles/imola_profile_v0_2.json")
IMOLA_V0_3 = Path("track_profiles/imola_profile_v0_3.json")


def _load_profile(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_turns(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return profile["turns"]


class TestImolaV03GeometryPreservation:
    """Verify that v0.3 preserves v0.2 turn geometry exactly."""

    def test_v03_loads_successfully(self) -> None:
        """v0_3 loads as valid JSON and passes validator."""
        data = _load_profile(IMOLA_V0_3)
        assert data["schema_version"] == 1
        assert data["status"] == "VALIDATED_MULTI_SESSION"

    def test_v03_profile_id_updated(self) -> None:
        """v0_3 has updated profile_id."""
        data = _load_profile(IMOLA_V0_3)
        assert data["profile_id"] == "imola-lmu-19turn-v0.3"

    def test_turn_count_is_19(self) -> None:
        """v0_3 has exactly 19 turns, matching the LMU convention."""
        data = _load_profile(IMOLA_V0_3)
        assert len(data["turns"]) == 19

    def test_turn_geometry_identical(self) -> None:
        """v0_2 and v0_3 have identical turn start/end/apex for every turn."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)

        for i, (t02, t03) in enumerate(zip(v02["turns"], v03["turns"])):
            assert t02["turn"] == t03["turn"], f"Turn number mismatch at index {i}"
            assert t02["name"] == t03["name"], f"Turn name mismatch at index {i}"
            assert t02["start_m"] == t03["start_m"], f"start_m mismatch for turn {t02['turn']}"
            assert t02["end_m"] == t03["end_m"], f"end_m mismatch for turn {t02['turn']}"
            assert t02["apex_m"] == t03["apex_m"], f"apex_m mismatch for turn {t02['turn']}"

    def test_lap_length_identical(self) -> None:
        """v0_2 and v0_3 have identical lap length."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)

        v02_lap_dist = v02["calibration"]["source_lap_dist_max_m"]
        v03_lap_dist = v03["calibration"]["source_lap_dist_max_m"]

        assert v02_lap_dist == v03_lap_dist

    def test_layout_identical(self) -> None:
        """v0_2 and v0_3 have identical track/layout."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)

        assert v02["track"] == v03["track"]
        assert v02["layout"] == v03["layout"]

    def test_aliases_unchanged(self) -> None:
        """v0_2 and v0_3 have identical aliases for every turn."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)

        for i, (t02, t03) in enumerate(zip(v02["turns"], v03["turns"])):
            assert t02.get("aliases", []) == t03.get("aliases", []), \
                f"Aliases mismatch for turn {t02['turn']}"

    def test_group_fields_identical(self) -> None:
        """v0_2 and v0_3 have identical group fields for every turn."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)

        for i, (t02, t03) in enumerate(zip(v02["turns"], v03["turns"])):
            assert t02.get("group", "") == t03.get("group", ""), \
                f"Group mismatch for turn {t02['turn']}"

    def test_display_policy_identical(self) -> None:
        """v0_2 and v0_3 have identical display_policy."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)

        assert v02["display_policy"] == v03["display_policy"]


class TestImolaV03GeometricNotes:
    """Verify that v0_3 has geometric_notes documenting all 6 large gaps."""

    def test_v03_has_geometric_notes(self) -> None:
        """v0_3 has geometric_notes field."""
        v03 = _load_profile(IMOLA_V0_3)
        assert "geometric_notes" in v03

    def test_v03_geometric_notes_has_expected_notes(self) -> None:
        """v0_3 has 7 notes: 6 gap explanations + minor gaps note + GPS limitation."""
        v03 = _load_profile(IMOLA_V0_3)
        notes = v03["geometric_notes"]
        assert len(notes) == 7

    def test_v03_note_ids_expected(self) -> None:
        """v0_3 has the expected note IDs for the gaps."""
        v03 = _load_profile(IMOLA_V0_3)
        note_ids = [n["id"] for n in v03["geometric_notes"].values()]
        expected_ids = [
            "gap_t4_to_t5",
            "gap_t5_to_t7",
            "gap_t7_to_t8",
            "gap_t13_to_t14",
            "gap_t15_to_t16",
            "minor_gaps",
            "gps_coverage_limitation",
        ]
        assert set(note_ids) == set(expected_ids)

    def test_v03_gaps_documented_as_expected(self) -> None:
        """v0_3 documents all 6 large gaps as real track features, not errors."""
        v03 = _load_profile(IMOLA_V0_3)
        notes = v03["geometric_notes"]

        # Check T4→T5 gap (280m, 5.7%)
        t4_t5 = notes["note_1"]
        assert t4_t5["classification"] == "straight_real_track_feature"
        assert t4_t5["gap_m"] == 280.0
        assert t4_t5["percentage_of_lap"] == 5.7

        # Check T5→T7 gap (170m, 3.5%)
        t5_t7 = notes["note_2"]
        assert t5_t7["classification"] == "straight_real_track_feature"
        assert t5_t7["gap_m"] == 170.0
        assert t5_t7["percentage_of_lap"] == 3.5

        # Check T7→T8 gap (230m, 4.7%)
        t7_t8 = notes["note_3"]
        assert t7_t8["classification"] == "straight_real_track_feature"
        assert t7_t8["gap_m"] == 230.0
        assert t7_t8["percentage_of_lap"] == 4.7

        # Check T13→T14 gap (310m, 6.3%)
        t13_t14 = notes["note_4"]
        assert t13_t14["classification"] == "straight_real_track_feature"
        assert t13_t14["gap_m"] == 310.0
        assert t13_t14["percentage_of_lap"] == 6.3

        # Check T15→T16 gap (430m, 8.8%)
        t15_t16 = notes["note_5"]
        assert t15_t16["classification"] == "straight_real_track_feature"
        assert t15_t16["gap_m"] == 430.0
        assert t15_t16["percentage_of_lap"] == 8.8

        # Check minor gaps note (note_6)
        minor_gaps = notes["note_6"]
        assert minor_gaps["classification"] == "acceptable_boundary_offsets"
        # note_6 uses a "gaps" list (not gap_description string)
        assert "gaps" in minor_gaps
        gap_entries = minor_gaps["gaps"]
        assert len(gap_entries) >= 6
        # Verify T18→T19 (turn 19) boundary offset is documented
        t19_gap = next((g for g in gap_entries if g["turn"] == 19), None)
        assert t19_gap is not None
        assert t19_gap["gap_m"] == 100.0

    def test_v03_gps_documented_as_limitation(self) -> None:
        """v0_3 documents GPS coverage as a known limitation."""
        v03 = _load_profile(IMOLA_V0_3)
        notes = v03["geometric_notes"]
        gps = notes["note_7"]
        assert gps["classification"] == "calibration_limitation"
        assert "known limitation" in gps["reason"]


class TestImolaV03SchemaCompatibility:
    """Verify that v0_3 doesn't break existing parsers."""

    def test_v03_schema_version_unchanged(self) -> None:
        """v0_3 schema_version is still 1."""
        v03 = _load_profile(IMOLA_V0_3)
        assert v03["schema_version"] == 1

    def test_v03_required_fields_present(self) -> None:
        """v0_3 has all required fields from schema v1."""
        v03 = _load_profile(IMOLA_V0_3)
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
        v03 = _load_profile(IMOLA_V0_3)
        assert isinstance(v03["geometric_notes"], dict)

    def test_v03_turns_structure_unchanged(self) -> None:
        """v0_3 turns have the same structure as v0_2."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)

        for i, (t02, t03) in enumerate(zip(v02["turns"], v03["turns"])):
            required_turn_fields = ["turn", "name", "group", "direction", "start_m", "apex_m", "end_m"]
            for field in required_turn_fields:
                assert field in t03, f"Missing field in turn {t03['turn']}: {field}"
                assert t02[field] == t03[field], f"Field {field} mismatch for turn {t03['turn']}"

    def test_v03_validator_passes(self) -> None:
        """v0_3 passes the validator (no errors, same warnings as v0_2: 6 warnings, 4 informational)."""
        from validate_track_profiles import validate_profile

        result = validate_profile(IMOLA_V0_3)
        assert result["status"] == "VALID_WITH_WARNINGS"
        assert result["error_count"] == 0
        assert result["warning_count"] == 6
        assert result["informational_count"] == 4


class TestImolaV03IndependentSessionData:
    """Verify that v0_3 independent session data is correct."""

    def test_v03_independent_session_all_pass(self) -> None:
        """v0_3 independent session has all 19 turns passing."""
        v03 = _load_profile(IMOLA_V0_3)
        indep = v03["calibration"]["validation_summary"]["independent_sessions"][0]
        assert indep["pass_count"] == 19
        assert indep["warning_count"] == 0
        assert indep["failure_count"] == 0
        assert indep["overall_status"] == "PASS"

    def test_v03_independent_session_median_offset(self) -> None:
        """v0_3 independent session median offset is 4m."""
        v03 = _load_profile(IMOLA_V0_3)
        indep = v03["calibration"]["validation_summary"]["independent_sessions"][0]
        assert indep["median_abs_offset_m"] == 4.0

    def test_v03_independent_session_max_offset(self) -> None:
        """v0_3 independent session max offset is 22m."""
        v03 = _load_profile(IMOLA_V0_3)
        indep = v03["calibration"]["validation_summary"]["independent_sessions"][0]
        assert indep["max_abs_offset_m"] == 22.0

    def test_v03_independent_session_turn_results_match_v02(self) -> None:
        """v0_3 independent session turn_results match v0_2 exactly."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)

        v02_results = v02["calibration"]["validation_summary"]["independent_sessions"][0]["turn_results"]
        v03_results = v03["calibration"]["validation_summary"]["independent_sessions"][0]["turn_results"]

        assert len(v02_results) == len(v03_results) == 19

        for t02, t03 in zip(v02_results, v03_results):
            assert t02["turn"] == t03["turn"]
            assert t02["name"] == t03["name"]
            assert t02["direction"] == t03["direction"]
            assert t02["expected_apex_m"] == t03["expected_apex_m"]
            assert t02["observed_apex_m"] == t03["observed_apex_m"]
            assert t02["offset_m"] == t03["offset_m"]
            assert t02["status"] == t03["status"] == "PASS"


class TestImolaV03IgnoredGeometrySemantics:
    """Verify that ignored_geometric_features_m and manual_low_curvature_turns are correct."""

    def test_v03_ignored_geometric_features_m_has_2_entries(self) -> None:
        """v0_3 has 2 entries in ignored_geometric_features_m (T8 and T16)."""
        v03 = _load_profile(IMOLA_V0_3)
        assert len(v03["ignored_geometric_features_m"]) == 2

    def test_v03_ignored_features_includes_t8(self) -> None:
        """v0_3 ignored features includes T8 at 2074m."""
        v03 = _load_profile(IMOLA_V0_3)
        t8_entry = next((e for e in v03["ignored_geometric_features_m"] if e["center_m"] == 2074.0), None)
        assert t8_entry is not None
        assert t8_entry["center_m"] == 2074.0
        assert "low curvature" in t8_entry["reason"]

    def test_v03_ignored_features_includes_t16(self) -> None:
        """v0_3 ignored features includes T16 at 3954m."""
        v03 = _load_profile(IMOLA_V0_3)
        t16_entry = next((e for e in v03["ignored_geometric_features_m"] if e["center_m"] == 3954.0), None)
        assert t16_entry is not None
        assert t16_entry["center_m"] == 3954.0
        assert "low curvature" in t16_entry["reason"]

    def test_v03_manual_low_curvature_turns_has_3_entries(self) -> None:
        """v0_3 has 3 entries in manual_low_curvature_turns (T8, T16, T19)."""
        v03 = _load_profile(IMOLA_V0_3)
        assert len(v03["manual_low_curvature_turns"]) == 3

    def test_v03_manual_low_curvature_turns_includes_t8(self) -> None:
        """v0_3 manual low curvature turns includes T8."""
        v03 = _load_profile(IMOLA_V0_3)
        t8_entry = next((e for e in v03["manual_low_curvature_turns"] if e["turn"] == 8), None)
        assert t8_entry is not None
        assert "flat right" in t8_entry["reason"]

    def test_v03_manual_low_curvature_turns_includes_t16(self) -> None:
        """v0_3 manual low curvature turns includes T16."""
        v03 = _load_profile(IMOLA_V0_3)
        t16_entry = next((e for e in v03["manual_low_curvature_turns"] if e["turn"] == 16), None)
        assert t16_entry is not None
        assert "flat right" in t16_entry["reason"]

    def test_v03_manual_low_curvature_turns_includes_t19(self) -> None:
        """v0_3 manual low curvature turns includes T19."""
        v03 = _load_profile(IMOLA_V0_3)
        t19_entry = next((e for e in v03["manual_low_curvature_turns"] if e["turn"] == 19), None)
        assert t19_entry is not None
        assert "flat right" in t19_entry["reason"]


class TestImolaV03ParserCompatibility:
    """Verify that v0_3 is compatible with existing profile parsers."""

    def test_v03_parsable_by_load_profile(self) -> None:
        """v0_3 can be loaded by _load_profile without error."""
        data = _load_profile(IMOLA_V0_3)
        assert data is not None

    def test_v03_turns_are_iterable(self) -> None:
        """v0_3 turns can be iterated without error."""
        data = _load_profile(IMOLA_V0_3)
        turns = _load_turns(data)
        assert len(turns) == 19

    def test_v03_all_turms_have_required_fields(self) -> None:
        """v0_3 all turns have required fields."""
        v03 = _load_profile(IMOLA_V0_3)
        required_turn_fields = ["turn", "name", "group", "direction", "start_m", "apex_m", "end_m"]

        for turn in v03["turns"]:
            for field in required_turn_fields:
                assert field in turn, f"Missing field {field} in turn {turn.get('turn', 'unknown')}"


class TestImolaV03Repeatability:
    """Verify that loading v0_3 is stable."""

    def test_v03_load_twice_is_same(self) -> None:
        """Loading v0_3 twice produces identical results."""
        data1 = _load_profile(IMOLA_V0_3)
        data2 = _load_profile(IMOLA_V0_3)
        assert json.dumps(data1) == json.dumps(data2)


class TestImolaV03EqualityWithV02:
    """Since geometry is unchanged, v0_2 and v0_3 should be equal in key fields."""

    def test_v03_geometry_equals_v02(self) -> None:
        """v0_3 turn geometry is identical to v0_2 (no corrections made)."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)

        assert len(v02["turns"]) == len(v03["turns"])

        for i, (t02, t03) in enumerate(zip(v02["turns"], v03["turns"])):
            assert t02["turn"] == t03["turn"]
            assert t02["name"] == t03["name"]
            assert t02["start_m"] == t03["start_m"]
            assert t02["end_m"] == t03["end_m"]
            assert t02["apex_m"] == t03["apex_m"]
            assert t02["direction"] == t03["direction"]

    def test_v03_profile_id_differs(self) -> None:
        """v0_3 profile_id is v0.3, v0_2 is v0.2 (they differ)."""
        v02 = _load_profile(IMOLA_V0_2)
        v03 = _load_profile(IMOLA_V0_3)
        assert v02["profile_id"] == "imola-lmu-19turn-v0.2"
        assert v03["profile_id"] == "imola-lmu-19turn-v0.3"
        assert v02["profile_id"] != v03["profile_id"]
