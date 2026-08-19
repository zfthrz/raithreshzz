"""
validate_historical_candidate_eligibility.py — validator para el output
de ``historical_candidate_eligibility.py``.

Verifica contract, policy, status, reason codes, delta, geometría,
provenance y prohibiciones (no actions, no coaching, no scores).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ELIGIBLE_STATUS = "ELIGIBLE_FOR_SELECTION"
WITHHELD_STATUS = "WITHHELD"
AMBIGUOUS_STATUS = "AMBIGUOUS"
ERROR_STATUS = "ERROR"

ALLOWED_STATUSES = {ELIGIBLE_STATUS, WITHHELD_STATUS, AMBIGUOUS_STATUS, ERROR_STATUS}

EXPECTED_ELIGIBILITY_VERSION = "0.1"
EXPECTED_SCHEMA_VERSION = "1.0"

REQUIRED_POLICY_KEYS = (
    "historical_actions_authorized",
    "historical_coaching_authorized",
    "session_reference_remains_authority",
)

PROHIBITED_KEYS = (
    "score",
    "probability",
    "rank",
    "actions",
    "coaching",
    "causal",
    "recommendation",
)

ALLOWED_REASON_CODES = {
    "missing_context",
    "invalid_geometry",
    "insignificant_delta",
    "no_delta",
    "not_comparable",
    "no_channel_evidence",
    "ambiguous_localization",
    "ambiguous_human_label",
    "uncertain",
    "eligible_ok",
    "input_not_object",
    "invalid_record",
}


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _has_nan_or_inf(value: Any) -> bool:
    try:
        f = float(value)
        if f != f or f == float("inf") or f == float("-inf"):
            return True
    except (TypeError, ValueError):
        return True
    return False


def validate(eligibility: dict[str, Any]) -> list[str]:
    """
    Validate a single eligibility output document.

    Returns
    -------
    list[str]
        List of error strings (empty means PASS).
    """
    errors: list[str] = []

    # ── contract / metadata ──────────────────────────────────────────────
    contract = eligibility.get("contract") or eligibility.get("metadata")
    if not isinstance(contract, dict):
        errors.append("contract/metadata ausente o inválido")
    else:
        if contract.get("status") != "SHADOW_ELIGIBILITY_ONLY":
            errors.append(
                f"contract.status={contract.get('status')!r}, "
                f"expected 'SHADOW_ELIGIBILITY_ONLY'"
            )
        schema = contract.get("schema_version")
        if schema is not None:
            if not isinstance(schema, str):
                errors.append(f"contract.schema_version tipo={type(schema).__name__}")

        version = contract.get("eligibility_version")
        if version is not None and version != EXPECTED_ELIGIBILITY_VERSION:
            errors.append(f"contract.eligibility_version={version!r}")

    # ── policy ───────────────────────────────────────────────────────────
    policy = eligibility.get("policy", {})
    if not isinstance(policy, dict):
        errors.append("policy ausente o inválido")
    else:
        for key in REQUIRED_POLICY_KEYS:
            value = policy.get(key)
            if key == "historical_actions_authorized" and value is not False:
                errors.append(f"policy.{key} != false")
            elif key == "session_reference_remains_authority" and value is not True:
                errors.append(f"policy.{key} != true")
            elif key == "historical_coaching_authorized" and value is not False:
                errors.append(f"policy.{key} != false")
            elif value is None:
                errors.append(f"policy.{key} ausente")
        if policy.get("min_significant_delta_s") != 0.08:
            errors.append(
                f"policy.min_significant_delta_s={policy.get('min_significant_delta_s')}, "
                f"esperado 0.08"
            )

    # ── results ──────────────────────────────────────────────────────────
    results = eligibility.get("results")
    if results is None:
        # Fallback to legacy field names
        results = eligibility.get("eligibility_records")

    if not isinstance(results, list):
        errors.append("results/eligibility_records ausente o inválido")
        return errors

    # ── duplicate identity check ────────────────────────────────────────
    seen_audit_ids: set[str] = set()
    seen_candidate_ids: set[str] = set()

    for index, record in enumerate(results):
        field_prefix = f"result[{index}]"

        if not isinstance(record, dict):
            errors.append(f"{field_prefix}: no es objeto dict")
            continue

        # Check eligibility_status
        status = record.get("eligibility_status")
        if status not in ALLOWED_STATUSES:
            errors.append(
                f"{field_prefix}.eligibility_status inválido: {status!r}"
            )

        # Check reason_codes
        reason_codes = record.get("reason_codes")
        if not isinstance(reason_codes, list) or len(reason_codes) == 0:
            errors.append(f"{field_prefix}.reason_codes ausente o vacío")
        else:
            for code in reason_codes:
                if code not in ALLOWED_REASON_CODES:
                    errors.append(
                        f"{field_prefix}.reason_codes contiene código no autorizado: "
                        f"{code!r}"
                    )
            if len(reason_codes) != len(set(reason_codes)):
                errors.append(f"{field_prefix}.reason_codes tiene duplicados")

        # Check provenance
        provenance = record.get("provenance", {})
        if not isinstance(provenance, dict):
            errors.append(f"{field_prefix}.provenance inválido")
        else:
            audit_id = provenance.get("audit_id")
            if not audit_id:
                errors.append(f"{field_prefix}.provenance.audit_id ausente")
            else:
                if audit_id in seen_audit_ids:
                    errors.append(
                        f"{field_prefix}.provenance.audit_id duplicado: {audit_id!r}"
                    )
                seen_audit_ids.add(audit_id)

        # Check candidate identity duplication
        candidate_context = record.get("candidate_context", {})
        candidate_id = candidate_context.get("candidate_id")
        if candidate_id:
            if candidate_id in seen_candidate_ids:
                errors.append(
                    f"{field_prefix}.candidate_context.candidate_id duplicado: {candidate_id!r}"
                )
            seen_candidate_ids.add(candidate_id)

        # Check geometry

        # Check geometry
        geometry = record.get("geometry", {})
        start = geometry.get("start_distance_m")
        end = geometry.get("end_distance_m")
        if _is_numeric(start) and _has_nan_or_inf(start):
            errors.append(f"{field_prefix}.geometry.start_distance_m es NaN/Inf")
        if _is_numeric(end) and _has_nan_or_inf(end):
            errors.append(f"{field_prefix}.geometry.end_distance_m es NaN/Inf")

        # Check delta_change_s
        delta = record.get("delta_change_s")
        if _is_numeric(delta) and _has_nan_or_inf(delta):
            errors.append(f"{field_prefix}.delta_change_s es NaN/Inf")

        # Check no prohibited keys
        for prohibited in PROHIBITED_KEYS:
            if prohibited in record:
                errors.append(f"{field_prefix}: clave prohibida {prohibited}")

    # ── summary ──────────────────────────────────────────────────────────
    summary = eligibility.get("summary", {})
    if not isinstance(summary, dict):
        errors.append("summary ausente o inválido")
    elif not isinstance(summary.get("total_candidates"), int):
        errors.append("summary.total_candidates no es entero")
    else:
        by_status = summary.get("by_status", {})
        if not isinstance(by_status, dict):
            errors.append("summary.by_status inválido")
        else:
            for status_key, count in by_status.items():
                if status_key not in ALLOWED_STATUSES:
                    errors.append(f"summary.by_status clave inválida: {status_key!r}")

    return errors


def validate_single(record: dict[str, Any]) -> list[str]:
    """Validate a single eligibility record."""
    errors: list[str] = []

    status = record.get("eligibility_status")
    if status not in ALLOWED_STATUSES:
        errors.append(f"eligibility_status inválido: {status!r}")

    reason_codes = record.get("reason_codes", [])
    if not isinstance(reason_codes, list) or len(reason_codes) == 0:
        errors.append("reason_codes ausente o vacío")
    else:
        for code in reason_codes:
            if code not in ALLOWED_REASON_CODES:
                errors.append(f"reason_codes contiene código no autorizado: {code!r}")

    contract = record.get("contract", {})
    if isinstance(contract, dict) and contract.get("status") != "SHADOW_ELIGIBILITY_ONLY":
        errors.append(f"contract.status inválido: {contract.get('status')!r}")

    for key in PROHIBITED_KEYS:
        if key in record:
            errors.append(f"campo prohibido: {key}")

    provenance = record.get("provenance", {})
    if not provenance.get("audit_id"):
        errors.append("provenance.audit_id ausente")

    return errors


def main() -> int:
    parser = __build_parser__()
    args = parser.parse_args()

    path = Path(args.eligibility_json).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    document = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(document)

    print("=" * 88)
    print("RACE ENGINEER - HISTORICAL CANDIDATE ELIGIBILITY VALIDATOR v0.1")
    print("=" * 88)
    if errors:
        print(f"Errors: {len(errors)}")
        for error in errors:
            print(f"  - {error}")
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


def __build_parser__() -> "argparse.ArgumentParser":
    import argparse

    parser = argparse.ArgumentParser(
        description="Valida el output de historical_candidate_eligibility.py"
    )
    parser.add_argument("eligibility_json", help="Output de elegibilidad a validar.")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
