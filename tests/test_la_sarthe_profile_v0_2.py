"""
Tests for Circuit de la Sarthe v0.2 track profile.
Validates geometry preservation, ordering, lap bounds,
complex/chicane consistency, ignored features semantics,
aliases, GPS/provenance consistency, independent-session validation,
parser compatibility, deterministic repeatability, and v0.1 vs v0.2 comparison.
"""

import json
import os
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.path.join(BASE_DIR, "track_profiles", "la_sarthe_profile_v0_2.json")
PROFILE_V1_PATH = os.path.join(BASE_DIR, "track_profiles", "la_sarthe_profile_v0_1.json")


@pytest.fixture
def profile():
    with open(PROFILE_PATH, "r") as f:
        return json.load(f)


@pytest.fixture
def profile_v1():
    with open(PROFILE_V1_PATH, "r") as f:
        return json.load(f)


def _find_turn(profile, turn_num):
    for t in profile["turns"]:
        if t["turn"] == turn_num:
            return t
    raise ValueError(f"Turn {turn_num} not found")


# ---- Schema & provenance ----

class TestSchemaAndProvenance:
    def test_schema_version(self, profile):
        assert profile["schema_version"] == 1

    def test_profile_id(self, profile):
        assert "v0.2" in profile["profile_id"]

    def test_status(self, profile):
        assert profile["status"] == "VALIDATED_MULTI_SESSION"

    def test_geometry_method(self, profile):
        assert "GPS trajectory" in profile["calibration"]["geometry_method"]

    def test_numbering_warning(self, profile):
        assert "FIA" in profile["calibration"]["numbering_warning"]
        assert "ACO corner names" in profile["calibration"]["numbering_warning"]

    def test_official_nomenclature_sources(self, profile):
        sources = profile["calibration"]["official_nomenclature_sources"]
        assert len(sources) == 2
        aco = [s for s in sources if "Automobile Club" in s["authority"]]
        fia = [s for s in sources if "FIA" in s["authority"]]
        assert len(aco) == 1
        assert len(fia) == 1

    def test_validation_summary_independent_sessions(self, profile):
        indep = profile["calibration"]["validation_summary"]["independent_sessions"]
        assert len(indep) == 2


# ---- Geometry preservation ----

class TestGeometryPreservation:
    def test_19_turns(self, profile):
        assert len(profile["turns"]) == 19

    def test_turn_numbers_1_to_19(self, profile):
        nums = sorted(t["turn"] for t in profile["turns"])
        assert nums == list(range(1, 20))

    def test_lap_length_unchanged(self, profile, profile_v1):
        assert profile["calibration"]["source_lap_dist_max_m"] == profile_v1["calibration"]["source_lap_dist_max_m"]

    def test_geometry_method_unchanged(self, profile, profile_v1):
        assert profile["calibration"]["geometry_method"] == profile_v1["calibration"]["geometry_method"]

    def test_display_policy_unchanged(self, profile, profile_v1):
        assert profile["display_policy"] == profile_v1["display_policy"]


# ---- Ordering & lap bounds ----

class TestOrderingAndLapBounds:
    def test_turns_ordered_by_start_m(self, profile):
        ends = [t["start_m"] for t in profile["turns"]]
        assert ends == sorted(ends)

    def test_apex_inside_turn(self, profile):
        for t in profile["turns"]:
            assert t["start_m"] <= t["apex_m"] <= t["end_m"]

    def test_all_turns_inside_lap_bounds(self, profile):
        for t in profile["turns"]:
            assert t["start_m"] >= 0
            assert t["end_m"] <= profile["calibration"]["source_lap_dist_max_m"]


# ---- Complex/chicane consistency ----

class TestComplexChicaneConsistency:
    def test_dunlop_chicane_direction_sequence(self, profile):
        t = _find_turn(profile, 2)
        assert "direction_sequence" in t
        assert t["direction_sequence"] == ["left", "right"]

    def test_daytona_chicane_direction_sequence(self, profile):
        t = _find_turn(profile, 5)
        assert "direction_sequence" in t
        assert len(t["direction_sequence"]) == 3

    def test_michelin_chicane_direction_sequence(self, profile):
        t = _find_turn(profile, 6)
        assert "direction_sequence" in t
        assert len(t["direction_sequence"]) == 3

    def test_porsche_curves_group(self, profile):
        porsche_turns = [t for t in profile["turns"] if t["group"] == "Porsche Curves"]
        assert len(porsche_turns) == 3

    def test_ford_chicanes_group(self, profile):
        ford_turns = [t for t in profile["turns"] if t["group"] == "Ford Chicanes and Motul Turn"]
        assert len(ford_turns) == 4

    def test_ford_chicanes_directions(self, profile):
        ford = [t for t in profile["turns"] if t["group"] == "Ford Chicanes and Motul Turn"]
        assert ford[0]["direction"] == "left"   # Ford Chicanes 1
        assert ford[1]["direction"] == "right"  # Ford Chicanes 2
        assert ford[2]["direction"] == "left"   # Motul Chicane Entry
        assert ford[3]["direction"] == "right"  # Motul Turn


# ---- Ignored features semantics ----

class TestIgnoredFeaturesSemantics:
    def test_ignored_features_empty(self, profile):
        assert profile["ignored_geometric_features_m"] == []

    def test_all_major_gaps_explained_in_geometric_notes(self, profile):
        notes = profile["geometric_notes"]
        gap_ids = [notes[k]["id"] for k in notes if notes[k].get("type") == "gap_explanation"]
        # All 11 gaps explained: 5 major straights + 6 minor boundary offsets
        expected = [
            "gap_t2_to_t3",
            "gap_t3_to_t4",
            "gap_t4_to_t5",
            "gap_t5_to_t6",
            "gap_t6_to_t7",
            "gap_t7_to_t8",
            "gap_t8_to_t9",
            "gap_t9_to_t10",
            "gap_t10_to_t11",
            "gap_t13_to_t14",
            "gap_t15_to_t16",
        ]
        assert set(gap_ids) == set(expected)

    def test_all_gap_classifications(self, profile):
        notes = profile["geometric_notes"]
        for key, note in notes.items():
            if note.get("type") == "gap_explanation":
                assert note["classification"] in (
                    "acceptable_boundary_offset",
                    "straight_real_track_feature",
                )


# ---- Aliases ----

class TestAliases:
    def test_dunlop_aliases(self, profile):
        t = _find_turn(profile, 1)
        assert "Courbe Dunlop" in t["aliases"]

    def test_forest_esses_aliases(self, profile):
        t = _find_turn(profile, 3)
        assert any("Esses" in a or "Esses" in a or "Foret" in a or "Foret" in a for a in t["aliases"])

    def test_porsche_curves_aliases(self, profile):
        t = _find_turn(profile, 11)
        assert "Virages Porsche" in t["aliases"]

    def test_ford_chicanes_aliases(self, profile):
        t = _find_turn(profile, 16)
        assert "Chicanes Ford" in t["aliases"]

    def test_motul_turn_aliases(self, profile):
        t = _find_turn(profile, 19)
        assert any("Motul" in a or "Raccordement" in a for a in t["aliases"])


# ---- GPS/provenance consistency ----

class TestGPSProvenance:
    def test_gps_note_exists(self, profile):
        assert "note_12" in profile["geometric_notes"]

    def test_gps_note_type(self, profile):
        note = profile["geometric_notes"]["note_12"]
        assert note["type"] == "data_limitation"
        assert note["classification"] == "calibration_limitation"

    def test_gps_evidence_fields(self, profile):
        note = profile["geometric_notes"]["note_12"]
        assert note["evidence"]["gps_coordinate_available"] is True
        assert note["evidence"]["gps_coverage_derivable"] is False

    def test_independent_session_validation(self, profile):
        indep = profile["calibration"]["validation_summary"]["independent_sessions"]
        for session in indep:
            assert session["overall_status"] == "PASS"


# ---- Parser compatibility ----

class TestParserCompatibility:
    def test_json_parseable(self, profile):
        """Ensure JSON structure is parseable by standard Python json module."""
        assert json.dumps(profile) is not None

    def test_schema_version_field(self, profile):
        """Ensure schema_version is an integer, not a string."""
        assert isinstance(profile["schema_version"], int)

    def test_turn_numbers_are_integers(self, profile):
        for t in profile["turns"]:
            assert isinstance(t["turn"], int)


# ---- Deterministic repeatability ----

class TestDeterministicRepeatability:
    def test_reparse_same_content(self, profile):
        """Re-serializing and re-parsing should yield identical structure."""
        reloaded = json.loads(json.dumps(profile))
        assert reloaded == profile


# ---- v0.1 vs v0.2 comparison ----

class TestV01VsV02Comparison:
    def test_turns_identical(self, profile, profile_v1):
        for v1_turn, v2_turn in zip(profile_v1["turns"], profile["turns"]):
            for key in ("turn", "name", "direction", "start_m", "apex_m", "end_m", "group"):
                assert v1_turn[key] == v2_turn[key], f"Turn {v1_turn['turn']}: {key} mismatch"

    def test_profile_id_changed(self, profile, profile_v1):
        assert profile["profile_id"] != profile_v1["profile_id"]
        assert "v0.2" in profile["profile_id"]
        assert "v0.1" in profile_v1["profile_id"]

    def test_geometric_notes_added(self, profile):
        assert "geometric_notes" in profile
        assert len(profile["geometric_notes"]) > 0

    def test_ignored_features_empty_in_v02(self, profile):
        assert profile["ignored_geometric_features_m"] == []

    def test_ignored_features_removed_from_v01(self, profile_v1, profile):
        """v0.1 had 4 range entries; v0.2 has 0."""
        assert len(profile_v1["ignored_geometric_features_m"]) == 4
        assert len(profile["ignored_geometric_features_m"]) == 0

    def test_validation_summary_added(self, profile):
        """v0.2 adds independent-session turn_results in validation_summary."""
        vs = profile["calibration"]["validation_summary"]
        assert "independent_sessions" in vs
        assert len(vs["independent_sessions"]) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
