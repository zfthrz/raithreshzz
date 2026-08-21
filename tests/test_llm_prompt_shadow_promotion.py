from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from assess_llm_prompt_shadow_promotion import (
    VERDICT_INSUFFICIENT,
    VERDICT_NO_BENEFIT,
    VERDICT_READY,
    VERDICT_REGRESSION,
    assess_sessions,
)
from tools.llm_repair_diagnostics import ERROR_CATEGORIES, ERROR_CHANNELS, ERROR_FIELDS, SessionDiagnostic


def diagnostic(
    source: str,
    track: str,
    policy: str,
    *,
    model: str = "model-a",
    repairs: int = 2,
    critical: int = 2,
    fallbacks: int = 0,
) -> SessionDiagnostic:
    categories = {name: 0 for name in ERROR_CATEGORIES}
    categories["FACTUAL_DIRECTION_INVERSION"] = critical
    return SessionDiagnostic(
        path=f"{source}-{policy}-{model}.json",
        source_json=source,
        backend="deepseek",
        model=model,
        prompt_policy=policy,
        track=track,
        comparison_count=3,
        episode_count=20,
        clean_episode_count=20 - repairs,
        episodes_requiring_repair_count=repairs,
        replaced_interpretation_count=repairs,
        replaced_recommendation_count=0,
        pruned_hypothesis_count=0,
        target_reference_repair_count=0,
        episode_retry_count=0,
        ranking_attempts_gt_one_count=0,
        summary_attempts_gt_one_count=0,
        global_attempts_gt_one_count=0,
        fallback_count=fallbacks,
        repair_rate=repairs / 20,
        clean_output=repairs == 0 and fallbacks == 0,
        validation_error_categories=categories,
        validation_error_fields={name: 0 for name in ERROR_FIELDS},
        validation_error_channels={name: 0 for name in ERROR_CHANNELS},
    )


def pair(source: str, track: str, *, shadow_repairs: int = 1):
    production = diagnostic(source, track, "production", repairs=2, critical=2)
    shadow = diagnostic(
        source,
        track,
        "episode-grounding-shadow-v0.1",
        repairs=shadow_repairs,
        critical=shadow_repairs,
    )
    return production, shadow


def test_one_equal_exact_pair_is_insufficient_and_has_no_benefit():
    production, shadow = pair("imola.json", "Imola", shadow_repairs=2)

    report = assess_sessions([production, shadow])

    assert report["verdict"] == VERDICT_INSUFFICIENT
    assert report["coverage"]["exact_pair_count"] == 1
    assert report["requirements"]["measurable_benefit"] is False


def test_cross_model_shadow_is_observational_not_an_exact_pair():
    production, shadow = pair("fuji.json", "Fuji")
    shadow = replace(shadow, model="different-model")

    report = assess_sessions([production, shadow])

    assert report["coverage"]["exact_pair_count"] == 0
    assert report["coverage"]["unpaired_shadow_count"] == 1
    assert report["verdict"] == VERDICT_INSUFFICIENT


def test_any_exact_pair_regression_blocks_promotion():
    production, shadow = pair("imola.json", "Imola", shadow_repairs=3)

    report = assess_sessions([production, shadow])

    assert report["verdict"] == VERDICT_REGRESSION
    assert "repair_rate_increased" in report["exact_pairs"][0]["regressions"]


def test_three_improved_pairs_across_two_tracks_are_ready():
    sessions = [
        *pair("imola-a.json", "Imola"),
        *pair("imola-b.json", "Imola"),
        *pair("fuji.json", "Fuji"),
    ]

    report = assess_sessions(sessions)

    assert report["verdict"] == VERDICT_READY
    assert report["coverage"]["exact_pair_count"] == 3
    assert report["requirements"]["measurable_benefit"] is True


def test_sufficient_equal_pairs_are_blocked_by_no_measurable_benefit():
    sessions = [
        *pair("imola-a.json", "Imola", shadow_repairs=2),
        *pair("imola-b.json", "Imola", shadow_repairs=2),
        *pair("fuji.json", "Fuji", shadow_repairs=2),
    ]

    report = assess_sessions(sessions)

    assert report["verdict"] == VERDICT_NO_BENEFIT
    assert report["requirements"]["no_regression"] is True
    assert report["requirements"]["measurable_benefit"] is False


def test_prompt_shadow_gate_is_documented_in_project_contracts():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "AGENTS.md",
        "PROJECT_CONTEXT.md",
        "PROJECT_STATUS.md",
        "README.md",
        "docs/LLM_PROMPT_SHADOW_PROMOTION_GATE_V0_1.md",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "assess_llm_prompt_shadow_promotion.py" in source, relative
        assert "PROMOTION_BLOCKED_INSUFFICIENT_PAIRED_EVIDENCE" in source, relative
