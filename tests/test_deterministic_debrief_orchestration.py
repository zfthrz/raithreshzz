from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import race_engineer


def test_deterministic_debrief_environment_removes_remote_credentials(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setenv("RACE_ENGINEER_DETERMINISTIC_FIRST", "0")
    monkeypatch.setenv("RACE_ENGINEER_EPISODE_DETERMINISTIC", "0")
    monkeypatch.setenv("RACE_ENGINEER_SUMMARY_DETERMINISTIC", "0")
    monkeypatch.setenv("RACE_ENGINEER_GLOBAL_DETERMINISTIC", "0")
    monkeypatch.setenv("RACE_ENGINEER_LLM_RANKER", "1")

    env = race_engineer.deterministic_debrief_subprocess_env()

    assert env["RACE_ENGINEER_DETERMINISTIC_FIRST"] == "1"
    assert env["RACE_ENGINEER_EPISODE_DETERMINISTIC"] == "1"
    assert env["RACE_ENGINEER_SUMMARY_DETERMINISTIC"] == "1"
    assert env["RACE_ENGINEER_GLOBAL_DETERMINISTIC"] == "1"
    assert env["RACE_ENGINEER_LLM_RANKER"] == "0"
    assert "DEEPSEEK_API_KEY" not in env
    assert os.environ["DEEPSEEK_API_KEY"] == "secret"


def test_force_deterministic_debrief_parser_contract():
    parser = race_engineer.build_parser()

    args = parser.parse_args([
        "analyze",
        "session.duckdb",
        "--force-deterministic-debrief",
    ])

    assert args.force_deterministic_debrief is True
    assert args.backend is None
    assert args.no_historical_context is False


@pytest.mark.parametrize("backend", ["ollama", "llamacpp"])
def test_force_deterministic_debrief_rejects_non_deepseek_before_file_access(backend):
    parser = race_engineer.build_parser()
    args = parser.parse_args([
        "analyze",
        "missing.duckdb",
        "--backend",
        backend,
        "--force-deterministic-debrief",
    ])

    with pytest.raises(ValueError, match="renderizador determinista heredado"):
        race_engineer.analyze_command(args)


def test_force_deterministic_debrief_allows_historical_context():
    parser = race_engineer.build_parser()
    args = parser.parse_args([
        "analyze",
        "missing.duckdb",
        "--force-deterministic-debrief",
    ])

    with pytest.raises(FileNotFoundError):
        race_engineer.analyze_command(args)


def test_force_deterministic_debrief_disables_historical_llm_in_source():
    source = open(race_engineer.__file__, encoding="utf-8").read()
    assert "if args.no_llm or deterministic_debrief:" in source
    assert "narrativa histórica LLM deshabilitada" in source


def test_default_analyze_route_has_no_public_backend_requirement():
    args = race_engineer.build_parser().parse_args(["analyze", "session.duckdb"])

    assert args.backend is None


def test_deterministic_artifact_reuse_requires_zero_model_calls(tmp_path: Path):
    analysis = tmp_path / "analysis.json"
    analysis.write_text("{}", encoding="utf-8")
    artifact = tmp_path / "debrief.json"
    metadata = {
        "source_json": str(analysis),
        "llm_analysis_version": "3.10.8.5.4",
        "model": race_engineer.llm_model_name("deepseek"),
        "structured_validation": "PASS",
        "factual_grounding_validation": "PASS",
        "deepseek_usage": {"http_request_count": 0},
    }
    artifact.write_text(json.dumps({"metadata": metadata}), encoding="utf-8")

    assert race_engineer.deterministic_debrief_artifact_matches_run(
        artifact, analysis
    )

    metadata["deepseek_usage"]["http_request_count"] = 1
    artifact.write_text(json.dumps({"metadata": metadata}), encoding="utf-8")
    assert not race_engineer.deterministic_debrief_artifact_matches_run(
        artifact, analysis
    )
