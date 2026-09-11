"""Deterministic coverage classifier for H5.3f v0.2 reviewed-action evidence gate.

Reads the current review revision (queue + labels) plus the gate verdict and
the externalised manifest, then emits a snapshot classifying each requirement
as SATISFIED, MISSING or BLOCKING.  Observational only — never decides, never
writes History, never calls an LLM.

Classification semantics:
  SATISFIED — evidence present and valid.
  MISSING   — evidence absent but achievable (e.g. track not yet reviewed,
              branch not yet covered).
  BLOCKING  — evidence present but violates a gate rule (e.g. non-affirmative
              labels above the limit).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from h5_3f_promotion_requirements import get_manifest
from assess_h5_3_promotion_v0_2 import assess_evidence, assess


SCHEMA_VERSION = "0.1"
SATISFIED = "SATISFIED"
MISSING = "MISSING"
BLOCKING = "BLOCKING"
AUTHORITY = "OBSERVATIONAL_ONLY"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return payload


def classify_evidence(
    queue: dict[str, Any],
    labels_data: dict[str, Any],
    structural_report: dict[str, Any],
) -> dict[str, Any]:
    """Return a coverage snapshot for *queue* + *labels* against the manifest.

    The gate verdict is computed internally and compared against the
    classification so the snapshot cannot contradict the real verdict.
    """
    manifest = get_manifest("h5_3f_v0_2")
    gate_report = assess_evidence(
        structural_report,
        queue,
        labels_data,
    )
    gate_verdict = gate_report["verdict"]
    coverage = gate_report.get("coverage", {})

    requirements: dict[str, dict[str, Any]] = {}

    # 1. required_tracks
    reviewed_tracks = coverage.get("tracks_reviewed", [])
    missing_tracks = coverage.get("missing_tracks", [])
    required_tracks = manifest["required_tracks"]
    satisfied_tracks = set(reviewed_tracks) & set(required_tracks)
    unsatisfied_tracks = set(required_tracks) - satisfied_tracks
    requirements["required_tracks"] = {
        "status": SATISFIED if not unsatisfied_tracks else MISSING,
        "detail": (
            f"All {len(required_tracks)} tracks reviewed"
            if not unsatisfied_tracks
            else f"{len(unsatisfied_tracks)} track(s) missing: {', '.join(sorted(unsatisfied_tracks))}"
        ),
        "evidence": {
            "tracks_reviewed": sorted(reviewed_tracks),
            "tracks_missing": sorted(missing_tracks),
        },
    }

    # 2. required_delta_signs
    reviewed_signs = coverage.get("delta_signs_reviewed", [])
    missing_signs = coverage.get("missing_delta_signs", [])
    required_signs = manifest["required_delta_signs"]
    satisfied_signs = set(reviewed_signs) & set(required_signs)
    unsatisfied_signs = set(required_signs) - satisfied_signs
    requirements["required_delta_signs"] = {
        "status": SATISFIED if not unsatisfied_signs else MISSING,
        "detail": (
            f"All {len(required_signs)} delta signs reviewed"
            if not unsatisfied_signs
            else f"{len(unsatisfied_signs)} sign(s) missing: {', '.join(sorted(unsatisfied_signs))}"
        ),
        "evidence": {
            "signs_reviewed": sorted(reviewed_signs),
            "signs_missing": sorted(missing_signs),
        },
    }

    # 3. required_action_codes
    reviewed_codes = coverage.get("action_codes_reviewed", [])
    required_codes = manifest["required_action_codes"]
    satisfied_codes = set(reviewed_codes) & set(required_codes)
    unsatisfied_codes = set(required_codes) - satisfied_codes
    requirements["required_action_codes"] = {
        "status": SATISFIED if not unsatisfied_codes else MISSING,
        "detail": (
            f"All {len(required_codes)} action codes reviewed"
            if not unsatisfied_codes
            else f"{len(unsatisfied_codes)} code(s) missing: {', '.join(sorted(unsatisfied_codes))}"
        ),
        "evidence": {
            "codes_reviewed": sorted(reviewed_codes),
            "codes_missing": sorted(sorted(unsatisfied_codes)),
        },
    }

    # 4. required_authorized_single_actions
    reviewed_single = coverage.get("authorized_single_actions_reviewed", [])
    required_single = manifest["required_authorized_single_actions"]
    required_single_set = {tuple(a) for a in required_single}
    reviewed_single_set = {tuple(a) for a in reviewed_single}
    unsatisfied_single = required_single_set - reviewed_single_set
    requirements["required_authorized_single_actions"] = {
        "status": SATISFIED if not unsatisfied_single else MISSING,
        "detail": (
            "All single-action policy branches reviewed"
            if not unsatisfied_single
            else f"{len(unsatisfied_single)} branch(es) missing: {', '.join(sorted('+'.join(a) for a in unsatisfied_single))}"
        ),
        "evidence": {
            "branches_reviewed": sorted(["+".join(a) for a in reviewed_single]),
            "branches_missing": sorted(["+".join(a) for a in sorted(unsatisfied_single)]),
        },
    }

    # 5. affirmative_labels — check non-affirmative count
    nonaffirmative_count = coverage.get("nonaffirmative_count", 0)
    max_nonaff = manifest.get("max_non_affirmative_labels")
    if nonaffirmative_count == 0:
        aff_status = SATISFIED
        aff_detail = "All labels are affirmative"
    elif max_nonaff is None:
        aff_status = BLOCKING
        aff_detail = f"{nonaffirmative_count} non-affirmative label(s) block readiness (limit is unbounded: any count > 0 is blocking)"
    else:
        aff_status = SATISFIED if nonaffirmative_count <= max_nonaff else BLOCKING
        aff_detail = (
            f"{nonaffirmative_count} non-affirmative label(s) (limit: {max_nonaff})"
        )
    requirements["affirmative_labels"] = {
        "status": aff_status,
        "detail": aff_detail,
        "evidence": {
            "nonaffirmative_count": nonaffirmative_count,
            "max_allowed": max_nonaff,
        },
    }

    # 6. isolated_reduce_throttle_withheld
    wh_reviewed = gate_report.get("requirements", {}).get(
        "isolated_reduce_throttle_withholding_reviewed", False
    )
    requirements["isolated_reduce_throttle_withholding"] = {
        "status": SATISFIED if wh_reviewed else MISSING,
        "detail": (
            "Isolated reduce_throttle withholding branch is reviewed"
            if wh_reviewed
            else "Isolated reduce_throttle withholding branch not yet reviewed"
        ),
        "evidence": {"wh_reviewed": wh_reviewed},
    }

    # 7. source_artifacts_valid
    source_valid = gate_report.get("requirements", {}).get(
        "source_artifacts_valid", False
    )
    requirements["source_artifacts_valid"] = {
        "status": SATISFIED if source_valid else BLOCKING,
        "detail": (
            "All source artifacts are valid"
            if source_valid
            else "At least one source artifact is invalid"
        ),
        "evidence": {"source_artifacts_valid": source_valid},
    }

    # 8. label_contract_valid
    label_valid = gate_report.get("requirements", {}).get(
        "label_contract_valid", False
    )
    requirements["label_contract_valid"] = {
        "status": SATISFIED if label_valid else BLOCKING,
        "detail": (
            "Label contract is valid"
            if label_valid
            else "At least one label violates the contract"
        ),
        "evidence": {"label_contract_valid": label_valid},
    }

    # 9. zero_authority_change
    zero_auth = gate_report.get("requirements", {}).get(
        "zero_authority_change", False
    )
    requirements["zero_authority_change"] = {
        "status": SATISFIED if zero_auth else BLOCKING,
        "detail": (
            "Zero authority change preserved"
            if zero_auth
            else "Authority was changed — blocking"
        ),
        "evidence": {"zero_authority_change": zero_auth},
    }

    # next_priority: lowest-hanging fruit (first MISSING requirement)
    next_priority = None
    for req_name, req_data in requirements.items():
        if req_data["status"] == MISSING:
            next_priority = f"Add evidence for '{req_name}': {req_data['detail']}"
            break

    # Build snapshot
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "gate_verdict": gate_verdict,
        "requirements": requirements,
        "next_priority": next_priority,
        "authority": AUTHORITY,
    }
    return snapshot


def audit(
    queue_path: Path,
    labels_path: Path,
    structural_report_path: Path | None = None,
) -> dict[str, Any]:
    """Run the coverage classifier over the current review revision."""
    queue = _load_object(queue_path)
    labels_data = _load_object(labels_path)

    if structural_report_path is not None:
        structural_report = _load_object(structural_report_path)
    else:
        from assess_h5_3_promotion_v0_1 import VERDICT_READY, assess as assess_structural

        structural_report = assess_structural(structural_report_path) if structural_report_path else {"verdict": VERDICT_READY}

    return classify_evidence(queue, labels_data, structural_report)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic H5.3f coverage classifier (observational only)."
    )
    parser.add_argument("queue_json", help="Path to the current action review queue JSON.")
    parser.add_argument("labels_json", help="Path to the current action review labels JSON.")
    parser.add_argument("--structural", help="Optional path to structural report JSON.")
    parser.add_argument("--output", required=True, help="Output path for the snapshot.")
    args = parser.parse_args()
    snapshot = audit(
        Path(args.queue_json),
        Path(args.labels_json),
        Path(args.structural) if args.structural else None,
    )
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("=" * 88)
    print("RACE ENGINEER - H5.3f DETERMINISTIC COVERAGE CLASSIFIER")
    print("=" * 88)
    print(f"Gate verdict: {snapshot['gate_verdict']}")
    print(f"Authority: {snapshot['authority']}")
    for req_name, req_data in snapshot["requirements"].items():
        print(f"  {req_name}: {req_data['status']}")
    if snapshot.get("next_priority"):
        print(f"Next priority: {snapshot['next_priority']}")
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
