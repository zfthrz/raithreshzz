from __future__ import annotations

import os

import pytest

import race_engineer


def test_deterministic_debrief_environment_removes_remote_credentials(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setenv("RACE_ENGINEER_DETERMINISTIC_FIRST", "0")
    monkeypatch.setenv("RACE_ENGINEER_LLM_RANKER", "1")

    env = race_engineer.deterministic_debrief_subprocess_env()

    assert env["RACE_ENGINEER_DETERMINISTIC_FIRST"] == "1"
    assert env["RACE_ENGINEER_LLM_RANKER"] == "0"
    assert "DEEPSEEK_API_KEY" not in env
    assert os.environ["DEEPSEEK_API_KEY"] == "secret"


def test_force_deterministic_debrief_parser_contract():
    parser = race_engineer.build_parser()

    args = parser.parse_args([
        "analyze",
        "session.duckdb",
        "--backend",
        "deepseek",
        "--force-deterministic-debrief",
    ])

    assert args.force_deterministic_debrief is True
    assert args.backend == "deepseek"
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

    with pytest.raises(ValueError, match="exige --backend deepseek"):
        race_engineer.analyze_command(args)


def test_force_deterministic_debrief_allows_historical_context():
    parser = race_engineer.build_parser()
    args = parser.parse_args([
        "analyze",
        "missing.duckdb",
        "--backend",
        "deepseek",
        "--force-deterministic-debrief",
    ])

    with pytest.raises(FileNotFoundError):
        race_engineer.analyze_command(args)


def test_force_deterministic_debrief_disables_historical_llm_in_source():
    source = open(race_engineer.__file__, encoding="utf-8").read()
    assert "if args.no_llm or args.force_deterministic_debrief:" in source
    assert "narrativa histórica LLM deshabilitada" in source
