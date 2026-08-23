"""Evaluate a conservative local-loss hypothesis over validated H5.3g evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from validate_h5_3_faster_lap_withholding import validate as validate_audit


POLICY_VERSION = "0.1"
SCHEMA_VERSION = "1.0"
STATUS = "SHADOW_LOCAL_LOSS_POLICY_EXPERIMENT"
MIN_LOCAL_LOSS_S = 0.20


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("audit JSON root must be an object")
    errors = validate_audit(document)
    if errors:
        raise ValueError("invalid H5.3g audit: " + "; ".join(errors))
    return document


def _evaluate_occurrence(occurrence: dict[str, Any]) -> dict[str, Any]:
    delta = occurrence.get("delta_change_s")
    throttle = occurrence.get("throttle_delta_avg")
    brake = occurrence.get("brake_delta_avg")
    gates = {
        "local_loss_meets_minimum": (
            isinstance(delta, (int, float)) and delta >= MIN_LOCAL_LOSS_S
        ),
        "throttle_evidence_available": isinstance(throttle, (int, float)),
        "brake_evidence_available": isinstance(brake, (int, float)),
        "spatial_bounds_available": all(
            isinstance(occurrence.get(key), (int, float))
            for key in ("start_distance_m", "end_distance_m")
        ),
    }
    return {
        "candidate_id": occurrence.get("candidate_id"),
        "delta_change_s": delta,
        "start_distance_m": occurrence.get("start_distance_m"),
        "end_distance_m": occurrence.get("end_distance_m"),
        "speed_delta_avg": occurrence.get("speed_delta_avg"),
        "throttle_delta_avg": throttle,
        "brake_delta_avg": brake,
        "gates": gates,
        "passes_quantitative_gates": all(gates.values()),
    }


def build_evaluation(audit_path: Path) -> dict[str, Any]:
    audit_path = Path(audit_path).resolve()
    audit = _load(audit_path)
    candidates: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    for case in audit.get("cases", []):
        occurrences = [_evaluate_occurrence(item) for item in case.get("occurrences", [])]
        human_gate = case.get("human_label") == "WITHHELD_BUT_ACTIONABLE"
        quantitative_gate = bool(occurrences) and all(
            item["passes_quantitative_gates"] for item in occurrences
        )
        base = {
            "review_id": case.get("review_id"),
            "context": case.get("context"),
            "location_label": case.get("location_label"),
            "human_label": case.get("human_label"),
            "occurrences": occurrences,
            "gates": {
                "human_withheld_but_actionable": human_gate,
                "all_occurrences_pass_quantitative_gates": quantitative_gate,
            },
        }
        if human_gate and quantitative_gate:
            candidates.append({
                **base,
                "decision": "LOCAL_POLICY_CANDIDATE",
                "authorization": {
                    "authorized": False,
                    "reason": "shadow_hypothesis_only",
                },
            })
        else:
            failed = [name for name, passed in base["gates"].items() if not passed]
            withheld.append({
                **base,
                "decision": "WITHHELD",
                "reason": "local_policy_gates_not_met",
                "failed_gates": failed,
            })
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "status": STATUS,
            "source_audit_json": str(audit_path),
            "source_audit_sha256": file_sha256(audit_path),
        },
        "policy": {
            "minimum_local_loss_s": MIN_LOCAL_LOSS_S,
            "required_human_label": "WITHHELD_BUT_ACTIONABLE",
            "require_throttle_and_brake_evidence": True,
            "require_all_occurrences_to_pass": True,
            "automatic_action_generation": False,
        },
        "contract": {
            "shadow_only": True,
            "existing_action_policy_changed": False,
            "local_policy_candidates_authorized": False,
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        },
        "summary": {
            "source_case_count": len(audit.get("cases", [])),
            "local_policy_candidate_count": len(candidates),
            "withheld_count": len(withheld),
        },
        "local_policy_candidates": candidates,
        "withheld": withheld,
        "next_step": "COLLECT_INDEPENDENT_CONFIRMING_CURRENT_FASTER_CASES",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate H5.3h local-loss policy in shadow.")
    parser.add_argument("faster_lap_withholding_audit_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_evaluation(Path(args.faster_lap_withholding_audit_json))
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("=" * 88)
    print("RACE ENGINEER - H5.3h LOCAL-LOSS POLICY EXPERIMENT v0.1")
    print("=" * 88)
    print(f"Local policy candidates: {result['summary']['local_policy_candidate_count']}")
    print(f"Withheld: {result['summary']['withheld_count']}")
    print("Authority: SHADOW ONLY - NO ACTIONS AUTHORIZED")
    print(f"Output: {output}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
