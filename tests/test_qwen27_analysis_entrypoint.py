from __future__ import annotations

import llm_analysis
import llm_analysis_qwen3_8_27b_iq3m as qwen27


def test_qwen27_entrypoint_selects_isolated_ollama_alias(monkeypatch):
    called = []
    original_model = llm_analysis.MODEL_NAME

    def fake_main():
        called.append(llm_analysis.MODEL_NAME)

    monkeypatch.setattr(llm_analysis, "main", fake_main)
    try:
        qwen27.main()
    finally:
        llm_analysis.MODEL_NAME = original_model

    assert called == ["qwen38-27b-iq3m"]
    assert qwen27.MODEL_NAME != "ingenierov3"
