import json
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
    ]
    for name in names:
        path = ROOT / name
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
