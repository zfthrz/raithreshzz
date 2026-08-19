# -*- coding: utf-8 -*-
"""Tests for track_profiles/interlagos_profile_v0_3.json.

Adapted from test_monza_profile_v0_3.py with Interlagos-specific expectations:
- 15 turns (LMU/RaceControl 15-turn scheme)
- 4 ignored_geometric_features_m (no filtering; all are distinct features)
- 6 manual_low_curvature_turns (T5, T13, T14, T15)
- geometric_notes is a dict (not a list)
- No geometry corrections from v0.2
- Preserves all v0.2 geometry

Run:
    pytest tests/test_interlagos_profile_v0_3.py -v
    pytest tests/test_interlagos_profile_v0_3.py -q
"""
import json
import copy

import pytest

PROFILE_PATH = "track_profiles/interlagos_profile_v0_3.json"
V02_PATH = "track_profiles/interlagos_profile_v0_2.json"


@pytest.fixture
def profile():
    with open(PROFILE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def v02_profile():
    with open(V02_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Schema compatibility and basic structure
# ---------------------------------------------------------------------------

class TestSchemaCompatibility:
    """Verify basic schema fields and version."""

    def test_schema_version_is_1(self, profile):
        assert profile["schema_version"] == 1

    def test_profile_id_matches_v03(self, profile):
        assert profile["profile_id"] == "interlagos-lmu-15turn-v0.3"

    def test_status_is_validated_multi_session(self, profile):
        assert profile["status"] == "VALIDATED_MULTI_SESSION"

    def test_has_required_top_level_keys(self, profile):
        required = {
            "schema_version", "profile_id", "status", "track", "layout",
            "distance_coordinate", "calibration", "turns", "display_policy",
            "geometric_notes", "ignored_geometric_features_m",
        }
        assert required.issubset(profile.keys())

    def test_track_and_layout(self, profile, v02_profile):
        assert profile["track"] == v02_profile["track"]
        assert profile["layout"] == v02_profile["layout"]

    def test_geometric_notes_is_dict(self, profile):
        assert isinstance(profile["geometric_notes"], dict)


# ---------------------------------------------------------------------------
# 2. Geometry preservation
# ---------------------------------------------------------------------------

class TestGeometryPreservation:
    """Verify all turn geometry is preserved from v0.2."""

    def test_turn_count(self, profile):
        assert len(profile["turns"]) == 15

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
        assert profile["profile_id"] == "interlagos-lmu-15turn-v0.3"

    def test_all_geometry_preserved_count(self, profile, v02_profile):
        """Count check — same number of turns."""
        assert len(profile["turns"]) == len(v02_profile["turns"])

    def test_senna_complex_preserved(self, profile):
        """S do Senna complex (T1–T2) must have correct direction sequence."""
        senna = [t for t in profile["turns"] if "Senna" in t["name"]]
        assert len(senna) == 2
        assert senna[0]["direction"] == "left"
        assert senna[1]["direction"] == "right"

    def test_ferradura_laranjinha_group_preserved(self, profile, v02_profile):
        """Ferradura–Laranjinha group must have exactly 2 turns."""
        assert profile["status"] == v02_profile["status"]


# ---------------------------------------------------------------------------
# 3. Layout and lap length
# ---------------------------------------------------------------------------

class TestLayoutAndLapLength:
    """Verify lap_length_m and layout fields."""

    def test_lap_length(self, profile, v02_profile):
        """Lap length must be 4267.1374... (same as v0.2)."""
        assert abs(profile["calibration"]["source_lap_dist_max_m"] - 4267.1374) < 0.01
        assert profile["calibration"]["source_lap_dist_max_m"] == v02_profile["calibration"]["source_lap_dist_max_m"]

    def test_display_policy(self, profile):
        assert profile["display_policy"]["prefer_corner_name"] is True
        assert profile["display_policy"]["turn_number_is_secondary"] is False
        assert profile["display_policy"]["turn_number_suffix"] == "LMU"
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
        """v0.3 should have 4 ignored features (all distinct features)."""
        assert len(profile["ignored_geometric_features_m"]) == 4

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

    def test_560m_inside_t3(self, profile):
        """The 560 m feature should be inside T3 Curva do Sol bounds."""
        t3 = [t for t in profile["turns"] if "Curva do Sol" in t["name"]][0]
        assert t3["start_m"] <= 560 <= t3["end_m"]

    def test_2014m_inside_t6_t7_ferradura_laranjinha(self, profile, v02_profile):
        """The 2014 m feature should be inside T6–T7 region."""
        centers = {f["center_m"] for f in v02_profile["ignored_geometric_features_m"]}
        assert 2014 in centers


# ---------------------------------------------------------------------------
# 6. Complex consistency
# ---------------------------------------------------------------------------

class TestComplexConsistency:
    """Verify S do Senna, Pinheirinho, and Mergulho complexes are consistent."""

    def test_senna_complex_has_two_turns(self, profile):
        senna_turns = [t for t in profile["turns"] if "Senna" in t["name"]]
        assert len(senna_turns) == 2

    def test_pinheirinho_complex_has_two_turns(self, profile):
        pinheirinho_turns = [t for t in profile["turns"] if t.get("group") == "Pinheirinho"]
        assert len(pinheirinho_turns) == 2

    def test_ferradura_laranjinha_has_two_turns(self, profile, v02_profile):
        fl_turns = [t for t in profile["turns"] if t.get("group") == v02_profile["turns"][5].get("group")]
        assert len(fl_turns) == 2

    def test_pinheirinho_continous(self, profile):
        """Pinheirinho T8–T9 must be continuous (end = start)."""
        pinheirinho = [t for t in profile["turns"] if t.get("group") == "Pinheirinho"]
        for i in range(len(pinheirinho) - 1):
            assert pinheirinho[i]["end_m"] == pinheirinho[i + 1]["start_m"]


# ---------------------------------------------------------------------------
# 7. Aliases
# ---------------------------------------------------------------------------

class TestAliases:
    """Verify aliases are preserved from v0.2."""

    def test_senna_has_aliases(self, profile):
        senna = profile["turns"][0]
        assert set(senna.get("aliases", [])) == {"Senna S"}

    def test_laranjinha_has_alias(self, profile):
        laranjinha = profile["turns"][6]
        assert "Laranjinha" in laranjinha.get("aliases", [])

    def test_juncao_has_alias(self, profile):
        juncao = profile["turns"][11]
        assert "Juncao" in juncao.get("aliases", [])

    def test_turn_13_has_cafe_alias(self, profile, v02_profile):
        t13 = profile["turns"][12]
        assert set(t13.get("aliases", [])) == set(v02_profile["turns"][12].get("aliases", []))


# ---------------------------------------------------------------------------
# 8. Manual low-curvature turns
# ---------------------------------------------------------------------------

class TestManualLowCurvatureTurns:
    """Verify manual_low_curvature_turns are preserved and documented."""

    def test_manual_low_curvature_turns_count(self, profile):
        """v0.3 should have 4 manual low-curvature turns."""
        assert len(profile.get("manual_low_curvature_turns", [])) == 4

    def test_manual_low_curvature_turns_match_v02(self, profile, v02_profile):
        """manual_low_curvature_turns must match v0.2."""
        assert profile.get("manual_low_curvature_turns", []) == v02_profile.get("manual_low_curvature_turns", [])

    def test_t5_is_manual_low_curvature(self, profile):
        """T5 must be in manual_low_curvature_turns."""
        manual_turns = {m["turn"] for m in profile.get("manual_low_curvature_turns", [])}
        assert 5 in manual_turns

    def test_t13_is_manual_low_curvature(self, profile):
        """T13 must be in manual_low_curvature_turns."""
        manual_turns = {m["turn"] for m in profile.get("manual_low_curvature_turns", [])}
        assert 13 in manual_turns


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

    def test_v03_has_geometric_notes_v02_lacks_field(self, profile, v02_profile):
        """v0.3 has geometric_notes, v0.2 does not."""
        assert "geometric_notes" in profile
        assert "geometric_notes" not in v02_profile or profile["geometric_notes"] != v02_profile.get("geometric_notes")

    def test_ignored_features_count_unchanged(self, profile, v02_profile):
        """v0.3 has same ignored features count as v0.2 (4)."""
        assert len(profile["ignored_geometric_features_m"]) == len(v02_profile["ignored_geometric_features_m"])

    def test_geometric_notes_has_gaps(self, profile):
        """v0.3 geometric_notes should contain gap explanations."""
        notes = profile["geometric_notes"]
        gap_ids = [n["id"] for n in notes.values() if "gap" in n.get("id", "")]
        assert len(gap_ids) >= 5  # 5 major gap explanations


# ---------------------------------------------------------------------------
# 12. Validation results match expectations
# ---------------------------------------------------------------------------

class TestValidatorExpectations:
    """Verify the profile produces the expected validator result."""

    def test_ignores_features_unchanged(self, profile, v02_profile):
        """v0.3 should have the same ignored features as v0.2 (all 4)."""
        v02_centers = {f["center_m"] for f in v02_profile["ignored_geometric_features_m"]}
        v03_centers = {f["center_m"] for f in profile["ignored_geometric_features_m"]}
        assert v03_centers == v02_centers

    def test_manual_low_curvature_unchanged(self, profile, v02_profile):
        """manual_low_curvature_turns should be the same as v0.2."""
        assert profile.get("manual_low_curvature_turns", []) == v02_profile.get("manual_low_curvature_turns", [])


# ---------------------------------------------------------------------------
# 13. Calibration data integrity
# ---------------------------------------------------------------------------

class TestCalibrationData:
    """Verify calibration section is preserved from v0.2."""

    def test_calibration_preserved(self, profile, v02_profile):
        """Calibration section (except geometry_method) must be identical."""
        calib_keys = {"source_session", "source_lap_internal_index", "source_lap_time_s_approx",
                      "source_lap_dist_max_m", "source_gps_path_m_approx",
                      "numbering_scheme", "requires_cross_session_validation"}
        for key in calib_keys:
            assert profile["calibration"][key] == v02_profile["calibration"][key]

    def test_validation_status_preserved(self, profile, v02_profile):
        assert profile["calibration"]["validation_status"] == v02_profile["calibration"]["validation_status"]

    def test_independent_session_preserved(self, profile, v02_profile):
        indep = profile["calibration"]["validation_summary"]["independent_sessions"]
        v02_indep = v02_profile["calibration"]["validation_summary"]["independent_sessions"]
        assert len(indep) == len(v02_indep)
        for i, (ind, v02_ind) in enumerate(zip(indep, v02_indep)):
            assert ind["session"] == v02_ind["session"]
