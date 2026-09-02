from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import deterministic_debrief_runtime as runtime


ROOT = Path(__file__).resolve().parents[1]


def _prepared_input(comparisons):
    return SimpleNamespace(
        source_data={"raw": []},
        metadata={"comparisons": len(comparisons)},
        comparisons=comparisons,
        track_location_context={"status": "NO_TRACK_PROFILE"},
    )


def _make_presentation(log):
    def start():
        log.append("start")

    def model_banner():
        log.append("model_banner")

    def track_status(ctx):
        log.append("track_status")

    def architecture():
        log.append("architecture")

    def quality_gate(gate):
        log.append("quality_gate")

    def comparison_header(index):
        log.append("comparison_header")

    def comparison_facts(comparison, prepared):
        log.append("comparison_facts")

    def comparison_route(prepared):
        log.append("comparison_route")

    def comparison_rejected(comparison, errors):
        log.append("comparison_rejected")

    def comparison_validated(execution):
        log.append("comparison_validated")

    def synthesis_header():
        log.append("synthesis_header")

    def session_facts(facts):
        log.append("session_facts")

    def synthesis_request():
        log.append("synthesis_request")

    def synthesis_rejected(errors):
        log.append("synthesis_rejected")

    def usage_summary():
        log.append("usage_summary")

    def final_analysis(analysis):
        log.append("final_analysis")

    def saved_result(output_path):
        log.append("saved_result")

    def complete():
        log.append("complete")

    return runtime.DebriefPresentation(
        start=start,
        model_banner=model_banner,
        track_status=track_status,
        architecture=architecture,
        quality_gate=quality_gate,
        comparison_header=comparison_header,
        comparison_facts=comparison_facts,
        comparison_route=comparison_route,
        comparison_rejected=comparison_rejected,
        comparison_validated=comparison_validated,
        synthesis_header=synthesis_header,
        session_facts=session_facts,
        synthesis_request=synthesis_request,
        synthesis_rejected=synthesis_rejected,
        usage_summary=usage_summary,
        final_analysis=final_analysis,
        saved_result=saved_result,
        complete=complete,
    )


def _make_stages(log, comparisons):
    gate = {"excluded_count": 0}
    quality_by_key = {}

    def prepare_input(path):
        log.append("prepare_input")
        return _prepared_input(comparisons)

    def build_quality_gate(comparisons_arg):
        log.append("build_quality_gate")
        return gate

    def quality_by_key_fn(gate_arg):
        log.append("quality_by_key")
        return quality_by_key

    def prepare_comparison(comparison, key, ctx):
        log.append("prepare_comparison")
        return SimpleNamespace(
            detected_episode_catalog=[{"episode_id": 1}],
            episode_catalog=[],
        )

    def require_detected(comparison, detected_catalog):
        log.append("require_detected")

    def execute_comparison(comparison, prepared, metadata):
        log.append("execute_comparison")
        return SimpleNamespace(result={"ok": True}, validated={"attempts": 0})

    def build_session_facts(results, ctx, source):
        log.append("build_session_facts")
        return {"priority_finding_count": 1}

    def get_global_response(metadata, results, facts):
        log.append("get_global_response")
        return {"status": "VALID"}

    def finalize_global(validated, metadata, results, facts, ctx):
        log.append("finalize_global")
        return ({"structured": {}}, {"audit": {}}, "ANALYSIS")

    def save_result(input_path, metadata, results, facts, structured, analysis, audit):
        log.append("save_result")
        return ("/tmp/out.json", "/tmp")

    return runtime.DebriefStages(
        prepare_input=prepare_input,
        build_quality_gate=build_quality_gate,
        quality_by_key=quality_by_key_fn,
        prepare_comparison=prepare_comparison,
        require_detected=require_detected,
        execute_comparison=execute_comparison,
        build_session_facts=build_session_facts,
        get_global_response=get_global_response,
        finalize_global=finalize_global,
        save_result=save_result,
    )


def test_runtime_source_has_no_backend_imports():
    source = (ROOT / "deterministic_debrief_runtime.py").read_text(encoding="utf-8")
    assert "llm_analysis" not in source
    assert "import llm_analysis" not in source
    assert "from llm_analysis" not in source


def test_order_of_calls_single_comparison():
    log = []
    comparisons = [{"reference_lap": 1, "comparison_lap": 2}]
    stages = _make_stages(log, comparisons)
    presentation = _make_presentation(log)

    result = runtime.run_deterministic_debrief(
        stages=stages,
        presentation=presentation,
        input_path="INPUT",
    )

    assert result.input_path == "INPUT"
    assert result.output_path == "/tmp/out.json"
    assert result.global_analysis == "ANALYSIS"

    # Exact, full order for one comparison.
    assert log == [
        "start",
        "prepare_input",
        "model_banner",
        "track_status",
        "architecture",
        "build_quality_gate",
        "quality_by_key",
        "quality_gate",
        "comparison_header",
        "prepare_comparison",
        "comparison_facts",
        "require_detected",
        "comparison_route",
        "execute_comparison",
        "comparison_validated",
        "synthesis_header",
        "build_session_facts",
        "session_facts",
        "synthesis_request",
        "get_global_response",
        "finalize_global",
        "save_result",
        "usage_summary",
        "final_analysis",
        "saved_result",
        "complete",
    ]


def test_exact_input_output_propagation():
    log = []
    comparisons = [{"reference_lap": 1, "comparison_lap": 2}]
    stages = _make_stages(log, comparisons)
    presentation = _make_presentation(log)

    result = runtime.run_deterministic_debrief(
        stages=stages,
        presentation=presentation,
        input_path="INPUT",
    )

    # The prepared input is propagated through to the final result.
    assert result.prepared.comparisons == comparisons
    assert result.output_path == "/tmp/out.json"
    assert result.output_dir == "/tmp"
    assert result.global_analysis == "ANALYSIS"
    # Final write captured from save_result.
    assert result.comparison_results[0] == {"ok": True}
    assert result.session_coaching_facts["priority_finding_count"] == 1


def test_final_write_captured_in_result():
    log = []
    comparisons = [{"reference_lap": 1, "comparison_lap": 2}]
    stages = _make_stages(log, comparisons)
    presentation = _make_presentation(log)

    result = runtime.run_deterministic_debrief(
        stages=stages,
        presentation=presentation,
        input_path="INPUT",
    )

    assert "save_result" in log
    assert result.output_path == "/tmp/out.json"
    assert result.output_dir == "/tmp"


def test_failure_without_hidden_fallback_on_rejected_global():
    # A rejected global synthesis must fail-closed, not fall back.
    log = []
    comparisons = [{"reference_lap": 1, "comparison_lap": 2}]
    stages = _make_stages(log, comparisons)
    presentation = _make_presentation(log)

    def rejected_global(metadata, results, facts):
        log.append("get_global_response")
        return {"status": "REJECTED", "validation_errors": ["bad"]}

    stages = runtime.DebriefStages(
        **{**stages.__dict__, "get_global_response": rejected_global}
    )

    with pytest.raises(RuntimeError, match="GLOBAL_LLM_STRUCTURED_VALIDATION_FAILED"):
        runtime.run_deterministic_debrief(
            stages=stages,
            presentation=presentation,
            input_path="INPUT",
        )
    # No final write after a rejected synthesis.
    assert "save_result" not in log


def test_failure_without_hidden_fallback_on_compare_reject():
    # A comparison that raises ComparisonResponseRejected must propagate.
    log = []
    comparisons = [{"reference_lap": 1, "comparison_lap": 2}]
    stages = _make_stages(log, comparisons)
    presentation = _make_presentation(log)

    def execute_rejected(comparison, prepared, metadata):
        log.append("execute_comparison")
        raise runtime.ComparisonResponseRejected(["err"])

    stages = runtime.DebriefStages(
        **{**stages.__dict__, "execute_comparison": execute_rejected}
    )

    with pytest.raises(RuntimeError, match="LLM_STRUCTURED_VALIDATION_FAILED"):
        runtime.run_deterministic_debrief(
            stages=stages,
            presentation=presentation,
            input_path="INPUT",
        )
    # No final write after a rejected comparison.
    assert "save_result" not in log
