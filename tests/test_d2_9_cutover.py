from __future__ import annotations

import json
from pathlib import Path

import llm_analysis_deepseek as deepseek_module


ROOT = Path(__file__).resolve().parents[1]

COMPARISON = {"reference_lap": 1, "comparison_lap": 2}
CATALOG = [
    {
        "episode_id": 1,
        "global_rank": 1,
        "action_time_loss_s": 0.6,
        "evidence_strength": "strong",
        "action_channels": ["brake"],
        "action_evidence_by_channel": {
            "brake": {"events": [{"direction": "lower_in_comparison_lap"}]}
        },
    },
    {
        "episode_id": 2,
        "global_rank": 2,
        "action_time_loss_s": 0.1,
        "evidence_strength": "moderate",
        "action_channels": ["brake"],
        "action_evidence_by_channel": {
            "brake": {"events": [{"direction": "lower_in_comparison_lap"}]}
        },
    },
    {
        "episode_id": 3,
        "global_rank": 3,
        "action_time_loss_s": 0.02,
        "evidence_strength": "weak",
        "action_channels": ["steering_magnitude"],
        "action_evidence_by_channel": {},
    },
]


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("no debería llamarse al LLM con el ranker determinista")


def _clean_ranker_env(monkeypatch):
    monkeypatch.delenv("RACE_ENGINEER_LLM_RANKER", raising=False)


def test_ranker_deterministic_by_default_without_llm(
    tmp_path: Path, monkeypatch
):
    _clean_ranker_env(monkeypatch)
    monkeypatch.setattr(deepseek_module, "deepseek_chat", _fail_if_called)

    result = deepseek_module.get_validated_comparison_ranker_response(
        CATALOG,
        [],
        COMPARISON,
        tmp_path,
    )

    assert result["status"] == "VALID"
    assert result["attempts"] == 0
    assert result["deterministic"] is True
    assert result["ranker_source"] == "D2_9_PRODUCT_POLICY"
    assert result["response"]["priority_cut_rank"] == 1
    assert result["response"]["no_actionable_start_rank"] == 3


def test_ranker_rollback_flag_restores_llm_rank(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_LLM_RANKER", "1")
    calls = []

    def llm_ranker(*_args, **_kwargs):
        calls.append(True)
        return json.dumps(
            {
                "ordered_episode_ids": [2, 1, 3],
                "priority_cut_rank": 1,
                "no_actionable_start_rank": 4,
            }
        )

    monkeypatch.setattr(deepseek_module, "deepseek_chat", llm_ranker)

    result = deepseek_module.get_validated_comparison_ranker_response(
        CATALOG,
        [],
        COMPARISON,
        tmp_path,
    )

    assert calls
    assert result["status"] == "VALID"
    assert result["attempts"] == 1
    assert result["response"]["ordered_episode_ids"] == [2, 1, 3]


def test_all_backends_declare_d2_9_cutover():
    for relative in (
        "llm_analysis_deepseek.py",
        "llm_analysis_llamacpp.py",
        "llm_analysis.py",
        "llm_analysis_ingenierov3.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "RACE_ENGINEER_LLM_RANKER" in source
        assert "llm_ranker_enabled" in source
        assert "build_product_priority_ranker_response" in source
        assert '"ranker_source": "D2_9_PRODUCT_POLICY"' in source
