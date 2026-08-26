from __future__ import annotations

from pathlib import Path

import llm_analysis_deepseek as deepseek_module


ROOT = Path(__file__).resolve().parents[1]

METADATA = {}
COMPARISON = {"reference_lap": 1, "comparison_lap": 2}
RECONSTRUCTABLE = {
    "episode_id": 1,
    "action_channels": ["brake"],
    "action_evidence_by_channel": {
        "brake": {"events": [{"direction": "lower_in_comparison_lap"}]}
    },
}
INTERPRETIVE = {
    "episode_id": 2,
    "action_channels": ["unknown_channel"],
    "action_evidence_by_channel": {},
}


def test_deterministic_first_uses_grounded_fallback_for_safe_episodes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_EPISODE_DETERMINISTIC", "1")
    called = []

    def fail_if_called(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("no debería llamarse al LLM en modo deterministic-first")

    monkeypatch.setattr(deepseek_module, "deepseek_chat", fail_if_called)

    result = deepseek_module.get_validated_episode_response(
        METADATA,
        COMPARISON,
        RECONSTRUCTABLE,
        tmp_path,
    )

    assert result["status"] == "VALID"
    assert result["deterministic"] is True
    assert result["deterministic_first"] is True
    assert result["attempts"] == 0
    assert called == []
    assert result["response"]["episode_id"] == 1
    assert "freno menor" in result["response"]["interpretation"]


def test_deterministic_first_rejects_genuinely_interpretive_episodes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_EPISODE_DETERMINISTIC", "1")
    called = []

    def fail_if_called(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("no debería llamarse al LLM en modo deterministic-first")

    monkeypatch.setattr(deepseek_module, "deepseek_chat", fail_if_called)

    result = deepseek_module.get_validated_episode_response(
        METADATA,
        COMPARISON,
        INTERPRETIVE,
        tmp_path,
    )

    assert result["status"] == "REJECTED"
    assert called == []
    assert "genuinamente interpretativo" in result["validation_errors"][0]


def test_transport_failure_falls_back_to_deterministic_for_safe_episodes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_DETERMINISTIC_FIRST", "0")
    monkeypatch.delenv("RACE_ENGINEER_EPISODE_DETERMINISTIC", raising=False)

    def raise_transport(*_args, **_kwargs):
        raise RuntimeError("backend caído")

    monkeypatch.setattr(deepseek_module, "deepseek_chat", raise_transport)

    result = deepseek_module.get_validated_episode_response(
        METADATA,
        COMPARISON,
        RECONSTRUCTABLE,
        tmp_path,
    )

    assert result["status"] == "VALID"
    assert result["fallback"] == "DETERMINISTIC_GROUNDED_EPISODE_TEXT"
    assert result["response"]["episode_id"] == 1


def test_all_backends_declare_episode_deterministic_first():
    for relative in (
        "llm_analysis_deepseek.py",
        "llm_analysis_llamacpp.py",
        "llm_analysis.py",
        "llm_analysis_ingenierov3.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "RACE_ENGINEER_EPISODE_DETERMINISTIC" in source
        assert '"deterministic_first": True' in source
        assert "transporte LLM falló" in source
        assert "build_deterministic_grounded_episode_fallback" in source
