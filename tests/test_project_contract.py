import json
import hashlib
from pathlib import Path

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
        "build_cross_session_comparison.py",
        "validate_cross_session_comparison.py",
        "historical_llm_analysis.py",
        "validate_historical_llm_analysis.py",
        "race_engineer.py",
        "runtime_paths.py",
    ]
    for name in names:
        path = ROOT / name
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_analyzer_uses_centralized_runtime_output_path():
    source = (ROOT / "analyze_telemetry.py").read_text(encoding="utf-8")
    assert "from runtime_paths import analysis_output_path" in source
    assert "analysis_output_path(DB_PATH)" in source


def test_llm_aliases_match_their_versioned_sources():
    alias_contracts = {
        "llm_analysis.py": "llm_analysis_v3_10_8_5_4_ingenierov3.py",
        "llm_analysis_ingenierov3.py": "llm_analysis_v3_10_8_5_4_ingenierov3.py",
        "llm_analysis_deepseek.py": "llm_analysis_v3_10_8_5_4_deepseek_v2.py",
    }

    for alias_name, source_name in alias_contracts.items():
        alias_digest = hashlib.sha256((ROOT / alias_name).read_bytes()).digest()
        source_digest = hashlib.sha256((ROOT / source_name).read_bytes()).digest()
        assert alias_digest == source_digest


def test_llm_scripts_use_centralized_runtime_paths_and_current_version():
    contracts = {
        "llm_analysis_v3_10_8_5_4_ingenierov3.py": (
            'llm_debug_dir(input_path, backend="ollama")',
            '_llm_analysis_v3_10_8_5_4_{MODEL_NAME}.json',
        ),
        "llm_analysis_v3_10_8_5_4_deepseek_v2.py": (
            'llm_debug_dir(input_path, backend="deepseek")',
            '_llm_analysis_v3_10_8_5_4_deepseek_v2_{MODEL_NAME}.json',
        ),
    }

    for name, (debug_contract, filename_contract) in contracts.items():
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "from runtime_paths import llm_debug_dir, llm_result_dir" in source
        assert "output_dir = str(llm_result_dir(input_path))" in source
        assert debug_contract in source
        assert filename_contract in source
        assert "_llm_analysis_v3_10_8_5_3" not in source
