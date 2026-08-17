from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from historical_llm_analysis_v0_1 import (
    HISTORICAL_LLM_VERSION,
    SCHEMA_VERSION,
    build_authorized_evidence,
    load_validated_source,
    render_analysis,
    selected_evidence,
    sha256_file,
    validate_response,
)


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    if metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append("metadata.schema_version inválida")
    if metadata.get("historical_llm_version") != HISTORICAL_LLM_VERSION:
        errors.append("metadata.historical_llm_version inválida")
    if document.get("status") != "VALIDATED_HISTORICAL_OBSERVATION":
        errors.append("status inválido")

    source_value = metadata.get("source_h5_2_json")
    source_path = Path(str(source_value or ""))
    if not source_path.is_file():
        errors.append("metadata.source_h5_2_json no existe")
        return errors
    if metadata.get("source_h5_2_sha256") != sha256_file(source_path):
        errors.append("metadata.source_h5_2_sha256 no coincide")

    try:
        source = load_validated_source(source_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"source H5.2 inválido: {exc}")
        return errors
    evidence = build_authorized_evidence(source)

    if document.get("context") != evidence["context"]:
        errors.append("context no coincide con H5.2")
    if document.get("localization") != evidence["localization"]:
        errors.append("localization no coincide con H5.2")
    if document.get("lap_comparison") != evidence["lap_comparison"]:
        errors.append("lap_comparison no coincide con H5.2")

    selection = document.get("llm_selection")
    if not isinstance(selection, dict):
        errors.append("llm_selection ausente o inválida")
        return errors
    errors.extend(validate_response(selection, evidence))
    if errors:
        return errors

    expected_selected = selected_evidence(selection, evidence)
    if document.get("selected_evidence") != expected_selected:
        errors.append("selected_evidence no coincide exactamente con H5.2")
    expected_rendered = render_analysis(selection, evidence)
    if document.get("rendered_analysis") != expected_rendered:
        errors.append("rendered_analysis no coincide con el render Python")

    authority = document.get("coaching_authority") or {}
    if authority.get("session_reference_remains_authority") is not True:
        errors.append("session_reference dejó de ser autoridad")
    if authority.get("historical_reference_is_observational") is not True:
        errors.append("historical_reference debe seguir siendo observacional")
    if authority.get("historical_actions_authorized") is not False:
        errors.append("historical_actions_authorized debe ser false")
    if authority.get("causal_claims_authorized") is not False:
        errors.append("causal_claims_authorized debe ser false")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida narrativa LLM observacional H5.2 v0.1"
    )
    parser.add_argument("historical_llm_json")
    args = parser.parse_args()
    document = json.loads(Path(args.historical_llm_json).read_text(encoding="utf-8"))
    errors = validate(document)
    print("=" * 88)
    print("RACE ENGINEER - H5.2 HISTORICAL LLM VALIDATION v0.1")
    print("=" * 88)
    print(f"Errors: {len(errors)}")
    for error in errors:
        print(f"  - {error}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
