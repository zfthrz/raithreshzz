from __future__ import annotations

import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent
LMU_TELEMETRY_DIR = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry"
)
DEFAULT_LOG_PATH = PROJECT_ROOT / "data" / "local" / "telemetry_auto_ingest_task.log"
DEFAULT_MAX_LOG_BYTES = 2 * 1024 * 1024


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
    runner: Callable[..., object] = subprocess.run,
    max_log_bytes: int = DEFAULT_MAX_LOG_BYTES,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rotate_log(log_path, max_bytes=max_log_bytes)
    selected_command = list(command) if command is not None else build_maintenance_command()
    selected_review_command = (
        list(review_command)
        if review_command is not None
        else (build_h5_3_review_command() if command is None else None)
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        stamp = datetime.now(timezone.utc).isoformat()
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
        except Exception:
            traceback.print_exc(file=log)
            return_code = 1
        finish = datetime.now(timezone.utc).isoformat()
        log.write(f"[{finish}] END exit_code={return_code}\n")
        log.flush()
    return return_code


if __name__ == "__main__":
    raise SystemExit(run_hidden_maintenance())
