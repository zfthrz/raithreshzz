from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Audita candidates H4 historical reference v0.1.")
    ap.add_argument("selection_json")
    ap.add_argument("--show-rejected", type=int, default=20)
    args = ap.parse_args()

    doc = json.loads(Path(args.selection_json).read_text(encoding="utf-8"))
    target = doc.get("target_session") or {}
    candidates = doc.get("candidates") or []
    selected = doc.get("selected_historical_reference")

    print("=" * 100)
    print("RACE ENGINEER - H4 HISTORICAL REFERENCE AUDIT v0.1")
    print("=" * 100)
    print(f"Target: session={target.get('session_id')} ref={target.get('session_reference')}")
    print(f"Context: {target.get('track')} | {target.get('track_layout')} | {target.get('vehicle_variant')} | {target.get('car_name_raw')}")
    print(f"Weather: {target.get('weather_conditions')}")
    print(f"Status: {doc.get('selection_status')} / {doc.get('selection_scope')}")
    if selected:
        print(f"Selected: session={selected.get('session_id')} lap={selected.get('lap')} duration={selected.get('duration_s')} delta={selected.get('historical_minus_session_reference_s')}")

    eligible = [c for c in candidates if c.get("eligibility") == "ELIGIBLE"]
    rejected = [c for c in candidates if c.get("eligibility") == "REJECTED"]
    print()
    print("ELIGIBLE CANDIDATES")
    print("session  lap   duration     delta_target  type        same_setup  timestamp")
    for c in eligible:
        obs = c.get("compatibility_observations") or {}
        print(
            f"{str(c.get('session_id')):7s} {str(c.get('reference_lap')):5s} "
            f"{str(c.get('reference_lap_duration_s')):12s} {str(c.get('candidate_minus_target_reference_s')):13s} "
            f"{str(c.get('session_type'))[:10]:10s} {str(obs.get('same_setup_sha256')):10s} {c.get('timestamp_utc')}"
        )

    reasons = Counter()
    for c in rejected:
        reasons.update(c.get("rejection_reasons") or [])
    print()
    print("REJECTION REASON COUNTS")
    for reason, count in reasons.most_common():
        print(f"  {reason:42s} {count:5d}")

    if rejected and args.show_rejected > 0:
        print()
        print(f"FIRST {min(args.show_rejected, len(rejected))} REJECTED")
        for c in rejected[: args.show_rejected]:
            print(f"  session={c.get('session_id')} timestamp={c.get('timestamp_utc')} reasons={','.join(c.get('rejection_reasons') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
