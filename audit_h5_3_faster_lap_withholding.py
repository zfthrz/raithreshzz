"""Reconstruct reviewed whole-lap-faster withholding evidence (H5.3g shadow)."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from label_h5_3_action_review_queue import load_queue
from validate_h5_3_action_review_labels import validate as validate_labels
from validate_historical_actions import validate as validate_actions


AUDIT_VERSION = "0.1"
SCHEMA_VERSION = "1.0"
STATUS = "SHADOW_FASTER_LAP_WITHHOLDING_REVIEW"


def file_sha256(path: Path) -> str:
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


def _resolve_source_path(value: Any, *, parent: Path, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} missing")
    path = Path(value)
    if not path.is_absolute():
        path = parent / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"{field} not found: {path}")
    return path


def _candidate_for_occurrence(occurrence: dict[str, Any]) -> dict[str, Any]:
    artifact_path = _resolve_source_path(
        occurrence.get("source_artifact"),
        parent=Path.cwd(),
        field="occurrence.source_artifact",
    )
    expected_hash = occurrence.get("source_artifact_sha256")
    if expected_hash != file_sha256(artifact_path):
        raise ValueError(f"source artifact hash mismatch: {artifact_path}")
    actions_document = _load_object(artifact_path)
    action_errors = validate_actions(actions_document)
    if action_errors:
        raise ValueError(
            f"invalid historical actions {artifact_path}: {'; '.join(action_errors)}"
        )
    selection_path = _resolve_source_path(
        (actions_document.get("metadata") or {}).get("source_selection_json"),
        parent=artifact_path.parent,
        field="metadata.source_selection_json",
    )
    selection = _load_object(selection_path)
    candidate_id = occurrence.get("candidate_id")
    matches = [
        candidate
        for candidate in selection.get("authorized_candidates", [])
        if isinstance(candidate, dict) and candidate.get("candidate_id") == candidate_id
    ]
    if len(matches) != 1:
        raise ValueError(f"candidate {candidate_id!r} is not unique in {selection_path}")
    candidate = matches[0]
    return {
        "source_artifact": str(artifact_path),
        "source_artifact_sha256": expected_hash,
        "source_selection_json": str(selection_path),
        "source_selection_sha256": file_sha256(selection_path),
        "candidate_id": candidate_id,
        "delta_change_s": candidate.get("delta_change_s"),
        "start_distance_m": candidate.get("start_distance_m"),
        "end_distance_m": candidate.get("end_distance_m"),
        "speed_delta_avg": candidate.get("speed_delta_avg"),
        "throttle_delta_avg": candidate.get("throttle_delta_avg"),
        "brake_delta_avg": candidate.get("brake_delta_avg"),
        "authorized_observations": candidate.get("authorized_observations"),
    }


def _evidence_status(occurrences: list[dict[str, Any]]) -> str:
    required = ("delta_change_s", "start_distance_m", "end_distance_m")
    if all(
        all(isinstance(occurrence.get(key), (int, float)) for key in required)
        and any(
            isinstance(occurrence.get(key), (int, float))
            for key in ("speed_delta_avg", "throttle_delta_avg", "brake_delta_avg")
        )
        for occurrence in occurrences
    ):
        return "QUANTITATIVE_EVIDENCE_AVAILABLE"
    return "QUANTITATIVE_EVIDENCE_PARTIAL"


def build_audit(queue_path: Path, labels_path: Path) -> dict[str, Any]:
    queue_path = Path(queue_path).resolve()
    labels_path = Path(labels_path).resolve()
    queue = load_queue(queue_path)
    labels = _load_object(labels_path)
    label_errors, _, _ = validate_labels(queue_path, labels_path)
    if label_errors:
        raise ValueError("invalid action review labels: " + "; ".join(label_errors))

    label_by_id = {
        label.get("review_id"): label
        for label in labels.get("labels", [])
        if isinstance(label, dict)
    }
    cases: list[dict[str, Any]] = []
    for item in queue.get("review_items", []):
        if (
            item.get("decision") != "WITHHELD"
            or item.get("delta_sign") != "current_faster"
        ):
            continue
        review_id = item.get("review_id")
        label = label_by_id.get(review_id)
        if label is None:
            raise ValueError(f"current_faster item is unreviewed: {review_id}")
        occurrences = [
            _candidate_for_occurrence(occurrence)
            for occurrence in item.get("occurrences", [])
        ]
        if not occurrences:
            raise ValueError(f"current_faster item has no occurrences: {review_id}")
        cases.append({
            "review_id": review_id,
            "context": item.get("context"),
            "location_label": item.get("location_label"),
            "decision": "WITHHELD",
            "withheld_reason": item.get("reason"),
            "delta_sign": "current_faster",
            "observation_codes": item.get("observation_codes"),
            "human_label": label.get("human_label"),
            "review_notes": label.get("review_notes"),
            "evidence_status": _evidence_status(occurrences),
            "occurrences": occurrences,
        })
    cases.sort(key=lambda case: (str((case.get("context") or {}).get("track")), str(case.get("location_label")), str(case.get("review_id"))))
    counts = Counter(case["human_label"] for case in cases)
    evidence_counts = Counter(case["evidence_status"] for case in cases)
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "audit_version": AUDIT_VERSION,
            "status": STATUS,
            "source_queue_json": str(queue_path),
            "source_queue_sha256": file_sha256(queue_path),
            "source_labels_json": str(labels_path),
            "source_labels_sha256": file_sha256(labels_path),
        },
        "contract": {
            "python_owns_quantitative_evidence": True,
            "human_labels_are_observational_evidence": True,
            "policy_changed": False,
            "automatic_action_authorization": False,
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        },
        "summary": {
            "reviewed_current_faster_withheld_count": len(cases),
            "human_labels": dict(sorted(counts.items())),
            "evidence_status": dict(sorted(evidence_counts.items())),
            "withheld_but_actionable_count": counts.get("WITHHELD_BUT_ACTIONABLE", 0),
            "ambiguous_count": counts.get("AMBIGUOUS", 0),
        },
        "cases": cases,
        "next_step": "REVIEW_LOCAL_ACTIONABILITY_POLICY_IN_SHADOW",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit reviewed H5.3 current_faster withholding evidence."
    )
    parser.add_argument("action_review_queue_json")
    parser.add_argument("action_review_labels_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = build_audit(Path(args.action_review_queue_json), Path(args.action_review_labels_json))
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("=" * 88)
    print("RACE ENGINEER - H5.3g FASTER-LAP WITHHOLDING AUDIT v0.1")
    print("=" * 88)
    print(f"Reviewed current_faster withheld cases: {output['summary']['reviewed_current_faster_withheld_count']}")
    for label, count in output["summary"]["human_labels"].items():
        print(f"  {label}: {count}")
    print(f"Output: {output_path}")
    print("Authority: SHADOW ONLY")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
