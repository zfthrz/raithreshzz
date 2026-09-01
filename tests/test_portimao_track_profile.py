from __future__ import annotations

import json
from pathlib import Path

from cross_session_zone_localization import find_validated_track_profile
from track_location import resolve_interval
from validate_track_profiles_v0_2 import validate_profile_v0_2


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO_ROOT / "track_profiles"
PROFILE_PATH = PROFILE_DIR / "portimao_profile_v0_1.json"


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_portimao_profile_has_exact_lmu_identity_and_single_session_status() -> None:
    profile = load_profile()
    assert profile["track"] == "Algarve International Circuit"
    assert profile["layout"] == "Algarve International Circuit"
    assert profile["status"] == "VALIDATED_SINGLE_SESSION"
    assert profile["calibration"]["requires_cross_session_validation"] is True
    assert profile["calibration"]["source_lap_internal_index"] == 3
    assert len(profile["calibration"]["same_session_validation_laps"]) == 2


def test_portimao_profile_preserves_official_fifteen_turn_sequence() -> None:
    profile = load_profile()
    turns = profile["turns"]
    assert [turn["turn"] for turn in turns] == list(range(1, 16))
    assert [turn["direction"] for turn in turns] == [
        "right", "right", "right", "left", "left", "left",
        "right", "right", "left", "right", "right", "left",
        "left", "right", "right",
    ]
    assert all(turn["start_m"] <= turn["apex_m"] <= turn["end_m"] for turn in turns)
    assert all(first["end_m"] <= second["start_m"] for first, second in zip(turns, turns[1:]))


def test_portimao_single_session_profile_fails_closed_for_production_lookup() -> None:
    profile, path = find_validated_track_profile(
        PROFILE_DIR,
        track="Algarve International Circuit",
        layout="Algarve International Circuit",
    )
    assert profile is None
    assert path is None


def test_portimao_profile_resolves_named_regions_deterministically() -> None:
    profile = load_profile()
    assert resolve_interval(profile, 360.0, 455.0)["label"].endswith("Primeira")
    assert resolve_interval(profile, 1900.0, 2100.0)["label"].endswith("Turns 7–8")
    assert resolve_interval(profile, 2660.0, 2790.0)["label"].endswith("Portimao")
    assert resolve_interval(profile, 3860.0, 4020.0)["label"].endswith("Galp")


def test_portimao_profile_passes_deterministic_validator_without_errors() -> None:
    result = validate_profile_v0_2(load_profile(), lap_length_m=4633.0)
    assert result["error_count"] == 0
    assert result["status"] in {"VALID", "VALID_WITH_WARNINGS"}
