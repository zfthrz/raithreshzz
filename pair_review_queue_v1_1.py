from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUEUE_SCHEMA_VERSION = "1.1"


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


def stable_pair_id(pair: dict[str, Any]) -> str:
    track = str(pair.get("track") or "")
    side_a = (safe_int(pair.get("session_a")), safe_int(pair.get("episode_pk_a")))
    side_b = (safe_int(pair.get("session_b")), safe_int(pair.get("episode_pk_b")))
    payload = {"track": track, "sides": sorted([side_a, side_b])}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def load_pairs(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("episode_pair_features debe ser una lista JSON.")

    pairs = []
    seen = set()

    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Item {index} no es un objeto.")

        session_a = safe_int(item.get("session_a"))
        session_b = safe_int(item.get("session_b"))
        if session_a is None or session_b is None:
            raise ValueError(f"Item {index}: session_a/session_b inválidos.")
        if session_a == session_b:
            raise ValueError(f"Item {index}: no es cross-session.")

        pair = dict(item)
        pair_id = stable_pair_id(pair)
        if pair_id in seen:
            continue
        seen.add(pair_id)
        pair["pair_id"] = pair_id
        pairs.append(pair)

    return pairs


def numeric_key(pair: dict[str, Any], field: str, *, missing: float) -> float:
    value = safe_float(pair.get(field))
    return missing if value is None else value


def rank_lenses(pairs: list[dict[str, Any]], seed: int) -> dict[str, list[dict[str, Any]]]:
    lenses: dict[str, list[dict[str, Any]]] = {}

    lenses["closest_centers"] = sorted(
        pairs,
        key=lambda p: (
            numeric_key(p, "center_distance_abs_diff_m", missing=float("inf")),
            p["pair_id"],
        ),
    )

    lenses["highest_spatial_overlap"] = sorted(
        pairs,
        key=lambda p: (
            -numeric_key(p, "overlap_over_union", missing=-1.0),
            numeric_key(p, "center_distance_abs_diff_m", missing=float("inf")),
            p["pair_id"],
        ),
    )

    lenses["highest_channel_similarity"] = sorted(
        pairs,
        key=lambda p: (
            -numeric_key(p, "channel_jaccard", missing=-1.0),
            numeric_key(p, "center_distance_abs_diff_m", missing=float("inf")),
            p["pair_id"],
        ),
    )

    lenses["nearby_channel_disagreement"] = sorted(
        pairs,
        key=lambda p: (
            numeric_key(p, "center_distance_abs_diff_m", missing=float("inf")),
            numeric_key(p, "channel_jaccard", missing=2.0),
            -numeric_key(p, "overlap_over_union", missing=-1.0),
            p["pair_id"],
        ),
    )

    lenses["similar_channels_farther_apart"] = sorted(
        pairs,
        key=lambda p: (
            -numeric_key(p, "channel_jaccard", missing=-1.0),
            -numeric_key(p, "center_distance_abs_diff_m", missing=-1.0),
            p["pair_id"],
        ),
    )

    lenses["impact_divergence"] = sorted(
        pairs,
        key=lambda p: (
            numeric_key(p, "action_time_loss_similarity", missing=2.0),
            numeric_key(p, "center_distance_abs_diff_m", missing=float("inf")),
            p["pair_id"],
        ),
    )

    random_pairs = list(pairs)
    rng = random.Random(seed)
    rng.shuffle(random_pairs)
    lenses["deterministic_baseline"] = random_pairs

    return lenses


def select_queue(
    pairs: list[dict[str, Any]],
    per_lens: int,
    max_total: int | None,
    seed: int,
) -> list[dict[str, Any]]:
    if per_lens <= 0:
        raise ValueError("--per-lens debe ser > 0.")

    lenses = rank_lenses(pairs, seed=seed)
    selected: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    # v1.1: round-robin estratificado. Antes se tomaban los primeros N de
    # cada lente y luego se recortaba por cantidad de lentes que habían
    # seleccionado el mismo par. Con colas grandes eso podía concentrar el
    # review en pares muy parecidos. Ahora recorremos rank por rank entre
    # lentes, de modo que el límite global conserve cobertura diversa.
    lens_names = list(lenses.keys())
    for rank_index in range(per_lens):
        for lens_name in lens_names:
            ranked_pairs = lenses[lens_name]
            if rank_index >= len(ranked_pairs):
                continue

            pair = ranked_pairs[rank_index]
            pair_id = pair["pair_id"]
            rank = rank_index + 1

            if pair_id not in selected:
                selected[pair_id] = {
                    "pair_id": pair_id,
                    "selected_by": [],
                    "features": pair,
                }
                order.append(pair_id)

            selected[pair_id]["selected_by"].append(
                {"lens": lens_name, "rank": rank}
            )

            if max_total is not None and len(order) >= max_total:
                break

        if max_total is not None and len(order) >= max_total:
            break

    queue = [selected[pair_id] for pair_id in order]

    if max_total is not None:
        if max_total <= 0:
            raise ValueError("--max-total debe ser > 0.")
        queue = queue[:max_total]

    for index, item in enumerate(queue, start=1):
        item["queue_position"] = index

    return queue


def file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def write_queue(
    input_path: Path,
    output_path: Path,
    queue: list[dict[str, Any]],
    pair_count: int,
    per_lens: int,
    max_total: int | None,
    seed: int,
) -> None:
    payload = {
        "metadata": {
            "queue_schema_version": QUEUE_SCHEMA_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_features_path": str(input_path.resolve()),
            "source_features_sha256": file_sha256(input_path),
            "source_pair_count": pair_count,
            "selected_pair_count": len(queue),
            "per_lens": per_lens,
            "max_total": max_total,
            "seed": seed,
            "selection_policy": "round_robin_stratified_v1.1",
            "semantics": (
                "Selection lenses are review-ordering only. "
                "They are not matching decisions or labels. "
                "The queue is intentionally capped for manageable human review."
            ),
        },
        "queue": queue,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera una cola diversa de pares para revisión humana sin decidir matches."
    )
    parser.add_argument("features_json", help="JSON generado por episode_pair_features.py")
    parser.add_argument("--output", default="pair_review_queue.json")
    parser.add_argument("--per-lens", type=int, default=6)
    parser.add_argument("--max-total", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20260810)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.features_json).resolve()
    output_path = Path(args.output).resolve()

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    pairs = load_pairs(input_path)
    if not pairs:
        print("No hay pares cross-session para revisar.")
        return 2

    queue = select_queue(
        pairs,
        per_lens=args.per_lens,
        max_total=args.max_total,
        seed=args.seed,
    )

    write_queue(
        input_path,
        output_path,
        queue,
        pair_count=len(pairs),
        per_lens=args.per_lens,
        max_total=args.max_total,
        seed=args.seed,
    )

    print()
    print("=" * 70)
    print("RACE ENGINEER - PAIR REVIEW QUEUE v1.1")
    print("=" * 70)
    print()
    print(f"Source pairs: {len(pairs)}")
    print(f"Selected unique pairs: {len(queue)}")
    print(f"Output: {output_path}")
    print()
    print("No matching decision was made.")
    print("The queue is for human calibration review only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
