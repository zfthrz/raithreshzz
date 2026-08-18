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


def test_llamacpp_aliases_match_versioned_sources():
    alias_hash = hashlib.sha256(
        (ROOT / "llm_analysis_llamacpp.py").read_bytes()
    ).digest()
    source_hash = hashlib.sha256(
        (ROOT / "llm_analysis_v3_10_8_5_4_llamacpp.py").read_bytes()
    ).digest()
    assert alias_hash == source_hash


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
    assert 'backend == "llamacpp"' in selection
