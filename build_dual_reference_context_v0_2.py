from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DUAL_REFERENCE_VERSION = "0.2"
SCHEMA_VERSION = "1.0"

STATUS_HISTORICAL_AVAILABLE = "DUAL_REFERENCE_AVAILABLE"
STATUS_SESSION_ONLY = "SESSION_REFERENCE_ONLY"

PROGRESS_AHEAD = "AHEAD_OF_HISTORICAL_BENCHMARK"
PROGRESS_BEHIND = "BEHIND_HISTORICAL_BENCHMARK"
PROGRESS_EQUAL = "EQUAL_TO_HISTORICAL_BENCHMARK"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: raíz JSON inválida.")
    return data


def lap_row(analysis: dict[str, Any], lap: int) -> dict[str, Any]:
    rows = analysis.get("laps")
    if not isinstance(rows, list):
        raise ValueError("analysis.laps ausente/inválido.")
    matches = [
        row for row in rows
        if isinstance(row, dict) and safe_int(row.get("lap")) == lap
    ]
    if len(matches) != 1:
        raise ValueError(f"Se esperaba exactamente una fila para lap={lap}; encontradas={len(matches)}.")
    return matches[0]


def derive_context_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    meta = analysis.get("metadata")
    if not isinstance(meta, dict):
        raise ValueError("analysis.metadata ausente/inválido.")

    vehicle = meta.get("vehicle_identity")
    if not isinstance(vehicle, dict):
        vehicle = {}

    session_context = meta.get("session_context")
    if not isinstance(session_context, dict):
        session_context = {}

    track = norm_text(meta.get("track"))
    layout = norm_text(session_context.get("lmu_track_layout"))
    # Real analyze_telemetry/session_history schema uses vehicle_identity.family/variant.
    # Keep aliases for backward/experimental compatibility.
    variant = norm_text(vehicle.get("variant")) or norm_text(vehicle.get("vehicle_variant"))
    car_name = norm_text(vehicle.get("car_name_raw"))

    # Older/experimental JSONs may have context keys directly in metadata.
    layout = layout or norm_text(meta.get("lmu_track_layout"))
    variant = variant or norm_text(meta.get("vehicle_variant"))
    car_name = car_name or norm_text(meta.get("car_name_raw"))

    return {
        "track": track,
        "track_layout": layout,
        "vehicle_variant": variant,
        "car_name_raw": car_name,
        "session_type": norm_text(meta.get("session_type")),
        "timestamp_utc": norm_text(meta.get("timestamp_utc")),
        "source_file": norm_text(meta.get("source_file")),
        "source_database": norm_text(meta.get("database")),
        "analysis_version": norm_text(meta.get("analysis_version")),
    }


def progress_status(delta_current_minus_historical_s: float, tolerance_s: float) -> str:
    if delta_current_minus_historical_s > tolerance_s:
        return PROGRESS_BEHIND
    if delta_current_minus_historical_s < -tolerance_s:
        return PROGRESS_AHEAD
    return PROGRESS_EQUAL


def validate_selection_target_against_analysis(
    analysis: dict[str, Any],
    selection: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    meta = analysis.get("metadata")
    if not isinstance(meta, dict):
        raise ValueError("analysis.metadata ausente/inválido.")

    # H4 v0.1/v0.2 real output uses target_session.session_reference.
    # Accept the earlier draft aliases only for backward compatibility.
    target = selection.get("target_session")
    if not isinstance(target, dict):
        target = selection.get("target")
    if not isinstance(target, dict):
        raise ValueError("selection.target_session ausente/inválido.")

    context = derive_context_from_analysis(analysis)

    analysis_ref_lap = safe_int(meta.get("reference_lap"))
    target_ref = target.get("session_reference")
    if not isinstance(target_ref, dict):
        target_ref = target.get("reference") or {}
    target_ref_lap = safe_int(target_ref.get("lap"))

    if analysis_ref_lap is None:
        raise ValueError("analysis.metadata.reference_lap ausente.")
    if target_ref_lap is None:
        raise ValueError("selection.target_session.session_reference.lap ausente.")
    if analysis_ref_lap != target_ref_lap:
        raise ValueError(
            f"Reference lap mismatch: analysis={analysis_ref_lap} selection={target_ref_lap}"
        )

    row = lap_row(analysis, analysis_ref_lap)
    duration = safe_float(row.get("duration_s"))
    if duration is None:
        duration = safe_float(row.get("duration"))
    target_duration = safe_float(target_ref.get("duration_s"))

    if duration is None or duration <= 0:
        raise ValueError("Duración de session reference inválida en analysis.laps.")
    if target_duration is None or target_duration <= 0:
        raise ValueError("Duración target inválida en H4 selection.")
    if abs(duration - target_duration) > 1e-6:
        raise ValueError(
            f"Reference duration mismatch: analysis={duration} selection={target_duration}"
        )

    # H4 real schema stores context directly in target_session.
    selection_context = target
    checks = (
        ("track", context.get("track"), selection_context.get("track")),
        ("track_layout", context.get("track_layout"), selection_context.get("track_layout")),
        ("vehicle_variant", context.get("vehicle_variant"), selection_context.get("vehicle_variant")),
        ("car_name_raw", context.get("car_name_raw"), selection_context.get("car_name_raw")),
    )
    for label, a, b in checks:
        # The analysis JSON may be legacy and not carry all session-context fields.
        # If both sides are known they must agree.
        if norm_text(a) is not None and norm_text(b) is not None and norm_text(a) != norm_text(b):
            raise ValueError(f"Context mismatch {label}: analysis={a!r} selection={b!r}")

    return context, target, {
        "lap": analysis_ref_lap,
        "duration_s": duration,
        "samples": safe_int(row.get("samples")),
        "lap_distance_m": (
            safe_float(row.get("lap_distance_m"))
            if safe_float(row.get("lap_distance_m")) is not None
            else safe_float(row.get("lap_distance"))
        ),
    }


def build_dual_reference(
    analysis_path: Path,
    selection_path: Path,
    *,
    equality_tolerance_s: float,
) -> dict[str, Any]:
    if equality_tolerance_s < 0:
        raise ValueError("equality_tolerance_s debe ser >= 0.")

    analysis = load_json(analysis_path)
    selection = load_json(selection_path)

    selection_meta = selection.get("metadata") or {}
    selector_version = norm_text(selection_meta.get("selector_version"))
    if selector_version not in {"0.1", "0.2"}:
        raise ValueError(f"H4 selector_version no soportada: {selector_version!r}")

    context, target, session_ref = validate_selection_target_against_analysis(
        analysis, selection
    )

    selection_status = (
        norm_text(selection.get("selection_status"))
        or norm_text(selection.get("status"))
    )
    selected = selection.get("selected_historical_reference")
    if selected is None:
        selected = selection.get("historical_reference")

    historical_available = (
        selection_status == "HISTORICAL_REFERENCE_SELECTED"
        and isinstance(selected, dict)
    )

    historical_ref = None
    progress = {
        "historical_reference_available": historical_available,
        "current_minus_historical_s": None,
        "historical_minus_current_s": None,
        "status": None,
        "interpretation": None,
        "equality_tolerance_s": equality_tolerance_s,
    }

    if historical_available:
        # H4 real selected snapshot uses lap/duration_s.
        hist_duration = safe_float(selected.get("duration_s"))
        if hist_duration is None:
            hist_duration = safe_float(selected.get("reference_lap_duration_s"))
        hist_lap = safe_int(selected.get("lap"))
        if hist_lap is None:
            hist_lap = safe_int(selected.get("reference_lap"))
        hist_session = safe_int(selected.get("session_id"))

        if hist_duration is None or hist_duration <= 0:
            raise ValueError("Historical reference duration inválida.")
        if hist_lap is None or hist_session is None:
            raise ValueError("Historical reference identity incompleta.")

        delta = session_ref["duration_s"] - hist_duration
        state = progress_status(delta, equality_tolerance_s)

        historical_ref = {
            "role": "long_term_benchmark",
            "session_id": hist_session,
            "lap": hist_lap,
            "duration_s": hist_duration,
            "timestamp_utc": norm_text(selected.get("timestamp_utc")),
            "session_type": norm_text(selected.get("session_type")),
            "weather_conditions": norm_text(selected.get("weather_conditions")),
            "weather_class": norm_text(selected.get("weather_class")),
            "same_setup_sha256": (
                norm_text(target.get("setup_sha256")) == norm_text(selected.get("setup_sha256"))
                if norm_text(target.get("setup_sha256")) is not None
                and norm_text(selected.get("setup_sha256")) is not None
                else None
            ),
            "source_database_path": norm_text(selected.get("source_database_path")),
            "source_json_path": norm_text(selected.get("source_json_path")),
            "selection_rank": safe_int(selected.get("selection_rank")),
        }
        progress.update({
            "current_minus_historical_s": delta,
            "historical_minus_current_s": -delta,
            "status": state,
            "interpretation": (
                "current_session_reference_is_slower"
                if state == PROGRESS_BEHIND
                else "current_session_reference_is_faster"
                if state == PROGRESS_AHEAD
                else "references_are_equivalent_within_tolerance"
            ),
        })

    dual_status = STATUS_HISTORICAL_AVAILABLE if historical_available else STATUS_SESSION_ONLY

    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "dual_reference_version": DUAL_REFERENCE_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_analysis_json": str(analysis_path.resolve()),
            "source_analysis_sha256": sha256_file(analysis_path),
            "source_h4_selection_json": str(selection_path.resolve()),
            "source_h4_selection_sha256": sha256_file(selection_path),
            "h4_selector_version": selector_version,
            "policy": {
                "session_reference_role": "operational_coaching_reference",
                "historical_reference_role": "long_term_progress_benchmark",
                "historical_reference_replaces_session_reference": False,
                "historical_action_coaching_enabled": False,
                "historical_telemetry_reconstruction_from_history_allowed": False,
                "fallback_when_no_historical_reference": "continue_with_session_reference_only",
            },
        },
        "status": dual_status,
        "context": {
            "track": target.get("track") or context.get("track"),
            "track_layout": target.get("track_layout") or context.get("track_layout"),
            "vehicle_variant": target.get("vehicle_variant") or context.get("vehicle_variant"),
            "car_name_raw": target.get("car_name_raw") or context.get("car_name_raw"),
        },
        "target_session": {
            "session_id": safe_int(target.get("session_id")),
            "timestamp_utc": target.get("timestamp_utc") or context.get("timestamp_utc"),
            "session_type": target.get("session_type") or context.get("session_type"),
            "weather_conditions": target.get("weather_conditions"),
            "weather_class": target.get("weather_class"),
        },
        "session_reference": {
            "role": "operational_coaching_reference",
            **session_ref,
        },
        "historical_reference": historical_ref,
        "long_term_progress": progress,
        "coaching_authority": {
            "active_reference": "session_reference",
            "historical_reference_can_change_driver_cues": False,
            "historical_reference_can_change_global_ABC_plan": False,
            "historical_reference_is_observational_only": True,
        },
        "next_stage": {
            "cross_session_telemetry_comparison_required_for_historical_actions": historical_available,
            "required_source": "raw DuckDB telemetry from both sessions",
            "history_episode_summaries_are_not_sufficient": True,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="H5.1 v0.2: construye contexto dual-reference determinista sin cambiar coaching."
    )
    ap.add_argument("analysis_json", help="JSON determinista de analyze_telemetry para la sesión target.")
    ap.add_argument("historical_selection_json", help="Salida H4 para la misma sesión target.")
    ap.add_argument("--output", default="dual_reference_context.json")
    ap.add_argument("--equality-tolerance-s", type=float, default=0.001)
    args = ap.parse_args()

    analysis_path = Path(args.analysis_json)
    selection_path = Path(args.historical_selection_json)
    output_path = Path(args.output)

    payload = build_dual_reference(
        analysis_path,
        selection_path,
        equality_tolerance_s=args.equality_tolerance_s,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    session = payload["session_reference"]
    hist = payload["historical_reference"]
    progress = payload["long_term_progress"]

    print("=" * 88)
    print(f"RACE ENGINEER - H5.1 DUAL REFERENCE CONTEXT v{DUAL_REFERENCE_VERSION}")
    print("=" * 88)
    print(f"Status:                 {payload['status']}")
    print(f"Target session:         {payload['target_session']['session_id']}")
    print(f"Session reference:      lap {session['lap']} / {session['duration_s']:.3f}s")
    if hist is None:
        print("Historical reference:   NONE")
        print("Coaching:               SESSION_REFERENCE_ONLY")
    else:
        print(
            f"Historical reference:   session {hist['session_id']} "
            f"lap {hist['lap']} / {hist['duration_s']:.3f}s"
        )
        print(f"Current - historical:   {progress['current_minus_historical_s']:+.3f}s")
        print(f"Long-term status:       {progress['status']}")
        print("Historical coaching:    DISABLED (observational only)")
    print(f"Output: {output_path.resolve()}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
