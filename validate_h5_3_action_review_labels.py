"""Validate human labels for a deterministic H5.3 action review queue."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from label_h5_3_action_review_queue import (
    LABEL_SCHEMA_VERSION,
    allowed_labels,
    file_sha256,
    item_snapshot,
    load_queue,
)


def validate(queue_path: Path, labels_path: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    queue = load_queue(queue_path)
    labels_data = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(labels_data, dict):
        return ["Labels root no es objeto."], warnings, {}
    metadata = labels_data.get("metadata")
    labels = labels_data.get("labels")
    if not isinstance(metadata, dict):
        errors.append("labels.metadata no es objeto.")
        metadata = {}
    if not isinstance(labels, list):
        errors.append("labels no es lista.")
        labels = []
    if metadata.get("label_schema_version") != LABEL_SCHEMA_VERSION:
        errors.append("metadata.label_schema_version inválida.")
    if metadata.get("source_queue_sha256") != file_sha256(queue_path):
        errors.append("metadata.source_queue_sha256 no coincide con la cola.")
    if metadata.get("historical_actions_authorized") is not False:
        errors.append("metadata.historical_actions_authorized debe ser false.")

    queue_by_id = {item["review_id"]: item for item in queue["review_items"]}
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    track_counts: Counter[str] = Counter()
    for index, record in enumerate(labels):
        if not isinstance(record, dict):
            errors.append(f"labels[{index}] no es objeto.")
            continue
        review_id = record.get("review_id")
        if not isinstance(review_id, str):
            errors.append(f"labels[{index}].review_id inválido.")
            continue
        if review_id in seen:
            errors.append(f"review_id duplicado: {review_id}")
        seen.add(review_id)
        source_item = queue_by_id.get(review_id)
        if source_item is None:
            errors.append(f"Label fuera de la cola: {review_id}")
            continue
        label = record.get("human_label")
        if label not in allowed_labels(source_item["decision"]):
            errors.append(f"{review_id}: human_label inválido para {source_item['decision']}: {label}")
        else:
            counts[label] += 1
        if not isinstance(record.get("review_notes"), str):
            errors.append(f"{review_id}: review_notes no es string.")
        if not isinstance(record.get("reviewed_at_utc"), str):
            errors.append(f"{review_id}: reviewed_at_utc ausente.")
        if record.get("item_snapshot") != item_snapshot(source_item):
            errors.append(f"{review_id}: item_snapshot no coincide con la cola.")
        track = str((source_item.get("context") or {}).get("track"))
        track_counts[track] += 1

    reviewed = seen & set(queue_by_id)
    unreviewed = len(queue_by_id) - len(reviewed)
    if unreviewed:
        warnings.append(f"Quedan {unreviewed} casos sin revisar.")
    if counts["UNSAFE_ACTION"]:
        warnings.append("Existen acciones marcadas UNSAFE_ACTION; la política debe permanecer shadow.")
    if counts["WITHHELD_BUT_ACTIONABLE"]:
        warnings.append("Existen casos WITHHELD_BUT_ACTIONABLE; requieren revisión de política separada.")
    summary = {
        "queue_items": len(queue_by_id),
        "reviewed": len(reviewed),
        "unreviewed": unreviewed,
        "counts": dict(sorted(counts.items())),
        "reviewed_by_track": dict(sorted(track_counts.items())),
        "historical_actions_authorized": False,
    }
    return errors, warnings, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate H5.3 action review labels.")
    parser.add_argument("queue_json")
    parser.add_argument("labels_json")
    args = parser.parse_args()
    queue_path = Path(args.queue_json).resolve()
    labels_path = Path(args.labels_json).resolve()
    errors, warnings, summary = validate(queue_path, labels_path)
    print("=" * 88)
    print("RACE ENGINEER - H5.3 ACTION REVIEW LABEL VALIDATOR v1.0")
    print("=" * 88)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print("RESULT: FAIL")
        return 1
    print("Authority: SHADOW ONLY")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
