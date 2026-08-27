from dataclasses import dataclass
from pathlib import Path

from session_change_tracking import (
    CHANGE_NEW,
    CHANGE_REPEATED,
    CHANGE_RESOLVED,
    compare_plans,
    same_observational_action,
)


def _item(
    *,
    start=100.0,
    end=150.0,
    field="braking_point_patterns",
    direction="later",
):
    return {
        "plan_label": "A",
        "start_distance_m": start,
        "end_distance_m": end,
        field: [
            {
                "status": "REPEATED",
                "coaching_direction": direction,
            }
        ],
    }


def test_same_action_same_overlapping_zone_matches():
    assert same_observational_action(
        _item(start=100, end=150),
        _item(start=120, end=170),
    )


def test_same_action_non_overlapping_zone_does_not_match():
    assert not same_observational_action(
        _item(start=100, end=150),
        _item(start=151, end=200),
    )


def test_opposite_direction_does_not_match():
    assert not same_observational_action(
        _item(direction="later"),
        _item(direction="earlier"),
    )


def test_different_action_family_does_not_match():
    assert not same_observational_action(
        _item(field="braking_point_patterns"),
        _item(field="throttle_onset_patterns"),
    )


def test_missing_physical_interval_fails_closed():
    current = _item()
    current.pop("start_distance_m")
    current.pop("end_distance_m")

    assert not same_observational_action(
        current,
        _item(),
    )


def test_compare_plans_classifies_repeated_new_and_resolved():
    repeated_current = _item(start=110, end=145)
    repeated_previous = _item(start=100, end=150)

    new_current = _item(
        start=300,
        end=350,
        field="throttle_onset_patterns",
        direction="later",
    )

    resolved_previous = _item(
        start=500,
        end=550,
        field="brake_release_patterns",
        direction="earlier",
    )

    result = compare_plans(
        [repeated_current, new_current],
        [repeated_previous, resolved_previous],
    )

    statuses = [item["status"] for item in result["changes"]]

    assert statuses == [
        CHANGE_REPEATED,
        CHANGE_NEW,
        CHANGE_RESOLVED,
    ]

    assert result["change_counts"] == {
        CHANGE_NEW: 1,
        CHANGE_REPEATED: 1,
        CHANGE_RESOLVED: 1,
    }


def test_compare_plans_is_observational_only():
    result = compare_plans([], [])

    assert result["observational_only"] is True
    assert result["affects_next_stint_plan"] is False
    assert result["historical_actions_authorized"] is False

def test_same_zone_tracks_actions_individually():
    previous = {
        "plan_label": "B",
        "start_distance_m": 138.0,
        "end_distance_m": 276.0,
        "braking_point_patterns": [
            {"coaching_direction": "later"}
        ],
        "brake_release_patterns": [
            {"coaching_direction": "later"}
        ],
    }

    current = {
        "plan_label": "A",
        "start_distance_m": 124.0,
        "end_distance_m": 293.0,
        "braking_point_patterns": [
            {"coaching_direction": "later"}
        ],
        "brake_release_patterns": [
            {"coaching_direction": "earlier"}
        ],
        "throttle_release_patterns": [
            {"coaching_direction": "later"}
        ],
    }

    result = compare_plans(
        [current],
        [previous],
    )

    observed = {
        (
            change["status"],
            change["action"]["family"],
            change["action"]["coaching_direction"],
        )
        for change in result["changes"]
    }

    assert observed == {
        (CHANGE_REPEATED, "braking_point", "later"),
        (CHANGE_NEW, "brake_release", "earlier"),
        (CHANGE_NEW, "throttle_release", "later"),
        (CHANGE_RESOLVED, "brake_release", "later"),
    }


def _write_analysis(
    path,
    *,
    timestamp,
    track="Circuit de Spa-Francorchamps",
    layout="Circuit de Spa-Francorchamps",
    variant="LMP2_ELMS",
):
    import json

    path.write_text(
        json.dumps({
            "metadata": {
                "timestamp_utc": timestamp,
                "track": track,
                "vehicle_identity": {
                    "family": "LMP2",
                    "variant": variant,
                    "car_name_raw": "test car",
                },
                "session_context": {
                    "lmu_track_name": track,
                    "lmu_track_layout": layout,
                },
            }
        }),
        encoding="utf-8",
    )


def _record(
    *,
    key,
    analysis_path,
    debrief_path,
    validated=True,
):
    from types import SimpleNamespace

    return SimpleNamespace(
        session_key=key,
        analysis_path=analysis_path,
        debrief_path=debrief_path,
        has_validated_debrief=validated,
    )


def test_previous_session_uses_latest_compatible_timestamp(tmp_path):
    from session_change_tracking import find_previous_compatible_session

    current_analysis = tmp_path / "current.json"
    older_analysis = tmp_path / "older.json"
    latest_analysis = tmp_path / "latest.json"

    _write_analysis(
        current_analysis,
        timestamp="2026-08-20T05:49:39Z",
    )
    _write_analysis(
        older_analysis,
        timestamp="2026-08-10T00:00:00Z",
    )
    _write_analysis(
        latest_analysis,
        timestamp="2026-08-12T07:41:11Z",
    )

    debrief = tmp_path / "debrief.json"
    debrief.write_text("{}", encoding="utf-8")

    current = _record(
        key="current",
        analysis_path=current_analysis,
        debrief_path=debrief,
    )
    older = _record(
        key="older",
        analysis_path=older_analysis,
        debrief_path=debrief,
    )
    latest = _record(
        key="latest",
        analysis_path=latest_analysis,
        debrief_path=debrief,
    )

    selected = find_previous_compatible_session(
        current,
        [older, current, latest],
    )

    assert selected is latest


def test_previous_session_rejects_vehicle_variant_mismatch(tmp_path):
    from session_change_tracking import find_previous_compatible_session

    current_analysis = tmp_path / "current.json"
    wec_analysis = tmp_path / "wec.json"

    _write_analysis(
        current_analysis,
        timestamp="2026-08-20T05:49:39Z",
        variant="LMP2_ELMS",
    )
    _write_analysis(
        wec_analysis,
        timestamp="2026-08-19T05:49:39Z",
        variant="LMP2_WEC",
    )

    debrief = tmp_path / "debrief.json"
    debrief.write_text("{}", encoding="utf-8")

    current = _record(
        key="current",
        analysis_path=current_analysis,
        debrief_path=debrief,
    )
    wec = _record(
        key="wec",
        analysis_path=wec_analysis,
        debrief_path=debrief,
    )

    assert (
        find_previous_compatible_session(
            current,
            [current, wec],
        )
        is None
    )


def test_previous_session_ignores_unvalidated_debrief(tmp_path):
    from session_change_tracking import find_previous_compatible_session

    current_analysis = tmp_path / "current.json"
    previous_analysis = tmp_path / "previous.json"

    _write_analysis(
        current_analysis,
        timestamp="2026-08-20T05:49:39Z",
    )
    _write_analysis(
        previous_analysis,
        timestamp="2026-08-12T07:41:11Z",
    )

    debrief = tmp_path / "debrief.json"
    debrief.write_text("{}", encoding="utf-8")

    current = _record(
        key="current",
        analysis_path=current_analysis,
        debrief_path=debrief,
    )
    previous = _record(
        key="previous",
        analysis_path=previous_analysis,
        debrief_path=debrief,
        validated=False,
    )

    assert (
        find_previous_compatible_session(
            current,
            [current, previous],
        )
        is None
    )
