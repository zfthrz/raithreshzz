from __future__ import annotations

from copy import deepcopy

from deterministic_comparison_decision import resolve_comparison_response


def test_quality_gate_fails_closed_without_calling_eligible_provider():
    called = []
    result, route = resolve_comparison_response(
        session_plan_eligible=False,
        episode_catalog=[{"episode_id": 1}],
        eligible_response=lambda: called.append(True),
    )
    assert called == []
    assert route == "QUALITY_GATE_EXCLUDED"
    assert result["status"] == "VALID"
    assert result["audit"]["summary"]["fallback"] == (
        "COMPARISON_QUALITY_GATE_EXCLUDED_BEFORE_LLM"
    )


def test_anomaly_gate_fails_closed_without_calling_eligible_provider():
    called = []
    result, route = resolve_comparison_response(
        session_plan_eligible=True,
        episode_catalog=[],
        eligible_response=lambda: called.append(True),
    )
    assert called == []
    assert route == "ANOMALY_GATE_EXCLUDED"
    assert result["audit"]["summary"]["fallback"] == (
        "ALL_EPISODES_EXCLUDED_BY_ANOMALY_GATE"
    )


def test_eligible_route_returns_provider_result_without_mutation():
    provider_result = {"status": "VALID", "response": {"items": [1]}}
    before = deepcopy(provider_result)
    result, route = resolve_comparison_response(
        session_plan_eligible=True,
        episode_catalog=[{"episode_id": 1}],
        eligible_response=lambda: provider_result,
    )
    assert route == "ELIGIBLE"
    assert result is provider_result
    assert provider_result == before


def test_quality_gate_has_precedence_over_empty_episode_catalog():
    result, route = resolve_comparison_response(
        session_plan_eligible=False,
        episode_catalog=[],
        eligible_response=lambda: {"status": "INVALID"},
    )
    assert route == "QUALITY_GATE_EXCLUDED"
    assert result["audit"]["summary"]["fallback"] == (
        "COMPARISON_QUALITY_GATE_EXCLUDED_BEFORE_LLM"
    )
