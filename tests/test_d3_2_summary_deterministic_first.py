from __future__ import annotations

from pathlib import Path

import llm_analysis_deepseek as deepseek_module


ROOT = Path(__file__).resolve().parents[1]

CATALOG = [
    {
        "episode_id": 1,
        "action_channels": ["brake"],
        "action_evidence_by_channel": {"brake": {}},
    }
]
ASSESSMENTS = [
    {
        "episode_id": 1,
        "classification": "PRIORITARIO",
        "interpretation": "frená más tarde",
        "recommendation": "frená más tarde",
    }
]
COMPARISON = {"reference_lap": 1, "comparison_lap": 2}


def test_deterministic_summary_is_contract_valid():
    summary = deepseek_module.build_deterministic_comparison_summary(
        ASSESSMENTS,
        CATALOG,
    )

    assert summary is not None
    assert deepseek_module.validate_comparison_summary_llm_response(
        summary, CATALOG
    ) == []


def test_deterministic_first_skips_llm(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_SUMMARY_DETERMINISTIC", "1")
    called = []

    def fail_if_called(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("no debería llamarse al LLM en modo deterministic-first")

    monkeypatch.setattr(deepseek_module, "deepseek_chat", fail_if_called)

    result = deepseek_module.get_validated_comparison_summary_response(
        ASSESSMENTS,
        CATALOG,
        COMPARISON,
        tmp_path,
    )

    assert result["status"] == "VALID"
    assert result["deterministic"] is True
    assert result["deterministic_first"] is True
    assert result["attempts"] == 0
    assert called == []
    assert result["response"]["conclusion"] == "frená más tarde"


def test_transport_failure_falls_back_to_deterministic(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_DETERMINISTIC_FIRST", "0")
    monkeypatch.delenv("RACE_ENGINEER_SUMMARY_DETERMINISTIC", raising=False)

    def raise_transport(*_args, **_kwargs):
        raise RuntimeError("backend caído")

    monkeypatch.setattr(deepseek_module, "deepseek_chat", raise_transport)

    result = deepseek_module.get_validated_comparison_summary_response(
        ASSESSMENTS,
        CATALOG,
        COMPARISON,
        tmp_path,
    )

    assert result["status"] == "VALID"
    assert result["fallback"] == "DETERMINISTIC_FROM_VALIDATED_EPISODES"
    assert result["response"]["conclusion"] == "frená más tarde"


def test_all_backends_declare_deterministic_first_summary():
    for relative in (
        "llm_analysis_deepseek.py",
        "llm_analysis_llamacpp.py",
        "llm_analysis.py",
        "llm_analysis_ingenierov3.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "RACE_ENGINEER_SUMMARY_DETERMINISTIC" in source
        assert '"deterministic_first": True' in source
        assert "transporte LLM falló" in source
