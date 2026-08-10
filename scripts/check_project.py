from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ACTIVE_PYTHON = [
    "analyze_telemetry.py",
    "llm_analysis.py",
    "session_history.py",
    "episode_pair_features.py",
    "validate_history_db.py",
    "validate_llm_analysis_output.py",
    "compare_llm_analysis_outputs.py",
    "vehicle_context.py",
]

CORE_MODULES = [
    "telemetry.py",
    "laps.py",
    "delta_comparison.py",
    "sector_analysis.py",
]

DEPENDENCIES = [
    "numpy",
    "pandas",
    "duckdb",
]

def main() -> int:
    errors = []
    warnings = []

    print("=" * 70)
    print("RACE ENGINEER - PROJECT CHECK")
    print("=" * 70)

    for name in ACTIVE_PYTHON:
        path = ROOT / name
        if not path.exists():
            errors.append(f"Missing active file: {name}")
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
            print(f"[OK] syntax: {name}")
        except Exception as exc:
            errors.append(f"Syntax error in {name}: {exc}")

    for name in CORE_MODULES:
        if (ROOT / name).exists():
            print(f"[OK] core module: {name}")
        else:
            warnings.append(f"Core module not present yet: {name}")

    for dep in DEPENDENCIES:
        if importlib.util.find_spec(dep):
            print(f"[OK] dependency: {dep}")
        else:
            errors.append(f"Dependency not installed: {dep}")

    devcontainer = ROOT / ".devcontainer" / "devcontainer.json"
    try:
        json.loads(devcontainer.read_text(encoding="utf-8"))
        print("[OK] devcontainer.json")
    except Exception as exc:
        errors.append(f"Invalid devcontainer.json: {exc}")

    example = ROOT / "examples" / "monza_analyze_v3_8.json"
    try:
        data = json.loads(example.read_text(encoding="utf-8"))
        version = str(data.get("metadata", {}).get("analysis_version"))
        if version != "3.8":
            errors.append(f"Example analysis_version={version}, expected 3.8")
        else:
            print("[OK] example JSON: analyze v3.8")
    except Exception as exc:
        errors.append(f"Invalid example JSON: {exc}")

    print()
    if warnings:
        print("WARNINGS")
        for item in warnings:
            print(f"  - {item}")
        print()

    if errors:
        print("PROJECT CHECK: FAIL")
        for item in errors:
            print(f"  - {item}")
        return 1

    if warnings:
        print("PROJECT CHECK: PASS WITH EXPECTED WARNINGS")
        print("Portable tools are ready. Raw telemetry analysis waits for the 4 core modules.")
    else:
        print("PROJECT CHECK: PASS")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
