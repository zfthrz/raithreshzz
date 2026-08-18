from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from historical_action_policy_v0_1 import (
    ACTION_POLICY_VERSION,
    SCHEMA_VERSION,
    STATUS_AUTHORIZED,
    build_action_candidates,
    sha256_file,
)


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    if metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append("metadata.schema_version inválida")
    if metadata.get("action_policy_version") != ACTION_POLICY_VERSION:
        errors.append("metadata.action_policy_version inválida")
    if document.get("status") != STATUS_AUTHORIZED:
        errors.append("status inválido")

    source_value = metadata.get("source_selection_json")
    source_path = Path(str(source_value or ""))
    if not source_path.is_file():
        errors.append("metadata.source_selection_json no existe")
        return errors
    if metadata.get("source_selection_sha256") != sha256_file(source_path):
        errors.append("metadata.source_selection_sha256 no coincide")

    try:
        expected = build_action_candidates(source_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"selección H5.3c inválida: {exc}")
        return errors

    if document.get("actions") != expected["actions"]:
        errors.append("actions no coinciden con la política determinista")
    if document.get("withheld") != expected["withheld"]:
        errors.append("withheld no coincide con la política determinista")

    authority = document.get("coaching_authority") or {}
    if authority.get("session_reference_remains_authority") is not True:
        errors.append("session_reference dejó de ser autoridad")
    if authority.get("historical_actions_authorized") is not True:
        errors.append("historical_actions_authorized debe ser true en este artefacto")
    if authority.get("scope") != "authorized_action_candidates_only":
        errors.append("scope de autorización inválido")

    for index, action in enumerate(document.get("actions", [])):
        if not isinstance(action, dict):
            errors.append(f"actions[{index}] inválido")
            continue
        authorization = action.get("authorization") or {}
        if authorization.get("authorized") is not True:
            errors.append(f"actions[{index}] no está autorizada")
        if authorization.get("policy_version") != ACTION_POLICY_VERSION:
            errors.append(f"actions[{index}].policy_version inválida")
        if action.get("delta_sign") != "current_slower":
            errors.append(f"actions[{index}] viola la regla anti-regresión")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida el artefacto de acciones históricas autorizadas H5.3."
    )
    parser.add_argument("actions_json")
    args = parser.parse_args()
    document = json.loads(Path(args.actions_json).read_text(encoding="utf-8"))
    errors = validate(document)
    print("=" * 88)
    print("RACE ENGINEER - H5.3 ACTION POLICY VALIDATION v0.1")
    print("=" * 88)
    print(f"Errors: {len(errors)}")
    for error in errors:
        print(f"  - {error}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
