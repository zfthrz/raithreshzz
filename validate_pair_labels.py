from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VALID_LABELS = {"SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"}


def file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(
    queue_path: Path,
    labels_path: Path,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []

    queue_data = load_json(queue_path)
    labels_data = load_json(labels_path)

    if not isinstance(queue_data, dict):
        return ["Queue root no es objeto."], warnings, {}
    if not isinstance(labels_data, dict):
        return ["Labels root no es objeto."], warnings, {}

    queue = queue_data.get("queue")
    if not isinstance(queue, list):
        errors.append("queue no es lista.")
        queue = []

    labels = labels_data.get("labels")
    if not isinstance(labels, list):
        errors.append("labels no es lista.")
        labels = []

    queue_by_id = {}
    for index, item in enumerate(queue):
        if not isinstance(item, dict):
            errors.append(f"queue[{index}] no es objeto.")
            continue
        pair_id = item.get("pair_id")
        if not isinstance(pair_id, str):
            errors.append(f"queue[{index}].pair_id inválido.")
            continue
        if pair_id in queue_by_id:
            errors.append(f"pair_id duplicado en queue: {pair_id}")
        queue_by_id[pair_id] = item

    metadata = labels_data.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append("labels.metadata no es objeto.")
        metadata = {}

    expected_queue_hash = file_sha256(queue_path)
    if metadata.get("source_queue_sha256") != expected_queue_hash:
        errors.append("source_queue_sha256 no coincide con la cola actual.")

    seen_labels = set()
    label_counts = Counter()
    sessions_by_label: dict[str, set[int]] = defaultdict(set)

    for index, record in enumerate(labels):
        if not isinstance(record, dict):
            errors.append(f"labels[{index}] no es objeto.")
            continue

        pair_id = record.get("pair_id")
        if not isinstance(pair_id, str):
            errors.append(f"labels[{index}].pair_id inválido.")
            continue

        if pair_id in seen_labels:
            errors.append(f"pair_id duplicado en labels: {pair_id}")
        seen_labels.add(pair_id)

        if pair_id not in queue_by_id:
            errors.append(f"Label referencia par fuera de la cola: {pair_id}")
            continue

        label = record.get("human_label")
        if label not in VALID_LABELS:
            errors.append(f"{pair_id}: human_label inválido: {label}")
            continue

        label_counts[label] += 1

        snapshot = record.get("feature_snapshot")
        if not isinstance(snapshot, dict):
            errors.append(f"{pair_id}: feature_snapshot ausente.")
            continue

        session_a = snapshot.get("session_a")
        session_b = snapshot.get("session_b")
        if session_a == session_b:
            errors.append(f"{pair_id}: label no es cross-session.")

        for session in (session_a, session_b):
            if isinstance(session, int):
                sessions_by_label[label].add(session)

        queue_features = queue_by_id[pair_id].get("features", {})
        for field in ("track", "session_a", "session_b", "episode_pk_a", "episode_pk_b"):
            if snapshot.get(field) != queue_features.get(field):
                errors.append(f"{pair_id}: snapshot.{field} no coincide con la cola.")

    non_skip = label_counts["SAME"] + label_counts["DIFFERENT"] + label_counts["AMBIGUOUS"]

    if non_skip == 0:
        warnings.append("Todavía no hay etiquetas de calibración utilizables.")
    if label_counts["AMBIGUOUS"] == 0 and non_skip > 0:
        warnings.append(
            "No hay ningún AMBIGUOUS. No es necesariamente un error, "
            "pero conviene confirmar que no se están forzando decisiones."
        )
    if label_counts["SAME"] == 0 and non_skip > 0:
        warnings.append("No hay ejemplos SAME todavía.")
    if label_counts["DIFFERENT"] == 0 and non_skip > 0:
        warnings.append("No hay ejemplos DIFFERENT todavía.")

    reviewed_queue_ids = {
        pair_id
        for pair_id in seen_labels
        if pair_id in queue_by_id
    }

    summary = {
        "queue_pairs": len(queue_by_id),
        "label_records": len(labels),
        "counts": dict(label_counts),
        "unreviewed": max(
            0,
            len(queue_by_id) - len(reviewed_queue_ids),
        ),
        "sessions_by_label": {
            label: sorted(sessions)
            for label, sessions in sessions_by_label.items()
        },
    }

    return errors, warnings, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Valida el dataset humano SAME/DIFFERENT/AMBIGUOUS."
    )
    parser.add_argument("queue_json")
    parser.add_argument("labels_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    queue_path = Path(args.queue_json).resolve()
    labels_path = Path(args.labels_json).resolve()

    if not queue_path.exists():
        raise FileNotFoundError(queue_path)
    if not labels_path.exists():
        raise FileNotFoundError(labels_path)

    errors, warnings, summary = validate(queue_path, labels_path)

    print()
    print("=" * 70)
    print("RACE ENGINEER - PAIR LABEL VALIDATOR v1.1")
    print("=" * 70)
    print()
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if warnings:
        print("\nWARNINGS")
        for item in warnings:
            print(f"- {item}")

    if errors:
        print("\nPAIR LABEL VALIDATION: FAIL")
        for item in errors:
            print(f"- {item}")
        return 1

    print("\nPAIR LABEL VALIDATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
