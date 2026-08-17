from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit_session_plan_actionability import (
    STALE_RENDER_ERROR,
    _validator_error_lines,
    audit_document,
    audit_paths,
    build_audit,
    classify_cue,
)


def plan_item(channel: str = "brake") -> dict:
    if channel == "brake":
        points = {
            "braking_point_patterns": [
                {"status": "REPEATED", "comparison_count": 3}
            ],
            "brake_release_patterns": [],
            "throttle_onset_patterns": [],
            "throttle_release_patterns": [],
        }
        cue = {
            "channel": "brake",
            "kind": "spatial_points",
            "source": "authorized_brake_onset_release",
            "point_comparison_count": 3,
            "region_comparison_count": 4,
        }
    else:
        points = {
            "braking_point_patterns": [],
            "brake_release_patterns": [],
            "throttle_onset_patterns": [
                {"status": "REPEATED", "comparison_count": 2}
            ],
            "throttle_release_patterns": [],
        }
        cue = {
            "channel": "throttle",
            "kind": "spatial_points",
            "source": "authorized_throttle_onset_release",
            "point_comparison_count": 2,
            "region_comparison_count": 5,
            "reference_action_profile": {
                "steps": [
                    {"kind": "application"},
                    {"kind": "released_gap"},
                    {"kind": "application"},
                ]
            },
        }
    return {
        "plan_label": "A",
        "comparison_count": cue["region_comparison_count"],
        "track_location": {"label": "Test corner"},
        "driver_cues": [cue],
        "actionable_cue_count": 1,
        **points,
    }


def document_with_plan(items: list[dict]) -> dict:
    return {
        "metadata": {"track": "Test Track"},
        "session_coaching_facts": {
            "next_stint_plan": items,
            "session_priority_policy": {
                "version": "1.9",
                "actionability_policy_version": "1.6",
            },
        },
    }


def test_classifies_direct_point_and_point_with_sequence_without_channel_score():
    brake = plan_item("brake")
    throttle = plan_item("throttle")

    brake_audit = classify_cue(brake, brake["driver_cues"][0])
    throttle_audit = classify_cue(throttle, throttle["driver_cues"][0])

    assert brake_audit["directness_class"] == "single_physical_point"
    assert brake_audit["instruction_component_count"] == 1
    assert throttle_audit["directness_class"] == (
        "physical_point_with_reference_sequence"
    )
    assert throttle_audit["instruction_component_count"] == 4
    assert "score" not in brake_audit
    assert "score" not in throttle_audit


def test_builds_shadow_summary_from_multiple_artifacts(tmp_path: Path):
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(
        json.dumps(document_with_plan([plan_item("brake")])),
        encoding="utf-8",
    )
    second_path.write_text(
        json.dumps(document_with_plan([plan_item("throttle")])),
        encoding="utf-8",
    )

    audit = audit_paths([first_path, second_path], run_validator=False)

    assert audit["metadata"]["status"] == "SHADOW_OBSERVATIONAL_ONLY"
    assert audit["contract"]["channel_preference_authorized"] is False
    assert audit["contract"]["complexity_score_authorized"] is False
    assert audit["summary"] == {
        "artifact_count": 2,
        "zone_count": 2,
        "primary_channel_counts": {"brake": 1, "throttle": 1},
        "primary_directness_counts": {
            "physical_point_with_reference_sequence": 1,
            "single_physical_point": 1,
        },
    }


def test_audit_rejects_inconsistent_cue_count(tmp_path: Path):
    path = tmp_path / "bad.json"
    item = plan_item("brake")
    item["actionable_cue_count"] = 2
    document = document_with_plan([item])
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="actionable_cue_count no coincide"):
        audit_document(path, document)


def test_build_audit_does_not_infer_preference_from_counts():
    result = {
        "zone_count": 2,
        "zones": [
            {"primary_cue": {"channel": "brake", "directness_class": "other"}},
            {"primary_cue": {"channel": "brake", "directness_class": "other"}},
        ],
    }

    audit = build_audit([result])

    assert audit["summary"]["primary_channel_counts"] == {"brake": 2}
    assert audit["contract"]["channel_preference_authorized"] is False


def test_validator_error_parser_requires_exact_stale_render_error():
    stale = (
        "REGRESSION VALIDATION: FAIL\n"
        f"- {STALE_RENDER_ERROR}\n"
        "\nErrores: 1"
    )
    unsafe = (
        stale
        + "\n- session_coaching_facts.next_stint_plan no coincide con Python."
    )

    assert _validator_error_lines(stale) == [STALE_RENDER_ERROR]
    assert _validator_error_lines(unsafe) == [
        STALE_RENDER_ERROR,
        "session_coaching_facts.next_stint_plan no coincide con Python.",
    ]
