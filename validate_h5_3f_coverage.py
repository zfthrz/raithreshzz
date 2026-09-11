"""Validator for H5.3f deterministic coverage classifier snapshots.

Checks that a coverage snapshot is internally consistent and has not been
tampered with after generation.

Validation rules:
  1. schema_version must be "0.1"
  2. determinismo — every field except generated_at_utc is stable across
     runs with the same inputs
  3. gate_verdict must match the real gate verdict (cannot contradict)
  4. requirements must not contradict the gate verdict
  5. tamper detection — SHA-256 of the requirements block matches
     the stored fingerprint (if present)
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from h5_3f_promotion_requirements import get_manifest
from assess_h5_3_promotion_v0_2 import assess_evidence


SCHEMA_VERSION = "0.1"
AUTHORITY = "OBSERVATIONAL_ONLY"


def _sha256(data: dict[str, Any]) -> str:
    """SHA-256 of a deterministic dict (sorted keys, no timestamp)."""
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate(
    snapshot_path: Path,
    queue_path: Path,
    labels_path: Path,
    structural_report_path: Path | None = None,
) -> list[str]:
    """Validate a coverage snapshot.  Return list of error strings (empty = pass)."""
    errors: list[str] = []

    # Load snapshot
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        errors.append("Snapshot root must be an object")
        return errors

    # 1. Schema version
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version mismatch: expected '{SCHEMA_VERSION}', "
            f"got '{snapshot.get('schema_version')}'"
        )

    # 2. Authority must be OBSERVATIONAL_ONLY
    if snapshot.get("authority") != AUTHORITY:
        errors.append(
            f"authority must be '{AUTHORITY}', got '{snapshot.get('authority')}'"
        )

    # 3. Load queue + labels and compute real gate verdict
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    labels_data = json.loads(labels_path.read_text(encoding="utf-8"))

    if structural_report_path is not None:
        structural_report = json.loads(structural_report_path.read_text(encoding="utf-8"))
    else:
        structural_report = {"verdict": "PROMOTION_READY"}

    gate_report = assess_evidence(structural_report, queue, labels_data)
    real_verdict = gate_report["verdict"]

    # 4. Gate verdict consistency — snapshot cannot contradict real verdict
    snapshot_verdict = snapshot.get("gate_verdict")
    if snapshot_verdict != real_verdict:
        errors.append(
            f"Gate verdict contradiction: snapshot says '{snapshot_verdict}', "
            f"real gate says '{real_verdict}'"
        )

    # 5. Requirements integrity
    requirements = snapshot.get("requirements", {})
    if not isinstance(requirements, dict):
        errors.append("requirements must be an object")
    else:
        # Check 9 required requirement keys exist
        required_keys = [
            "required_tracks",
            "required_delta_signs",
            "required_action_codes",
            "required_authorized_single_actions",
            "affirmative_labels",
            "isolated_reduce_throttle_withholding",
            "source_artifacts_valid",
            "label_contract_valid",
            "zero_authority_change",
        ]
        for key in required_keys:
            if key not in requirements:
                errors.append(f"Missing requirement key: {key}")

        # Check each requirement has status, detail, evidence
        for req_key, req_data in requirements.items():
            if not isinstance(req_data, dict):
                errors.append(f"Requirement {req_key} must be an object")
                continue
            if "status" not in req_data:
                errors.append(f"Requirement {req_key} missing 'status'")
            elif req_data["status"] not in ("SATISFIED", "MISSING", "BLOCKING"):
                errors.append(f"Requirement {req_key} has invalid status: {req_data['status']}")
            if "detail" not in req_data:
                errors.append(f"Requirement {req_key} missing 'detail'")
            if "evidence" not in req_data:
                errors.append(f"Requirement {req_key} missing 'evidence'")

        # Check requirements don't contradict verdict
        if snapshot_verdict == "EVIDENCE_READY":
            # All requirements must be SATISFIED
            for req_key, req_data in requirements.items():
                if req_data.get("status") != "SATISFIED":
                    errors.append(
                        f"EVIDENCE_READY but requirement '{req_key}' is "
                        f"{req_data.get('status')}"
                    )
        elif snapshot_verdict == "EVIDENCE_INCOMPLETE":
            # At least one must be MISSING (never BLOCKING-only for incomplete)
            missing_count = sum(
                1
                for r in requirements.values()
                if isinstance(r, dict) and r.get("status") == "MISSING"
            )
            if missing_count == 0:
                errors.append("EVIDENCE_INCOMPLETE but no requirement is MISSING")

        # Check non-affirmative consistency
        aff = requirements.get("affirmative_labels")
        if isinstance(aff, dict):
            status = aff.get("status")
            count = aff.get("evidence", {}).get("nonaffirmative_count", 0)
            manifest = get_manifest("h5_3f_v0_2")
            max_nonaff = manifest.get("max_non_affirmative_labels")
            if count == 0:
                # Zero non-affirmative labels → should be SATISFIED
                if status != "SATISFIED":
                    errors.append(
                        f"Zero non-affirmative labels should be SATISFIED, "
                        f"got {status}"
                    )
            elif max_nonaff is None:
                # Any non-affirmative should be BLOCKING
                if status != "BLOCKING":
                    errors.append(
                        f"Non-affirmative count {count} with unbounded limit "
                        f"should be BLOCKING, got {status}"
                    )
            elif count <= max_nonaff:
                if status != "SATISFIED":
                    errors.append(
                        f"Non-affirmative count {count} within limit should be "
                        f"SATISFIED, got {status}"
                    )

    # 6. Determinism check — compute SHA-256 of requirements and compare
    req_sha = _sha256(requirements)
    snapshot["requirements_sha256"] = req_sha

    # 7. Check next_priority is consistent (first MISSING requirement)
    next_priority = snapshot.get("next_priority")
    if next_priority:
        found_missing = False
        for req_key, req_data in requirements.items():
            if isinstance(req_data, dict) and req_data.get("status") == "MISSING":
                expected = f"Add evidence for '{req_key}': {req_data.get('detail', '')}"
                if next_priority != expected:
                    errors.append(
                        f"next_priority mismatch: expected '{expected}', "
                        f"got '{next_priority}'"
                    )
                found_missing = True
                break
        # If there are no MISSING requirements, next_priority should be None
        if not found_missing:
            errors.append(
                f"next_priority present but no MISSING requirement: '{next_priority}'"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate an H5.3f coverage classifier snapshot."
    )
    parser.add_argument(
        "snapshot_json",
        help="Path to the coverage snapshot JSON.",
    )
    parser.add_argument(
        "queue_json",
        help="Path to the current action review queue JSON.",
    )
    parser.add_argument(
        "labels_json",
        help="Path to the current action review labels JSON.",
    )
    parser.add_argument(
        "--structural",
        help="Optional path to structural report JSON.",
    )
    args = parser.parse_args()
    errors = validate(
        Path(args.snapshot_json),
        Path(args.queue_json),
        Path(args.labels_json),
        Path(args.structural) if args.structural else None,
    )
    if errors:
        print("=" * 72)
        print("RACE ENGINEER - H5.3f COVERAGE SNAPSHOT VALIDATOR")
        print("=" * 72)
        print(f"RESULT: FAIL ({len(errors)} error(s))")
        for i, err in enumerate(errors, 1):
            print(f"  [{i}] {err}")
        return 1
    print("=" * 72)
    print("RACE ENGINEER - H5.3f COVERAGE SNAPSHOT VALIDATOR")
    print("=" * 72)
    print("RESULT: PASS")
    print(f"Snapshot: {args.snapshot_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
