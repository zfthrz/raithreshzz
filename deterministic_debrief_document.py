"""Construction and serialization of the deterministic debrief artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _first_detection(comparisons, field):
    return next(
        (
            item.get(field)
            for item in comparisons
            if isinstance(item, dict)
            and isinstance(item.get(field), dict)
            and item.get(field)
        ),
        {},
    )


def build_debrief_document(
    *,
    input_path: str,
    metadata: dict[str, Any],
    comparison_results: list[dict[str, Any]],
    session_coaching_facts: dict[str, Any],
    global_structured: dict[str, Any],
    global_analysis: str,
    global_validation_audit: dict[str, Any] | None,
    analysis_timestamp: str,
    model_name: str,
    usage_summary: dict[str, Any],
    context_size: int,
    temperature: float,
    anomaly_gate_config: dict[str, Any],
) -> dict[str, Any]:
    """Build the stable historical JSON schema without filesystem access."""
    return {
        "metadata": {
            "llm_analysis_version": "3.10.8.5.4",
            "report_presentation_version": "2.4",
            "source_json": input_path,
            "source_analysis_version": metadata.get("analysis_version"),
            "track": metadata.get("track"),
            "session_type": metadata.get("session_type"),
            "timestamp_utc": metadata.get("timestamp_utc"),
            "reference_lap": metadata.get("reference_lap"),
            "model": model_name,
            "deepseek_usage": usage_summary,
            "context": context_size,
            "temperature": temperature,
            "track_location_profile": session_coaching_facts.get(
                "track_location_profile"
            ),
            "braking_point_detection": _first_detection(
                comparison_results, "braking_point_detection"
            ),
            "throttle_point_detection": _first_detection(
                comparison_results, "throttle_point_detection"
            ),
            "session_comparison_quality_gate": session_coaching_facts.get(
                "comparison_quality_gate", {}
            ),
            "anomaly_gate": {
                "version": "1.0",
                "status": "ACTIVE",
                "classification": "NON_REPRESENTATIVE_TIME_LOSS",
                "config": dict(anomaly_gate_config),
                "cause_inference": False,
            },
            "structured_validation": "PASS",
            "factual_grounding_validation": "PASS",
            "analysis_timestamp": analysis_timestamp,
        },
        "comparisons": comparison_results,
        "session_coaching_facts": session_coaching_facts,
        "global_validation_audit": global_validation_audit or {},
        "global_structured": global_structured,
        "global_analysis": global_analysis,
    }


def write_debrief_document(path: str | Path, document: dict[str, Any]) -> Path:
    """Write UTF-8 JSON using the established pretty-print contract."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return destination


def build_comparison_result(
    *,
    comparison: dict[str, Any],
    comparison_quality: dict[str, Any],
    session_plan_eligible: bool,
    detected_episode_catalog: list[dict[str, Any]],
    episode_catalog: list[dict[str, Any]],
    excluded_anomalies: list[dict[str, Any]],
    validated: dict[str, Any],
    rendered: str,
) -> dict[str, Any]:
    """Build one stable comparison record without mutating its inputs."""
    reference_lap = comparison["reference_lap"]
    comparison_lap = comparison["comparison_lap"]
    objective = comparison.get("objective_analysis", {}) or {}
    return {
        "status": "VALID",
        "validation_attempts": validated["attempts"],
        "llm_validation_audit": validated.get("audit", {}),
        "ground_truth": {
            "reference_lap": reference_lap,
            "comparison_lap": comparison_lap,
            "reference_time_s": comparison["reference_time_s"],
            "comparison_time_s": comparison["comparison_time_s"],
            "comparison_minus_reference_s": comparison[
                "comparison_minus_reference_s"
            ],
        },
        "reference_lap": reference_lap,
        "comparison_lap": comparison_lap,
        "reference_time_s": comparison["reference_time_s"],
        "comparison_time_s": comparison["comparison_time_s"],
        "comparison_minus_reference_s": comparison[
            "comparison_minus_reference_s"
        ],
        "driver_analysis_priority": comparison.get("driver_analysis_priority"),
        "driver_analysis_priority_rank": comparison.get(
            "driver_analysis_priority_rank"
        ),
        "session_plan_eligible": session_plan_eligible,
        "session_comparison_quality": comparison_quality,
        "detected_driver_action_episode_count": len(detected_episode_catalog),
        "driver_action_episode_count": len(episode_catalog),
        "coaching_eligible_episode_count": len(episode_catalog),
        "excluded_anomaly_count": len(excluded_anomalies),
        "excluded_anomalies": excluded_anomalies,
        "braking_point_detection": objective.get("braking_point_detection", {}),
        "throttle_point_detection": objective.get("throttle_point_detection", {}),
        "episode_ground_truth": episode_catalog,
        "llm_structured": validated["response"],
        "analysis": rendered,
    }
