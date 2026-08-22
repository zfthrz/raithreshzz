"""H5.3f v0.2 evidence gate for reviewed runtime shadow actions.

This gate extends, but does not replace, the v0.1 structural promotion report. Its
strongest verdict only means that evidence is ready for an explicit product decision;
it never enables historical coaching authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from assess_h5_3_promotion_v0_1 import VERDICT_READY, assess as assess_structural
from label_h5_3_action_review_queue import file_sha256, load_queue
from validate_h5_3_action_review_labels import validate as validate_labels
from validate_historical_actions import validate as validate_actions


ASSESS_VERSION = "0.2"
SCHEMA_VERSION = "1.0"
EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
EVIDENCE_READY = "EVIDENCE_READY_FOR_EXPLICIT_DECISION"

REQUIRED_TRACKS = {
    "Fuji Speedway",
    "Autodromo Enzo e Dino Ferrari",
    "Autódromo José Carlos Pace",
    "Autodromo Nazionale Monza",
}
REQUIRED_DELTA_SIGNS = {"current_slower", "current_faster"}
REQUIRED_ACTION_CODES = {
    "increase_brake",
    "increase_throttle",
    "reduce_brake",
    "reduce_throttle",
}
REQUIRED_AUTHORIZED_SINGLE_ACTIONS = {
    ("increase_brake",),
    ("increase_throttle",),
    ("reduce_brake",),
}
AFFIRMATIVE_LABEL_BY_DECISION = {
    "AUTHORIZED_SHADOW_ACTION": "ACTION_USEFUL",
    "WITHHELD": "CORRECTLY_WITHHELD",
}


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return payload


def _validate_source_artifacts(queue: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = queue.get("metadata") or {}
    sources = metadata.get("source_artifacts")
    if not isinstance(sources, list) or not sources:
        return ["action review queue has no source_artifacts provenance"]
    if metadata.get("source_artifact_count") != len(sources):
        errors.append("source_artifact_count does not match source_artifacts")
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"source_artifacts[{index}] is not an object")
            continue
        path_value = source.get("source_artifact")
        expected_hash = source.get("source_artifact_sha256")
        if not isinstance(path_value, str) or not path_value:
            errors.append(f"source_artifacts[{index}] has no path")
            continue
        path = Path(path_value)
        if not path.exists():
            errors.append(f"source artifact missing: {path}")
            continue
        if expected_hash != file_sha256(path):
            errors.append(f"source artifact hash mismatch: {path}")
            continue
        document = _load_object(path)
        action_errors = validate_actions(document)
        if action_errors:
            errors.append(f"source artifact invalid: {path}: {'; '.join(action_errors)}")
        authority = document.get("coaching_authority") or {}
        if authority.get("historical_actions_authorized") is not False:
            errors.append(f"source artifact changed authority: {path}")
    return errors


def assess_evidence(
    structural_report: dict[str, Any],
    queue: dict[str, Any],
    labels_data: dict[str, Any],
    *,
    label_errors: list[str] | None = None,
    source_errors: list[str] | None = None,
) -> dict[str, Any]:
    unmet: list[str] = []
    label_errors = label_errors or []
    source_errors = source_errors or []
    if structural_report.get("verdict") != VERDICT_READY:
        unmet.append("H5.3f v0.1 structural gate is not PROMOTION_READY")
    unmet.extend(f"label validation: {error}" for error in label_errors)
    unmet.extend(f"source validation: {error}" for error in source_errors)

    queue_metadata = queue.get("metadata") or {}
    if queue_metadata.get("historical_actions_authorized") is not False:
        unmet.append("queue historical_actions_authorized must remain false")
    if queue_metadata.get("session_reference_remains_authority") is not True:
        unmet.append("queue must preserve session reference authority")

    items = queue.get("review_items")
    labels = labels_data.get("labels")
    if not isinstance(items, list):
        items = []
        unmet.append("queue review_items is invalid")
    if not isinstance(labels, list):
        labels = []
        unmet.append("labels list is invalid")
    item_by_id = {
        item.get("review_id"): item
        for item in items
        if isinstance(item, dict) and isinstance(item.get("review_id"), str)
    }
    label_by_id = {
        label.get("review_id"): label
        for label in labels
        if isinstance(label, dict) and isinstance(label.get("review_id"), str)
    }
    unreviewed = sorted(set(item_by_id) - set(label_by_id))
    if unreviewed:
        unmet.append(f"{len(unreviewed)} action review items are unreviewed")

    tracks: set[str] = set()
    delta_signs: set[str] = set()
    action_codes: set[str] = set()
    authorized_single_actions: set[tuple[str, ...]] = set()
    decisions: set[str] = set()
    nonaffirmative: list[str] = []
    isolated_reduce_throttle_withheld = False
    for review_id, item in item_by_id.items():
        label = label_by_id.get(review_id)
        if label is None:
            continue
        context = item.get("context") or {}
        track = context.get("track")
        if isinstance(track, str) and track:
            tracks.add(track)
        delta_sign = item.get("delta_sign")
        if isinstance(delta_sign, str):
            delta_signs.add(delta_sign)
        decision = item.get("decision")
        if isinstance(decision, str):
            decisions.add(decision)
        actions = tuple(sorted(item.get("actions") or []))
        action_codes.update(actions)
        if decision == "AUTHORIZED_SHADOW_ACTION" and len(actions) == 1:
            authorized_single_actions.add(actions)
        if (
            decision == "WITHHELD"
            and item.get("reason") == "insufficient_action_context"
            and "current_throttle_higher" in (item.get("observation_codes") or [])
        ):
            isolated_reduce_throttle_withheld = True
        expected_label = AFFIRMATIVE_LABEL_BY_DECISION.get(str(decision))
        if label.get("human_label") != expected_label:
            nonaffirmative.append(review_id)

    missing_tracks = sorted(REQUIRED_TRACKS - tracks)
    missing_delta_signs = sorted(REQUIRED_DELTA_SIGNS - delta_signs)
    missing_action_codes = sorted(REQUIRED_ACTION_CODES - action_codes)
    missing_single_actions = sorted(
        "+".join(actions)
        for actions in REQUIRED_AUTHORIZED_SINGLE_ACTIONS - authorized_single_actions
    )
    missing_decisions = sorted(set(AFFIRMATIVE_LABEL_BY_DECISION) - decisions)
    if missing_tracks:
        unmet.append("missing reviewed action tracks: " + ", ".join(missing_tracks))
    if missing_delta_signs:
        unmet.append("missing reviewed delta signs: " + ", ".join(missing_delta_signs))
    if missing_action_codes:
        unmet.append("missing reviewed action codes: " + ", ".join(missing_action_codes))
    if missing_single_actions:
        unmet.append("missing authorized single-action branches: " + ", ".join(missing_single_actions))
    if missing_decisions:
        unmet.append("missing reviewed decisions: " + ", ".join(missing_decisions))
    if not isolated_reduce_throttle_withheld:
        unmet.append("isolated reduce_throttle withholding branch is not reviewed")
    if nonaffirmative:
        unmet.append(f"{len(nonaffirmative)} review labels are non-affirmative")

    verdict = EVIDENCE_READY if not unmet else EVIDENCE_INCOMPLETE
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "assess_version": ASSESS_VERSION,
        },
        "verdict": verdict,
        "structural_verdict": structural_report.get("verdict"),
        "requirements": {
            "all_items_reviewed": not unreviewed,
            "required_tracks_reviewed": not missing_tracks,
            "both_delta_signs_reviewed": not missing_delta_signs,
            "all_action_codes_reviewed": not missing_action_codes,
            "authorized_single_action_branches_reviewed": not missing_single_actions,
            "both_policy_decisions_reviewed": not missing_decisions,
            "isolated_reduce_throttle_withholding_reviewed": isolated_reduce_throttle_withheld,
            "all_labels_affirmative": not nonaffirmative,
            "source_artifacts_valid": not source_errors,
            "label_contract_valid": not label_errors,
            "zero_authority_change": queue_metadata.get("historical_actions_authorized") is False,
        },
        "coverage": {
            "tracks_reviewed": sorted(tracks),
            "missing_tracks": missing_tracks,
            "delta_signs_reviewed": sorted(delta_signs),
            "missing_delta_signs": missing_delta_signs,
            "action_codes_reviewed": sorted(action_codes),
            "missing_action_codes": missing_action_codes,
            "authorized_single_actions_reviewed": [list(actions) for actions in sorted(authorized_single_actions)],
            "missing_authorized_single_actions": missing_single_actions,
            "review_item_count": len(item_by_id),
            "unreviewed_count": len(unreviewed),
            "nonaffirmative_count": len(nonaffirmative),
        },
        "unmet": sorted(set(unmet)),
        "authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
            "automatic_promotion": False,
        },
    }


def assess(manifest_path: Path, queue_path: Path, labels_path: Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    queue_path = Path(queue_path).resolve()
    labels_path = Path(labels_path).resolve()
    structural_report = assess_structural(manifest_path)
    queue = load_queue(queue_path)
    labels_data = _load_object(labels_path)
    label_errors, _, _ = validate_labels(queue_path, labels_path)
    source_errors = _validate_source_artifacts(queue)
    report = assess_evidence(
        structural_report,
        queue,
        labels_data,
        label_errors=label_errors,
        source_errors=source_errors,
    )
    report["metadata"].update({
        "source_manifest_json": str(manifest_path),
        "source_manifest_sha256": file_sha256(manifest_path),
        "source_action_review_queue_json": str(queue_path),
        "source_action_review_queue_sha256": file_sha256(queue_path),
        "source_action_review_labels_json": str(labels_path),
        "source_action_review_labels_sha256": file_sha256(labels_path),
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="H5.3f v0.2 reviewed-action evidence gate.")
    parser.add_argument("manifest_json")
    parser.add_argument("action_review_queue_json")
    parser.add_argument("action_review_labels_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = assess(
        Path(args.manifest_json),
        Path(args.action_review_queue_json),
        Path(args.action_review_labels_json),
    )
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("=" * 88)
    print("RACE ENGINEER - H5.3f REVIEWED-ACTION EVIDENCE GATE v0.2")
    print("=" * 88)
    print(f"Verdict: {report['verdict']}")
    for item in report["unmet"]:
        print(f"  - {item}")
    print(f"Output: {output_path}")
    print("Authority: SHADOW ONLY - explicit decision still required")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
