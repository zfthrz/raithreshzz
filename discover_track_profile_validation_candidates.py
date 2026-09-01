#!/usr/bin/env python3
"""Discover independent LMU sessions for provisional track-profile validation.

Read-only: this command never writes telemetry, profiles, History, or pipeline state.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import duckdb

import extract_lmu_track_gps as gps


VERSION = "0.1"
PROVISIONAL_STATUS = "VALIDATED_SINGLE_SESSION"
MIN_PROFILE_DISTANCE_COVERAGE = 0.90
DEFAULT_TELEMETRY_DIR = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry"
)
PROJECT_ROOT = Path(__file__).resolve().parent


def _load_profile(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"profile root is not an object: {path}")
    return payload


def _probe_session(path: Path, target_hz: float = 10.0) -> dict[str, Any]:
    """Read metadata and apply the extractor's existing lap selection unchanged."""
    connection = duckdb.connect(str(path), read_only=True)
    try:
        tables = gps.table_names(connection)
        metadata = gps.read_metadata(connection)
        missing = [name for name in gps.REQUIRED_GPS_TABLES if name not in tables]
        if missing:
            return {"metadata": metadata, "missing_channels": missing}

        channels = {
            name: gps.read_value_table(connection, name)
            for name in ("GPS Time", "GPS Latitude", "GPS Longitude", "Lap Dist")
            if name in tables
        }
        master_times, _time_source = gps.build_master_times(channels, target_hz)
        gps_time_reference = [
            float(value)
            for value in channels.get("GPS Time", {}).get("values", [])
            if gps.finite(value)
        ] or master_times
        latitude = gps.align_channel(
            channels.get("GPS Latitude"), master_times, gps_time_reference
        )
        longitude = gps.align_channel(
            channels.get("GPS Longitude"), master_times, gps_time_reference
        )
        lap_distance = gps.align_channel(
            channels.get("Lap Dist"), master_times, gps_time_reference
        )
        boundaries = gps.read_lap_event_times(connection, tables)
        laps = (
            gps.assign_laps_from_boundaries(master_times, boundaries)
            if boundaries
            else gps.detect_laps_from_distance(lap_distance)
        )
        groups = gps.group_indices_by_lap(laps)
        for indices in groups.values():
            gps.repair_lap_distance_boundary_sample(indices, lap_distance)
        metrics = {
            lap: gps.lap_metrics(
                indices, latitude, longitude, lap_distance, master_times
            )
            for lap, indices in groups.items()
        }
        if not metrics:
            return {"metadata": metadata, "missing_channels": [], "error": "no_laps"}
        selected_lap = gps.choose_default_lap(metrics)
        selected = metrics[selected_lap]
        return {
            "metadata": metadata,
            "missing_channels": [],
            "selected_lap": selected_lap,
            "selected_lap_metrics": selected,
            "usable_gps_lap": (
                selected["gps_coverage"] >= 0.70
                and selected["duration_s"] >= 30.0
                and (selected["lap_dist_max_m"] or 0.0) >= 1000.0
            ),
        }
    finally:
        connection.close()


def _probe_metadata(path: Path) -> dict[str, Any]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        return gps.read_metadata(connection)
    finally:
        connection.close()


def _powershell(parts: list[str]) -> str:
    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    return " ".join(quote(part) if any(char.isspace() for char in part) else part for part in parts)


def discover_candidates(
    profiles_dir: Path,
    telemetry_dir: Path,
    *,
    settle_seconds: int,
    now_s: float | None = None,
    probe: Callable[[Path], dict[str, Any]] = _probe_session,
    metadata_probe: Callable[[Path], dict[str, Any]] = _probe_metadata,
) -> dict[str, Any]:
    now_value = time.time() if now_s is None else now_s
    profiles: list[tuple[Path, dict[str, Any]]] = []
    for profile_path in sorted(profiles_dir.glob("*_profile_v0_1.json")):
        profile = _load_profile(profile_path)
        if profile.get("status") == PROVISIONAL_STATUS:
            profiles.append((profile_path, profile))

    identities = {
        (str(profile.get("track") or ""), str(profile.get("layout") or ""))
        for _path, profile in profiles
    }
    source_sessions = {
        str((profile.get("calibration") or {}).get("source_session") or "")
        for _path, profile in profiles
    }
    sessions: list[tuple[Path, dict[str, Any], float]] = []
    probe_errors: list[dict[str, str]] = []
    for database in sorted(telemetry_dir.glob("*.duckdb")):
        age_s = max(0.0, now_value - database.stat().st_mtime)
        try:
            metadata = metadata_probe(database)
            identity = (
                str(metadata.get("TrackName") or ""),
                str(metadata.get("TrackLayout") or ""),
            )
            if identity not in identities or database.stem in source_sessions:
                continue
            session = probe(database)
            session["metadata"] = metadata
            sessions.append((database, session, age_s))
        except Exception as exc:  # one unreadable/live DB must not hide other candidates
            probe_errors.append(
                {"path": str(database), "error": f"{type(exc).__name__}: {exc}"}
            )

    profile_rows: list[dict[str, Any]] = []
    for profile_path, profile in profiles:
        source_session = str((profile.get("calibration") or {}).get("source_session") or "")
        matches: list[dict[str, Any]] = []
        for database, session, age_s in sessions:
            metadata = session.get("metadata") or {}
            if metadata.get("TrackName") != profile.get("track"):
                continue
            if metadata.get("TrackLayout") != profile.get("layout"):
                continue
            if database.stem == source_session:
                continue
            stable = age_s >= settle_seconds
            metrics = session.get("selected_lap_metrics") or {}
            profile_lap_length = float(profile.get("lap_length_m") or 0.0)
            lap_distance_coverage = (
                float(metrics.get("lap_dist_span_m") or 0.0) / profile_lap_length
                if profile_lap_length > 0.0 else 0.0
            )
            gps_path_coverage = (
                float(metrics.get("gps_path_m") or 0.0) / profile_lap_length
                if profile_lap_length > 0.0 else 0.0
            )
            usable = (
                bool(session.get("usable_gps_lap"))
                and lap_distance_coverage >= MIN_PROFILE_DISTANCE_COVERAGE
                and gps_path_coverage >= MIN_PROFILE_DISTANCE_COVERAGE
            )
            status = (
                "READY_FOR_GPS_EXPORT"
                if stable and usable and not session.get("missing_channels")
                else "WAITING_STABILITY"
                if not stable
                else "NOT_USABLE_FOR_GPS_EXPORT"
            )
            output_dir = PROJECT_ROOT / "track_exports" / f"{profile['profile_id']}_validation"
            csv_path = output_dir / f"{database.stem}_track_gps.csv"
            extract_parts = [
                "python", "extract_lmu_track_gps.py", str(database),
                "--output-dir", str(output_dir),
            ]
            validate_parts = [
                "python", "validate_track_profile_session.py", str(profile_path),
                str(csv_path),
            ]
            matches.append(
                {
                    "status": status,
                    "telemetry": str(database),
                    "age_seconds": round(age_s, 1),
                    "selected_lap": session.get("selected_lap"),
                    "selected_lap_metrics": metrics,
                    "profile_lap_length_m": profile_lap_length,
                    "lap_distance_coverage": round(lap_distance_coverage, 4),
                    "gps_path_coverage": round(gps_path_coverage, 4),
                    "missing_channels": session.get("missing_channels", []),
                    "extract_command": _powershell(extract_parts),
                    "validate_command": _powershell(validate_parts),
                }
            )
        matches.sort(key=lambda row: Path(row["telemetry"]).stat().st_mtime, reverse=True)
        profile_rows.append(
            {
                "profile_id": profile.get("profile_id"),
                "profile": str(profile_path),
                "track": profile.get("track"),
                "layout": profile.get("layout"),
                "source_session_excluded": source_session,
                "candidate_count": len(matches),
                "ready_count": sum(row["status"] == "READY_FOR_GPS_EXPORT" for row in matches),
                "candidates": matches,
            }
        )

    return {
        "version": VERSION,
        "mode": "AUDIT_READ_ONLY",
        "profiles_mutated": False,
        "automatic_export": False,
        "automatic_promotion": False,
        "telemetry_dir": str(telemetry_dir),
        "settle_seconds": settle_seconds,
        "minimum_profile_distance_coverage": MIN_PROFILE_DISTANCE_COVERAGE,
        "provisional_profile_count": len(profile_rows),
        "compatible_session_probe_count": len(sessions),
        "ready_profile_count": sum(row["ready_count"] > 0 for row in profile_rows),
        "profiles": profile_rows,
        "probe_errors": probe_errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telemetry-dir", type=Path, default=DEFAULT_TELEMETRY_DIR)
    parser.add_argument("--profiles-dir", type=Path, default=PROJECT_ROOT / "track_profiles")
    parser.add_argument("--settle-seconds", type=int, default=600)
    parser.add_argument("--output", default="-")
    args = parser.parse_args(argv)
    if args.settle_seconds < 0:
        parser.error("--settle-seconds must be non-negative")

    try:
        report = discover_candidates(
            args.profiles_dir.resolve(), args.telemetry_dir.resolve(),
            settle_seconds=args.settle_seconds,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
