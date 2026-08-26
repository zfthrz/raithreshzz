from session_coaching_plan import build_plan_priority_reason


def test_priority_reason_for_repeated_region_with_physical_anchor():
    item = {
        "kind": "repeated_region",
        "comparison_count": 3,
        "driver_cues": [{"text": "Frená más tarde."}, {"text": "Soltá antes."}],
        "actionable_cue_count": 2,
        "braking_point_patterns": [{"distance_m": 100.0}],
        "brake_release_patterns": [],
        "throttle_onset_patterns": [],
        "throttle_release_patterns": [],
    }

    assert build_plan_priority_reason(item) == {
        "kind": "repeated_region",
        "comparison_count": 3,
        "repeated": True,
        "has_physical_anchor": True,
        "physical_anchor_types": ["braking_point"],
        "actionable_cue_count": 2,
    }


def test_priority_reason_for_single_finding_without_physical_anchor():
    item = {
        "kind": "single_priority_finding",
        "comparisons": ["lap_2_vs_1"],
        "driver_cues": [{"text": "Aplicá gas progresivamente."}],
        "braking_point_patterns": [],
        "brake_release_patterns": [],
        "throttle_onset_patterns": [],
        "throttle_release_patterns": [],
    }

    reason = build_plan_priority_reason(item)

    assert reason["kind"] == "single_priority_finding"
    assert reason["comparison_count"] == 1
    assert reason["repeated"] is False
    assert reason["has_physical_anchor"] is False
    assert reason["physical_anchor_types"] == []
    assert reason["actionable_cue_count"] == 1


def test_priority_reason_is_safe_for_invalid_input():
    assert build_plan_priority_reason(None) == {}
