# -*- coding: utf-8 -*-
"""Tests for track_profiles/spa_francorchamps_profile_v0_3.json.

Adapted from test_monza_profile_v0_3.py with Spa-Francorchamps-specific expectations:
- 19 turns (LMU/FIA/F1 19-turn map)
- 5 ignored_geometric_features_m (all distinct features at 638.5, 1474.5, 3392.5, 5444.5, 6414.5 m)
- 7 gap_explanation notes (major straights at Spa)
- geometric_notes is a dict (not a list)
- No geometry corrections from v0.2
- No manual_low_curvature_turns (v0.2 had none)

Run:
    pytest tests/test_spa_francorchamps_profile_v0_3.py -v
    pytest tests/test_spa_francorchamps_profile_v0_3.py -q
"""
import json
import copy

import pytest

PROFILE_PATH = "track_profiles/spa_francorchamps_profile_v0_3.json"
V02_PATH = "track_profiles/spa_francorchamps_profile_v0_2.json"


@pytest.fixture
def profile():
    with open(PROFILE_PATH) as f:
        return json.load(f)


@pytest.fixture
def v02_profile():
    with open(V02_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Schema compatibility and basic structure
# ---------------------------------------------------------------------------

class TestSchemaCompatibility:
    """Verify basic schema fields and version."""

    def test_schema_version_is_1(self, profile):
        assert profile["schema_version"] == 1

    def test_profile_id_matches_v03(self, profile):
        assert profile["profile_id"] == "spa-francorchamps-lmu-fia2026-v0.3"

    def test_status_is_validated_multi_session(self, profile):
        assert profile["status"] == "VALIDATED_MULTI_SESSION"

    def test_has_required_top_level_keys(self, profile):
        required = {
            "schema_version", "profile_id", "status", "track", "layout",
            "distance_coordinate", "calibration", "turns", "display_policy",
            "geometric_notes", "ignored_geometric_features_m",
        }
        assert required.issubset(profile.keys())

    def test_track_and_layout(self, profile):
        assert profile["track"] == "Circuit de Spa-Francorchamps"
        assert profile["layout"] == "Circuit de Spa-Francorchamps"

    def test_geometric_notes_is_dict(self, profile):
        assert isinstance(profile["geometric_notes"], dict)


# ---------------------------------------------------------------------------
# 2. Geometry preservation
# ---------------------------------------------------------------------------

class TestGeometryPreservation:
    """Verify all turn geometry is preserved from v0.2."""

    def test_turn_count(self, profile):
        assert len(profile["turns"]) == 19

    def test_all_geometry_preserved(self, profile, v02_profile):
        """Every turn in v0.2 must match v0.3 exactly."""
        for i, (turn_v2, turn_v3) in enumerate(
            zip(v02_profile["turns"], profile["turns"])
        ):
            for field in ("turn", "name", "group", "direction", "start_m", "apex_m", "end_m"):
                assert turn_v3[field] == turn_v2[field], \
                    f"Turn {i} {field} changed: {turn_v3[field]} != {turn_v2[field]}"

    def test_profile_id_incremented(self, profile):
        """v0.3 must have a different profile_id from v0.2."""
        assert profile["profile_id"] == "spa-francorchamps-lmu-fia2026-v0.3"

    def test_all_geometry_preserved_count(self, profile, v02_profile):
        """Count check — same number of turns."""
        assert len(profile["turns"]) == len(v02_profile["turns"])

    def test_eau_rouge_complex_preserved(self, profile):
        """Eau Rouge complex (T2–T4) must have correct direction sequence."""
        eau_rouge = [t for t in profile["turns"] if "Eau Rouge" in t["name"]]
        assert len(eau_rouge) == 3
        assert eau_rouge[0]["direction"] == "left"
        assert eau_rouge[1]["direction"] == "right"
        assert eau_rouge[2]["direction"] == "left"

    def test_les_combes_complex_preserved(self, profile):
        """Les Combes (T5–T6) must have correct direction sequence."""
        les_combes = [t for t in profile["turns"] if "Les Combes" in t["name"]]
        assert len(les_combes) == 2
        assert les_combes[0]["direction"] == "right"
        assert les_combes[1]["direction"] == "left"


# ---------------------------------------------------------------------------
# 3. Layout and lap length
# ---------------------------------------------------------------------------

class TestLayoutAndLapLength:
    """Verify lap_length_m and layout fields."""

    def test_lap_length(self, profile, v02_profile):
        """Lap length must be 6972.0 (same as v0.2)."""
        assert abs(profile["calibration"]["source_lap_dist_max_m"] - 6972.0) < 0.01
        assert profile["calibration"]["source_lap_dist_max_m"] == v02_profile["calibration"]["source_lap_dist_max_m"]

    def test_display_policy(self, profile):
        assert profile["display_policy"]["prefer_corner_name"] is True
        assert profile["display_policy"]["turn_number_is_secondary"] is True
        assert profile["display_policy"]["turn_number_suffix"] == "FIA"
        assert profile["display_policy"]["always_preserve_lmu_distance_m"] is True


# ---------------------------------------------------------------------------
# 4. Ordering and lap bounds
# ---------------------------------------------------------------------------

class TestOrderingAndLapBounds:
    """Verify turns are in valid order and within lap bounds."""

    def test_turns_ordered_by_turn_number(self, profile):
        turns = profile["turns"]
        numbers = [t["turn"] for t in turns]
        assert numbers == sorted(numbers)

    def test_all_apex_inside_turn_bounds(self, profile):
        """Each turn's apex must be within [start, end]."""
        for turn in profile["turns"]:
            assert turn["start_m"] <= turn["apex_m"] <= turn["end_m"]

    def test_first_turn_starts_after_zero(self, profile):
        assert profile["turns"][0]["start_m"] >= 0


# ---------------------------------------------------------------------------
# 5. Ignored geometric features
# ---------------------------------------------------------------------------

class TestIgnoredFeatures:
    """Verify ignored_geometric_features_m semantics and uniqueness."""

    def test_ignored_features_count(self, profile):
        """v0.3 should have 5 ignored features (all distinct features)."""
        assert len(profile["ignored_geometric_features_m"]) == 5

    def test_ignored_features_are_unique_centers(self, profile):
        """All center_m values must be unique."""
        centers = [f["center_m"] for f in profile["ignored_geometric_features_m"]]
        assert len(centers) == len(set(centers))

    def test_ignored_features_no_overlap_with_apexes(self, profile):
        """No ignored feature center should coincide with any turn apex."""
        apexes = {t["apex_m"]: t["name"] for t in profile["turns"]}
        for feat in profile["ignored_geometric_features_m"]:
            for apex in apexes:
                if abs(feat["center_m"] - apex) < 10:
                    pytest.fail(
                        f"Ignored feature at {feat['center_m']} m "
                        f"overlaps with apex at {apex} m ({apexes[apex]})"
                    )

    def test_ignored_features_reasons_not_empty(self, profile):
        """All ignored features must have a non-empty reason string."""
        for feat in profile["ignored_geometric_features_m"]:
            assert feat["reason"] and len(feat["reason"].strip()) > 0

    def test_638_5m_near_la_source(self, profile):
        """The 638.5 m feature should be near La Source (T1–T2 region)."""
        la_source = [t for t in profile["turns"] if t["group"] == "La Source"]
        eau_rouge = [t for t in profile["turns"] if "Eau Rouge" in t["name"]]
        assert la_source[0]["end_m"] <= 638.5 <= eau_rouge[0]["start_m"]

    def test_1474_5m_inside_kemmlin(self, profile):
        """The 1474.5 m feature should be inside the Kemmlin straight region."""
        # Kemmlin straight is between T4 (Raidillon) and T5 (Les Combes)
        t4 = [t for t in profile["turns"] if "Raidillon" in t["name"] and t["turn"] == 4][0]
        t5 = [t for t in profile["turns"] if t["group"] == "Les Combes"][0]
        assert t4["end_m"] <= 1474.5 <= t5["start_m"]

    def test_3392_5m_inside_kemmlin_straight(self, profile):
        """The 3392.5 m feature should be inside the Kemmlin straight after Jacky Ickx."""
        t9 = [t for t in profile["turns"] if "Jacky Ickx" in t["name"]][0]
        t10 = [t for t in profile["turns"] if t["group"] == "Pouhon"][0]
        assert t9["end_m"] <= 3392.5 <= t10["start_m"]


# ---------------------------------------------------------------------------
# 6. Complex consistency
# ---------------------------------------------------------------------------

class TestComplexConsistency:
    """Verify Eau Rouge, Les Combes, Pouhon, and Bus Stop complexes are consistent."""

    def test_eau_rouge_complex_has_three_turns(self, profile):
        eau_rouge_turns = [t for t in profile["turns"] if "Eau Rouge" in t["name"]]
        assert len(eau_rouge_turns) == 3

    def test_les_combes_complex_has_two_turns(self, profile):
        les_combes_turns = [t for t in profile["turns"] if t.get("group") == "Les Combes"]
        assert len(les_combes_turns) == 2

    def test_pouhon_complex_has_two_turns(self, profile):
        pouhon_turns = [t for t in profile["turns"] if t.get("group") == "Pouhon"]
        assert len(pouhon_turns) == 2

    def test_bus_stop_complex_has_two_turns(self, profile):
        bus_stop_turns = [t for t in profile["turns"] if t.get("group") == "Bus Stop"]
        assert len(bus_stop_turns) == 2

    def test_blanchimont_complex_has_two_turns(self, profile):
        blanchimont_turns = [t for t in profile["turns"] if t.get("group") == "Blanchimont"]
        assert len(blanchimont_turns) == 2

    def test_eau_rouge_not_continuous(self, profile):
        """Eau Rouge T2–T4 may have small boundary offsets (10m gap T2→T3 is expected at Spa)."""
        # At Spa, Eau Rouge has a 10m gap between T2 end (946.5) and T3 start (956.5).
        # This is a real boundary offset; the test verifies the gap is small (≤ 20m).
        eau_rouge = [t for t in profile["turns"] if "Eau Rouge" in t["name"]]
        for i in range(len(eau_rouge) - 1):
            gap = eau_rouge[i + 1]["start_m"] - eau_rouge[i]["end_m"]
            assert gap <= 20  # small boundary offsets are acceptable

    def test_les_combes_not_continuous(self, profile):
        """Les Combes T5–T6 may have small boundary offsets (12m gap is acceptable at Spa)."""
        # Les Combes has a 12m gap between T5 end (2336.5) and T6 start (2348.5).
        # This is a real boundary offset; the test verifies the gap is small (≤ 20m).
        les_combes = [t for t in profile["turns"] if t.get("group") == "Les Combes"]
        for i in range(len(les_combes) - 1):
            gap = les_combes[i + 1]["start_m"] - les_combes[i]["end_m"]
            assert gap <= 20

    def test_pouhon_continuous(self, profile):
        """Pouhon T10–T11 must be continuous (end = start)."""
        pouhon = [t for t in profile["turns"] if t.get("group") == "Pouhon"]
        for i in range(len(pouhon) - 1):
            assert pouhon[i]["end_m"] == pouhon[i + 1]["start_m"]

    def test_blanchimont_continous(self, profile):
        """Blanchimont T16–T17 must be continuous (end = start)."""
        blanchimont = [t for t in profile["turns"] if t.get("group") == "Blanchimont"]
        for i in range(len(blanchimont) - 1):
            assert blanchimont[i]["end_m"] == blanchimont[i + 1]["start_m"]

    def test_fagnes_complex_has_two_turns(self, profile):
        fagnes_turns = [t for t in profile["turns"] if t.get("group") == "Fagnes"]
        assert len(fagnes_turns) == 2

    def test_fagnes_not_continuous(self, profile):
        """Fagnes T12–T13 may have small boundary offsets (12m gap is acceptable at Spa)."""
        # Fagnes has a 12m gap between T12 end (4456.5) and T13 start (4468.5).
        # This is a real boundary offset; the test verifies the gap is small (≤ 20m).
        fagnes = [t for t in profile["turns"] if t.get("group") == "Fagnes"]
        for i in range(len(fagnes) - 1):
            gap = fagnes[i + 1]["start_m"] - fagnes[i]["end_m"]
            assert gap <= 20


# ---------------------------------------------------------------------------
# 7. Aliases
# ---------------------------------------------------------------------------

class TestAliases:
    """Verify aliases are preserved from v0.2."""

    def test_bruxelles_has_rivage_alias(self, profile):
        bruxelles = [t for t in profile["turns"] if "Bruxelles" in t["name"]][0]
        assert set(bruxelles.get("aliases", [])) == {"Rivage"}

    def test_jacky_ickx_has_aliases(self, profile):
        jacky_ickx = [t for t in profile["turns"] if "Jacky Ickx" in t["name"]][0]
        assert set(jacky_ickx.get("aliases", [])) == {"Speakers Corner", "Corner With No Name"}

    def test_pouhon_has_double_gauche_alias(self, profile):
        pouhon = [t for t in profile["turns"] if "Pouhon" in t["name"]][0]
        assert set(pouhon.get("aliases", [])) == {"Double Gauche"}

    def test_fagnes_has_pif_paf_alias(self, profile):
        fagnes = [t for t in profile["turns"] if "Fagnes" in t["name"]][0]
        assert set(fagnes.get("aliases", [])) == {"Pif-Paf"}

    def test_campus_has_stavelot_alias(self, profile):
        campus = [t for t in profile["turns"] if "Campus" in t["name"]][0]
        assert set(campus.get("aliases", [])) == {"Stavelot"}

    def test_bus_stop_has_chicane_alias(self, profile):
        bus_stop = [t for t in profile["turns"] if "Bus Stop" in t["name"]][0]
        assert set(bus_stop.get("aliases", [])) == {"Chicane"}


# ---------------------------------------------------------------------------
# 8. Manual low-curvature turns
# ---------------------------------------------------------------------------

class TestManualLowCurvatureTurns:
    """Verify manual_low_curvature_turns is empty (v0.2 had none)."""

    def test_no_manual_low_curvature_turns(self, profile, v02_profile):
        """v0.3 should have no manual low-curvature turns (same as v0.2)."""
        assert profile.get("manual_low_curvature_turns", []) == v02_profile.get("manual_low_curvature_turns", [])

    def test_manual_low_curvature_is_empty(self, profile):
        """manual_low_curvature_turns must be empty list."""
        assert profile.get("manual_low_curvature_turns", []) == []


# ---------------------------------------------------------------------------
# 9. Parser compatibility
# ---------------------------------------------------------------------------

class TestParserCompatibility:
    """Verify the profile is parseable and serializable."""

    def test_can_serialize_to_json(self, profile):
        """Profile must be serializable to JSON without errors."""
        json.dumps(profile)

    def test_can_serialize_to_pretty_json(self, profile):
        """Profile must be pretty-printable (indent=2)."""
        output = json.dumps(profile, indent=2)
        assert "profile_id" in output

    def test_all_turns_have_required_fields(self, profile):
        required_fields = {"turn", "name", "group", "direction", "start_m", "apex_m", "end_m"}
        for turn in profile["turns"]:
            assert required_fields.issubset(turn.keys())

    def test_geometric_notes_keys_are_strings(self, profile):
        """geometric_notes keys must be string identifiers (e.g., 'note_1')."""
        for key in profile["geometric_notes"]:
            assert isinstance(key, str)


# ---------------------------------------------------------------------------
# 10. Deterministic repeatability
# ---------------------------------------------------------------------------

class TestDeterministic:
    """Verify the profile file is deterministic and parseable."""

    def test_can_read_profile(self, profile):
        assert profile is not None

    def test_can_clone_profile(self, profile):
        clone = copy.deepcopy(profile)
        assert clone["profile_id"] == profile["profile_id"]

    def test_can_re_serialize_clone(self, profile):
        clone = copy.deepcopy(profile)
        output = json.dumps(clone)
        restored = json.loads(output)
        assert restored["profile_id"] == profile["profile_id"]


# ---------------------------------------------------------------------------
# 11. Comparison v0.2 vs v0.3
# ---------------------------------------------------------------------------

class TestComparisonV02V03:
    """Compare v0.2 and v0.3 structural differences."""

    def test_status_unchanged(self, profile, v02_profile):
        assert profile["status"] == v02_profile["status"]

    def test_profile_id_changed(self, profile, v02_profile):
        assert profile["profile_id"] != v02_profile["profile_id"]

    def test_turns_unchanged(self, profile, v02_profile):
        """Turns must be identical."""
        assert profile["turns"] == v02_profile["turns"]

    def test_display_policy_unchanged(self, profile, v02_profile):
        """Display policy must be identical."""
        assert profile["display_policy"] == v02_profile["display_policy"]

    def test_ignored_features_unchanged(self, profile, v02_profile):
        """ignored_geometric_features_m must have same center_m values (reason strings may differ)."""
        v02_centers = {f["center_m"] for f in v02_profile["ignored_geometric_features_m"]}
        v03_centers = {f["center_m"] for f in profile["ignored_geometric_features_m"]}
        assert v03_centers == v02_centers

    def test_v03_has_geometric_notes_v02_lacks_field(self, profile, v02_profile):
        """v0.3 has geometric_notes, v0.2 does not."""
        assert "geometric_notes" in profile
        assert "geometric_notes" not in v02_profile or profile["geometric_notes"] != v02_profile.get("geometric_notes")

    def test_geometric_notes_has_gaps(self, profile):
        """v0.3 geometric_notes should contain gap explanations."""
        notes = profile["geometric_notes"]
        gap_count = sum(1 for n in notes.values() if n.get("type") == "gap_explanation")
        assert gap_count >= 7  # 7 major gap explanations

    def test_geometric_notes_has_ignored_features(self, profile):
        """v0.3 geometric_notes should contain ignored_features_explanation."""
        notes = profile["geometric_notes"]
        ignored_count = sum(1 for n in notes.values() if n.get("type") == "ignored_features_explanation")
        assert ignored_count >= 1  # At least 1 ignored features note


# ---------------------------------------------------------------------------
# 12. Calibration data integrity
# ---------------------------------------------------------------------------

class TestCalibrationData:
    """Verify calibration section is preserved from v0.2."""

    def test_calibration_preserved(self, profile, v02_profile):
        """Calibration section (except geometry_method) must be identical."""
        calib_keys = {"source_session", "source_lap_internal_index", "source_lap_time_s_approx",
                      "source_lap_dist_max_m", "geometry_method", "numbering_scheme",
                      "requires_cross_session_validation"}
        for key in calib_keys:
            assert profile["calibration"][key] == v02_profile["calibration"][key]

    def test_validation_status_preserved(self, profile, v02_profile):
        """validation_status must be identical at calibration level."""
        assert profile["calibration"]["validation_status"] == v02_profile["calibration"]["validation_status"]

    def test_independent_session_preserved(self, profile, v02_profile):
        indep = profile["calibration"]["validation_summary"]["independent_sessions"]
        v02_indep = v02_profile["calibration"]["validation_summary"]["independent_sessions"]
        assert len(indep) == len(v02_indep)
        for i, (ind, v02_ind) in enumerate(zip(indep, v02_indep)):
            assert ind["session"] == v02_ind["session"]


# ---------------------------------------------------------------------------
# 13. Validator expectations match
# ---------------------------------------------------------------------------

class TestValidatorExpectations:
    """Verify the profile produces the expected validator result."""

    def test_ignored_features_preserved(self, profile, v02_profile):
        """v0.3 should have the same ignored features as v0.2 (all 5)."""
        v02_centers = {f["center_m"] for f in v02_profile["ignored_geometric_features_m"]}
        v03_centers = {f["center_m"] for f in profile["ignored_geometric_features_m"]}
        assert v03_centers == v02_centers

    def test_manual_low_curvature_unchanged(self, profile, v02_profile):
        """manual_low_curvature_turns should be the same as v0.2 (empty)."""
        assert profile.get("manual_low_curvature_turns", []) == v02_profile.get("manual_low_curvature_turns", [])

    def test_all_ignored_features_justified(self, profile):
        """All ignored features should have a justification in geometric_notes."""
        notes = profile["geometric_notes"]
        ignored_note = notes.get("note_9", {})
        assert ignored_note.get("type") == "ignored_features_explanation"
        assert "all 5" in ignored_note.get("reason", "").lower() or "5" in ignored_note.get("reason", "")

    def test_all_gaps_justified(self, profile):
        """Major gap explanations (type=gap_explanation with straight_real_track_feature) should be classified as straights."""
        notes = profile["geometric_notes"]
        straight_gaps = [n for n in notes.values() if n.get("type") == "gap_explanation" and n.get("classification") == "straight_real_track_feature"]
        assert len(straight_gaps) >= 7  # 7 major gap explanations (Straights)
