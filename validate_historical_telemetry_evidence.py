"""Validate Historical Telemetry Evidence v0.1 artifacts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_document(document: object) -> list[str]:
    errors = []
    if not isinstance(document, dict):
        return ["root debe ser un objeto"]
    metadata = document.get("metadata")
    contract = document.get("contract")
    intervals = document.get("interval_evidence")
    if not isinstance(metadata, dict):
        errors.append("metadata ausente o inválido")
    else:
        if metadata.get("version") != "0.1":
            errors.append("metadata.version debe ser 0.1")
        if metadata.get("status") not in {
            "FULL_COMMON_COVERAGE", "PARTIAL_COMMON_COVERAGE", "NO_COMMON_COVERAGE"
        }:
            errors.append("metadata.status inválido")
        for key in ("current_coverage_ratio", "reference_coverage_ratio"):
            value = metadata.get(key)
            if not _finite(value) or not 0.0 <= value <= 1.0:
                errors.append(f"metadata.{key} debe estar entre 0 y 1")
    required_contract = {
        "observational_only": True,
        "affects_next_stint_plan": False,
        "historical_actions_authorized": False,
        "llm_called": False,
    }
    if contract != required_contract:
        errors.append("contract no conserva autoridad observacional read-only")
    if not isinstance(intervals, list):
        errors.append("interval_evidence debe ser una lista")
        return errors
    seen_ids = set()
    for index, item in enumerate(intervals):
        prefix = f"interval_evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} debe ser un objeto")
            continue
        interval_id = item.get("interval_id")
        if not isinstance(interval_id, str) or not interval_id:
            errors.append(f"{prefix}.interval_id inválido")
        elif interval_id in seen_ids:
            errors.append(f"{prefix}.interval_id duplicado")
        else:
            seen_ids.add(interval_id)
        start = item.get("start_distance_m")
        end = item.get("end_distance_m")
        if not _finite(start) or not _finite(end) or end <= start:
            errors.append(f"{prefix} tiene límites inválidos")
        if item.get("status") not in {"FULL_COVERAGE", "PARTIAL_COVERAGE", "UNAVAILABLE"}:
            errors.append(f"{prefix}.status inválido")
        coverage = item.get("coverage_ratio")
        if not _finite(coverage) or not 0.0 <= coverage <= 1.0:
            errors.append(f"{prefix}.coverage_ratio inválido")
        count = item.get("sample_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"{prefix}.sample_count inválido")
        for key in (
            "delta_change_s", "speed_delta_mean_kmh",
            "throttle_delta_mean_percent", "brake_delta_mean_percent",
        ):
            value = item.get(key)
            if value is not None and not _finite(value):
                errors.append(f"{prefix}.{key} debe ser finito o null")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    document = json.loads(args.artifact.read_text(encoding="utf-8"))
    errors = validate_document(document)
    for error in errors:
        print(f"- {error}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
