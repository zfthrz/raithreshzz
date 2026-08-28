from __future__ import annotations

import argparse
from pathlib import Path

from authorized_episode_pair_matcher import (
    classify_features_authorized,
    load_pairs,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only audit of authorized H2 decisions on one feature batch."
    )
    parser.add_argument("features_json", type=Path)
    parser.add_argument(
        "--batches-root",
        type=Path,
        default=Path(__file__).resolve().parent / "calibration_batches",
    )
    args = parser.parse_args()

    pairs = load_pairs(args.features_json.resolve())
    decisions, metadata = classify_features_authorized(
        pairs,
        batches_root=args.batches_root,
    )

    print("Authorized H2 runtime audit (read-only)")
    print(f"Pairs: {len(decisions)}")
    print(f"Decision counts: {metadata['decision_counts']}")
    print(f"Authority scopes: {metadata['authority_scope_counts']}")
    print(f"Context sessions: {metadata['context_session_counts']}")
    print()

    inherited_matches = [
        row for row in decisions
        if row.get("decision") == "MATCH"
        and (row.get("authority") or {}).get("calibration_scope")
        == "COVERED_BY_TRACK_MATCH_BASELINE"
    ]
    inherited_rejects = [
        row for row in decisions
        if row.get("decision") == "REJECT"
        and (row.get("authority") or {}).get("calibration_scope")
        == "COVERED_BY_TRACK_MATCH_BASELINE"
    ]

    print(f"Inherited production MATCH: {len(inherited_matches)}")
    print(f"Inherited production REJECT: {len(inherited_rejects)}")
    if inherited_rejects:
        print("FAIL: inherited REJECT escaped the production gate.")
        return 2

    for row in inherited_matches[:10]:
        authority = row.get("authority") or {}
        print(
            f"  MATCH pair={row.get('pair_id')} "
            f"sessions={row.get('session_a')}/{row.get('session_b')} "
            f"rule={row.get('rule_id')} "
            f"baseline={','.join(authority.get('baseline_source_variants') or [])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
