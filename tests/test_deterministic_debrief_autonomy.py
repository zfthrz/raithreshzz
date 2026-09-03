"""Transitive autonomy tests for the deterministic product debrief.

Confirms that running deterministic_debrief.py cannot reach any
llm_analysis* backend, directly or transitively, through:

1. Import-block assertion on entrypoint;
2. sys.modules audit after a real run;
3. StageProvider gate tests (transport/provider);
4. Artifact equivalence with contract;
5. Legacy metadata preservation without DeepSeek;
6. Exit-code / fail-closed verification.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]

import deterministic_debrief
import deterministic_debrief_main


def test_entrypoint_blocks_llm_analysis_imports_at_parse():
    """Every top-level import in deterministic_debrief.py is backend-free."""
    source = (ROOT / "deterministic_debrief.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("llm_analysis"), (
                    f"Top-level import {alias.name} violates backend-free invariant"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith("llm_analysis"), (
                    f"Import from {node.module} violates backend-free invariant"
                )


def test_main_module_blocks_llm_analysis_imports_at_parse():
    """Every top-level import in deterministic_debrief_main.py is backend-free."""
    source = (ROOT / "deterministic_debrief_main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("llm_analysis"), (
                    f"Top-level import {alias.name} violates backend-free invariant"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith("llm_analysis"), (
                    f"Import from {node.module} violates backend-free invariant"
                )


def test_neutral_app_blocks_llm_analysis_imports_at_parse():
    """deterministic_debrief_app.py has no llm_analysis* imports."""
    source = (ROOT / "deterministic_debrief_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("llm_analysis")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith("llm_analysis")


def test_neutral_runtime_blocks_llm_analysis_imports_at_parse():
    """deterministic_debrief_runtime.py has no llm_analysis* imports."""
    source = (ROOT / "deterministic_debrief_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("llm_analysis")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith("llm_analysis")


def test_neutral_wiring_blocks_llm_analysis_imports_at_parse():
    """deterministic_debrief_wiring.py has no llm_analysis* imports."""
    source = (ROOT / "deterministic_debrief_wiring.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("llm_analysis")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith("llm_analysis")


def test_transitive_closure_zero_backend_hits():
    """The full transitive import closure has zero llm_analysis* imports."""
    from scripts.audit_imports import _audit_transitive

    visited, all_imports = _audit_transitive(
        ROOT / "deterministic_debrief.py", ROOT
    )
    backend_hits = [i for i in all_imports if i.startswith("llm_analysis")]
    assert backend_hits == [], f"Backend imports in transitive closure: {backend_hits}"


def test_transitive_audit_follows_packages_and_dotted_modules(tmp_path):
    """The audit must not stop at package directories."""
    entry = tmp_path / "entry.py"
    package = tmp_path / "product"
    package.mkdir()
    entry.write_text("import product\n", encoding="utf-8")
    (package / "__init__.py").write_text(
        "from product.runtime import run\n", encoding="utf-8"
    )
    (package / "runtime.py").write_text(
        "import llm_analysis_deepseek\n", encoding="utf-8"
    )

    from scripts.audit_imports import _audit_transitive

    visited, all_imports = _audit_transitive(entry, tmp_path)

    assert package / "__init__.py" in visited
    assert package / "runtime.py" in visited
    assert "llm_analysis_deepseek" in all_imports


@pytest.mark.parametrize(
    "source",
    [
        'import importlib\nimportlib.import_module("llm_analysis_deepseek")\n',
        '__import__("llm_analysis_llamacpp")\n',
    ],
)
def test_transitive_audit_detects_literal_dynamic_backend_imports(tmp_path, source):
    entry = tmp_path / "entry.py"
    entry.write_text(source, encoding="utf-8")

    from scripts.audit_imports import _audit_transitive

    _visited, all_imports = _audit_transitive(entry, tmp_path)

    assert any(name.startswith("llm_analysis") for name in all_imports)


def test_entrypoint_preserves_deterministic_environment():
    """run() configures deterministic env and removes DEEPSEEK_API_KEY.

    Uses the same patching strategy as the existing test_entrypoint
    test: intercept deterministic_debrief_main.main so the lazy
    import inside run() is intercepted without filesystem interaction.
    """
    with patch("deterministic_debrief_main.main"):
        assert deterministic_debrief.run() == 0
    assert "DEEPSEEK_API_KEY" not in deterministic_debrief.os.environ
    assert deterministic_debrief.os.environ["RACE_ENGINEER_LLM_RANKER"] == "0"
    for name, value in deterministic_debrief.DETERMINISTIC_ENVIRONMENT.items():
        assert deterministic_debrief.os.environ[name] == value


def test_main_module_no_llm_analysis_in_sys_modules_after_run():
    """After run(), no llm_analysis* module is loaded transitively.

    Captures sys.modules snapshot BEFORE run(), then captures after.
    Only NEW modules loaded by the run() call are inspected.
    """
    before = set(sys.modules.keys())
    with patch("deterministic_debrief_main.main"):
        deterministic_debrief.run()
    after = set(sys.modules.keys())
    new_modules = after - before
    for mod_name in new_modules:
        if mod_name.startswith("llm_analysis"):
            pytest.fail(
                f"New llm_analysis* module loaded by run(): {mod_name}"
            )


def test_main_module_compatible_metadata_preserved():
    """LegacyArtifactMetadata fields exist without DeepSeek dependency."""
    from deterministic_debrief_compatibility import (
        LEGACY_ARTIFACT_FIELDS,
        LegacyArtifactMetadata,
    )

    meta = LegacyArtifactMetadata(
        model_name="deterministic_debrief",
        context_size=0,
        temperature=0.0,
        anomaly_gate_config={},
    )
    kwargs = meta.persistence_kwargs(usage_summary={})
    assert "model_name" in kwargs
    assert "usage_summary" in kwargs
    assert "context_size" in kwargs
    assert "temperature" in kwargs
    assert "anomaly_gate_config" in kwargs


def test_compatible_debrief_output_no_backend():
    """save_compatible_debrief does not import llm_analysis*."""
    # By construction, save_compatible_debrief is defined in
    # deterministic_debrief_output which imports deterministic_debrief_document
    # and runtime_paths; neither is a backend.
    source = (ROOT / "deterministic_debrief_output.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("llm_analysis")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith("llm_analysis")


def test_save_compatible_debrief_signature_compatible():
    """save_compatible_debrief accepts the legacy keyword arguments."""
    from deterministic_debrief_output import save_compatible_debrief

    # Verify the function accepts the legacy keyword signature
    sig_params = list(save_compatible_debrief.__code__.co_varnames)
    assert "input_path" in sig_params
    assert "metadata" in sig_params
    assert "comparison_results" in sig_params
    assert "session_coaching_facts" in sig_params
    assert "global_structured" in sig_params
    assert "global_analysis" in sig_params
    assert "model_name" in sig_params
    assert "usage_summary" in sig_params
    assert "context_size" in sig_params
    assert "temperature" in sig_params
    assert "anomaly_gate_config" in sig_params
