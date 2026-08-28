from __future__ import annotations

import argparse
import json
from pathlib import Path

from track_readiness import build_track_readiness


def _print_table(payload: dict) -> None:
    rows = payload.get("rows") or []
    print(
        f"Tracks: {payload['summary']['tracks']}  "
        f"Contexts: {payload['summary']['contexts']}  "
        f"Read-only: {payload.get('read_only') is True}"
    )
    print("Status counts:")
    for status, count in (payload["summary"].get("status_counts") or {}).items():
        print(f"  {status}: {count}")
    print()

    headers = (
        "Track",
        "Variant",
        "Sessions",
        "Labels",
        "Profile",
        "H2",
        "Historical",
        "Status",
        "Next",
    )
    body = []
    for row in rows:
        body.append(
            (
                row["track"],
                row["vehicle_variant"],
                str(row["sessions"]),
                f"{row['labeled_pairs']}/{row['queue_pairs']}",
                row["profile_status"],
                row["matcher_status"],
                row["historical_status"],
                row["overall_status"],
                row["next_action"]["code"],
            )
        )

    widths = [len(value) for value in headers]
    for item in body:
        for index, value in enumerate(item):
            widths[index] = min(42, max(widths[index], len(str(value))))

    def render(item: tuple[str, ...]) -> str:
        cells = []
        for index, value in enumerate(item):
            text = str(value)
            if len(text) > widths[index]:
                text = text[: max(1, widths[index] - 1)] + "…"
            cells.append(text.ljust(widths[index]))
        return "  ".join(cells)

    print(render(headers))
    print(render(tuple("-" * width for width in widths)))
    for item in body:
        print(render(item))

    track_only = payload.get("track_only") or []
    if track_only:
        print("\nProfiles without discovered vehicle context:")
        for row in track_only:
            print(
                f"  {row['track']} / {row['track_layout']}: "
                f"{row['profile_status']} -> {row['next_action']['code']}"
            )

    errors = payload.get("errors") or []
    if errors:
        print("\nRead-only discovery warnings:")
        for error in errors:
            print(f"  - {error}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only track/context readiness audit"
    )
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    payload = build_track_readiness(project_root=args.project_root)
    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_table(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
