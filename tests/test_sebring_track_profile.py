from __future__ import annotations

import json
from pathlib import Path

from cross_session_zone_localization import find_validated_track_profile
from track_location import resolve_interval
from validate_track_profiles_v0_2 import validate_profile_v0_2


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO_ROOT / "track_profiles"
PROFILE_PATH = PROFILE_DIR / "sebring_profile_v0_1.json"


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_sebring_profile_has_exact_lmu_identity_and_multi_session_status() -> None:
    profile = load_profile()
    assert profile["track"] == "Sebring International Raceway"
    assert profile["layout"] == "Sebring International Raceway"
    assert profile["status"] == "VALIDATED_MULTI_SESSION"
    assert profile["calibration"]["requires_cross_session_validation"] is False
    assert profile["calibration"]["validation_status"] == "PASS"
    assert profile["calibration"]["source_lap_internal_index"] == 3
    assert len(profile["calibration"]["same_session_validation_laps"]) == 3


def test_sebring_profile_preserves_official_seventeen_turn_sequence() -> None:
    turns = load_profile()["turns"]
    assert [turn["turn"] for turn in turns] == list(range(1, 18))
    assert [turn["direction"] for turn in turns] == [
        "left", "right", "left", "right", "left", "right", "right",
        "right", "left", "right", "left", "right", "right", "left",
        "right", "right", "right",
    ]
    assert sum(turn["direction"] == "left" for turn in turns) == 6
    assert sum(turn["direction"] == "right" for turn in turns) == 11
    assert all(turn["start_m"] <= turn["apex_m"] <= turn["end_m"] for turn in turns)
    assert all(first["end_m"] <= second["start_m"] for first, second in zip(turns, turns[1:]))


def test_sebring_multi_session_profile_is_available_for_production_lookup() -> None:
    profile, path = find_validated_track_profile(
        PROFILE_DIR,
        track="Sebring International Raceway",
        layout="Sebring International Raceway",
    )
    assert profile is not None
    assert path == PROFILE_PATH


def test_sebring_profile_resolves_named_regions_deterministically() -> None:
    profile = load_profile()
    assert resolve_interval(profile, 1970.0, 2010.0)["label"].endswith("Hairpin")
    assert resolve_interval(profile, 2730.0, 2790.0)["label"].endswith("Cunningham Corner")
    assert resolve_interval(profile, 5190.0, 5500.0)["label"].endswith("Turn 17")


def test_sebring_profile_passes_deterministic_validator_without_errors() -> None:
    result = validate_profile_v0_2(load_profile(), lap_length_m=5814.0)
    assert result["error_count"] == 0
    assert result["status"] in {"VALID", "VALID_WITH_WARNINGS"}
