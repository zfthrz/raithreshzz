from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CalibrationLabelingTarget:
    batch_id: str
    batch_dir: Path
    queue_path: Path
    labels_path: Path
    queue_pairs: int
    labeled_pairs: int
    complete: bool


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _integer(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def resolve_calibration_labeling_target(
    batches_root: Path,
    *,
    batch_id: str,
) -> CalibrationLabelingTarget:
    root = Path(batches_root).resolve()
    wanted = str(batch_id or "").strip()
    if not wanted:
        raise ValueError("El batch seleccionado no tiene batch_id.")

    matches: list[tuple[Path, dict[str, Any]]] = []
    if root.is_dir():
        for status_path in root.glob("*/BATCH_STATUS.json"):
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and str(payload.get("batch_id") or "") == wanted:
                matches.append((status_path, payload))

    if not matches:
        raise FileNotFoundError(
            f"No se encontró un BATCH_STATUS.json para batch_id={wanted}."
        )
    if len(matches) != 1:
        raise ValueError(
            f"batch_id ambiguo ({wanted}): se encontraron {len(matches)} batches."
        )

    status_path, payload = matches[0]
    batch_dir_value = payload.get("batch_dir")
    batch_dir = (
        Path(batch_dir_value).expanduser()
        if isinstance(batch_dir_value, str) and batch_dir_value.strip()
        else status_path.parent
    )
    if not batch_dir.is_absolute():
        batch_dir = (root / batch_dir).resolve()
    else:
        batch_dir = batch_dir.resolve()

    steps = _dict(payload.get("steps"))
    review_queue = _dict(steps.get("review_queue"))
    human_labels = _dict(steps.get("human_labels"))

    queue_value = review_queue.get("path")
    queue_path = (
        Path(queue_value).expanduser()
        if isinstance(queue_value, str) and queue_value.strip()
        else batch_dir / "pair_review_queue.json"
    )
    if not queue_path.is_absolute():
        queue_path = (batch_dir / queue_path).resolve()
    else:
        queue_path = queue_path.resolve()

    labels_value = human_labels.get("labels_path")
    labels_path = (
        Path(labels_value).expanduser()
        if isinstance(labels_value, str) and labels_value.strip()
        else batch_dir / "pair_labels.json"
    )
    if not labels_path.is_absolute():
        labels_path = (batch_dir / labels_path).resolve()
    else:
        labels_path = labels_path.resolve()

    if not queue_path.is_file():
        raise FileNotFoundError(
            f"El batch {wanted} no tiene una cola de revisión utilizable:\n{queue_path}"
        )

    queue_pairs = _integer(
        human_labels.get("queue_pairs", review_queue.get("queue_pairs"))
    )
    labeled_pairs = _integer(human_labels.get("labeled_pairs"))
    try:
        queue_payload = json.loads(queue_path.read_text(encoding="utf-8"))
        queue = queue_payload.get("queue")
        if isinstance(queue, list):
            queue_pairs = len(queue)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    if labels_path.is_file():
        try:
            labels_payload = json.loads(labels_path.read_text(encoding="utf-8"))
            labels = labels_payload.get("labels")
            if isinstance(labels, list):
                labeled_pairs = len({
                    item.get("pair_id")
                    for item in labels
                    if isinstance(item, dict)
                    and isinstance(item.get("pair_id"), str)
                    and item.get("human_label")
                    in {"SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"}
                })
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    complete = queue_pairs > 0 and labeled_pairs >= queue_pairs

    return CalibrationLabelingTarget(
        batch_id=wanted,
        batch_dir=batch_dir,
        queue_path=queue_path,
        labels_path=labels_path,
        queue_pairs=queue_pairs,
        labeled_pairs=labeled_pairs,
        complete=complete,
    )


def _ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def labeling_python_executable(project_root: Path) -> Path:
    project_root = Path(project_root).resolve()
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt" and venv_python.is_file():
        return venv_python.resolve()
    return Path(sys.executable).resolve()


def build_calibration_labeling_powershell_command(
    project_root: Path,
    target: CalibrationLabelingTarget,
) -> list[str]:
    project_root = Path(project_root).resolve()
    python = labeling_python_executable(project_root)
    labeler = (project_root / "label_episode_pairs.py").resolve()
    if not labeler.is_file():
        raise FileNotFoundError(labeler)

    command = (
        f"Set-Location -LiteralPath {_ps_single_quote(str(project_root))}; "
        f"& {_ps_single_quote(str(python))} "
        f"{_ps_single_quote(str(labeler))} "
        f"{_ps_single_quote(str(target.queue_path))} "
        f"--labels {_ps_single_quote(str(target.labels_path))}"
    )
    return [
        "powershell.exe",
        "-NoLogo",
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]


def launch_calibration_labeling_powershell(
    project_root: Path,
    target: CalibrationLabelingTarget,
) -> subprocess.Popen:
    if os.name != "nt":
        raise RuntimeError(
            "El lanzamiento interactivo del labeler sólo está soportado en Windows."
        )
    command = build_calibration_labeling_powershell_command(project_root, target)
    return subprocess.Popen(
        command,
        cwd=str(Path(project_root).resolve()),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
