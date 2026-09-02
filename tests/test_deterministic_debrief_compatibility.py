from __future__ import annotations

from copy import deepcopy

from deterministic_debrief_compatibility import (
    LEGACY_ARTIFACT_FIELDS,
    LegacyArtifactMetadata,
)
from deterministic_debrief_document import build_debrief_document


def test_legacy_metadata_mapping_is_complete_and_provider_neutral():
    metadata = LegacyArtifactMetadata(
        model_name="deepseek-v4-pro",
        context_size=8192,
        temperature=0.15,
        anomaly_gate_config={"local_loss_s": 1.0},
    )
    usage = {"http_request_count": 0, "total_tokens": 0}

    assert set(LEGACY_ARTIFACT_FIELDS) == {
        "model_name",
        "usage_summary",
        "context_size",
        "temperature",
        "anomaly_gate_config",
    }
    assert metadata.persistence_kwargs(usage) == {
        "model_name": "deepseek-v4-pro",
        "usage_summary": usage,
        "context_size": 8192,
        "temperature": 0.15,
        "anomaly_gate_config": {"local_loss_s": 1.0},
    }


def test_compatibility_object_preserves_exact_document_shape():
    compatibility = LegacyArtifactMetadata(
        model_name="deepseek-v4-pro",
        context_size=8192,
        temperature=0.15,
        anomaly_gate_config={"threshold": 1},
    )
    usage = {"http_request_count": 0}
    common = {
        "input_path": "source.json",
        "metadata": {"track": "Spa", "reference_lap": 1},
        "comparison_results": [],
        "session_coaching_facts": {},
        "global_structured": {},
        "global_analysis": "Debrief exacto",
        "global_validation_audit": {},
        "analysis_timestamp": "2026-09-02T00:00:00+00:00",
    }

    expected = build_debrief_document(
        **deepcopy(common),
        model_name="deepseek-v4-pro",
        usage_summary=deepcopy(usage),
        context_size=8192,
        temperature=0.15,
        anomaly_gate_config={"threshold": 1},
    )
    actual = build_debrief_document(
        **deepcopy(common),
        **compatibility.persistence_kwargs(deepcopy(usage)),
    )

    assert actual == expected
    assert actual["metadata"]["model"] == "deepseek-v4-pro"
    assert actual["metadata"]["deepseek_usage"] == usage
