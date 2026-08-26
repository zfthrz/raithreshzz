"""Read-only inventory of calibration batches and retention candidates."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BATCHES_ROOT = PROJECT_ROOT / "calibration_batches"


def _directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _label_count(batch_dir: Path, payload: dict[str, Any]) -> int:
    steps = payload.get("steps") if isinstance(payload.get("steps"), dict) else {}
    human = steps.get("human_labels") if isinstance(steps.get("human_labels"), dict) else {}
    labels_path = Path(human.get("labels_path") or batch_dir / "pair_labels.json")
    if not labels_path.is_absolute():
        labels_path = batch_dir / labels_path
    try:
        labels = json.loads(labels_path.read_text(encoding="utf-8")).get("labels")
    except (OSError, TypeError, json.JSONDecodeError):
        return int(human.get("labeled_pairs") or 0)
    if not isinstance(labels, list):
        return 0
    return len({
        item.get("pair_id")
        for item in labels
        if isinstance(item, dict)
        and isinstance(item.get("pair_id"), str)
        and item.get("human_label") in {"SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"}
    })


def inventory(batches_root: Path) -> dict[str, Any]:
    root = Path(batches_root).resolve()
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    invalid: list[str] = []

    if root.is_dir():
        for batch_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            status_path = batch_dir / "BATCH_STATUS.json"
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
                selection = payload["steps"]["vehicle_context_selection"]
                context = (
                    str(payload["track"]),
                    str(payload["track_layout"]),
                    str(payload["vehicle_variant"]),
                )
                ids = sorted(int(value) for value in selection["session_ids"])
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                invalid.append(str(batch_dir))
                continue
            grouped[context].append({
                "batch_id": str(payload.get("batch_id") or batch_dir.name),
                "path": str(batch_dir),
                "session_ids": ids,
                "session_count": len(ids),
                "human_labels": _label_count(batch_dir, payload),
                "size_bytes": _directory_size(batch_dir),
                "updated_at_utc": str(payload.get("updated_at_utc") or ""),
            })

    records: list[dict[str, Any]] = []
    for context, batches in sorted(grouped.items()):
        newest = max(
            batches,
            key=lambda item: (
                item["session_count"],
                item["updated_at_utc"],
                item["batch_id"],
            ),
        )
        for batch in sorted(batches, key=lambda item: item["batch_id"]):
            if batch["batch_id"] == newest["batch_id"]:
                classification = (
                    "CURRENT_WITH_HUMAN_EVIDENCE"
                    if batch["human_labels"]
                    else "ACTIVE_HUMAN_REVIEW"
                )
            elif batch["human_labels"]:
                classification = "PRESERVE_HUMAN_EVIDENCE"
            else:
                classification = "SUPERSEDED_UNLABELED_REGENERABLE"
            records.append({
                "track": context[0],
                "track_layout": context[1],
                "vehicle_variant": context[2],
                **batch,
                "classification": classification,
            })

    reclaimable = [
        item for item in records
        if item["classification"] == "SUPERSEDED_UNLABELED_REGENERABLE"
    ]
    return {
        "schema_version": 1,
        "authority": "READ_ONLY_AUDIT",
        "destructive_actions_performed": 0,
        "summary": {
            "contexts": len(grouped),
            "batches": len(records),
            "invalid_directories": len(invalid),
            "total_size_bytes": sum(item["size_bytes"] for item in records),
            "superseded_unlabeled_batches": len(reclaimable),
            "potentially_reclaimable_bytes": sum(
                item["size_bytes"] for item in reclaimable
            ),
        },
        "batches": records,
        "invalid_directories": invalid,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batches-root", type=Path, default=DEFAULT_BATCHES_ROOT)
    parser.add_argument("--json", action="store_true", help="imprime el reporte completo")
    args = parser.parse_args()
    report = inventory(args.batches_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        print("RACE ENGINEER - CALIBRATION BATCH RETENTION AUDIT")
        print(f"Contexts: {summary['contexts']}")
        print(f"Batches: {summary['batches']}")
        print(
            "Superseded unlabeled: "
            f"{summary['superseded_unlabeled_batches']} / "
            f"{summary['potentially_reclaimable_bytes'] / 1024 / 1024:.1f} MiB"
        )
        print("RESULT: READ_ONLY_AUDIT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
