from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(document: dict) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    if metadata.get("schema_version") != "1.0":
        errors.append("metadata.schema_version inválida")
    if metadata.get("cross_session_version") != "0.1":
        errors.append("metadata.cross_session_version inválida")
    if document.get("status") != "RAW_CROSS_SESSION_COMPARISON_AVAILABLE":
        errors.append("status inválido")

    for key in ("historical_reference", "current_session_reference"):
        reference = document.get(key)
        if not isinstance(reference, dict):
            errors.append(f"{key} ausente")
            continue
        if not isinstance(reference.get("session_id"), int):
            errors.append(f"{key}.session_id inválido")
        if not isinstance(reference.get("lap"), int):
            errors.append(f"{key}.lap inválido")
        if not Path(str(reference.get("source_database") or "")).is_file():
            errors.append(f"{key}.source_database no existe")

    temporal = document.get("temporal_validation") or {}
    if temporal.get("status") != "OK":
        errors.append("temporal_validation.status no es OK")
    error = temporal.get("error_s")
    tolerance = temporal.get("tolerance_s")
    if not isinstance(error, (int, float)) or not isinstance(tolerance, (int, float)):
        errors.append("temporal_validation error/tolerance inválidos")
    elif abs(error) > tolerance:
        errors.append("temporal_validation excede tolerancia")

    spatial = document.get("spatial_comparison") or {}
    zones = spatial.get("zone_summaries")
    if not isinstance(zones, list):
        errors.append("spatial_comparison.zone_summaries inválido")
    elif spatial.get("zone_summary_count") != len(zones):
        errors.append("zone_summary_count no coincide")

    authority = document.get("coaching_authority") or {}
    if authority.get("session_reference_remains_authority") is not True:
        errors.append("session_reference dejó de ser autoridad")
    if authority.get("historical_actions_authorized") is not False:
        errors.append("historical_actions_authorized debe ser false en v0.1")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida output H5.2 v0.1")
    parser.add_argument("comparison_json")
    args = parser.parse_args()
    document = json.loads(Path(args.comparison_json).read_text(encoding="utf-8"))
    errors = validate(document)

    print("=" * 88)
    print("RACE ENGINEER - H5.2 RAW CROSS-SESSION VALIDATION v0.1")
    print("=" * 88)
    print(f"Errors: {len(errors)}")
    for error in errors:
        print(f"  - {error}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
