from __future__ import annotations

import argparse
import json
from pathlib import Path

from track_readiness import build_track_readiness


def _print_table(payload: dict) -> None:
    summary = payload["summary"]
    print(
        f"Tracks: {summary['tracks']}  "
        f"Contexts: {summary['contexts']}  "
        f"Resolved missing layout: {summary.get('resolved_missing_layout_from_profile', 0)}  "
        f"Unresolved sessions: {summary.get('unresolved_sessions', 0)}  "
        f"Read-only: {payload.get('read_only') is True}"
    )

    print("Status counts:")
    for status, count in (summary.get("status_counts") or {}).items():
        print(f"  {status}: {count}")

    print("\nTrack summary:")
    track_headers = (
        "Track",
        "Profile",
        "Contexts",
        "Satisfied",
        "Pending",
        "Unresolved",
    )
    track_body = []
    for track in payload.get("tracks") or []:
        track_body.append(
            (
                track["track"],
                track["profile_status"],
                str(track["context_count"]),
                str(track["satisfied_contexts"]),
                str(track["pending_contexts"]),
                str(track["unresolved_sessions"]),
            )
        )

    track_widths = [len(value) for value in track_headers]
    for item in track_body:
        for index, value in enumerate(item):
            track_widths[index] = min(42, max(track_widths[index], len(str(value))))

    def render(item: tuple[str, ...], widths: list[int]) -> str:
        cells = []
        for index, value in enumerate(item):
            text = str(value)
            if len(text) > widths[index]:
                text = text[: max(1, widths[index] - 1)] + "…"
            cells.append(text.ljust(widths[index]))
        return "  ".join(cells)

    print(render(track_headers, track_widths))
    print(render(tuple("-" * width for width in track_widths), track_widths))
    for item in track_body:
        print(render(item, track_widths))

    print("\nContext detail:")
    headers = (
        "Track",
        "Layout",
        "Variant",
        "Sessions",
        "Layout source",
        "Labels",
        "Profile",
        "Baseline",
        "H2",
        "Historical",
        "Status",
        "Next",
    )
    body = []
    for row in payload.get("rows") or []:
        resolution = row.get("layout_resolution_counts") or {}
        resolution_text = ",".join(
            f"{key}:{value}" for key, value in sorted(resolution.items())
        ) or "—"
        body.append(
            (
                row["track"],
                row["track_layout"],
                row["vehicle_variant"],
                str(row["sessions"]),
                resolution_text,
                f"{row['labeled_pairs']}/{row['queue_pairs']}",
                row["profile_status"],
                (
                    row.get("baseline_status", "NO_TRACK_BASELINE")
                    + (
                        "["
                        + ",".join(row.get("baseline_source_variants") or [])
                        + "]"
                        if row.get("baseline_source_variants")
                        else ""
                    )
                    + (
                        "/REJECT:VARIANT"
                        if row.get("baseline_status") == "TRACK_MATCH_BASELINE_SHADOW"
                        else ""
                    )
                ),
                row["matcher_status"],
                row["historical_status"],
                row["overall_status"],
                row["next_action"]["code"],
            )
        )

    widths = [len(value) for value in headers]
    for item in body:
        for index, value in enumerate(item):
            widths[index] = min(38, max(widths[index], len(str(value))))

    print(render(headers, widths))
    print(render(tuple("-" * width for width in widths), widths))
    for item in body:
        print(render(item, widths))

    unresolved = payload.get("unresolved_sessions") or []
    if unresolved:
        print("\nUnresolved runtime sessions:")
        for item in unresolved:
            print(
                f"  - {item['track']} / {item['vehicle_variant']} / "
                f"{item['session_key']} -> {item['reason']}"
            )

    identity_warnings = payload.get("identity_warnings") or []
    if identity_warnings:
        print("\nIdentity warnings:")
        for warning in identity_warnings:
            layouts = " | ".join(warning.get("layouts") or [])
            print(
                f"  - {warning['code']}: {warning.get('track')} / "
                f"{warning.get('vehicle_variant')} -> {layouts}"
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
