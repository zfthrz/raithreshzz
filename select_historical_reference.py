from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

SELECTOR_VERSION = "0.2"
EXPECTED_HISTORY_SCHEMA_VERSION = 4
DEFAULT_DB_NAME = "race_engineer_history.duckdb"
DEFAULT_MIN_VALID_LAPS = 3


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def base_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def default_db_path() -> str:
    return os.path.join(base_dir(), DEFAULT_DB_NAME)


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_float(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def norm_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None



PRECIPITATION_TOKENS = (
    "rain",
    "rainy",
    "drizzle",
    "shower",
    "storm",
    "thunder",
    "wet",
    "precip",
)

UNKNOWN_WEATHER_TOKENS = {
    "unknown",
    "n/a",
    "na",
    "none",
    "null",
    "unavailable",
}


def weather_class(value: Any) -> str:
    """
    H4 weather comparability class.

    DRY:
        Any known weather label without a precipitation/wet token.
        Examples: Clear, Light Clouds, Partially Cloudy, Cloudy, Overcast.

    WET:
        Any label explicitly indicating rain/precipitation/wet conditions.

    UNKNOWN:
        Missing or explicitly unknown weather.
    """
    text = norm_text(value)
    if text is None:
        return "UNKNOWN"

    lowered = text.casefold()
    if lowered in UNKNOWN_WEATHER_TOKENS:
        return "UNKNOWN"

    if any(token in lowered for token in PRECIPITATION_TOKENS):
        return "WET"

    return "DRY"


def weather_compatibility(target_raw: Any, candidate_raw: Any) -> tuple[bool, str]:
    """
    Policy v0.2:
    - DRY <-> DRY: comparable regardless of cloud label.
    - WET <-> WET: require exact raw label for now.
    - Known target <-> UNKNOWN candidate: reject.
    - UNKNOWN target: provisional.
    """
    target_class = weather_class(target_raw)
    candidate_class = weather_class(candidate_raw)

    if target_class == "UNKNOWN":
        return True, "TARGET_WEATHER_UNKNOWN_PROVISIONAL"

    if candidate_class == "UNKNOWN":
        return False, "WEATHER_UNKNOWN_WHILE_TARGET_KNOWN"

    if target_class != candidate_class:
        return False, "WEATHER_CLASS_MISMATCH"

    if target_class == "DRY":
        return True, "DRY_CLASS_COMPATIBLE"

    if norm_text(target_raw) == norm_text(candidate_raw):
        return True, "WET_EXACT_RAW_COMPATIBLE"

    return False, "WET_WEATHER_RAW_MISMATCH"


def parse_timestamp(value: Any) -> datetime | None:
    text = norm_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def require_schema4(connection) -> None:
    row = connection.execute(
        "SELECT schema_version FROM history_meta LIMIT 1"
    ).fetchone()
    version = safe_int(row[0]) if row else None
    if version != EXPECTED_HISTORY_SCHEMA_VERSION:
        raise RuntimeError(
            f"H4 selector v{SELECTOR_VERSION} requiere History schema "
            f"{EXPECTED_HISTORY_SCHEMA_VERSION}; DB={version!r}."
        )


def load_session(connection, session_id: int) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
            session_id,
            source_json_path,
            source_json_sha256,
            source_analysis_version,
            track,
            session_type,
            timestamp_utc,
            vehicle_family,
            vehicle_variant,
            car_class_raw,
            car_name_raw,
            vehicle_supported_domain,
            weather_conditions,
            setup_sha256,
            setup_available,
            lmu_session_type,
            lmu_track_name,
            lmu_track_layout,
            reference_lap,
            reference_distance_m,
            temporal_validation_status,
            objective_analysis_validation,
            valid_lap_count,
            discarded_lap_count,
            comparison_count
        FROM sessions
        WHERE session_id = ?
        """,
        [session_id],
    ).fetchone()
    if row is None:
        raise ValueError(f"No existe session_id={session_id}.")
    names = [
        "session_id", "source_json_path", "source_json_sha256",
        "source_analysis_version", "track", "session_type", "timestamp_utc",
        "vehicle_family", "vehicle_variant", "car_class_raw", "car_name_raw",
        "vehicle_supported_domain", "weather_conditions", "setup_sha256",
        "setup_available", "lmu_session_type", "lmu_track_name",
        "lmu_track_layout", "reference_lap", "reference_distance_m",
        "temporal_validation_status", "objective_analysis_validation",
        "valid_lap_count", "discarded_lap_count", "comparison_count",
    ]
    return dict(zip(names, row))


def load_reference_lap(connection, session_id: int, reference_lap: int | None) -> dict[str, Any] | None:
    if reference_lap is None:
        return None
    row = connection.execute(
        """
        SELECT
            session_id,
            lap,
            start_time_s,
            end_time_s,
            duration_s,
            samples,
            lap_distance_m,
            is_valid,
            is_discarded,
            is_ignored_initial,
            is_reference
        FROM laps
        WHERE session_id = ? AND lap = ?
        """,
        [session_id, reference_lap],
    ).fetchone()
    if row is None:
        return None
    names = [
        "session_id", "lap", "start_time_s", "end_time_s", "duration_s",
        "samples", "lap_distance_m", "is_valid", "is_discarded",
        "is_ignored_initial", "is_reference",
    ]
    return dict(zip(names, row))


def load_historical_sessions(connection, target: dict[str, Any]) -> list[dict[str, Any]]:
    # Query is intentionally broader than the final gate so rejected candidates remain auditable.
    rows = connection.execute(
        """
        SELECT
            session_id,
            source_json_path,
            source_json_sha256,
            source_analysis_version,
            track,
            session_type,
            timestamp_utc,
            vehicle_family,
            vehicle_variant,
            car_class_raw,
            car_name_raw,
            vehicle_supported_domain,
            weather_conditions,
            setup_sha256,
            setup_available,
            lmu_session_type,
            lmu_track_name,
            lmu_track_layout,
            reference_lap,
            reference_distance_m,
            temporal_validation_status,
            objective_analysis_validation,
            valid_lap_count,
            discarded_lap_count,
            comparison_count
        FROM sessions
        WHERE session_id <> ?
        ORDER BY timestamp_utc, session_id
        """,
        [target["session_id"]],
    ).fetchall()
    names = [
        "session_id", "source_json_path", "source_json_sha256",
        "source_analysis_version", "track", "session_type", "timestamp_utc",
        "vehicle_family", "vehicle_variant", "car_class_raw", "car_name_raw",
        "vehicle_supported_domain", "weather_conditions", "setup_sha256",
        "setup_available", "lmu_session_type", "lmu_track_name",
        "lmu_track_layout", "reference_lap", "reference_distance_m",
        "temporal_validation_status", "objective_analysis_validation",
        "valid_lap_count", "discarded_lap_count", "comparison_count",
    ]
    return [dict(zip(names, row)) for row in rows]


def validate_reference_lap(lap: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    if lap is None:
        return ["REFERENCE_LAP_ROW_MISSING"]
    duration = safe_float(lap.get("duration_s"))
    samples = safe_int(lap.get("samples"))
    distance = safe_float(lap.get("lap_distance_m"))
    if lap.get("is_valid") is not True:
        reasons.append("REFERENCE_LAP_NOT_VALID")
    if lap.get("is_discarded") is True:
        reasons.append("REFERENCE_LAP_DISCARDED")
    if lap.get("is_ignored_initial") is True:
        reasons.append("REFERENCE_LAP_IGNORED_INITIAL")
    if lap.get("is_reference") is not True:
        reasons.append("REFERENCE_LAP_FLAG_MISSING")
    if duration is None or duration <= 0:
        reasons.append("REFERENCE_LAP_DURATION_INVALID")
    if samples is None or samples <= 0:
        reasons.append("REFERENCE_LAP_SAMPLES_INVALID")
    if distance is None or distance <= 0:
        reasons.append("REFERENCE_LAP_DISTANCE_INVALID")
    return reasons


def target_gate_errors(target: dict[str, Any], target_lap: dict[str, Any] | None, min_valid_laps: int) -> list[str]:
    errors: list[str] = []
    for field in ("track", "lmu_track_layout", "vehicle_variant", "car_name_raw"):
        if not norm_text(target.get(field)):
            errors.append(f"TARGET_{field.upper()}_MISSING")
    if target.get("vehicle_supported_domain") is not True:
        errors.append("TARGET_VEHICLE_DOMAIN_UNSUPPORTED")
    if norm_text(target.get("temporal_validation_status")) != "OK":
        errors.append("TARGET_TEMPORAL_VALIDATION_NOT_OK")
    if norm_text(target.get("objective_analysis_validation")) != "OK":
        errors.append("TARGET_OBJECTIVE_VALIDATION_NOT_OK")
    valid_count = safe_int(target.get("valid_lap_count"))
    if valid_count is None or valid_count < min_valid_laps:
        errors.append("TARGET_INSUFFICIENT_VALID_LAPS")
    if safe_int(target.get("reference_lap")) is None:
        errors.append("TARGET_REFERENCE_LAP_MISSING")
    errors.extend("TARGET_" + code for code in validate_reference_lap(target_lap))
    if parse_timestamp(target.get("timestamp_utc")) is None:
        errors.append("TARGET_TIMESTAMP_INVALID")
    return errors


def evaluate_candidate(
    target: dict[str, Any],
    target_lap: dict[str, Any],
    candidate: dict[str, Any],
    candidate_lap: dict[str, Any] | None,
    *,
    min_valid_laps: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    target_ts = parse_timestamp(target.get("timestamp_utc"))
    candidate_ts = parse_timestamp(candidate.get("timestamp_utc"))

    if candidate_ts is None:
        reasons.append("CANDIDATE_TIMESTAMP_INVALID")
    elif target_ts is not None and candidate_ts >= target_ts:
        reasons.append("NOT_HISTORICAL_BEFORE_TARGET")

    if norm_text(candidate.get("track")) != norm_text(target.get("track")):
        reasons.append("TRACK_MISMATCH")
    if norm_text(candidate.get("lmu_track_layout")) != norm_text(target.get("lmu_track_layout")):
        reasons.append("LAYOUT_MISMATCH")
    if norm_text(candidate.get("vehicle_variant")) != norm_text(target.get("vehicle_variant")):
        reasons.append("VEHICLE_VARIANT_MISMATCH")
    if norm_text(candidate.get("car_name_raw")) != norm_text(target.get("car_name_raw")):
        reasons.append("CAR_NAME_MISMATCH")
    if candidate.get("vehicle_supported_domain") is not True:
        reasons.append("VEHICLE_DOMAIN_UNSUPPORTED")
    if norm_text(candidate.get("temporal_validation_status")) != "OK":
        reasons.append("TEMPORAL_VALIDATION_NOT_OK")
    if norm_text(candidate.get("objective_analysis_validation")) != "OK":
        reasons.append("OBJECTIVE_VALIDATION_NOT_OK")

    valid_count = safe_int(candidate.get("valid_lap_count"))
    if valid_count is None or valid_count < min_valid_laps:
        reasons.append("INSUFFICIENT_VALID_LAPS")

    # Weather v0.2: all known dry cloud-cover labels are functionally equivalent.
    # Wet conditions remain conservative until precipitation intensity / track wetness
    # are modeled explicitly.
    weather_ok, weather_reason = weather_compatibility(
        target.get("weather_conditions"),
        candidate.get("weather_conditions"),
    )
    if not weather_ok:
        reasons.append(weather_reason)

    reasons.extend(validate_reference_lap(candidate_lap))

    target_duration = safe_float(target_lap.get("duration_s"))
    cand_duration = safe_float(candidate_lap.get("duration_s")) if candidate_lap else None
    delta_to_target = (
        cand_duration - target_duration
        if cand_duration is not None and target_duration is not None
        else None
    )

    return {
        "session_id": safe_int(candidate.get("session_id")),
        "timestamp_utc": candidate.get("timestamp_utc"),
        "session_type": candidate.get("session_type"),
        "lmu_session_type": candidate.get("lmu_session_type"),
        "track": candidate.get("track"),
        "track_layout": candidate.get("lmu_track_layout"),
        "vehicle_variant": candidate.get("vehicle_variant"),
        "car_name_raw": candidate.get("car_name_raw"),
        "weather_conditions": candidate.get("weather_conditions"),
        "weather_class": weather_class(candidate.get("weather_conditions")),
        "setup_sha256": candidate.get("setup_sha256"),
        "valid_lap_count": valid_count,
        "reference_lap": safe_int(candidate.get("reference_lap")),
        "reference_lap_duration_s": cand_duration,
        "reference_lap_samples": safe_int(candidate_lap.get("samples")) if candidate_lap else None,
        "reference_lap_distance_m": safe_float(candidate_lap.get("lap_distance_m")) if candidate_lap else None,
        "source_json_path": candidate.get("source_json_path"),
        "source_json_sha256": candidate.get("source_json_sha256"),
        "eligibility": "ELIGIBLE" if not reasons else "REJECTED",
        "rejection_reasons": reasons,
        "compatibility_observations": {
            "same_session_type": norm_text(candidate.get("session_type")) == norm_text(target.get("session_type")),
            "same_lmu_session_type": norm_text(candidate.get("lmu_session_type")) == norm_text(target.get("lmu_session_type")),
            "same_setup_sha256": (
                norm_text(target.get("setup_sha256")) is not None
                and norm_text(candidate.get("setup_sha256")) == norm_text(target.get("setup_sha256"))
            ),
            "same_weather_raw": (
                norm_text(target.get("weather_conditions")) is not None
                and norm_text(candidate.get("weather_conditions")) == norm_text(target.get("weather_conditions"))
            ),
            "target_weather_class": weather_class(target.get("weather_conditions")),
            "candidate_weather_class": weather_class(candidate.get("weather_conditions")),
            "weather_compatibility": weather_compatibility(
                target.get("weather_conditions"),
                candidate.get("weather_conditions"),
            )[1],
        },
        "candidate_minus_target_reference_s": delta_to_target,
    }


def selected_snapshot(candidate: dict[str, Any], target_duration: float | None) -> dict[str, Any]:
    duration = safe_float(candidate.get("reference_lap_duration_s"))
    return {
        "session_id": candidate.get("session_id"),
        "lap": candidate.get("reference_lap"),
        "duration_s": duration,
        "timestamp_utc": candidate.get("timestamp_utc"),
        "session_type": candidate.get("session_type"),
        "lmu_session_type": candidate.get("lmu_session_type"),
        "weather_conditions": candidate.get("weather_conditions"),
        "weather_class": candidate.get("weather_class"),
        "setup_sha256": candidate.get("setup_sha256"),
        "source_json_path": candidate.get("source_json_path"),
        "source_json_sha256": candidate.get("source_json_sha256"),
        "historical_minus_session_reference_s": (
            duration - target_duration
            if duration is not None and target_duration is not None
            else None
        ),
        "selection_basis": "fastest_eligible_session_reference_lap",
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="H4 v0.2: selecciona benchmark histórico determinista para una sesión target."
    )
    ap.add_argument("current_session_id", type=int)
    ap.add_argument("--db", default=default_db_path())
    ap.add_argument("--output", default="historical_reference_selection.json")
    ap.add_argument("--min-valid-laps", type=int, default=DEFAULT_MIN_VALID_LAPS)
    args = ap.parse_args()

    if args.min_valid_laps < 1:
        raise ValueError("--min-valid-laps debe ser >= 1.")

    db_path = Path(args.db).resolve()
    out_path = Path(args.output).resolve()
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        require_schema4(connection)
        target = load_session(connection, args.current_session_id)
        target_ref = safe_int(target.get("reference_lap"))
        target_lap = load_reference_lap(connection, args.current_session_id, target_ref)
        errors = target_gate_errors(target, target_lap, args.min_valid_laps)
        if errors:
            raise ValueError("Target session no elegible para H4: " + ", ".join(errors))
        assert target_lap is not None

        candidates = []
        for candidate in load_historical_sessions(connection, target):
            cref = safe_int(candidate.get("reference_lap"))
            clap = load_reference_lap(connection, safe_int(candidate.get("session_id")), cref)
            candidates.append(
                evaluate_candidate(
                    target, target_lap, candidate, clap,
                    min_valid_laps=args.min_valid_laps,
                )
            )

        eligible = [c for c in candidates if c["eligibility"] == "ELIGIBLE"]
        eligible.sort(
            key=lambda c: (
                safe_float(c.get("reference_lap_duration_s"))
                if safe_float(c.get("reference_lap_duration_s")) is not None
                else float("inf"),
                c.get("timestamp_utc") or "",
                c.get("session_id") or 0,
            )
        )
        rejected = [c for c in candidates if c["eligibility"] == "REJECTED"]
        rejected.sort(key=lambda c: (c.get("timestamp_utc") or "", c.get("session_id") or 0))
        ordered_candidates = eligible + rejected

        target_duration = safe_float(target_lap.get("duration_s"))
        selected = selected_snapshot(eligible[0], target_duration) if eligible else None
        target_weather_known = weather_class(target.get("weather_conditions")) != "UNKNOWN"

        payload = {
            "metadata": {
                "selector_version": SELECTOR_VERSION,
                "created_at_utc": utc_now_iso(),
                "history_schema_version": EXPECTED_HISTORY_SCHEMA_VERSION,
                "database_path": str(db_path),
                "min_valid_laps": args.min_valid_laps,
                "candidate_unit": "session_reference_lap",
                "hard_context_gate": [
                    "historical_timestamp_before_target",
                    "same_track",
                    "same_lmu_track_layout",
                    "same_vehicle_variant",
                    "same_car_name_raw",
                    "vehicle_supported_domain_true",
                    "temporal_validation_status_OK",
                    "objective_analysis_validation_OK",
                    "minimum_valid_lap_count",
                    "valid_reference_lap_with_samples_and_distance",
                    "weather_class_compatible_dry_or_conservative_wet",
                ],
                "weather_policy_v0_2": {
                    "classes": ["DRY", "WET", "UNKNOWN"],
                    "dry_rule": "all known non-precipitation weather labels are comparable",
                    "wet_rule": "exact raw weather label required until wetness/intensity is modeled",
                    "unknown_rule": "known target rejects unknown candidate; unknown target is provisional",
                },
                "non_gating_observations_v0_2": [
                    "session_type",
                    "lmu_session_type",
                    "setup_sha256",
                ],
                "policy": (
                    "Deterministic H4 selection only. Does not alter coaching. "
                    "Only per-session analyze_telemetry reference laps compete."
                ),
            },
            "target_session": {
                "session_id": target["session_id"],
                "timestamp_utc": target.get("timestamp_utc"),
                "track": target.get("track"),
                "track_layout": target.get("lmu_track_layout"),
                "vehicle_family": target.get("vehicle_family"),
                "vehicle_variant": target.get("vehicle_variant"),
                "car_name_raw": target.get("car_name_raw"),
                "session_type": target.get("session_type"),
                "lmu_session_type": target.get("lmu_session_type"),
                "weather_conditions": target.get("weather_conditions"),
                "weather_class": weather_class(target.get("weather_conditions")),
                "setup_sha256": target.get("setup_sha256"),
                "valid_lap_count": safe_int(target.get("valid_lap_count")),
                "session_reference": {
                    "lap": safe_int(target_lap.get("lap")),
                    "duration_s": target_duration,
                    "samples": safe_int(target_lap.get("samples")),
                    "lap_distance_m": safe_float(target_lap.get("lap_distance_m")),
                },
            },
            "selection_status": (
                "HISTORICAL_REFERENCE_SELECTED" if selected is not None
                else "NO_COMPATIBLE_HISTORICAL_REFERENCE"
            ),
            "selection_scope": (
                "FULLY_GATED_V0_2_WEATHER_CLASS" if target_weather_known
                else "PROVISIONAL_TARGET_WEATHER_UNKNOWN"
            ),
            "selected_historical_reference": selected,
            "candidate_summary": {
                "candidate_sessions_considered": len(candidates),
                "eligible": len(eligible),
                "rejected": len(rejected),
            },
            "candidates": ordered_candidates,
        }
    finally:
        connection.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 84)
    print(f"RACE ENGINEER - H4 HISTORICAL REFERENCE SELECTOR v{SELECTOR_VERSION}")
    print("=" * 84)
    print(f"Target session:       {payload['target_session']['session_id']}")
    print(f"Context:              {payload['target_session']['track']} | {payload['target_session']['track_layout']} | {payload['target_session']['vehicle_variant']}")
    print(f"Car:                  {payload['target_session']['car_name_raw']}")
    print(f"Target ref lap:       {payload['target_session']['session_reference']['lap']} ({payload['target_session']['session_reference']['duration_s']:.3f}s)")
    print(f"Candidates considered:{payload['candidate_summary']['candidate_sessions_considered']}")
    print(f"Eligible:             {payload['candidate_summary']['eligible']}")
    print(f"Rejected:             {payload['candidate_summary']['rejected']}")
    print(f"Status:               {payload['selection_status']}")
    if payload["selected_historical_reference"]:
        s = payload["selected_historical_reference"]
        print(f"Historical ref:       session={s['session_id']} lap={s['lap']} duration={s['duration_s']:.3f}s")
        print(f"Hist - session ref:   {s['historical_minus_session_reference_s']:+.3f}s")
    print(f"Output: {out_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
