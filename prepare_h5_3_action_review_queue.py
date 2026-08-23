"""Build a deterministic, read-only human-review queue from H5.3 shadow actions.

The queue groups semantically equivalent candidates across sessions while preserving
every source occurrence. It never changes action policy, generated source artifacts
or coaching authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from validate_historical_actions import validate as validate_actions


SCHEMA_VERSION = "1.0"
STATUS = "H5_3_ACTION_REVIEW_QUEUE_READY"


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


def _selection_candidates(document: dict[str, Any], artifact_path: Path) -> dict[str, dict[str, Any]]:
    source_value = (document.get("metadata") or {}).get("source_selection_json")
    if not isinstance(source_value, str) or not source_value:
        raise ValueError(f"{artifact_path}: missing source_selection_json")
    source_path = Path(source_value)
    if not source_path.is_absolute():
        source_path = artifact_path.parent / source_path
    source = _load_object(source_path.resolve())
    result: dict[str, dict[str, Any]] = {}
    for candidate in source.get("authorized_candidates", []):
        if not isinstance(candidate, dict):
            continue
        candidate_id = candidate.get("candidate_id")
        if isinstance(candidate_id, str):
            result[candidate_id] = candidate
    return result


def _occurrence_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    """Preserve Python-owned quantitative evidence for human review."""
    return {
        "delta_change_s": candidate.get("delta_change_s"),
        "speed_delta_avg": candidate.get("speed_delta_avg"),
        "throttle_delta_avg": candidate.get("throttle_delta_avg"),
        "brake_delta_avg": candidate.get("brake_delta_avg"),
        "start_distance_m": candidate.get("start_distance_m"),
        "end_distance_m": candidate.get("end_distance_m"),
    }


def _review_signature(entry: dict[str, Any]) -> str:
    identity = {
        "decision": entry["decision"],
        "context": entry["context"],
        "location_label": entry.get("location_label"),
        "delta_sign": entry.get("delta_sign"),
        "actions": entry.get("actions", []),
        "reason": entry.get("reason"),
        "observation_codes": entry.get("observation_codes", []),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _entries_from_artifact(path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    path = path.resolve()
    document = _load_object(path)
    errors = validate_actions(document)
    if errors:
        raise ValueError(f"{path}: invalid historical actions: {'; '.join(errors)}")
    authority = document.get("coaching_authority") or {}
    if authority.get("historical_actions_authorized") is not False:
        raise ValueError(f"{path}: historical action authority must remain false")
    if authority.get("session_reference_remains_authority") is not True:
        raise ValueError(f"{path}: session reference authority was not preserved")

    candidates = _selection_candidates(document, path)
    occurrence_base = {
        "source_artifact": str(path),
        "source_artifact_sha256": file_sha256(path),
    }
    entries: list[dict[str, Any]] = []
    for item in document.get("actions", []):
        candidate_id = item["candidate_id"]
        candidate = candidates.get(candidate_id) or {}
        authorization = item.get("authorization") or {}
        entry = {
            "decision": "AUTHORIZED_SHADOW_ACTION",
            "context": item.get("context") or candidate.get("context") or {},
            "location_label": item.get("location_label"),
            "delta_sign": item.get("delta_sign"),
            "actions": sorted(item.get("actions", [])),
            "actions_text": sorted(item.get("actions_text", [])),
            "reason": None,
            "observation_codes": sorted(authorization.get("observation_codes", [])),
            "occurrence": {
                **occurrence_base,
                "candidate_id": candidate_id,
                **_occurrence_evidence(candidate),
                "delta_change_s": item.get("delta_change_s", candidate.get("delta_change_s")),
            },
        }
        entry["review_id"] = _review_signature(entry)
        entries.append(entry)

    for item in document.get("withheld", []):
        candidate_id = item["candidate_id"]
        candidate = candidates.get(candidate_id) or {}
        entry = {
            "decision": "WITHHELD",
            "context": candidate.get("context") or {},
            "location_label": item.get("location_label"),
            "delta_sign": item.get("delta_sign"),
            "actions": [],
            "actions_text": [],
            "reason": item.get("reason"),
            "observation_codes": sorted(item.get("observation_codes", [])),
            "occurrence": {
                **occurrence_base,
                "candidate_id": candidate_id,
                **_occurrence_evidence(candidate),
            },
        }
        entry["review_id"] = _review_signature(entry)
        entries.append(entry)
    return entries, occurrence_base


def build_queue(artifact_paths: Iterable[Path], *, input_root: Path | None = None) -> dict[str, Any]:
    paths = sorted({Path(path).resolve() for path in artifact_paths}, key=str)
    if not paths:
        raise ValueError("No historical_actions.json artifacts found")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prototypes: dict[str, dict[str, Any]] = {}
    source_artifacts: list[dict[str, str]] = []
    for path in paths:
        entries, source = _entries_from_artifact(path)
        source_artifacts.append(source)
        for entry in entries:
            review_id = entry.pop("review_id")
            occurrence = entry.pop("occurrence")
            prototypes.setdefault(review_id, entry)
            grouped[review_id].append(occurrence)

    review_items: list[dict[str, Any]] = []
    for review_id, prototype in prototypes.items():
        occurrences = sorted(
            grouped[review_id],
            key=lambda item: (item["source_artifact"], item["candidate_id"]),
        )
        review_items.append({
            "review_id": review_id,
            **prototype,
            "occurrence_count": len(occurrences),
            "occurrences": occurrences,
        })
    review_items.sort(key=lambda item: (
        str((item.get("context") or {}).get("track")),
        str(item.get("location_label")),
        item["decision"],
        item["review_id"],
    ))

    decision_counts: dict[str, int] = defaultdict(int)
    for item in review_items:
        decision_counts[item["decision"]] += 1
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "status": STATUS,
            "input_root": str(input_root.resolve()) if input_root else None,
            "source_artifact_count": len(paths),
            "source_artifacts": source_artifacts,
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
            "deduplication": "semantic identity with all source occurrences preserved",
        },
        "summary": {
            "review_item_count": len(review_items),
            "source_occurrence_count": sum(item["occurrence_count"] for item in review_items),
            "by_decision": dict(sorted(decision_counts.items())),
        },
        "review_items": review_items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a read-only H5.3 action review queue.")
    parser.add_argument("--input-root", default="data/generated/h5_3_shadow")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_root = Path(args.input_root).resolve()
    paths = list(input_root.rglob("historical_actions.json"))
    queue = build_queue(paths, input_root=input_root)
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 88)
    print("RACE ENGINEER - H5.3 ACTION REVIEW QUEUE v1.0")
    print("=" * 88)
    print(f"Validated source artifacts: {queue['metadata']['source_artifact_count']}")
    print(f"Review items: {queue['summary']['review_item_count']}")
    print(f"Source occurrences: {queue['summary']['source_occurrence_count']}")
    print(f"Output: {output_path}")
    print("Authority: SHADOW ONLY")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
