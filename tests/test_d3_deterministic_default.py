from __future__ import annotations

import json
from pathlib import Path

import llm_analysis_deepseek as deepseek_module


ROOT = Path(__file__).resolve().parents[1]

METADATA = {}
COMPARISON = {"reference_lap": 1, "comparison_lap": 2}
CATALOG = [
    {
        "episode_id": 1,
        "action_channels": ["brake"],
        "action_evidence_by_channel": {"brake": {}},
    }
]
ASSESSMENTS = [
    {
        "episode_id": 1,
        "classification": "PRIORITARIO",
        "interpretation": "frená más tarde",
        "recommendation": "frená más tarde",
    }
]
RECONSTRUCTABLE = {
    "episode_id": 1,
    "action_channels": ["brake"],
    "action_evidence_by_channel": {
        "brake": {"events": [{"direction": "lower_in_comparison_lap"}]}
    },
}
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


def _clean_env(monkeypatch):
    for name in (
        "RACE_ENGINEER_DETERMINISTIC_FIRST",
        "RACE_ENGINEER_EPISODE_DETERMINISTIC",
        "RACE_ENGINEER_SUMMARY_DETERMINISTIC",
        "RACE_ENGINEER_GLOBAL_DETERMINISTIC",
    ):
        monkeypatch.delenv(name, raising=False)


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("no debería llamarse al LLM en modo determinista")


def test_master_default_enables_all_three_without_llm(
    tmp_path: Path, monkeypatch
):
    _clean_env(monkeypatch)
    monkeypatch.setattr(deepseek_module, "deepseek_chat", _fail_if_called)

    episode = deepseek_module.get_validated_episode_response(
        METADATA,
        COMPARISON,
        RECONSTRUCTABLE,
        tmp_path,
    )
    summary = deepseek_module.get_validated_comparison_summary_response(
        ASSESSMENTS,
        CATALOG,
        COMPARISON,
        tmp_path,
    )
    global_response = deepseek_module.get_validated_global_response(
        METADATA,
        VALID_COMPARISON_RESULTS,
        FACTS,
        tmp_path,
    )

    assert episode["status"] == "VALID"
    assert episode["deterministic_first"] is True
    assert summary["status"] == "VALID"
    assert summary["deterministic_first"] is True
    assert global_response["status"] == "VALID"
    assert global_response["deterministic_first"] is True


def test_master_zero_disables_default_but_per_flag_still_enables(
    tmp_path: Path, monkeypatch
):
    _clean_env(monkeypatch)
    monkeypatch.setenv("RACE_ENGINEER_DETERMINISTIC_FIRST", "0")
    monkeypatch.setenv("RACE_ENGINEER_SUMMARY_DETERMINISTIC", "1")
    monkeypatch.setattr(deepseek_module, "deepseek_chat", _fail_if_called)

    episode = deepseek_module.get_validated_episode_response(
        METADATA,
        COMPARISON,
        RECONSTRUCTABLE,
        tmp_path,
    )
    summary = deepseek_module.get_validated_comparison_summary_response(
        ASSESSMENTS,
        CATALOG,
        COMPARISON,
        tmp_path,
    )

    # Con master=0 y sin flag específico, el episodio vuelve a LLM-first;
    # el summary con flag "1" sigue determinista.
    assert episode["status"] == "VALID"
    assert episode.get("deterministic_first") is not True
    assert summary["status"] == "VALID"
    assert summary["deterministic_first"] is True


def test_per_flag_zero_overrides_master_default(
    tmp_path: Path, monkeypatch
):
    _clean_env(monkeypatch)
    monkeypatch.setenv("RACE_ENGINEER_SUMMARY_DETERMINISTIC", "0")

    valid_summary = deepseek_module.build_deterministic_comparison_summary(
        ASSESSMENTS,
        CATALOG,
    )
    calls = []

    def llm_summary(*_args, **_kwargs):
        calls.append(True)
        return json.dumps(valid_summary, ensure_ascii=False)

    monkeypatch.setattr(deepseek_module, "deepseek_chat", llm_summary)

    episode = deepseek_module.get_validated_episode_response(
        METADATA,
        COMPARISON,
        RECONSTRUCTABLE,
        tmp_path,
    )
    summary = deepseek_module.get_validated_comparison_summary_response(
        ASSESSMENTS,
        CATALOG,
        COMPARISON,
        tmp_path,
    )

    # El master default sigue activo para episodio; summary con flag "0" llama LLM.
    assert episode["deterministic_first"] is True
    assert calls
    assert summary["status"] == "VALID"
    assert summary["response"]["conclusion"] == "frená más tarde"


def test_all_backends_declare_master_switch():
    for relative in (
        "llm_analysis_deepseek.py",
        "llm_analysis_llamacpp.py",
        "llm_analysis.py",
        "llm_analysis_ingenierov3.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "RACE_ENGINEER_DETERMINISTIC_FIRST" in source
        assert "deterministic_first_enabled" in source
        assert 'os.environ.get("RACE_ENGINEER_DETERMINISTIC_FIRST", "1")' in source
