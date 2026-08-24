from __future__ import annotations

import json
import subprocess
from pathlib import Path

from model_observability import (
    STALE_RENDER_MARKER,
    collect,
    derive_backend_model,
    parse_debug_attempts,
    run_validation,
)


def test_derive_backend_model_from_filename():
    assert derive_backend_model(
        "s_llm_analysis_v3_10_8_5_4_deepseek_v2_deepseek-v4-pro.json"
    ) == ("deepseek", "deepseek-v4-pro")
    assert derive_backend_model(
        "s_llm_analysis_v3_10_8_5_4_llamacpp_qwen3-14b.json"
    ) == ("llamacpp", "qwen3-14b")
    assert derive_backend_model(
        "s_llm_analysis_v3_10_8_5_4_ingenierov3.json"
    ) == ("ollama", "ingenierov3")


def test_parse_debug_attempts_counts_retries():
    files = [
        "comparison_1_episode_1_prompt_attempt_1.txt",
        "comparison_1_summary_prompt_attempt_1.txt",
        "comparison_1_summary_prompt_attempt_2.txt",
    ]

    stats = parse_debug_attempts(files)

    assert stats["calls"] == 2
    assert stats["retried_calls"] == 1
    assert stats["retry_rate"] == 0.5
    assert stats["max_attempts"] == 2
    assert stats["prompt_files"] == 3


def _completed(returncode: int, output: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=output,
        stderr="",
    )


def test_run_validation_classifies_pass_stale_fail(tmp_path: Path):
    path = tmp_path / "debrief.json"
    path.write_text("{}", encoding="utf-8")

    assert (
        run_validation(
            path,
            validator_script=tmp_path / "v.py",
            runner=lambda *_a, **_k: _completed(0),
        )
        == "PASS"
    )
    assert (
        run_validation(
            path,
            validator_script=tmp_path / "v.py",
            runner=lambda *_a, **_k: _completed(1, STALE_RENDER_MARKER),
        )
        == "STALE_RENDER"
    )
    assert (
        run_validation(
            path,
            validator_script=tmp_path / "v.py",
            runner=lambda *_a, **_k: _completed(1, "otro error"),
        )
        == "FAIL"
    )


def test_collect_aggregates_by_backend(tmp_path: Path):
    llm = tmp_path / "llm_results" / "session"
    llm.mkdir(parents=True)
    (llm / "s_llm_analysis_v3_10_8_5_4_deepseek_v2_deepseek-v4-pro.json").write_text(
        "{}", encoding="utf-8"
    )
    (llm / "s_llm_analysis_v3_10_8_5_4_deepseek_v2_deepseek-v4-flash.json").write_text(
        "{}", encoding="utf-8"
    )
    debug = tmp_path / "llm_debug" / "session" / "deepseek"
    debug.mkdir(parents=True)
    (debug / "comparison_1_summary_prompt_attempt_1.txt").write_text("x", encoding="utf-8")
    (debug / "comparison_1_summary_prompt_attempt_2.txt").write_text("x", encoding="utf-8")

    report = collect(
        llm.parent,
        tmp_path / "llm_debug",
        tmp_path / "validate.py",
        runner=lambda *_a, **_k: _completed(0),
    )

    backend = report["summary"]["by_backend"]["deepseek"]
    assert backend["artifacts"] == 2
    assert backend["validation"] == {"PASS": 2}
    assert backend["calls"] == 1
    assert backend["retried_calls"] == 1
    assert backend["retry_rate"] == 1.0
    assert report["summary"]["by_model"]["deepseek/deepseek-v4-pro"]["artifacts"] == 1
