"""Explicit compatibility contract for the established debrief artifact."""

from __future__ import annotations

from dataclasses import dataclass


LEGACY_ARTIFACT_FIELDS = {
    "model_name": "metadata.model and compatible filename suffix",
    "usage_summary": "metadata.deepseek_usage",
    "context_size": "metadata.context",
    "temperature": "metadata.temperature",
    "anomaly_gate_config": "metadata.anomaly_gate.config",
}


@dataclass(frozen=True)
class LegacyArtifactMetadata:
    """Values retained byte-for-byte for readers of the historical schema.

    These names do not select a provider and carry no coaching authority.
    They remain explicit until a separately versioned schema migration exists.
    """

    model_name: str
    context_size: int
    temperature: float
    anomaly_gate_config: dict

    def persistence_kwargs(self, usage_summary: dict) -> dict:
        return {
            "model_name": self.model_name,
            "usage_summary": usage_summary,
            "context_size": self.context_size,
            "temperature": self.temperature,
            "anomaly_gate_config": self.anomaly_gate_config,
        }
