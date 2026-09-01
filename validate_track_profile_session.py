#!/usr/bin/env python3
"""Read-only independent-session validation for an LMU track profile."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from detect_track_turns import compute_curvature, load_points, local_peak_indices, resample


VERSION = "0.1"
STEP_M = 2.0
HEADING_WINDOW_M = 20.0
SMOOTH_WINDOW_M = 14.0
APEX_PASS_TOLERANCE_M = 35.0
APEX_WARNING_TOLERANCE_M = 70.0


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return payload


def _session_key(summary: dict[str, Any], csv_path: Path) -> str:
    source = str(summary.get("source_file") or "").strip()
    if source:
        return Path(source).stem
    suffix = "_track_gps"
    return csv_path.stem[:-len(suffix)] if csv_path.stem.endswith(suffix) else csv_path.stem


def _summary_path(csv_path: Path) -> Path:
    suffix = "_track_gps"
    stem = csv_path.stem
    base = stem[:-len(suffix)] if stem.endswith(suffix) else stem
    return csv_path.with_name(f"{base}_track_gps_summary.json")


def _turn_result(
    turn: dict[str, Any],
    samples: list[dict[str, float]],
    signed: list[float],
    strength: list[float],
    peak_indices: list[int],
) -> dict[str, Any]:
    expected_direction = str(turn.get("direction") or "").casefold()
    expected_sign = 1 if expected_direction == "left" else -1
    start_m = float(turn["start_m"])
    end_m = float(turn["end_m"])
    expected_apex_m = float(turn["apex_m"])
    candidates = [
        index
        for index in peak_indices
        if start_m <= float(samples[index]["d"]) <= end_m
        and signed[index] * expected_sign > 0.0
    ]
    if not candidates:
        return {
            "turn": int(turn["turn"]),
            "name": str(turn.get("name") or f"Turn {turn['turn']}"),
            "direction": expected_direction,
            "expected_apex_m": expected_apex_m,
            "observed_apex_m": None,
            "offset_m": None,
            "observed_signed_curvature_rad_per_m": None,
            "status": "FAIL",
            "reason": "no_same_direction_local_extremum_inside_profile_interval",
        }

    selected = min(
        candidates,
        key=lambda index: (
            abs(float(samples[index]["d"]) - expected_apex_m),
            -float(strength[index]),
        ),
    )
    observed_apex_m = float(samples[selected]["d"])
    offset_m = observed_apex_m - expected_apex_m
    absolute_offset = abs(offset_m)
    if absolute_offset <= APEX_PASS_TOLERANCE_M:
        status = "PASS"
    elif absolute_offset <= APEX_WARNING_TOLERANCE_M:
        status = "WARNING"
    else:
        status = "FAIL"

    return {
        "turn": int(turn["turn"]),
        "name": str(turn.get("name") or f"Turn {turn['turn']}"),
        "direction": expected_direction,
        "expected_apex_m": round(expected_apex_m, 3),
        "observed_apex_m": round(observed_apex_m, 3),
        "offset_m": round(offset_m, 3),
        "observed_signed_curvature_rad_per_m": signed[selected],
        "status": status,
    }


def build_report(
    profile: dict[str, Any],
    summary: dict[str, Any],
    csv_path: Path,
) -> dict[str, Any]:
    track = str(summary.get("track_name") or "").strip()
    layout = str(summary.get("track_layout") or "").strip()
    expected_track = str(profile.get("track") or "").strip()
    expected_layout = str(profile.get("layout") or "").strip()
    session = _session_key(summary, csv_path)
    source_session = str(
        (profile.get("calibration") or {}).get("source_session") or ""
    ).strip()

    contract_errors: list[str] = []
    if track != expected_track:
        contract_errors.append(f"track mismatch: {track!r} != {expected_track!r}")
    if layout != expected_layout:
        contract_errors.append(f"layout mismatch: {layout!r} != {expected_layout!r}")
    if session == source_session:
        contract_errors.append("candidate session is the profile source session")
    if not isinstance(profile.get("turns"), list) or not profile["turns"]:
        contract_errors.append("profile has no turns")

    turn_results: list[dict[str, Any]] = []
    if not contract_errors:
        samples = resample(load_points(csv_path), STEP_M)
        _headings, signed, strength = compute_curvature(
            samples, STEP_M, HEADING_WINDOW_M, SMOOTH_WINDOW_M
        )
        peaks = local_peak_indices(strength)
        turn_results = [
            _turn_result(turn, samples, signed, strength, peaks)
            for turn in profile["turns"]
        ]

    pass_count = sum(row["status"] == "PASS" for row in turn_results)
    warning_count = sum(row["status"] == "WARNING" for row in turn_results)
    failure_count = sum(row["status"] == "FAIL" for row in turn_results)
    offsets = [
        abs(float(row["offset_m"]))
        for row in turn_results
        if row.get("offset_m") is not None
    ]
    ready = not contract_errors and bool(turn_results) and failure_count == 0
    overall = (
        "BLOCKED_CONTRACT"
        if contract_errors
        else "PASS_WITH_WARNINGS"
        if ready and warning_count
        else "PASS"
        if ready
        else "FAIL"
    )

    return {
        "version": VERSION,
        "mode": "AUDIT_READ_ONLY",
        "profile_mutated": False,
        "automatic_promotion": False,
        "profile_id": profile.get("profile_id"),
        "profile_status": profile.get("status"),
        "profile_track": expected_track,
        "profile_layout": expected_layout,
        "independent_session": session,
        "selected_lap": summary.get("selected_lap"),
        "method": (
            "same-direction nearest local extremum inside each calibrated interval; "
            "2 m resampling, 20 m heading window, 14 m smoothing"
        ),
        "apex_pass_tolerance_m": APEX_PASS_TOLERANCE_M,
        "apex_warning_tolerance_m": APEX_WARNING_TOLERANCE_M,
        "pass_count": pass_count,
        "warning_count": warning_count,
        "failure_count": failure_count,
        "median_abs_offset_m": round(statistics.median(offsets), 3) if offsets else None,
        "max_abs_offset_m": round(max(offsets), 3) if offsets else None,
        "overall_status": overall,
        "promotion_readiness": (
            "READY_FOR_EXPLICIT_PROMOTION" if ready else "NOT_READY"
        ),
        "contract_errors": contract_errors,
        "turn_results": turn_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("gps_csv", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--output", default="-")
    args = parser.parse_args(argv)

    try:
        summary_path = args.summary or _summary_path(args.gps_csv)
        report = build_report(
            _load_object(args.profile), _load_object(summary_path), args.gps_csv
        )
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output == "-":
            sys.stdout.write(payload)
        else:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0 if report["promotion_readiness"] == "READY_FOR_EXPLICIT_PROMOTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
