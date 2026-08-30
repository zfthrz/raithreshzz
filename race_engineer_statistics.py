from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class UsageSummary:
    session_count: int
    valid_lap_count: int
    total_distance_km: float
    favorite_track: str | None
    favorite_category: str | None
    favorite_car: str | None


@dataclass(frozen=True)
class MonthlyUsage:
    month: str
    summary: UsageSummary


@dataclass(frozen=True)
class SessionUsage:
    session_id: int
    timestamp: str
    month: str | None
    track: str
    category: str
    car: str
    valid_lap_count: int
    total_distance_km: float


@dataclass(frozen=True)
class DistributionItem:
    label: str
    valid_lap_count: int
    total_distance_km: float


@dataclass(frozen=True)
class HistoryStatistics:
    overall: UsageSummary
    monthly: tuple[MonthlyUsage, ...]
    sessions: tuple[SessionUsage, ...]
    track_distribution: tuple[DistributionItem, ...]
    category_distribution: tuple[DistributionItem, ...]
    car_distribution: tuple[DistributionItem, ...]


@dataclass(frozen=True)
class _LapUsage:
    session_id: int
    month: str | None
    track: str
    category: str
    car: str
    distance_km: float


def _month_key(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return f"{parsed.year:04d}-{parsed.month:02d}"


def _clean_label(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def car_display_name(
    vehicle_family: object,
    vehicle_variant: object,
    car_name_raw: object,
) -> str:
    family = str(vehicle_family or "").strip().upper()
    variant = str(vehicle_variant or "").strip().upper()
    if family == "LMP2" or variant in {"LMP2", "LMP2_WEC", "LMP2_ELMS"}:
        return "Oreca 07"
    return _clean_label(car_name_raw, "Auto no identificado")


def _favorite(rows: list[_LapUsage], field: str) -> str | None:
    counts: dict[str, int] = defaultdict(int)
    distances: dict[str, float] = defaultdict(float)
    for row in rows:
        label = getattr(row, field)
        counts[label] += 1
        distances[label] += row.distance_km
    if not counts:
        return None
    return min(
        counts,
        key=lambda label: (-counts[label], -distances[label], label.casefold()),
    )


def _distribution(rows: list[_LapUsage], field: str) -> tuple[DistributionItem, ...]:
    counts: dict[str, int] = defaultdict(int)
    distances: dict[str, float] = defaultdict(float)
    for row in rows:
        label = getattr(row, field)
        counts[label] += 1
        distances[label] += row.distance_km
    return tuple(
        DistributionItem(
            label=label,
            valid_lap_count=counts[label],
            total_distance_km=distances[label],
        )
        for label in sorted(
            counts,
            key=lambda item: (-counts[item], -distances[item], item.casefold()),
        )
    )


def _summarize(rows: list[_LapUsage], *, session_count: int | None = None) -> UsageSummary:
    sessions = {row.session_id for row in rows}
    return UsageSummary(
        session_count=len(sessions) if session_count is None else session_count,
        valid_lap_count=len(rows),
        total_distance_km=sum(row.distance_km for row in rows),
        favorite_track=_favorite(rows, "track"),
        favorite_category=_favorite(rows, "category"),
        favorite_car=_favorite(rows, "car"),
    )


def load_history_statistics(history_db: Path) -> HistoryStatistics:
    import duckdb

    database = Path(history_db)
    if not database.is_file():
        raise FileNotFoundError(f"History DB no encontrada: {database}")

    connection = duckdb.connect(str(database), read_only=True)
    try:
        total_sessions = int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        records = connection.execute(
            """
            SELECT
                s.session_id,
                s.timestamp_utc,
                s.track,
                s.vehicle_family,
                s.vehicle_variant,
                s.car_name_raw,
                l.lap,
                l.lap_distance_m
            FROM sessions AS s
            LEFT JOIN laps AS l
              ON s.session_id = l.session_id
             AND l.is_valid IS TRUE
            ORDER BY s.timestamp_utc DESC NULLS LAST, s.session_id DESC, l.lap
            """
        ).fetchall()
    finally:
        connection.close()

    rows: list[_LapUsage] = []
    session_rows: dict[int, dict] = {}
    for session_id, timestamp, track, family, variant, car_name, lap, distance_m in records:
        session_id = int(session_id)
        session = session_rows.setdefault(
            session_id,
            {
                "timestamp": str(timestamp or "").strip() or "Sin fecha",
                "month": _month_key(timestamp),
                "track": _clean_label(track, "Circuito no identificado"),
                "category": _clean_label(variant or family, "Categoría no identificada"),
                "car": car_display_name(family, variant, car_name),
                "valid_lap_count": 0,
                "total_distance_km": 0.0,
            },
        )
        if lap is None:
            continue
        try:
            distance_km = max(float(distance_m or 0.0), 0.0) / 1000.0
        except (TypeError, ValueError):
            distance_km = 0.0
        session["valid_lap_count"] += 1
        session["total_distance_km"] += distance_km
        rows.append(
            _LapUsage(
                session_id=session_id,
                month=_month_key(timestamp),
                track=_clean_label(track, "Circuito no identificado"),
                category=_clean_label(variant or family, "Categoría no identificada"),
                car=car_display_name(family, variant, car_name),
                distance_km=distance_km,
            )
        )

    by_month: dict[str, list[_LapUsage]] = defaultdict(list)
    for row in rows:
        by_month[row.month or "Sin fecha"].append(row)

    monthly = tuple(
        MonthlyUsage(month=month, summary=_summarize(by_month[month]))
        for month in sorted(
            by_month,
            key=lambda value: (value != "Sin fecha", value),
            reverse=True,
        )
    )
    sessions = tuple(
        SessionUsage(session_id=session_id, **values)
        for session_id, values in session_rows.items()
    )
    return HistoryStatistics(
        overall=_summarize(rows, session_count=total_sessions),
        monthly=monthly,
        sessions=sessions,
        track_distribution=_distribution(rows, "track"),
        category_distribution=_distribution(rows, "category"),
        car_distribution=_distribution(rows, "car"),
    )
