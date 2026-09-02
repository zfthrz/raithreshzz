from __future__ import annotations

import pytest

from deterministic_comparison_execution import (
    ComparisonResponseRejected,
    QUALITY_GATE_AUDIT_RENDER,
    execute_prepared_comparison,
)
from deterministic_comparison_preparation import PreparedComparison


COMPARISON = {
    "reference_lap": 1,
    "comparison_lap": 2,
    "reference_time_s": 90.0,
    "comparison_time_s": 90.5,
    "comparison_minus_reference_s": 0.5,
}


def prepared(*, eligible=True, episodes=None):
    catalog = [{"episode_id": 1}] if episodes is None else episodes
    return PreparedComparison(
        comparison_quality={"session_plan_eligible": eligible},
        session_plan_eligible=eligible,
        detected_episode_catalog=[{"episode_id": 1}],
        episode_catalog=catalog,
        excluded_anomalies=[],
    )


def test_execute_eligible_response_renders_and_builds_result():
    renders = []
    execution = execute_prepared_comparison(
        COMPARISON,
        prepared(),
        eligible_response=lambda: {
            "status": "VALID",
            "attempts": 0,
            "response": {"episode_assessments": []},
        },
        render_comparison=lambda comparison, episodes, response: renders.append(
            (comparison, episodes, response)
        )
        or "rendered",
    )
    assert execution.route == "ELIGIBLE"
    assert execution.result["analysis"] == "rendered"
    assert len(renders) == 1


def test_execute_quality_gate_never_calls_provider_or_renderer():
    calls = []
    execution = execute_prepared_comparison(
        COMPARISON,
        prepared(eligible=False),
        eligible_response=lambda: calls.append("provider"),
        render_comparison=lambda *args: calls.append("render"),
    )
    assert calls == []
    assert execution.route == "QUALITY_GATE_EXCLUDED"
    assert execution.result["analysis"] == QUALITY_GATE_AUDIT_RENDER


def test_execute_anomaly_gate_uses_deterministic_empty_response():
    execution = execute_prepared_comparison(
        COMPARISON,
        prepared(episodes=[]),
        eligible_response=lambda: pytest.fail("provider must not run"),
        render_comparison=lambda *args: "empty render",
    )
    assert execution.route == "ANOMALY_GATE_EXCLUDED"
    assert execution.result["analysis"] == "empty render"


def test_execute_rejects_invalid_provider_response():
    with pytest.raises(ComparisonResponseRejected) as exc:
        execute_prepared_comparison(
            COMPARISON,
            prepared(),
            eligible_response=lambda: {
                "status": "REJECTED",
                "validation_errors": ["bad"],
            },
            render_comparison=lambda *args: "unused",
        )
    assert exc.value.validation_errors == ["bad"]
