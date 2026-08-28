from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from auto_ingest_telemetry import le_mans_ultimate_is_running


PROJECT_ROOT = Path(__file__).resolve().parent
LMU_TELEMETRY_DIR = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry"
)
DEFAULT_LOG_PATH = PROJECT_ROOT / "data" / "local" / "telemetry_auto_ingest_task.log"
DEFAULT_RUNTIME_PATH = PROJECT_ROOT / "data" / "local" / "telemetry_scheduler_runtime.json"
DEFAULT_H3_IMPORT_STATE_PATH = PROJECT_ROOT / "data" / "local" / "h3_import_maintenance.json"
DEFAULT_H3_MATERIALIZATION_STATE_PATH = (
    PROJECT_ROOT / "data" / "local" / "h3_materialization_readiness.json"
)
DEFAULT_MAX_LOG_BYTES = 2 * 1024 * 1024


def write_runtime_state(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_runtime_state(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def console_python_executable(executable: Path | None = None) -> Path:
    current = Path(sys.executable if executable is None else executable).resolve()
    if current.name.casefold() == "pythonw.exe":
        console = current.with_name("python.exe")
        if console.is_file():
            return console
    return current


def build_maintenance_command(
    *,
    python_executable: Path | None = None,
    telemetry_dir: Path = LMU_TELEMETRY_DIR,
) -> list[str]:
    return [
        str(console_python_executable(python_executable)),
        str(PROJECT_ROOT / "auto_ingest_telemetry.py"),
        "--telemetry-dir",
        str(telemetry_dir),
        "maintenance",
        "--min-size-mb",
        "5",
        "--backfill-minutes",
        "30",
    ]


def build_h5_3_review_command(
    *, python_executable: Path | None = None,
) -> list[str]:
    return [
        str(console_python_executable(python_executable)),
        str(PROJECT_ROOT / "maintain_h5_3_action_review.py"),
    ]


def build_calibration_queue_command(
    *, python_executable: Path | None = None,
) -> list[str]:
    return [
        str(console_python_executable(python_executable)),
        str(PROJECT_ROOT / "maintain_calibration_queues.py"),
    ]


def build_mixed_cue_review_command(
    *, python_executable: Path | None = None,
) -> list[str]:
    return [
        str(console_python_executable(python_executable)),
        str(PROJECT_ROOT / "maintain_mixed_cue_review.py"),
        "--state",
        str(PROJECT_ROOT / "data" / "local" / "mixed_cue_review_maintenance.json"),
    ]


def build_h3_import_audit_command(
    *, python_executable: Path | None = None,
) -> list[str]:
    return [
        str(console_python_executable(python_executable)),
        str(PROJECT_ROOT / "maintain_h3_imports.py"),
        "--output",
        str(DEFAULT_H3_IMPORT_STATE_PATH),
        "--reuse-unchanged-output",
    ]


def build_h3_materialization_audit_command(
    *, python_executable: Path | None = None,
) -> list[str]:
    return [
        str(console_python_executable(python_executable)),
        str(PROJECT_ROOT / "audit_h3_materialization_readiness.py"),
        "--output",
        str(DEFAULT_H3_MATERIALIZATION_STATE_PATH),
        "--reuse-unchanged-output",
    ]


def rotate_log(path: Path, *, max_bytes: int = DEFAULT_MAX_LOG_BYTES) -> None:
    if max_bytes < 1 or not path.is_file() or path.stat().st_size < max_bytes:
        return
    backup = path.with_name(path.name + ".1")
    if backup.exists():
        backup.unlink()
    path.replace(backup)


def run_hidden_maintenance(
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    command: Sequence[str] | None = None,
    review_command: Sequence[str] | None = None,
    calibration_command: Sequence[str] | None = None,
    mixed_cue_command: Sequence[str] | None = None,
    h3_import_audit_command: Sequence[str] | None = None,
    h3_materialization_audit_command: Sequence[str] | None = None,
    runner: Callable[..., object] = subprocess.run,
    max_log_bytes: int = DEFAULT_MAX_LOG_BYTES,
    runtime_path: Path = DEFAULT_RUNTIME_PATH,
    game_is_running: Callable[[], bool] = le_mans_ultimate_is_running,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rotate_log(log_path, max_bytes=max_log_bytes)
    selected_command = list(command) if command is not None else build_maintenance_command()
    selected_review_command = (
        list(review_command)
        if review_command is not None
        else (build_h5_3_review_command() if command is None else None)
    )
    selected_calibration_command = (
        list(calibration_command)
        if calibration_command is not None
        else (build_calibration_queue_command() if command is None else None)
    )
    selected_mixed_cue_command = (
        list(mixed_cue_command)
        if mixed_cue_command is not None
        else (build_mixed_cue_review_command() if command is None else None)
    )
    selected_h3_import_audit_command = (
        list(h3_import_audit_command)
        if h3_import_audit_command is not None
        else (build_h3_import_audit_command() if command is None else None)
    )
    selected_h3_materialization_audit_command = (
        list(h3_materialization_audit_command)
        if h3_materialization_audit_command is not None
        else (build_h3_materialization_audit_command() if command is None else None)
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        stamp = datetime.now(timezone.utc).isoformat()
        previous_runtime = read_runtime_state(runtime_path)
        running_state = {
            "status": "RUNNING",
            "started_at": stamp,
            "pid": os.getpid(),
        }
        if previous_runtime.get("last_successful_at"):
            running_state["last_successful_at"] = previous_runtime["last_successful_at"]
        write_runtime_state(runtime_path, running_state)
        log.write(f"\n[{stamp}] START hidden History maintenance\n")
        log.flush()
        try:
            completed = runner(
                selected_command,
                cwd=str(PROJECT_ROOT),
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                creationflags=creationflags,
            )
            return_code = int(getattr(completed, "returncode", 1))
            if return_code == 0 and selected_review_command is not None:
                log.write("H5.3 review maintenance\n")
                log.flush()
                review_completed = runner(
                    selected_review_command,
                    cwd=str(PROJECT_ROOT),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                    creationflags=creationflags,
                )
                review_return_code = int(getattr(review_completed, "returncode", 1))
                if review_return_code != 0:
                    log.write(
                        "H5.3 REVIEW WARNING: "
                        f"maintenance exit_code={review_return_code}; History remains successful.\n"
                    )
            if return_code == 0 and selected_calibration_command is not None:
                log.write("H2 calibration queue maintenance\n")
                log.flush()
                calibration_completed = runner(
                    selected_calibration_command,
                    cwd=str(PROJECT_ROOT),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                    creationflags=creationflags,
                )
                calibration_return_code = int(
                    getattr(calibration_completed, "returncode", 1)
                )
                if calibration_return_code != 0:
                    log.write(
                        "H2 CALIBRATION QUEUE WARNING: "
                        f"maintenance exit_code={calibration_return_code}; "
                        "History remains successful.\n"
                    )
            if return_code == 0 and selected_mixed_cue_command is not None:
                log.write("Mixed-cue shadow review maintenance\n")
                log.flush()
                mixed_completed = runner(
                    selected_mixed_cue_command,
                    cwd=str(PROJECT_ROOT),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                    creationflags=creationflags,
                )
                mixed_return_code = int(getattr(mixed_completed, "returncode", 1))
                if mixed_return_code != 0:
                    log.write(
                        "MIXED CUE REVIEW WARNING: "
                        f"maintenance exit_code={mixed_return_code}; "
                        "History remains successful.\n"
                    )
            if return_code == 0 and selected_h3_import_audit_command is not None:
                log.write("H3 import readiness audit (read-only)\n")
                log.flush()
                try:
                    h3_completed = runner(
                        selected_h3_import_audit_command,
                        cwd=str(PROJECT_ROOT),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=False,
                        creationflags=creationflags,
                    )
                    h3_return_code = int(getattr(h3_completed, "returncode", 1))
                except Exception as exc:
                    h3_return_code = 1
                    log.write(f"H3 IMPORT AUDIT EXCEPTION: {type(exc).__name__}: {exc}\n")
                if h3_return_code != 0:
                    log.write(
                        "H3 IMPORT AUDIT WARNING: "
                        f"maintenance exit_code={h3_return_code}; "
                        "History remains successful and no import was attempted.\n"
                    )
            if return_code == 0 and selected_h3_materialization_audit_command is not None:
                if game_is_running():
                    log.write(
                        "H3 materialization readiness audit: "
                        "DEFERRED_GAME_RUNNING\n"
                    )
                else:
                    log.write("H3 materialization readiness audit (read-only)\n")
                    log.flush()
                    try:
                        materialization_completed = runner(
                            selected_h3_materialization_audit_command,
                            cwd=str(PROJECT_ROOT),
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            check=False,
                            creationflags=creationflags,
                        )
                        materialization_return_code = int(
                            getattr(materialization_completed, "returncode", 1)
                        )
                    except Exception as exc:
                        materialization_return_code = 1
                        log.write(
                            "H3 MATERIALIZATION AUDIT EXCEPTION: "
                            f"{type(exc).__name__}: {exc}\n"
                        )
                    if materialization_return_code != 0:
                        log.write(
                            "H3 MATERIALIZATION AUDIT WARNING: "
                            f"maintenance exit_code={materialization_return_code}; "
                            "History remains successful and no bundle was written.\n"
                        )
        except Exception:
            traceback.print_exc(file=log)
            return_code = 1
        finish = datetime.now(timezone.utc).isoformat()
        log.write(f"[{finish}] END exit_code={return_code}\n")
        log.flush()
        finished_state = {
            "status": "PASS" if return_code == 0 else "FAILED",
            "started_at": stamp,
            "finished_at": finish,
            "exit_code": return_code,
            "pid": os.getpid(),
        }
        last_successful_at = (
            finish if return_code == 0 else previous_runtime.get("last_successful_at")
        )
        if last_successful_at:
            finished_state["last_successful_at"] = last_successful_at
        write_runtime_state(runtime_path, finished_state)
    return return_code


if __name__ == "__main__":
    raise SystemExit(run_hidden_maintenance())
