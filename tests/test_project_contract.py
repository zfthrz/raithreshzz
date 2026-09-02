import importlib
import json
import os
from pathlib import Path

import prepare_calibration_batch

ROOT = Path(__file__).resolve().parents[1]

def test_monza_example_is_analyze_v38():
    data = json.loads((ROOT / "examples" / "monza_analyze_v3_8.json").read_text(encoding="utf-8"))
    metadata = data["metadata"]
    assert str(metadata["analysis_version"]) == "3.8"
    assert metadata["same_vehicle"] is True
    assert metadata["lap_comparison_model"] == "same_vehicle_different_laps"

def test_active_python_files_compile():
    names = [
        "analyze_telemetry.py",
        "llm_analysis.py",
        "session_history.py",
        "episode_pair_features.py",
        "validate_history_db.py",
        "validate_llm_analysis_output.py",
        "compare_llm_analysis_outputs.py",
        "vehicle_context.py",
        "cross_session_context.py",
        "cross_session_zone_localization.py",
        "build_cross_session_comparison.py",
        "historical_telemetry_evidence.py",
        "build_historical_telemetry_evidence.py",
        "validate_historical_telemetry_evidence.py",
        "audit_session_plan_actionability.py",
        "validate_cross_session_comparison.py",
        "historical_llm_analysis.py",
        "audit_h5_2_zone_selection.py",
        "rerender_llm_analysis_output.py",
        "validate_historical_llm_analysis.py",
        "race_engineer.py",
        "runtime_paths.py",
        "prepare_calibration_batch.py",
    ]
    for name in names:
        path = ROOT / name
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_calibration_orchestrator_accepts_current_history_schema_contract():
    assert prepare_calibration_batch.EXPECTED_HISTORY_SCHEMA_VERSION == 4
    assert prepare_calibration_batch.validate_dependency_contract(ROOT) == []


def test_analyzer_uses_centralized_runtime_output_path():
    source = (ROOT / "analyze_telemetry.py").read_text(encoding="utf-8")
    assert "from runtime_paths import analysis_output_path" in source
    assert "analysis_output_path(DB_PATH)" in source


def test_h5_2_raw_aliases_match_v0_2_sources():
    alias_contracts = {
        "build_cross_session_comparison.py": (
            "build_cross_session_comparison_v0_2.py"
        ),
        "validate_cross_session_comparison.py": (
            "validate_cross_session_comparison_v0_2.py"
        ),
    }
    for alias_name, source_name in alias_contracts.items():
        assert (ROOT / alias_name).read_bytes() == (ROOT / source_name).read_bytes()


def test_h2_matcher_alias_matches_v0_3_source():
    assert (ROOT / "episode_pair_matcher.py").read_text(encoding="utf-8") == (
        ROOT / "episode_pair_matcher_v0_3.py"
    ).read_text(encoding="utf-8")


def test_llm_scripts_use_centralized_runtime_paths_and_current_version():
    contracts = {
        "llm_analysis.py": (
            'llm_debug_dir(input_path, backend="ollama")',
            '_llm_analysis_v3_10_8_5_4_{MODEL_NAME}.json',
        ),
        "llm_analysis_ingenierov3.py": (
            'llm_debug_dir(input_path, backend="ollama")',
            '_llm_analysis_v3_10_8_5_4_{MODEL_NAME}.json',
        ),
        "llm_analysis_llamacpp.py": (
            'llm_debug_dir(input_path, backend="deepseek")',
            '_llm_analysis_v3_10_8_5_4_llamacpp_{MODEL_NAME}.json',
        ),
    }

    for name, (debug_contract, filename_contract) in contracts.items():
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "from runtime_paths import llm_debug_dir, llm_result_dir" in source
        assert "output_dir = str(llm_result_dir(input_path))" in source
        assert debug_contract in source
        assert filename_contract in source
        assert "_llm_analysis_v3_10_8_5_3" not in source

    deepseek_source = (ROOT / "llm_analysis_deepseek.py").read_text(
        encoding="utf-8"
    )
    document_source = (ROOT / "deterministic_debrief_document.py").read_text(
        encoding="utf-8"
    )
    output_source = (ROOT / "deterministic_debrief_output.py").read_text(
        encoding="utf-8"
    )
    assert 'llm_debug_dir(input_path, backend="deepseek")' in deepseek_source
    assert "save_compatible_debrief(" in deepseek_source
    assert "compatible_debrief_output_path(" in output_source
    assert "from runtime_paths import llm_result_dir" in document_source
    assert "_llm_analysis_v{DEBRIEF_ARTIFACT_VERSION}" in document_source
    assert "_deepseek_v2_{model_name}.json" in document_source
    assert "_llm_analysis_v3_10_8_5_3" not in document_source


def test_llm_session_braking_constants_execute_both_fact_paths():
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.BRAKING_POINT_SESSION_MIN_DELTA_M == 8.0
        assert module.BRAKING_POINT_PATTERN_ONSET_TOLERANCE_M == 8.0
        assert module.BRAKE_RELEASE_SESSION_MIN_DELTA_M == 8.0
        assert module.BRAKE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M == 8.0

        braking = module._session_braking_point_fact(
            {
                "braking_point_comparison": {
                    "status": "VALID",
                    "braking_pair_id": "pair",
                    "reference_event_id": "reference",
                    "comparison_event_id": "comparison",
                    "reference_onset_m": 100.0,
                    "comparison_onset_m": 110.0,
                    "comparison_minus_reference_m": 10.0,
                    "authorized_numeric_coaching": True,
                }
            }
        )
        assert braking["coaching_direction"] == "earlier"
        assert braking["coaching_magnitude_m"] == 10

        release = module._session_brake_release_fact(
            {
                "brake_release_point_comparison": {
                    "status": "VALID",
                    "braking_pair_id": "pair",
                    "reference_event_id": "reference",
                    "comparison_event_id": "comparison",
                    "reference_release_m": 200.0,
                    "comparison_release_m": 190.0,
                    "comparison_minus_reference_m": -10.0,
                    "authorized_numeric_coaching": True,
                }
            }
        )
        assert release["coaching_direction"] == "later"
        assert release["coaching_magnitude_m"] == 10
