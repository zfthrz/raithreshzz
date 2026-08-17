from __future__ import annotations

import json
from pathlib import Path

import rerender_llm_analysis_output as rerender


def test_rebuild_splits_throttle_point_and_profile_without_mutating_source(
    tmp_path: Path,
    monkeypatch,
):
    source_path = tmp_path / "source.json"
    source_path.write_text("{}", encoding="utf-8")
    item = {
        "plan_label": "A",
        "comparison_count": 3,
        "track_location": {"label": "Test corner"},
        "braking_point_patterns": [],
        "brake_release_patterns": [],
        "throttle_onset_patterns": [{
            "coaching_magnitude_m": 10,
            "coaching_direction": "later",
            "comparison_count": 2,
        }],
        "throttle_release_patterns": [],
        "reference_action_profiles": [{
            "channel": "throttle",
            "shape_summary": "reaplicación sostenida sin volver a soltar dentro de la zona",
            "steps": [{"kind": "application"}],
        }],
        "driver_cues": [{"text": "old combined cue"}],
        "actionable_cue_count": 1,
    }
    document = {
        "metadata": {"track": "Test Track"},
        "comparisons": [],
        "session_coaching_facts": {
            "next_stint_plan": [item],
            "session_priority_policy": {
                "version": "1.9",
                "actionability_policy_version": "1.6",
            },
        },
        "global_structured": {
            "repeated_observations": [],
            "next_session_priorities": [],
            "opportunities": [],
            "hypotheses": [],
            "limitations": [],
            "conclusion": "Conclusión segura",
        },
        "global_analysis": "old render",
    }
    monkeypatch.setattr(
        rerender.renderer,
        "render_global_analysis",
        lambda metadata, comparisons, facts, structured: "new render",
    )

    rebuilt = rerender.rebuild_document(document, source_path=source_path)

    assert document["session_coaching_facts"]["next_stint_plan"][0][
        "driver_cues"
    ] == [{"text": "old combined cue"}]
    rebuilt_item = rebuilt["session_coaching_facts"]["next_stint_plan"][0]
    assert [cue["kind"] for cue in rebuilt_item["driver_cues"]] == [
        "spatial_points",
        "reference_action_profile",
    ]
    assert rebuilt_item["driver_cues"][0]["text"] == (
        "reaplicá el acelerador aproximadamente 10 m más tarde"
    )
    assert rebuilt_item["driver_cues"][1]["text"] == (
        "reaplicá y sostené el acelerador como en la referencia"
    )
    assert rebuilt_item["actionable_cue_count"] == 2
    assert rebuilt["session_coaching_facts"]["session_priority_policy"][
        "actionability_policy_version"
    ] == "1.7"
    assert rebuilt["global_analysis"] == "new render"
    assert rebuilt["metadata"]["deterministic_rerender"]["llm_called"] is False
    assert rebuilt["global_structured"]["next_session_priorities"] == [
        "Zona prioritaria A: reaplicá el acelerador aproximadamente 10 m más "
        "tarde; reaplicá y sostené el acelerador como en la referencia"
    ]
