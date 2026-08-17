from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_TELEMETRY_DIR = PROJECT_ROOT / "telemetria"
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "local" / "telemetry_auto_ingest.json"
STATE_VERSION = "0.1"

STATUS_BASELINED = "BASELINED"
STATUS_BASELINE_SKIPPED_SMALL = "BASELINE_SKIPPED_SMALL"
STATUS_BACKFILL_FAILED = "BACKFILL_FAILED"
STATUS_PENDING_STABILITY = "PENDING_STABILITY"
STATUS_HISTORY_READY = "HISTORY_READY"
STATUS_DEBRIEF_READY = "DEBRIEF_READY"
STATUS_HISTORY_ONLY_INELIGIBLE = "HISTORY_ONLY_INELIGIBLE"
STATUS_HISTORY_ONLY_SUPERSEDED = "HISTORY_ONLY_SUPERSEDED"
STATUS_FAILED = "FAILED"
STATUS_CHANGED_REVIEW_REQUIRED = "CHANGED_REVIEW_REQUIRED"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def resolve_path(value: str | None, default: Path) -> Path:
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def analysis_path_for_database(path: Path) -> Path:
    configured = os.environ.get("RACE_ENGINEER_GENERATED_DIR")
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            root = PROJECT_ROOT / root
    else:
        root = PROJECT_ROOT / "data" / "generated"
    return root.resolve() / "analysis" / f"{path.stem}.json"


def existing_pipeline_status(path: Path) -> tuple[str, int] | None:
    configured = os.environ.get("RACE_ENGINEER_GENERATED_DIR")
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            root = PROJECT_ROOT / root
    else:
        root = PROJECT_ROOT / "data" / "generated"
    state_path = root.resolve() / "runs" / path.stem / "state.json"
    if not state_path.is_file():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    stored_database = payload.get("database")
    if not isinstance(stored_database, str):
        return None
    try:
        if Path(stored_database).resolve() != path.resolve():
            return None
    except OSError:
        return None
    stages = payload.get("stages")
    if not isinstance(stages, dict):
        return None
    history = stages.get("history")
    details = history.get("details") if isinstance(history, dict) else None
    session_id = details.get("session_id") if isinstance(details, dict) else None
    if not isinstance(session_id, int):
        return None
    validator = stages.get("llm_validator")
    validator_status = validator.get("status") if isinstance(validator, dict) else None
    status = (
        STATUS_DEBRIEF_READY
        if validator_status in {"RUN", "REUSED"}
        else STATUS_HISTORY_READY
    )
    return status, session_id


def valid_lap_count(path: Path) -> int:
    analysis_path = analysis_path_for_database(path)
    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    valid_laps = metadata.get("valid_laps") if isinstance(metadata, dict) else None
    if not isinstance(valid_laps, list):
        raise ValueError(f"Falta metadata.valid_laps en {analysis_path}")
    return len(valid_laps)


def empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "files": {}}


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return empty_state()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        raise ValueError(f"Estado inválido: {path}")
    payload["version"] = STATE_VERSION
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["version"] = STATE_VERSION
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def discover(telemetry_dir: Path) -> list[Path]:
    if not telemetry_dir.is_dir():
        raise FileNotFoundError(f"No existe el directorio de telemetría: {telemetry_dir}")
    return sorted(
        (path.resolve() for path in telemetry_dir.rglob("*.duckdb") if path.is_file()),
        key=lambda path: str(path).casefold(),
    )


def probe_duckdb(path: Path) -> None:
    import duckdb

    connection = duckdb.connect(str(path), read_only=True)
    try:
        connection.execute("SELECT 1").fetchone()
    finally:
        connection.close()


def run_race_engineer(path: Path, extra_args: list[str]) -> None:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "race_engineer.py"),
        "analyze",
        str(path),
        *extra_args,
    ]
    print("+ " + subprocess.list2cmdline(command))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def baseline(telemetry_dir: Path, state_path: Path, *, now: datetime) -> int:
    state = load_state(state_path)
    added = 0
    for path in discover(telemetry_dir):
        key = str(path)
        if key in state["files"]:
            continue
        stamp = isoformat(now)
        state["files"][key] = {
            "status": STATUS_BASELINED,
            "signature": signature(path),
            "first_seen_at": stamp,
            "stable_since": stamp,
            "updated_at": stamp,
        }
        added += 1
    save_state(state_path, state)
    print(f"BASELINE: {added} archivo(s) registrado(s), 0 analizados.")
    print(f"Estado: {state_path}")
    return 0


def scan(
    telemetry_dir: Path,
    state_path: Path,
    *,
    settle_seconds: int,
    now: datetime,
    runner: Callable[[Path, list[str]], None] = run_race_engineer,
    probe: Callable[[Path], None] = probe_duckdb,
) -> int:
    state = load_state(state_path)
    stamp = isoformat(now)
    discovered = discover(telemetry_dir)
    history_ready = 0
    pending = 0
    failed = 0

    for path in discovered:
        key = str(path)
        current_signature = signature(path)
        entry = state["files"].get(key)

        if entry is None:
            entry = {
                "status": STATUS_PENDING_STABILITY,
                "signature": current_signature,
                "first_seen_at": stamp,
                "stable_since": stamp,
                "updated_at": stamp,
            }
            state["files"][key] = entry
        elif entry.get("signature") != current_signature:
            previous_status = entry.get("status")
            entry.update({
                "signature": current_signature,
                "stable_since": stamp,
                "updated_at": stamp,
            })
            if previous_status in {
                STATUS_HISTORY_READY,
                STATUS_DEBRIEF_READY,
                STATUS_BASELINE_SKIPPED_SMALL,
                STATUS_BACKFILL_FAILED,
            }:
                entry["status"] = STATUS_CHANGED_REVIEW_REQUIRED
                entry["last_error"] = (
                    "El archivo cambió después de ser importado; no se reprocesó automáticamente."
                )
            else:
                entry["status"] = STATUS_PENDING_STABILITY
                entry.pop("last_error", None)

        status = entry.get("status")
        if status in {
            STATUS_BASELINED,
            STATUS_BASELINE_SKIPPED_SMALL,
            STATUS_BACKFILL_FAILED,
            STATUS_HISTORY_READY,
            STATUS_DEBRIEF_READY,
            STATUS_CHANGED_REVIEW_REQUIRED,
        }:
            continue

        stable_since = parse_time(entry["stable_since"])
        stable_for = max(0.0, (now - stable_since).total_seconds())
        if stable_for < settle_seconds:
            entry["status"] = STATUS_PENDING_STABILITY
            pending += 1
            continue

        try:
            probe(path)
            runner(path, ["--no-llm", "--no-historical-context"])
        except Exception as exc:
            entry["status"] = STATUS_FAILED
            entry["last_error"] = f"{type(exc).__name__}: {exc}"
            entry["updated_at"] = stamp
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
            failed += 1
            save_state(state_path, state)
            continue

        entry["status"] = STATUS_HISTORY_READY
        entry["history_ready_at"] = stamp
        entry["updated_at"] = stamp
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry.pop("last_error", None)
        history_ready += 1
        save_state(state_path, state)

    save_state(state_path, state)
    state["last_scan"] = {
        "at": stamp,
        "discovered": len(discovered),
        "history_ready": history_ready,
        "pending": pending,
        "failed": failed,
    }
    save_state(state_path, state)
    print(
        "SCAN: "
        f"{len(discovered)} encontrados | {history_ready} importados a History | "
        f"{pending} esperando estabilidad | {failed} fallidos"
    )
    print(f"Estado: {state_path}")
    return 1 if failed else 0


def backfill_next(
    state_path: Path,
    *,
    min_size_mb: float,
    now: datetime,
    runner: Callable[[Path, list[str]], None] = run_race_engineer,
    probe: Callable[[Path], None] = probe_duckdb,
    pipeline_status_reader: Callable[
        [Path], tuple[str, int] | None
    ] = existing_pipeline_status,
) -> int:
    state = load_state(state_path)
    minimum_bytes = int(min_size_mb * 1024 * 1024)
    candidates: list[tuple[Path, dict[str, Any]]] = []
    skipped_small = 0
    reconciled = 0

    for path_text, entry in state["files"].items():
        current_status = entry.get("status")
        if current_status in {STATUS_BASELINED, STATUS_HISTORY_READY}:
            existing = pipeline_status_reader(Path(path_text))
            if existing is not None:
                existing_status, session_id = existing
                if current_status != existing_status:
                    reconciled += 1
                entry["status"] = existing_status
                entry["reconciled_session_id"] = session_id
                entry["reconciled_at"] = isoformat(now)
                continue
        if current_status != STATUS_BASELINED:
            continue
        size = int((entry.get("signature") or {}).get("size", 0))
        if size < minimum_bytes:
            entry["status"] = STATUS_BASELINE_SKIPPED_SMALL
            entry["backfill_eligibility"] = {
                "eligible": False,
                "size_bytes": size,
                "minimum_size_bytes": minimum_bytes,
                "reason": "archivo menor al tamaño mínimo",
            }
            skipped_small += 1
            continue
        entry["backfill_eligibility"] = {
            "eligible": True,
            "size_bytes": size,
            "minimum_size_bytes": minimum_bytes,
        }
        candidates.append((Path(path_text), entry))

    save_state(state_path, state)
    if not candidates:
        print(
            "BACKFILL: no hay archivos históricos elegibles pendientes "
            f"| reconciliados: {reconciled} "
            f"| pequeños excluidos ahora: {skipped_small}"
        )
        return 0

    candidates.sort(
        key=lambda item: (
            int((item[1].get("signature") or {}).get("mtime_ns", 0)),
            str(item[0]).casefold(),
        ),
        reverse=True,
    )
    selected_path, selected_entry = candidates[0]
    stamp = isoformat(now)
    try:
        if not selected_path.is_file():
            raise FileNotFoundError(selected_path)
        probe(selected_path)
        runner(selected_path, ["--no-llm", "--no-historical-context"])
    except Exception as exc:
        selected_entry["status"] = STATUS_BACKFILL_FAILED
        selected_entry["last_error"] = f"{type(exc).__name__}: {exc}"
        selected_entry["backfill_attempts"] = int(
            selected_entry.get("backfill_attempts", 0)
        ) + 1
        selected_entry["updated_at"] = stamp
        save_state(state_path, state)
        print(f"BACKFILL: FAILED — {selected_path.name}")
        print("No se procesarán más archivos hasta la próxima ejecución manual.")
        return 1

    selected_entry["status"] = STATUS_HISTORY_READY
    selected_entry["history_ready_at"] = stamp
    selected_entry["updated_at"] = stamp
    selected_entry["backfill_attempts"] = int(
        selected_entry.get("backfill_attempts", 0)
    ) + 1
    selected_entry.pop("last_error", None)
    state["last_backfill_at"] = stamp
    save_state(state_path, state)
    print(f"BACKFILL: PASS — {selected_path.name}")
    print(f"Pendientes elegibles restantes: {len(candidates) - 1}")
    print(f"Sesiones existentes reconciliadas: {reconciled}")
    print(f"Pequeños excluidos ahora: {skipped_small}")
    return 0


def maintenance(
    telemetry_dir: Path,
    state_path: Path,
    *,
    settle_seconds: int,
    min_size_mb: float,
    backfill_minutes: int,
    now: datetime,
    runner: Callable[[Path, list[str]], None] = run_race_engineer,
    probe: Callable[[Path], None] = probe_duckdb,
    pipeline_status_reader: Callable[
        [Path], tuple[str, int] | None
    ] = existing_pipeline_status,
) -> int:
    scan_result = scan(
        telemetry_dir,
        state_path,
        settle_seconds=settle_seconds,
        now=now,
        runner=runner,
        probe=probe,
    )
    if scan_result != 0:
        print("MAINTENANCE: backfill omitido porque el escaneo tuvo fallos.")
        return scan_result

    state = load_state(state_path)
    summary = state.get("last_scan") or {}
    if any(int(summary.get(name, 0)) > 0 for name in ("history_ready", "pending")):
        print("MAINTENANCE: prioridad para telemetría nueva; backfill omitido.")
        return 0

    last_backfill = state.get("last_backfill_at")
    if isinstance(last_backfill, str):
        elapsed_minutes = max(
            0.0,
            (now - parse_time(last_backfill)).total_seconds() / 60.0,
        )
        if elapsed_minutes < backfill_minutes:
            remaining = backfill_minutes - elapsed_minutes
            print(f"MAINTENANCE: próximo backfill en aproximadamente {remaining:.1f} min.")
            return 0

    return backfill_next(
        state_path,
        min_size_mb=min_size_mb,
        now=now,
        runner=runner,
        probe=probe,
        pipeline_status_reader=pipeline_status_reader,
    )


def debrief_next(
    state_path: Path,
    *,
    backend: str,
    now: datetime,
    runner: Callable[[Path, list[str]], None] = run_race_engineer,
) -> int:
    state = load_state(state_path)
    candidates = [
        (path, entry)
        for path, entry in state["files"].items()
        if entry.get("status") == STATUS_HISTORY_READY
    ]
    candidates.sort(key=lambda item: item[1].get("history_ready_at", ""))
    if not candidates:
        print("DEBRIEF: no hay sesiones pendientes.")
        return 0

    path_text, entry = candidates[0]
    path = Path(path_text)
    try:
        runner(path, ["--backend", backend])
    except Exception as exc:
        entry["last_debrief_error"] = f"{type(exc).__name__}: {exc}"
        entry["debrief_attempts"] = int(entry.get("debrief_attempts", 0)) + 1
        entry["updated_at"] = isoformat(now)
        save_state(state_path, state)
        print("DEBRIEF: falló; la sesión permanece guardada en History y pendiente.")
        return 1

    entry["status"] = STATUS_DEBRIEF_READY
    entry["debrief_ready_at"] = isoformat(now)
    entry["updated_at"] = isoformat(now)
    entry["debrief_backend"] = backend
    entry["debrief_attempts"] = int(entry.get("debrief_attempts", 0)) + 1
    entry.pop("last_debrief_error", None)
    save_state(state_path, state)
    print(f"DEBRIEF: PASS — {path.name}")
    print("Se procesó una sola sesión.")
    return 0


def debrief_latest(
    state_path: Path,
    *,
    backend: str,
    min_size_mb: float,
    min_valid_laps: int,
    now: datetime,
    runner: Callable[[Path, list[str]], None] = run_race_engineer,
    lap_counter: Callable[[Path], int] = valid_lap_count,
) -> int:
    state = load_state(state_path)
    minimum_bytes = int(min_size_mb * 1024 * 1024)
    eligible: list[tuple[Path, dict[str, Any]]] = []

    for path_text, entry in state["files"].items():
        if entry.get("status") != STATUS_HISTORY_READY:
            continue
        path = Path(path_text)
        size = int((entry.get("signature") or {}).get("size", 0))
        try:
            laps = lap_counter(path)
        except Exception as exc:
            entry["status"] = STATUS_HISTORY_ONLY_INELIGIBLE
            entry["debrief_eligibility"] = {
                "eligible": False,
                "reason": f"No se pudo verificar valid_laps: {type(exc).__name__}: {exc}",
            }
            continue
        entry["debrief_eligibility"] = {
            "size_bytes": size,
            "valid_laps": laps,
            "minimum_size_bytes": minimum_bytes,
            "minimum_valid_laps": min_valid_laps,
        }
        if size < minimum_bytes or laps < min_valid_laps:
            reasons = []
            if size < minimum_bytes:
                reasons.append("archivo menor al tamaño mínimo")
            if laps < min_valid_laps:
                reasons.append("vueltas válidas insuficientes")
            entry["status"] = STATUS_HISTORY_ONLY_INELIGIBLE
            entry["debrief_eligibility"].update({
                "eligible": False,
                "reason": "; ".join(reasons),
            })
            continue
        entry["debrief_eligibility"]["eligible"] = True
        eligible.append((path, entry))

    save_state(state_path, state)
    if not eligible:
        print("DEBRIEF LATEST: no hay sesiones nuevas elegibles.")
        return 0

    eligible.sort(
        key=lambda item: (
            int((item[1].get("signature") or {}).get("mtime_ns", 0)),
            str(item[0]).casefold(),
        ),
        reverse=True,
    )
    selected_path, selected_entry = eligible[0]
    try:
        runner(selected_path, ["--backend", backend])
    except Exception as exc:
        selected_entry["last_debrief_error"] = f"{type(exc).__name__}: {exc}"
        selected_entry["debrief_attempts"] = int(
            selected_entry.get("debrief_attempts", 0)
        ) + 1
        selected_entry["updated_at"] = isoformat(now)
        save_state(state_path, state)
        print("DEBRIEF LATEST: falló; History permanece guardado para reintentar.")
        return 1

    stamp = isoformat(now)
    selected_entry["status"] = STATUS_DEBRIEF_READY
    selected_entry["debrief_ready_at"] = stamp
    selected_entry["updated_at"] = stamp
    selected_entry["debrief_backend"] = backend
    selected_entry["debrief_attempts"] = int(
        selected_entry.get("debrief_attempts", 0)
    ) + 1
    selected_entry.pop("last_debrief_error", None)

    for older_path, older_entry in eligible[1:]:
        older_entry["status"] = STATUS_HISTORY_ONLY_SUPERSEDED
        older_entry["superseded_by"] = str(selected_path)
        older_entry["updated_at"] = stamp

    save_state(state_path, state)
    print(f"DEBRIEF LATEST: PASS — {selected_path.name}")
    print(f"Sesiones anteriores conservadas sólo en History: {len(eligible) - 1}")
    return 0


def show_status(state_path: Path) -> int:
    state = load_state(state_path)
    counts: dict[str, int] = {}
    for entry in state["files"].values():
        status = str(entry.get("status", "UNKNOWN"))
        counts[status] = counts.get(status, 0) + 1
    print("RACE ENGINEER - AUTOMATIC TELEMETRY INGEST")
    print(f"Estado: {state_path}")
    print(f"Archivos registrados: {len(state['files'])}")
    for status in sorted(counts):
        print(f"  {status}: {counts[status]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detecta telemetría nueva, prioriza History y serializa debriefs."
    )
    parser.add_argument("--telemetry-dir", default=None)
    parser.add_argument("--state", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("baseline", help="Registrar archivos actuales sin analizarlos.")
    backfill = subparsers.add_parser(
        "backfill-next",
        help="Importar a History un archivo BASELINED elegible.",
    )
    backfill.add_argument("--min-size-mb", type=float, default=5.0)
    scan_parser = subparsers.add_parser("scan", help="Importar archivos nuevos estables a History.")
    scan_parser.add_argument("--settle-seconds", type=int, default=600)
    maintenance_parser = subparsers.add_parser(
        "maintenance",
        help="Priorizar sesiones nuevas y hacer backfill gradual sin solapamiento.",
    )
    maintenance_parser.add_argument("--settle-seconds", type=int, default=600)
    maintenance_parser.add_argument("--min-size-mb", type=float, default=5.0)
    maintenance_parser.add_argument("--backfill-minutes", type=int, default=30)
    debrief = subparsers.add_parser("debrief-next", help="Generar exactamente un debrief pendiente.")
    debrief.add_argument("--backend", choices=("deepseek", "ollama"), default="deepseek")
    latest = subparsers.add_parser(
        "debrief-latest",
        help="Generar el debrief sólo para la sesión válida más reciente.",
    )
    latest.add_argument("--backend", choices=("deepseek", "ollama"), default="deepseek")
    latest.add_argument("--min-size-mb", type=float, default=5.0)
    latest.add_argument("--min-valid-laps", type=int, default=2)
    subparsers.add_parser("status", help="Mostrar el estado de la cola.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    telemetry_dir = resolve_path(args.telemetry_dir, DEFAULT_TELEMETRY_DIR)
    state_path = resolve_path(args.state, DEFAULT_STATE_PATH)
    now = utc_now()
    if args.command == "baseline":
        return baseline(telemetry_dir, state_path, now=now)
    if args.command == "backfill-next":
        if args.min_size_mb < 0:
            raise ValueError("--min-size-mb no puede ser negativo.")
        return backfill_next(
            state_path,
            min_size_mb=args.min_size_mb,
            now=now,
        )
    if args.command == "scan":
        if args.settle_seconds < 0:
            raise ValueError("--settle-seconds no puede ser negativo.")
        return scan(
            telemetry_dir,
            state_path,
            settle_seconds=args.settle_seconds,
            now=now,
        )
    if args.command == "maintenance":
        if (
            args.settle_seconds < 0
            or args.min_size_mb < 0
            or args.backfill_minutes < 1
        ):
            raise ValueError("Los parámetros de maintenance son inválidos.")
        return maintenance(
            telemetry_dir,
            state_path,
            settle_seconds=args.settle_seconds,
            min_size_mb=args.min_size_mb,
            backfill_minutes=args.backfill_minutes,
            now=now,
        )
    if args.command == "debrief-next":
        return debrief_next(state_path, backend=args.backend, now=now)
    if args.command == "debrief-latest":
        if args.min_size_mb < 0 or args.min_valid_laps < 1:
            raise ValueError("Los mínimos de elegibilidad son inválidos.")
        return debrief_latest(
            state_path,
            backend=args.backend,
            min_size_mb=args.min_size_mb,
            min_valid_laps=args.min_valid_laps,
            now=now,
        )
    if args.command == "status":
        return show_status(state_path)
    raise RuntimeError(f"Comando no implementado: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
