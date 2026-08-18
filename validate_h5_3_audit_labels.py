from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


VALID_LABELS = {"ACTIONABLE", "OBSERVATIONAL_ONLY", "NOT_COMPARABLE", "AMBIGUOUS"}
SNAPSHOT_FIELDS = (
    "audit_id",
    "candidate_id",
    "location_label",
    "delta_sign",
    "current_minus_historical_s",
    "track",
    "track_layout",
    "vehicle_variant",
    "car_name_raw",
    "observational_channel_evidence",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(
    dataset_path: Path,
    labels_path: Path,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    dataset_data = load_json(dataset_path)
    labels_data = load_json(labels_path)

    if not isinstance(dataset_data, dict):
        return ["Dataset root no es objeto."], warnings, {}
    if not isinstance(labels_data, dict):
        return ["Labels root no es objeto."], warnings, {}

    dataset_candidates = dataset_data.get("candidates")
    if not isinstance(dataset_candidates, list):
        errors.append("dataset.candidates no es lista.")
        dataset_candidates = []
    labels = labels_data.get("labels")
    if not isinstance(labels, list):
        errors.append("labels no es lista.")
        labels = []

    dataset_by_id = {}
    for index, item in enumerate(dataset_candidates):
        if not isinstance(item, dict):
            errors.append(f"dataset.candidates[{index}] no es objeto.")
            continue
        audit_id = item.get("audit_id")
        if not isinstance(audit_id, str):
            errors.append(f"dataset.candidates[{index}].audit_id inválido.")
            continue
        if audit_id in dataset_by_id:
            errors.append(f"audit_id duplicado en dataset: {audit_id}")
        dataset_by_id[audit_id] = item

    metadata = labels_data.get("metadata") or {}
    if not isinstance(metadata, dict):
        errors.append("labels.metadata no es objeto.")
        metadata = {}
    if metadata.get("source_dataset_sha256") != file_sha256(dataset_path):
        errors.append("source_dataset_sha256 no coincide con el dataset actual.")

    seen = set()
    counts = Counter()
    for index, record in enumerate(labels):
        if not isinstance(record, dict):
            errors.append(f"labels[{index}] no es objeto.")
            continue
        audit_id = record.get("audit_id")
        if not isinstance(audit_id, str):
            errors.append(f"labels[{index}].audit_id inválido.")
            continue
        if audit_id in seen:
            errors.append(f"audit_id duplicado en labels: {audit_id}")
        seen.add(audit_id)
        if audit_id not in dataset_by_id:
            errors.append(f"Label referencia candidato fuera del dataset: {audit_id}")
            continue
        label = record.get("human_label")
        if label not in VALID_LABELS:
            errors.append(f"{audit_id}: human_label inválido: {label}")
            continue
        counts[label] += 1
        snapshot = record.get("candidate_snapshot")
        if not isinstance(snapshot, dict):
            errors.append(f"{audit_id}: candidate_snapshot ausente.")
            continue
        source = dataset_by_id[audit_id]
        expected = {
            "audit_id": source.get("audit_id"),
            "candidate_id": source.get("candidate_id"),
            "location_label": source.get("location_label"),
            "delta_sign": source.get("delta_sign"),
            "current_minus_historical_s": source.get(
                "current_minus_historical_s"
            ),
            "observational_channel_evidence": source.get(
                "observational_channel_evidence"
            ),
        }
        source_context = source.get("context") or {}
        for field in ("track", "track_layout", "vehicle_variant", "car_name_raw"):
            expected[field] = source_context.get(field)
        for field in SNAPSHOT_FIELDS:
            if snapshot.get(field) != expected.get(field):
                errors.append(f"{audit_id}: snapshot.{field} no coincide con el dataset.")

    if not counts:
        warnings.append("Todavía no hay etiquetas de auditoría.")
    if counts["ACTIONABLE"] == 0 and counts:
        warnings.append("No hay candidatos ACTIONABLE todavía.")
    if counts["NOT_COMPARABLE"] == 0 and counts:
        warnings.append("No hay candidatos NOT_COMPARABLE todavía.")
    if counts["AMBIGUOUS"] == 0 and counts:
        warnings.append(
            "No hay AMBIGUOUS. No es necesariamente un error, pero conviene "
            "confirmar que no se está forzando una decisión."
        )

    reviewed = {
        audit_id
        for audit_id in seen
        if audit_id in dataset_by_id
    }
    summary = {
        "dataset_candidates": len(dataset_by_id),
        "label_records": len(labels),
        "counts": dict(counts),
        "unreviewed": max(0, len(dataset_by_id) - len(reviewed)),
    }
    return errors, warnings, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Valida labels humanos del dataset H5.3b."
    )
    parser.add_argument("dataset_json")
    parser.add_argument("labels_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dataset_path = Path(args.dataset_json).resolve()
    labels_path = Path(args.labels_json).resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(dataset_path)
    if not labels_path.exists():
        raise FileNotFoundError(labels_path)

    errors, warnings, summary = validate(dataset_path, labels_path)
    print()
    print("=" * 70)
    print("RACE ENGINEER - H5.3B AUDIT LABEL VALIDATOR v0.1")
    print("=" * 70)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if warnings:
        print("\nWARNINGS")
        for item in warnings:
            print(f"- {item}")
    if errors:
        print("\nH5.3B AUDIT LABEL VALIDATION: FAIL")
        for item in errors:
            print(f"- {item}")
        return 1
    print("\nH5.3B AUDIT LABEL VALIDATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
