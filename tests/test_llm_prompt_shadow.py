from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_prompt_shadow_policy import (
    SHADOW_AUTHORITY,
    SHADOW_PROMPT_POLICY_VERSION,
    build_shadow_episode_system_prompt,
    prompt_sha256,
)
from run_llm_prompt_shadow import (
    build_run_plan,
    configure_utf8_output,
    configure_shadow_module,
    main,
)


def test_shadow_prompt_preserves_production_prompt_and_adds_closed_preflight():
    production = "PRODUCTION CONTRACT\n"

    shadow = build_shadow_episode_system_prompt(production)

    assert shadow.startswith("PRODUCTION CONTRACT")
    assert "SHADOW PREFLIGHT DE GROUNDING" in shadow
    assert "channel_direction_contract" in shadow
    assert "La vuelta de REFERENCIA" in shadow
    assert "hypotheses vacía" in shadow
    assert prompt_sha256(shadow) == prompt_sha256(shadow)


def test_empty_production_prompt_is_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        build_shadow_episode_system_prompt("  ")


def test_utf8_output_configuration_handles_windows_legacy_streams():
    class FakeStream:
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    stdout = FakeStream()
    stderr = FakeStream()

    configure_utf8_output(stdout, stderr, object())

    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_run_plan_is_backend_scoped_and_hashes_source(tmp_path: Path):
    source = tmp_path / "session.json"
    source.write_text('{"metadata": {}}', encoding="utf-8")

    plan = build_run_plan(source, "deepseek", tmp_path / "shadow")

    assert plan.input_path == source.resolve()
    assert plan.module_name == "llm_analysis_deepseek"
    assert plan.policy == SHADOW_PROMPT_POLICY_VERSION
    assert plan.output_dir == (
        tmp_path / "shadow" / SHADOW_PROMPT_POLICY_VERSION / "deepseek" / "session"
    ).resolve()
    assert len(plan.source_sha256) == 64
    assert plan.model_override is None
    assert plan.api_model_override is None


def test_model_override_is_recorded_and_scopes_output_directory(tmp_path: Path):
    source = tmp_path / "session.json"
    source.write_text("{}", encoding="utf-8")

    plan = build_run_plan(
        source,
        "llamacpp",
        tmp_path / "shadow",
        model_override="Qwen_Qwen3.6-35B-A3B-IQ2_M.gguf",
    )

    assert plan.model_override == "Qwen_Qwen3.6-35B-A3B-IQ2_M.gguf"
    assert plan.output_dir.parent.name == "qwen-qwen3-6-35b-a3b-iq2-m-gguf"


def test_configured_module_redirects_output_and_marks_shadow_metadata(tmp_path: Path):
    source = tmp_path / "session.json"
    source.write_text("{}", encoding="utf-8")
    plan = build_run_plan(source, "ollama", tmp_path / "shadow")

    def fake_save_result(*_args, **_kwargs):
        plan.output_dir.mkdir(parents=True, exist_ok=True)
        output = plan.output_dir / "result.json"
        output.write_text('{"metadata": {"model": "local"}}', encoding="utf-8")
        return str(output), str(plan.output_dir)

    module = SimpleNamespace(
        EPISODE_SYSTEM_PROMPT="BASE PROMPT",
        MODEL_NAME="old-model",
        save_result=fake_save_result,
    )

    prompt_hash = configure_shadow_module(module, plan)
    result = module.save_result()
    payload = json.loads(Path(result[0]).read_text(encoding="utf-8"))

    assert "SHADOW PREFLIGHT DE GROUNDING" in module.EPISODE_SYSTEM_PROMPT
    assert module.llm_result_dir("ignored") == plan.output_dir
    assert module.llm_debug_dir("ignored", backend="legacy-label") == plan.debug_dir
    assert payload["metadata"]["backend"] == "ollama"
    assert payload["metadata"]["prompt_shadow"] == {
        "runner_version": "0.1",
        "policy": SHADOW_PROMPT_POLICY_VERSION,
        "authority": SHADOW_AUTHORITY,
        "episode_prompt_sha256": prompt_hash,
        "source_json_sha256": plan.source_sha256,
        "model_override": None,
        "api_model_override": None,
        "production_output_modified": False,
    }


def test_configured_module_applies_explicit_model_override(tmp_path: Path):
    source = tmp_path / "session.json"
    source.write_text("{}", encoding="utf-8")
    plan = build_run_plan(
        source,
        "llamacpp",
        tmp_path / "shadow",
        model_override="Qwen_Qwen3.6-35B-A3B-IQ2_M.gguf",
    )
    module = SimpleNamespace(
        EPISODE_SYSTEM_PROMPT="BASE PROMPT",
        MODEL_NAME="qwen3-14b",
        save_result=lambda: (str(tmp_path / "missing.json"), str(tmp_path)),
    )

    configure_shadow_module(module, plan)

    assert module.MODEL_NAME == "Qwen_Qwen3.6-35B-A3B-IQ2_M.gguf"


def test_llamacpp_api_model_is_used_only_during_transport(tmp_path: Path):
    source = tmp_path / "session.json"
    source.write_text("{}", encoding="utf-8")
    plan = build_run_plan(
        source,
        "llamacpp",
        tmp_path / "shadow",
        model_override="qwen3.6-35b-a3b-iq2_m",
        api_model_override=r"C:\llama.cpp\models\Qwen_Qwen3.6-35B-A3B-IQ2_M.gguf",
    )
    observed_models = []
    module = SimpleNamespace(
        EPISODE_SYSTEM_PROMPT="BASE PROMPT",
        MODEL_NAME="qwen3-14b",
        llamacpp_chat=lambda: observed_models.append(module.MODEL_NAME) or {"ok": True},
        save_result=lambda: (str(tmp_path / "missing.json"), str(tmp_path)),
    )

    configure_shadow_module(module, plan)
    response = module.llamacpp_chat()

    assert response == {"ok": True}
    assert observed_models == [r"C:\llama.cpp\models\Qwen_Qwen3.6-35B-A3B-IQ2_M.gguf"]
    assert module.MODEL_NAME == "qwen3.6-35b-a3b-iq2_m"


def test_plan_only_calls_no_backend_and_writes_nothing(tmp_path: Path, monkeypatch, capsys):
    source = tmp_path / "session.json"
    source.write_text("{}", encoding="utf-8")
    output_root = tmp_path / "shadow"

    def forbidden_import(_name):
        raise AssertionError("plan-only mode must not import or call a backend")

    monkeypatch.setattr("run_llm_prompt_shadow.importlib.import_module", forbidden_import)

    result = main(
        [
            str(source),
            "--backend",
            "llamacpp",
            "--output-root",
            str(output_root),
        ]
    )

    assert result == 0
    assert not output_root.exists()
    output = capsys.readouterr().out
    assert "Mode: PLAN_ONLY" in output
    assert "no LLM called and no files written" in output


def test_execute_blocks_existing_shadow_without_force(tmp_path: Path, monkeypatch, capsys):
    source = tmp_path / "session.json"
    source.write_text("{}", encoding="utf-8")
    output_root = tmp_path / "shadow"
    plan = build_run_plan(source, "deepseek", output_root)
    plan.output_dir.mkdir(parents=True)
    (plan.output_dir / "existing.json").write_text("{}", encoding="utf-8")

    def forbidden_import(_name):
        raise AssertionError("blocked execution must not import or call a backend")

    monkeypatch.setattr("run_llm_prompt_shadow.importlib.import_module", forbidden_import)

    result = main(
        [
            str(source),
            "--backend",
            "deepseek",
            "--output-root",
            str(output_root),
            "--execute",
        ]
    )

    assert result == 2
    assert "BLOCKED_EXISTING_SHADOW_OUTPUT" in capsys.readouterr().out
