from __future__ import annotations

import argparse
import inspect
import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any

PROBE_VERSION = "0.1"


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def norm_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def public_methods(cls: type) -> list[dict[str, Any]]:
    rows = []
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        attr = getattr(cls, name, None)
        if not callable(attr):
            continue
        try:
            sig = str(inspect.signature(attr))
        except (TypeError, ValueError):
            sig = "<signature unavailable>"
        rows.append({"name": name, "signature": sig})
    return rows


def source_snippet(obj: Any, max_lines: int = 160) -> dict[str, Any]:
    try:
        source = inspect.getsource(obj)
        lines = source.splitlines()
        return {
            "available": True,
            "line_count": len(lines),
            "snippet": "\n".join(lines[:max_lines]),
            "truncated": len(lines) > max_lines,
        }
    except (OSError, TypeError):
        return {
            "available": False,
            "line_count": None,
            "snippet": None,
            "truncated": False,
        }


def basename_any(path_text: str | None) -> str | None:
    text = norm_text(path_text)
    if text is None:
        return None
    # Works for both Windows paths persisted from local analysis and POSIX paths.
    if "\\" in text:
        return PureWindowsPath(text).name
    return Path(text).name


def resolve_duckdb(
    telemetry_dir: Path,
    source_database_path: str | None,
    source_json_path: str | None,
) -> tuple[Path | None, list[str]]:
    attempted: list[str] = []

    db_base = basename_any(source_database_path)
    if db_base:
        candidate = telemetry_dir / db_base
        attempted.append(str(candidate))
        if candidate.is_file():
            return candidate.resolve(), attempted

    json_base = basename_any(source_json_path)
    if json_base:
        candidate = telemetry_dir / (Path(json_base).stem + ".duckdb")
        attempted.append(str(candidate))
        if candidate.is_file():
            return candidate.resolve(), attempted

    # Last deterministic fallback: if source_json_path is a full persisted path and the
    # sibling .duckdb exists in this environment, accept it.
    source_json = norm_text(source_json_path)
    if source_json and "\\" not in source_json:
        candidate = Path(source_json).with_suffix(".duckdb")
        attempted.append(str(candidate))
        if candidate.is_file():
            return candidate.resolve(), attempted

    return None, attempted


def load_dual(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("dual_reference_context inválido.")
    return data


def history_session_row(connection, session_id: int) -> dict[str, Any]:
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
        raise ValueError(f"No existe session_id={session_id} en History.")
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


def lap_summary_for(lap_analyzer: Any, lap: int) -> dict[str, Any] | None:
    rows = lap_analyzer.all_lap_summaries()
    try:
        import pandas as pd
        if isinstance(rows, list):
            df = pd.DataFrame(rows)
        else:
            df = rows.copy()
        if "lap" not in df.columns:
            return None
        selected = df[df["lap"] == lap]
        if len(selected) != 1:
            return None
        row = selected.iloc[0]
        result = {}
        for key, value in row.to_dict().items():
            if hasattr(value, "item"):
                try:
                    value = value.item()
                except Exception:
                    pass
            result[str(key)] = value
        return result
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def instance_shape(obj: Any) -> dict[str, str]:
    result = {}
    try:
        attrs = vars(obj)
    except TypeError:
        return result
    for name, value in sorted(attrs.items()):
        if name.startswith("__"):
            continue
        result[name] = type(value).__name__
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="H5.2 probe: inspecciona interfaces reales para comparación cross-session."
    )
    ap.add_argument("dual_reference_json")
    ap.add_argument("--history-db", default="race_engineer_history.duckdb")
    ap.add_argument("--telemetry-dir", default="telemetria")
    ap.add_argument("--output", default="cross_session_interface_probe.json")
    args = ap.parse_args()

    dual_path = Path(args.dual_reference_json).resolve()
    history_path = Path(args.history_db).resolve()
    telemetry_dir = Path(args.telemetry_dir).resolve()
    output_path = Path(args.output).resolve()

    if not history_path.is_file():
        raise FileNotFoundError(f"History DB no existe: {history_path}")
    if not telemetry_dir.is_dir():
        raise FileNotFoundError(f"telemetria/ no existe: {telemetry_dir}")

    dual = load_dual(dual_path)
    target = dual.get("target_session") or {}
    session_ref = dual.get("session_reference") or {}
    historical_ref = dual.get("historical_reference")

    target_session_id = safe_int(target.get("session_id"))
    target_lap = safe_int(session_ref.get("lap"))
    if target_session_id is None or target_lap is None:
        raise ValueError("Dual context no tiene target session/reference completos.")

    if not isinstance(historical_ref, dict):
        raise ValueError(
            "Dual context no tiene historical_reference. H5.2 no corresponde para este target."
        )
    historical_session_id = safe_int(historical_ref.get("session_id"))
    historical_lap = safe_int(historical_ref.get("lap"))
    if historical_session_id is None or historical_lap is None:
        raise ValueError("Historical reference incompleta.")

    try:
        import duckdb
        from telemetry import Telemetry
        from laps import LapAnalyzer
        from delta_comparison import DeltaComparison
        from sector_analysis import SectorAnalysis
    except Exception as exc:
        raise RuntimeError(
            f"No se pudieron importar módulos core: {type(exc).__name__}: {exc}"
        ) from exc

    con = duckdb.connect(str(history_path), read_only=True)
    try:
        current_history = history_session_row(con, target_session_id)
        historical_history = history_session_row(con, historical_session_id)
    finally:
        con.close()

    current_db, current_attempted = resolve_duckdb(
        telemetry_dir,
        current_history.get("source_database_path"),
        current_history.get("source_json_path"),
    )
    historical_db, historical_attempted = resolve_duckdb(
        telemetry_dir,
        historical_history.get("source_database_path"),
        historical_history.get("source_json_path"),
    )

    if current_db is None:
        raise FileNotFoundError(
            "No pude resolver DuckDB actual. Intentados: " + ", ".join(current_attempted)
        )
    if historical_db is None:
        raise FileNotFoundError(
            "No pude resolver DuckDB histórico. Intentados: " + ", ".join(historical_attempted)
        )

    # Hard context consistency from History before opening raw telemetry.
    context_keys = ("track", "vehicle_variant", "car_name_raw", "lmu_track_layout")
    context_mismatches = []
    for key in context_keys:
        if norm_text(current_history.get(key)) != norm_text(historical_history.get(key)):
            context_mismatches.append(
                {
                    "field": key,
                    "current": current_history.get(key),
                    "historical": historical_history.get(key),
                }
            )
    if context_mismatches:
        raise ValueError(f"History context mismatch: {context_mismatches}")

    current_tel = Telemetry(str(current_db))
    historical_tel = Telemetry(str(historical_db))
    try:
        current_laps = LapAnalyzer(current_tel)
        historical_laps = LapAnalyzer(historical_tel)

        current_summary = lap_summary_for(current_laps, target_lap)
        historical_summary = lap_summary_for(historical_laps, historical_lap)

        report = {
            "metadata": {
                "probe_version": PROBE_VERSION,
                "dual_reference_json": str(dual_path),
                "history_db": str(history_path),
                "telemetry_dir": str(telemetry_dir),
            },
            "selection": {
                "current": {
                    "session_id": target_session_id,
                    "lap": target_lap,
                    "history": current_history,
                    "resolved_duckdb": str(current_db),
                    "resolution_attempts": current_attempted,
                    "lap_summary": current_summary,
                },
                "historical": {
                    "session_id": historical_session_id,
                    "lap": historical_lap,
                    "history": historical_history,
                    "resolved_duckdb": str(historical_db),
                    "resolution_attempts": historical_attempted,
                    "lap_summary": historical_summary,
                },
            },
            "context_mismatches": context_mismatches,
            "modules": {
                "telemetry": {
                    "module_file": inspect.getsourcefile(Telemetry),
                    "class_signature": str(inspect.signature(Telemetry)),
                    "public_methods": public_methods(Telemetry),
                    "instance_attributes": instance_shape(current_tel),
                },
                "laps": {
                    "module_file": inspect.getsourcefile(LapAnalyzer),
                    "class_signature": str(inspect.signature(LapAnalyzer)),
                    "public_methods": public_methods(LapAnalyzer),
                    "instance_attributes": instance_shape(current_laps),
                    "class_source": source_snippet(LapAnalyzer, max_lines=220),
                },
                "delta_comparison": {
                    "module_file": inspect.getsourcefile(DeltaComparison),
                    "class_signature": str(inspect.signature(DeltaComparison)),
                    "public_methods": public_methods(DeltaComparison),
                    "class_source": source_snippet(DeltaComparison, max_lines=260),
                },
                "sector_analysis": {
                    "module_file": inspect.getsourcefile(SectorAnalysis),
                    "class_signature": str(inspect.signature(SectorAnalysis)),
                    "public_methods": public_methods(SectorAnalysis),
                },
            },
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

        print("=" * 88)
        print(f"RACE ENGINEER - H5.2 CROSS-SESSION INTERFACE PROBE v{PROBE_VERSION}")
        print("=" * 88)
        print(
            f"Current:    session={target_session_id} lap={target_lap} "
            f"db={current_db.name}"
        )
        print(
            f"Historical: session={historical_session_id} lap={historical_lap} "
            f"db={historical_db.name}"
        )
        print(f"Context mismatches: {len(context_mismatches)}")
        print()
        print("SELECTED LAP SUMMARIES")
        print(f"  current:    {current_summary}")
        print(f"  historical: {historical_summary}")
        print()
        print("LAP ANALYZER PUBLIC METHODS")
        for row in report["modules"]["laps"]["public_methods"]:
            print(f"  {row['name']}{row['signature']}")
        print()
        print("DELTA COMPARISON PUBLIC METHODS")
        for row in report["modules"]["delta_comparison"]["public_methods"]:
            print(f"  {row['name']}{row['signature']}")
        print()
        print("INSTANCE ATTRIBUTES")
        print(f"  Telemetry:   {report['modules']['telemetry']['instance_attributes']}")
        print(f"  LapAnalyzer: {report['modules']['laps']['instance_attributes']}")
        print()
        print(f"Full report: {output_path}")
        print("RESULT: PASS")
        return 0
    finally:
        current_tel.close()
        historical_tel.close()


if __name__ == "__main__":
    raise SystemExit(main())
