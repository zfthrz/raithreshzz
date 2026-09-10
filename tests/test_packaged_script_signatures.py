from pathlib import Path

import pytest

import race_engineer
import validate_llm_analysis_output as output_validator


def test_frozen_script_signature_uses_packaged_executable(tmp_path, monkeypatch):
    executable = tmp_path / "RaceEngineerCLI.exe"
    executable.write_bytes(b"closed packaged runtime")
    missing_source = tmp_path / "analyze_telemetry.py"

    monkeypatch.setattr(race_engineer.sys, "frozen", True, raising=False)
    monkeypatch.setattr(race_engineer.sys, "executable", str(executable))

    assert race_engineer.script_signature(missing_source) == {
        "path": "packaged:analyze_telemetry.py",
        "sha256": race_engineer.sha256_file(executable),
    }


def test_source_script_signature_still_requires_real_file(tmp_path, monkeypatch):
    monkeypatch.delattr(race_engineer.sys, "frozen", raising=False)

    with pytest.raises(FileNotFoundError):
        race_engineer.script_signature(tmp_path / "missing.py")


def test_packaged_cli_includes_duckdb_dynamic_uuid_dependency():
    spec = (Path(__file__).parents[1] / "RaceEngineer.spec").read_text(encoding="utf-8")

    assert 'cli_analysis = analysis("RaceEngineerCLI.py", hiddenimports=["uuid"])' in spec


def test_packaged_validator_uses_neutral_deterministic_renderer(tmp_path):
    renderer = output_validator._build_packaged_renderer(tmp_path)

    assert renderer.render_comparison_analysis.__module__ == "deterministic_comparison_render"
    assert renderer.render_global_analysis.__module__ == "deterministic_global_render"
    assert (
        renderer.build_deterministic_next_session_priorities.__module__
        == "deterministic_coaching"
    )
