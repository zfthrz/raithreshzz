from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cross_session_context import resolve_cross_session_pair
from cross_session_zone_localization import (
    LOCALIZATION_VERSION,
    build_trend_zone_summaries,
    find_validated_track_profile,
    localize_trend_zones,
    profile_boundaries,
    unlocalized_zone_summaries,
)
from delta_comparison import DeltaComparison
from laps import LapAnalyzer
from sector_analysis import SectorAnalysis
from telemetry import Telemetry


CROSS_SESSION_VERSION = "0.2"
SCHEMA_VERSION = "1.1"
TEMPORAL_TOLERANCE_S = 1e-6


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def build_comparison(
    dual_reference_path: Path,
    history_db_path: Path,
    telemetry_dir: Path,
    *,
    resolution_m: float,
    track_profile_dir: Path | None = None,
) -> dict[str, Any]:
    if resolution_m <= 0:
        raise ValueError("resolution_m debe ser > 0")
    if track_profile_dir is None:
        track_profile_dir = Path(__file__).resolve().parent / "track_profiles"

    pair = resolve_cross_session_pair(
        dual_reference_path,
        history_db_path,
        telemetry_dir,
    )
    current = pair["current"]
    historical = pair["historical"]

    historical_telemetry = Telemetry(str(historical["database"]))
    current_telemetry = Telemetry(str(current["database"]))
    try:
        historical_laps = LapAnalyzer(historical_telemetry)
        current_laps = LapAnalyzer(current_telemetry)
        delta = DeltaComparison(historical_laps, current_laps)
        sector = SectorAnalysis(delta)
        sector_result = sector.analyze(
            historical["lap"],
            current["lap"],
            resolution=resolution_m,
        )
        comparison = sector_result["comparison"]
        trend_zone_summaries = build_trend_zone_summaries(
            sector,
            comparison,
            sector_result["zones"],
        )
        profile, profile_path = find_validated_track_profile(
            track_profile_dir,
            track=pair["context"]["track"],
            layout=pair["context"]["track_layout"],
        )
        if profile is not None and profile_path is not None:
            zone_summaries = localize_trend_zones(
                sector,
                comparison,
                sector_result["zones"],
                profile,
                threshold=float(sector_result["threshold"]),
                min_zone_distance=float(sector_result["min_zone_distance"]),
            )
            localization = {
                "version": LOCALIZATION_VERSION,
                "mode": "validated_track_profile",
                "profile_id": profile.get("profile_id"),
                "profile_status": profile.get("status"),
                "profile_track": profile.get("track"),
                "profile_layout": profile.get("layout"),
                "profile_source_path": str(profile_path),
                "profile_source_sha256": sha256_file(profile_path),
                "boundary_count": len(profile_boundaries(profile)),
            }
        else:
            zone_summaries = unlocalized_zone_summaries(trend_zone_summaries)
            localization = {
                "version": LOCALIZATION_VERSION,
                "mode": "unavailable",
                "reason": "no_exact_validated_track_profile",
                "profile_id": None,
                "boundary_count": 0,
            }
        historical_summary = historical_laps.lap_summary(historical["lap"])
        current_summary = current_laps.lap_summary(current["lap"])
    finally:
        historical_telemetry.close()
        current_telemetry.close()

    if comparison.empty:
        raise ValueError("La comparación cross-session quedó vacía")

    historical_duration = float(historical_summary["duration"])
    current_duration = float(current_summary["duration"])
    expected_delta = current_duration - historical_duration
    calculated_delta = float(comparison["time_delta"].iloc[-1])
    temporal_error = calculated_delta - expected_delta
    temporal_status = (
        "OK" if abs(temporal_error) <= TEMPORAL_TOLERANCE_S else "ERROR"
    )
    if temporal_status != "OK":
        raise ValueError(
            "Validación temporal cross-session falló: "
            f"error={temporal_error:+.9f}s"
        )

    trend_zone_summaries = json_safe(trend_zone_summaries)
    zone_summaries = json_safe(zone_summaries)
    localization = json_safe(localization)
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "cross_session_version": CROSS_SESSION_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_dual_reference_json": str(dual_reference_path.resolve()),
            "source_dual_reference_sha256": sha256_file(dual_reference_path),
            "history_db": str(history_db_path.resolve()),
            "resolution_m": resolution_m,
            "policy": {
                "python_owns_cross_session_facts": True,
                "historical_reference_is_reference_lap_a": True,
                "current_session_is_comparison_lap_b": True,
                "delta_sign": "current_minus_historical",
                "historical_coaching_enabled": False,
                "llm_may_narrate_only_authorized_evidence": True,
                "trend_zones_preserved_for_audit": True,
                "llm_consumes_localized_zones": True,
            },
        },
        "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
        "context": pair["context"],
        "historical_reference": {
            "role": "raw_reference_lap_a",
            "session_id": historical["session_id"],
            "lap": historical["lap"],
            "duration_s": historical_duration,
            "source_database": str(historical["database"]),
            "source_database_sha256": sha256_file(historical["database"]),
            "lap_summary": json_safe(historical_summary),
        },
        "current_session_reference": {
            "role": "raw_comparison_lap_b",
            "session_id": current["session_id"],
            "lap": current["lap"],
            "duration_s": current_duration,
            "source_database": str(current["database"]),
            "source_database_sha256": sha256_file(current["database"]),
            "lap_summary": json_safe(current_summary),
        },
        "temporal_validation": {
            "status": temporal_status,
            "expected_current_minus_historical_s": expected_delta,
            "calculated_current_minus_historical_s": calculated_delta,
            "error_s": temporal_error,
            "tolerance_s": TEMPORAL_TOLERANCE_S,
        },
        "spatial_comparison": {
            "common_distance_m": float(comparison["distance"].iloc[-1]),
            "sample_count": int(len(comparison)),
            "resolution_m": resolution_m,
            "trend_zone_summary_count": len(trend_zone_summaries),
            "trend_zone_summaries": trend_zone_summaries,
            "localization": localization,
            "zone_summary_count": len(zone_summaries),
            "zone_summaries": zone_summaries,
        },
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_reference_is_observational": True,
            "historical_actions_authorized": False,
            "reason": (
                "H5.2 LLM permits controlled observational selection only; "
                "historical actions remain disabled"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.2: comparación determinista de vueltas raw cross-session"
    )
    parser.add_argument("dual_reference_json")
    parser.add_argument("--history-db", required=True)
    parser.add_argument("--telemetry-dir", default="telemetria")
    parser.add_argument("--output", required=True)
    parser.add_argument("--resolution-m", type=float, default=1.0)
    parser.add_argument(
        "--track-profile-dir",
        default=str(Path(__file__).resolve().parent / "track_profiles"),
    )
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    payload = build_comparison(
        Path(args.dual_reference_json).resolve(),
        Path(args.history_db).resolve(),
        Path(args.telemetry_dir).resolve(),
        resolution_m=args.resolution_m,
        track_profile_dir=Path(args.track_profile_dir).resolve(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    temporal = payload["temporal_validation"]
    print("=" * 88)
    print(f"RACE ENGINEER - H5.2 RAW CROSS-SESSION v{CROSS_SESSION_VERSION}")
    print("=" * 88)
    print(
        "Historical: "
        f"session={payload['historical_reference']['session_id']} "
        f"lap={payload['historical_reference']['lap']}"
    )
    print(
        "Current:    "
        f"session={payload['current_session_reference']['session_id']} "
        f"lap={payload['current_session_reference']['lap']}"
    )
    print(
        "Current - historical: "
        f"{temporal['calculated_current_minus_historical_s']:+.3f}s"
    )
    print(f"Temporal validation: {temporal['status']}")
    print(
        "Trend zones preserved: "
        f"{payload['spatial_comparison']['trend_zone_summary_count']}"
    )
    print(
        "Zone localization: "
        f"{payload['spatial_comparison']['localization']['mode']}"
    )
    print(f"Zone summaries: {payload['spatial_comparison']['zone_summary_count']}")
    print("Historical coaching: DISABLED pending LLM authorization contract")
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
