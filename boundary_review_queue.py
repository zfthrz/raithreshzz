from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Emit the existing queue contract so label_episode_pairs.py can consume it.
QUEUE_SCHEMA_VERSION = "1.1"
BOUNDARY_SELECTOR_VERSION = "1.0"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def stable_pair_id(pair: dict[str, Any]) -> str:
    track = str(pair.get("track") or "")
    side_a = (safe_int(pair.get("session_a")), safe_int(pair.get("episode_pk_a")))
    side_b = (safe_int(pair.get("session_b")), safe_int(pair.get("episode_pk_b")))
    payload = {"track": track, "sides": sorted([side_a, side_b])}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def load_pairs(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("episode_pair_features debe ser una lista JSON.")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Item {idx} no es un objeto.")
        pair = dict(item)
        pair_id = stable_pair_id(pair)
        if pair_id in seen:
            continue
        seen.add(pair_id)
        pair["pair_id"] = pair_id
        out.append(pair)
    return out


def load_labeled_ids(path: Path) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw.get("labels") if isinstance(raw, dict) else None
    if not isinstance(records, list):
        raise ValueError("pair_labels.json no contiene labels[].")
    return {str(r.get("pair_id")) for r in records if isinstance(r, dict) and r.get("pair_id")}


def per_channel_values(pair: dict[str, Any], key: str) -> list[float]:
    pcm = pair.get("per_channel_metrics")
    if not isinstance(pcm, dict):
        return []
    vals: list[float] = []
    for metric in pcm.values():
        if not isinstance(metric, dict):
            continue
        value = safe_float(metric.get(key))
        if value is not None:
            vals.append(value)
    return vals


def mean_or(values: list[float], default: float) -> float:
    return sum(values) / len(values) if values else default


def shape_conflict_score(pair: dict[str, Any]) -> float:
    """Review-order score only; NOT a matcher score or threshold."""
    coverage = mean_or(per_channel_values(pair, "coverage_abs_diff"), 0.0)
    onset = mean_or(per_channel_values(pair, "onset_offset_abs_diff_m"), 0.0)
    end = mean_or(per_channel_values(pair, "end_offset_abs_diff_m"), 0.0)
    mean_sim = mean_or(per_channel_values(pair, "mean_difference_similarity"), 1.0)
    peak_sim = mean_or(per_channel_values(pair, "peak_difference_similarity"), 1.0)
    # Bounded-ish ranking heuristic. Distances are capped so one huge event cannot dominate.
    return (
        min(coverage, 1.0)
        + min(onset / 40.0, 1.0)
        + min(end / 40.0, 1.0)
        + (1.0 - max(0.0, min(mean_sim, 1.0)))
        + 0.5 * (1.0 - max(0.0, min(peak_sim, 1.0)))
    )


def num(pair: dict[str, Any], key: str, default: float) -> float:
    value = safe_float(pair.get(key))
    return default if value is None else value


def shared_count(pair: dict[str, Any]) -> int:
    shared = pair.get("shared_channels")
    return len(shared) if isinstance(shared, list) else 0


def rank_lenses(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    # These bounds are sampling windows only. They MUST NOT be reused as matcher thresholds.
    nearby = [
        p for p in candidates
        if num(p, "center_distance_abs_diff_m", float("inf")) <= 250.0 and shared_count(p) >= 1
    ]

    lenses: dict[str, list[dict[str, Any]]] = {}

    # 1) Same/overlapping region but strongly different shared-channel shape.
    overlap_conflict = [p for p in nearby if num(p, "overlap_over_shorter", 0.0) >= 0.50]
    lenses["overlap_shape_conflict"] = sorted(
        overlap_conflict,
        key=lambda p: (
            -shape_conflict_score(p),
            num(p, "center_distance_abs_diff_m", float("inf")),
            p["pair_id"],
        ),
    )

    # 2) Adjacent events: spatially close, little/no overlap, at least one shared channel.
    adjacent = [
        p for p in nearby
        if 5.0 <= num(p, "center_distance_abs_diff_m", float("inf")) <= 150.0
        and num(p, "overlap_over_union", 0.0) <= 0.25
    ]
    lenses["nearby_low_overlap"] = sorted(
        adjacent,
        key=lambda p: (
            num(p, "center_distance_abs_diff_m", float("inf")),
            -num(p, "channel_jaccard", -1.0),
            p["pair_id"],
        ),
    )

    # 3) Very close centers but channel identity disagreement.
    channel_conflict = [
        p for p in nearby
        if num(p, "center_distance_abs_diff_m", float("inf")) <= 40.0
        and num(p, "channel_jaccard", 1.0) < 1.0
    ]
    lenses["very_close_channel_conflict"] = sorted(
        channel_conflict,
        key=lambda p: (
            num(p, "channel_jaccard", 1.0),
            -shape_conflict_score(p),
            num(p, "center_distance_abs_diff_m", float("inf")),
            p["pair_id"],
        ),
    )

    # 4) High channel identity in nearby but not trivially coincident locations.
    similar_channels = [
        p for p in nearby
        if num(p, "channel_jaccard", 0.0) >= 0.50
        and 5.0 <= num(p, "center_distance_abs_diff_m", float("inf")) <= 250.0
    ]
    lenses["nearby_similar_channels"] = sorted(
        similar_channels,
        key=lambda p: (
            num(p, "center_distance_abs_diff_m", float("inf")),
            num(p, "overlap_over_shorter", 0.0),
            -shape_conflict_score(p),
            p["pair_id"],
        ),
    )

    return lenses


def select_queue(candidates: list[dict[str, Any]], max_total: int) -> list[dict[str, Any]]:
    if max_total <= 0:
        raise ValueError("--max-total debe ser > 0")
    lenses = rank_lenses(candidates)
    names = list(lenses)
    selected: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    # Round-robin through ranks, preserving hard-case diversity.
    max_rank = max((len(v) for v in lenses.values()), default=0)
    for rank_index in range(max_rank):
        for name in names:
            ranked = lenses[name]
            if rank_index >= len(ranked):
                continue
            pair = ranked[rank_index]
            pair_id = pair["pair_id"]
            if pair_id not in selected:
                selected[pair_id] = {"pair_id": pair_id, "selected_by": [], "features": pair}
                order.append(pair_id)
            selected[pair_id]["selected_by"].append({"lens": name, "rank": rank_index + 1})
            if len(order) >= max_total:
                break
        if len(order) >= max_total:
            break

    queue = [selected[pair_id] for pair_id in order[:max_total]]
    for i, item in enumerate(queue, start=1):
        item["queue_position"] = i
    return queue


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Selecciona pocos hard cases cercanos para calibrar la frontera SAME/DIFFERENT. No decide matches."
    )
    ap.add_argument("features_json")
    ap.add_argument("existing_labels_json")
    ap.add_argument("--output", default="boundary_review_queue.json")
    ap.add_argument("--max-total", type=int, default=8)
    args = ap.parse_args()

    features_path = Path(args.features_json).resolve()
    labels_path = Path(args.existing_labels_json).resolve()
    output_path = Path(args.output).resolve()
    if not features_path.exists():
        raise FileNotFoundError(features_path)
    if not labels_path.exists():
        raise FileNotFoundError(labels_path)

    pairs = load_pairs(features_path)
    labeled_ids = load_labeled_ids(labels_path)
    candidates = [p for p in pairs if p["pair_id"] not in labeled_ids]
    queue = select_queue(candidates, max_total=args.max_total)

    payload = {
        "metadata": {
            "queue_schema_version": QUEUE_SCHEMA_VERSION,
            "boundary_selector_version": BOUNDARY_SELECTOR_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_features_path": str(features_path),
            "source_features_sha256": file_sha256(features_path),
            "existing_labels_path": str(labels_path),
            "existing_labels_sha256": file_sha256(labels_path),
            "source_pair_count": len(pairs),
            "excluded_already_labeled_count": len(labeled_ids),
            "candidate_count_after_exclusion": len(candidates),
            "selected_pair_count": len(queue),
            "max_total": args.max_total,
            "selection_policy": "boundary_hard_cases_v1.0",
            "semantics": (
                "Focused human-review sample for boundary calibration only. "
                "Sampling windows and shape_conflict_score are review-order heuristics, "
                "not matcher thresholds, weights, probabilities, or decisions."
            ),
        },
        "queue": queue,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 72)
    print("RACE ENGINEER - BOUNDARY REVIEW QUEUE v1.0")
    print("=" * 72)
    print(f"Source pairs: {len(pairs)}")
    print(f"Already labeled excluded: {len(labeled_ids)}")
    print(f"Selected hard cases: {len(queue)}")
    print(f"Output: {output_path}")
    print("No matcher decision was made.")
    return 0 if queue else 2


if __name__ == "__main__":
    raise SystemExit(main())
