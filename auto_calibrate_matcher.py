from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_calibration_dataset import assign_sessions, collect_sessions, label_counts, partition_records
from validate_pair_labels import validate as validate_pair_labels

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BATCHES_ROOT = PROJECT_ROOT / "calibration_batches"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "generated"
    / "diagnostics"
    / "h2_auto_calibration_shadow.json"
)

PROVISIONAL_MIN_LABELS = 24
CALIBRATED_MIN_LABELS = 72
CALIBRATED_MIN_SESSIONS = 6
CALIBRATED_MIN_EVAL_PAIRS = 4

MATCH_CENTER_MAX_M = 200.0
MATCH_OVERLAP_SHORTER_MIN = 0.90
MATCH_OVERLAP_UNION_MIN = 0.40
MATCH_SHARED_CHANNEL_MIN = 1
REJECT_OVERLAP_UNION_MAX = 0.33
REJECT_DISABLED_CENTER_M = 1_000_000_000.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(path)
    return data


def _context(payload: dict[str, Any]) -> tuple[str, str, str] | None:
    key = (
        str(payload.get("track") or "").strip(),
        str(payload.get("track_layout") or "").strip(),
        str(payload.get("vehicle_variant") or "").strip(),
    )
    return key if all(key) else None


def _batch_path(status_path: Path, payload: dict[str, Any], raw: Any, fallback: str) -> Path:
    batch_dir = Path(payload.get("batch_dir") or status_path.parent)
    if not batch_dir.is_absolute():
        batch_dir = (status_path.parent / batch_dir).resolve()
    path = Path(raw) if isinstance(raw, str) and raw.strip() else batch_dir / fallback
    if not path.is_absolute():
        path = (batch_dir / path).resolve()
    return path


def collect_records(batches_root: Path):
    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
    conflicts: dict[tuple[str, str, str], list[str]] = {}

    for status_path in sorted(batches_root.glob("*/BATCH_STATUS.json")):
        try:
            payload = load_json(status_path)
        except Exception:
            continue
        key = _context(payload)
        if key is None:
            continue
        steps = payload.get("steps") if isinstance(payload.get("steps"), dict) else {}
        review = steps.get("review_queue") if isinstance(steps.get("review_queue"), dict) else {}
        human = steps.get("human_labels") if isinstance(steps.get("human_labels"), dict) else {}
        queue_path = _batch_path(status_path, payload, review.get("path"), "pair_review_queue.json")
        labels_path = _batch_path(status_path, payload, human.get("labels_path"), "pair_labels.json")
        if not queue_path.is_file() or not labels_path.is_file():
            continue
        try:
            errors, _warnings, _summary = validate_pair_labels(queue_path, labels_path)
        except Exception:
            continue
        if errors:
            continue
        queue = load_json(queue_path).get("queue")
        labels = load_json(labels_path).get("labels")
        if not isinstance(queue, list) or not isinstance(labels, list):
            continue
        queue_by_id = {
            item.get("pair_id"): item
            for item in queue
            if isinstance(item, dict) and isinstance(item.get("pair_id"), str)
        }
        dest = grouped.setdefault(key, {})
        for label_record in labels:
            if not isinstance(label_record, dict):
                continue
            pair_id = label_record.get("pair_id")
            label = label_record.get("human_label")
            if label not in {"SAME", "DIFFERENT", "AMBIGUOUS"} or pair_id not in queue_by_id:
                continue
            features = queue_by_id[pair_id].get("features")
            if not isinstance(features, dict):
                continue
            record = {
                "pair_id": pair_id,
                "human_label": label,
                "reviewed_at_utc": label_record.get("reviewed_at_utc"),
                "features": features,
                "batch_id": str(payload.get("batch_id") or status_path.parent.name),
            }
            old = dest.get(pair_id)
            if old is None:
                dest[pair_id] = record
                continue

            if old["human_label"] == label:
                old_time = str(old.get("reviewed_at_utc") or "")
                new_time = str(record.get("reviewed_at_utc") or "")
                if new_time > old_time:
                    dest[pair_id] = record
                continue

            old_time = str(old.get("reviewed_at_utc") or "")
            new_time = str(record.get("reviewed_at_utc") or "")

            # Explicit later human correction supersedes an older decision.
            # Missing/equal timestamps remain fail-closed as a true conflict.
            if old_time and new_time and old_time != new_time:
                if new_time > old_time:
                    dest[pair_id] = record
                continue

            conflicts.setdefault(key, []).append(pair_id)

    return {key: list(items.values()) for key, items in grouped.items()}, conflicts


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def derive_thresholds(calibration: list[dict[str, Any]]) -> dict[str, Any]:
    strong_same = []
    different_zero_overlap = []
    protected_zero_overlap = []

    for record in calibration:
        f = record["features"]
        center = _f(f.get("center_distance_abs_diff_m"))
        shorter = _f(f.get("overlap_over_shorter"))
        union = _f(f.get("overlap_over_union"))
        shared = f.get("shared_channels")
        shared_count = len(shared) if isinstance(shared, list) else 0
        if center is None or shorter is None or union is None:
            continue
        if (
            record["human_label"] == "SAME"
            and center <= MATCH_CENTER_MAX_M
            and shorter >= MATCH_OVERLAP_SHORTER_MIN
            and union >= MATCH_OVERLAP_UNION_MIN
            and shared_count >= MATCH_SHARED_CHANNEL_MIN
        ):
            strong_same.append(record)
        if union <= REJECT_OVERLAP_UNION_MAX:
            if record["human_label"] == "DIFFERENT":
                different_zero_overlap.append(center)
            else:
                protected_zero_overlap.append(center)

    match_enabled = bool(strong_same)
    reject_center = REJECT_DISABLED_CENTER_M
    if different_zero_overlap:
        low = max(protected_zero_overlap, default=0.0)
        high = min(different_zero_overlap)
        if high - low >= 25.0:
            reject_center = (low + high) / 2.0

    return {
        "match_enabled": match_enabled,
        "match_center_max_m": MATCH_CENTER_MAX_M,
        "match_overlap_shorter_min": MATCH_OVERLAP_SHORTER_MIN,
        "match_overlap_union_min": MATCH_OVERLAP_UNION_MIN,
        "match_shared_channel_min": MATCH_SHARED_CHANNEL_MIN,
        "extended_match_center_max_m": None,
        "shape_conflict_mean_sim_max": 0.20,
        "shape_conflict_coverage_diff_min": 0.50,
        "shape_conflict_impact_sim_max": 0.45,
        "reject_center_gt_m": reject_center,
        "reject_overlap_union_max": REJECT_OVERLAP_UNION_MAX,
    }


def choose_status(records, sessions, calibration, evaluation, cal_counts, eval_counts, thresholds):
    if len(records) < PROVISIONAL_MIN_LABELS:
        return None, ["insufficient_labels"]
    if len(calibration) < 4:
        return None, ["insufficient_calibration_pairs"]
    if cal_counts.get("SAME", 0) < 1:
        return None, ["no_same_in_calibration"]
    if cal_counts.get("DIFFERENT", 0) < 1:
        return None, ["no_different_in_calibration"]
    if not thresholds.get("match_enabled"):
        return None, ["no_high_precision_same_core"]

    full = (
        len(records) >= CALIBRATED_MIN_LABELS
        and len(sessions) >= CALIBRATED_MIN_SESSIONS
        and len(evaluation) >= CALIBRATED_MIN_EVAL_PAIRS
        and cal_counts.get("SAME", 0) >= 3
        and cal_counts.get("DIFFERENT", 0) >= 3
        and eval_counts.get("SAME", 0) >= 1
        and eval_counts.get("DIFFERENT", 0) >= 1
    )
    return (
        "CANDIDATE_CALIBRATED"
        if full
        else "CANDIDATE_CALIBRATED_PROVISIONAL_LOW_EVIDENCE"
    ), []


def build_registry(batches_root: Path) -> dict[str, Any]:
    grouped, conflicts = collect_records(batches_root)
    contexts = []

    for key in sorted(grouped):
        records = grouped[key]
        if conflicts.get(key):
            contexts.append({
                "track": key[0],
                "track_layout": key[1],
                "vehicle_variant": key[2],
                "status": "BLOCKED_CONFLICTING_HUMAN_LABELS",
                "authorized": False,
                "human_labels": len(records),
                "thresholds": None,
                "provenance": {"conflicting_pair_ids": sorted(set(conflicts[key]))},
            })
            continue

        sessions = collect_sessions(records)
        assignment = assign_sessions(sessions, evaluation_fraction=0.25, seed=20260810)
        calibration, evaluation, cross_split = partition_records(records, assignment)
        cal_counts = label_counts(calibration)
        eval_counts = label_counts(evaluation)
        thresholds = derive_thresholds(calibration)
        status, reasons = choose_status(
            records, sessions, calibration, evaluation, cal_counts, eval_counts, thresholds
        )
        contexts.append({
            "track": key[0],
            "track_layout": key[1],
            "vehicle_variant": key[2],
            "status": status or "NOT_READY_FOR_AUTO_CALIBRATION",
            "authorized": False,
            "human_labels": len(records),
            "thresholds": thresholds if status is not None else None,
            "provenance": {
                "source": "AUTO_HUMAN_LABEL_CALIBRATION",
                "usable_sessions": len(sessions),
                "calibration_pairs": len(calibration),
                "evaluation_pairs": len(evaluation),
                "cross_split_pairs_excluded": len(cross_split),
                "calibration_labels": cal_counts,
                "evaluation_labels": eval_counts,
                "all_labels": dict(Counter(r["human_label"] for r in records)),
                "gate_reasons": reasons,
            },
        })

    return {
        "schema_version": 1,
        "updated_at_utc": utc_now_iso(),
        "authority": "SHADOW_ONLY",
        "policy": {
            "provisional_min_labels": PROVISIONAL_MIN_LABELS,
            "calibrated_min_labels": CALIBRATED_MIN_LABELS,
            "calibrated_min_sessions": CALIBRATED_MIN_SESSIONS,
            "calibrated_min_evaluation_pairs": CALIBRATED_MIN_EVAL_PAIRS,
            "pair_count_alone_never_authorizes": True,
            "production_matcher_reads_this_output": False,
        },
        "contexts": contexts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches-root", default=str(DEFAULT_BATCHES_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    registry = build_registry(Path(args.batches_root).resolve())
    if not args.dry_run:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix(output.suffix + ".tmp")
        tmp.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(output)

    print(json.dumps({
        "contexts": len(registry["contexts"]),
        "authority": registry["authority"],
        "authorized": sum(1 for c in registry["contexts"] if c.get("authorized")),
        "calibrated_candidates": sum(
            1 for c in registry["contexts"]
            if c.get("status") == "CANDIDATE_CALIBRATED"
        ),
        "provisional_candidates": sum(
            1 for c in registry["contexts"]
            if c.get("status")
            == "CANDIDATE_CALIBRATED_PROVISIONAL_LOW_EVIDENCE"
        ),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
