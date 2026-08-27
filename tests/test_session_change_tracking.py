from dataclasses import dataclass
from pathlib import Path

from session_change_tracking import (
    CHANGE_NEW,
    CHANGE_REPEATED,
    CHANGE_RESOLVED,
    MATCH_BASIS_PHYSICAL,
    MATCH_BASIS_QUALITATIVE,
    MATCH_BASIS_REFERENCE_PROFILE,
    MATCH_BASIS_STEERING,
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
    assert {
        change["match_basis"] for change in result["changes"]
    } == {MATCH_BASIS_PHYSICAL}


def _profile_item(*, shape="one_application", start=100, end=150):
    return {
        "start_distance_m": start,
        "end_distance_m": end,
        "reference_action_profiles": [{
            "channel": "throttle",
            "shape_sequence": [shape],
            "shape_summary": "ignored free-form summary",
        }],
    }


def _qualitative_item(*, direction="aumentar", start=100, end=150):
    return {
        "start_distance_m": start,
        "end_distance_m": end,
        "targets": [f"{direction} el acelerador hacia la referencia"],
        "driver_cues": [{
            "kind": "qualitative_reference_level",
            "source": "deterministic_observed_level_to_reference",
            "channel": "throttle",
            "channels": ["throttle"],
            "text": "this text is not identity",
        }],
    }


def _steering_item(*, valid=True, start=100, end=150):
    item = {
        "start_distance_m": start,
        "end_distance_m": end,
        "steering_coaching_requested": True,
        "validated_recommendation": "reducir la magnitud del volante",
        "steering_direction": "higher_in_comparison_lap",
        "driver_cues": [{
            "kind": "validated_llm_steering",
            "source": "validated_llm_recommendation+python_direction",
            "channel": "steering_magnitude",
        }],
    }
    if not valid:
        item["driver_cues"][0]["source"] = "unvalidated"
    return item


def test_reference_profile_same_structure_repeats():
    result = compare_plans([_profile_item()], [_profile_item()])
    assert [(change["status"], change["match_basis"]) for change in result["changes"]] == [
        (CHANGE_REPEATED, MATCH_BASIS_REFERENCE_PROFILE)
    ]


def test_reference_profile_different_structure_is_new_and_resolved():
    result = compare_plans(
        [_profile_item(shape="two_applications")],
        [_profile_item(shape="one_application")],
    )
    assert [(change["status"], change["match_basis"]) for change in result["changes"]] == [
        (CHANGE_NEW, MATCH_BASIS_REFERENCE_PROFILE),
        (CHANGE_RESOLVED, MATCH_BASIS_REFERENCE_PROFILE),
    ]


def test_qualitative_compatible_repeats_without_using_cue_text():
    current = _qualitative_item()
    previous = _qualitative_item()
    current["driver_cues"][0]["text"] = "completely different presentation"
    result = compare_plans([current], [previous])
    assert [(change["status"], change["match_basis"]) for change in result["changes"]] == [
        (CHANGE_REPEATED, MATCH_BASIS_QUALITATIVE)
    ]


def test_qualitative_does_not_cross_match_reference_profile():
    result = compare_plans([_qualitative_item()], [_profile_item()])
    assert not any(change["status"] == CHANGE_REPEATED for change in result["changes"])
    assert {change["match_basis"] for change in result["changes"]} == {
        MATCH_BASIS_QUALITATIVE,
        MATCH_BASIS_REFERENCE_PROFILE,
    }


def test_validated_steering_repeats_and_invalid_steering_fails_closed():
    valid = compare_plans([_steering_item()], [_steering_item()])
    assert [(change["status"], change["match_basis"]) for change in valid["changes"]] == [
        (CHANGE_REPEATED, MATCH_BASIS_STEERING)
    ]
    invalid = compare_plans([_steering_item(valid=False)], [_steering_item(valid=False)])
    assert invalid["changes"] == []


def test_structured_category_requires_physical_zone_overlap():
    result = compare_plans(
        [_profile_item(start=200, end=250)],
        [_profile_item(start=100, end=150)],
    )
    assert not any(change["status"] == CHANGE_REPEATED for change in result["changes"])
    assert [change["status"] for change in result["changes"]] == [CHANGE_NEW, CHANGE_RESOLVED]


def test_compare_plans_does_not_mutate_input_plans():
    import copy

    current = [_profile_item()]
    previous = [_qualitative_item()]
    current_before = copy.deepcopy(current)
    previous_before = copy.deepcopy(previous)
    result = compare_plans(current, previous)

    assert current == current_before
    assert previous == previous_before
    assert result["observational_only"] is True
    assert result["affects_next_stint_plan"] is False
    assert result["historical_actions_authorized"] is False


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
