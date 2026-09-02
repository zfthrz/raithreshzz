from __future__ import annotations

from pathlib import Path

from deterministic_debrief_wiring import StageProviders, bind_stages


ROOT = Path(__file__).resolve().parents[1]


def test_wiring_has_no_backend_import():
    source = (ROOT / "deterministic_debrief_wiring.py").read_text(encoding="utf-8")
    assert "llm_analysis" not in source
    assert "deepseek_chat" not in source


def test_wiring_binds_output_dir_only_to_relevant_stages():
    calls = []

    def marker(name):
        return lambda *args: calls.append((name, args)) or name

    providers = StageProviders(
        prepare_input=marker("prepare"),
        build_quality_gate=marker("gate"),
        quality_by_key=marker("quality"),
        prepare_comparison=marker("prepare_comparison"),
        require_detected=marker("require"),
        execute_comparison=marker("execute"),
        build_session_facts=marker("facts"),
        get_global_response=marker("global"),
        finalize_global=marker("finalize"),
        save_result=marker("save"),
    )
    stages = bind_stages(providers, output_dir="DEBUG")
    assert stages.execute_comparison("comparison", "prepared", "metadata") == "execute"
    assert stages.get_global_response("metadata", "results", "facts") == "global"
    assert calls == [
        ("execute", ("comparison", "prepared", "metadata", "DEBUG")),
        ("global", ("metadata", "results", "facts", "DEBUG")),
    ]
