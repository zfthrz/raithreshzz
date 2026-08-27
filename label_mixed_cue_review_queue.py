"""Interactive resumable labeling for mixed-cue presentation review."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LABEL_SCHEMA_VERSION = "1.0"
KEYS = {
    "c": "COMBINED_BETTER",
    "f": "FOCUSED_PLUS_PROFILE_BETTER",
    "e": "EQUIVALENT",
    "a": "AMBIGUOUS",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_queue(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("review_items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("La cola debe contener review_items.")
    ids = [item.get("review_id") for item in items if isinstance(item, dict)]
    if len(ids) != len(items) or any(not isinstance(value, str) for value in ids):
        raise ValueError("La cola contiene review_id inválidos.")
    if len(ids) != len(set(ids)):
        raise ValueError("La cola contiene review_id duplicados.")
    return payload


def item_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    return dict(item)


def load_labels(path: Path, queue_path: Path) -> dict[str, Any]:
    queue_hash = file_sha256(queue_path)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (payload.get("metadata") or {}).get("source_queue_sha256") != queue_hash:
            raise ValueError("Los labels pertenecen a otra versión de la cola.")
        return payload
    return {
        "metadata": {
            "label_schema_version": LABEL_SCHEMA_VERSION,
            "source_queue_path": str(queue_path.resolve()),
            "source_queue_sha256": queue_hash,
            "created_at_utc": utc_now(),
            "updated_at_utc": utc_now(),
            "presentation_preference_authorized": False,
        },
        "labels": [],
    }


def save(path: Path, payload: dict[str, Any]) -> None:
    payload["metadata"]["updated_at_utc"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pending(queue: dict[str, Any], labels: dict[str, Any]) -> list[dict[str, Any]]:
    done = {record.get("review_id") for record in labels.get("labels") or []}
    return [item for item in queue["review_items"] if item["review_id"] not in done]


def upsert(labels: dict[str, Any], item: dict[str, Any], human_label: str, notes: str) -> None:
    record = {
        "review_id": item["review_id"],
        "human_label": human_label,
        "review_notes": notes,
        "reviewed_at_utc": utc_now(),
        "item_snapshot": item_snapshot(item),
    }
    for index, previous in enumerate(labels["labels"]):
        if previous.get("review_id") == item["review_id"]:
            labels["labels"][index] = record
            return
    labels["labels"].append(record)


def print_item(item: dict[str, Any], position: int, total: int) -> None:
    print("\n" + "=" * 88)
    print(f"MIXED CUE PRESENTATION REVIEW {position}/{total}")
    print("=" * 88)
    print(f"Track/session: {item.get('track')} / {item.get('session')}")
    print(f"Location: {item.get('location')}  Plan: {item.get('plan_label')}")
    print(f"Physical support: {item.get('channel_point_support')}")
    print(f"Dominant channel: {item.get('dominant_channel')}")
    print("\nCURRENT COMBINED:")
    print(item.get("combined_text"))
    print("\nFOCUSED CHANNEL:")
    for text in item.get("focused_event_texts") or []:
        print(f"- {text}")
    print("\nREFERENCE PROFILE:")
    print(item.get("reference_profile_text"))
    print("\n[c] COMBINED_BETTER")
    print("[f] FOCUSED_PLUS_PROFILE_BETTER")
    print("[e] EQUIVALENT")
    print("[a] AMBIGUOUS")
    print("[q] guardar y salir")


def main() -> int:
    parser = argparse.ArgumentParser(description="Label mixed-cue presentation review queue.")
    parser.add_argument("queue_json", type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    queue_path = args.queue_json.resolve()
    labels_path = args.labels.resolve()
    queue = load_queue(queue_path)
    labels = load_labels(labels_path, queue_path)
    remaining = pending(queue, labels)
    if args.summary or not remaining:
        print(f"Queue: {len(queue['review_items'])}  Reviewed: {len(labels['labels'])}  Pending: {len(remaining)}")
        return 0
    for position, item in enumerate(remaining, 1):
        print_item(item, position, len(remaining))
        while True:
            choice = input("\nLabel: ").strip().lower()
            if choice == "q":
                save(labels_path, labels)
                print(f"Guardado: {labels_path}")
                return 0
            human_label = KEYS.get(choice)
            if human_label is None:
                print("Entrada inválida.")
                continue
            notes = input("Notas opcionales: ").strip()
            upsert(labels, item, human_label, notes)
            save(labels_path, labels)
            break
    print(f"Revisión completa. Labels: {labels_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
