"""Validate H5.3i by exact source reconstruction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from audit_h5_3_local_loss_recurrence import STATUS, build_audit


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    if metadata.get("status") != STATUS:
        errors.append("metadata.status is invalid")
    source = metadata.get("source_evaluation_json")
    if not isinstance(source, str) or not source:
        return errors + ["source evaluation path is missing"]
    try:
        expected = build_audit(Path(source))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return errors + [f"source reconstruction failed: {exc}"]
    if document != expected:
        errors.append("document does not match deterministic source reconstruction")
    contract = document.get("contract") or {}
    if contract.get("historical_actions_authorized") is not False:
        errors.append("historical actions must remain unauthorized")
    if contract.get("cross_zone_patterns_do_not_confirm_zone_recurrence") is not True:
        errors.append("cross-zone patterns cannot confirm exact-zone recurrence")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate H5.3i recurrence audit.")
    parser.add_argument("recurrence_audit_json")
    args = parser.parse_args()
    document = json.loads(Path(args.recurrence_audit_json).read_text(encoding="utf-8"))
    errors = validate(document)
    print("=" * 88)
    print("RACE ENGINEER - H5.3i LOCAL-LOSS RECURRENCE VALIDATOR v0.1")
    print("=" * 88)
    for error in errors:
        print(f"- {error}")
    print(f"Errors: {len(errors)}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
