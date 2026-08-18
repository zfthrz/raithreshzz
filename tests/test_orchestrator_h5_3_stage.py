from __future__ import annotations

from pathlib import Path

from runtime_paths import h5_3_candidates_path, h5_3_section_path


ROOT = Path(__file__).resolve().parents[1]


def test_orchestrator_declares_h5_3_observational_stage():
    source = (ROOT / "race_engineer.py").read_text(encoding="utf-8")

    assert 'ORCHESTRATOR_VERSION = "0.3"' in source
    assert '"h5_3"' in source
    assert "build_historical_coaching_candidates.py" in source
    assert "render_historical_debrief.py" in source
    assert "validate_historical_debrief.py" in source
    assert "h5_3_candidates_path" in source
    assert "h5_3_section_path" in source
    assert 'stage_results.get("h5_3") in {STATUS_RUN, STATUS_REUSED}' in source
    assert 'section.get("rendered_section", "")' in source


def test_h5_3_runtime_paths_are_centralized(tmp_path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_GENERATED_DIR", str(tmp_path / "generated"))

    candidates = h5_3_candidates_path("telemetria/example.duckdb")
    section = h5_3_section_path("telemetria/example.duckdb")

    assert candidates.parts[-4:] == (
        "generated",
        "h5_3",
        "example",
        "historical_coaching_candidates.json",
    )
    assert section.parts[-3:] == ("h5_3", "example", "historical_section.json")
    assert candidates.parent == section.parent
