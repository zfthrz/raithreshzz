from __future__ import annotations

from pathlib import Path

from runtime_paths import historical_telemetry_evidence_output_path


ROOT = Path(__file__).resolve().parents[1]


def test_historical_telemetry_evidence_runtime_path_is_centralized(tmp_path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_GENERATED_DIR", str(tmp_path))

    path = historical_telemetry_evidence_output_path("telemetria/spa.duckdb")

    assert path == (
        tmp_path
        / "h5_2_telemetry_evidence"
        / "spa"
        / "interval_evidence_v0_1.json"
    )


def test_orchestrator_runs_deterministic_evidence_before_optional_llm():
    source = (ROOT / "race_engineer.py").read_text(encoding="utf-8")

    evidence_position = source.index("# H5.2 deterministic telemetry evidence (shadow)")
    llm_position = source.index("# H5.2 LLM historical narrative (observational)")

    assert evidence_position < llm_position
    assert '"h5_2_telemetry_evidence"' in source
    assert '"--current-duration"' in source
    assert '"--reference-duration"' in source
    assert '"--zones"' in source
    assert '"observational_only": True' in source
    assert "historical_actions_authorized" not in source
    assert '"telemetry_evidence_sha256"' in source
    assert '"--telemetry-evidence"' in source


def test_orchestrator_evidence_failure_is_recorded_without_returning():
    source = (ROOT / "race_engineer.py").read_text(encoding="utf-8")
    start = source.index("except (subprocess.CalledProcessError, OSError, ValueError) as exc:")
    end = source.index("# H5.2 LLM historical narrative (observational)", start)
    failure_block = source[start:end]

    assert 'stage_results["h5_2_telemetry_evidence"] = STATUS_FAILED' in failure_block
    assert 'status=STATUS_FAILED' in failure_block
    assert "return 1" not in failure_block
