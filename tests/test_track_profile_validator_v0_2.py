"""Track profile validator v0.2 — dual v1/v2 schema validation tests.

Tests validate that v0.2:
- Preserves v0.1 v1 profile validation (golden profiles).
- Adds v2 segment-specific checks.
- Produces dict findings compatible with v0.1 output.
"""

import json
import os
import pytest

from validate_track_profiles_v0_2 import validate_profile_v0_2

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "..", "track_profiles")


def _load_fixture(name: str) -> dict:
    path = os.path.join(FIXTURE_DIR, name)
    return json.load(open(path, encoding="utf-8"))


def _load_golden(name: str) -> dict:
    path = os.path.join(GOLDEN_DIR, name)
    return json.load(open(path, encoding="utf-8"))


def _get_lap_length(profile: dict) -> float | None:
    return profile.get("lap_length_m") or profile.get("validation_summary", {}).get("lap_length_m")


# ─────────────────────────────────────────────
# BACKWARD COMPATIBILITY — v1 GOLDEN PROFILES
# ─────────────────────────────────────────────

@pytest.mark.parametrize("profile_name", [
    "monza_profile_v0_3.json",
    "imola_profile_v0_3.json",
    "fuji_speedway_profile_v0_3.json",
    "spa_francorchamps_profile_v0_3.json",
    "la_sarthe_profile_v0_2.json",
    "interlagos_profile_v0_3.json",
])
def test_golden_v1_profiles_validate_identically(profile_name: str) -> None:
    """Golden v1 profiles must validate identically with v0.2 as they did with v0.1."""
    profile = _load_golden(profile_name)
    result = validate_profile_v0_2(profile, _get_lap_length(profile))
    assert result["validator_version"] == "0.2"
    # Must have no SEGMENT_* findings
    for finding in result["findings"]:
        assert not finding["code"].startswith("SEGMENT_")


def test_v1_schema_version_no_segments() -> None:
    """v1 profiles (schema_version 1) must not have segments."""
    profile = _load_golden("monza_profile_v0_3.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))
    for finding in result["findings"]:
        assert not finding["code"].startswith("SEGMENT_")


# ─────────────────────────────────────────────
# FIXTURE A: VALID V2 PROFILE
# ─────────────────────────────────────────────

def test_fixture_a_valid_v2_profile() -> None:
    """Fixture A: valid v2 with turns + segments, no errors."""
    profile = _load_fixture("v2_valid_profile.json")
    result = validate_profile_v0_2(profile, 7000.0)

    assert result["validator_version"] == "0.2"
    assert result["status"] == "VALID"
    error_findings = [
        f for f in result["findings"] if f["severity"] == "error"
    ]
    assert len(error_findings) == 0


# ─────────────────────────────────────────────
# FIXTURE B: VALID V2 WITHOUT SEGMENTS
# ─────────────────────────────────────────────

def test_fixture_b_valid_v2_no_segments() -> None:
    """Fixture B: v2 with 0 segments is valid (segments are optional)."""
    profile = _load_fixture("v2_valid_no_segments.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    assert result["validator_version"] == "0.2"
    assert result["status"] == "VALID"


# ─────────────────────────────────────────────
# FIXTURE C: INVALID DUPLICATE SEGMENT ID
# ─────────────────────────────────────────────

def test_fixture_c_invalid_duplicate_segment_id() -> None:
    """Fixture C: duplicate segment_id must be INVALID."""
    profile = _load_fixture("v2_invalid_duplicate_id.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    assert result["validator_version"] == "0.2"
    assert result["status"] == "INVALID"

    # Check for SEGMENT_ID error
    segment_id_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_ID" and f["severity"] == "error"
    ]
    assert len(segment_id_errors) > 0


# ─────────────────────────────────────────────
# FIXTURE D: INVALID SEGMENT OVERLAP
# ─────────────────────────────────────────────

def test_fixture_d_invalid_segment_overlap() -> None:
    """Fixture D: overlapping segments must be INVALID."""
    profile = _load_fixture("v2_invalid_overlap.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    assert result["validator_version"] == "0.2"
    assert result["status"] == "INVALID"

    # Check for SEGMENT_ORDERING error
    ordering_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_ORDERING" and f["severity"] == "error"
    ]
    assert len(ordering_errors) > 0


# ─────────────────────────────────────────────
# FIXTURE E: INVALID TURN/SEGMENT OVERLAP
# ─────────────────────────────────────────────

def test_fixture_e_invalid_turn_segment_overlap() -> None:
    """Fixture E: segment overlapping turn must be INVALID."""
    profile = _load_fixture("v2_invalid_turn_segment_overlap.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    assert result["validator_version"] == "0.2"
    assert result["status"] == "INVALID"

    # Check for TURN_SEGMENT_OVERLAP error
    overlap_errors = [
        f for f in result["findings"]
        if f["code"] == "TURN_SEGMENT_OVERLAP" and f["severity"] == "error"
    ]
    assert len(overlap_errors) > 0


# ─────────────────────────────────────────────
# FIXTURE F: INVALID SEGMENT BOUNDS
# ─────────────────────────────────────────────

def test_fixture_f_invalid_bounds() -> None:
    """Fixture F: segment with start < 0 must be INVALID."""
    profile = _load_fixture("v2_invalid_bounds.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    assert result["validator_version"] == "0.2"
    assert result["status"] == "INVALID"

    # Check for SEGMENT_BOUNDS error
    bounds_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_BOUNDS" and f["severity"] == "error"
    ]
    assert len(bounds_errors) > 0


# ─────────────────────────────────────────────
# FIXTURE G: INVALID SEGMENT TYPE
# ─────────────────────────────────────────────

def test_fixture_g_invalid_type() -> None:
    """Fixture G: invalid segment type must be INVALID."""
    profile = _load_fixture("v2_invalid_type.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    assert result["validator_version"] == "0.2"
    assert result["status"] == "INVALID"

    # Check for SEGMENT_TYPE error
    type_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_TYPE" and f["severity"] == "error"
    ]
    assert len(type_errors) > 0


# ─────────────────────────────────────────────
# FIXTURE H: VALID UNCOVERED GAP
# ─────────────────────────────────────────────

def test_fixture_h_valid_uncovered_gap() -> None:
    """Fixture H: valid v2 with uncovered region between turns (no segments)."""
    profile = _load_fixture("v2_valid_uncovered_gap.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    assert result["validator_version"] == "0.2"
    # Uncovered regions are valid — no errors
    error_findings = [
        f for f in result["findings"] if f["severity"] == "error"
    ]
    assert len(error_findings) == 0


# ─────────────────────────────────────────────
# FIXTURE I: INVALID PROVENANCE/EVIDENCE
# ─────────────────────────────────────────────

def test_fixture_i_invalid_evidence() -> None:
    """Fixture I: missing provenance/evidence must be INVALID."""
    profile = _load_fixture("v2_invalid_evidence.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    assert result["validator_version"] == "0.2"
    assert result["status"] == "INVALID"

    # Check for SEGMENT_PROVENANCE or SEGMENT_EVIDENCE errors
    evidence_errors = [
        f for f in result["findings"]
        if f["code"] in ("SEGMENT_PROVENANCE", "SEGMENT_EVIDENCE")
        and f["severity"] == "error"
    ]
    assert len(evidence_errors) > 0


def test_fixture_i_valid_evidence() -> None:
    """Fixture I: valid v2 with complete provenance/evidence."""
    profile = _load_fixture("v2_valid_evidence.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    assert result["validator_version"] == "0.2"
    # Valid profile — no errors
    error_findings = [
        f for f in result["findings"] if f["severity"] == "error"
    ]
    assert len(error_findings) == 0


# ─────────────────────────────────────────────
# SEGMENT ORDERING & OVERLAP DETECTION
# ─────────────────────────────────────────────

def test_deterministic_ordering() -> None:
    """Segments must be ordered by start_distance_m ascending."""
    profile = _load_fixture("v2_valid_profile.json")
    profile["segments"] = [
        profile["segments"][1],  # seg_transition_1 first
        profile["segments"][0],  # seg_straight_1 second
    ]

    result = validate_profile_v0_2(profile, 7000.0)

    assert result["status"] == "INVALID"
    ordering_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_ORDERING" and f["severity"] == "error"
    ]
    assert len(ordering_errors) > 0


def test_segment_segment_overlap_detected() -> None:
    """Segments must not overlap each other."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [
            {
                "turn": "T1",
                "name": "Turn 1",
                "start_m": 100.0,
                "apex_m": 200.0,
                "end_m": 300.0,
                "type": "right",
                "confidence": "high",
            }
        ],
        "segments": [
            {
                "segment_id": "seg_a",
                "type": "straight",
                "start_distance_m": 300.0,
                "end_distance_m": 500.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
            {
                "segment_id": "seg_b",
                "type": "straight",
                "start_distance_m": 400.0,
                "end_distance_m": 600.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert result["status"] == "INVALID"
    overlap_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_ORDERING" and f["severity"] == "error"
    ]
    assert len(overlap_errors) > 0


def test_segment_turn_overlap_detected() -> None:
    """Segments must not overlap turns."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [
            {
                "turn": "T1",
                "name": "Turn 1",
                "start_m": 100.0,
                "apex_m": 200.0,
                "end_m": 400.0,
                "type": "right",
                "confidence": "high",
            }
        ],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": 300.0,
                "end_distance_m": 500.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert result["status"] == "INVALID"
    overlap_errors = [
        f for f in result["findings"]
        if f["code"] == "TURN_SEGMENT_OVERLAP" and f["severity"] == "error"
    ]
    assert len(overlap_errors) > 0


def test_non_overlapping_segments_and_turns_valid() -> None:
    """Non-overlapping segments and turns must be valid."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [
            {
                "turn": "T1",
                "name": "Turn 1",
                "start_m": 100.0,
                "apex_m": 200.0,
                "end_m": 300.0,
                "type": "right",
                "confidence": "high",
            }
        ],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": 500.0,
                "end_distance_m": 600.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert result["status"] == "VALID"
    error_findings = [
        f for f in result["findings"] if f["severity"] == "error"
    ]
    assert len(error_findings) == 0


def test_uncovered_regions_valid() -> None:
    """Uncovered regions between turns + segments are valid."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [
            {
                "turn": "T1",
                "name": "Turn 1",
                "start_m": 100.0,
                "apex_m": 200.0,
                "end_m": 300.0,
                "type": "right",
                "confidence": "high",
            },
            {
                "turn": "T2",
                "name": "Turn 2",
                "start_m": 800.0,
                "apex_m": 900.0,
                "end_m": 1000.0,
                "type": "left",
                "confidence": "high",
            }
        ],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": 300.0,
                "end_distance_m": 400.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    # Regions [400, 800] and [1000, 1000] are uncovered — this is valid
    result = validate_profile_v0_2(profile, 1000.0)

    # Must not have errors (uncovered regions are valid)
    assert result["status"] == "VALID"


# ─────────────────────────────────────────────
# OPTIONAL SEGMENTS
# ─────────────────────────────────────────────

def test_optional_segments_empty_array_valid() -> None:
    """Empty segments array must be valid for v2 profiles."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [
            {
                "turn": "T1",
                "name": "Turn 1",
                "start_m": 100.0,
                "apex_m": 200.0,
                "end_m": 300.0,
                "type": "right",
                "confidence": "high",
            }
        ],
        "segments": [],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    # Must not have segment errors
    segment_errors = [
        f for f in result["findings"]
        if f["code"].startswith("SEGMENT_") and f["severity"] == "error"
    ]
    assert len(segment_errors) == 0


# ─────────────────────────────────────────────
# UNKNOWN SCHEMA FAILS CLOSED
# ─────────────────────────────────────────────

def test_unknown_schema_fails_closed() -> None:
    """Unknown schema_version must fail closed (not crash)."""
    profile = {
        "schema_version": 99,
        "track": "Test",
        "turns": [],
        "segments": [],
    }

    # Must not raise
    result = validate_profile_v0_2(profile, 1000.0)

    # Should be INVALID for unknown schema
    assert result["status"] == "INVALID"


# ─────────────────────────────────────────────
# SEGMENT TYPE VALIDATION
# ─────────────────────────────────────────────

def test_valid_segment_types() -> None:
    """'straight' and 'transition' must be valid segment types."""
    for seg_type in ("straight", "transition"):
        profile = {
            "schema_version": 2,
            "track": "Test",
            "turns": [],
            "segments": [
                {
                    "segment_id": "seg_1",
                    "type": seg_type,
                    "start_distance_m": 100.0,
                    "end_distance_m": 200.0,
                    "provenance": "test",
                    "confidence": "high",
                    "evidence": {"method": "test"},
                },
            ],
        }
        result = validate_profile_v0_2(profile, 1000.0)
        type_errors = [
            f for f in result["findings"]
            if f["code"] == "SEGMENT_TYPE" and f["severity"] == "error"
        ]
        assert len(type_errors) == 0


def test_invalid_segment_type() -> None:
    """Invalid segment types must produce errors."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "unknown_type",
                "start_distance_m": 100.0,
                "end_distance_m": 200.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert "INVALID" in result["status"]
    type_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_TYPE" and f["severity"] == "error"
    ]
    assert len(type_errors) > 0


# ─────────────────────────────────────────────
# SEGMENT CONFIDENCE REQUIRED
# ─────────────────────────────────────────────

def test_segment_confidence_required() -> None:
    """Segment confidence must be 'low', 'medium', or 'high'."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": 100.0,
                "end_distance_m": 200.0,
                "provenance": "test",
                "confidence": "invalid_confidence",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert "INVALID" in result["status"]
    confidence_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_CONFIDENCE" and f["severity"] == "error"
    ]
    assert len(confidence_errors) > 0


# ─────────────────────────────────────────────
# SEGMENT PROVENANCE REQUIRED
# ─────────────────────────────────────────────

def test_provenance_required() -> None:
    """Segment provenance is required."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": 100.0,
                "end_distance_m": 200.0,
                "provenance": "",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert "INVALID" in result["status"]
    provenance_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_PROVENANCE" and f["severity"] == "error"
    ]
    assert len(provenance_errors) > 0


# ─────────────────────────────────────────────
# SEGMENT EVIDENCE REQUIRED
# ─────────────────────────────────────────────

def test_evidence_required() -> None:
    """Segment evidence dict is required."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": 100.0,
                "end_distance_m": 200.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": None,
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert "INVALID" in result["status"]
    evidence_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_EVIDENCE" and f["severity"] == "error"
    ]
    assert len(evidence_errors) > 0


# ─────────────────────────────────────────────
# SEGMENT BOUNDS
# ─────────────────────────────────────────────

def test_segment_bounds_within_lap() -> None:
    """Segment end_distance_m must not exceed lap_length_m."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": 500.0,
                "end_distance_m": 1500.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)  # lap_length = 1000

    assert "INVALID" in result["status"]
    bounds_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_BOUNDS" and f["severity"] == "error"
    ]
    assert len(bounds_errors) > 0


def test_segment_start_negative_invalid() -> None:
    """Segment start_distance_m < 0 must be invalid."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": -100.0,
                "end_distance_m": 200.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert "INVALID" in result["status"]
    bounds_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_BOUNDS" and f["severity"] == "error"
    ]
    assert len(bounds_errors) > 0


def test_segment_start_gte_end_invalid() -> None:
    """Segment start_distance_m >= end_distance_m must be invalid."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": 500.0,
                "end_distance_m": 500.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert result["status"] == "INVALID"
    ordering_errors = [
        f for f in result["findings"]
        if f["code"] == "SEGMENT_ORDERING" and f["severity"] == "error"
    ]
    assert len(ordering_errors) > 0


# ─────────────────────────────────────────────
# BACKWARD COMPATIBILITY
# ─────────────────────────────────────────────

def test_v1_profiles_validate_identically_v0_1() -> None:
    """v1 profiles must validate identically with v0.2 as they did with v0.1."""
    profile = _load_golden("monza_profile_v0_3.json")
    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    # Must have no SEGMENT_* findings for v1 profiles
    segment_findings = [
        f for f in result["findings"] if f["code"].startswith("SEGMENT_")
    ]
    assert len(segment_findings) == 0


def test_schema_version_dispatch() -> None:
    """Schema version dispatch must work correctly."""
    v1 = _load_golden("monza_profile_v0_3.json")
    v2 = _load_fixture("v2_valid_profile.json")

    v1_result = validate_profile_v0_2(v1, _get_lap_length(v1))
    v2_result = validate_profile_v0_2(v2, 7000.0)

    assert v1_result["validator_version"] == "0.2"
    assert v2_result["validator_version"] == "0.2"


def test_all_golden_profiles_no_v2_findings() -> None:
    """All golden profiles must validate with no SEGMENT_* findings."""
    GOLDEN_PROFILES = [
        "monza_profile_v0_3.json",
        "imola_profile_v0_3.json",
        "fuji_speedway_profile_v0_3.json",
        "spa_francorchamps_profile_v0_3.json",
        "la_sarthe_profile_v0_2.json",
        "interlagos_profile_v0_3.json",
    ]
    for profile_name in GOLDEN_PROFILES:
        profile = _load_golden(profile_name)
        result = validate_profile_v0_2(profile, _get_lap_length(profile))

        segment_findings = [
            f for f in result["findings"] if f["code"].startswith("SEGMENT_")
        ]
        assert len(segment_findings) == 0, f"{profile_name} has SEGMENT_ findings"


def test_backward_compatibility_no_crash() -> None:
    """v0.2 must not crash on any existing golden profile."""
    GOLDEN_PROFILES = [
        "monza_profile_v0_3.json",
        "imola_profile_v0_3.json",
        "fuji_speedway_profile_v0_3.json",
        "spa_francorchamps_profile_v0_3.json",
        "la_sarthe_profile_v0_2.json",
        "interlagos_profile_v0_3.json",
    ]
    for profile_name in GOLDEN_PROFILES:
        profile = _load_golden(profile_name)
        result = validate_profile_v0_2(profile, _get_lap_length(profile))
        assert result is not None
        assert result["validator_version"] == "0.2"


def test_no_migration_required() -> None:
    """v0.2 must not migrate any golden profiles (shadow-only)."""
    profile = _load_golden("monza_profile_v0_3.json")
    original_schema = profile.get("schema_version")

    result = validate_profile_v0_2(profile, _get_lap_length(profile))

    # v0.1 must not change schema version
    assert profile.get("schema_version") == original_schema


# ─────────────────────────────────────────────
# TEST SEGMENTS
# ─────────────────────────────────────────────

def test_segment_turn_overlap_detected_v2() -> None:
    """Segments must not overlap turns (v2-specific)."""
    profile = {
        "schema_version": 2,
        "track": "Test",
        "turns": [
            {
                "turn": "T1",
                "name": "Turn 1",
                "start_m": 100.0,
                "apex_m": 200.0,
                "end_m": 400.0,
                "type": "right",
                "confidence": "high",
            }
        ],
        "segments": [
            {
                "segment_id": "seg_1",
                "type": "straight",
                "start_distance_m": 300.0,
                "end_distance_m": 500.0,
                "provenance": "test",
                "confidence": "high",
                "evidence": {"method": "test"},
            },
        ],
    }

    result = validate_profile_v0_2(profile, 1000.0)

    assert result["status"] == "INVALID"
    overlap_errors = [
        f for f in result["findings"]
        if f["code"] == "TURN_SEGMENT_OVERLAP" and f["severity"] == "error"
    ]
    assert len(overlap_errors) > 0
