from __future__ import annotations

from pathlib import Path

import llm_analysis_deepseek as deepseek_module


ROOT = Path(__file__).resolve().parents[1]

FACTS = {
    "next_stint_plan": [
        {
            "plan_label": "A",
            "kind": "repeated_region",
            "targets": ["reducir el freno"],
            "observed_differences": ["más freno"],
        }
    ]
}
VALID_COMPARISON_RESULTS = [
    {
        "episode_ground_truth": [
            {
                "episode_id": 1,
                "action_channels": ["brake"],
                "action_evidence_by_channel": {"brake": {}},
            }
        ]
    }
]
METADATA = {}


def test_global_deterministic_fallback_is_contract_valid():
    fallback = deepseek_module.build_deterministic_global_fallback(FACTS)

    assert fallback is not None
    assert (
        deepseek_module.validate_global_llm_response(
            fallback,
            VALID_COMPARISON_RESULTS,
            FACTS,
        )
        == []
    )


def test_global_deterministic_first_skips_llm(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_GLOBAL_DETERMINISTIC", "1")
    called = []

    def fail_if_called(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("no debería llamarse al LLM en modo deterministic-first")

    monkeypatch.setattr(deepseek_module, "deepseek_chat", fail_if_called)

    result = deepseek_module.get_validated_global_response(
        METADATA,
        VALID_COMPARISON_RESULTS,
        FACTS,
        tmp_path,
    )

    assert result["status"] == "VALID"
    assert result["deterministic"] is True
    assert result["deterministic_first"] is True
    assert result["attempts"] == 0
    assert called == []
    assert "conclusion" in result["response"]
    assert "next_session_priorities" in result["response"]


def test_global_transport_failure_falls_back_to_deterministic(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_DETERMINISTIC_FIRST", "0")
    monkeypatch.delenv("RACE_ENGINEER_GLOBAL_DETERMINISTIC", raising=False)

    def raise_transport(*_args, **_kwargs):
        raise RuntimeError("backend caído")

    monkeypatch.setattr(deepseek_module, "deepseek_chat", raise_transport)

    result = deepseek_module.get_validated_global_response(
        METADATA,
        VALID_COMPARISON_RESULTS,
        FACTS,
        tmp_path,
    )

    assert result["status"] == "VALID"
    assert result["fallback"] == "DETERMINISTIC_GLOBAL_FROM_NEXT_STINT_PLAN"
    assert result["response"]["conclusion"].startswith("Empezá la próxima tanda")


def test_all_backends_declare_global_deterministic_first():
    for relative in (
        "llm_analysis_deepseek.py",
        "llm_analysis_llamacpp.py",
        "llm_analysis.py",
        "llm_analysis_ingenierov3.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "RACE_ENGINEER_GLOBAL_DETERMINISTIC" in source
        assert '"deterministic_first": True' in source
        assert "transporte LLM falló" in source
        assert "build_deterministic_global_fallback" in source
