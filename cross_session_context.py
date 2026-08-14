from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
from typing import Any


class CrossSessionNotApplicableError(ValueError):
    """Raised when H5.2 lacks a safe, fully resolved raw-session pair."""


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def norm_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def basename_any(path_text: str | None) -> str | None:
    text = norm_text(path_text)
    if text is None:
        return None
    if "\\" in text:
        return PureWindowsPath(text).name
    return Path(text).name


def resolve_duckdb(
    telemetry_dir: Path,
    source_database_path: str | None,
    source_json_path: str | None,
) -> tuple[Path | None, list[str]]:
    attempted: list[str] = []

    database_basename = basename_any(source_database_path)
    if database_basename:
        candidate = telemetry_dir / database_basename
        attempted.append(str(candidate))
        if candidate.is_file():
            return candidate.resolve(), attempted

    json_basename = basename_any(source_json_path)
    if json_basename:
        candidate = telemetry_dir / (Path(json_basename).stem + ".duckdb")
        attempted.append(str(candidate))
        if candidate.is_file():
            return candidate.resolve(), attempted

    return None, attempted


def load_dual_reference(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CrossSessionNotApplicableError("dual_reference_context inválido")
    return data


def history_session_row(connection: Any, session_id: int) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
            session_id,
            source_json_path,
            source_database_path,
            track,
            session_type,
            timestamp_utc,
            vehicle_variant,
            car_name_raw,
            lmu_track_layout,
            reference_lap
        FROM sessions
        WHERE session_id = ?
        """,
        [session_id],
    ).fetchone()
    if row is None:
        raise CrossSessionNotApplicableError(
            f"session_id={session_id} no existe en History"
        )
    names = [
        "session_id",
        "source_json_path",
        "source_database_path",
        "track",
        "session_type",
        "timestamp_utc",
        "vehicle_variant",
        "car_name_raw",
        "lmu_track_layout",
        "reference_lap",
    ]
    return dict(zip(names, row))


def resolve_cross_session_pair(
    dual_reference_path: Path,
    history_db_path: Path,
    telemetry_dir: Path,
) -> dict[str, Any]:
    dual = load_dual_reference(dual_reference_path)
    target = dual.get("target_session") or {}
    session_reference = dual.get("session_reference") or {}
    historical_reference = dual.get("historical_reference")

    current_session_id = safe_int(target.get("session_id"))
    current_lap = safe_int(session_reference.get("lap"))
    if current_session_id is None or current_lap is None:
        raise CrossSessionNotApplicableError(
            "dual_reference_context no identifica sesión/vuelta actual"
        )
    if not isinstance(historical_reference, dict):
        raise CrossSessionNotApplicableError(
            "dual_reference_context no contiene historical_reference"
        )
    historical_session_id = safe_int(historical_reference.get("session_id"))
    historical_lap = safe_int(historical_reference.get("lap"))
    if historical_session_id is None or historical_lap is None:
        raise CrossSessionNotApplicableError(
            "historical_reference no identifica sesión/vuelta"
        )

    if not history_db_path.is_file():
        raise CrossSessionNotApplicableError(f"History DB no existe: {history_db_path}")
    if not telemetry_dir.is_dir():
        raise CrossSessionNotApplicableError(f"telemetria no existe: {telemetry_dir}")

    import duckdb

    connection = duckdb.connect(str(history_db_path), read_only=True)
    try:
        current_history = history_session_row(connection, current_session_id)
        historical_history = history_session_row(connection, historical_session_id)
    finally:
        connection.close()

    context_keys = ("track", "vehicle_variant", "car_name_raw", "lmu_track_layout")
    mismatches = [
        {
            "field": key,
            "current": current_history.get(key),
            "historical": historical_history.get(key),
        }
        for key in context_keys
        if norm_text(current_history.get(key)) != norm_text(historical_history.get(key))
    ]
    if mismatches:
        raise CrossSessionNotApplicableError(f"context mismatch: {mismatches}")

    current_database, current_attempts = resolve_duckdb(
        telemetry_dir,
        current_history.get("source_database_path"),
        current_history.get("source_json_path"),
    )
    historical_database, historical_attempts = resolve_duckdb(
        telemetry_dir,
        historical_history.get("source_database_path"),
        historical_history.get("source_json_path"),
    )
    if current_database is None:
        raise CrossSessionNotApplicableError(
            "DuckDB actual no resoluble; intentados: " + ", ".join(current_attempts)
        )
    if historical_database is None:
        raise CrossSessionNotApplicableError(
            "DuckDB histórico no resoluble; intentados: "
            + ", ".join(historical_attempts)
        )

    return {
        "dual_reference": dual,
        "context": {
            "track": current_history.get("track"),
            "track_layout": current_history.get("lmu_track_layout"),
            "vehicle_variant": current_history.get("vehicle_variant"),
            "car_name_raw": current_history.get("car_name_raw"),
        },
        "current": {
            "session_id": current_session_id,
            "lap": current_lap,
            "history": current_history,
            "database": current_database,
            "resolution_attempts": current_attempts,
        },
        "historical": {
            "session_id": historical_session_id,
            "lap": historical_lap,
            "history": historical_history,
            "database": historical_database,
            "resolution_attempts": historical_attempts,
        },
    }
