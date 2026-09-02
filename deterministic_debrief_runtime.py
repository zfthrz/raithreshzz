"""Neutral coordinator for the deterministic debrief flow.

The runtime owns only the *order* of the six stages and the fail-closed
contract. Every backend-specific callable (LLM transport, model banner,
console presentation) is injected by the caller; nothing in this module
imports a provider or reaches for a backend.

Order:

    input -> comparaciones -> session coaching facts -> sintesis global
    -> finalizacion -> escritura

Presentation (``print`` / ``print_header`` / ``print_deepseek_usage_summary``)
is intentionally out of the core: it fires through the injected
``DebriefPresentation`` hooks, so the runtime stays a pure coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from deterministic_comparison_execution import (
    ComparisonResponseRejected,
    ExecutedComparison,
)
from deterministic_comparison_preparation import PreparedComparison
from deterministic_debrief_input import PreparedDebriefInput


@dataclass(frozen=True)
class DebriefStages:
    """Injectable stage providers (one per deterministic step)."""

    prepare_input: Callable[..., "PreparedDebriefInput"]
    build_quality_gate: Callable[..., dict]
    quality_by_key: Callable[..., dict]
    prepare_comparison: Callable[..., "PreparedComparison"]
    require_detected: Callable[..., None]
    execute_comparison: Callable[..., "ExecutedComparison"]
    build_session_facts: Callable[..., dict]
    get_global_response: Callable[..., dict]
    finalize_global: Callable[..., tuple]
    save_result: Callable[..., tuple]


@dataclass(frozen=True)
class DebriefPresentation:
    """Injectable console presentation hooks (all side effects)."""

    start: Callable[[], None]
    model_banner: Callable[[], None]
    track_status: Callable[..., None]
    architecture: Callable[[], None]
    quality_gate: Callable[..., None]
    comparison_header: Callable[..., None]
    comparison_facts: Callable[..., None]
    comparison_route: Callable[..., None]
    comparison_rejected: Callable[..., None]
    comparison_validated: Callable[..., None]
    synthesis_header: Callable[[], None]
    session_facts: Callable[..., None]
    synthesis_request: Callable[[], None]
    synthesis_rejected: Callable[..., None]
    usage_summary: Callable[[], None]
    final_analysis: Callable[..., None]
    saved_result: Callable[..., None]
    complete: Callable[[], None]


@dataclass(frozen=True)
class DebriefRunResult:
    """Neutral outcome of one coordinated run (no backend metadata)."""

    input_path: str
    output_path: str
    output_dir: str
    prepared: PreparedDebriefInput
    comparison_results: list
    session_coaching_facts: dict
    global_structured: dict
    global_validation_audit: dict
    global_analysis: str


def run_deterministic_debrief(
    *,
    stages: DebriefStages,
    presentation: DebriefPresentation,
    input_path: str,
) -> DebriefRunResult:
    """Coordinate the six deterministic debrief stages in exact order."""

    presentation.start()

    # 1. input
    prepared = stages.prepare_input(input_path)
    comparisons = prepared.comparisons
    track_location_context = prepared.track_location_context

    presentation.model_banner()
    presentation.track_status(track_location_context)
    presentation.architecture()

    # 2. comparaciones
    gate = stages.build_quality_gate(comparisons)
    quality_by_key = stages.quality_by_key(gate)
    presentation.quality_gate(gate)

    comparison_results = []
    for index, comparison in enumerate(comparisons, start=1):
        presentation.comparison_header(index)

        prepared_comparison = stages.prepare_comparison(
            comparison,
            quality_by_key,
            track_location_context,
        )
        presentation.comparison_facts(comparison, prepared_comparison)

        stages.require_detected(
            comparison,
            prepared_comparison.detected_episode_catalog,
        )
        presentation.comparison_route(prepared_comparison)

        try:
            execution = stages.execute_comparison(
                comparison,
                prepared_comparison,
                prepared.metadata,
            )
        except ComparisonResponseRejected as exc:
            presentation.comparison_rejected(comparison, exc.validation_errors)
            raise
        presentation.comparison_validated(execution)
        comparison_results.append(execution.result)

    # 3. session coaching facts
    presentation.synthesis_header()
    session_coaching_facts = stages.build_session_facts(
        comparison_results,
        track_location_context,
        prepared.source_data,
    )
    presentation.session_facts(session_coaching_facts)
    presentation.synthesis_request()

    # 4. sintesis global (fail-closed on rejected)
    global_validated = stages.get_global_response(
        prepared.metadata,
        comparison_results,
        session_coaching_facts,
    )
    if global_validated.get("status") != "VALID":
        presentation.synthesis_rejected(global_validated.get("validation_errors"))
        raise RuntimeError(
            "GLOBAL_LLM_STRUCTURED_VALIDATION_FAILED. "
            "La síntesis global no se guardó como válida."
        )

    # 5. finalizacion
    (
        global_structured,
        global_validation_audit,
        global_analysis,
    ) = stages.finalize_global(
        global_validated,
        prepared.metadata,
        comparison_results,
        session_coaching_facts,
        track_location_context,
    )

    # 6. escritura
    output_path, output_dir = stages.save_result(
        input_path,
        prepared.metadata,
        comparison_results,
        session_coaching_facts,
        global_structured,
        global_analysis,
        global_validation_audit,
    )

    presentation.usage_summary()
    presentation.final_analysis(global_analysis)
    presentation.saved_result(output_path)
    presentation.complete()

    return DebriefRunResult(
        input_path=input_path,
        output_path=output_path,
        output_dir=output_dir,
        prepared=prepared,
        comparison_results=comparison_results,
        session_coaching_facts=session_coaching_facts,
        global_structured=global_structured,
        global_validation_audit=global_validation_audit,
        global_analysis=global_analysis,
    )
