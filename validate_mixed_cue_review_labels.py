"""Validate mixed-cue presentation human labels against an exact queue."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from label_mixed_cue_review_queue import (
    KEYS,
    LABEL_SCHEMA_VERSION,
    file_sha256,
    item_snapshot,
    load_queue,
)


def validate(queue_path: Path, labels_path: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    queue = load_queue(queue_path)
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    metadata = labels.get("metadata") if isinstance(labels, dict) else None
    records = labels.get("labels") if isinstance(labels, dict) else None
    if not isinstance(metadata, dict) or not isinstance(records, list):
        return ["El archivo de labels es inválido."], warnings, {}
    if metadata.get("label_schema_version") != LABEL_SCHEMA_VERSION:
        errors.append("label_schema_version inválida.")
    if metadata.get("source_queue_sha256") != file_sha256(queue_path):
        errors.append("source_queue_sha256 no coincide.")
    if metadata.get("presentation_preference_authorized") is not False:
        errors.append("presentation_preference_authorized debe ser false.")
    by_id = {item["review_id"]: item for item in queue["review_items"]}
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"labels[{index}] no es objeto.")
            continue
        review_id = record.get("review_id")
        if review_id in seen:
            errors.append(f"review_id duplicado: {review_id}")
        seen.add(review_id)
        item = by_id.get(review_id)
        if item is None:
            errors.append(f"Label fuera de la cola: {review_id}")
            continue
        human_label = record.get("human_label")
        if human_label not in set(KEYS.values()):
            errors.append(f"{review_id}: human_label inválido.")
        else:
            counts[human_label] += 1
        if record.get("item_snapshot") != item_snapshot(item):
            errors.append(f"{review_id}: item_snapshot no coincide.")
        if not isinstance(record.get("review_notes"), str):
            errors.append(f"{review_id}: review_notes no es string.")
    reviewed = len(seen & set(by_id))
    pending = len(by_id) - reviewed
    if pending:
        warnings.append(f"Quedan {pending} casos sin revisar.")
    return errors, warnings, {
        "queue_items": len(by_id),
        "reviewed": reviewed,
        "pending": pending,
        "counts": dict(sorted(counts.items())),
        "presentation_preference_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate mixed-cue review labels.")
    parser.add_argument("queue_json", type=Path)
    parser.add_argument("labels_json", type=Path)
    args = parser.parse_args()
    errors, warnings, summary = validate(args.queue_json.resolve(), args.labels_json.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print("RESULT: FAIL" if errors else "RESULT: PASS")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
