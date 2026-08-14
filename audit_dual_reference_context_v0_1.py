from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Audita H5.1 dual-reference context.")
    ap.add_argument("dual_reference_json")
    args = ap.parse_args()

    doc = json.loads(Path(args.dual_reference_json).read_text(encoding="utf-8"))
    ctx = doc.get("context") or {}
    target = doc.get("target_session") or {}
    session = doc.get("session_reference") or {}
    hist = doc.get("historical_reference")
    progress = doc.get("long_term_progress") or {}
    authority = doc.get("coaching_authority") or {}
    next_stage = doc.get("next_stage") or {}

    print("=" * 96)
    print("RACE ENGINEER - H5.1 DUAL REFERENCE AUDIT v0.1")
    print("=" * 96)
    print(f"Status:  {doc.get('status')}")
    print(
        f"Context: {ctx.get('track')} | {ctx.get('track_layout')} | "
        f"{ctx.get('vehicle_variant')} | {ctx.get('car_name_raw')}"
    )
    print(
        f"Target:  session={target.get('session_id')} type={target.get('session_type')} "
        f"weather={target.get('weather_conditions')}/{target.get('weather_class')}"
    )
    print(
        f"Session reference: lap={session.get('lap')} duration={session.get('duration_s')} "
        f"role={session.get('role')}"
    )
    if hist is None:
        print("Historical reference: NONE")
    else:
        print(
            f"Historical reference: session={hist.get('session_id')} lap={hist.get('lap')} "
            f"duration={hist.get('duration_s')} role={hist.get('role')}"
        )
        print(
            f"Progress: current-historical={progress.get('current_minus_historical_s')} "
            f"status={progress.get('status')}"
        )
    print()
    print("COACHING AUTHORITY")
    for k, v in authority.items():
        print(f"  {k}: {v}")
    print()
    print("NEXT STAGE")
    for k, v in next_stage.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
