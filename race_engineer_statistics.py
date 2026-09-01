from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from runtime_paths import history_db_default_path


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


HISTORY_STATISTICS_SCHEMA_VERSION = 1


def _usage_summary_payload(summary: UsageSummary) -> dict:
    return {
        "session_count": int(summary.session_count),
        "valid_lap_count": int(summary.valid_lap_count),
        "total_distance_km": round(summary.total_distance_km, 3),
        "favorite_track": summary.favorite_track,
        "favorite_category": summary.favorite_category,
        "favorite_car": summary.favorite_car,
    }


def _monthly_payload(item: MonthlyUsage) -> dict:
    return {
        "month": item.month,
        "summary": _usage_summary_payload(item.summary),
    }


def _session_payload(item: SessionUsage) -> dict:
    return {
        "session_id": int(item.session_id),
        "timestamp": item.timestamp,
        "month": item.month,
        "track": item.track,
        "category": item.category,
        "car": item.car,
        "valid_lap_count": int(item.valid_lap_count),
        "total_distance_km": round(item.total_distance_km, 3),
    }


def _distribution_payload(item: DistributionItem) -> dict:
    return {
        "label": item.label,
        "valid_lap_count": int(item.valid_lap_count),
        "total_distance_km": round(item.total_distance_km, 3),
    }


def history_statistics_document(
    history: HistoryStatistics,
    *,
    generated_from: str,
) -> dict:
    return {
        "schema_version": HISTORY_STATISTICS_SCHEMA_VERSION,
        "generated_from": generated_from,
        "overall": _usage_summary_payload(history.overall),
        "monthly": [_monthly_payload(item) for item in history.monthly],
        "sessions": [_session_payload(item) for item in history.sessions],
        "track_distribution": [
            _distribution_payload(item) for item in history.track_distribution
        ],
        "category_distribution": [
            _distribution_payload(item) for item in history.category_distribution
        ],
        "car_distribution": [
            _distribution_payload(item) for item in history.car_distribution
        ],
    }


def _statistics_error_message(database: Path) -> None:
    print(f"ERROR: no se pudo leer la History DB ({database})", file=sys.stderr)


def _effective_file_path(path: Path) -> Path:
    # Absolute, sin segmentos relativos, . o ..: compara el archivo real.
    return path.resolve()


def _normalized_path_key(path: Path) -> str:
    # Ruta resuelta pasada por normcase: compara sin distinguir mayúsculas
    # en sistemas case-insensitive (Windows) y preserva la resolución.
    return os.path.normcase(str(_effective_file_path(path)))


def _is_same_file_destination(database: Path, output: Path) -> bool:
    # Decide si database y output apuntan al mismo archivo (misma ruta,
    # alias de case, o segmentos . / ..).
    # Fail closed únicamente ante identidad confirmada.
    if database.exists() and output.exists():
        try:
            if os.path.samefile(str(database), str(output)):
                return True
        except OSError:
            pass
    return _normalized_path_key(database) == _normalized_path_key(output)


def _refuse_same_file_output(database: Path, output: str) -> bool:
    output_path = Path(output)
    if _is_same_file_destination(database, output_path):
        print(
            f"ERROR: --output no puede ser la propia History DB ({output_path})",
            file=sys.stderr,
        )
        return True
    return False


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exporta de forma read-only las estadísticas de History a un JSON determinista.",
    )
    parser.add_argument(
        "--history-db",
        default=None,
        help="Ruta de la History DB DuckDB. Si se omite, se usa history_db_default_path().",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Ruta del JSON de salida que se creará. Con el valor '-' se escribe a stdout.",
    )
    args = parser.parse_args(argv)

    database = Path(args.history_db) if args.history_db else history_db_default_path()
    if args.output != "-" and _refuse_same_file_output(database, args.output):
        return 1
    try:
        statistics = load_history_statistics(database)
    except Exception as exc:  # noqa: BLE001 - el mensaje de stderr debe ser claro
        _statistics_error_message(database)
        print(f"Detalle: {exc}", file=sys.stderr)
        return 1

    payload = (
        json.dumps(
            history_statistics_document(statistics, generated_from=str(database)),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    if args.output == "-":
        print(payload, end="")
        return 0
    output_path = Path(args.output)
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(output_path)
    except OSError as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        print(f"ERROR: no se pudo escribir {output_path}", file=sys.stderr)
        print(f"Detalle: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
