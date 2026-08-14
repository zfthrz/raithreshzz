from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POOL_SCHEMA_VERSION = "1.0"

FEATURE_KEYS = [
    "track", "session_a", "session_b", "episode_pk_a", "episode_pk_b",
    "episode_id_a", "episode_id_b", "start_distance_a_m", "end_distance_a_m",
    "center_distance_a_m", "start_distance_b_m", "end_distance_b_m",
    "center_distance_b_m", "center_distance_abs_diff_m", "overlap_m",
    "overlap_over_union", "overlap_over_shorter", "channel_jaccard",
    "channels_a", "channels_b", "shared_channels", "channels_only_a",
    "channels_only_b", "action_time_loss_a_s", "action_time_loss_b_s",
    "action_time_loss_similarity", "per_channel_metrics",
]


def safe_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def stable_pair_id(pair: dict[str, Any]) -> str:
    track = str(pair.get("track") or "")
    side_a = (safe_int(pair.get("session_a")), safe_int(pair.get("episode_pk_a")))
    side_b = (safe_int(pair.get("session_b")), safe_int(pair.get("episode_pk_b")))
    payload = {"track": track, "sides": sorted([side_a, side_b])}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def compact(pair: dict[str, Any]) -> dict[str, Any]:
    return {key: pair.get(key) for key in FEATURE_KEYS}


def load_features(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("episode_pair_features debe ser una lista JSON.")
    return [x for x in raw if isinstance(x, dict)]


def load_decisions(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        rows = raw.get("decisions")
        if rows is None:
            rows = raw.get("matches")
    else:
        rows = raw
    if not isinstance(rows, list):
        raise ValueError("No se encontró una lista de decisiones en episode_pair_matches.")
    return [x for x in rows if isinstance(x, dict)]


def main() -> int:
    ap = argparse.ArgumentParser(description="Crea un pool ciego de los pares AMBIGUOUS del matcher para pre-review DeepSeek.")
    ap.add_argument("features_json")
    ap.add_argument("matches_json")
    ap.add_argument("--output", default="deepseek_ambiguous_pool.json")
    args = ap.parse_args()

    features_path = Path(args.features_json).resolve()
    matches_path = Path(args.matches_json).resolve()
    out_path = Path(args.output).resolve()

    features = load_features(features_path)
    decisions = load_decisions(matches_path)
    by_id = {stable_pair_id(pair): pair for pair in features}

    pool = []
    unresolved = []
    seen = set()
    for row in decisions:
        if row.get("decision") != "AMBIGUOUS":
            continue
        idx = safe_int(row.get("pair_index"))
        pair = features[idx] if idx is not None and 0 <= idx < len(features) else None
        pid = row.get("pair_id")
        if pair is None and isinstance(pid, str):
            pair = by_id.get(pid)
        if pair is None:
            unresolved.append(pid)
            continue
        canonical_pid = stable_pair_id(pair)
        if canonical_pid in seen:
            continue
        seen.add(canonical_pid)
        pool.append({
            "pair_id": canonical_pid,
            "feature_snapshot": compact(pair),
        })

    pool.sort(key=lambda x: x["pair_id"])
    payload = {
        "metadata": {
            "schema_version": POOL_SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_features": str(features_path),
            "source_matches": str(matches_path),
            "source_feature_count": len(features),
            "source_decision_count": len(decisions),
            "ambiguous_pair_count": len(pool),
            "unresolved_pair_count": len(unresolved),
            "blindness_contract": {
                "human_labels_in_queue": False,
                "matcher_decisions_in_queue": False,
                "matcher_thresholds_in_queue": False,
                "matcher_rules_in_queue": False,
            },
            "policy": "DeepSeek pre-review only. No automatic human ground-truth assignment.",
        },
        "pairs": pool,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 78)
    print("H2.2 - DEEPSEEK AMBIGUOUS POOL v1.0")
    print("=" * 78)
    print(f"Features:          {len(features)}")
    print(f"Decisions:         {len(decisions)}")
    print(f"AMBIGUOUS selected:{len(pool):>6}")
    print(f"Unresolved joins:  {len(unresolved):>6}")
    print(f"Output: {out_path}")
    if unresolved:
        print("ERROR: hubo decisiones AMBIGUOUS que no pudieron resolverse contra features.")
        return 2
    print("Blindness: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
