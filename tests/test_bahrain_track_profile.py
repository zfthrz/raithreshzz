from __future__ import annotations

import json
from pathlib import Path

from cross_session_zone_localization import find_validated_track_profile
from track_location import resolve_interval
from validate_track_profiles_v0_2 import validate_profile_v0_2


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO_ROOT / "track_profiles"
PROFILE_PATH = PROFILE_DIR / "bahrain_profile_v0_1.json"


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_bahrain_profile_has_exact_lmu_identity_and_multi_session_status() -> None:
    profile = load_profile()
    assert profile["track"] == "Bahrain International Circuit"
    assert profile["layout"] == "Bahrain International Circuit"
    assert profile["status"] == "VALIDATED_MULTI_SESSION"
    assert profile["calibration"]["requires_cross_session_validation"] is False
    assert profile["calibration"]["validation_status"] == "PASS"
    assert profile["calibration"]["source_lap_internal_index"] == 4
    assert len(profile["calibration"]["same_session_validation_laps"]) == 2


def test_bahrain_profile_preserves_fia_fifteen_turn_sequence() -> None:
    turns = load_profile()["turns"]
    assert [turn["turn"] for turn in turns] == list(range(1, 16))
    assert [turn["direction"] for turn in turns] == [
        "right", "left", "right", "right", "left", "right", "left",
        "right", "left", "left", "left", "right", "right", "right", "right",
    ]
    assert all(turn["start_m"] <= turn["apex_m"] <= turn["end_m"] for turn in turns)
    assert all(first["end_m"] <= second["start_m"] for first, second in zip(turns, turns[1:]))


def test_bahrain_multi_session_profile_is_available_for_production_lookup() -> None:
    profile, path = find_validated_track_profile(
        PROFILE_DIR,
        track="Bahrain International Circuit",
        layout="Bahrain International Circuit",
    )
    assert profile is not None
    assert path == PROFILE_PATH


def test_bahrain_profile_resolves_numbered_complexes_deterministically() -> None:
    profile = load_profile()
    assert resolve_interval(profile, 710.0, 850.0)["label"].endswith("Turns 1–3")
    assert resolve_interval(profile, 2580.0, 2760.0)["label"].endswith("Turns 9–10")
    assert resolve_interval(profile, 4880.0, 4960.0)["label"].endswith("Turns 14–15")


def test_bahrain_profile_passes_deterministic_validator_without_errors() -> None:
    result = validate_profile_v0_2(load_profile(), lap_length_m=5375.0)
    assert result["error_count"] == 0
    assert result["status"] in {"VALID", "VALID_WITH_WARNINGS"}
