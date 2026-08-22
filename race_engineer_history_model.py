"""Read-only History catalogue for the Race Engineer desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb


EXPECTED_HISTORY_SCHEMA_VERSION = 4


@dataclass(frozen=True)
class HistorySession:
    session_id: int
    timestamp_utc: str
    track: str
    track_layout: str
    session_type: str
    vehicle_variant: str
    car_name: str
    weather: str
    reference_lap: int | None
    reference_time_s: float | None
    valid_lap_count: int
    comparison_count: int
    source_json_path: Path | None
    source_database_path: Path | None


@dataclass(frozen=True)
class HistoryLap:
    lap: int
    duration_s: float | None
    is_valid: bool
    is_reference: bool
    is_discarded: bool
    is_ignored_initial: bool


@dataclass(frozen=True)
class HistoryDetail:
    session: HistorySession
    laps: tuple[HistoryLap, ...]


def _optional_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _require_schema4(connection) -> None:
    row = connection.execute(
        "SELECT schema_version FROM history_meta LIMIT 1"
    ).fetchone()
    version = int(row[0]) if row else None
    if version != EXPECTED_HISTORY_SCHEMA_VERSION:
        raise ValueError(
            "History incompatible: "
            f"schema esperado={EXPECTED_HISTORY_SCHEMA_VERSION}, encontrado={version}."
        )


def load_history_sessions(database_path: Path) -> list[HistorySession]:
    """Load schema-4 sessions without creating or modifying the database."""

    database = Path(database_path).resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = duckdb.connect(str(database), read_only=True)
    try:
        _require_schema4(connection)
        rows = connection.execute(
            """
            SELECT
                s.session_id,
                s.timestamp_utc,
                s.track,
                s.lmu_track_layout,
                s.session_type,
                s.vehicle_variant,
                s.car_name_raw,
                s.weather_conditions,
                s.reference_lap,
                reference.duration_s,
                s.valid_lap_count,
                s.comparison_count,
                s.source_json_path,
                s.source_database_path
            FROM sessions AS s
            LEFT JOIN laps AS reference
              ON reference.session_id = s.session_id
             AND reference.lap = s.reference_lap
            ORDER BY s.timestamp_utc DESC NULLS LAST, s.session_id DESC
            """
        ).fetchall()
    finally:
        connection.close()
    return [
        HistorySession(
            session_id=int(row[0]),
            timestamp_utc=str(row[1] or ""),
            track=str(row[2] or "Circuito no informado"),
            track_layout=str(row[3] or "—"),
            session_type=str(row[4] or "—"),
            vehicle_variant=str(row[5] or "—"),
            car_name=str(row[6] or "Vehículo no informado"),
            weather=str(row[7] or "—"),
            reference_lap=int(row[8]) if row[8] is not None else None,
            reference_time_s=float(row[9]) if row[9] is not None else None,
            valid_lap_count=int(row[10] or 0),
            comparison_count=int(row[11] or 0),
            source_json_path=_optional_path(row[12]),
            source_database_path=_optional_path(row[13]),
        )
        for row in rows
    ]


def filter_history_sessions(
    sessions: list[HistorySession], query: str
) -> list[HistorySession]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return list(sessions)
    result = []
    for session in sessions:
        haystack = " ".join(
            (
                str(session.session_id),
                session.timestamp_utc,
                session.track,
                session.track_layout,
                session.session_type,
                session.vehicle_variant,
                session.car_name,
                session.weather,
            )
        ).casefold()
        if all(term in haystack for term in terms):
            result.append(session)
    return result


def load_history_detail(database_path: Path, session: HistorySession) -> HistoryDetail:
    database = Path(database_path).resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = duckdb.connect(str(database), read_only=True)
    try:
        _require_schema4(connection)
        rows = connection.execute(
            """
            SELECT lap, duration_s, is_valid, is_reference,
                   is_discarded, is_ignored_initial
            FROM laps
            WHERE session_id = ?
            ORDER BY lap
            """,
            [session.session_id],
        ).fetchall()
    finally:
        connection.close()
    laps = tuple(
        HistoryLap(
            lap=int(row[0]),
            duration_s=float(row[1]) if row[1] is not None else None,
            is_valid=bool(row[2]),
            is_reference=bool(row[3]),
            is_discarded=bool(row[4]),
            is_ignored_initial=bool(row[5]),
        )
        for row in rows
    )
    return HistoryDetail(session=session, laps=laps)

