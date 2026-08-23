"""Maintain an expanded H5.3 review queue without making human decisions."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from migrate_h5_3_action_review_labels import migrate_labels
from prepare_h5_3_action_review_queue import build_queue, file_sha256
from validate_h5_3_action_review_labels import validate as validate_labels


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT_ROOT = PROJECT_ROOT / "data" / "generated" / "h5_3_shadow"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "generated" / "h5_3"
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "local" / "h5_3_review_maintenance.json"
QUEUE_PATTERN = re.compile(r"^action_review_queue_v(\d+)\.json$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _discover_pairs(output_root: Path) -> list[tuple[int, Path, Path]]:
    pairs: list[tuple[int, Path, Path]] = []
    for queue_path in output_root.glob("action_review_queue_v*.json"):
        match = QUEUE_PATTERN.match(queue_path.name)
        if match is None:
            continue
        revision = int(match.group(1))
        labels_path = output_root / f"action_review_labels_v{revision}.json"
        if labels_path.is_file():
            pairs.append((revision, queue_path.resolve(), labels_path.resolve()))
    return sorted(pairs)


def _load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return document


def _artifact_fingerprint(paths: list[Path]) -> list[dict[str, str]]:
    return [
        {"path": str(path.resolve()), "sha256": file_sha256(path.resolve())}
        for path in sorted(paths, key=lambda item: str(item.resolve()))
    ]


def maintain(
    *,
    input_root: Path = DEFAULT_INPUT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    input_root = Path(input_root).resolve()
    output_root = Path(output_root).resolve()
    state_path = Path(state_path).resolve()
    artifacts = sorted(input_root.rglob("historical_actions.json"), key=str)
    if not artifacts:
        result = {
            "status": "NO_SOURCE_ARTIFACTS",
            "updated_at_utc": _utc_now(),
            "source_artifact_count": 0,
            "pending_review_count": 0,
            "historical_actions_authorized": False,
        }
        _write_json(state_path, result)
        return result

    pairs = _discover_pairs(output_root)
    if not pairs:
        raise ValueError("No existing reviewed queue/labels pair is available for safe migration")
    revision, current_queue_path, current_labels_path = pairs[-1]
    errors, _, current_summary = validate_labels(current_queue_path, current_labels_path)
    if errors:
        raise ValueError("Current review labels are invalid: " + "; ".join(errors))

    proposed_queue = build_queue(artifacts, input_root=input_root)
    current_queue = _load_json(current_queue_path)
    fingerprint = _artifact_fingerprint(artifacts)
    if proposed_queue.get("review_items") == current_queue.get("review_items"):
        result = {
            "status": "UP_TO_DATE",
            "updated_at_utc": _utc_now(),
            "source_artifact_count": len(artifacts),
            "source_artifacts": fingerprint,
            "current_revision": revision,
            "current_queue_json": str(current_queue_path),
            "current_labels_json": str(current_labels_path),
            "review_item_count": current_summary["queue_items"],
            "pending_review_count": current_summary["unreviewed"],
            "historical_actions_authorized": False,
        }
        _write_json(state_path, result)
        return result

    new_revision = revision + 1
    new_queue_path = output_root / f"action_review_queue_v{new_revision}.json"
    new_labels_path = output_root / f"action_review_labels_v{new_revision}.json"
    if new_queue_path.exists() or new_labels_path.exists():
        raise ValueError(f"Refusing to overwrite existing review revision v{new_revision}")
    _write_json(new_queue_path, proposed_queue)
    migrated = migrate_labels(current_queue_path, current_labels_path, new_queue_path)
    _write_json(new_labels_path, migrated)
    errors, warnings, summary = validate_labels(new_queue_path, new_labels_path)
    if errors:
        raise ValueError("Migrated review labels are invalid: " + "; ".join(errors))
    migration = migrated["metadata"]["migration"]
    result = {
        "status": "NEW_REVIEW_REQUIRED" if summary["unreviewed"] else "EXPANDED_NO_REVIEW_REQUIRED",
        "updated_at_utc": _utc_now(),
        "source_artifact_count": len(artifacts),
        "source_artifacts": fingerprint,
        "previous_revision": revision,
        "current_revision": new_revision,
        "current_queue_json": str(new_queue_path.resolve()),
        "current_labels_json": str(new_labels_path.resolve()),
        "review_item_count": summary["queue_items"],
        "pending_review_count": summary["unreviewed"],
        "preserved_label_count": migration["preserved_label_count"],
        "dropped_label_count": migration["dropped_label_count"],
        "warnings": warnings,
        "historical_actions_authorized": False,
    }
    _write_json(state_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain the H5.3 human-review queue safely.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    args = parser.parse_args()
    try:
        result = maintain(
            input_root=Path(args.input_root),
            output_root=Path(args.output_root),
            state_path=Path(args.state),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failure = {
            "status": "FAILED",
            "updated_at_utc": _utc_now(),
            "error": str(exc),
            "historical_actions_authorized": False,
        }
        _write_json(Path(args.state).resolve(), failure)
        print(f"H5.3 REVIEW MAINTENANCE: FAILED - {exc}")
        return 1
    print(
        "H5.3 REVIEW MAINTENANCE: "
        f"{result['status']} | pending={result['pending_review_count']}"
    )
    if result.get("current_queue_json"):
        print(f"Queue: {result['current_queue_json']}")
        print(f"Labels: {result['current_labels_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
