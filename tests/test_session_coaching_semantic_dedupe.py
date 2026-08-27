from session_coaching_plan import dedupe_semantic_next_stint_plan


def _item(
    label,
    *,
    start=100.0,
    end=200.0,
    action_kind="brake_release",
    direction="later",
    point=150.0,
    comparison=None,
):
    fields = {
        "braking_point": ("braking_point_patterns", "reference_onset_m"),
        "brake_release": ("brake_release_patterns", "reference_release_m"),
        "throttle_onset": ("throttle_onset_patterns", "reference_onset_m"),
        "throttle_release": ("throttle_release_patterns", "reference_release_m"),
    }

    item = {
        "plan_label": label,
        "kind": "single_priority_finding",
        "start_distance_m": start,
        "end_distance_m": end,
        "comparisons": [comparison or label],
        "comparison_count": 1,
        "braking_point_patterns": [],
        "brake_release_patterns": [],
        "throttle_onset_patterns": [],
        "throttle_release_patterns": [],
        "targets": [],
        "driver_cues": [{"text": f"cue-{label}"}],
    }

    field, point_key = fields[action_kind]

    item[field] = [{
        "coaching_direction": direction,
        point_key: point,
        "authorized_numeric_coaching": True,
    }]

    return item


def test_same_zone_same_physical_action_merges():
    plan = [
        _item("A", point=150.0, comparison="lap2"),
        _item("B", point=157.0, comparison="lap3"),
    ]

    result = dedupe_semantic_next_stint_plan(plan)

    assert len(result) == 1
    assert result[0]["plan_label"] == "A"
    assert result[0]["comparisons"] == ["lap2", "lap3"]
    assert result[0]["semantic_dedupe"]["merged"] is True
    assert result[0]["semantic_dedupe"]["source_plan_labels"] == ["A", "B"]
    assert result[0]["semantic_dedupe"]["shared_action_kinds"] == [
        "brake_release"
    ]


def test_brake_and_throttle_in_same_zone_remain_distinct():
    plan = [
        _item("A", action_kind="brake_release"),
        _item("B", action_kind="throttle_onset"),
    ]

    result = dedupe_semantic_next_stint_plan(plan)

    assert len(result) == 2


def test_opposite_directions_remain_distinct():
    plan = [
        _item("A", direction="later"),
        _item("B", direction="earlier"),
    ]

    result = dedupe_semantic_next_stint_plan(plan)

    assert len(result) == 2


def test_distant_physical_points_remain_distinct():
    plan = [
        _item("A", point=140.0),
        _item("B", point=170.0),
    ]

    result = dedupe_semantic_next_stint_plan(plan)

    assert len(result) == 2


def test_spatially_distinct_zones_remain_distinct():
    plan = [
        _item("A", start=100.0, end=180.0, point=150.0),
        _item("B", start=300.0, end=380.0, point=155.0),
    ]

    result = dedupe_semantic_next_stint_plan(plan)

    assert len(result) == 2


def test_partial_action_chain_overlap_does_not_merge():
    first = _item("A", action_kind="brake_release", point=150.0)
    second = _item("B", action_kind="brake_release", point=152.0)

    second["throttle_onset_patterns"] = [{
        "coaching_direction": "earlier",
        "reference_onset_m": 190.0,
        "authorized_numeric_coaching": True,
    }]

    result = dedupe_semantic_next_stint_plan([first, second])

    assert len(result) == 2


def test_first_item_survives_and_driver_cues_are_not_combined():
    first = _item("A", point=150.0)
    second = _item("B", point=155.0)

    result = dedupe_semantic_next_stint_plan([first, second])

    assert len(result) == 1
    assert result[0] is first
    assert result[0]["driver_cues"] == [{"text": "cue-A"}]


def test_labels_are_compacted_after_merge():
    plan = [
        _item("A", point=150.0),
        _item("B", point=155.0),
        _item(
            "C",
            start=400.0,
            end=500.0,
            point=450.0,
        ),
    ]

    result = dedupe_semantic_next_stint_plan(plan)

    assert len(result) == 2
    assert [item["plan_label"] for item in result] == ["A", "B"]
