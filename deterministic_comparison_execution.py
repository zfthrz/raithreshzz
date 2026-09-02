"""Backend-neutral execution of one prepared debrief comparison."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from deterministic_comparison_decision import resolve_comparison_response
from deterministic_comparison_preparation import PreparedComparison
from deterministic_debrief_document import build_comparison_result


QUALITY_GATE_AUDIT_RENDER = (
    "Comparación preservada para auditoría. Fue excluida del coaching de sesión "
    "por el gate global de calidad y no se envió al LLM."
)


class ComparisonResponseRejected(RuntimeError):
    def __init__(self, validation_errors):
        self.validation_errors = list(validation_errors or [])
        super().__init__(
            "LLM_STRUCTURED_VALIDATION_FAILED. "
            "La respuesta no se guardó como análisis válido."
        )


@dataclass(frozen=True)
class ExecutedComparison:
    result: dict[str, Any]
    validated: dict[str, Any]
    route: str


def execute_prepared_comparison(
    comparison: dict[str, Any],
    prepared: PreparedComparison,
    *,
    eligible_response: Callable[[], dict[str, Any]],
    render_comparison: Callable[..., str],
) -> ExecutedComparison:
    validated, route = resolve_comparison_response(
        session_plan_eligible=prepared.session_plan_eligible,
        episode_catalog=prepared.episode_catalog,
        eligible_response=eligible_response,
    )
    if validated.get("status") != "VALID":
        raise ComparisonResponseRejected(validated.get("validation_errors"))

    structured = validated.get("response")
    if not isinstance(structured, dict):
        raise ComparisonResponseRejected(["response estructurada ausente"])

    if prepared.session_plan_eligible:
        rendered = render_comparison(
            comparison,
            prepared.episode_catalog,
            structured,
        )
    else:
        rendered = QUALITY_GATE_AUDIT_RENDER

    result = build_comparison_result(
        comparison=comparison,
        comparison_quality=prepared.comparison_quality,
        session_plan_eligible=prepared.session_plan_eligible,
        detected_episode_catalog=prepared.detected_episode_catalog,
        episode_catalog=prepared.episode_catalog,
        excluded_anomalies=prepared.excluded_anomalies,
        validated=validated,
        rendered=rendered,
    )
    return ExecutedComparison(result=result, validated=validated, route=route)
