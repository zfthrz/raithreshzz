from __future__ import annotations

import json
from pathlib import Path

from cross_session_zone_localization import find_validated_track_profile
from track_location import resolve_interval


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO_ROOT / "track_profiles"
PROFILE_PATH = PROFILE_DIR / "daytona_road_course_profile_v0_1.json"


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_daytona_profile_has_exact_lmu_identity_and_multisession_provenance():
    profile = load_profile()

    assert profile["status"] == "VALIDATED_MULTI_SESSION"
    assert profile["track"] == "Daytona International Speedway"
    assert profile["layout"] == "Daytona International Speedway Road Course"
    assert profile["calibration"]["validation_status"] == "PASS"
    independent = profile["calibration"]["validation_summary"]["independent_sessions"]
    assert len(independent) == 2
    assert all(item["overall_status"] == "PASS" for item in independent)
    assert all(item["gps_coverage"] == 1.0 for item in independent)


def test_daytona_profile_uses_verified_twelve_turn_road_course_scheme():
    profile = load_profile()
    turns = profile["turns"]

    assert [item["turn"] for item in turns] == list(range(1, 13))
    assert all(item["start_m"] <= item["apex_m"] <= item["end_m"] for item in turns)
    assert all(first["end_m"] <= second["start_m"] for first, second in zip(turns, turns[1:]))
    assert {
        "Kink",
        "International Horseshoe",
        "Dogleg",
        "West Horseshoe",
        "Le Mans Chicane Entry",
        "Le Mans Chicane Exit",
    }.issubset({item["name"] for item in turns})
    assert {item["turn"] for item in profile["manual_low_curvature_turns"]} == {
        7,
        8,
        11,
        12,
    }


def test_daytona_profile_is_resolved_only_for_exact_road_course_layout():
    selected, selected_path = find_validated_track_profile(
        PROFILE_DIR,
        track="Daytona International Speedway",
        layout="Daytona International Speedway Road Course",
    )
    assert selected["profile_id"] == "daytona-road-course-lmu-12turn-v0.1"
    assert selected_path == PROFILE_PATH.resolve()

    missing, missing_path = find_validated_track_profile(
        PROFILE_DIR,
        track="Daytona International Speedway",
        layout="Daytona International Speedway Oval",
    )
    assert missing is None
    assert missing_path is None


def test_daytona_named_regions_resolve_from_lmu_distance():
    profile = load_profile()

    assert resolve_interval(profile, 900.0, 1000.0)["label"].endswith(
        "International Horseshoe"
    )
    assert resolve_interval(profile, 3780.0, 4100.0)["label"].endswith(
        "Le Mans Chicane"
    )
    assert resolve_interval(profile, 4400.0, 4950.0)["label"].endswith(
        "Speedway Turns 3–4"
    )
