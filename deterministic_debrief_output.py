"""Compatible persistence provider for the deterministic product debrief."""

from __future__ import annotations

from datetime import datetime, timezone

from deterministic_debrief_document import (
    build_debrief_document,
    compatible_debrief_output_path,
    write_debrief_document,
)


def save_compatible_debrief(
    input_path,
    metadata,
    comparison_results,
    session_coaching_facts,
    global_structured,
    global_analysis,
    global_validation_audit=None,
    *,
    model_name,
    usage_summary,
    context_size,
    temperature,
    anomaly_gate_config,
    now=None,
):
    """Write the established artifact schema without importing a backend."""
    output_path_value, output_dir_value = compatible_debrief_output_path(
        input_path,
        model_name=model_name,
    )
    timestamp = (now or (lambda: datetime.now(timezone.utc)))().isoformat()
    document = build_debrief_document(
        input_path=input_path,
        metadata=metadata,
        comparison_results=comparison_results,
        session_coaching_facts=session_coaching_facts,
        global_structured=global_structured,
        global_analysis=global_analysis,
        global_validation_audit=global_validation_audit,
        analysis_timestamp=timestamp,
        model_name=model_name,
        usage_summary=usage_summary,
        context_size=context_size,
        temperature=temperature,
        anomaly_gate_config=anomaly_gate_config,
    )
    write_debrief_document(output_path_value, document)
    return str(output_path_value), str(output_dir_value)
