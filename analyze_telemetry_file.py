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
    skip_stability_wait: bool = False,
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
            f"El DuckDB mide menos de {min_size_mib:g} MiB; no se autoriza el análisis."
        )
    current_seconds = time.time() if now_seconds is None else now_seconds
    age_seconds = max(0.0, current_seconds - stat.st_mtime)
    if not skip_stability_wait and age_seconds < min_stable_seconds:
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
    skip_stability_wait: bool = False,
    deterministic_debrief: bool = False,
) -> int:
    print("=" * 72)
    print("RACE ENGINEER - SAFE TELEMETRY LAUNCHER v0.2")
    print("=" * 72)
    if game_running():
        print("BLOCKED: Le Mans Ultimate está abierto.")
        if skip_stability_wait:
            print("Cerrá el juego; el override no omite este bloqueo.")
        else:
            print("Cerrá el juego y esperá 10 minutos antes de analizar.")
        return 2

    if skip_stability_wait:
        print("WARNING: override explícito de espera de estabilidad activado.")

    try:
        database = validate_selected_database(
            argument,
            roots=roots,
            min_size_mib=min_size_mib,
            min_stable_seconds=min_stable_seconds,
            now_seconds=now_seconds,
            skip_stability_wait=skip_stability_wait,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"BLOCKED: {exc}")
        return 2

    print(f"Archivo: {database}")
    print("Etapa 1/2: análisis determinista + History, sin LLM.")
    try:
        runner(database, ["--no-llm"])
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
        blocked_stage = "DEBRIEF" if deterministic_debrief else "LLM"
        print(
            f"BLOCKED_{blocked_stage}: se requieren al menos "
            f"{min_valid_laps} vueltas válidas."
        )
        print("La evidencia determinista puede permanecer en History.")
        return 2

    if deterministic_debrief:
        print("Etapa 2/2: debrief determinista, sin acceso a LLM.")
        final_args = [
            "--backend",
            "deepseek",
            "--force-deterministic-debrief",
        ]
    else:
        print(f"Etapa 2/2: pipeline completo con backend {backend}.")
        final_args = ["--backend", backend]
    try:
        runner(database, final_args)
    except Exception as exc:
        stage = "debrief determinista" if deterministic_debrief else "pipeline LLM"
        print(f"FAILED: {stage}: {type(exc).__name__}: {exc}")
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
        choices=("deepseek", "ollama", "llamacpp"),
        default="deepseek",
    )
    parser.add_argument(
        "--skip-stability-wait",
        action="store_true",
        help=(
            "omite sólo la espera de 10 minutos; LMU cerrado, tamaño y vueltas "
            "válidas siguen siendo obligatorios"
        ),
    )
    parser.add_argument(
        "--deterministic-debrief",
        action="store_true",
        help="genera el debrief validado sin acceso a un backend LLM",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return analyze_selected_file(
        args.database,
        backend=args.backend,
        skip_stability_wait=args.skip_stability_wait,
        deterministic_debrief=args.deterministic_debrief,
    )


if __name__ == "__main__":
    raise SystemExit(main())
