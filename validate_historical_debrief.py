from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from render_historical_debrief_v0_1 import (
    RENDER_VERSION,
    SCHEMA_VERSION,
    STATUS_SECTION,
    build_section,
    load_validated_sources,
    sha256_file,
)


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    if metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append("metadata.schema_version inválida")
    if metadata.get("render_version") != RENDER_VERSION:
        errors.append("metadata.render_version inválida")
    if document.get("status") != STATUS_SECTION:
        errors.append("status inválido")

    dual_value = metadata.get("source_dual_reference_json")
    dual_path = Path(str(dual_value or ""))
    comparison_value = metadata.get("source_comparison_json")
    comparison_path = Path(str(comparison_value or ""))
    if not dual_path.is_file() or not comparison_path.is_file():
        errors.append("fuentes H5.1/H5.2 no existen")
        return errors
    if metadata.get("source_dual_reference_sha256") != sha256_file(dual_path):
        errors.append("source_dual_reference_sha256 no coincide")
    if metadata.get("source_comparison_sha256") != sha256_file(comparison_path):
        errors.append("source_comparison_sha256 no coincide")

    telemetry_value = metadata.get("source_telemetry_evidence_json")
    telemetry_path = Path(str(telemetry_value)) if telemetry_value else None
    if telemetry_path is not None:
        if not telemetry_path.is_file():
            errors.append("fuente H5.2 telemetry evidence no existe")
            return errors
        if metadata.get("source_telemetry_evidence_sha256") != sha256_file(
            telemetry_path
        ):
            errors.append("source_telemetry_evidence_sha256 no coincide")

    try:
        expected = build_section(dual_path, comparison_path, telemetry_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"fuentes H5.3 inválidas: {exc}")
        return errors

    if document.get("labels") != expected["labels"]:
        errors.append("labels no coinciden con las fuentes H5.1/H5.2")
    if document.get("zones") != expected["zones"]:
        errors.append("zones no coinciden exactamente con H5.2")
    if document.get("limitations") != expected["limitations"]:
        errors.append("limitations no coinciden con las fuentes")
    if document.get("rendered_section") != expected["rendered_section"]:
        errors.append("rendered_section no coincide con el render Python")

    authority = document.get("coaching_authority") or {}
    if authority.get("session_reference_remains_authority") is not True:
        errors.append("session_reference dejó de ser autoridad")
    if authority.get("historical_reference_is_observational") is not True:
        errors.append("historical_reference debe seguir siendo observacional")
    if authority.get("historical_actions_authorized") is not False:
        errors.append("historical_actions_authorized debe ser false")
    return errors


def build_safe_fallback(
    dual_reference_path: Path,
    comparison_path: Path,
) -> dict[str, Any]:
    """Regenera la sección determinista desde las fuentes; si las fuentes son
    inválidas devuelve un registro explícito de fallo sin tocar el debrief normal."""
    try:
        section = build_section(dual_reference_path, comparison_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "H5_3_FAILED",
            "reason": f"{type(exc).__name__}: {exc}",
            "normal_debrief_unchanged": True,
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        }
    section["metadata"]["fallback"] = "regenerated_from_validated_sources"
    section["metadata"]["normal_debrief_unchanged"] = True
    return section


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida la sección histórica H5.3d y provee fallback seguro."
    )
    parser.add_argument("section_json")
    args = parser.parse_args()
    document = json.loads(Path(args.section_json).read_text(encoding="utf-8"))
    errors = validate(document)
    print("=" * 88)
    print("RACE ENGINEER - H5.3d/e HISTORICAL SECTION VALIDATION v0.1")
    print("=" * 88)
    print(f"Errors: {len(errors)}")
    for error in errors:
        print(f"  - {error}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
