"""Deterministic decision boundary for one debrief comparison.

This module owns the fail-closed responses for comparisons excluded by the
session quality gate or by the anomaly gate.  The normal eligible path is
supplied as a callback so transport/provider details remain outside this
policy module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


ValidatedResponse = dict[str, Any]


def quality_gate_excluded_response() -> ValidatedResponse:
    return {
        "status": "VALID",
        "attempts": 0,
        "response": {
            "episode_assessments": [],
            "comparison_observations": [],
            "limitations": [
                "Comparación globalmente no representativa; no se usa para coaching de sesión"
            ],
            "conclusion": (
                "Comparación preservada para auditoría; excluida del coaching de sesión"
            ),
        },
        "validation_errors": [],
        "audit": {
            "episodes": [],
            "priority_ranking": {
                "attempts": 0,
                "ordered_episode_ids": [],
                "priority_cut_rank": None,
                "no_actionable_start_rank": None,
                "classifications": [],
            },
            "summary": {
                "attempts": 0,
                "fallback": "COMPARISON_QUALITY_GATE_EXCLUDED_BEFORE_LLM",
                "pruned_summary_items": {},
            },
        },
    }


def anomaly_gate_excluded_response() -> ValidatedResponse:
    return {
        "status": "VALID",
        "attempts": 0,
        "response": {
            "episode_assessments": [],
            "comparison_observations": [],
            "limitations": [
                (
                    "No se generó coaching técnico porque los episodios "
                    "detectados fueron excluidos como pérdidas anómalas"
                )
            ],
            "conclusion": "No se genera coaching técnico para esta comparación",
        },
        "validation_errors": [],
        "audit": {
            "episodes": [],
            "priority_ranking": {
                "attempts": 0,
                "ordered_episode_ids": [],
                "priority_cut_rank": None,
                "no_actionable_start_rank": None,
                "classifications": [],
            },
            "summary": {
                "attempts": 0,
                "fallback": "ALL_EPISODES_EXCLUDED_BY_ANOMALY_GATE",
                "pruned_summary_items": {},
            },
        },
    }


def resolve_comparison_response(
    *,
    session_plan_eligible: bool,
    episode_catalog: list[dict[str, Any]],
    eligible_response: Callable[[], ValidatedResponse],
) -> tuple[ValidatedResponse, str]:
    """Return the established response plus an explicit deterministic route."""
    if not session_plan_eligible:
        return quality_gate_excluded_response(), "QUALITY_GATE_EXCLUDED"
    if not episode_catalog:
        return anomaly_gate_excluded_response(), "ANOMALY_GATE_EXCLUDED"
    return eligible_response(), "ELIGIBLE"
