from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUEUE_SCHEMA_VERSION = "1.1"
SELECTOR_VERSION = "1.0"

# Sampling windows ONLY. These are not matcher thresholds.
DISTANCE_BANDS = (
    ("gt45_to_100m", 45.0, 100.0),
    ("gt100_to_250m", 100.0, 250.0),
    ("gt250_to_400m", 250.0, 400.0),
    ("gt400_to_lt623_5m", 400.0, 623.5),
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def num(pair: dict[str, Any], key: str, default: float) -> float:
    value = safe_float(pair.get(key))
    return default if value is None else value


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


def load_labeled_ids(paths: list[Path]) -> set[str]:
    result: set[str] = set()
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        records = raw.get("labels") if isinstance(raw, dict) else None
        if not isinstance(records, list):
            raise ValueError(f"{path} no contiene labels[].")
        for record in records:
            if isinstance(record, dict) and record.get("pair_id"):
                result.add(str(record["pair_id"]))
    return result


def shared_count(pair: dict[str, Any]) -> int:
    value = pair.get("shared_channels")
    return len(value) if isinstance(value, list) else 0


def per_channel_values(pair: dict[str, Any], key: str) -> list[float]:
    metrics = pair.get("per_channel_metrics")
    if not isinstance(metrics, dict):
        return []
    values: list[float] = []
    for metric in metrics.values():
        if not isinstance(metric, dict):
            continue
        value = safe_float(metric.get(key))
        if value is not None:
            values.append(value)
    return values


def mean_or(values: list[float], default: float) -> float:
    return sum(values) / len(values) if values else default


def shape_similarity_for_sampling(pair: dict[str, Any]) -> float:
    """Review-order heuristic only. NOT a matcher score."""
    mean_sim = mean_or(per_channel_values(pair, "mean_difference_similarity"), 0.0)
    peak_sim = mean_or(per_channel_values(pair, "peak_difference_similarity"), 0.0)
    coverage = mean_or(per_channel_values(pair, "coverage_abs_diff"), 1.0)
    onset = mean_or(per_channel_values(pair, "onset_offset_abs_diff_m"), 100.0)
    end = mean_or(per_channel_values(pair, "end_offset_abs_diff_m"), 100.0)
    timing_similarity = 1.0 - min((onset + end) / 160.0, 1.0)
    coverage_similarity = 1.0 - min(max(coverage, 0.0), 1.0)
    return (
        0.35 * max(0.0, min(mean_sim, 1.0))
        + 0.25 * max(0.0, min(peak_sim, 1.0))
        + 0.20 * coverage_similarity
        + 0.20 * timing_similarity
    )


def in_band(distance: float, low_exclusive: float, high_inclusive: float) -> bool:
    return distance > low_exclusive and distance <= high_inclusive


def band_candidates(
    candidates: list[dict[str, Any]], low: float, high: float
) -> list[dict[str, Any]]:
    return [
        p
        for p in candidates
        if in_band(num(p, "center_distance_abs_diff_m", float("inf")), low, high)
        and shared_count(p) >= 1
    ]


def pick_two_for_band(
    candidates: list[dict[str, Any]],
    band_name: str,
    low: float,
    high: float,
) -> list[dict[str, Any]]:
    pool = band_candidates(candidates, low, high)
    if not pool:
        return []

    # Lens A: closest-to-boundary case. This probes how far downward REJECT could move.
    closest = sorted(
        pool,
        key=lambda p: (
            num(p, "center_distance_abs_diff_m", float("inf")),
            -num(p, "channel_jaccard", 0.0),
            -shared_count(p),
            -shape_similarity_for_sampling(p),
            p["pair_id"],
        ),
    )

    # Lens B: adversarial negative candidate: high channel/shape similarity and low overlap.
    adversarial = sorted(
        pool,
        key=lambda p: (
            -num(p, "channel_jaccard", 0.0),
            -shared_count(p),
            -shape_similarity_for_sampling(p),
            num(p, "overlap_over_union", 0.0),
            num(p, "center_distance_abs_diff_m", float("inf")),
            p["pair_id"],
        ),
    )

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lens_name, ranked in (("closest_in_band", closest), ("channel_shape_adversarial", adversarial)):
        for rank, pair in enumerate(ranked, start=1):
            if pair["pair_id"] in seen:
                continue
            seen.add(pair["pair_id"])
            selected.append({
                "pair_id": pair["pair_id"],
                "selected_by": [{"lens": f"{band_name}:{lens_name}", "rank": rank}],
                "features": pair,
            })
            break
    return selected


def select_queue(candidates: list[dict[str, Any]], max_total: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for band_name, low, high in DISTANCE_BANDS:
        for item in pick_two_for_band(candidates, band_name, low, high):
            if item["pair_id"] in seen:
                continue
            seen.add(item["pair_id"])
            selected.append(item)
            if len(selected) >= max_total:
                break
        if len(selected) >= max_total:
            break

    # Backfill only inside the same target window, prioritizing distance coverage.
    if len(selected) < max_total:
        remaining = [
            p for p in candidates
            if p["pair_id"] not in seen
            and 45.0 < num(p, "center_distance_abs_diff_m", float("inf")) < 623.5
            and shared_count(p) >= 1
        ]
        remaining = sorted(
            remaining,
            key=lambda p: (
                -num(p, "channel_jaccard", 0.0),
                -shape_similarity_for_sampling(p),
                num(p, "center_distance_abs_diff_m", float("inf")),
                p["pair_id"],
            ),
        )
        for pair in remaining:
            selected.append({
                "pair_id": pair["pair_id"],
                "selected_by": [{"lens": "backfill_target_window", "rank": len(selected) + 1}],
                "features": pair,
            })
            seen.add(pair["pair_id"])
            if len(selected) >= max_total:
                break

    for idx, item in enumerate(selected, start=1):
        item["queue_position"] = idx
    return selected


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Selecciona una muestra humana pequeña dentro de 45-623.5 m para calibrar "
            "el límite de REJECT. No decide matches ni thresholds."
        )
    )
    ap.add_argument("features_json")
    ap.add_argument("--labels", nargs="+", required=True, help="Uno o más JSON de labels ya revisados.")
    ap.add_argument("--output", default="reject_boundary_review_queue.json")
    ap.add_argument("--max-total", type=int, default=8)
    args = ap.parse_args()

    if args.max_total <= 0:
        raise ValueError("--max-total debe ser > 0")

    features_path = Path(args.features_json).resolve()
    label_paths = [Path(p).resolve() for p in args.labels]
    output_path = Path(args.output).resolve()

    if not features_path.exists():
        raise FileNotFoundError(features_path)
    for path in label_paths:
        if not path.exists():
            raise FileNotFoundError(path)

    pairs = load_pairs(features_path)
    labeled_ids = load_labeled_ids(label_paths)
    candidates = [p for p in pairs if p["pair_id"] not in labeled_ids]
    queue = select_queue(candidates, args.max_total)

    payload = {
        "metadata": {
            "queue_schema_version": QUEUE_SCHEMA_VERSION,
            "reject_boundary_selector_version": SELECTOR_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_features_path": str(features_path),
            "source_features_sha256": file_sha256(features_path),
            "existing_labels": [
                {"path": str(p), "sha256": file_sha256(p)} for p in label_paths
            ],
            "source_pair_count": len(pairs),
            "excluded_already_labeled_count": len(labeled_ids),
            "candidate_count_after_exclusion": len(candidates),
            "selected_pair_count": len(queue),
            "max_total": args.max_total,
            "selection_policy": "reject_boundary_stratified_adversarial_v1.0",
            "distance_sampling_bands_m": [
                {"name": name, "low_exclusive": low, "high_inclusive": high}
                for name, low, high in DISTANCE_BANDS
            ],
            "semantics": (
                "Human-review sampling only. Distance bands, channel/shape ranking, and all "
                "selection heuristics are NOT matcher thresholds, scores, probabilities, or decisions."
            ),
        },
        "queue": queue,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 72)
    print("RACE ENGINEER - REJECT BOUNDARY REVIEW QUEUE v1.0")
    print("=" * 72)
    print(f"Source pairs: {len(pairs)}")
    print(f"Already labeled excluded: {len(labeled_ids)}")
    print(f"Selected boundary cases: {len(queue)}")
    for item in queue:
        f = item["features"]
        print(
            f"  {item['queue_position']}: {item['pair_id']} "
            f"center={num(f, 'center_distance_abs_diff_m', float('nan')):.1f}m "
            f"overlap_union={num(f, 'overlap_over_union', float('nan')):.3f} "
            f"jaccard={num(f, 'channel_jaccard', float('nan')):.3f} "
            f"via={item['selected_by'][0]['lens']}"
        )
    print(f"Output: {output_path}")
    print("No matcher decision or threshold was changed.")
    return 0 if queue else 2


if __name__ == "__main__":
    raise SystemExit(main())
