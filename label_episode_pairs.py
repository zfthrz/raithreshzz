from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LABEL_SCHEMA_VERSION = "1.1"
VALID_LABELS = {"SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def load_queue(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("La cola debe ser un objeto JSON.")

    metadata = data.get("metadata")
    queue = data.get("queue")
    if not isinstance(metadata, dict):
        raise ValueError("metadata ausente en la cola.")
    if not isinstance(queue, list):
        raise ValueError("queue ausente o inválida.")

    seen = set()
    for index, item in enumerate(queue):
        if not isinstance(item, dict):
            raise ValueError(f"queue[{index}] no es objeto.")
        pair_id = item.get("pair_id")
        if not isinstance(pair_id, str) or not pair_id:
            raise ValueError(f"queue[{index}].pair_id inválido.")
        if pair_id in seen:
            raise ValueError(f"pair_id duplicado en queue: {pair_id}")
        seen.add(pair_id)
        if not isinstance(item.get("features"), dict):
            raise ValueError(f"queue[{index}].features inválido.")

    return data


def load_labels(path: Path, queue_path: Path, reviewer: str | None) -> dict[str, Any]:
    queue_hash = file_sha256(queue_path)

    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("El archivo de labels debe ser un objeto JSON.")
        metadata = data.get("metadata", {})
        if metadata.get("source_queue_sha256") != queue_hash:
            raise ValueError(
                "El archivo de labels pertenece a otra cola o la cola cambió. "
                "No se mezclan automáticamente."
            )
        if reviewer and not metadata.get("reviewer"):
            metadata["reviewer"] = reviewer
        data["metadata"] = metadata
        if not isinstance(data.get("labels"), list):
            raise ValueError("labels debe ser lista.")
        return data

    return {
        "metadata": {
            "label_schema_version": LABEL_SCHEMA_VERSION,
            "created_at_utc": utc_now_iso(),
            "updated_at_utc": utc_now_iso(),
            "source_queue_path": str(queue_path.resolve()),
            "source_queue_sha256": queue_hash,
            "reviewer": reviewer,
            "semantics": (
                "Human calibration labels. SAME means same general location and "
                "driving-difference type, not proven identical causality."
            ),
        },
        "labels": [],
    }


def labels_by_id(labels_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in labels_data["labels"]:
        if isinstance(item, dict) and isinstance(item.get("pair_id"), str):
            result[item["pair_id"]] = item
    return result


def compact_feature_snapshot(features: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "track", "session_a", "session_b", "episode_pk_a", "episode_pk_b",
        "episode_id_a", "episode_id_b", "start_distance_a_m", "end_distance_a_m",
        "center_distance_a_m", "start_distance_b_m", "end_distance_b_m",
        "center_distance_b_m", "center_distance_abs_diff_m", "overlap_m",
        "overlap_over_union", "overlap_over_shorter", "channel_jaccard",
        "channels_a", "channels_b", "shared_channels", "channels_only_a",
        "channels_only_b", "action_time_loss_a_s", "action_time_loss_b_s",
        "action_time_loss_similarity", "per_channel_metrics",
    ]
    return {key: features.get(key) for key in keys}


def save_labels(path: Path, data: dict[str, Any]) -> None:
    data["metadata"]["updated_at_utc"] = utc_now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def fmt(value: Any, digits: int = 3) -> str:
    number = safe_float(value)
    return "N/D" if number is None else f"{number:.{digits}f}"


def print_pair(item: dict[str, Any], index: int, total: int) -> None:
    pair_id = item["pair_id"]
    f = item["features"]

    print()
    print("=" * 78)
    print(f"PAIR {index}/{total}  id={pair_id}")
    print("=" * 78)
    print(f"Track: {f.get('track')}")
    print(
        "A: "
        f"session={f.get('session_a')} episode_pk={f.get('episode_pk_a')} "
        f"episode_id={f.get('episode_id_a')}"
    )
    print(
        "B: "
        f"session={f.get('session_b')} episode_pk={f.get('episode_pk_b')} "
        f"episode_id={f.get('episode_id_b')}"
    )

    print("\nSpatial:")
    print(
        "  A: "
        f"{fmt(f.get('start_distance_a_m'), 1)} - {fmt(f.get('end_distance_a_m'), 1)} m "
        f"center={fmt(f.get('center_distance_a_m'), 1)}"
    )
    print(
        "  B: "
        f"{fmt(f.get('start_distance_b_m'), 1)} - {fmt(f.get('end_distance_b_m'), 1)} m "
        f"center={fmt(f.get('center_distance_b_m'), 1)}"
    )
    print(f"  center diff: {fmt(f.get('center_distance_abs_diff_m'), 1)} m")
    print(f"  overlap / union: {fmt(f.get('overlap_over_union'))}")
    print(f"  overlap / shorter: {fmt(f.get('overlap_over_shorter'))}")

    print("\nChannels:")
    print(f"  A: {f.get('channels_a')}")
    print(f"  B: {f.get('channels_b')}")
    print(f"  shared: {f.get('shared_channels')}")
    print(f"  Jaccard: {fmt(f.get('channel_jaccard'))}")

    print("\nTemporal impact (secondary evidence):")
    print(f"  A: {fmt(f.get('action_time_loss_a_s'), 4)} s")
    print(f"  B: {fmt(f.get('action_time_loss_b_s'), 4)} s")
    print(f"  similarity: {fmt(f.get('action_time_loss_similarity'))}")

    per_channel = f.get("per_channel_metrics", {})
    if isinstance(per_channel, dict) and per_channel:
        print("\nShared-channel shape metrics:")
        for channel, metrics in per_channel.items():
            if not isinstance(metrics, dict):
                continue
            print(f"  {channel}:")
            print(f"    coverage abs diff: {fmt(metrics.get('coverage_abs_diff'))}")
            print(f"    onset offset diff: {fmt(metrics.get('onset_offset_abs_diff_m'), 1)} m")
            print(f"    end offset diff: {fmt(metrics.get('end_offset_abs_diff_m'), 1)} m")
            print(f"    mean diff similarity: {fmt(metrics.get('mean_difference_similarity'))}")
            print(f"    peak diff similarity: {fmt(metrics.get('peak_difference_similarity'))}")

    selected_by = item.get("selected_by", [])
    if selected_by:
        print("\nSelected for review by:")
        for ref in selected_by:
            print(f"  - {ref.get('lens')} (rank {ref.get('rank')})")

    print("\nLabel semantics:")
    print("  SAME       = misma región y mismo tipo general de diferencia de conducción.")
    print("  DIFFERENT  = no deben agruparse históricamente.")
    print("  AMBIGUOUS  = evidencia insuficiente/conflictiva.")
    print("  SKIP       = no revisar ahora.")


def upsert_label(
    labels_data: dict[str, Any],
    item: dict[str, Any],
    label: str,
    notes: str,
) -> None:
    if label not in VALID_LABELS:
        raise ValueError(
            f"human_label inválido: {label}. "
            f"Permitidos: {sorted(VALID_LABELS)}"
        )

    pair_id = item["pair_id"]

    record = {
        "pair_id": pair_id,
        "human_label": label,
        "review_notes": notes,
        "reviewed_at_utc": utc_now_iso(),
        "selected_by": item.get("selected_by", []),
        "feature_snapshot": compact_feature_snapshot(item["features"]),
    }

    for index, old in enumerate(labels_data["labels"]):
        if old.get("pair_id") == pair_id:
            labels_data["labels"][index] = record
            return

    labels_data["labels"].append(record)


def build_pending_items(
    queue_data: dict[str, Any],
    labels_data: dict[str, Any],
    *,
    include_skipped_on_resume: bool,
) -> list[dict[str, Any]]:
    """Calcula de forma determinista qué pares deben reaparecer al reanudar."""
    queue = queue_data["queue"]
    existing = labels_by_id(labels_data)

    pending = []

    for item in queue:
        pair_id = item["pair_id"]
        previous = existing.get(pair_id)

        if previous is None:
            pending.append(item)
            continue

        if (
            include_skipped_on_resume
            and previous.get("human_label") == "SKIP"
        ):
            pending.append(item)

    return pending


def interactive_review(
    queue_data: dict[str, Any],
    labels_data: dict[str, Any],
    labels_path: Path,
    *,
    include_skipped_on_resume: bool,
) -> int:
    pending = build_pending_items(
        queue_data,
        labels_data,
        include_skipped_on_resume=include_skipped_on_resume,
    )

    if not pending:
        print("No quedan pares pendientes.")
        return 0

    print()
    print("Controles: [s] SAME  [d] DIFFERENT  [a] AMBIGUOUS  [k] SKIP  [q] quit")

    for position, item in enumerate(pending, start=1):
        print_pair(item, position, len(pending))

        while True:
            choice = input("\nLabel [s/d/a/k/q]: ").strip().lower()
            mapping = {"s": "SAME", "d": "DIFFERENT", "a": "AMBIGUOUS", "k": "SKIP"}

            if choice == "q":
                save_labels(labels_path, labels_data)
                print(f"\nGuardado: {labels_path}")
                return 0

            label = mapping.get(choice)
            if label is None:
                print("Entrada inválida.")
                continue

            notes = input("Notas opcionales: ").strip()
            upsert_label(labels_data, item, label, notes)
            save_labels(labels_path, labels_data)
            print(f"Guardado: {label}")
            break

    print("\nRevisión de la cola completa.")
    print(f"Labels: {labels_path}")
    return 0


def print_summary(labels_data: dict[str, Any]) -> None:
    counts = {label: 0 for label in sorted(VALID_LABELS)}
    for item in labels_data["labels"]:
        label = item.get("human_label")
        if label in counts:
            counts[label] += 1

    print("\n" + "=" * 60)
    print("PAIR LABEL SUMMARY")
    print("=" * 60 + "\n")
    print(f"Total reviewed records: {len(labels_data['labels'])}")
    for label, count in counts.items():
        print(f"{label}: {count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Revisión humana de pares de episodios para calibración del matcher."
    )
    parser.add_argument("queue_json")
    parser.add_argument("--labels", default="pair_labels.json")
    parser.add_argument("--reviewer", default=None)
    parser.add_argument("--include-skipped", action="store_true")
    parser.add_argument("--summary", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    queue_path = Path(args.queue_json).resolve()
    labels_path = Path(args.labels).resolve()

    if not queue_path.exists():
        raise FileNotFoundError(queue_path)

    queue_data = load_queue(queue_path)
    labels_data = load_labels(labels_path, queue_path, args.reviewer)

    if args.summary:
        print_summary(labels_data)
        return 0

    return interactive_review(
        queue_data,
        labels_data,
        labels_path,
        include_skipped_on_resume=args.include_skipped,
    )


if __name__ == "__main__":
    raise SystemExit(main())
