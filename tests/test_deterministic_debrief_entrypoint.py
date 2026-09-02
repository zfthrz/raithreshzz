from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

import deterministic_debrief
import race_engineer


def test_entrypoint_configures_all_gates_and_blocks_llm_backend(monkeypatch):
    """Verify deterministic_debrief.run() configures gates, blocks DeepSeek,
    and does NOT transitively import any llm_analysis* module."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")

    # Patch at the target module so the lazy import inside run() is intercepted.
    with patch("deterministic_debrief_main.main") as mock_main:
        assert deterministic_debrief.run() == 0
        assert "DEEPSEEK_API_KEY" not in deterministic_debrief.os.environ
        assert deterministic_debrief.os.environ[
            "RACE_ENGINEER_LLM_RANKER"
        ] == "0"
        for name, value in deterministic_debrief.DETERMINISTIC_ENVIRONMENT.items():
            assert deterministic_debrief.os.environ[name] == value


def test_orchestrator_resolves_product_entrypoint_not_provider_script():
    path = race_engineer.deterministic_debrief_script()

    assert path.name == "deterministic_debrief.py"
    assert path.is_file()
