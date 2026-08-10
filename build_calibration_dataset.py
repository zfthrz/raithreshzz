from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_pair_labels import validate as validate_pair_labels


DATASET_SCHEMA_VERSION = "1.0"
USABLE_LABELS = {"SAME", "DIFFERENT", "AMBIGUOUS"}
IGNORED_LABELS = {"SKIP"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def session_key(
    track: Any,
    session_id: Any,
) -> str:
    """
    Clave robusta por track + session_id.

    session_id es global en el History DB actual, pero incluir el track
    evita depender de esa suposición en datasets exportados.
    """
    return json.dumps(
        [
            str(track),
            safe_int(session_id),
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def stable_session_order_key(
    key: str,
    seed: int,
) -> str:
    raw = f"{seed}|{key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def collect_reviewed_records(
    queue_data: dict[str, Any],
    labels_data: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    queue = queue_data["queue"]
    labels = labels_data["labels"]

    queue_by_id = {
        item["pair_id"]: item
        for item in queue
        if isinstance(item, dict)
        and isinstance(item.get("pair_id"), str)
    }

    label_by_id = {
        item["pair_id"]: item
        for item in labels
        if isinstance(item, dict)
        and isinstance(item.get("pair_id"), str)
    }

    usable = []
    ignored = []

    for pair_id, label_record in label_by_id.items():
        queue_item = queue_by_id[pair_id]
        label = label_record.get("human_label")
        features = queue_item.get("features", {})

        base_record = {
            "pair_id": pair_id,
            "human_label": label,
            "review_notes": label_record.get("review_notes", ""),
            "reviewed_at_utc": label_record.get("reviewed_at_utc"),
            "selected_by": queue_item.get("selected_by", []),
            "features": features,
        }

        if label in USABLE_LABELS:
            usable.append(base_record)
        elif label in IGNORED_LABELS:
            ignored.append(base_record)

    return usable, ignored


def collect_sessions(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sessions: dict[str, dict[str, Any]] = {}

    for record in records:
        features = record["features"]

        track = features.get("track")

        for suffix in ("a", "b"):
            session_id = safe_int(
                features.get(f"session_{suffix}")
            )

            if session_id is None:
                continue

            key = session_key(
                track,
                session_id,
            )

            sessions.setdefault(
                key,
                {
                    "session_key": key,
                    "track": track,
                    "session_id": session_id,
                },
            )

    return sorted(
        sessions.values(),
        key=lambda item: (
            str(item.get("track")),
            int(item["session_id"]),
        ),
    )


def assign_sessions(
    sessions: list[dict[str, Any]],
    *,
    evaluation_fraction: float,
    seed: int,
) -> dict[str, str]:
    if not 0.0 < evaluation_fraction < 1.0:
        raise ValueError(
            "--evaluation-fraction debe estar entre 0 y 1."
        )

    if not sessions:
        return {}

    ordered = sorted(
        sessions,
        key=lambda item: (
            stable_session_order_key(
                item["session_key"],
                seed,
            ),
            item["session_key"],
        ),
    )

    total = len(ordered)

    if total == 1:
        evaluation_count = 0
    else:
        evaluation_count = int(
            round(
                total
                *
                evaluation_fraction
            )
        )

        evaluation_count = max(
            1,
            min(
                total - 1,
                evaluation_count,
            ),
        )

    evaluation_keys = {
        item["session_key"]
        for item in ordered[:evaluation_count]
    }

    assignment = {}

    for item in sessions:
        key = item["session_key"]

        assignment[key] = (
            "evaluation"
            if key in evaluation_keys
            else "calibration"
        )

    return assignment


def partition_records(
    records: list[dict[str, Any]],
    assignment: dict[str, str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    calibration = []
    evaluation = []
    cross_split = []

    for record in records:
        features = record["features"]
        track = features.get("track")

        session_a = safe_int(
            features.get("session_a")
        )

        session_b = safe_int(
            features.get("session_b")
        )

        key_a = session_key(
            track,
            session_a,
        )

        key_b = session_key(
            track,
            session_b,
        )

        partition_a = assignment.get(
            key_a
        )

        partition_b = assignment.get(
            key_b
        )

        if (
            partition_a == "calibration"
            and
            partition_b == "calibration"
        ):
            calibration.append(record)
            continue

        if (
            partition_a == "evaluation"
            and
            partition_b == "evaluation"
        ):
            evaluation.append(record)
            continue

        cross_split.append({
            "pair_id": record["pair_id"],
            "human_label": record["human_label"],
            "track": track,
            "session_a": session_a,
            "session_b": session_b,
            "partition_a": partition_a,
            "partition_b": partition_b,
            "reason": "cross_partition_pair_excluded_to_prevent_session_leakage",
        })

    return (
        calibration,
        evaluation,
        cross_split,
    )


def label_counts(
    records: list[dict[str, Any]],
) -> dict[str, int]:
    counts = Counter(
        record["human_label"]
        for record in records
    )

    return {
        label: counts.get(label, 0)
        for label in (
            "SAME",
            "DIFFERENT",
            "AMBIGUOUS",
        )
    }


def session_partition_records(
    sessions: list[dict[str, Any]],
    assignment: dict[str, str],
) -> list[dict[str, Any]]:
    result = []

    for item in sessions:
        row = dict(item)
        row["partition"] = assignment[
            item["session_key"]
        ]
        result.append(row)

    return result


def build_dataset(
    queue_path: Path,
    labels_path: Path,
    *,
    evaluation_fraction: float,
    seed: int,
) -> dict[str, Any]:
    errors, warnings, validation_summary = (
        validate_pair_labels(
            queue_path,
            labels_path,
        )
    )

    if errors:
        raise ValueError(
            "PAIR LABEL VALIDATION FAILED:\n- "
            +
            "\n- ".join(errors)
        )

    queue_data = load_json(
        queue_path
    )

    labels_data = load_json(
        labels_path
    )

    usable, ignored = collect_reviewed_records(
        queue_data,
        labels_data,
    )

    sessions = collect_sessions(
        usable
    )

    assignment = assign_sessions(
        sessions,
        evaluation_fraction=evaluation_fraction,
        seed=seed,
    )

    calibration, evaluation, cross_split = partition_records(
        usable,
        assignment,
    )

    calibration_session_keys = {
        item["session_key"]
        for item in sessions
        if assignment[
            item["session_key"]
        ] == "calibration"
    }

    evaluation_session_keys = {
        item["session_key"]
        for item in sessions
        if assignment[
            item["session_key"]
        ] == "evaluation"
    }

    overlap = (
        calibration_session_keys
        &
        evaluation_session_keys
    )

    if overlap:
        raise AssertionError(
            "Internal error: session leakage detected."
        )

    build_warnings = list(
        warnings
    )

    if not usable:
        build_warnings.append(
            "No hay labels utilizables SAME/DIFFERENT/AMBIGUOUS."
        )

    if len(sessions) < 2:
        build_warnings.append(
            "Hay menos de dos sesiones utilizables; "
            "no se puede formar una evaluación independiente."
        )

    if not calibration and usable:
        build_warnings.append(
            "El split dejó calibración sin pares internos."
        )

    if not evaluation and len(sessions) >= 2:
        build_warnings.append(
            "El split dejó evaluación sin pares internos. "
            "Esto puede ocurrir con pocos pares/sesiones porque "
            "los pares cross-partition se excluyen."
        )

    return {
        "metadata": {
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_queue_path": str(queue_path.resolve()),
            "source_queue_sha256": file_sha256(queue_path),
            "source_labels_path": str(labels_path.resolve()),
            "source_labels_sha256": file_sha256(labels_path),
            "split_unit": "session",
            "evaluation_fraction_requested": evaluation_fraction,
            "seed": seed,
            "leakage_policy": (
                "A session may belong to only one partition. "
                "Pairs crossing partitions are excluded from both."
            ),
            "skip_policy": (
                "SKIP is excluded from calibration/evaluation ground truth."
            ),
            "ambiguous_policy": (
                "AMBIGUOUS is preserved as a first-class human label."
            ),
            "matcher_status": (
                "NO_THRESHOLDS_NO_MATCH_SCORE_NO_AUTOMATIC_MATCHING"
            ),
        },
        "validation": {
            "pair_label_validation_summary": validation_summary,
            "warnings": build_warnings,
        },
        "session_assignment": session_partition_records(
            sessions,
            assignment,
        ),
        "counts": {
            "reviewed_usable_pairs": len(usable),
            "ignored_skip_pairs": len(ignored),
            "usable_sessions": len(sessions),
            "calibration_sessions": len(
                calibration_session_keys
            ),
            "evaluation_sessions": len(
                evaluation_session_keys
            ),
            "calibration_pairs": len(calibration),
            "evaluation_pairs": len(evaluation),
            "cross_split_pairs_excluded": len(cross_split),
            "calibration_labels": label_counts(
                calibration
            ),
            "evaluation_labels": label_counts(
                evaluation
            ),
            "all_usable_labels": label_counts(
                usable
            ),
        },
        "calibration": calibration,
        "evaluation": evaluation,
        "excluded_cross_split": cross_split,
        "ignored_skip": [
            {
                "pair_id": record["pair_id"],
                "human_label": record["human_label"],
            }
            for record in ignored
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Construye datasets de calibración/evaluación "
            "separados por sesión, sin leakage."
        )
    )

    parser.add_argument(
        "queue_json",
        help="pair_review_queue JSON",
    )

    parser.add_argument(
        "labels_json",
        help="pair labels JSON validado",
    )

    parser.add_argument(
        "--output",
        default="calibration_dataset.json",
    )

    parser.add_argument(
        "--evaluation-fraction",
        type=float,
        default=0.25,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=20260810,
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    queue_path = Path(
        args.queue_json
    ).resolve()

    labels_path = Path(
        args.labels_json
    ).resolve()

    output_path = Path(
        args.output
    ).resolve()

    if not queue_path.exists():
        raise FileNotFoundError(
            queue_path
        )

    if not labels_path.exists():
        raise FileNotFoundError(
            labels_path
        )

    dataset = build_dataset(
        queue_path,
        labels_path,
        evaluation_fraction=args.evaluation_fraction,
        seed=args.seed,
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            dataset,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("RACE ENGINEER - CALIBRATION DATASET BUILDER v1.0")
    print("=" * 72)
    print()
    print(
        json.dumps(
            dataset["counts"],
            indent=2,
            ensure_ascii=False,
        )
    )

    warnings = dataset[
        "validation"
    ][
        "warnings"
    ]

    if warnings:
        print()
        print("WARNINGS")

        for warning in warnings:
            print(
                f"- {warning}"
            )

    print()
    print(
        f"Output: {output_path}"
    )

    print(
        "Session leakage check: PASS"
    )

    print(
        "Matcher status: "
        "NO THRESHOLDS / NO SCORE / NO AUTOMATIC MATCHING"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
