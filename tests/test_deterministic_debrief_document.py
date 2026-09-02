from __future__ import annotations

import json

from deterministic_debrief_document import (
    build_comparison_result,
    build_debrief_document,
    write_debrief_document,
)


def test_document_builder_preserves_schema_and_first_detector():
    comparisons = [
        {"braking_point_detection": {}, "throttle_point_detection": {}},
        {
            "braking_point_detection": {"version": "2.1"},
            "throttle_point_detection": {"version": "1.2"},
        },
    ]
    document = build_debrief_document(
        input_path="analysis.json",
        metadata={
            "analysis_version": "3.8",
            "track": "Spa",
            "session_type": "P",
            "timestamp_utc": "2026-09-01T00:00:00Z",
            "reference_lap": 3,
        },
        comparison_results=comparisons,
        session_coaching_facts={
            "track_location_profile": {"profile_id": "spa"},
            "comparison_quality_gate": {"status": "PASS"},
        },
        global_structured={"opportunities": []},
        global_analysis="Debrief",
        global_validation_audit=None,
        analysis_timestamp="2026-09-01T01:00:00+00:00",
        model_name="deterministic",
        usage_summary={"http_request_count": 0},
        context_size=32768,
        temperature=0.0,
        anomaly_gate_config={"threshold": 1},
    )
    assert list(document) == [
        "metadata",
        "comparisons",
        "session_coaching_facts",
        "global_validation_audit",
        "global_structured",
        "global_analysis",
    ]
    assert document["metadata"]["braking_point_detection"] == {"version": "2.1"}
    assert document["metadata"]["throttle_point_detection"] == {"version": "1.2"}
    assert document["metadata"]["deepseek_usage"]["http_request_count"] == 0
    assert document["global_validation_audit"] == {}


def test_document_writer_uses_utf8_and_established_indentation(tmp_path):
    destination = tmp_path / "nested" / "debrief.json"
    document = {"text": "frená", "items": [1, 2]}
    assert write_debrief_document(destination, document) == destination
    raw = destination.read_text(encoding="utf-8")
    assert raw == json.dumps(document, indent=2, ensure_ascii=False)
    assert json.loads(raw) == document


def test_comparison_result_preserves_ground_truth_and_counts():
    comparison = {
        "reference_lap": 1,
        "comparison_lap": 2,
        "reference_time_s": 90.0,
        "comparison_time_s": 90.5,
        "comparison_minus_reference_s": 0.5,
        "driver_analysis_priority": "HIGH",
        "driver_analysis_priority_rank": 1,
        "objective_analysis": {
            "braking_point_detection": {"version": "2.1"},
            "throttle_point_detection": {"version": "1.2"},
        },
    }
    episodes = [{"episode_id": 1}]
    result = build_comparison_result(
        comparison=comparison,
        comparison_quality={"status": "PASS"},
        session_plan_eligible=True,
        detected_episode_catalog=episodes + [{"episode_id": 2}],
        episode_catalog=episodes,
        excluded_anomalies=[{"episode_id": 2}],
        validated={"attempts": 0, "response": {"episode_assessments": []}},
        rendered="rendered",
    )
    assert result["ground_truth"]["comparison_minus_reference_s"] == 0.5
    assert result["detected_driver_action_episode_count"] == 2
    assert result["coaching_eligible_episode_count"] == 1
    assert result["excluded_anomaly_count"] == 1
    assert result["braking_point_detection"] == {"version": "2.1"}
    assert result["analysis"] == "rendered"
