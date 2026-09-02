"""Neutral composition root for the deterministic product debrief."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from coaching_precision import render_track_reference_section
from comparison_response_pipeline import build_validated_comparison_response
from deterministic_coaching import build_deterministic_next_session_priorities
from deterministic_comparison_execution import execute_prepared_comparison
from deterministic_comparison_preparation import require_detected_episodes
from deterministic_comparison_render import render_comparison_analysis
from deterministic_comparison_responses import (
    build_episode_response,
    build_ranker_response,
    build_summary_response,
)
from deterministic_comparison_stage import prepare_runtime_comparison
from deterministic_comparison_summary import build_deterministic_comparison_summary
from deterministic_comparison_validation import validate_comparison_response
from deterministic_debrief_dataset import build_debrief_dataset
from deterministic_debrief_finalize import finalize_validated_global_debrief
from deterministic_debrief_input import prepare_debrief_input
from deterministic_debrief_output import save_compatible_debrief
from deterministic_debrief_presentation import build_console_presentation
from deterministic_debrief_wiring import StageProviders, bind_stages
from deterministic_episode_response import build_grounded_episode_response
from deterministic_episode_validation import validate_single_episode_response
from deterministic_global_fallback import build_validated_deterministic_global_response
from deterministic_global_render import render_global_analysis
from deterministic_global_validation import validate_global_response
from deterministic_input_contract import load_json, validate_data_model, validate_lap_times
from deterministic_priority_contract import (
    apply_priority_classifications,
    derive_priority_classifications,
    validate_priority_ranker_response,
)
from deterministic_priority_shadow import build_deterministic_ranker_shadow_audit
from deterministic_summary_validation import validate_comparison_summary_response
from deterministic_track_context import load_track_location_context
from product_priority_ranker import build_product_priority_ranker_response
from session_coaching import build_session_coaching_facts
from session_coaching_quality import build_session_comparison_quality_gate
from session_coaching_recurrence import _comparison_quality_map


@dataclass(frozen=True)
class LegacyArtifactMetadata:
    """Schema-compatible metadata retained without selecting a backend."""

    model_name: str
    context_size: int
    temperature: float
    anomaly_gate_config: dict


STAGE_PROVIDER_CLASSIFICATION = {
    "prepare_input": "neutral_wrapper",
    "build_quality_gate": "neutral_direct",
    "quality_by_key": "neutral_direct",
    "prepare_comparison": "neutral_direct",
    "require_detected": "neutral_direct",
    "execute_comparison": "neutral_direct",
    "build_session_facts": "neutral_direct",
    "get_global_response": "neutral_direct",
    "finalize_global": "neutral_direct",
    "save_result": "compatibility_wrapper",
}


def prepare_input(input_path, *, base_dir):
    return prepare_debrief_input(
        input_path,
        load_json=load_json,
        validate_data_model=validate_data_model,
        validate_lap_times=validate_lap_times,
        build_dataset=build_debrief_dataset,
        load_track_location_context=lambda metadata: load_track_location_context(
            metadata, base_dir=base_dir
        ),
    )


def prepare_comparison(comparison, quality_by_key, track_location_context):
    return prepare_runtime_comparison(
        comparison,
        quality_by_key,
        track_location_context,
    )


def execute_comparison(comparison, prepared, metadata, output_dir):
    return execute_prepared_comparison(
        comparison,
        prepared,
        eligible_response=lambda: build_validated_comparison_response(
            metadata,
            comparison,
            prepared.episode_catalog,
            output_dir,
            get_episode_response=lambda metadata, comparison, episode, output_dir: build_episode_response(
                episode,
                build_fallback=build_grounded_episode_response,
                validate_response=validate_single_episode_response,
            ),
            get_ranker_response=lambda episode_catalog, episode_assessments, comparison, output_dir: build_ranker_response(
                episode_catalog,
                build_ranker=build_product_priority_ranker_response,
                validate_response=validate_priority_ranker_response,
            ),
            build_ranker_shadow=build_deterministic_ranker_shadow_audit,
            apply_classifications=apply_priority_classifications,
            get_summary_response=lambda episode_assessments, episode_catalog, comparison, output_dir: build_summary_response(
                episode_assessments,
                episode_catalog,
                build_summary=lambda assessments, catalog: build_deterministic_comparison_summary(
                    assessments,
                    catalog,
                    validate_summary=validate_comparison_summary_response,
                ),
            ),
            validate_response=validate_comparison_response,
            derive_classifications=derive_priority_classifications,
        ),
        render_comparison=render_comparison_analysis,
    )


def get_global_response(metadata, comparison_results, session_facts, output_dir):
    del metadata, output_dir
    return build_validated_deterministic_global_response(
        session_facts,
        comparison_results,
        validate_response=validate_global_response,
        build_priorities=build_deterministic_next_session_priorities,
    )


def finalize_global(validated, metadata, comparison_results, session_facts, track_context):
    return finalize_validated_global_debrief(
        global_validated=validated,
        metadata=metadata,
        comparison_results=comparison_results,
        session_coaching_facts=session_facts,
        track_location_context=track_context,
        render_global=render_global_analysis,
        render_track_reference=render_track_reference_section,
    )


def build_stage_providers(*, base_dir: str, save_result: Callable) -> StageProviders:
    """Expose the audited product callables before output-dir binding."""
    return StageProviders(
        prepare_input=lambda input_path: prepare_input(input_path, base_dir=base_dir),
        build_quality_gate=build_session_comparison_quality_gate,
        quality_by_key=_comparison_quality_map,
        prepare_comparison=prepare_comparison,
        require_detected=require_detected_episodes,
        execute_comparison=execute_comparison,
        build_session_facts=build_session_coaching_facts,
        get_global_response=get_global_response,
        finalize_global=finalize_global,
        save_result=save_result,
    )


def build_debrief_runtime(
    *,
    output_dir: str,
    base_dir: str,
    artifact_metadata: LegacyArtifactMetadata,
    usage_record: Callable[[], dict],
    usage_presentation: Callable[[], None],
    save_output: Callable = save_compatible_debrief,
):
    """Build the product runtime while preserving the legacy artifact schema."""

    def save_result(
        input_path,
        metadata,
        comparison_results,
        session_facts,
        global_structured,
        global_analysis,
        global_validation_audit=None,
    ):
        return save_output(
            input_path,
            metadata,
            comparison_results,
            session_facts,
            global_structured,
            global_analysis,
            global_validation_audit,
            model_name=artifact_metadata.model_name,
            usage_summary=usage_record(),
            context_size=artifact_metadata.context_size,
            temperature=artifact_metadata.temperature,
            anomaly_gate_config=artifact_metadata.anomaly_gate_config,
        )

    providers = build_stage_providers(base_dir=base_dir, save_result=save_result)
    stages = bind_stages(providers, output_dir=output_dir)
    presentation = build_console_presentation(
        model_name=artifact_metadata.model_name,
        context_size=artifact_metadata.context_size,
        temperature=artifact_metadata.temperature,
        usage_summary=usage_presentation,
    )
    return stages, presentation
