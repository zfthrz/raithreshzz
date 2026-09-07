"""Compatible persistence provider for the deterministic product debrief."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from debrief_english import build_english_presentation
from debrief_language import load_debrief_language, require_language

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
    language=None,
    default_language=None,
):
    """Write the established artifact schema without importing a backend."""
    output_path_value, output_dir_value = compatible_debrief_output_path(
        input_path,
        model_name=model_name,
    )
    selected_language = (
        require_language(language)
        if language is not None
        else require_language(default_language or load_debrief_language())
    )
    if output_path_value.exists():
        existing = json.loads(output_path_value.read_text(encoding="utf-8"))
        stored_language = require_language(existing.get("metadata", {}).get("debrief_language", "es"))
        if language is not None and selected_language != stored_language:
            raise ValueError("Changing the language of an existing debrief is not supported")
        selected_language = stored_language
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
    document["metadata"]["debrief_language"] = selected_language
    document["metadata"]["report_presentation_version"] = "2.5"
    if selected_language == "en":
        document["localized_presentation"] = build_english_presentation(document)
    write_debrief_document(output_path_value, document)
    return str(output_path_value), str(output_dir_value)
