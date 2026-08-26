"""Prepare at most one changed H2 human-label queue per scheduler cycle."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from prepare_calibration_batch import group_history_by_context, load_history_rows


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "local" / "race_engineer_history.duckdb"
DEFAULT_ANALYSIS_DIR = PROJECT_ROOT / "data" / "generated" / "analysis"
DEFAULT_BATCHES_ROOT = PROJECT_ROOT / "calibration_batches"
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "local" / "calibration_queue_maintenance.json"
BOOTSTRAP_FILENAMES = (
    "00_history_init.log",
    "01_history_import.log",
    "02_history_validation.log",
    "BATCH_STATUS.json",
)


def context_key(context: tuple[str, str, str]) -> str:
    return " | ".join(context)


def session_ids(rows: list[dict[str, Any]]) -> list[int]:
    return sorted(int(row["session_id"]) for row in rows)


def _live_review_progress(
    status_path: Path,
    payload: dict[str, Any],
) -> tuple[int, int]:
    steps = payload.get("steps") if isinstance(payload.get("steps"), dict) else {}
    review = steps.get("review_queue") if isinstance(steps.get("review_queue"), dict) else {}
    human = steps.get("human_labels") if isinstance(steps.get("human_labels"), dict) else {}
    batch_dir = status_path.parent
    queue_path = Path(review.get("path") or batch_dir / "pair_review_queue.json")
    labels_path = Path(human.get("labels_path") or batch_dir / "pair_labels.json")
    if not queue_path.is_absolute():
        queue_path = batch_dir / queue_path
    if not labels_path.is_absolute():
        labels_path = batch_dir / labels_path

    queue_pairs = int(review.get("queue_pairs") or human.get("queue_pairs") or 0)
    labeled_pairs = int(human.get("labeled_pairs") or 0)
    try:
        queue = json.loads(queue_path.read_text(encoding="utf-8")).get("queue")
        if isinstance(queue, list):
            queue_pairs = len(queue)
    except (OSError, TypeError, json.JSONDecodeError):
        pass
    try:
        labels = json.loads(labels_path.read_text(encoding="utf-8")).get("labels")
        if isinstance(labels, list):
            labeled_pairs = len({
                item.get("pair_id")
                for item in labels
                if isinstance(item, dict)
                and isinstance(item.get("pair_id"), str)
                and item.get("human_label")
                in {"SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"}
            })
    except (OSError, TypeError, json.JSONDecodeError):
        pass
    return queue_pairs, labeled_pairs


def existing_batch_inventory(
    batches_root: Path,
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    if not batches_root.is_dir():
        return result
    for path in batches_root.glob("*/BATCH_STATUS.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            selection = payload["steps"]["vehicle_context_selection"]
            context = (
                str(payload["track"]),
                str(payload["track_layout"]),
                str(payload["vehicle_variant"]),
            )
            ids = tuple(sorted(int(value) for value in selection["session_ids"]))
            queue_pairs, labeled_pairs = _live_review_progress(path, payload)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        result.setdefault(context, []).append({
            "batch_id": str(payload.get("batch_id") or path.parent.name),
            "session_ids": ids,
            "queue_pairs": queue_pairs,
            "labeled_pairs": labeled_pairs,
            "pending_review": queue_pairs > 0 and labeled_pairs < queue_pairs,
        })
    return result


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": "0.1", "contexts": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("contexts"), dict):
        raise ValueError(f"Estado de colas inválido: {path}")
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def snapshot_bootstrap_files(root: Path) -> dict[Path, bytes | None]:
    return {
        root / name: (root / name).read_bytes() if (root / name).is_file() else None
        for name in BOOTSTRAP_FILENAMES
    }


def restore_bootstrap_files(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def prepare_command(
    context: tuple[str, str, str],
    *,
    python_executable: str,
    project_root: Path,
    analysis_dir: Path,
    db_path: Path,
    batches_root: Path,
) -> list[str]:
    track, layout, variant = context
    return [
        python_executable,
        str(project_root / "prepare_calibration_batch.py"),
        str(analysis_dir),
        "--project-root", str(project_root),
        "--db", str(db_path),
        "--output-dir", str(batches_root),
        "--track", track,
        "--track-layout", layout,
        "--vehicle-variant", variant,
        "--skip-import",
    ]


def maintain(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    analysis_dir: Path = DEFAULT_ANALYSIS_DIR,
    batches_root: Path = DEFAULT_BATCHES_ROOT,
    state_path: Path = DEFAULT_STATE_PATH,
    project_root: Path = PROJECT_ROOT,
    history_loader: Callable[[Path], list[dict[str, Any]]] = load_history_rows,
    runner: Callable[..., Any] = subprocess.run,
    now: datetime | None = None,
) -> int:
    rows = history_loader(db_path)
    grouped = group_history_by_context(rows)
    state = load_state(state_path)
    recorded = state["contexts"]
    existing = existing_batch_inventory(batches_root)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    pending: list[tuple[tuple[str, str, str], list[int]]] = []

    for context, context_rows in sorted(grouped.items()):
        if len(context_rows) < 2:
            continue
        ids = session_ids(context_rows)
        key = context_key(context)
        context_batches = existing.get(context, [])
        latest_size = max(
            (len(batch["session_ids"]) for batch in context_batches),
            default=0,
        )
        latest_pending = [
            batch
            for batch in context_batches
            if len(batch["session_ids"]) == latest_size and batch["pending_review"]
        ]
        if latest_pending:
            active = sorted(latest_pending, key=lambda item: item["batch_id"])[-1]
            recorded[key] = {
                "session_ids": ids,
                "status": "WAITING_FOR_HUMAN_REVIEW",
                "active_batch_id": active["batch_id"],
                "active_batch_session_ids": list(active["session_ids"]),
                "labeled_pairs": active["labeled_pairs"],
                "queue_pairs": active["queue_pairs"],
                "updated_at": stamp,
            }
            continue
        if tuple(ids) in {
            batch["session_ids"] for batch in context_batches
        }:
            recorded[key] = {
                "session_ids": ids,
                "status": "QUEUE_ALREADY_PREPARED",
                "updated_at": stamp,
            }
            continue
        previous = recorded.get(key)
        if (
            isinstance(previous, dict)
            and previous.get("session_ids") == ids
            and previous.get("status") in {"QUEUE_PREPARED", "PREPARATION_FAILED"}
        ):
            continue
        pending.append((context, ids))

    if not pending:
        state["last_run"] = {"at": stamp, "status": "NO_CHANGED_CONTEXTS"}
        save_state(state_path, state)
        print("CALIBRATION QUEUES: no hay contextos nuevos o modificados.")
        return 0

    context, ids = pending[0]
    command = prepare_command(
        context,
        python_executable=sys.executable,
        project_root=project_root,
        analysis_dir=analysis_dir,
        db_path=db_path,
        batches_root=batches_root,
    )
    bootstrap_snapshot = snapshot_bootstrap_files(batches_root)
    try:
        completed = runner(command, cwd=str(project_root), check=False)
    finally:
        restore_bootstrap_files(bootstrap_snapshot)
    return_code = int(getattr(completed, "returncode", 1))
    key = context_key(context)
    recorded[key] = {
        "session_ids": ids,
        "status": "QUEUE_PREPARED" if return_code == 0 else "PREPARATION_FAILED",
        "updated_at": stamp,
        "exit_code": return_code,
    }
    state["last_run"] = {
        "at": stamp,
        "status": recorded[key]["status"],
        "context": key,
        "remaining_changed_contexts": len(pending) - 1,
    }
    save_state(state_path, state)
    print(f"CALIBRATION QUEUES: {recorded[key]['status']} — {key}")
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BATCHES_ROOT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args()
    return maintain(
        db_path=args.db.resolve(),
        analysis_dir=args.analysis_dir.resolve(),
        batches_root=args.output_dir.resolve(),
        state_path=args.state.resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
