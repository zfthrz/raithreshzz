from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

from auto_ingest_telemetry import (
    PROJECT_ROOT,
    analysis_path_for_database,
    le_mans_ultimate_is_running,
    path_is_within,
    run_race_engineer,
    valid_lap_count,
)


LMU_TELEMETRY_DIR = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry"
)
LOCAL_TELEMETRY_DIR = PROJECT_ROOT / "telemetria"
MINIMUM_SIZE_MIB = 5.0
MINIMUM_VALID_LAPS = 2
MINIMUM_STABLE_SECONDS = 600


def allowed_roots() -> tuple[Path, ...]:
    return (LMU_TELEMETRY_DIR.resolve(), LOCAL_TELEMETRY_DIR.resolve())


def validate_selected_database(
    argument: str,
    *,
    roots: tuple[Path, ...] | None = None,
    min_size_mib: float = MINIMUM_SIZE_MIB,
    min_stable_seconds: int = MINIMUM_STABLE_SECONDS,
    now_seconds: float | None = None,
) -> Path:
    path = Path(argument).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.casefold() != ".duckdb":
        raise ValueError("El archivo seleccionado no es un DuckDB.")
    if "race_engineer_history" in path.name.casefold():
        raise ValueError("La base History no puede analizarse como telemetría.")
    authorized_roots = roots if roots is not None else allowed_roots()
    if not any(path_is_within(path, root) for root in authorized_roots):
        raise ValueError("El DuckDB está fuera de las carpetas de telemetría autorizadas.")

    stat = path.stat()
    minimum_bytes = int(min_size_mib * 1024 * 1024)
    if stat.st_size < minimum_bytes:
        raise ValueError(
            f"El DuckDB mide menos de {min_size_mib:g} MiB; no se autoriza LLM."
        )
    current_seconds = time.time() if now_seconds is None else now_seconds
    age_seconds = max(0.0, current_seconds - stat.st_mtime)
    if age_seconds < min_stable_seconds:
        remaining = min_stable_seconds - age_seconds
        raise ValueError(
            "El DuckDB todavía no cumplió la espera de estabilidad; "
            f"faltan aproximadamente {remaining:.0f} s."
        )
    return path


def analyze_selected_file(
    argument: str,
    *,
    backend: str,
    roots: tuple[Path, ...] | None = None,
    runner: Callable[[Path, list[str]], None] = run_race_engineer,
    lap_counter: Callable[[Path], int] = valid_lap_count,
    game_running: Callable[[], bool] = le_mans_ultimate_is_running,
    min_size_mib: float = MINIMUM_SIZE_MIB,
    min_valid_laps: int = MINIMUM_VALID_LAPS,
    min_stable_seconds: int = MINIMUM_STABLE_SECONDS,
    now_seconds: float | None = None,
) -> int:
    print("=" * 72)
    print("RACE ENGINEER - SAFE TELEMETRY LAUNCHER v0.1")
    print("=" * 72)
    if game_running():
        print("BLOCKED: Le Mans Ultimate está abierto.")
        print("Cerrá el juego y esperá 10 minutos antes de analizar.")
        return 2

    try:
        database = validate_selected_database(
            argument,
            roots=roots,
            min_size_mib=min_size_mib,
            min_stable_seconds=min_stable_seconds,
            now_seconds=now_seconds,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"BLOCKED: {exc}")
        return 2

    print(f"Archivo: {database}")
    print("Etapa 1/2: análisis determinista + History, sin LLM.")
    try:
        runner(database, ["--no-llm", "--no-historical-context"])
    except Exception as exc:
        print(f"FAILED: etapa determinista/History: {type(exc).__name__}: {exc}")
        return 1

    try:
        laps = lap_counter(database)
    except Exception as exc:
        analysis_path = analysis_path_for_database(database)
        print(f"FAILED: no se pudo leer {analysis_path}: {type(exc).__name__}: {exc}")
        return 1
    print(f"Vueltas válidas confirmadas por Python: {laps}")
    if laps < min_valid_laps:
        print(
            f"BLOCKED_LLM: se requieren al menos {min_valid_laps} vueltas válidas."
        )
        print("La evidencia determinista puede permanecer en History; no se llamó al LLM.")
        return 2

    print(f"Etapa 2/2: pipeline completo con backend {backend}.")
    try:
        runner(database, ["--backend", backend])
    except Exception as exc:
        print(f"FAILED: pipeline LLM: {type(exc).__name__}: {exc}")
        return 1

    print("RESULT: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launcher seguro para analizar un DuckDB desde Windows Explorer."
    )
    parser.add_argument("database")
    parser.add_argument(
        "--backend",
        choices=("deepseek", "ollama"),
        default="deepseek",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return analyze_selected_file(args.database, backend=args.backend)


if __name__ == "__main__":
    raise SystemExit(main())
