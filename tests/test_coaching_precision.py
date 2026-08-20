from coaching_precision import (
    build_precision_evidence,
    corner_relative_anchor,
    lap_support_from_pattern,
)


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


def test_location_mismatch_withholds_only_relative_anchor():
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
    assert result["reference_lap"] == 4
    assert result["supporting_laps"] == [3]
    assert result["representative_delta_m"] == 15
    assert result["corner_relative_reference"] is None
    assert result["anchor_coherence"] == {
        "status": "WITHHELD_LOCATION_MISMATCH",
        "anchor_turn": 1,
        "allowed_turns": [2],
        "expected_label": "T2 — Esses",
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
