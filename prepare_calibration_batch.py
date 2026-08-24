from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ORCHESTRATOR_VERSION = "1.5"
EXPECTED_HISTORY_SCHEMA_VERSION = 4

REQUIRED_SCRIPTS = (
    "session_history.py",
    "validate_history_db.py",
    "episode_pair_features.py",
    "pair_review_queue.py",
    "label_episode_pairs.py",
    "validate_pair_labels.py",
    "build_calibration_dataset.py",
    "calibration_feature_report.py",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "track"


def stable_json_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(raw).hexdigest()


def session_signature(
    rows: list[dict[str, Any]],
) -> str:
    normalized = []

    for row in rows:
        normalized.append({
            "session_id": int(row["session_id"]),
            "track": str(row.get("track") or ""),
            "track_layout": str(row.get("lmu_track_layout") or ""),
            "vehicle_family": str(row.get("vehicle_family") or ""),
            "vehicle_variant": str(row.get("vehicle_variant") or ""),
            "source_json_sha256": str(
                row.get("source_json_sha256") or ""
            ),
            "source_analysis_version": str(
                row.get("source_analysis_version") or ""
            ),
            "timestamp_utc": str(
                row.get("timestamp_utc") or ""
            ),
        })

    normalized.sort(
        key=lambda item: (
            item["track"],
            item["session_id"],
            item["source_json_sha256"],
        )
    )

    return stable_json_hash(normalized)


def build_batch_paths(
    output_root: Path,
    track: str,
    signature: str,
    vehicle_variant: str | None = None,
    track_layout: str | None = None,
) -> dict[str, Path]:
    context_slug = slugify(track)

    if track_layout:
        layout_slug = slugify(track_layout)
        if layout_slug != context_slug:
            context_slug = context_slug + "--" + layout_slug

    if vehicle_variant:
        context_slug = (
            context_slug
            + "--"
            + slugify(vehicle_variant)
        )

    batch_name = (
        f"{context_slug}-"
        f"{signature[:10]}"
    )

    batch_dir = (
        output_root
        /
        batch_name
    )

    return {
        "batch_dir": batch_dir,
        "logs_dir": batch_dir / "logs",
        "status": batch_dir / "BATCH_STATUS.json",
        "pair_features": batch_dir / "episode_pair_features.json",
        "review_queue": batch_dir / "pair_review_queue.json",
        "labels": batch_dir / "pair_labels.json",
        "dataset": batch_dir / "calibration_dataset.json",
        "feature_report": batch_dir / "calibration_feature_report.json",
    }


def command_string(
    command: list[str],
) -> str:
    return shlex.join(
        [
            str(part)
            for part in command
        ]
    )


def run_command(
    command: list[str],
    *,
    cwd: Path,
    log_path: Path | None = None,
) -> dict[str, Any]:
    result = subprocess.run(
        [
            str(part)
            for part in command
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )

    payload = {
        "command": command_string(command),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

    if log_path is not None:
        log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        log_path.write_text(
            (
                f"$ {payload['command']}\n\n"
                f"--- STDOUT ---\n"
                f"{result.stdout}\n"
                f"--- STDERR ---\n"
                f"{result.stderr}\n"
                f"--- RETURN CODE ---\n"
                f"{result.returncode}\n"
            ),
            encoding="utf-8",
        )

    return payload


def ensure_required_scripts(
    project_root: Path,
) -> list[str]:
    missing = []

    for name in REQUIRED_SCRIPTS:
        if not (
            project_root
            /
            name
        ).is_file():
            missing.append(
                name
            )

    return missing


def validate_dependency_contract(
    project_root: Path,
) -> list[dict[str, str]]:
    """Reject known-stale core scripts before any batch work starts.

    This prevents a new orchestrator from silently invoking an older
    pair_review_queue.py/session_history.py that happens to share the
    stable generic filename.
    """
    checks = (
        (
            "session_history.py",
            re.compile(
                rf"^\s*SCHEMA_VERSION\s*=\s*{EXPECTED_HISTORY_SCHEMA_VERSION}\s*$",
                re.MULTILINE,
            ),
            f"history_schema_{EXPECTED_HISTORY_SCHEMA_VERSION}",
        ),
        (
            "pair_review_queue.py",
            re.compile(
                r"^\s*QUEUE_SCHEMA_VERSION\s*=\s*[\"']1\.1[\"']\s*$",
                re.MULTILINE,
            ),
            "review_queue_schema_1.1",
        ),
    )

    errors: list[dict[str, str]] = []

    for filename, pattern, requirement in checks:
        path = project_root / filename
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append({
                "script": filename,
                "requirement": requirement,
                "reason": f"unreadable:{exc}",
            })
            continue

        if not pattern.search(text):
            errors.append({
                "script": filename,
                "requirement": requirement,
                "reason": "stale_or_incompatible_script",
            })

    return errors


def load_history_rows(
    db_path: Path,
) -> list[dict[str, Any]]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "duckdb no está instalado en este entorno."
        ) from exc

    connection = duckdb.connect(
        str(db_path),
        read_only=True,
    )

    try:
        rows = connection.execute(
            """
            SELECT
                session_id,
                track,
                vehicle_family,
                vehicle_variant,
                car_class_raw,
                car_name_raw,
                vehicle_supported_domain,
                lmu_track_layout,
                source_json_sha256,
                source_analysis_version,
                timestamp_utc
            FROM sessions
            ORDER BY
                track,
                lmu_track_layout,
                vehicle_variant,
                session_id
            """
        ).fetchall()
    finally:
        connection.close()

    return [
        {
            "session_id": row[0],
            "track": row[1],
            "vehicle_family": row[2],
            "vehicle_variant": row[3],
            "car_class_raw": row[4],
            "car_name_raw": row[5],
            "vehicle_supported_domain": (
                bool(row[6])
                if row[6] is not None
                else None
            ),
            "lmu_track_layout": row[7],
            "source_json_sha256": row[8],
            "source_analysis_version": row[9],
            "timestamp_utc": row[10],
        }
        for row in rows
    ]


def group_history_by_track(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[
        str,
        list[dict[str, Any]]
    ] = {}

    for row in rows:
        track = str(
            row.get("track")
            or
            ""
        ).strip()

        if not track:
            track = "<UNKNOWN_TRACK>"

        result.setdefault(
            track,
            [],
        ).append(
            row
        )

    return result


def group_history_by_context(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    result: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = {}

    for row in rows:
        track = str(
            row.get("track")
            or
            ""
        ).strip()

        layout = str(
            row.get("lmu_track_layout")
            or
            ""
        ).strip()

        variant = str(
            row.get("vehicle_variant")
            or
            ""
        ).strip()

        if (
            not track
            or
            not layout
            or
            not variant
            or
            row.get("vehicle_supported_domain") is not True
        ):
            continue

        result.setdefault(
            (track, layout, variant),
            [],
        ).append(
            row
        )

    return result


def choose_context(
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]],
    requested_track: str | None,
    requested_variant: str | None,
    requested_layout: str | None,
    *,
    min_sessions: int = 2,
) -> tuple[tuple[str, str, str] | None, str | None]:
    if min_sessions < 2:
        raise ValueError(
            "min_sessions no puede ser menor que 2."
        )

    candidates = []

    for key, context_rows in grouped.items():
        track, layout, variant = key

        if requested_track is not None and track != requested_track:
            continue

        if requested_layout is not None and layout != requested_layout:
            continue

        if requested_variant is not None and variant != requested_variant:
            continue

        if len(context_rows) >= min_sessions:
            candidates.append(
                key
            )

    candidates.sort()

    if len(candidates) == 1:
        return candidates[0], None

    if not candidates:
        return (
            None,
            (
                "insufficient_vehicle_context_data: "
                "no track + layout + vehicle_variant context has "
                f">= {min_sessions} sessions"
            ),
        )

    choices = ", ".join(
        f"{track} | {layout} | {variant}"
        for track, layout, variant in candidates
    )

    return (
        None,
        (
            "multiple_eligible_vehicle_contexts: "
            "use --track, --track-layout and/or --vehicle-variant; choices="
            + choices
        ),
    )


def choose_track(
    grouped: dict[str, list[dict[str, Any]]],
    requested_track: str | None,
    *,
    min_sessions: int = 2,
) -> tuple[
    str | None,
    str | None,
]:
    if min_sessions < 2:
        raise ValueError(
            "min_sessions no puede ser menor que 2."
        )

    if requested_track is not None:
        if requested_track not in grouped:
            return (
                None,
                (
                    "requested_track_not_found: "
                    f"{requested_track}"
                ),
            )

        count = len(
            grouped[
                requested_track
            ]
        )

        if count < min_sessions:
            return (
                None,
                (
                    "insufficient_sessions_for_requested_track: "
                    f"{requested_track} has {count}, "
                    f"requires >= {min_sessions}"
                ),
            )

        return (
            requested_track,
            None,
        )

    eligible = [
        track
        for track, rows in grouped.items()
        if len(rows) >= min_sessions
    ]

    eligible.sort()

    if len(eligible) == 1:
        return (
            eligible[0],
            None,
        )

    if not eligible:
        return (
            None,
            (
                "insufficient_cross_session_data: "
                f"no track has >= {min_sessions} sessions"
            ),
        )

    return (
        None,
        (
            "multiple_eligible_tracks: "
            "use --track; choices="
            +
            ", ".join(
                eligible
            )
        ),
    )


def load_json(
    path: Path,
) -> Any:
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def file_sha256(
    path: Path,
) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def review_queue_reuse_status(
    queue_path: Path,
    pair_features_path: Path,
    *,
    per_lens: int,
    max_total: int | None,
    seed: int,
) -> tuple[bool, str]:
    try:
        data = load_json(queue_path)
    except Exception as exc:
        return False, f"queue_unreadable:{exc}"

    if not isinstance(data, dict):
        return False, "queue_root_not_object"

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return False, "queue_metadata_missing"

    if str(metadata.get("queue_schema_version") or "") != "1.1":
        return False, "queue_schema_changed"

    if metadata.get("selection_policy") != "round_robin_stratified_v1.1":
        return False, "queue_selection_policy_changed"

    if metadata.get("source_features_sha256") != file_sha256(pair_features_path):
        return False, "pair_features_changed"

    if metadata.get("per_lens") != per_lens:
        return False, "per_lens_changed"

    if metadata.get("max_total") != max_total:
        return False, "max_total_changed"

    if metadata.get("seed") != seed:
        return False, "seed_changed"

    return True, "compatible"


def pair_feature_count(
    path: Path,
) -> int:
    data = load_json(
        path
    )

    if not isinstance(
        data,
        list,
    ):
        raise ValueError(
            "episode_pair_features JSON debe ser una lista."
        )

    return len(
        data
    )


def review_queue_count(
    path: Path,
) -> int:
    data = load_json(
        path
    )

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            "pair_review_queue root debe ser objeto."
        )

    queue = data.get(
        "queue"
    )

    if not isinstance(
        queue,
        list,
    ):
        raise ValueError(
            "pair_review_queue.queue debe ser lista."
        )

    return len(
        queue
    )


def label_progress(
    queue_path: Path,
    labels_path: Path,
) -> dict[str, Any]:
    queue_data = load_json(
        queue_path
    )

    queue = queue_data.get(
        "queue",
        [],
    )

    if not isinstance(
        queue,
        list,
    ):
        raise ValueError(
            "queue inválida."
        )

    queue_ids = {
        item.get(
            "pair_id"
        )
        for item in queue
        if isinstance(
            item,
            dict,
        )
        and isinstance(
            item.get(
                "pair_id"
            ),
            str,
        )
    }

    if not labels_path.exists():
        return {
            "exists": False,
            "queue_pairs": len(
                queue_ids
            ),
            "labeled_pairs": 0,
            "unreviewed_pairs": len(
                queue_ids
            ),
            "complete": False,
        }

    labels_data = load_json(
        labels_path
    )

    labels = labels_data.get(
        "labels",
        [],
    )

    if not isinstance(
        labels,
        list,
    ):
        raise ValueError(
            "labels inválidas."
        )

    labeled_ids = {
        item.get(
            "pair_id"
        )
        for item in labels
        if isinstance(
            item,
            dict,
        )
        and isinstance(
            item.get(
                "pair_id"
            ),
            str,
        )
        and item.get(
            "pair_id"
        ) in queue_ids
    }

    unreviewed = (
        queue_ids
        -
        labeled_ids
    )

    return {
        "exists": True,
        "queue_pairs": len(
            queue_ids
        ),
        "labeled_pairs": len(
            labeled_ids
        ),
        "unreviewed_pairs": len(
            unreviewed
        ),
        "complete": (
            len(
                queue_ids
            ) > 0
            and
            not unreviewed
        ),
    }


def dataset_readiness(
    dataset_path: Path,
) -> dict[str, Any]:
    data = load_json(
        dataset_path
    )

    counts = data.get(
        "counts",
        {},
    )

    if not isinstance(
        counts,
        dict,
    ):
        raise ValueError(
            "dataset.counts inválido."
        )

    calibration_pairs = int(
        counts.get(
            "calibration_pairs",
            0,
        )
        or
        0
    )

    evaluation_pairs = int(
        counts.get(
            "evaluation_pairs",
            0,
        )
        or
        0
    )

    excluded = int(
        counts.get(
            "cross_split_pairs_excluded",
            0,
        )
        or
        0
    )

    return {
        "calibration_pairs": calibration_pairs,
        "evaluation_pairs": evaluation_pairs,
        "cross_split_pairs_excluded": excluded,
        "calibration_ready": calibration_pairs > 0,
        "evaluation_ready": evaluation_pairs > 0,
    }


def new_status(
    *,
    project_root: Path,
    input_dir: Path,
    db_path: Path,
) -> dict[str, Any]:
    return {
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "updated_at_utc": utc_now_iso(),
        "project_root": str(
            project_root
        ),
        "input_dir": str(
            input_dir
        ),
        "history_db": str(
            db_path
        ),
        "overall_status": "STARTING",
        "track": None,
        "track_layout": None,
        "vehicle_family": None,
        "vehicle_variant": None,
        "batch_id": None,
        "batch_dir": None,
        "steps": {},
        "next_action": None,
        "matcher": {
            "status": "BLOCKED_BY_REAL_DATA",
            "reason": (
                "No thresholds, weights, automatic matching, "
                "clustering, or persistent_pattern are implemented."
            ),
        },
    }


def set_step(
    status: dict[str, Any],
    name: str,
    state: str,
    **details: Any,
) -> None:
    payload = {
        "status": state,
    }

    payload.update(
        details
    )

    status[
        "steps"
    ][
        name
    ] = payload

    status[
        "updated_at_utc"
    ] = utc_now_iso()


def write_status(
    path: Path,
    status: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            status,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def refresh_matcher_status(
    status: dict[str, Any],
) -> None:
    """Actualiza status['matcher'] según la calibración real por contexto."""
    try:
        from episode_pair_matcher import CALIBRATIONS
    except Exception:
        return
    calibration = CALIBRATIONS.get(
        (
            status.get("track"),
            status.get("track_layout"),
            status.get("vehicle_variant"),
        )
    )
    if calibration is None:
        status["matcher"] = {
            "status": "NO_CALIBRATION_FOR_CONTEXT",
            "reason": (
                "No hay thresholds calibrados para este contexto exacto; "
                "labelar el batch para calibrar."
            ),
        }
        return
    status["matcher"] = {
        "status": calibration["status"],
        "reason": (
            "Thresholds provisionales disponibles para este contexto; "
            "requieren más datos independientes antes de evaluar."
        ),
        "human_labels": calibration.get("human_labels"),
    }
    if calibration.get("provenance"):
        status["matcher"]["provenance"] = calibration["provenance"]


def ensure_success(
    result: dict[str, Any],
    *,
    step_name: str,
) -> None:
    if result[
        "returncode"
    ] != 0:
        raise RuntimeError(
            (
                f"{step_name} failed with return code "
                f"{result['returncode']}.\n"
                f"Command: {result['command']}\n"
                f"STDOUT:\n{result['stdout']}\n"
                f"STDERR:\n{result['stderr']}"
            )
        )


def run_pipeline(
    args: argparse.Namespace,
    *,
    command_runner: Callable[..., dict[str, Any]] = run_command,
    history_loader: Callable[
        [Path],
        list[dict[str, Any]]
    ] = load_history_rows,
) -> tuple[int, dict[str, Any], Path]:
    project_root = Path(
        args.project_root
    ).resolve()

    input_dir = Path(
        args.input_dir
    ).resolve()

    db_path = Path(
        args.db
    )

    if not db_path.is_absolute():
        db_path = (
            project_root
            /
            db_path
        )

    db_path = db_path.resolve()

    output_root = Path(
        args.output_dir
    )

    if not output_root.is_absolute():
        output_root = (
            project_root
            /
            output_root
        )

    output_root = output_root.resolve()

    bootstrap_status_path = (
        output_root
        /
        "BATCH_STATUS.json"
    )

    status = new_status(
        project_root=project_root,
        input_dir=input_dir,
        db_path=db_path,
    )

    write_status(
        bootstrap_status_path,
        status,
    )

    missing = ensure_required_scripts(
        project_root
    )

    if missing:
        set_step(
            status,
            "project_contract",
            "FAIL",
            missing_scripts=missing,
        )

        status[
            "overall_status"
        ] = "BLOCKED_PROJECT_CONTRACT"

        status[
            "next_action"
        ] = (
            "Restore missing project scripts before preparing a batch."
        )

        write_status(
            bootstrap_status_path,
            status,
        )

        return (
            2,
            status,
            bootstrap_status_path,
        )

    dependency_errors = validate_dependency_contract(
        project_root
    )

    if dependency_errors:
        set_step(
            status,
            "project_contract",
            "FAIL",
            required_scripts=list(REQUIRED_SCRIPTS),
            incompatible_scripts=dependency_errors,
        )

        status["overall_status"] = "BLOCKED_PROJECT_CONTRACT"
        status["next_action"] = (
            "Replace stale generic scripts with the required H2 versions "
            "before preparing the batch."
        )

        write_status(
            bootstrap_status_path,
            status,
        )

        return (
            2,
            status,
            bootstrap_status_path,
        )

    set_step(
        status,
        "project_contract",
        "PASS",
        required_scripts=list(
            REQUIRED_SCRIPTS
        ),
        dependency_contract={
            "session_history_schema": EXPECTED_HISTORY_SCHEMA_VERSION,
            "pair_review_queue_schema": "1.1",
            "max_review_pairs_default": 24,
        },
    )

    if not input_dir.is_dir():
        set_step(
            status,
            "input_directory",
            "FAIL",
            path=str(
                input_dir
            ),
        )

        status[
            "overall_status"
        ] = "BLOCKED_INPUT_DIRECTORY"

        status[
            "next_action"
        ] = (
            "Provide a directory containing analyze_telemetry JSON files."
        )

        write_status(
            bootstrap_status_path,
            status,
        )

        return (
            2,
            status,
            bootstrap_status_path,
        )

    set_step(
        status,
        "input_directory",
        "PASS",
        path=str(
            input_dir
        ),
        json_files_seen=len(
            list(
                input_dir.rglob(
                    "*.json"
                )
                if args.recursive
                else input_dir.glob(
                    "*.json"
                )
            )
        ),
    )

    python = sys.executable

    init_result = command_runner(
        [
            python,
            str(
                project_root
                /
                "session_history.py"
            ),
            "--db",
            str(
                db_path
            ),
            "init",
        ],
        cwd=project_root,
        log_path=(
            output_root
            /
            "00_history_init.log"
        ),
    )

    if init_result[
        "returncode"
    ] != 0:
        set_step(
            status,
            "history_init",
            "FAIL",
            command=init_result[
                "command"
            ],
        )

        status[
            "overall_status"
        ] = "BLOCKED_HISTORY_INIT"

        write_status(
            bootstrap_status_path,
            status,
        )

        return (
            1,
            status,
            bootstrap_status_path,
        )

    set_step(
        status,
        "history_init",
        "PASS",
        command=init_result[
            "command"
        ],
    )

    before_rows = history_loader(
        db_path
    )

    if args.skip_import:
        set_step(
            status,
            "history_import",
            "SKIPPED",
            reason="--skip-import",
            sessions_before=len(
                before_rows
            ),
        )
    else:
        import_command = [
            python,
            str(
                project_root
                /
                "session_history.py"
            ),
            "--db",
            str(
                db_path
            ),
            "import-dir",
            str(
                input_dir
            ),
        ]

        if args.recursive:
            import_command.append(
                "--recursive"
            )

        import_result = command_runner(
            import_command,
            cwd=project_root,
            log_path=(
                output_root
                /
                "01_history_import.log"
            ),
        )

        if import_result[
            "returncode"
        ] != 0:
            set_step(
                status,
                "history_import",
                "FAIL",
                command=import_result[
                    "command"
                ],
            )

            status[
                "overall_status"
            ] = "BLOCKED_HISTORY_IMPORT"

            write_status(
                bootstrap_status_path,
                status,
            )

            return (
                1,
                status,
                bootstrap_status_path,
            )

        after_import_rows = history_loader(
            db_path
        )

        set_step(
            status,
            "history_import",
            "PASS",
            command=import_result[
                "command"
            ],
            sessions_before=len(
                before_rows
            ),
            sessions_after=len(
                after_import_rows
            ),
            imported_session_delta=(
                len(
                    after_import_rows
                )
                -
                len(
                    before_rows
                )
            ),
        )

    validation_result = command_runner(
        [
            python,
            str(
                project_root
                /
                "validate_history_db.py"
            ),
            "--db",
            str(
                db_path
            ),
        ],
        cwd=project_root,
        log_path=(
            output_root
            /
            "02_history_validation.log"
        ),
    )

    if validation_result[
        "returncode"
    ] != 0:
        set_step(
            status,
            "history_validation",
            "FAIL",
            command=validation_result[
                "command"
            ],
        )

        status[
            "overall_status"
        ] = "BLOCKED_HISTORY_VALIDATION"

        status[
            "next_action"
        ] = (
            "Fix History DB validation errors before pair generation."
        )

        write_status(
            bootstrap_status_path,
            status,
        )

        return (
            1,
            status,
            bootstrap_status_path,
        )

    set_step(
        status,
        "history_validation",
        "PASS",
        command=validation_result[
            "command"
        ],
    )

    rows = history_loader(
        db_path
    )

    grouped_context = group_history_by_context(
        rows
    )

    context_summary = {
        f"{track} | {layout} | {variant}": len(
            context_rows
        )
        for (track, layout, variant), context_rows
        in grouped_context.items()
    }

    chosen_context, reason = choose_context(
        grouped_context,
        args.track,
        args.vehicle_variant,
        args.track_layout,
        min_sessions=2,
    )

    if chosen_context is None:
        set_step(
            status,
            "vehicle_context_selection",
            "BLOCKED",
            reason=reason,
            sessions_by_vehicle_context=context_summary,
        )

        status[
            "overall_status"
        ] = "BLOCKED_VEHICLE_CONTEXT_SELECTION"

        if (
            reason is not None
            and
            reason.startswith(
                "multiple_eligible_vehicle_contexts"
            )
        ):
            status[
                "next_action"
            ] = (
                "Run again with --track <exact track name>, "
                "--track-layout <exact layout> and/or "
                "--vehicle-variant <exact variant>."
            )
        else:
            status[
                "next_action"
            ] = (
                "Import at least two sessions with the same track, "
                "explicit layout and supported vehicle_variant."
            )

        write_status(
            bootstrap_status_path,
            status,
        )

        return (
            2,
            status,
            bootstrap_status_path,
        )

    chosen_track, chosen_layout, chosen_variant = chosen_context
    context_rows = grouped_context[
        chosen_context
    ]


    signature = session_signature(
        context_rows
    )

    paths = build_batch_paths(
        output_root,
        chosen_track,
        signature,
        chosen_variant,
        chosen_layout,
    )

    batch_dir = paths[
        "batch_dir"
    ]

    logs_dir = paths[
        "logs_dir"
    ]

    batch_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    logs_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    status[
        "track"
    ] = chosen_track

    status[
        "track_layout"
    ] = chosen_layout

    status[
        "vehicle_variant"
    ] = chosen_variant

    families = sorted({
        str(row.get("vehicle_family"))
        for row in context_rows
        if row.get("vehicle_family")
    })

    status[
        "vehicle_family"
    ] = (
        families[0]
        if len(families) == 1
        else None
    )

    status[
        "batch_id"
    ] = signature[:10]

    status[
        "batch_dir"
    ] = str(
        batch_dir
    )

    set_step(
        status,
        "vehicle_context_selection",
        "PASS",
        selected_track=chosen_track,
        selected_track_layout=chosen_layout,
        selected_vehicle_variant=chosen_variant,
        vehicle_family=status.get("vehicle_family"),
        session_count=len(
            context_rows
        ),
        session_ids=[
            int(
                row[
                    "session_id"
                ]
            )
            for row in context_rows
        ],
        session_signature=signature,
        sessions_by_vehicle_context=context_summary,
    )

    batch_status_path = paths[
        "status"
    ]

    refresh_matcher_status(
        status,
    )
    write_status(
        batch_status_path,
        status,
    )

    pair_features_path = paths[
        "pair_features"
    ]

    if pair_features_path.exists():
        features_count = pair_feature_count(
            pair_features_path
        )

        set_step(
            status,
            "pair_features",
            "REUSED",
            path=str(
                pair_features_path
            ),
            pair_count=features_count,
        )
    else:
        features_result = command_runner(
            [
                python,
                str(
                    project_root
                    /
                    "episode_pair_features.py"
                ),
                "--db",
                str(
                    db_path
                ),
                "--track",
                chosen_track,
                "--track-layout",
                chosen_layout,
                "--vehicle-variant",
                chosen_variant,
                "--format",
                "json",
                "--output",
                str(
                    pair_features_path
                ),
            ],
            cwd=project_root,
            log_path=(
                logs_dir
                /
                "03_pair_features.log"
            ),
        )

        if features_result[
            "returncode"
        ] != 0:
            set_step(
                status,
                "pair_features",
                "FAIL",
                command=features_result[
                    "command"
                ],
            )

            status[
                "overall_status"
            ] = "BLOCKED_PAIR_FEATURES"

            write_status(
                batch_status_path,
                status,
            )

            return (
                1,
                status,
                batch_status_path,
            )

        features_count = pair_feature_count(
            pair_features_path
        )

        set_step(
            status,
            "pair_features",
            "PASS",
            command=features_result[
                "command"
            ],
            path=str(
                pair_features_path
            ),
            pair_count=features_count,
        )

    if features_count == 0:
        set_step(
            status,
            "review_queue",
            "BLOCKED",
            reason="no_cross_session_episode_pairs",
        )

        status[
            "overall_status"
        ] = "BLOCKED_NO_PAIR_FEATURES"

        status[
            "next_action"
        ] = (
            "Collect more usable same-track sessions/episodes."
        )

        write_status(
            batch_status_path,
            status,
        )

        return (
            2,
            status,
            batch_status_path,
        )

    queue_path = paths[
        "review_queue"
    ]

    reuse_queue = False
    reuse_reason = "missing"
    if queue_path.exists():
        reuse_queue, reuse_reason = review_queue_reuse_status(
            queue_path,
            pair_features_path,
            per_lens=args.per_lens,
            max_total=args.max_review_pairs,
            seed=args.seed,
        )

    if reuse_queue:
        queue_count = review_queue_count(
            queue_path
        )

        set_step(
            status,
            "review_queue",
            "REUSED",
            path=str(
                queue_path
            ),
            queue_pairs=queue_count,
            reuse_reason=reuse_reason,
        )
    else:
        queue_command = [
            python,
            str(
                project_root
                /
                "pair_review_queue.py"
            ),
            str(
                pair_features_path
            ),
            "--output",
            str(
                queue_path
            ),
            "--per-lens",
            str(
                args.per_lens
            ),
            "--seed",
            str(
                args.seed
            ),
        ]

        if args.max_review_pairs is not None:
            queue_command.extend([
                "--max-total",
                str(
                    args.max_review_pairs
                ),
            ])

        queue_result = command_runner(
            queue_command,
            cwd=project_root,
            log_path=(
                logs_dir
                /
                "04_review_queue.log"
            ),
        )

        if queue_result[
            "returncode"
        ] != 0:
            set_step(
                status,
                "review_queue",
                "FAIL",
                command=queue_result[
                    "command"
                ],
            )

            status[
                "overall_status"
            ] = "BLOCKED_REVIEW_QUEUE"

            write_status(
                batch_status_path,
                status,
            )

            return (
                1,
                status,
                batch_status_path,
            )

        queue_count = review_queue_count(
            queue_path
        )

        set_step(
            status,
            "review_queue",
            "READY",
            command=queue_result[
                "command"
            ],
            path=str(
                queue_path
            ),
            queue_pairs=queue_count,
            regenerated_reason=reuse_reason,
            review_policy={
                "per_lens": args.per_lens,
                "max_review_pairs": args.max_review_pairs,
                "seed": args.seed,
            },
        )

    labels_path = (
        Path(
            args.labels
        ).resolve()
        if args.labels is not None
        else paths[
            "labels"
        ]
    )

    progress = label_progress(
        queue_path,
        labels_path,
    )

    review_command = command_string([
        python,
        str(
            project_root
            /
            "label_episode_pairs.py"
        ),
        str(
            queue_path
        ),
        "--labels",
        str(
            labels_path
        ),
    ])

    if not progress[
        "exists"
    ]:
        set_step(
            status,
            "human_labels",
            "PENDING",
            labels_path=str(
                labels_path
            ),
            **progress,
            review_command=review_command,
        )

        set_step(
            status,
            "calibration_dataset",
            "BLOCKED_BY_LABELS",
        )

        set_step(
            status,
            "feature_report",
            "BLOCKED_BY_LABELS",
        )

        status[
            "overall_status"
        ] = "READY_FOR_HUMAN_REVIEW"

        status[
            "next_action"
        ] = review_command

        write_status(
            batch_status_path,
            status,
        )

        return (
            0,
            status,
            batch_status_path,
        )

    label_validation_result = command_runner(
        [
            python,
            str(
                project_root
                /
                "validate_pair_labels.py"
            ),
            str(
                queue_path
            ),
            str(
                labels_path
            ),
        ],
        cwd=project_root,
        log_path=(
            logs_dir
            /
            "05_label_validation.log"
        ),
    )

    if label_validation_result[
        "returncode"
    ] != 0:
        set_step(
            status,
            "label_validation",
            "FAIL",
            command=label_validation_result[
                "command"
            ],
        )

        status[
            "overall_status"
        ] = "BLOCKED_LABEL_VALIDATION"

        status[
            "next_action"
        ] = (
            "Fix label validation errors before building a dataset."
        )

        write_status(
            batch_status_path,
            status,
        )

        return (
            1,
            status,
            batch_status_path,
        )

    set_step(
        status,
        "label_validation",
        "PASS",
        command=label_validation_result[
            "command"
        ],
    )

    progress = label_progress(
        queue_path,
        labels_path,
    )

    if not progress[
        "complete"
    ]:
        set_step(
            status,
            "human_labels",
            "INCOMPLETE",
            labels_path=str(
                labels_path
            ),
            **progress,
            review_command=review_command,
        )

        set_step(
            status,
            "calibration_dataset",
            "BLOCKED_BY_INCOMPLETE_LABELS",
        )

        set_step(
            status,
            "feature_report",
            "BLOCKED_BY_INCOMPLETE_LABELS",
        )

        status[
            "overall_status"
        ] = "WAITING_FOR_HUMAN_REVIEW"

        status[
            "next_action"
        ] = review_command

        write_status(
            batch_status_path,
            status,
        )

        return (
            0,
            status,
            batch_status_path,
        )

    set_step(
        status,
        "human_labels",
        "PASS",
        labels_path=str(
            labels_path
        ),
        **progress,
    )

    dataset_path = paths[
        "dataset"
    ]

    dataset_result = command_runner(
        [
            python,
            str(
                project_root
                /
                "build_calibration_dataset.py"
            ),
            str(
                queue_path
            ),
            str(
                labels_path
            ),
            "--evaluation-fraction",
            str(
                args.evaluation_fraction
            ),
            "--seed",
            str(
                args.seed
            ),
            "--output",
            str(
                dataset_path
            ),
        ],
        cwd=project_root,
        log_path=(
            logs_dir
            /
            "06_calibration_dataset.log"
        ),
    )

    if dataset_result[
        "returncode"
    ] != 0:
        set_step(
            status,
            "calibration_dataset",
            "FAIL",
            command=dataset_result[
                "command"
            ],
        )

        status[
            "overall_status"
        ] = "BLOCKED_CALIBRATION_DATASET"

        write_status(
            batch_status_path,
            status,
        )

        return (
            1,
            status,
            batch_status_path,
        )

    readiness = dataset_readiness(
        dataset_path
    )

    set_step(
        status,
        "calibration_dataset",
        "PASS",
        command=dataset_result[
            "command"
        ],
        path=str(
            dataset_path
        ),
        **readiness,
    )

    report_path = paths[
        "feature_report"
    ]

    report_result = command_runner(
        [
            python,
            str(
                project_root
                /
                "calibration_feature_report.py"
            ),
            str(
                dataset_path
            ),
            "--output",
            str(
                report_path
            ),
        ],
        cwd=project_root,
        log_path=(
            logs_dir
            /
            "07_feature_report.log"
        ),
    )

    if report_result[
        "returncode"
    ] != 0:
        set_step(
            status,
            "feature_report",
            "FAIL",
            command=report_result[
                "command"
            ],
        )

        status[
            "overall_status"
        ] = "BLOCKED_FEATURE_REPORT"

        write_status(
            batch_status_path,
            status,
        )

        return (
            1,
            status,
            batch_status_path,
        )

    set_step(
        status,
        "feature_report",
        "PASS",
        command=report_result[
            "command"
        ],
        path=str(
            report_path
        ),
    )

    if readiness[
        "evaluation_ready"
    ]:
        set_step(
            status,
            "evaluation_readiness",
            "PASS",
            evaluation_pairs=readiness[
                "evaluation_pairs"
            ],
        )

        status[
            "overall_status"
        ] = "CALIBRATION_BATCH_READY_FOR_INSPECTION"

        status[
            "next_action"
        ] = (
            "Inspect calibration_feature_report.json. "
            "Do not select matcher thresholds from evaluation data."
        )
    else:
        set_step(
            status,
            "evaluation_readiness",
            "WARNING_EMPTY",
            evaluation_pairs=0,
            reason=(
                "No internal evaluation pairs survived the session split."
            ),
        )

        status[
            "overall_status"
        ] = "READY_FOR_MORE_REAL_DATA"

        status[
            "next_action"
        ] = (
            "Collect more independent same-track sessions before "
            "using this batch for matcher evaluation."
        )

    write_status(
        batch_status_path,
        status,
    )

    return (
        0,
        status,
        batch_status_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Orquesta la preparación de un batch de calibración "
            "sin implementar matching automático."
        )
    )

    parser.add_argument(
        "input_dir",
        help=(
            "Directorio con JSON analyze_telemetry v3.8+."
        ),
    )

    parser.add_argument(
        "--project-root",
        default=str(
            Path(
                __file__
            ).resolve().parent
        ),
    )

    parser.add_argument(
        "--db",
        default="race_engineer_history.duckdb",
    )

    parser.add_argument(
        "--output-dir",
        default="calibration_batches",
    )

    parser.add_argument(
        "--track",
        default=None,
        help=(
            "Nombre exacto del circuito. Puede combinarse con "
            "--track-layout y --vehicle-variant."
        ),
    )

    parser.add_argument(
        "--track-layout",
        default=None,
        help=(
            "Layout LMU exacto. H2 exige layout explícito e idéntico "
            "para generar pares cross-session."
        ),
    )

    parser.add_argument(
        "--vehicle-variant",
        default=None,
        help=(
            "Variante normalizada exacta, por ejemplo "
            "LMP2_ELMS o LMP2_WEC."
        ),
    )

    parser.add_argument(
        "--recursive",
        action="store_true",
    )

    parser.add_argument(
        "--skip-import",
        action="store_true",
        help=(
            "No importar JSON; usar sólo el History DB existente."
        ),
    )

    parser.add_argument(
        "--labels",
        default=None,
        help=(
            "Archivo de labels existente. "
            "Por defecto usa pair_labels.json dentro del batch."
        ),
    )

    parser.add_argument(
        "--per-lens",
        type=int,
        default=6,
        help=(
            "Profundidad máxima por lente de selección. "
            "Default conservador para review humano inicial."
        ),
    )

    parser.add_argument(
        "--max-review-pairs",
        type=int,
        default=24,
        help=(
            "Máximo de pares para revisión humana. Default: 24. "
            "La cola se regenera si cambia esta política."
        ),
    )

    parser.add_argument(
        "--evaluation-fraction",
        type=float,
        default=0.25,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=20260810,
    )

    return parser


def print_summary(
    status: dict[str, Any],
    status_path: Path,
) -> None:
    print()
    print(
        "=" * 76
    )
    print(
        f"RACE ENGINEER - CALIBRATION BATCH ORCHESTRATOR v{ORCHESTRATOR_VERSION}"
    )
    print(
        "=" * 76
    )
    print()

    print(
        f"Overall: {status['overall_status']}"
    )

    if status.get(
        "track"
    ):
        print(
            f"Track: {status['track']}"
        )

    if status.get(
        "track_layout"
    ):
        print(
            f"Track layout: {status['track_layout']}"
        )

    if status.get(
        "vehicle_variant"
    ):
        print(
            f"Vehicle variant: {status['vehicle_variant']}"
        )

    if status.get(
        "batch_id"
    ):
        print(
            f"Batch ID: {status['batch_id']}"
        )

    print(
        f"Status: {status_path}"
    )

    print()

    for name, payload in status[
        "steps"
    ].items():
        print(
            f"{name}: {payload.get('status')}"
        )

    if status.get(
        "next_action"
    ):
        print()
        print(
            "NEXT ACTION"
        )
        print(
            status[
                "next_action"
            ]
        )

    print()
    print(
        f"MATCHER: {status['matcher'].get('status', 'UNKNOWN')}"
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        code, status, status_path = run_pipeline(
            args
        )
    except Exception as exc:
        print(
            f"FATAL ORCHESTRATOR ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    print_summary(
        status,
        status_path,
    )

    return code


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
