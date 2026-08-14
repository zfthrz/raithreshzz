from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Audita distribución de patterns H3.")
    ap.add_argument("patterns_json")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    doc = json.loads(Path(args.patterns_json).read_text(encoding="utf-8"))
    patterns = doc.get("patterns")
    if not isinstance(patterns, list):
        raise ValueError("patterns_json inválido")

    print("=" * 86)
    print("RACE ENGINEER - H3 PERSISTENT PATTERN AUDIT v0.1")
    print("=" * 86)
    print(f"Patterns/classes: {len(patterns)}")
    print(f"Episodes:         {(doc.get('summary') or {}).get('episode_count')}")
    print()
    counts = Counter(p.get("state") for p in patterns)
    print("STATE COUNTS")
    for state, count in sorted(counts.items()):
        print(f"  {state:28s} {count:6d}")

    repeats = [
        p for p in patterns
        if p.get("state") in {"persistent_pattern", "cross_session_repeat", "conflict_review_required"}
    ]
    repeats.sort(
        key=lambda p: (
            p.get("state") == "conflict_review_required",
            p.get("independent_session_count", 0),
            p.get("observation_count", 0),
        ),
        reverse=True,
    )

    print()
    print(f"TOP {min(args.limit, len(repeats))} RECURRENT CLASSES")
    print("state                     sess  obs  center   spread  common_channels              M/A/R")
    for p in repeats[: args.limit]:
        sp = p.get("spatial_summary") or {}
        ch = p.get("channel_summary") or {}
        eq = p.get("equivalence_evidence") or {}
        dc = eq.get("decision_counts") or {}
        center = sp.get("center_median_m")
        spread = sp.get("center_spread_m")
        print(
            f"{p.get('state','?'):25s} "
            f"{p.get('independent_session_count',0):4d} "
            f"{p.get('observation_count',0):4d} "
            f"{center if center is not None else float('nan'):7.1f} "
            f"{spread if spread is not None else float('nan'):7.1f} "
            f"{','.join(ch.get('common_action_channels') or [])[:28]:28s} "
            f"{dc.get('MATCH',0)}/{dc.get('AMBIGUOUS',0)}/{dc.get('REJECT',0)}"
        )

    conflicts = [p for p in patterns if p.get("state") == "conflict_review_required"]
    print()
    print(f"CONFLICTS: {len(conflicts)}")
    for p in conflicts[: args.limit]:
        print(
            f"  {p.get('pattern_id')} sessions={p.get('independent_session_count')} "
            f"obs={p.get('observation_count')} reasons={(p.get('uncertainty') or {}).get('conflict_reasons')}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
