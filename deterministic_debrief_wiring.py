"""Neutral binding of deterministic stage providers to one runtime run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from deterministic_debrief_runtime import DebriefStages


@dataclass(frozen=True)
class StageProviders:
    prepare_input: Callable
    build_quality_gate: Callable
    quality_by_key: Callable
    prepare_comparison: Callable
    require_detected: Callable
    execute_comparison: Callable
    build_session_facts: Callable
    get_global_response: Callable
    finalize_global: Callable
    save_result: Callable


def bind_stages(
    providers: StageProviders,
    *,
    output_dir: str,
) -> DebriefStages:
    """Bind only the debug-output argument; no backend is imported or selected."""
    return DebriefStages(
        prepare_input=providers.prepare_input,
        build_quality_gate=providers.build_quality_gate,
        quality_by_key=providers.quality_by_key,
        prepare_comparison=providers.prepare_comparison,
        require_detected=providers.require_detected,
        execute_comparison=lambda comparison, prepared, metadata: (
            providers.execute_comparison(
                comparison,
                prepared,
                metadata,
                output_dir,
            )
        ),
        build_session_facts=providers.build_session_facts,
        get_global_response=lambda metadata, results, facts: (
            providers.get_global_response(
                metadata,
                results,
                facts,
                output_dir,
            )
        ),
        finalize_global=providers.finalize_global,
        save_result=providers.save_result,
    )
