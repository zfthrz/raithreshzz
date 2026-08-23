"""Validate H5.3h by exact reconstruction from the validated H5.3g audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluate_h5_3_local_loss_policy import STATUS, build_evaluation


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    if metadata.get("status") != STATUS:
        errors.append("metadata.status is invalid")
    source = metadata.get("source_audit_json")
    if not isinstance(source, str) or not source:
        return errors + ["source audit path is missing"]
    try:
        expected = build_evaluation(Path(source))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return errors + [f"source reconstruction failed: {exc}"]
    if document != expected:
        errors.append("document does not match deterministic source reconstruction")
    contract = document.get("contract") or {}
    if contract.get("local_policy_candidates_authorized") is not False:
        errors.append("local policy candidates must remain unauthorized")
    if contract.get("historical_actions_authorized") is not False:
        errors.append("historical actions must remain unauthorized")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate H5.3h local-loss experiment.")
    parser.add_argument("evaluation_json")
    args = parser.parse_args()
    document = json.loads(Path(args.evaluation_json).read_text(encoding="utf-8"))
    errors = validate(document)
    print("=" * 88)
    print("RACE ENGINEER - H5.3h LOCAL-LOSS POLICY VALIDATOR v0.1")
    print("=" * 88)
    for error in errors:
        print(f"- {error}")
    print(f"Errors: {len(errors)}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
