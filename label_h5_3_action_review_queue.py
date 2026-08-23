"""Interactive, resumable human labeling for the H5.3 action review queue."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LABEL_SCHEMA_VERSION = "1.0"

ACTION_LABELS = {
    "ACTION_USEFUL",
    "OBSERVATIONAL_ONLY",
    "NOT_COMPARABLE",
    "AMBIGUOUS",
    "UNSAFE_ACTION",
}
WITHHELD_LABELS = {
    "CORRECTLY_WITHHELD",
    "WITHHELD_BUT_ACTIONABLE",
    "NOT_COMPARABLE",
    "AMBIGUOUS",
}
KEYS_BY_DECISION = {
    "AUTHORIZED_SHADOW_ACTION": {
        "u": "ACTION_USEFUL",
        "o": "OBSERVATIONAL_ONLY",
        "n": "NOT_COMPARABLE",
        "a": "AMBIGUOUS",
        "x": "UNSAFE_ACTION",
    },
    "WITHHELD": {
        "c": "CORRECTLY_WITHHELD",
        "w": "WITHHELD_BUT_ACTIONABLE",
        "n": "NOT_COMPARABLE",
        "a": "AMBIGUOUS",
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_queue(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("review_items"), list):
        raise ValueError("La cola H5.3 debe ser un objeto con review_items.")
    seen: set[str] = set()
    for index, item in enumerate(payload["review_items"]):
        if not isinstance(item, dict):
            raise ValueError(f"review_items[{index}] no es objeto.")
        review_id = item.get("review_id")
        decision = item.get("decision")
        if not isinstance(review_id, str) or not review_id:
            raise ValueError(f"review_items[{index}].review_id inválido.")
        if review_id in seen:
            raise ValueError(f"review_id duplicado: {review_id}")
        if decision not in KEYS_BY_DECISION:
            raise ValueError(f"review_items[{index}].decision inválido: {decision}")
        seen.add(review_id)
    return payload


def load_labels(path: Path, queue_path: Path, reviewer: str | None) -> dict[str, Any]:
    queue_hash = file_sha256(queue_path)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("labels"), list):
            raise ValueError("El archivo de labels H5.3 es inválido.")
        metadata = payload.get("metadata") or {}
        if metadata.get("source_queue_sha256") != queue_hash:
            raise ValueError("Los labels pertenecen a otra cola o la cola cambió.")
        if reviewer and not metadata.get("reviewer"):
            metadata["reviewer"] = reviewer
        payload["metadata"] = metadata
        return payload
    return {
        "metadata": {
            "label_schema_version": LABEL_SCHEMA_VERSION,
            "created_at_utc": utc_now_iso(),
            "updated_at_utc": utc_now_iso(),
            "source_queue_path": str(queue_path.resolve()),
            "source_queue_sha256": queue_hash,
            "reviewer": reviewer,
            "historical_actions_authorized": False,
            "semantics": "Human review of H5.3 shadow action usefulness and withholding decisions.",
        },
        "labels": [],
    }


def allowed_labels(decision: str) -> set[str]:
    if decision == "AUTHORIZED_SHADOW_ACTION":
        return ACTION_LABELS
    if decision == "WITHHELD":
        return WITHHELD_LABELS
    raise ValueError(f"decision inválido: {decision}")


def item_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": item.get("review_id"),
        "decision": item.get("decision"),
        "context": item.get("context"),
        "location_label": item.get("location_label"),
        "delta_sign": item.get("delta_sign"),
        "actions": item.get("actions"),
        "actions_text": item.get("actions_text"),
        "reason": item.get("reason"),
        "observation_codes": item.get("observation_codes"),
        "occurrence_count": item.get("occurrence_count"),
    }


def upsert_label(labels_data: dict[str, Any], item: dict[str, Any], label: str, notes: str) -> None:
    decision = item["decision"]
    if label not in allowed_labels(decision):
        raise ValueError(f"{label} no es válido para {decision}.")
    record = {
        "review_id": item["review_id"],
        "human_label": label,
        "review_notes": notes,
        "reviewed_at_utc": utc_now_iso(),
        "item_snapshot": item_snapshot(item),
    }
    for index, previous in enumerate(labels_data["labels"]):
        if previous.get("review_id") == item["review_id"]:
            labels_data["labels"][index] = record
            return
    labels_data["labels"].append(record)


def save_labels(path: Path, labels_data: dict[str, Any]) -> None:
    labels_data["metadata"]["updated_at_utc"] = utc_now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(labels_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pending_items(queue: dict[str, Any], labels_data: dict[str, Any]) -> list[dict[str, Any]]:
    reviewed = {
        item.get("review_id")
        for item in labels_data["labels"]
        if isinstance(item, dict)
    }
    return [item for item in queue["review_items"] if item["review_id"] not in reviewed]


def print_item(item: dict[str, Any], position: int, total: int) -> None:
    context = item.get("context") or {}
    print()
    print("=" * 88)
    print(f"H5.3 ACTION REVIEW {position}/{total}")
    print("=" * 88)
    print(f"Track: {context.get('track')} / {context.get('track_layout')}")
    print(f"Vehicle: {context.get('vehicle_variant')} / {context.get('car_name_raw')}")
    print(f"Location: {item.get('location_label')}")
    print(f"Current decision: {item.get('decision')}")
    print(f"Delta sign: {item.get('delta_sign')}")
    print(f"Observation codes: {', '.join(item.get('observation_codes') or [])}")
    if item["decision"] == "AUTHORIZED_SHADOW_ACTION":
        print(f"Proposed action: {', '.join(item.get('actions_text') or [])}")
    else:
        print(f"Withheld reason: {item.get('reason')}")
    print(f"Independent occurrences represented: {item.get('occurrence_count')}")
    deltas = [occurrence.get("delta_change_s") for occurrence in item.get("occurrences", [])]
    available_deltas = [value for value in deltas if isinstance(value, (int, float))]
    if available_deltas:
        print("Observed zone deltas: " + ", ".join(f"{value:+.3f} s" for value in available_deltas))
    quantitative_keys = (
        ("speed_delta_avg", "speed"),
        ("throttle_delta_avg", "throttle"),
        ("brake_delta_avg", "brake"),
    )
    for occurrence_index, occurrence in enumerate(item.get("occurrences", []), start=1):
        values = [
            f"{label}={occurrence.get(key):+.3f}"
            for key, label in quantitative_keys
            if isinstance(occurrence.get(key), (int, float))
        ]
        if values:
            prefix = "Observed channel mean deltas (current - historical)"
            if item.get("occurrence_count", 0) > 1:
                prefix += f" #{occurrence_index}"
            print(prefix + ": " + ", ".join(values))

    print("\nLabel semantics:")
    if item["decision"] == "AUTHORIZED_SHADOW_ACTION":
        print("  [u] ACTION_USEFUL       = la acción es clara y útil para el piloto.")
        print("  [o] OBSERVATIONAL_ONLY  = evidencia válida, pero no daría esta instrucción.")
        print("  [x] UNSAFE_ACTION       = la instrucción podría ser engañosa o perjudicial.")
    else:
        print("  [c] CORRECTLY_WITHHELD  = fue correcto no generar una instrucción.")
        print("  [w] WITHHELD_BUT_ACTIONABLE = debería existir una acción, pero no se inventa aquí.")
    print("  [n] NOT_COMPARABLE      = esta comparación no permite juzgar la acción.")
    print("  [a] AMBIGUOUS           = la evidencia no alcanza para decidir.")
    print("  [q] guardar y salir")


def print_summary(queue: dict[str, Any], labels_data: dict[str, Any]) -> None:
    counts: dict[str, int] = {}
    for record in labels_data["labels"]:
        label = record.get("human_label")
        counts[label] = counts.get(label, 0) + 1
    print()
    print("=" * 68)
    print("H5.3 ACTION REVIEW LABEL SUMMARY")
    print("=" * 68)
    print(f"Queue items: {len(queue['review_items'])}")
    print(f"Reviewed: {len(labels_data['labels'])}")
    print(f"Pending: {len(pending_items(queue, labels_data))}")
    for label, count in sorted(counts.items()):
        print(f"{label}: {count}")


def interactive_review(queue: dict[str, Any], labels_data: dict[str, Any], labels_path: Path) -> int:
    pending = pending_items(queue, labels_data)
    if not pending:
        print("No quedan casos H5.3 pendientes.")
        print_summary(queue, labels_data)
        return 0
    for position, item in enumerate(pending, start=1):
        print_item(item, position, len(pending))
        key_map = KEYS_BY_DECISION[item["decision"]]
        while True:
            choice = input("\nLabel: ").strip().lower()
            if choice == "q":
                save_labels(labels_path, labels_data)
                print(f"Guardado: {labels_path}")
                return 0
            label = key_map.get(choice)
            if label is None:
                print("Entrada inválida para este caso.")
                continue
            notes = input("Notas opcionales: ").strip()
            upsert_label(labels_data, item, label, notes)
            save_labels(labels_path, labels_data)
            print(f"Guardado: {label}")
            break
    print("\nRevisión H5.3 completa.")
    print_summary(queue, labels_data)
    print(f"Labels: {labels_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Review H5.3 shadow actions without changing authority.")
    parser.add_argument("queue_json")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--reviewer")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    queue_path = Path(args.queue_json).resolve()
    labels_path = Path(args.labels).resolve()
    queue = load_queue(queue_path)
    labels_data = load_labels(labels_path, queue_path, args.reviewer)
    if args.summary:
        print_summary(queue, labels_data)
        return 0
    return interactive_review(queue, labels_data, labels_path)


if __name__ == "__main__":
    raise SystemExit(main())
