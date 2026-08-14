from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida output de H5.2 interface probe.")
    ap.add_argument("probe_json")
    args = ap.parse_args()

    doc = json.loads(Path(args.probe_json).read_text(encoding="utf-8"))
    errors = []

    if (doc.get("metadata") or {}).get("probe_version") != "0.1":
        errors.append("probe_version inválida")

    selection = doc.get("selection") or {}
    for side in ("current", "historical"):
        row = selection.get(side)
        if not isinstance(row, dict):
            errors.append(f"selection.{side} ausente")
            continue
        if not Path(str(row.get("resolved_duckdb") or "")).is_file():
            errors.append(f"{side}: resolved_duckdb no existe")
        if not isinstance(row.get("lap_summary"), dict):
            errors.append(f"{side}: lap_summary ausente")

    if doc.get("context_mismatches"):
        errors.append("context_mismatches no vacío")

    modules = doc.get("modules") or {}
    for name in ("telemetry", "laps", "delta_comparison", "sector_analysis"):
        row = modules.get(name)
        if not isinstance(row, dict):
            errors.append(f"module {name} ausente")
            continue
        if not row.get("module_file"):
            errors.append(f"module {name}: module_file ausente")
        if not isinstance(row.get("public_methods"), list):
            errors.append(f"module {name}: public_methods inválido")

    delta_methods = {
        x.get("name") for x in (modules.get("delta_comparison") or {}).get("public_methods", [])
        if isinstance(x, dict)
    }
    if "compare" not in delta_methods:
        errors.append("DeltaComparison.compare no detectado")

    lap_methods = {
        x.get("name") for x in (modules.get("laps") or {}).get("public_methods", [])
        if isinstance(x, dict)
    }
    if "all_lap_summaries" not in lap_methods:
        errors.append("LapAnalyzer.all_lap_summaries no detectado")

    print("=" * 88)
    print("RACE ENGINEER - H5.2 INTERFACE PROBE VALIDATION v0.1")
    print("=" * 88)
    print(f"Errors: {len(errors)}")
    for e in errors:
        print(f"  - {e}")

    if errors:
        print("RESULT: FAIL")
        return 2

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
