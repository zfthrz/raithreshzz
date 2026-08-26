from coaching_precision import (
    build_precision_evidence,
    build_track_reference_rows,
    corner_relative_anchor,
    lap_support_from_pattern,
    render_track_reference_section,
    build_p10_plan_presentation,
    build_p11_plan_focus,
)

import copy


PROFILE = {
    "turns": [
        {"turn": 1, "name": "Hairpin", "start_m": 4620.0, "apex_m": 4680.0, "end_m": 4740.0},
        {"turn": 2, "name": "Esses", "start_m": 5000.0, "apex_m": 5060.0, "end_m": 5120.0},
    ]
}


def test_lap_support_is_derived_from_explicit_comparisons():
    result = lap_support_from_pattern({
        "comparisons": ["1->2", "1->3"],
        "deltas_m": [31.0, 35.0],
        "median_delta_m": 33.0,
    })
    assert result == {
        "reference_lap": 1,
        "supporting_laps": [2, 3],
        "support_count": 2,
        "observed_delta_min_m": 31.0,
        "observed_delta_max_m": 35.0,
        "representative_delta_m": 33,
    }


def test_ambiguous_reference_laps_fail_closed():
    result = lap_support_from_pattern({"comparisons": ["1->2", "4->5"]})
    assert result["reference_lap"] is None
    assert result["supporting_laps"] == [2, 5]


def test_braking_onset_uses_next_corner_entry_anchor():
    result = corner_relative_anchor(PROFILE, 4500.0, event_kind="braking_onset")
    assert result["anchor_turn"] == 1
    assert result["anchor_type"] == "turn_start"
    assert result["relative_offset_m"] == -120.0
    assert result["driver_label"] == "~120 m antes de T1 — Hairpin"


def test_throttle_onset_uses_apex_anchor():
    result = corner_relative_anchor(PROFILE, 4700.0, event_kind="throttle_onset")
    assert result["anchor_turn"] == 1
    assert result["anchor_type"] == "apex"
    assert result["relative_offset_m"] == 20.0
    assert result["driver_label"] == "~20 m después del ápice de T1 — Hairpin"


def test_precision_evidence_preserves_absolute_coordinate():
    result = build_precision_evidence(
        {
            "comparisons": ["1->2", "1->3"],
            "deltas_m": [31.0, 35.0],
            "median_delta_m": 33.0,
            "reference_onset_m": 4500.0,
        },
        PROFILE,
        event_kind="braking_onset",
        point_key="reference_onset_m",
    )
    anchor = result["corner_relative_reference"]
    assert anchor["event_distance_m"] == 4500.0
    assert anchor["driver_label"] == "~120 m antes de T1 — Hairpin"


def test_enrichment_is_additive_and_does_not_change_source_point():
    from coaching_precision import enrich_patterns_with_precision

    pattern = {
        "reference_onset_m": 4500.0,
        "comparisons": ["1->2", "1->3"],
        "deltas_m": [31.0, 35.0],
        "median_delta_m": 33.0,
    }
    original = dict(pattern)
    enrich_patterns_with_precision(
        [pattern], PROFILE, event_kind="braking_onset", point_key="reference_onset_m"
    )
    assert pattern["reference_onset_m"] == original["reference_onset_m"]
    assert pattern["precision_evidence"]["reference_lap"] == 1


def test_llamacpp_render_exposes_reference_lap_anchor_and_support():
    import llm_analysis_llamacpp as module

    lines = module._render_precision_evidence_lines({
        "precision_evidence": [{
            "reference_lap": 1,
            "supporting_laps": [2, 3],
            "observed_delta_min_m": 31.0,
            "observed_delta_max_m": 35.0,
            "representative_delta_m": 33,
            "corner_relative_reference": {
                "driver_label": "~120 m antes de T1 — Hairpin"
            },
        }]
    })
    assert lines == [
        "**Referencia del cue:** vuelta 1; punto de referencia ~120 m antes de T1 — Hairpin.",
        "**Evidencia entre vueltas:** el mismo desvío apareció en las vueltas 2 y 3; rango observado 31–35 m; valor representativo 33 m.",
    ]


def test_plan_enrichment_covers_single_pattern_with_explicit_provenance():
    from coaching_precision import enrich_plan_items_with_precision

    plan = [{
        "braking_point_patterns": [{
            "status": "SINGLE",
            "reference_onset_m": 4500.0,
            "comparisons": ["1->4"],
            "deltas_m": [-15.2],
            "median_delta_m": -15.2,
        }],
    }]
    enrich_plan_items_with_precision(plan, PROFILE)
    evidence = plan[0]["braking_point_patterns"][0]["precision_evidence"]
    assert evidence["reference_lap"] == 1
    assert evidence["supporting_laps"] == [4]
    assert evidence["support_count"] == 1
    assert evidence["representative_delta_m"] == 15
    assert evidence["corner_relative_reference"]["driver_label"] == "~120 m antes de T1 — Hairpin"


def test_single_plan_pattern_preserves_comparison_and_signed_delta():
    import llm_analysis_llamacpp as module

    pattern = module._single_fact_as_plan_pattern({
        "authorized_numeric_coaching": True,
        "coaching_magnitude_m": 15,
        "coaching_direction": "later",
        "comparison_minus_reference_m": -15.2,
        "reference_onset_m": 4500.0,
    }, "4->3")
    assert pattern["status"] == "SINGLE"
    assert pattern["comparisons"] == ["4->3"]
    assert pattern["deltas_m"] == [-15.2]
    assert pattern["median_delta_m"] == -15.2


def test_location_mismatch_reselects_only_local_authorized_anchor():
    local_profile = {
        "turns": [
            {
                "turn": 1,
                "name": "Approach",
                "start_m": 4860.0,
                "apex_m": 4910.0,
                "end_m": 5000.0,
            },
            {
                "turn": 2,
                "name": "Esses",
                "start_m": 5000.0,
                "apex_m": 5060.0,
                "end_m": 5120.0,
            },
        ]
    }
    result = build_precision_evidence(
        {
            "comparisons": ["4->3"],
            "deltas_m": [-15.2],
            "median_delta_m": -15.2,
            "reference_onset_m": 4910.0,
        },
        local_profile,
        event_kind="braking_onset",
        point_key="reference_onset_m",
        expected_location={
            "status": "RESOLVED",
            "label": "T2 — Esses",
            "overlaps": [
                {"turn": 2, "overlap_m": 40.0, "overlap_share": 0.8},
            ],
        },
    )
    anchor = result["corner_relative_reference"]
    assert anchor["event_distance_m"] == 4910.0
    assert anchor["anchor_turn"] == 2
    assert anchor["anchor_type"] == "turn_start"
    assert anchor["relative_offset_m"] == -90.0
    assert anchor["driver_label"] == "~90 m antes de T2 — Esses"
    assert result["anchor_coherence"] == {
        "status": "RESELECTED_WITHIN_LOCATION",
        "anchor_turn": 2,
        "original_anchor_turn": 1,
        "allowed_turns": [2],
        "locality": {
            "status": "LOCAL",
            "anchor_turn": 2,
            "abs_offset_m": 90.0,
            "turn_span_m": 120.0,
        },
    }


def test_location_match_keeps_relative_anchor():
    result = build_precision_evidence(
        {
            "comparisons": ["4->3"],
            "deltas_m": [-15.2],
            "median_delta_m": -15.2,
            "reference_onset_m": 4950.0,
        },
        PROFILE,
        event_kind="braking_onset",
        point_key="reference_onset_m",
        expected_location={
            "status": "RESOLVED",
            "label": "T2 — Esses",
            "overlaps": [
                {"turn": 2, "overlap_m": 40.0, "overlap_share": 0.8},
            ],
        },
    )
    assert result["corner_relative_reference"]["anchor_turn"] == 2
    assert result["anchor_coherence"] == {
        "status": "MATCHED",
        "anchor_turn": 2,
        "allowed_turns": [2],
    }
def test_track_reference_groups_consecutive_same_name_and_marks_plan():
    profile = {
        "status": "VALIDATED_MULTI_SESSION",
        "turns": [
            {"turn": 1, "name": "TGR Corner", "start_m": 700, "apex_m": 760, "end_m": 820},
            {"turn": 2, "name": "Turn 2", "start_m": 830, "apex_m": 900, "end_m": 1000},
            {"turn": 3, "name": "Coca-Cola Corner", "start_m": 1200, "apex_m": 1280, "end_m": 1380},
            {"turn": 4, "name": "100R", "start_m": 1500, "apex_m": 1620, "end_m": 1750},
            {"turn": 5, "name": "100R", "start_m": 1750, "apex_m": 1850, "end_m": 1950},
        ],
    }
    plan = [
        {"track_location": {
            "status": "RESOLVED",
            "label": "T1 — TGR Corner",
            "overlaps": [{"turn": 1, "overlap_m": 40.0, "overlap_share": 0.8}],
        }},
        {"track_location": {
            "status": "RESOLVED",
            "label": "T3 — Coca-Cola Corner",
            "overlaps": [{"turn": 3, "overlap_m": 30.0, "overlap_share": 0.6}],
        }},
        {"track_location": {
            "status": "RESOLVED",
            "label": "T4–T5 — 100R",
            "overlaps": [
                {"turn": 4, "overlap_m": 50.0, "overlap_share": 0.7},
                {"turn": 5, "overlap_m": 45.0, "overlap_share": 0.6},
            ],
        }},
    ]

    rows = build_track_reference_rows(profile, plan)
    assert rows == [
        {"start_turn": 1, "end_turn": 1, "name": "TGR Corner", "plan_zones": ["ZONA A"]},
        {"start_turn": 2, "end_turn": 2, "name": "Turn 2", "plan_zones": []},
        {"start_turn": 3, "end_turn": 3, "name": "Coca-Cola Corner", "plan_zones": ["ZONA B"]},
        {"start_turn": 4, "end_turn": 5, "name": "100R", "plan_zones": ["ZONA C"]},
    ]

    rendered = render_track_reference_section(profile, plan)
    assert "- T1 — TGR Corner ← ZONA A" in rendered
    assert "- T4–T5 — 100R ← ZONA C" in rendered


def test_track_reference_fails_closed_without_validated_profile():
    profile = {
        "status": "SHADOW_ONLY",
        "turns": [
            {"turn": 1, "name": "Hairpin", "start_m": 0, "apex_m": 50, "end_m": 100},
        ],
    }
    assert build_track_reference_rows(profile) == []
    assert render_track_reference_section(profile) == ""
def test_track_reference_prefers_explicit_label_turns_over_overlap_spill():
    profile = {
        "status": "VALIDATED_MULTI_SESSION",
        "turns": [
            {"turn": 11, "name": "Dunlop", "start_m": 2850, "apex_m": 2910, "end_m": 3000},
            {"turn": 12, "name": "Dunlop", "start_m": 3000, "apex_m": 3060, "end_m": 3120},
            {"turn": 13, "name": "13th Corner", "start_m": 3120, "apex_m": 3180, "end_m": 3240},
        ],
    }
    plan = [{
        "track_location": {
            "status": "RESOLVED",
            "label": "T12 — Dunlop",
            "overlaps": [
                {"turn": 12, "overlap_m": 60.0, "overlap_share": 0.75},
                {"turn": 13, "overlap_m": 20.0, "overlap_share": 0.25},
            ],
        },
    }]

    rows = build_track_reference_rows(profile, plan)
    assert rows == [
        {"start_turn": 11, "end_turn": 11, "name": "Dunlop", "plan_zones": []},
        {"start_turn": 12, "end_turn": 12, "name": "Dunlop", "plan_zones": ["ZONA A"]},
        {"start_turn": 13, "end_turn": 13, "name": "13th Corner", "plan_zones": []},
    ]


def test_track_reference_does_not_group_same_name_with_different_zone_marks():
    profile = {
        "status": "VALIDATED_MULTI_SESSION",
        "turns": [
            {"turn": 11, "name": "Dunlop", "start_m": 2850, "apex_m": 2910, "end_m": 3000},
            {"turn": 12, "name": "Dunlop", "start_m": 3000, "apex_m": 3060, "end_m": 3120},
        ],
    }
    plan = [{
        "track_location": {
            "status": "RESOLVED",
            "label": "T12 — Dunlop",
            "overlaps": [
                {"turn": 12, "overlap_m": 60.0, "overlap_share": 1.0},
            ],
        },
    }]

    rendered = render_track_reference_section(profile, plan)
    assert "- T11 — Dunlop" in rendered
    assert "- T12 — Dunlop ← ZONA A" in rendered
    assert "T11–T12" not in rendered
def test_constrained_anchor_fails_closed_when_allowed_turn_missing_from_profile():
    result = build_precision_evidence(
        {
            "comparisons": ["4->3"],
            "deltas_m": [-15.2],
            "median_delta_m": -15.2,
            "reference_onset_m": 4500.0,
        },
        PROFILE,
        event_kind="braking_onset",
        point_key="reference_onset_m",
        expected_location={
            "status": "RESOLVED",
            "label": "T9 — Missing",
            "overlaps": [
                {"turn": 9, "overlap_m": 40.0, "overlap_share": 0.8},
            ],
        },
    )
    assert result["corner_relative_reference"] is None
    assert result["anchor_coherence"] == {
        "status": "WITHHELD_LOCATION_MISMATCH",
        "anchor_turn": 1,
        "allowed_turns": [9],
        "expected_label": "T9 — Missing",
    }


def test_nonlocal_constrained_anchor_is_withheld():
    result = build_precision_evidence(
        {
            "comparisons": ["4->3"],
            "deltas_m": [-15.2],
            "median_delta_m": -15.2,
            "reference_onset_m": 4500.0,
        },
        PROFILE,
        event_kind="braking_onset",
        point_key="reference_onset_m",
        expected_location={
            "status": "RESOLVED",
            "label": "T2 — Esses",
            "overlaps": [
                {"turn": 2, "overlap_m": 40.0, "overlap_share": 0.8},
            ],
        },
    )
    assert result["corner_relative_reference"] is None
    assert result["anchor_coherence"] == {
        "status": "WITHHELD_NONLOCAL_RESELECTION",
        "anchor_turn": 1,
        "candidate_anchor_turn": 2,
        "allowed_turns": [2],
        "locality": {
            "status": "NONLOCAL",
            "anchor_turn": 2,
            "abs_offset_m": 500.0,
            "turn_span_m": 120.0,
        },
    }
def test_locality_guard_preserves_absolute_coordinate_when_reselection_is_valid():
    local_profile = {
        "turns": [
            {
                "turn": 1,
                "name": "Approach",
                "start_m": 4860.0,
                "apex_m": 4910.0,
                "end_m": 5000.0,
            },
            {
                "turn": 2,
                "name": "Esses",
                "start_m": 5000.0,
                "apex_m": 5060.0,
                "end_m": 5120.0,
            },
        ]
    }
    result = build_precision_evidence(
        {
            "comparisons": ["4->3"],
            "deltas_m": [-15.2],
            "median_delta_m": -15.2,
            "reference_onset_m": 4910.0,
        },
        local_profile,
        event_kind="braking_onset",
        point_key="reference_onset_m",
        expected_location={
            "status": "RESOLVED",
            "label": "T2 — Esses",
            "overlaps": [
                {"turn": 2, "overlap_m": 40.0, "overlap_share": 0.8},
            ],
        },
    )
    assert result["corner_relative_reference"]["event_distance_m"] == 4910.0


def test_brake_release_prefers_exit_when_closer_than_apex():
    profile = {"turns": [{"turn": 1, "name": "Hairpin", "start_m": 1000.0, "apex_m": 1060.0, "end_m": 1120.0}]}
    r = corner_relative_anchor(profile, 1108.0, event_kind="brake_release")
    assert r["event_distance_m"] == 1108.0
    assert r["anchor_type"] == "turn_end"
    assert r["relative_offset_m"] == -12.0
    assert r["relative_magnitude_m"] == 12


def test_throttle_onset_prefers_exit_when_closer_than_apex():
    profile = {"turns": [{"turn": 1, "name": "Hairpin", "start_m": 1000.0, "apex_m": 1060.0, "end_m": 1120.0}]}
    r = corner_relative_anchor(profile, 1110.0, event_kind="throttle_onset")
    assert r["anchor_type"] == "turn_end"
    assert r["relative_offset_m"] == -10.0


def test_throttle_release_prefers_entry_when_closer_than_apex():
    profile = {"turns": [{"turn": 1, "name": "Hairpin", "start_m": 1000.0, "apex_m": 1080.0, "end_m": 1160.0}]}
    r = corner_relative_anchor(profile, 1015.0, event_kind="throttle_release")
    assert r["anchor_type"] == "turn_start"
    assert r["relative_offset_m"] == 15.0


def test_braking_onset_remains_entry_only_even_if_exit_is_closer():
    profile = {"turns": [{"turn": 1, "name": "Hairpin", "start_m": 1000.0, "apex_m": 1060.0, "end_m": 1120.0}]}
    r = corner_relative_anchor(profile, 1110.0, event_kind="braking_onset")
    assert r["anchor_type"] == "turn_start"


def test_p6_changes_label_anchor_not_absolute_physical_point():
    profile = {"turns": [{"turn": 1, "name": "Hairpin", "start_m": 1000.0, "apex_m": 1060.0, "end_m": 1120.0}]}
    r = corner_relative_anchor(profile, 1108.0, event_kind="throttle_onset")
    assert r["event_distance_m"] == 1108.0
    assert r["anchor_type"] == "turn_end"
    assert r["relative_offset_m"] == -12.0



def _p7_pattern(point, kind, magnitude=15, direction="later"):
    key = {
        "braking_onset": "reference_onset_m",
        "brake_release": "reference_release_m",
        "throttle_onset": "reference_onset_m",
        "throttle_release": "reference_release_m",
    }[kind]
    return {
        "status": "REPEATED",
        key: point,
        "coaching_magnitude_m": magnitude,
        "coaching_direction": direction,
        "comparisons": ["1->2", "1->3"],
        "deltas_m": [float(magnitude), float(magnitude)],
        "median_delta_m": float(magnitude),
    }


def test_p7_builds_ordered_additive_coaching_sequence():
    from coaching_precision import (
        enrich_plan_items_with_precision,
        enrich_plan_items_with_coaching_sequence,
    )
    plan = [{
        "braking_point_patterns": [_p7_pattern(4500.0, "braking_onset", 15)],
        "brake_release_patterns": [_p7_pattern(4690.0, "brake_release", 20)],
        "throttle_onset_patterns": [_p7_pattern(4710.0, "throttle_onset", 25)],
    }]
    enrich_plan_items_with_precision(plan, PROFILE)
    enrich_plan_items_with_coaching_sequence(plan)
    seq = plan[0]["coaching_sequence"]
    assert seq["status"] == "COMBINED"
    assert seq["event_count"] == 3
    assert [e["event_kind"] for e in seq["events"]] == [
        "braking_onset", "brake_release", "throttle_onset"
    ]
    assert [e["event_distance_m"] for e in seq["events"]] == [
        4500.0, 4690.0, 4710.0
    ]


def test_p7_does_not_create_sequence_for_single_physical_cue():
    from coaching_precision import (
        enrich_plan_items_with_precision,
        enrich_plan_items_with_coaching_sequence,
    )
    plan = [{
        "braking_point_patterns": [_p7_pattern(4500.0, "braking_onset", 15)]
    }]
    enrich_plan_items_with_precision(plan, PROFILE)
    enrich_plan_items_with_coaching_sequence(plan)
    assert "coaching_sequence" not in plan[0]


def test_p7_fails_closed_on_invalid_same_channel_order():
    from coaching_precision import (
        enrich_plan_items_with_precision,
        enrich_plan_items_with_coaching_sequence,
    )
    plan = [{
        "braking_point_patterns": [_p7_pattern(4700.0, "braking_onset", 15)],
        "brake_release_patterns": [_p7_pattern(4500.0, "brake_release", 20)],
    }]
    enrich_plan_items_with_precision(plan, PROFILE)
    enrich_plan_items_with_coaching_sequence(plan)
    assert "coaching_sequence" not in plan[0]


def test_p7_driver_cues_consolidate_brake_and_throttle_spatial_points():
    import llm_analysis as module
    from coaching_precision import (
        enrich_plan_items_with_precision,
        enrich_plan_items_with_coaching_sequence,
    )
    item = {
        "comparison_count": 2,
        "braking_point_patterns": [_p7_pattern(4500.0, "braking_onset", 15)],
        "brake_release_patterns": [_p7_pattern(4690.0, "brake_release", 20)],
        "throttle_onset_patterns": [_p7_pattern(4710.0, "throttle_onset", 25)],
    }
    plan = [item]
    enrich_plan_items_with_precision(plan, PROFILE)
    enrich_plan_items_with_coaching_sequence(plan)
    cues = module.build_driver_cues_for_plan_item(item, max_cues=2)
    assert len(cues) == 1
    assert cues[0]["kind"] == "combined_spatial_sequence"
    assert cues[0]["source"] == "deterministic_coaching_sequence"
    assert cues[0]["coaching_sequence"]["event_count"] == 3
    assert len(cues[0]["precision_evidence"]) == 3



def test_p7_active_backends_have_sequence_integration_parity():
    from pathlib import Path

    for filename in (
        "llm_analysis.py",
        "llm_analysis_deepseek.py",
        "llm_analysis_llamacpp.py",
    ):
        source = Path(filename).read_text(encoding="utf-8")
        assert "enrich_plan_items_with_coaching_sequence" in source, filename
        assert "enrich_plan_items_with_coaching_sequence(next_stint_plan)" in source, filename
        shared_source = Path("deterministic_coaching.py").read_text(encoding="utf-8")
        assert '"kind": "combined_spatial_sequence"' in shared_source, filename
        assert '"source": "deterministic_coaching_sequence"' in shared_source, filename


# ============================================================
# H5.4 P8 — DETERMINISTIC DRIVER-FACING CUE PRIORITY
# ============================================================

from coaching_precision import (
    enrich_cues_with_deterministic_priority,
    _cue_priority_rank,
    _remove_suppressed_spatial_cues,
    _prioritize_cues,
    _deduplicate_coaching_cues,
)


def _cue(kind, channel=None, text="", event_distance_m=None, **extra):
    cue = {"kind": kind, "channel": channel, "text": text, **extra}
    if event_distance_m is not None:
        cue["event_distance_m"] = event_distance_m
    return cue


def test_p8_combined_spatial_sequence_gets_slot_1():
    """Test A: combined_spatial_sequence must occupy cue slot 1."""
    cues = [
        _cue("spatial_points", "brake", "frená 15 m más tarde", 4500.0),
        _cue("combined_spatial_sequence", "brake+throttle", "frená 15 m más tarde; después soltá el freno 20 m más tarde", 4490.0),
        _cue("validated_llm_steering", "steering_magnitude", "reducí la magnitud del volante", 9000.0),
    ]
    result = enrich_cues_with_deterministic_priority(cues)
    assert result[0]["kind"] == "combined_spatial_sequence"
    assert result[0]["text"] != ""


def test_p8_component_spatial_cue_not_duplicated_after_combined_sequence():
    """Test B: component spatial cue is not duplicated after combined sequence."""
    cues = [
        _cue("combined_spatial_sequence", "brake+throttle", "frená 15 m más tarde; después soltá el freno 20 m más tarde", 4490.0),
        _cue("spatial_points", "brake", "frená 15 m más tarde", 4500.0),
        _cue("validated_llm_steering", "steering_magnitude", "reducí la magnitud del volante", 9000.0),
    ]
    result = enrich_cues_with_deterministic_priority(cues)
    kinds = [cue["kind"] for cue in result]
    assert "spatial_points" not in kinds


def test_p8_two_independent_physical_cues_ordered_by_event_distance_m():
    """Test C: two independent spatial cues are ordered by event_distance_m."""
    cues = [
        _cue("spatial_points", "throttle", "soltá el acelerador 10 m más tarde", 4700.0),
        _cue("spatial_points", "brake", "frená 15 m más tarde", 4500.0),
        _cue("validated_llm_steering", "steering_magnitude", "reducí la magnitud del volante", 9000.0),
    ]
    result = enrich_cues_with_deterministic_priority(cues)
    assert result[0]["kind"] == "spatial_points"
    assert result[0]["channel"] == "brake"
    assert result[0]["event_distance_m"] == 4500.0
    assert result[1]["kind"] == "spatial_points"
    assert result[1]["channel"] == "throttle"
    assert result[1]["event_distance_m"] == 4700.0


def test_p8_physical_cue_beats_reference_profile():
    """Test D: physical cue beats reference_action_profile by priority rank."""
    cues = [
        _cue("reference_action_profile", "brake", "replicá la secuencia de freno de la referencia: consistente", 9000.0),
        _cue("spatial_points", "brake", "frená 15 m más tarde", 4500.0),
        _cue("validated_llm_steering", "steering_magnitude", "reducí la magnitud del volante", 9500.0),
    ]
    result = enrich_cues_with_deterministic_priority(cues)
    assert result[0]["kind"] == "spatial_points"
    assert result[1]["kind"] == "reference_action_profile"


def test_p8_reference_profile_can_fill_slot_2_when_distinct():
    """Test E: reference_profile can fill slot 2 when distinct from spatial cue."""
    cues = [
        _cue("spatial_points", "brake", "frená 15 m más tarde", 4500.0),
        _cue("reference_action_profile", "throttle", "replicá la secuencia de acelerador de la referencia: consistente", 9000.0),
    ]
    result = enrich_cues_with_deterministic_priority(cues)
    kinds = [cue["kind"] for cue in result]
    assert "spatial_points" in kinds
    assert "reference_action_profile" in kinds


def test_p8_steering_cannot_displace_physical_brake_throttle_cue():
    """Test F: steering must never displace authorized brake/throttle physical evidence."""
    cues = [
        _cue("spatial_points", "brake", "frená 15 m más tarde", 4500.0),
        _cue("validated_llm_steering", "steering_magnitude", "reducí la magnitud del volante", 9000.0),
    ]
    result = enrich_cues_with_deterministic_priority(cues)
    kinds = [cue["kind"] for cue in result]
    spatial_idx = next(i for i, c in enumerate(result) if c["kind"] == "spatial_points")
    steering_idx = next(i for i, c in enumerate(result) if c["kind"] == "validated_llm_steering")
    assert spatial_idx < steering_idx


def test_p8_single_cue_legacy_behavior_unchanged():
    """Test G: single-cue legacy behavior must remain unchanged."""
    cues = [
        _cue("validated_llm_steering", "steering_magnitude", "reducí la magnitud del volante", 9000.0),
    ]
    result = enrich_cues_with_deterministic_priority(cues)
    assert len(result) == 1
    assert result[0]["kind"] == "validated_llm_steering"


def test_p8_backend_parity():
    """Test H: all active backends must call enrich_cues_with_deterministic_priority."""
    from pathlib import Path
    import re

    for filename in (
        "llm_analysis.py",
        "llm_analysis_deepseek.py",
        "llm_analysis_ingenierov3.py",
        "llm_analysis_llamacpp.py",
    ):
        source = Path(filename).read_text(encoding="utf-8")
        assert "enrich_cues_with_deterministic_priority" in source, filename
        # Accept both one-line and multi-line call patterns.
        one_line = (
            'enrich_cues_with_deterministic_priority(item["driver_cues"])'
        )
        multi_line = (
            r'enrich_cues_with_deterministic_priority\(\s*item\["driver_cues"\]'
        )
        assert (
            one_line in source
            or
            re.search(multi_line, source) is not None
        ), filename


# ============================================================
# H5.4 P9 - DETERMINISTIC CROSS-ZONE DRIVER-PLAN DIVERSITY
# ============================================================

from coaching_precision import (
    _derive_action_family,
    _derive_primary_action_family,
    derive_p9_presentation_metadata,
    build_p9_presentation_order,
)


def _p9_item(driver_cues=None):
    return {"driver_cues": driver_cues or []}


def _p9_cue(kind, channel="brake", text="test", **extra):
    cue = {"kind": kind, "channel": channel, "text": text, **extra}
    return cue


def test_p9_repeated_throttle_plus_brake_diversity():
    """Test A: repeated throttle + brake diversity."""
    plan = [
        _p9_item([_p9_cue("spatial_points", "throttle", "soltá el acelerador")]),  # THROTTLE_TIMING
        _p9_item([_p9_cue("spatial_points", "throttle", "soltá el acelerador")]),  # THROTTLE_TIMING
        _p9_item([_p9_cue("spatial_points", "brake", "frená")]),  # BRAKE_TIMING
    ]
    result = build_p9_presentation_order(plan)
    families = [item["_p9_presentation_metadata"]["primary_action_family"] for item in result]
    # First occurrence of each family preserved, then remaining THROTTLE_TIMING.
    assert "THROTTLE_TIMING" in families[:2]
    assert "BRAKE_TIMING" in families[:2]
    assert families.count("THROTTLE_TIMING") == 2
    assert families.count("BRAKE_TIMING") == 1


def test_p9_all_unique_unchanged():
    """Test B: all unique families — order unchanged."""
    plan = [
        _p9_item([_p9_cue("spatial_points", "brake")]),
        _p9_item([_p9_cue("spatial_points", "throttle")]),
        _p9_item([_p9_cue("validated_llm_steering", "steering_magnitude")]),
    ]
    result = build_p9_presentation_order(plan)
    families = [item["_p9_presentation_metadata"]["primary_action_family"] for item in result]
    assert families == ["BRAKE_TIMING", "THROTTLE_TIMING", "STEERING"]
    # Original order preserved for unique families (check by original index).
    assert result[0]["_p9_original_index"] == 0
    assert result[1]["_p9_original_index"] == 1
    assert result[2]["_p9_original_index"] == 2


def test_p9_all_same_unchanged():
    """Test C: all same family — order unchanged, all marked repeated except first."""
    plan = [
        _p9_item([_p9_cue("spatial_points", "throttle")]),
        _p9_item([_p9_cue("spatial_points", "throttle")]),
        _p9_item([_p9_cue("spatial_points", "throttle")]),
    ]
    result = build_p9_presentation_order(plan)
    families = [item["_p9_presentation_metadata"]["primary_action_family"] for item in result]
    assert families == ["THROTTLE_TIMING", "THROTTLE_TIMING", "THROTTLE_TIMING"]
    assert result[0]["_p9_presentation_metadata"]["redundancy_status"] == "FIRST_OCCURRENCE"
    assert result[1]["_p9_presentation_metadata"]["redundancy_status"] == "REPEATED_FAMILY"
    assert result[2]["_p9_presentation_metadata"]["redundancy_status"] == "REPEATED_FAMILY"


def test_p9_combined_sequence_classification():
    """Test D: combined sequence classified as BRAKE_THROTTLE_SEQUENCE."""
    cues = [_p9_cue("combined_spatial_sequence", "brake+throttle")]
    assert _derive_action_family(cues[0]) == "BRAKE_THROTTLE_SEQUENCE"
    assert _derive_primary_action_family([cues[0]]) == "BRAKE_THROTTLE_SEQUENCE"


def test_p9_profile_vs_timing_classification():
    """Test E: profile vs timing classification."""
    assert _derive_action_family(_p9_cue("spatial_points", "brake")) == "BRAKE_TIMING"
    assert _derive_action_family(_p9_cue("reference_action_profile", "brake")) == "BRAKE_PROFILE"
    assert _derive_action_family(_p9_cue("spatial_points", "throttle")) == "THROTTLE_TIMING"
    assert _derive_action_family(_p9_cue("reference_action_profile", "throttle")) == "THROTTLE_PROFILE"


def test_p9_no_cue_fail_closed():
    """Test F: no-authorized-cue fails closed."""
    assert _derive_primary_action_family([]) == "OTHER_AUTHORIZED"
    assert _derive_primary_action_family([{"kind": "unknown_kind"}]) == "OTHER_AUTHORIZED"
    metadata = derive_p9_presentation_metadata([])
    assert metadata["primary_action_family"] == "OTHER_AUTHORIZED"
    assert metadata["has_authorized_cue"] is False


def test_p9_speed_cannot_create_family():
    """Test G: speed never creates an action family."""
    # Speed cues should not appear in P8 driver_cues, but if they did,
    # they should map to OTHER_AUTHORIZED.
    assert _derive_action_family({"kind": "speed", "channel": "speed"}) == "OTHER_AUTHORIZED"
    assert _derive_action_family({}) == "OTHER_AUTHORIZED"


def test_p9_h52_ranks_unchanged():
    """Test H: H5.2 ranks are preserved."""
    plan = [
        {"driver_cues": [_p9_cue("spatial_points", "brake")], "plan_rank": 1},
        {"driver_cues": [_p9_cue("spatial_points", "throttle")], "plan_rank": 2},
        {"driver_cues": [_p9_cue("validated_llm_steering", "steering_magnitude")], "plan_rank": 3},
    ]
    result = build_p9_presentation_order(plan)
    for i, item in enumerate(result):
        assert "plan_rank" in item
        assert item.get("plan_rank") == i + 1


def test_p9_deterministic_repeated_result():
    """Test I: result is deterministic across repeated calls."""
    plan = [
        _p9_item([_p9_cue("spatial_points", "throttle")]),
        _p9_item([_p9_cue("spatial_points", "throttle")]),
        _p9_item([_p9_cue("spatial_points", "brake")]),
    ]
    result1 = build_p9_presentation_order(plan)
    result2 = build_p9_presentation_order(plan)
    families1 = [item["_p9_presentation_metadata"]["primary_action_family"] for item in result1]
    families2 = [item["_p9_presentation_metadata"]["primary_action_family"] for item in result2]
    assert families1 == families2


def test_p9_backend_parity():
    """Test J: all active backends apply P9 to the local plan under construction."""
    from pathlib import Path
    import re

    for filename in (
        "llm_analysis.py",
        "llm_analysis_deepseek.py",
        "llm_analysis_ingenierov3.py",
        "llm_analysis_llamacpp.py",
    ):
        source = Path(filename).read_text(encoding="utf-8")
        assert "enrich_plan_with_p9_presentation_metadata" in source, filename
        build_facts = source.split(
            "def build_session_coaching_facts(",
            1,
        )[1].split("\ndef ", 1)[0]
        assert (
            "next_stint_plan = enrich_plan_with_p9_presentation_metadata("
            in build_facts
        ), filename
        assert 'session_coaching_facts["next_stint_plan"]' not in build_facts, filename


def test_p9_no_cue_items_dont_displace_authorized():
    """Test: items with no authorized cue (OTHER_AUTHORIZED) stay at end."""
    plan = [
        _p9_item([_p9_cue("spatial_points", "brake")]),
        _p9_item([]),
        _p9_item([_p9_cue("spatial_points", "throttle")]),
    ]
    result = build_p9_presentation_order(plan)
    # FIRST_OCCURRENCE items should come first.
    statuses = [item["_p9_presentation_metadata"]["redundancy_status"] for item in result]
    # OTHER_AUTHORIZED items should not displace authorized items.
    first_authored_idx = next(i for i, item in enumerate(result) if item["_p9_presentation_metadata"]["primary_action_family"] != "OTHER_AUTHORIZED")
    last_authored_idx = next(i for i in range(len(result) - 1, -1, -1) if result[i]["_p9_presentation_metadata"]["primary_action_family"] != "OTHER_AUTHORIZED")
    assert first_authored_idx <= last_authored_idx


# ============================================================
# H5.4 P10 - DETERMINISTIC DRIVER-FACING PLAN PROJECTION
# ============================================================

from coaching_precision import build_p10_plan_presentation


def _p10_plan_item(presentation_rank=None):
    return {"_p9_presentation_metadata": {"presentation_rank": presentation_rank} if presentation_rank is not None else {}}


def test_p10_ranks_reorder_presentation_but_original_unchanged():
    """Test A: ranks [0,2,1] reorder presentation but original unchanged."""
    plan = [_p10_plan_item(r) for r in [0, 2, 1]]
    result = build_p10_plan_presentation(plan)
    presentation = result["presentation"]
    # Presentation should be reordered: 0, 2, 1 -> indices should be 0, 2, 1
    assert presentation[0] is not plan[0]  # deepcopy
    assert presentation[1] is not plan[2]  # rank 2 goes to position 1
    assert presentation[2] is not plan[1]  # rank 1 goes to position 2
    # Original plan is unchanged
    assert plan[0] == _p10_plan_item(0)
    assert plan[1] == _p10_plan_item(2)
    assert plan[2] == _p10_plan_item(1)


def test_p10_already_correct_order_reordered_false():
    """Test B: already-correct order => reordered=false."""
    plan = [_p10_plan_item(r) for r in [0, 1, 2]]
    result = build_p10_plan_presentation(plan)
    assert result["_p10_presentation"]["reordered"] is False
    assert result["_p10_presentation"]["status"] == "ACTIVE"


def test_p10_missing_p9_metadata_fallback():
    """Test C: missing P9 metadata => fallback."""
    plan = [_p10_plan_item(None), _p10_plan_item(1), _p10_plan_item(2)]
    result = build_p10_plan_presentation(plan)
    assert result["_p10_presentation"]["status"] == "FALLBACK_ORIGINAL_ORDER"
    assert result["_p10_presentation"]["reason"] == "INVALID_PRESENTATION_RANK"


def test_p10_duplicate_rank_fallback():
    """Test D: duplicate rank => fallback."""
    plan = [_p10_plan_item(r) for r in [0, 1, 1]]
    result = build_p10_plan_presentation(plan)
    assert result["_p10_presentation"]["status"] == "FALLBACK_ORIGINAL_ORDER"
    assert result["_p10_presentation"]["reason"] == "DUPLICATE_PRESENTATION_RANK"


def test_p10_invalid_non_contiguous_rank_fallback():
    """Test E: invalid/non-contiguous rank => fallback."""
    plan = [_p10_plan_item(r) for r in [0, 2, 3]]  # missing rank 1
    result = build_p10_plan_presentation(plan)
    assert result["_p10_presentation"]["status"] == "FALLBACK_ORIGINAL_ORDER"
    assert result["_p10_presentation"]["reason"] == "NON_CONTIGUOUS_PRESENTATION_RANK"


def test_p10_input_not_mutated():
    """Test F: input list/dicts are not mutated."""
    import copy
    original_plan = [_p10_plan_item(r) for r in [0, 1, 2]]
    plan_copy = copy.deepcopy(original_plan)
    result = build_p10_plan_presentation(original_plan)
    assert original_plan == plan_copy  # input unchanged


def test_p10_deterministic_repeated_result():
    """Test G: repeated calls deterministic."""
    plan = [_p10_plan_item(r) for r in [0, 2, 1]]
    result1 = build_p10_plan_presentation(plan)
    result2 = build_p10_plan_presentation(plan)
    assert result1["presentation"] == result2["presentation"]
    assert result1["_p10_presentation"] == result2["_p10_presentation"]


def test_p10_p8_p9_fields_preserved():
    """Test H: P8/P9 fields preserved."""
    plan = [
        {
            "_p9_presentation_metadata": {"presentation_rank": 0},
            "driver_cues": [{"kind": "spatial_points", "channel": "brake", "text": "test"}],
            "actionable_cue_count": 1,
        },
        {
            "_p9_presentation_metadata": {"presentation_rank": 1},
            "driver_cues": [{"kind": "spatial_points", "channel": "throttle", "text": "test"}],
            "actionable_cue_count": 1,
        },
    ]
    result = build_p10_plan_presentation(plan)
    assert result["presentation"][0]["_p9_presentation_metadata"]["presentation_rank"] == 0
    assert result["presentation"][0]["driver_cues"] == [{"kind": "spatial_points", "channel": "brake", "text": "test"}]
    assert result["presentation"][0]["actionable_cue_count"] == 1


# ============================================================
# H5.4 P11 - DETERMINISTIC DRIVER FOCUS SLOTS
# ============================================================

def _p11_plan_item(presentation_rank=None, driver_cues=None):
    item = {"_p9_presentation_metadata": {}}
    if presentation_rank is not None:
        item["_p9_presentation_metadata"]["presentation_rank"] = presentation_rank
    if driver_cues is not None:
        item["driver_cues"] = driver_cues
    return item


def test_p11_first_two_items():
    """Test A: 3-item presentation -> first 2."""
    plan = [_p11_plan_item(r) for r in [0, 1, 2]]
    presentation = [copy.deepcopy(item) for item in plan]
    p10_result = {"presentation": presentation, "_p10_presentation": {"status": "ACTIVE"}}
    result = build_p11_plan_focus(plan, p10_result)
    assert result["status"] == "ACTIVE"
    assert result["focus_count"] == 2
    assert len(result["items"]) == 2
    assert result["items"][0] is not plan[0]  # deepcopy
    assert result["items"][1] is not plan[1]
    assert result["items"][0] == plan[0]
    assert result["items"][1] == plan[1]


def test_p11_two_items():
    """Test B: 2 items -> both."""
    plan = [_p11_plan_item(r) for r in [0, 1]]
    presentation = [copy.deepcopy(item) for item in plan]
    p10_result = {"presentation": presentation, "_p10_presentation": {"status": "ACTIVE"}}
    result = build_p11_plan_focus(plan, p10_result)
    assert result["status"] == "ACTIVE"
    assert result["focus_count"] == 2
    assert len(result["items"]) == 2


def test_p11_one_item():
    """Test C: 1 item -> one."""
    plan = [_p11_plan_item(r) for r in [0]]
    presentation = [copy.deepcopy(item) for item in plan]
    p10_result = {"presentation": presentation, "_p10_presentation": {"status": "ACTIVE"}}
    result = build_p11_plan_focus(plan, p10_result)
    assert result["status"] == "ACTIVE"
    assert result["focus_count"] == 1
    assert len(result["items"]) == 1


def test_p11_empty_presentation():
    """Test D: empty presentation -> deterministic documented behavior."""
    plan = []
    presentation = []
    p10_result = {"presentation": presentation, "_p10_presentation": {"status": "ACTIVE"}}
    result = build_p11_plan_focus(plan, p10_result)
    assert result["status"] == "ACTIVE"
    assert result["focus_count"] == 0
    assert result["items"] == []


def test_p11_fallback_status_unavailable():
    """Test E: invalid/fallback P10 -> UNAVAILABLE."""
    plan = [_p11_plan_item(r) for r in [0, 1]]
    p10_result = {
        "presentation": plan,
        "_p10_presentation": {"status": "FALLBACK_ORIGINAL_ORDER"},
    }
    result = build_p11_plan_focus(plan, p10_result)
    assert result["status"] == "UNAVAILABLE"
    assert result["focus_count"] == 0
    assert result["items"] == []


def test_p11_invalid_presentation_unavailable():
    """Test E: invalid P10 presentation -> UNAVAILABLE."""
    plan = [_p11_plan_item(r) for r in [0, 1]]
    p10_result = {"presentation": "not_a_list", "_p10_presentation": {"status": "ACTIVE"}}
    result = build_p11_plan_focus(plan, p10_result)
    assert result["status"] == "UNAVAILABLE"
    assert result["focus_count"] == 0
    assert result["items"] == []


def test_p11_not_mutated():
    """Test F: original next_stint_plan not mutated."""
    import copy
    plan = [_p11_plan_item(r) for r in [0, 1, 2]]
    plan_copy = copy.deepcopy(plan)
    presentation = [copy.deepcopy(item) for item in plan]
    p10_result = {"presentation": presentation, "_p10_presentation": {"status": "ACTIVE"}}
    build_p11_plan_focus(plan, p10_result)
    assert plan == plan_copy


def test_p10_not_mutated():
    """Test G: P10 presentation not mutated."""
    import copy
    plan = [_p11_plan_item(r) for r in [0, 1]]
    presentation = [copy.deepcopy(item) for item in plan]
    p10_result = {"presentation": presentation, "_p10_presentation": {"status": "ACTIVE"}}
    p10_copy = copy.deepcopy(p10_result)
    build_p11_plan_focus(plan, p10_result)
    assert p10_result == p10_copy


def test_p11_p8_p9_metadata_preserved():
    """Test H: P8/P9 metadata preserved in focus items."""
    plan = [
        {
            "_p9_presentation_metadata": {"presentation_rank": 0},
            "driver_cues": [{"kind": "spatial_points", "channel": "brake", "text": "test"}],
            "actionable_cue_count": 1,
        },
        {
            "_p9_presentation_metadata": {"presentation_rank": 1},
            "driver_cues": [{"kind": "spatial_points", "channel": "throttle", "text": "test"}],
            "actionable_cue_count": 1,
        },
    ]
    presentation = [copy.deepcopy(item) for item in plan]
    p10_result = {"presentation": presentation, "_p10_presentation": {"status": "ACTIVE"}}
    result = build_p11_plan_focus(plan, p10_result)
    assert result["items"][0]["_p9_presentation_metadata"]["presentation_rank"] == 0
    assert result["items"][0]["driver_cues"] == [{"kind": "spatial_points", "channel": "brake", "text": "test"}]
    assert result["items"][0]["actionable_cue_count"] == 1


def test_p11_deterministic():
    """Test I: repeated calls deterministic."""
    plan = [_p11_plan_item(r) for r in [0, 1, 2]]
    presentation = [copy.deepcopy(item) for item in plan]
    p10_result = {"presentation": presentation, "_p10_presentation": {"status": "ACTIVE"}}
    result1 = build_p11_plan_focus(plan, p10_result)
    result2 = build_p11_plan_focus(plan, p10_result)
    assert result1 == result2


def test_p11_speed_time_loss_not_used():
    """Test J: speed/time_loss/magnitude cannot affect focus."""
    plan = [_p11_plan_item(r) for r in [0, 1, 2]]
    plan[0]["speed_m_s"] = 100.0
    plan[0]["time_loss_s"] = 0.5
    plan[0]["magnitude"] = 0.9
    presentation = [copy.deepcopy(item) for item in plan]
    p10_result = {"presentation": presentation, "_p10_presentation": {"status": "ACTIVE"}}
    result = build_p11_plan_focus(plan, p10_result)
    # Focus items preserve the original fields but are not affected by them.
    assert result["focus_count"] == 2
    assert result["items"][0] == plan[0]


def test_p11_integration():
    """Test K: canonical backend integration."""
    plan = [
        {
            "_p9_presentation_metadata": {"presentation_rank": 0},
            "driver_cues": [{"kind": "spatial_points", "channel": "brake", "text": "test"}],
        },
        {
            "_p9_presentation_metadata": {"presentation_rank": 1},
            "driver_cues": [{"kind": "spatial_points", "channel": "throttle", "text": "test"}],
        },
        {
            "_p9_presentation_metadata": {"presentation_rank": 2},
            "driver_cues": [{"kind": "spatial_points", "channel": "steering", "text": "test"}],
        },
    ]
    presentation = [copy.deepcopy(item) for item in plan]
    p10_result = {
        "presentation": presentation,
        "_p10_presentation": {
            "status": "ACTIVE",
            "policy_version": "0.1",
            "item_count": 3,
            "reordered": False,
            "reason": "DIVERSITY_NO_CHANGE",
        },
    }
    result = build_p11_plan_focus(plan, p10_result)
    assert result["status"] == "ACTIVE"
    assert result["policy_version"] == "0.1"
    assert result["focus_count"] == 2
    assert len(result["items"]) == 2
    assert result["items"][0] == plan[0]
    assert result["items"][1] == plan[1]
    assert result["items"][0] is not plan[0]  # deepcopy
