from __future__ import annotations

from pathlib import Path

from race_engineer import (
    STATUS_SKIPPED,
    h5_2_llm_skip_on_failure,
)


ROOT = Path(__file__).resolve().parents[1]


def test_h5_2_llm_skip_on_failure_marks_skipped_not_applicable():
    stage_results: dict[str, str] = {}

    h5_2_llm_skip_on_failure(stage_results)

    assert stage_results["h5_2_llm"] == STATUS_SKIPPED
    assert STATUS_SKIPPED == "SKIPPED_NOT_APPLICABLE"


def test_h5_2_llm_skip_on_failure_prints_advisory(capsys):
    h5_2_llm_skip_on_failure({})

    captured = capsys.readouterr().out
    assert "narrativa H5.2 no disponible" in captured
    assert "continúa sin narrativa observacional" in captured


def test_h5_2_llm_failure_branch_does_not_block_analysis():
    source = (ROOT / "race_engineer.py").read_text(encoding="utf-8")

    marker = "h5_2_llm_skip_on_failure(stage_results)"
    assert marker in source
    assert 'stage_results["h5_2_llm"] = STATUS_FAILED' not in source

    start = source.index(marker)
    section_end = source.index("# H5.3 historical section", start)
    section = source[start:section_end]

    assert "return 1" not in section
    # El registro RUN debe quedar bajo el guard else (sólo sin excepción).
    assert "else:" in section
    assert 'status=STATUS_RUN' in section


def test_d3_1_scope_does_not_touch_ranking_plan_or_cues():
    source = (ROOT / "race_engineer.py").read_text(encoding="utf-8")

    assert "build_driver_cues_for_plan_item" not in source
    assert "build_deterministic_comparison_ranker_response" not in source
    assert "historical_actions_authorized" not in source
    assert "next_stint_plan" not in source
