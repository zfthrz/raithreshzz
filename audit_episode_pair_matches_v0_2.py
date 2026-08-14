from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

AUDIT_VERSION = "0.2"

DISTANCE_BINS = [
    "0-5.5m",
    ">5.5-20m",
    ">20-45m",
    ">45-100m",
    ">100-250m",
    ">250-<623.5m",
    ">=623.5m",
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x




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


def resolve_pair(decision: dict[str, Any], features: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    # v0.1 matcher always emitted pair_index. Prefer it because raw feature files do not
    # contain pair_id; pair_review_queue creates that identifier later.
    idx = safe_int(decision.get("pair_index"))
    if idx is not None and 0 <= idx < len(features):
        pair = features[idx]
        return stable_pair_id(pair), pair

    pid = decision.get("pair_id")
    if pid is not None:
        pair = by_id.get(str(pid))
        if pair is not None:
            return str(pid), pair

    return str(pid) if pid is not None else "UNRESOLVED", {}

def distance_bin(x: float | None) -> str:
    if x is None:
        return "missing"
    if x <= 5.5:
        return "0-5.5m"
    if x <= 20.0:
        return ">5.5-20m"
    if x <= 45.0:
        return ">20-45m"
    if x <= 100.0:
        return ">45-100m"
    if x <= 250.0:
        return ">100-250m"
    if x < 623.5:
        return ">250-<623.5m"
    return ">=623.5m"


def pct(n: int, d: int) -> str:
    return f"{(100.0*n/d):6.2f}%" if d else "  n/a "


def qstats(values: list[float]) -> str:
    if not values:
        return "n=0"
    s = sorted(values)
    return f"n={len(s)} min={s[0]:.1f} median={median(s):.1f} max={s[-1]:.1f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit H2 matcher decisions by spatial region and rule.")
    ap.add_argument("features_json")
    ap.add_argument("matches_json")
    ap.add_argument("--show-matches", action="store_true")
    args = ap.parse_args()

    features_path = Path(args.features_json).resolve()
    matches_path = Path(args.matches_json).resolve()
    features = load_json(features_path)
    matches = load_json(matches_path)

    if not isinstance(features, list):
        raise ValueError("features_json must be a JSON list")
    if not isinstance(matches, dict) or not isinstance(matches.get("decisions"), list):
        raise ValueError("matches_json must contain decisions[]")

    feature_rows = [p for p in features if isinstance(p, dict)]
    by_id = {}
    for p in feature_rows:
        pid = p.get("pair_id") or stable_pair_id(p)
        by_id[str(pid)] = p
    decisions = matches["decisions"]

    total = len(decisions)
    outcome = Counter(str(d.get("decision")) for d in decisions)
    rules = Counter(str(d.get("rule_id")) for d in decisions)

    print("=" * 78)
    print(f"RACE ENGINEER - MATCHER AUDIT v{AUDIT_VERSION}")
    print("=" * 78)
    print(f"Pairs: {total}")
    for name in ("MATCH", "AMBIGUOUS", "REJECT"):
        print(f"{name:10s}: {outcome[name]:5d}  {pct(outcome[name], total)}")

    print("\nRULE COUNTS")
    for rule, n in rules.most_common():
        print(f"  {rule:42s} {n:5d}  {pct(n,total)}")

    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    distance_values: dict[str, list[float]] = defaultdict(list)
    overlap_values: dict[str, list[float]] = defaultdict(list)

    match_rows = []
    unresolved_rows = []
    for d in decisions:
        pid, p = resolve_pair(d, feature_rows, by_id)
        center = f(p.get("center_distance_abs_diff_m"))
        overlap = f(p.get("overlap_over_union"))
        decision = str(d.get("decision"))
        b = distance_bin(center)
        matrix[b][decision] += 1
        if center is not None:
            distance_values[decision].append(center)
        if overlap is not None:
            overlap_values[decision].append(overlap)
        row = (center if center is not None else float("inf"), pid, p, d)
        if decision == "MATCH":
            match_rows.append(row)
        if decision == "AMBIGUOUS":
            unresolved_rows.append(row)

    resolved_n = sum(sum(c.values()) for b, c in matrix.items() if b != "missing")
    missing_n = sum(matrix.get("missing", Counter()).values())
    print(f"\nFEATURE JOIN: resolved={resolved_n} missing={missing_n}")

    print("\nDECISION BY CENTER-DISTANCE BIN")
    print(f"{'bin':15s} {'total':>6s} {'MATCH':>7s} {'AMBIG':>7s} {'REJECT':>7s}")
    bin_order = DISTANCE_BINS + ["missing", "other"]
    for b in bin_order:
        c = matrix.get(b, Counter())
        n = sum(c.values())
        if not n:
            continue
        print(f"{b:15s} {n:6d} {c['MATCH']:7d} {c['AMBIGUOUS']:7d} {c['REJECT']:7d}")

    print("\nCENTER DISTANCE BY DECISION")
    for name in ("MATCH", "AMBIGUOUS", "REJECT"):
        print(f"  {name:10s}: {qstats(distance_values[name])}")

    print("\nOVERLAP/UNION BY DECISION")
    for name in ("MATCH", "AMBIGUOUS", "REJECT"):
        vals = overlap_values[name]
        if vals:
            print(f"  {name:10s}: n={len(vals)} min={min(vals):.3f} median={median(vals):.3f} max={max(vals):.3f}")
        else:
            print(f"  {name:10s}: n=0")

    if unresolved_rows:
        unresolved_rows.sort(key=lambda r: r[0])
        print("\nAMBIGUOUS - 12 CLOSEST")
        for center, pid, p, d in unresolved_rows[:12]:
            ov = f(p.get("overlap_over_union"))
            ovs = f(p.get("overlap_over_shorter"))
            print(
                f"  {pid} center={center:.1f}m overlap_union={ov if ov is not None else 'NA'} "
                f"overlap_shorter={ovs if ovs is not None else 'NA'} rule={d.get('rule_id')}"
            )

    if args.show_matches and match_rows:
        match_rows.sort(key=lambda r: r[0])
        print("\nALL MATCH PAIRS")
        for center, pid, p, d in match_rows:
            print(
                f"  {pid} sessions={p.get('session_a')}->{p.get('session_b')} "
                f"episodes={p.get('episode_id_a')}->{p.get('episode_id_b')} "
                f"center={center:.1f}m overlap_union={f(p.get('overlap_over_union'))} "
                f"overlap_shorter={f(p.get('overlap_over_shorter'))} channels={p.get('shared_channels')}"
            )

    print("\nInterpretation: do not tune thresholds from this audit alone; use it to choose the next human-review boundary sample.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
