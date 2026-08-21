from __future__ import annotations

import hashlib
import os
from pathlib import Path

import analyze_telemetry_file as launcher
import llm_analysis_llamacpp as llamacpp
import race_engineer


ROOT = Path(__file__).resolve().parents[1]


def test_llamacpp_module_defaults(monkeypatch):
    monkeypatch.delenv("LLAMACPP_MODEL", raising=False)
    monkeypatch.delenv("LLAMACPP_API_URL", raising=False)
    import importlib

    module = importlib.reload(llamacpp)

    assert module.MODEL_NAME == "qwen3-14b"
    assert module.LLAMACPP_URL == "http://localhost:8080/v1/chat/completions"
    assert hasattr(module, "llamacpp_chat")


def test_race_engineer_resolves_llamacpp_backend(monkeypatch):
    monkeypatch.delenv("LLAMACPP_MODEL", raising=False)

    assert race_engineer.llm_script("llamacpp").name == "llm_analysis_llamacpp.py"
    assert race_engineer.llm_model_name("llamacpp") == "qwen3-14b"


def test_llamacpp_backend_is_exposed_in_entry_points():
    source = (ROOT / "race_engineer.py").read_text(encoding="utf-8")
    assert '"llamacpp"' in source
    launcher_source = (ROOT / "analyze_telemetry_file.py").read_text(encoding="utf-8")
    assert '"llamacpp"' in launcher_source
    historical = (ROOT / "historical_llm_analysis.py").read_text(encoding="utf-8")
    assert 'backend == "llamacpp"' in historical
    selection = (ROOT / "historical_candidate_selection.py").read_text(
        encoding="utf-8"
    )
    assert 'backend == "llamacpp"' in historical


# ── Context budget tests ─────────────────────────────────────────────────────


def test_compute_context_budget_basic():
    budget = llamacpp.compute_context_budget(
        prompt_tokens=5000,
        completion_tokens=2000,
        max_output_tokens=8192,
        context_window=131072,
    )
    assert budget["prompt_tokens"] == 5000
    assert budget["completion_tokens"] == 2000
    assert budget["max_output_tokens"] == 8192
    assert budget["context_window"] == 131072
    assert budget["estimated_remaining_tokens"] == 124072
    assert budget["usage_percent"] == 5.3
    assert budget["over_budget"] is False


def test_compute_context_budget_high_usage():
    budget = llamacpp.compute_context_budget(
        prompt_tokens=60000,
        completion_tokens=40000,
        max_output_tokens=8192,
        context_window=131072,
    )
    assert budget["estimated_remaining_tokens"] == 31072
    assert budget["usage_percent"] == 76.3
    assert budget["over_budget"] is False


def test_compute_context_budget_over_budget():
    budget = llamacpp.compute_context_budget(
        prompt_tokens=80000,
        completion_tokens=60000,
        max_output_tokens=8192,
        context_window=131072,
    )
    assert budget["estimated_remaining_tokens"] == -8928
    assert budget["usage_percent"] == 106.8
    assert budget["over_budget"] is True


def test_compute_context_budget_zero_window():
    budget = llamacpp.compute_context_budget(
        prompt_tokens=0,
        completion_tokens=0,
        max_output_tokens=8192,
        context_window=0,
    )
    assert budget["usage_percent"] == 0.0
    assert budget["over_budget"] is False


def test_compute_context_budget_exact_fit():
    budget = llamacpp.compute_context_budget(
        prompt_tokens=65536,
        completion_tokens=65536,
        max_output_tokens=8192,
        context_window=131072,
    )
    assert budget["estimated_remaining_tokens"] == 0
    assert budget["usage_percent"] == 100.0
    assert budget["over_budget"] is False


def test_compute_context_budget_warning_at_90_percent():
    budget = llamacpp.compute_context_budget(
        prompt_tokens=60000,
        completion_tokens=60000,
        max_output_tokens=8192,
        context_window=131072,
    )
    assert budget["usage_percent"] > 90.0
    assert budget["over_budget"] is False


def test_llamacpp_call_log_isolation():
    llamacpp.reset_llamacpp_call_log()
    assert llamacpp.LLAMACPP_CALL_LOG == []

    budget1 = llamacpp.compute_context_budget(
        prompt_tokens=1000,
        completion_tokens=500,
        max_output_tokens=8192,
        context_window=131072,
    )
    llamacpp.LLAMACPP_CALL_LOG.append(budget1)
    assert len(llamacpp.LLAMACPP_CALL_LOG) == 1

    llamacpp.reset_llamacpp_call_log()
    assert llamacpp.LLAMACPP_CALL_LOG == []


def test_llamacpp_call_log_records_full_budget():
    llamacpp.reset_llamacpp_call_log()

    budget = llamacpp.compute_context_budget(
        prompt_tokens=12345,
        completion_tokens=6789,
        max_output_tokens=8192,
        context_window=131072,
    )
    llamacpp.LLAMACPP_CALL_LOG.append(budget)

    assert len(llamacpp.LLAMACPP_CALL_LOG) == 1
    recorded = llamacpp.LLAMACPP_CALL_LOG[0]
    assert recorded["prompt_tokens"] == 12345
    assert recorded["completion_tokens"] == 6789
    assert recorded["max_output_tokens"] == 8192
    assert recorded["context_window"] == 131072
    assert recorded["estimated_remaining_tokens"] == 111938
    assert recorded["usage_percent"] > 0
    assert recorded["over_budget"] is False


def test_llamacpp_call_log_tracks_multiple_calls():
    llamacpp.reset_llamacpp_call_log()

    budgets = [
        llamacpp.compute_context_budget(1000, 500, 8192, 131072),
        llamacpp.compute_context_budget(20000, 15000, 8192, 131072),
        llamacpp.compute_context_budget(80000, 60000, 8192, 131072),
    ]
    llamacpp.LLAMACPP_CALL_LOG.extend(budgets)

    assert len(llamacpp.LLAMACPP_CALL_LOG) == 3
    assert llamacpp.LLAMACPP_CALL_LOG[-1]["usage_percent"] > 100.0
    assert llamacpp.LLAMACPP_CALL_LOG[-1]["over_budget"] is True
