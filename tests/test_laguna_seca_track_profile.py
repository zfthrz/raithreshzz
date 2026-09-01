from __future__ import annotations

import json
from pathlib import Path

from cross_session_zone_localization import find_validated_track_profile
from track_location import resolve_interval
from validate_track_profiles_v0_2 import validate_profile_v0_2


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO_ROOT / "track_profiles"
PROFILE_PATH = PROFILE_DIR / "laguna_seca_profile_v0_1.json"


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_laguna_profile_has_exact_lmu_identity_and_single_session_status() -> None:
    profile = load_profile()
    assert profile["track"] == "WeatherTech Raceway Laguna Seca"
    assert profile["layout"] == "WeatherTech Raceway Laguna Seca"
    assert profile["status"] == "VALIDATED_SINGLE_SESSION"
    assert profile["calibration"]["requires_cross_session_validation"] is True
    assert profile["calibration"]["source_lap_internal_index"] == 3
    assert len(profile["calibration"]["same_session_validation_laps"]) == 3


def test_laguna_profile_preserves_eleven_integer_turns_and_corkscrew_components() -> None:
    turns = load_profile()["turns"]
    assert [turn["turn"] for turn in turns] == list(range(1, 12))
    corkscrew = turns[7]
    assert corkscrew["name"] == "Corkscrew"
    assert [part["label"] for part in corkscrew["components"]] == ["T8", "T8A"]
    assert [part["direction"] for part in corkscrew["components"]] == ["left", "right"]
    assert all(turn["start_m"] <= turn["apex_m"] <= turn["end_m"] for turn in turns)
    assert all(first["end_m"] <= second["start_m"] for first, second in zip(turns, turns[1:]))


def test_laguna_single_session_profile_fails_closed_for_production_lookup() -> None:
    profile, path = find_validated_track_profile(
        PROFILE_DIR,
        track="WeatherTech Raceway Laguna Seca",
        layout="WeatherTech Raceway Laguna Seca",
    )
    assert profile is None
    assert path is None


def test_laguna_profile_resolves_named_regions_deterministically() -> None:
    profile = load_profile()
    assert resolve_interval(profile, 430.0, 550.0)["label"].endswith("Andretti Hairpin")
    assert resolve_interval(profile, 2430.0, 2560.0)["label"].endswith("Corkscrew")
    assert resolve_interval(profile, 2630.0, 2800.0)["label"].endswith("Rainey Curve")


def test_laguna_profile_passes_deterministic_validator_without_errors() -> None:
    result = validate_profile_v0_2(load_profile(), lap_length_m=3584.0)
    assert result["error_count"] == 0
    assert result["status"] in {"VALID", "VALID_WITH_WARNINGS"}
