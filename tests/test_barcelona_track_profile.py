from __future__ import annotations

import json
from pathlib import Path

from cross_session_zone_localization import find_validated_track_profile
from validate_track_profiles_v0_2 import validate_profile_v0_2


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO_ROOT / "track_profiles"
PROFILE_PATH = PROFILE_DIR / "barcelona_profile_v0_1.json"


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_barcelona_profile_has_exact_lmu_identity_and_multi_session_status() -> None:
    profile = load_profile()

    assert profile["track"] == "Circuit de Barcelona"
    assert profile["layout"] == "Circuit de Barcelona"
    assert profile["status"] == "VALIDATED_MULTI_SESSION"
    assert profile["calibration"]["requires_cross_session_validation"] is False
    assert profile["calibration"]["validation_status"] == "PASS"
    assert len(profile["calibration"]["validation_summary"]["independent_sessions"]) == 3


def test_barcelona_profile_preserves_fia_fourteen_turn_sequence() -> None:
    turns = load_profile()["turns"]

    assert [turn["turn"] for turn in turns] == list(range(1, 15))
    assert [turn["direction"] for turn in turns] == [
        "right", "left", "right", "right", "left", "left", "left",
        "right", "right", "left", "left", "right", "right", "right",
    ]
    assert all(turn["start_m"] <= turn["apex_m"] <= turn["end_m"] for turn in turns)
    assert all(first["end_m"] <= second["start_m"] for first, second in zip(turns, turns[1:]))


def test_barcelona_multi_session_profile_is_available_for_production_lookup() -> None:
    profile, path = find_validated_track_profile(
        PROFILE_DIR,
        track="Circuit de Barcelona",
        layout="Circuit de Barcelona",
    )

    assert profile is not None
    assert path == PROFILE_PATH


def test_barcelona_profile_passes_deterministic_validator() -> None:
    result = validate_profile_v0_2(load_profile(), lap_length_m=4657.0)

    assert result["error_count"] == 0
    assert result["status"] in {"VALID", "VALID_WITH_WARNINGS"}
