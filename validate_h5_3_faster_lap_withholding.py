"""Validate H5.3g by reconstructing it from the hashed review sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from audit_h5_3_faster_lap_withholding import STATUS, build_audit


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    if metadata.get("status") != STATUS:
        errors.append("metadata.status is invalid")
    queue_value = metadata.get("source_queue_json")
    labels_value = metadata.get("source_labels_json")
    if not isinstance(queue_value, str) or not isinstance(labels_value, str):
        return errors + ["source queue/labels paths are missing"]
    try:
        expected = build_audit(Path(queue_value), Path(labels_value))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return errors + [f"source reconstruction failed: {exc}"]
    if document != expected:
        errors.append("document does not match deterministic source reconstruction")
    authority = document.get("contract") or {}
    if authority.get("historical_actions_authorized") is not False:
        errors.append("historical_actions_authorized must remain false")
    if authority.get("automatic_action_authorization") is not False:
        errors.append("automatic_action_authorization must remain false")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate H5.3g faster-lap withholding audit.")
    parser.add_argument("audit_json")
    args = parser.parse_args()
    path = Path(args.audit_json).resolve()
    document = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(document)
    print("=" * 88)
    print("RACE ENGINEER - H5.3g FASTER-LAP WITHHOLDING VALIDATOR v0.1")
    print("=" * 88)
    for error in errors:
        print(f"- {error}")
    print(f"Errors: {len(errors)}")
    print(f"RESULT: {'PASS' if not errors else 'FAIL'}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
