from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from historical_candidate_selection_v0_1 import (
    CANDIDATE_SELECTION_VERSION,
    SCHEMA_VERSION,
    build_authorized_evidence,
    load_validated_sources,
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
    if metadata.get("candidate_selection_version") != CANDIDATE_SELECTION_VERSION:
        errors.append("metadata.candidate_selection_version inválida")
    if document.get("status") != "VALIDATED_HISTORICAL_CANDIDATE_SELECTION":
        errors.append("status inválido")

    dataset_value = metadata.get("source_dataset_json")
    dataset_path = Path(str(dataset_value or ""))
    if not dataset_path.is_file():
        errors.append("metadata.source_dataset_json no existe")
        return errors
    if metadata.get("source_dataset_sha256") != sha256_file(dataset_path):
        errors.append("metadata.source_dataset_sha256 no coincide")

    labels_value = metadata.get("source_labels_json")
    labels_path = Path(str(labels_value or ""))
    if not labels_path.is_file():
        errors.append("metadata.source_labels_json no existe")
        return errors
    if metadata.get("source_labels_sha256") != sha256_file(labels_path):
        errors.append("metadata.source_labels_sha256 no coincide")

    try:
        dataset, labels = load_validated_sources(dataset_path, labels_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"fuentes H5.3 inválidas: {exc}")
        return errors
    evidence = build_authorized_evidence(dataset, labels)

    if document.get("authorized_candidates") != evidence["candidates"]:
        errors.append("authorized_candidates no coincide exactamente con H5.3b")

    selection = document.get("llm_selection")
    if not isinstance(selection, dict):
        errors.append("llm_selection ausente o inválida")
        return errors
    errors.extend(validate_response(selection, evidence))
    if errors:
        return errors

    expected_selected = selected_evidence(selection, evidence)
    if document.get("selected_evidence") != expected_selected:
        errors.append("selected_evidence no coincide exactamente con H5.3b")
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
    if authority.get("candidate_selection_is_shadow") is not True:
        errors.append("candidate_selection_is_shadow debe ser true")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida selección LLM de candidatos históricos H5.3c v0.1"
    )
    parser.add_argument("selection_json")
    args = parser.parse_args()
    document = json.loads(Path(args.selection_json).read_text(encoding="utf-8"))
    errors = validate(document)
    print("=" * 88)
    print("RACE ENGINEER - H5.3c CANDIDATE SELECTION VALIDATION v0.1")
    print("=" * 88)
    print(f"Errors: {len(errors)}")
    for error in errors:
        print(f"  - {error}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
