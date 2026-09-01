from __future__ import annotations

from types import ModuleType

import pytest

import deterministic_debrief
import race_engineer


def test_entrypoint_forces_all_gates_and_blocks_transport(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    for name in deterministic_debrief.DETERMINISTIC_ENVIRONMENT:
        monkeypatch.setenv(name, "0" if name != "RACE_ENGINEER_LLM_RANKER" else "1")

    renderer = ModuleType("fake_legacy_renderer")
    renderer.deepseek_chat = lambda *args, **kwargs: "network"
    called = []

    def fake_main():
        called.append(True)
        with pytest.raises(RuntimeError, match="transport is disabled"):
            renderer.deepseek_chat("system", "user")

    renderer.main = fake_main

    assert deterministic_debrief.run(renderer) == 0
    assert called == [True]
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
