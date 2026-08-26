#!/usr/bin/env python3
"""Build a labeler-compatible queue from human-label coverage gaps.

The source batches remain immutable.  This tool only writes a small evidence
batch when ``--write`` is explicitly supplied.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_LABELS = {"SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"}


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON root inválido: {path}")
    return data


def _context(status: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(status.get("track") or ""),
        str(status.get("track_layout") or ""),
        str(status.get("vehicle_variant") or ""),
    )


def _path(batch_dir: Path, value: Any, fallback: str) -> Path:
    candidate = Path(str(value)) if value else batch_dir / fallback
    return candidate if candidate.is_absolute() else batch_dir / candidate


def _canonical_item(item: dict[str, Any]) -> str:
    comparable = {
        "pair_id": item.get("pair_id"),
        "features": item.get("features"),
    }
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def collect_uncovered(
    batches_root: Path,
    context: tuple[str, str, str],
) -> dict[str, Any]:
    labeled: set[str] = set()
    candidates: dict[str, dict[str, Any]] = {}
    canonical: dict[str, str] = {}
    source_queues: set[str] = set()
    session_ids: set[int] = set()

    statuses: list[tuple[Path, dict[str, Any]]] = []
    for status_path in sorted(batches_root.glob("*/BATCH_STATUS.json")):
        status = _load(status_path)
        if _context(status) == context:
            statuses.append((status_path, status))

    if not statuses:
        raise ValueError("No hay batches para el contexto solicitado.")

    # Coverage is global within the exact track/layout/vehicle context.
    for status_path, status in statuses:
        steps = status.get("steps") if isinstance(status.get("steps"), dict) else {}
        human = steps.get("human_labels") if isinstance(steps.get("human_labels"), dict) else {}
        labels_path = _path(status_path.parent, human.get("labels_path"), "pair_labels.json")
        if not labels_path.is_file():
            continue
        labels = _load(labels_path).get("labels", [])
        if not isinstance(labels, list):
            continue
        for record in labels:
            if (
                isinstance(record, dict)
                and isinstance(record.get("pair_id"), str)
                and record.get("human_label") in VALID_LABELS
            ):
                labeled.add(record["pair_id"])

    for status_path, status in statuses:
        steps = status.get("steps") if isinstance(status.get("steps"), dict) else {}
        review = steps.get("review_queue") if isinstance(steps.get("review_queue"), dict) else {}
        selection = steps.get("vehicle_context_selection") if isinstance(steps.get("vehicle_context_selection"), dict) else {}
        for value in selection.get("session_ids", []):
            if isinstance(value, int):
                session_ids.add(value)
        queue_path = _path(status_path.parent, review.get("path"), "pair_review_queue.json")
        if not queue_path.is_file():
            continue
        queue = _load(queue_path).get("queue", [])
        if not isinstance(queue, list):
            continue
        source_queues.add(str(queue_path.resolve()))
        for item in queue:
            if not isinstance(item, dict) or not isinstance(item.get("pair_id"), str):
                continue
            pair_id = item["pair_id"]
            if pair_id in labeled:
                continue
            signature = _canonical_item(item)
            if pair_id in canonical and canonical[pair_id] != signature:
                raise ValueError(f"Evidencia conflictiva para pair_id {pair_id}.")
            canonical[pair_id] = signature
            candidates.setdefault(pair_id, copy.deepcopy(item))

    queue = []
    for position, pair_id in enumerate(sorted(candidates), start=1):
        item = candidates[pair_id]
        item["queue_position"] = position
        queue.append(item)

    return {
        "context": context,
        "queue": queue,
        "labeled_pair_count": len(labeled),
        "source_queues": sorted(source_queues),
        "session_ids": sorted(session_ids),
    }


def _slug(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in normalized.split("-") if part)


def build_documents(result: dict[str, Any], batches_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    track, layout, variant = result["context"]
    pair_ids = [item["pair_id"] for item in result["queue"]]
    digest_source = json.dumps([track, layout, variant, pair_ids], ensure_ascii=False, separators=(",", ":"))
    batch_id = "uncovered-" + hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:10]
    dirname = "--".join(filter(None, (_slug(track), _slug(layout) if layout != track else "", _slug(variant), batch_id)))
    batch_dir = batches_root / dirname
    queue_path = batch_dir / "pair_review_queue.json"
    labels_path = batch_dir / "pair_labels.json"
    now = datetime.now(timezone.utc).isoformat()
    queue_doc = {
        "metadata": {
            "queue_schema_version": "1.1",
            "created_at_utc": now,
            "selected_pair_count": len(pair_ids),
            "selection_policy": "uncovered_human_evidence_v0.1",
            "source_queue_paths": result["source_queues"],
            "covered_pair_count": result["labeled_pair_count"],
            "semantics": "Deduplicated pairs not covered by any human label in the exact context.",
        },
        "queue": result["queue"],
    }
    status = {
        "orchestrator_version": "uncovered-review-v0.1",
        "updated_at_utc": now,
        "overall_status": "READY_FOR_HUMAN_REVIEW" if pair_ids else "NO_UNCOVERED_PAIRS",
        "track": track,
        "track_layout": layout,
        "vehicle_variant": variant,
        "batch_id": batch_id,
        "batch_dir": str(batch_dir.resolve()),
        "steps": {
            "vehicle_context_selection": {
                "status": "PASS",
                "session_count": len(result["session_ids"]),
                "session_ids": result["session_ids"],
            },
            "review_queue": {
                "status": "READY" if pair_ids else "EMPTY",
                "path": str(queue_path.resolve()),
                "queue_pairs": len(pair_ids),
            },
            "human_labels": {
                "status": "PENDING" if pair_ids else "NOT_APPLICABLE",
                "labels_path": str(labels_path.resolve()),
                "queue_pairs": len(pair_ids),
                "labeled_pairs": 0,
                "unreviewed_pairs": len(pair_ids),
                "complete": not pair_ids,
            },
            "calibration_dataset": {"status": "BLOCKED_BY_LABELS" if pair_ids else "NOT_APPLICABLE"},
            "evaluation_readiness": {"status": "SHADOW_EVIDENCE_ONLY", "evaluation_pairs": 0},
        },
    }
    return batch_dir, queue_doc, status


def write_documents(batch_dir: Path, queue: dict[str, Any], status: dict[str, Any]) -> None:
    batch_dir.mkdir(parents=True, exist_ok=True)
    queue_path = batch_dir / "pair_review_queue.json"
    labels_path = batch_dir / "pair_labels.json"
    if queue_path.exists():
        existing = _load(queue_path)
        if existing.get("queue") != queue.get("queue"):
            if labels_path.exists():
                raise ValueError(
                    "La cola consolidada cambió y ya tiene labels; no se sobrescribe."
                )
            queue_path.write_text(
                json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    else:
        queue_path.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    (batch_dir / "BATCH_STATUS.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batches-root", type=Path, default=Path("calibration_batches"))
    parser.add_argument("--track", required=True)
    parser.add_argument("--track-layout", required=True)
    parser.add_argument("--vehicle-variant", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = collect_uncovered(args.batches_root, (args.track, args.track_layout, args.vehicle_variant))
    batch_dir, queue, status = build_documents(result, args.batches_root)
    if args.write and queue["queue"]:
        write_documents(batch_dir, queue, status)
    print(f"Uncovered pairs: {len(queue['queue'])}")
    print(f"Output: {batch_dir if queue['queue'] else 'NONE'}")
    if args.write and not queue["queue"]:
        print("RESULT: NOTHING_TO_WRITE")
    else:
        print("RESULT: " + ("WRITTEN" if args.write else "DRY_RUN"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
