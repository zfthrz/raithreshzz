from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LABEL_SCHEMA_VERSION = "1.0"
VALID_LABELS = {"ACTIONABLE", "OBSERVATIONAL_ONLY", "NOT_COMPARABLE", "AMBIGUOUS"}
KEY_MAP = {
    "a": "ACTIONABLE",
    "o": "OBSERVATIONAL_ONLY",
    "n": "NOT_COMPARABLE",
    "m": "AMBIGUOUS",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("El dataset debe ser un objeto JSON.")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("dataset.candidates ausente/inválido.")
    seen = set()
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            raise ValueError(f"candidates[{index}] no es objeto.")
        audit_id = item.get("audit_id")
        if not isinstance(audit_id, str) or not audit_id:
            raise ValueError(f"candidates[{index}].audit_id inválido.")
        if audit_id in seen:
            raise ValueError(f"audit_id duplicado: {audit_id}")
        seen.add(audit_id)
    return payload


def load_labels(
    path: Path,
    dataset_path: Path,
    reviewer: str | None,
) -> dict[str, Any]:
    dataset_hash = file_sha256(dataset_path)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("El archivo de labels debe ser un objeto JSON.")
        metadata = payload.get("metadata") or {}
        if metadata.get("source_dataset_sha256") != dataset_hash:
            raise ValueError(
                "Los labels pertenecen a otro dataset o el dataset cambió."
            )
        if reviewer and not metadata.get("reviewer"):
            metadata["reviewer"] = reviewer
        payload["metadata"] = metadata
        if not isinstance(payload.get("labels"), list):
            raise ValueError("labels debe ser lista.")
        return payload
    return {
        "metadata": {
            "label_schema_version": LABEL_SCHEMA_VERSION,
            "created_at_utc": utc_now_iso(),
            "updated_at_utc": utc_now_iso(),
            "source_dataset_path": str(dataset_path.resolve()),
            "source_dataset_sha256": dataset_hash,
            "reviewer": reviewer,
            "semantics": (
                "Human audit labels for H5.3 shadow candidates. ACTIONABLE means "
                "a clear future coaching candidate; OBSERVATIONAL_ONLY means valid "
                "evidence without action; NOT_COMPARABLE and AMBIGUOUS reserve "
                "judgment."
            ),
        },
        "labels": [],
    }


def labels_by_id(labels_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in labels_data["labels"]:
        if isinstance(item, dict) and isinstance(item.get("audit_id"), str):
            result[item["audit_id"]] = item
    return result


def candidate_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    context = item.get("context") or {}
    return {
        "audit_id": item["audit_id"],
        "candidate_id": item.get("candidate_id"),
        "location_label": item.get("location_label"),
        "delta_sign": item.get("delta_sign"),
        "current_minus_historical_s": item.get("current_minus_historical_s"),
        "track": context.get("track"),
        "track_layout": context.get("track_layout"),
        "vehicle_variant": context.get("vehicle_variant"),
        "car_name_raw": context.get("car_name_raw"),
        "observational_channel_evidence": item.get(
            "observational_channel_evidence"
        ),
    }


def save_labels(path: Path, data: dict[str, Any]) -> None:
    data["metadata"]["updated_at_utc"] = utc_now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def upsert_label(
    labels_data: dict[str, Any],
    item: dict[str, Any],
    label: str,
    notes: str,
) -> None:
    if label not in VALID_LABELS:
        raise ValueError(
            f"human_label inválido: {label}. Permitidos: {sorted(VALID_LABELS)}"
        )
    audit_id = item["audit_id"]
    record = {
        "audit_id": audit_id,
        "human_label": label,
        "review_notes": notes,
        "reviewed_at_utc": utc_now_iso(),
        "candidate_snapshot": candidate_snapshot(item),
    }
    for index, old in enumerate(labels_data["labels"]):
        if old.get("audit_id") == audit_id:
            labels_data["labels"][index] = record
            return
    labels_data["labels"].append(record)


def build_pending_items(
    dataset_data: dict[str, Any],
    labels_data: dict[str, Any],
) -> list[dict[str, Any]]:
    existing = labels_by_id(labels_data)
    return [
        item
        for item in dataset_data["candidates"]
        if item["audit_id"] not in existing
    ]


def print_candidate(item: dict[str, Any], index: int, total: int) -> None:
    context = item.get("context") or {}
    evidence = item.get("evidence") or {}
    print()
    print("=" * 78)
    print(f"CANDIDATE {index}/{total}  audit_id={item['audit_id']}")
    print("=" * 78)
    print(f"Track: {context.get('track')} / {context.get('track_layout')}")
    print(
        f"Vehicle: {context.get('vehicle_variant')} "
        f"/ {context.get('car_name_raw')}"
    )
    print(f"Delta sign: {item.get('delta_sign')}")
    print(
        "Current - historical: "
        f"{item.get('current_minus_historical_s')} s"
    )
    print(f"Location: {item.get('location_label')}")
    print(
        "Zone evidence: "
        f"delta_change={evidence.get('delta_change_s')} s "
        f"[{evidence.get('start_distance_m')} - {evidence.get('end_distance_m')} m]"
    )
    channel = item.get("observational_channel_evidence") or {}
    if channel:
        print(
            "Channels: "
            f"speed={channel.get('speed_delta_avg')} "
            f"throttle={channel.get('throttle_delta_avg')} "
            f"brake={channel.get('brake_delta_avg')} "
            f"steering={channel.get('steering_delta_avg')}"
        )
    print("\nLabel semantics:")
    print("  ACTIONABLE        = candidato claro para coaching futuro.")
    print("  OBSERVATIONAL_ONLY = evidencia válida, sin acción asignable.")
    print("  NOT_COMPARABLE     = no debe compararse de esta forma.")
    print("  AMBIGUOUS          = evidencia insuficiente/conflictiva.")


def interactive_review(
    dataset_data: dict[str, Any],
    labels_data: dict[str, Any],
    labels_path: Path,
) -> int:
    pending = build_pending_items(dataset_data, labels_data)
    if not pending:
        print("No quedan candidatos pendientes.")
        return 0

    print()
    print("Controles: [a] ACTIONABLE  [o] OBSERVATIONAL_ONLY  [n] NOT_COMPARABLE  "
          "[m] AMBIGUOUS  [q] quit")

    for position, item in enumerate(pending, start=1):
        print_candidate(item, position, len(pending))
        while True:
            choice = input("\nLabel [a/o/n/m/q]: ").strip().lower()
            if choice == "q":
                save_labels(labels_path, labels_data)
                print(f"\nGuardado: {labels_path}")
                return 0
            label = KEY_MAP.get(choice)
            if label is None:
                print("Entrada inválida.")
                continue
            notes = input("Notas opcionales: ").strip()
            upsert_label(labels_data, item, label, notes)
            save_labels(labels_path, labels_data)
            print(f"Guardado: {label}")
            break

    print("\nAuditoría del dataset completa.")
    print(f"Labels: {labels_path}")
    return 0


def print_summary(labels_data: dict[str, Any]) -> None:
    counts = {label: 0 for label in sorted(VALID_LABELS)}
    for item in labels_data["labels"]:
        label = item.get("human_label")
        if label in counts:
            counts[label] += 1
    print()
    print("=" * 60)
    print("H5.3B AUDIT LABEL SUMMARY")
    print("=" * 60)
    print(f"Total reviewed: {len(labels_data['labels'])}")
    for label, count in counts.items():
        print(f"{label}: {count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Revisión humana de candidatos H5.3a en shadow."
    )
    parser.add_argument("dataset_json")
    parser.add_argument("--labels", default="h5_3_audit_labels.json")
    parser.add_argument("--reviewer", default=None)
    parser.add_argument("--summary", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dataset_path = Path(args.dataset_json).resolve()
    labels_path = Path(args.labels).resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(dataset_path)

    dataset_data = load_dataset(dataset_path)
    labels_data = load_labels(labels_path, dataset_path, args.reviewer)
    if args.summary:
        print_summary(labels_data)
        return 0
    return interactive_review(dataset_data, labels_data, labels_path)


if __name__ == "__main__":
    raise SystemExit(main())
