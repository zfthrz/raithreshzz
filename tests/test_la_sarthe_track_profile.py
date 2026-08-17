from __future__ import annotations

import json
from pathlib import Path

from cross_session_zone_localization import find_validated_track_profile
from track_location import resolve_interval


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO_ROOT / "track_profiles"
PROFILE_PATH = PROFILE_DIR / "la_sarthe_profile_v0_1.json"


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_la_sarthe_profile_has_exact_identity_and_multisession_provenance():
    profile = load_profile()

    assert profile["status"] == "VALIDATED_MULTI_SESSION"
    assert profile["track"] == "Circuit de la Sarthe"
    assert profile["layout"] == "Circuit de la Sarthe"
    assert profile["calibration"]["validation_status"] == "PASS"
    assert len(profile["calibration"]["validation_summary"]["independent_sessions"]) == 2
    assert all(
        item["overall_status"] == "PASS"
        for item in profile["calibration"]["validation_summary"]["independent_sessions"]
    )


def test_la_sarthe_profile_uses_project_local_segments_and_aco_names():
    profile = load_profile()
    turns = profile["turns"]

    assert [item["turn"] for item in turns] == list(range(1, 20))
    assert all(item["start_m"] <= item["apex_m"] <= item["end_m"] for item in turns)
    assert all(first["end_m"] <= second["start_m"] for first, second in zip(turns, turns[1:]))
    assert {
        "Dunlop Curve",
        "Tertre Rouge Corner",
        "Daytona Chicane",
        "Michelin Chicane",
        "Mulsanne Corner",
        "Arnage Corner",
        "Motul Turn",
    }.issubset({item["name"] for item in turns})
    assert "not official FIA turn numbers" in profile["calibration"]["numbering_warning"]


def test_la_sarthe_profile_is_resolved_only_for_exact_track_and_layout():
    selected, selected_path = find_validated_track_profile(
        PROFILE_DIR,
        track="Circuit de la Sarthe",
        layout="Circuit de la Sarthe",
    )
    assert selected["profile_id"] == "circuit-de-la-sarthe-lmu-aco2026-v0.1"
    assert selected_path == PROFILE_PATH.resolve()

    missing, missing_path = find_validated_track_profile(
        PROFILE_DIR,
        track="Circuit de la Sarthe",
        layout="Circuit Bugatti",
    )
    assert missing is None
    assert missing_path is None


def test_la_sarthe_named_complexes_resolve_from_lmu_distance():
    profile = load_profile()

    assert resolve_interval(profile, 4020.0, 4260.0)["label"].endswith(
        "Daytona Chicane"
    )
    assert resolve_interval(profile, 9580.0, 9900.0)["label"].endswith(
        "Indianapolis"
    )
    assert resolve_interval(profile, 11400.0, 12400.0)["label"].endswith(
        "Porsche Curves"
    )
    assert resolve_interval(profile, 13200.0, 13480.0)["label"].endswith(
        "Ford Chicanes and Motul Turn"
    )
