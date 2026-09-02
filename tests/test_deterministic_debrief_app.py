from __future__ import annotations

import ast
import inspect

import deterministic_debrief_app as app
import llm_analysis_deepseek as legacy


def test_product_stage_audit_has_no_historical_dependency():
    providers = app.build_stage_providers(
        base_dir="unused",
        save_result=lambda *args: None,
    )

    assert set(app.STAGE_PROVIDER_CLASSIFICATION) == set(providers.__dataclass_fields__)
    assert set(app.STAGE_PROVIDER_CLASSIFICATION.values()) == {
        "neutral_direct",
        "neutral_wrapper",
        "compatibility_wrapper",
    }
    for name in providers.__dataclass_fields__:
        provider = getattr(providers, name)
        assert provider.__module__ != "llm_analysis_deepseek", name


def test_neutral_app_does_not_import_historical_backend():
    tree = ast.parse(inspect.getsource(app))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert "llm_analysis_deepseek" not in imports


def test_historical_runtime_builder_uses_neutral_assembler(monkeypatch):
    for name in (
        "_stage_prepare_input",
        "_stage_prepare_comparison",
        "_stage_execute_comparison",
        "_stage_get_global_response",
        "_stage_finalize_global",
    ):
        monkeypatch.setattr(
            legacy,
            name,
            lambda *args, _name=name, **kwargs: (_ for _ in ()).throw(
                AssertionError(f"historical wrapper reached: {_name}")
            ),
        )

    stages, presentation = legacy._build_debrief_runtime("unused-output")

    assert stages.prepare_comparison is app.prepare_comparison
    assert stages.finalize_global is app.finalize_global
    assert callable(stages.execute_comparison)
    assert callable(presentation.complete)
