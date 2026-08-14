from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "1.0"
DEFAULT_QUOTAS = {
    "same_high_boundary": 6,
    "same_medium_boundary": 6,
    "different_high_boundary": 6,
    "different_medium_boundary": 6,
    "ambiguous_diverse": 8,
}
FORBIDDEN_HUMAN_QUEUE_KEYS = {
    "human_label", "review_notes", "deepseek_label", "deepseek_confidence",
    "matcher_decision", "decision", "rule_id", "matcher_rule", "selected_by_deepseek",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_float(v: Any, default: float | None = None) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return x


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pool(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = load_json(path)
    if not isinstance(raw, dict) or not isinstance(raw.get("pairs"), list):
        raise ValueError("Pool inválido: se esperaba objeto con lista 'pairs'.")
    pairs = []
    seen = set()
    for i, item in enumerate(raw["pairs"]):
        if not isinstance(item, dict):
            raise ValueError(f"pairs[{i}] no es objeto.")
        pid = item.get("pair_id")
        features = item.get("feature_snapshot")
        if not isinstance(pid, str) or not pid:
            raise ValueError(f"pairs[{i}].pair_id inválido.")
        if pid in seen:
            raise ValueError(f"pair_id duplicado en pool: {pid}")
        if not isinstance(features, dict):
            raise ValueError(f"pairs[{i}].feature_snapshot inválido.")
        seen.add(pid)
        pairs.append(item)
    return raw.get("metadata") or {}, pairs


def load_reviews(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    raw = load_json(path)
    if not isinstance(raw, dict) or not isinstance(raw.get("reviews"), list):
        raise ValueError("Reviews inválido: se esperaba objeto con lista 'reviews'.")
    by_id: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(raw["reviews"]):
        if not isinstance(r, dict):
            raise ValueError(f"reviews[{i}] no es objeto.")
        pid = r.get("pair_id")
        if not isinstance(pid, str) or not pid:
            raise ValueError(f"reviews[{i}].pair_id inválido.")
        if pid in by_id:
            raise ValueError(f"pair_id duplicado en reviews: {pid}")
        by_id[pid] = r
    return raw.get("metadata") or {}, by_id


def load_existing_labels(paths: list[Path]) -> set[str]:
    ids: set[str] = set()
    for path in paths:
        raw = load_json(path)
        labels = raw.get("labels") if isinstance(raw, dict) else None
        if not isinstance(labels, list):
            raise ValueError(f"Labels inválido: {path}")
        for row in labels:
            if isinstance(row, dict) and isinstance(row.get("pair_id"), str):
                ids.add(row["pair_id"])
    return ids


def f(features: dict[str, Any], key: str, missing: float) -> float:
    x = safe_float(features.get(key))
    return missing if x is None else x


def same_boundary_key(item: dict[str, Any]) -> tuple[Any, ...]:
    """DeepSeek says SAME: prefer the hardest/most expansive SAME candidates."""
    ft = item["feature_snapshot"]
    return (
        -f(ft, "center_distance_abs_diff_m", -1.0),
        f(ft, "overlap_over_shorter", 2.0),
        f(ft, "overlap_over_union", 2.0),
        f(ft, "channel_jaccard", 2.0),
        item["pair_id"],
    )


def different_boundary_key(item: dict[str, Any]) -> tuple[Any, ...]:
    """DeepSeek says DIFFERENT: prefer the most dangerous cases to auto-reject."""
    ft = item["feature_snapshot"]
    return (
        f(ft, "center_distance_abs_diff_m", float("inf")),
        -f(ft, "overlap_over_shorter", -1.0),
        -f(ft, "overlap_over_union", -1.0),
        -f(ft, "channel_jaccard", -1.0),
        item["pair_id"],
    )


def distance_bin(features: dict[str, Any]) -> str:
    x = safe_float(features.get("center_distance_abs_diff_m"))
    if x is None:
        return "missing"
    if x <= 5.5:
        return "0-5.5"
    if x <= 20.0:
        return "5.5-20"
    if x <= 45.0:
        return "20-45"
    if x <= 100.0:
        return "45-100"
    if x <= 250.0:
        return "100-250"
    return ">250"


def ambiguous_diverse(items: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    if n <= 0:
        return []
    bin_order = ["0-5.5", "5.5-20", "20-45", "45-100", "100-250", ">250", "missing"]
    confidence_order = ["MEDIUM", "LOW"]
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        review = item["_review"]
        buckets[(distance_bin(item["feature_snapshot"]), str(review.get("confidence")))].append(item)
    for rows in buckets.values():
        rows.sort(key=lambda x: x["pair_id"])

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    while len(selected) < n:
        added = False
        for b in bin_order:
            for conf in confidence_order:
                rows = buckets.get((b, conf), [])
                while rows and rows[0]["pair_id"] in seen:
                    rows.pop(0)
                if rows:
                    item = rows.pop(0)
                    selected.append(item)
                    seen.add(item["pair_id"])
                    added = True
                    if len(selected) >= n:
                        return selected
        if not added:
            break
    return selected


def contains_forbidden_key(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_HUMAN_QUEUE_KEYS:
                return k
            bad = contains_forbidden_key(v)
            if bad:
                return bad
    elif isinstance(obj, list):
        for v in obj:
            bad = contains_forbidden_key(v)
            if bad:
                return bad
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Genera una cola humana ciega y estratificada a partir del pre-review DeepSeek. "
            "DeepSeek se usa sólo para seleccionar casos; su label/confidence NO se muestran al revisor humano."
        )
    )
    ap.add_argument("pool_json")
    ap.add_argument("reviews_json")
    ap.add_argument("--labels", nargs="*", default=[], help="Archivos de labels humanos previos a excluir.")
    ap.add_argument("--output", default="deepseek_human_review_queue.json")
    ap.add_argument("--audit-output", default="deepseek_human_review_selection_audit.json")
    ap.add_argument("--max-total", type=int, default=32)
    ap.add_argument("--same-high", type=int, default=DEFAULT_QUOTAS["same_high_boundary"])
    ap.add_argument("--same-medium", type=int, default=DEFAULT_QUOTAS["same_medium_boundary"])
    ap.add_argument("--different-high", type=int, default=DEFAULT_QUOTAS["different_high_boundary"])
    ap.add_argument("--different-medium", type=int, default=DEFAULT_QUOTAS["different_medium_boundary"])
    ap.add_argument("--ambiguous", type=int, default=DEFAULT_QUOTAS["ambiguous_diverse"])
    args = ap.parse_args()

    if args.max_total <= 0:
        raise ValueError("--max-total debe ser > 0.")
    quotas = {
        "same_high_boundary": args.same_high,
        "same_medium_boundary": args.same_medium,
        "different_high_boundary": args.different_high,
        "different_medium_boundary": args.different_medium,
        "ambiguous_diverse": args.ambiguous,
    }
    if any(v < 0 for v in quotas.values()):
        raise ValueError("Las cuotas no pueden ser negativas.")
    if sum(quotas.values()) > args.max_total:
        raise ValueError("La suma de cuotas supera --max-total.")

    pool_path = Path(args.pool_json).resolve()
    reviews_path = Path(args.reviews_json).resolve()
    label_paths = [Path(x).resolve() for x in args.labels]
    out_path = Path(args.output).resolve()
    audit_path = Path(args.audit_output).resolve()

    pool_meta, pool_pairs = load_pool(pool_path)
    review_meta, reviews_by_id = load_reviews(reviews_path)
    excluded_ids = load_existing_labels(label_paths)

    if review_meta.get("source_pair_count") not in (None, len(pool_pairs)):
        raise ValueError("reviews.source_pair_count no coincide con el pool.")

    candidates: list[dict[str, Any]] = []
    missing_review: list[str] = []
    invalid_review: list[str] = []
    for p in pool_pairs:
        pid = p["pair_id"]
        if pid in excluded_ids:
            continue
        r = reviews_by_id.get(pid)
        if r is None:
            missing_review.append(pid)
            continue
        if r.get("status") != "VALID":
            invalid_review.append(pid)
            continue
        if r.get("label") not in {"SAME", "DIFFERENT", "AMBIGUOUS"}:
            invalid_review.append(pid)
            continue
        if r.get("confidence") not in {"HIGH", "MEDIUM", "LOW"}:
            invalid_review.append(pid)
            continue
        row = dict(p)
        row["_review"] = r
        candidates.append(row)

    strata: dict[str, list[dict[str, Any]]] = {
        "same_high_boundary": [],
        "same_medium_boundary": [],
        "different_high_boundary": [],
        "different_medium_boundary": [],
        "ambiguous_diverse": [],
    }
    for item in candidates:
        r = item["_review"]
        key = None
        if r["label"] == "SAME" and r["confidence"] == "HIGH":
            key = "same_high_boundary"
        elif r["label"] == "SAME" and r["confidence"] == "MEDIUM":
            key = "same_medium_boundary"
        elif r["label"] == "DIFFERENT" and r["confidence"] == "HIGH":
            key = "different_high_boundary"
        elif r["label"] == "DIFFERENT" and r["confidence"] == "MEDIUM":
            key = "different_medium_boundary"
        elif r["label"] == "AMBIGUOUS":
            key = "ambiguous_diverse"
        if key:
            strata[key].append(item)

    strata["same_high_boundary"].sort(key=same_boundary_key)
    strata["same_medium_boundary"].sort(key=same_boundary_key)
    strata["different_high_boundary"].sort(key=different_boundary_key)
    strata["different_medium_boundary"].sort(key=different_boundary_key)

    chosen: list[tuple[str, dict[str, Any]]] = []
    chosen_ids: set[str] = set()

    def take(name: str, rows: list[dict[str, Any]], n: int) -> None:
        rank = 0
        for item in rows:
            if len([1 for s, _ in chosen if s == name]) >= n:
                break
            pid = item["pair_id"]
            if pid in chosen_ids:
                continue
            chosen_ids.add(pid)
            rank += 1
            chosen.append((name, item))

    take("same_high_boundary", strata["same_high_boundary"], quotas["same_high_boundary"])
    take("same_medium_boundary", strata["same_medium_boundary"], quotas["same_medium_boundary"])
    take("different_high_boundary", strata["different_high_boundary"], quotas["different_high_boundary"])
    take("different_medium_boundary", strata["different_medium_boundary"], quotas["different_medium_boundary"])
    take("ambiguous_diverse", ambiguous_diverse(strata["ambiguous_diverse"], quotas["ambiguous_diverse"]), quotas["ambiguous_diverse"])

    # Backfill, if a requested stratum is too small, without exceeding max_total.
    if len(chosen) < args.max_total:
        remaining = [x for x in candidates if x["pair_id"] not in chosen_ids]
        # Prefer unresolved/medium cases first, then boundary SAME, then close DIFFERENT.
        def backfill_key(item: dict[str, Any]) -> tuple[Any, ...]:
            r = item["_review"]
            label_rank = {"AMBIGUOUS": 0, "SAME": 1, "DIFFERENT": 2}[r["label"]]
            conf_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[r["confidence"]]
            ft = item["feature_snapshot"]
            center = f(ft, "center_distance_abs_diff_m", float("inf"))
            return (label_rank, conf_rank, center, item["pair_id"])
        remaining.sort(key=backfill_key)
        for item in remaining:
            if len(chosen) >= args.max_total:
                break
            chosen_ids.add(item["pair_id"])
            chosen.append(("backfill_blind", item))

    # Deterministic neutral order for the human. Pair-id ordering does not reveal DS strata.
    human_items = []
    audit_rows = []
    for stratum, item in chosen:
        pid = item["pair_id"]
        r = item["_review"]
        human_items.append({
            "pair_id": pid,
            "features": item["feature_snapshot"],
            "selected_by": [],
        })
        audit_rows.append({
            "pair_id": pid,
            "selection_stratum": stratum,
            "deepseek_label": r.get("label"),
            "deepseek_confidence": r.get("confidence"),
            "deepseek_reason_codes": r.get("reason_codes", []),
            "deepseek_reason": r.get("reason"),
            "center_distance_abs_diff_m": item["feature_snapshot"].get("center_distance_abs_diff_m"),
            "overlap_over_union": item["feature_snapshot"].get("overlap_over_union"),
            "overlap_over_shorter": item["feature_snapshot"].get("overlap_over_shorter"),
            "channel_jaccard": item["feature_snapshot"].get("channel_jaccard"),
        })

    human_items.sort(key=lambda x: x["pair_id"])
    audit_rows.sort(key=lambda x: x["pair_id"])

    queue_payload = {
        "metadata": {
            "queue_schema_version": "1.0",
            "generator_version": VERSION,
            "created_at_utc": utc_now_iso(),
            "source_pool_sha256": sha256_file(pool_path),
            "source_review_sha256": sha256_file(reviews_path),
            "selected_pair_count": len(human_items),
            "excluded_existing_human_label_count": len(excluded_ids),
            "blindness_contract": {
                "deepseek_labels_in_queue": False,
                "deepseek_confidence_in_queue": False,
                "deepseek_reasoning_in_queue": False,
                "matcher_decisions_in_queue": False,
                "human_labels_in_queue": False,
            },
            "semantics": "Blind human calibration queue. DeepSeek was used only for hidden case selection; its decisions are stored separately in the audit file.",
        },
        "queue": human_items,
    }

    bad = contains_forbidden_key(queue_payload.get("queue"))
    if bad:
        raise RuntimeError(f"Blindness violation in human queue: forbidden key {bad}")

    audit_payload = {
        "metadata": {
            "audit_schema_version": "1.0",
            "generator_version": VERSION,
            "created_at_utc": utc_now_iso(),
            "source_pool": str(pool_path),
            "source_reviews": str(reviews_path),
            "source_human_label_files": [str(p) for p in label_paths],
            "candidate_count_after_exclusions": len(candidates),
            "selected_pair_count": len(audit_rows),
            "missing_review_count": len(missing_review),
            "invalid_review_count": len(invalid_review),
            "quotas": quotas,
            "warning": "Do not inspect this file before completing the blind human review if reviewer independence matters.",
        },
        "selections": audit_rows,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(queue_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 78)
    print(f"H2.2 - BLIND HUMAN REVIEW SELECTION v{VERSION}")
    print("=" * 78)
    print(f"Pool pairs:                  {len(pool_pairs):>6}")
    print(f"DeepSeek reviews:            {len(reviews_by_id):>6}")
    print(f"Existing human IDs excluded: {len(excluded_ids):>6}")
    print(f"Candidates after exclusion:  {len(candidates):>6}")
    print(f"Selected for human review:   {len(human_items):>6}")
    print(f"Missing reviews:             {len(missing_review):>6}")
    print(f"Invalid reviews:             {len(invalid_review):>6}")
    print("Human queue blindness: PASS")
    print(f"Human queue: {out_path}")
    print(f"Hidden audit: {audit_path}")
    print("IMPORTANT: complete human labels before opening the hidden audit file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
