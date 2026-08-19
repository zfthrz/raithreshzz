"""Validate the unified H5.3 runtime shadow-selection contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import historical_candidate_selection as h53c


VALIDATOR_VERSION = "0.2"
SCHEMA_VERSION = "1.0"
SELECTION_VERSION = "0.2"
VALID_STATUS = "VALIDATED_HISTORICAL_CANDIDATE_SELECTION"
PROHIBITED_KEYS = frozenset({"actions", "coaching", "scores", "score", "human_labels"})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_prohibited(value: Any, prefix: str = "root") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in PROHIBITED_KEYS:
                errors.append(f"{prefix} contiene clave prohibida: {key}")
            errors.extend(_find_prohibited(child, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_find_prohibited(child, f"{prefix}[{index}]"))
    return errors


def validate(selection: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(selection, dict):
        return ["la selección no es un objeto"]

    metadata = selection.get("metadata") or {}
    if metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append("metadata.schema_version inválido")
    if metadata.get("candidate_selection_version") != SELECTION_VERSION:
        errors.append("metadata.candidate_selection_version inválido")
    if metadata.get("status") != VALID_STATUS or selection.get("status") != VALID_STATUS:
        errors.append("status de selección inválido")
    if metadata.get("backend") not in {"deterministic", "deepseek", "ollama", "llamacpp"}:
        errors.append("metadata.backend inválido")

    source_value = metadata.get("source_candidates_json")
    source_path = Path(str(source_value or ""))
    if not source_value:
        errors.append("metadata.source_candidates_json ausente")
    elif not source_path.is_file():
        errors.append("metadata.source_candidates_json no existe")
    elif metadata.get("source_candidates_sha256") != _sha256_file(source_path):
        errors.append("metadata.source_candidates_sha256 no coincide")

    authorized = selection.get("authorized_candidates")
    if not isinstance(authorized, list) or not authorized:
        errors.append("authorized_candidates ausente o vacío")
        authorized = []
    authorized_ids: set[str] = set()
    for index, candidate in enumerate(authorized):
        if not isinstance(candidate, dict):
            errors.append(f"authorized_candidates[{index}] inválido")
            continue
        candidate_id = candidate.get("candidate_id")
        if not candidate_id:
            errors.append(f"authorized_candidates[{index}].candidate_id ausente")
        elif candidate_id in authorized_ids:
            errors.append(f"authorized_candidates[{index}].candidate_id duplicado")
        else:
            authorized_ids.add(candidate_id)
        observations = candidate.get("authorized_observations")
        if not isinstance(observations, list) or not observations:
            errors.append(f"authorized_candidates[{index}].authorized_observations inválido")

    response = selection.get("llm_selection")
    if not isinstance(response, dict):
        errors.append("llm_selection inválido")
        response = {}
    evidence = {
        "candidates": authorized,
        "required_limitation_codes": list(h53c.REQUIRED_LIMITATIONS),
    }
    errors.extend(
        f"llm_selection: {error}"
        for error in h53c.validate_response(response, evidence)
    )

    selected = response.get("selected_candidates", [])
    selected_ids = [
        item.get("candidate_id")
        for item in selected
        if isinstance(item, dict)
    ]
    selected_evidence = selection.get("selected_evidence")
    if not isinstance(selected_evidence, list):
        errors.append("selected_evidence inválido")
        selected_evidence = []
    evidence_ids = [
        item.get("candidate_id")
        for item in selected_evidence
        if isinstance(item, dict)
    ]
    if evidence_ids != selected_ids:
        errors.append("selected_evidence no coincide con llm_selection")
    if selection.get("selected_count") != len(selected_ids):
        errors.append("selected_count no coincide")

    authority = selection.get("coaching_authority") or {}
    if authority.get("session_reference_remains_authority") is not True:
        errors.append("session_reference dejó de ser autoridad")
    if authority.get("historical_actions_authorized") is not False:
        errors.append("historical_actions_authorized debe ser false")

    errors.extend(_find_prohibited(selection))
    return errors


def validate_and_report(selection_path: Path) -> dict[str, Any]:
    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    errors = validate(payload)
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "error_count": len(errors),
        "source_file": str(selection_path),
        "schema_version": payload.get("metadata", {}).get("schema_version"),
        "selection_version": payload.get("metadata", {}).get(
            "candidate_selection_version"
        ),
        "selection_count": payload.get("selected_count"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida la selección runtime shadow H5.3 unificada."
    )
    parser.add_argument("selection_json")
    args = parser.parse_args()
    selection_path = Path(args.selection_json).resolve()
    if not selection_path.is_file():
        raise FileNotFoundError(f"No encontrado: {selection_path}")
    result = validate_and_report(selection_path)
    print("=" * 88)
    print(f"RACE ENGINEER - H5.3 SHADOW SELECTION VALIDATOR v{VALIDATOR_VERSION}")
    print("=" * 88)
    print(f"Source: {selection_path}")
    print(f"Errors: {result['error_count']}")
    for error in result["errors"]:
        print(f"  - {error}")
    print("RESULT: " + result["status"])
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
