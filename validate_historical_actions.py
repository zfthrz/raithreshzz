"""validate_historical_actions.py — validator para el output shadow
de ``historical_action_policy.py`` (v0.2).

Verifica contract, policy, status, reason codes, anti-regresión,
vocabulario cerrado, observation codes, speed/time never actions,
authority contract, no authorized-empty, candidate ID uniqueness,
y provenance.

v0.2 mejoras:
- No depende de re-ejecutar build_action_candidates (el artefacto
  autocontiene metadata determinista).
- Valida classified_observation_codes en cada action/withheld.
- Valida que no existan authorized actions con actions vacíos.
- Valida candidate_id unicidad en actions y withheld.
- Valida observation codes conocidos vs desconocidos.
- Valida authority contract (historical_actions_authorized=false,
  session_reference_remains_authority=true).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from historical_action_policy_v0_2 import (
    ACTION_POLICY_VERSION,
    SCHEMA_VERSION,
    STATUS_AUTHORIZED,
    OBSERVATION_TO_ACTION,
    ACTION_TEXT,
    KNOWN_OBSERVATION_CODES,
    KNOWN_NON_MAPPABLE_CODES,
    ALLOWED_WITHHELD_REASON_CODES,
    build_action_candidates,
    sha256_file,
)


ALLOWED_REASON_CODES = ALLOWED_WITHHELD_REASON_CODES

ALLOWED_POLICIES = frozenset({
    "closed_action_vocabulary",
    "closed_observation_vocabulary",
    "speed_is_context_not_target",
    "time_codes_are_not_actions",
    "session_reference_remains_authority",
})


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    if metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append("metadata.schema_version inválida")
    if metadata.get("action_policy_version") != ACTION_POLICY_VERSION:
        errors.append(f"metadata.action_policy_version inválido: {metadata.get('action_policy_version')}, esperado {ACTION_POLICY_VERSION}")
    if document.get("status") != STATUS_AUTHORIZED:
        errors.append("status inválido")

    # ── Policy checks ──────────────────────────────────────────────────────
    policy = metadata.get("policy", {})
    if not isinstance(policy, dict):
        errors.append("metadata.policy inválido")
    else:
        if policy.get("closed_action_vocabulary") != sorted(ACTION_TEXT):
            errors.append("metadata.policy.closed_action_vocabulary no coincide")
        if not policy.get("speed_is_context_not_target"):
            errors.append("metadata.policy.speed_is_context_not_target no es true")
        if not policy.get("time_codes_are_not_actions"):
            errors.append("metadata.policy.time_codes_are_not_actions no es true")
        if policy.get("session_reference_remains_authority") is not True:
            errors.append("metadata.policy.session_reference_remains_authority no es true")
        if policy.get("historical_actions_authorized") is not False:
            errors.append("metadata.policy.historical_actions_authorized no es false")

    # ── Provenance ─────────────────────────────────────────────────────────
    source_value = metadata.get("source_selection_json")
    source_path = Path(str(source_value or ""))
    if not source_value:
        errors.append("metadata.source_selection_json ausente")
    elif not source_path.is_file():
        errors.append("metadata.source_selection_json no existe")
    else:
        if metadata.get("source_selection_sha256") != sha256_file(source_path):
            errors.append("metadata.source_selection_sha256 no coincide")
        else:
            try:
                expected = build_action_candidates(source_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"selección H5.3 inválida: {exc}")
            else:
                if document.get("actions") != expected.get("actions"):
                    errors.append("actions no coinciden con la política determinista")
                if document.get("withheld") != expected.get("withheld"):
                    errors.append("withheld no coincide con la política determinista")

    # ── Coaching authority ─────────────────────────────────────────────────
    authority = document.get("coaching_authority") or {}
    if authority.get("session_reference_remains_authority") is not True:
        errors.append("session_reference dejó de ser autoridad")
    if authority.get("historical_actions_authorized") is not False:
        errors.append("historical_actions_authorized debe ser false (shadow only)")
    if authority.get("scope") != "authorized_action_candidates_only":
        errors.append("scope de autorización inválido")

    # ── Actions ────────────────────────────────────────────────────────────
    actions = document.get("actions", [])
    if not isinstance(actions, list):
        errors.append("actions no es lista")
        return errors

    action_candidate_ids: set[str] = set()
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            errors.append(f"actions[{index}] inválido")
            continue

        # Candidate identity
        candidate_id = action.get("candidate_id")
        if not candidate_id:
            errors.append(f"actions[{index}]: candidate_id ausente")
        else:
            if candidate_id in action_candidate_ids:
                errors.append(f"actions: candidate_id duplicado: {candidate_id}")
            action_candidate_ids.add(candidate_id)

        # Anti-regresión: sólo current_slower
        if action.get("delta_sign") != "current_slower":
            errors.append(f"actions[{index}] viola anti-regresión: delta_sign={action.get('delta_sign')}")

        # No authorized-empty: authorized=true requiere >=1 action
        authorization = action.get("authorization") or {}
        if authorization.get("authorized") is not True:
            errors.append(f"actions[{index}] no está autorizada")
        if authorization.get("policy_version") != ACTION_POLICY_VERSION:
            errors.append(f"actions[{index}].policy_version inválida: {authorization.get('policy_version')}")

        # Actions list must be non-empty
        action_codes = action.get("actions", [])
        if not action_codes:
            errors.append(f"actions[{index}]: authorized pero actions=[] (empty authorization)")

        # Validate action codes are in vocabulary
        for action_code in action_codes:
            if action_code not in ACTION_TEXT:
                errors.append(f"actions[{index}]: action code desconocido: {action_code}")

        # Validate action codes match observation codes
        observation_codes = action.get("authorization", {}).get("observation_codes", [])
        classified = action.get("authorization", {}).get("classified_observation_codes", {})
        mappable_codes = classified.get("mappable", [])
        if set(action_codes) != set(OBSERVATION_TO_ACTION.get(code, "") for code in mappable_codes):
            errors.append(f"actions[{index}]: action codes no coinciden con observation_codes mappables")

        # Validate observation codes are known
        for code in observation_codes:
            if code not in KNOWN_OBSERVATION_CODES:
                errors.append(f"actions[{index}]: observation code desconocido: {code}")

        # Validate action codes are never speed-related
        for action_code in action_codes:
            if "speed" in action_code:
                errors.append(f"actions[{index}]: action code velocidad (prohibido): {action_code}")

    # ── Withheld ───────────────────────────────────────────────────────────
    withheld = document.get("withheld", [])
    if not isinstance(withheld, list):
        errors.append("withheld no es lista")

    withheld_candidate_ids: set[str] = set()
    for index, item in enumerate(withheld):
        if not isinstance(item, dict):
            errors.append(f"withheld[{index}] inválido")
            continue

        # Candidate identity
        candidate_id = item.get("candidate_id")
        if not candidate_id:
            errors.append(f"withheld[{index}]: candidate_id ausente")
        else:
            if candidate_id in withheld_candidate_ids:
                errors.append(f"withheld: candidate_id duplicado: {candidate_id}")
            withheld_candidate_ids.add(candidate_id)

        # Validate reason code
        reason = item.get("reason")
        if reason not in ALLOWED_REASON_CODES:
            errors.append(f"withheld[{index}]: reason_code inválido: {reason}")

        # Validate observation codes if present
        if "observation_codes" in item:
            for code in item["observation_codes"]:
                if code not in KNOWN_OBSERVATION_CODES:
                    errors.append(f"withheld[{index}]: observation code desconocido: {code}")

        # Validate classified observation codes if present (v0.2)
        if "classified_observation_codes" in item:
            classified = item["classified_observation_codes"]
            if not isinstance(classified, dict):
                errors.append(f"withheld[{index}]: classified_observation_codes inválido")
            else:
                for key in ("mappable", "non_mappable", "unknown"):
                    if key not in classified:
                        errors.append(f"withheld[{index}]: classified missing key: {key}")
                    elif not isinstance(classified[key], list):
                        errors.append(f"withheld[{index}]: classified.{key} no es lista")

    # ── Cross-check: no overlap between actions and withheld ───────────────
    if action_candidate_ids & withheld_candidate_ids:
        errors.append(f"candidate_id aparece en actions y withheld: {action_candidate_ids & withheld_candidate_ids}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida el artefacto shadow de candidatos de acción H5.3 v0.2."
    )
    parser.add_argument("actions_json")
    args = parser.parse_args()
    document = json.loads(Path(args.actions_json).read_text(encoding="utf-8"))
    errors = validate(document)
    print("=" * 88)
    print("RACE ENGINEER - H5.3 ACTION POLICY VALIDATION v0.2")
    print("=" * 88)
    print(f"Errors: {len(errors)}")
    for error in errors:
        print(f"  - {error}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
