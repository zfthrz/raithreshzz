from __future__ import annotations

import json
from pathlib import Path

import pytest

from shadow_split_mixed_cue_plan import (
    audit_document,
    build_summary,
    compare_item,
    split_combined_cues,
)


def combined_cue() -> dict:
    return {
        "channel": "brake+throttle",
        "channels": ["brake", "throttle"],
        "kind": "combined_spatial_sequence",
        "text": "soltá el acelerador y frená más tarde",
        "source": "deterministic_coaching_sequence",
        "point_comparison_count": 2,
        "region_comparison_count": 1,
        "coaching_sequence": {
            "version": "0.1",
            "status": "COMBINED",
            "events": [
                {
                    "event_kind": "throttle_release",
                    "channel": "throttle",
                    "text": "soltá el acelerador aproximadamente 19 m más temprano",
                },
                {
                    "event_kind": "braking_onset",
                    "channel": "brake",
                    "text": "frená aproximadamente 15 m más tarde",
                },
            ],
        },
    }


def plan_item() -> dict:
    return {
        "plan_label": "A",
        "track_location": {"label": "T5 — Variante Villeneuve"},
        "comparison_count": 1,
        "braking_point_patterns": [{"status": "SINGLE", "comparison_count": 1}],
        "brake_release_patterns": [],
        "throttle_onset_patterns": [],
        "throttle_release_patterns": [{"status": "SINGLE", "comparison_count": 1}],
        "driver_cues": [combined_cue()],
    }


def document_with_plan(items: list[dict]) -> dict:
    return {
        "session_coaching_facts": {"next_stint_plan": items},
    }


def test_split_combined_cues_into_single_channel_cues():
    split = split_combined_cues([combined_cue()])

    assert len(split) == 2
    assert [cue["channel"] for cue in split] == ["throttle", "brake"]
    assert split[0]["kind"] == "spatial_points"
    assert "19 m más temprano" in split[0]["text"]
    assert "15 m más tarde" in split[1]["text"]
    assert split[0]["source"] == "deterministic_coaching_sequence_shadow_split"


def test_split_caps_at_two_cues_and_keeps_single_channel_cues():
    steering = {
        "channel": "steering_magnitude",
        "kind": "validated_llm_steering",
        "text": "replicá la secuencia de dirección",
        "source": "validated_llm_recommendation+python_direction",
    }
    split = split_combined_cues([combined_cue(), steering])

    assert len(split) == 2
    assert [cue["channel"] for cue in split] == ["throttle", "brake"]


def test_split_keeps_non_combined_cues():
    cue = {"channel": "brake", "kind": "spatial_points", "text": "frená más tarde"}
    split = split_combined_cues([cue])
    assert split == [cue]


def test_compare_item_marks_combined_and_reports_channels():
    comparison = compare_item(plan_item())

    assert comparison["had_combined_cue"] is True
    assert comparison["production_primary_channel"] == "brake+throttle"
    assert comparison["production_primary_directness"] == "combined_spatial_sequence"
    assert comparison["split_primary_channel"] == "throttle"
    assert comparison["split_primary_directness"] == "single_physical_point"
    assert comparison["production_cue_count"] == 1
    assert comparison["split_cue_count"] == 2


def test_build_summary_aggregates_counts():
    results = [
        {
            "zone_count": 1,
            "zones": [compare_item(plan_item())],
        }
    ]

    summary = build_summary(results)

    assert summary["zone_count"] == 1
    assert summary["combined_cue_zones"] == 1
    assert summary["production_primary_channel_counts"] == {"brake+throttle": 1}
    assert summary["split_primary_channel_counts"] == {"throttle": 1}


def test_audit_document_requires_plan(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"session_coaching_facts": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="next_stint_plan"):
        audit_document(json.loads(path.read_text(encoding="utf-8")))


def test_audit_document_walks_plan(tmp_path: Path):
    path = tmp_path / "debrief.json"
    path.write_text(
        json.dumps(document_with_plan([plan_item()])),
        encoding="utf-8",
    )

    audit = audit_document(json.loads(path.read_text(encoding="utf-8")))

    assert audit["zone_count"] == 1
    assert audit["zones"][0]["plan_label"] == "A"
