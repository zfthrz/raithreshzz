"""Explicitly import one exact H3 context after a verified History backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from authorized_episode_pair_matcher import DEFAULT_BATCHES_ROOT
from h3_import_readiness import (
    H3_IMPORTED,
    H3_READY_TO_IMPORT,
    H3Context,
    clear_h3_import_readiness_cache,
    discover_h3_import_readiness,
)
from maintain_h3_imports import DEFAULT_HISTORY_DB, audit_input_fingerprint, write_report
from run_h3_pipeline import import_h3_outputs
from runtime_paths import local_root


H3_CONTEXT_IMPORTER_VERSION = "0.1"
DEFAULT_BACKUP_ROOT = local_root() / "history_backups"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def backup_history_database(history_db: Path, backup_root: Path) -> dict[str, Any]:
    """Checkpoint and copy the closed-on-disk DuckDB image, then verify its hash."""

    import duckdb

    history_db = Path(history_db).resolve()
    if not history_db.is_file():
        raise FileNotFoundError(history_db)
    backup_root = Path(backup_root).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(history_db))
    try:
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    # Windows does not permit copying a DuckDB file while its connection holds
    # the file lock.  Hash before and after the short copy window so any
    # concurrent History writer makes this operation fail closed.
    source_sha = sha256_file(history_db)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_root / f"{history_db.stem}_before_h3_{timestamp}{history_db.suffix}"
    shutil.copy2(history_db, backup_path)
    backup_sha = sha256_file(backup_path)
    source_sha_after = sha256_file(history_db)

    if source_sha != backup_sha or source_sha_after != source_sha:
        raise RuntimeError(
            "History cambió durante el backup o la copia no coincide por SHA-256"
        )
    return {
        "path": str(backup_path),
        "sha256": backup_sha,
        "source_sha256": source_sha,
        "verified": True,
        "size_bytes": backup_path.stat().st_size,
    }


def import_context(
    context: H3Context,
    *,
    batches_root: Path = DEFAULT_BATCHES_ROOT,
    history_db: Path = DEFAULT_HISTORY_DB,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    apply: bool = False,
    expected_input_fingerprint: str | None = None,
    readiness_discoverer: Callable[..., dict[H3Context, dict[str, Any]]] = (
        discover_h3_import_readiness
    ),
    backupper: Callable[[Path, Path], dict[str, Any]] = backup_history_database,
    importer: Callable[[Path, Path, Path], dict[str, Any]] = import_h3_outputs,
) -> tuple[dict[str, Any], int]:
    """Validate, back up and import one exact context; fail closed throughout."""

    batches_root = Path(batches_root).resolve()
    history_db = Path(history_db).resolve()
    fingerprint = audit_input_fingerprint(
        batches_root=batches_root,
        history_db=history_db,
    )
    base = {
        "version": H3_CONTEXT_IMPORTER_VERSION,
        "mode": "APPLY_EXPLICIT" if apply else "AUDIT_READ_ONLY",
        "context": {
            "track": context.track,
            "track_layout": context.track_layout,
            "vehicle_variant": context.vehicle_variant,
        },
        "input_fingerprint": fingerprint,
        "history_db": str(history_db),
        "history_mutated": False,
        "historical_actions_authorized": False,
        "backup": None,
    }
    if expected_input_fingerprint is not None and expected_input_fingerprint != fingerprint:
        return {
            **base,
            "status": "BLOCKED_STALE_READINESS",
            "result": "BLOCKED",
            "reason": "input_fingerprint cambió desde la confirmación",
        }, 2

    current = readiness_discoverer(
        batches_root=batches_root,
        history_db=history_db,
    ).get(context)
    if not isinstance(current, dict):
        return {
            **base,
            "status": "BLOCKED_CONTEXT_NOT_FOUND",
            "result": "BLOCKED",
            "reason": "el contexto exacto no existe en readiness",
        }, 2
    if current.get("status") != H3_READY_TO_IMPORT:
        return {
            **base,
            "status": "BLOCKED_NOT_READY",
            "result": "BLOCKED",
            "readiness": current,
            "reason": f"estado actual: {current.get('status')}",
        }, 2

    patterns_path = Path(str(current.get("patterns_path") or "")).resolve()
    matches_path = Path(str(current.get("matches_path") or "")).resolve()
    ready = {
        **base,
        "status": "READY_TO_IMPORT",
        "result": "PASS",
        "readiness": current,
        "patterns_path": str(patterns_path),
        "matches_path": str(matches_path),
    }
    if not apply:
        return ready, 0

    try:
        backup = backupper(history_db, Path(backup_root).resolve())
        if backup.get("verified") is not True:
            raise RuntimeError("backup de History no verificado")
        import_result = importer(history_db, patterns_path, matches_path)
    except Exception as exc:
        return {
            **ready,
            "status": "FAILED",
            "result": "FAILED",
            "backup": locals().get("backup"),
            "reason": f"{type(exc).__name__}: {exc}",
        }, 1

    clear_h3_import_readiness_cache()
    post = readiness_discoverer(
        batches_root=batches_root,
        history_db=history_db,
    ).get(context)
    valid_import = (
        import_result.get("status") in {"RUN", "REUSED"}
        and isinstance(post, dict)
        and post.get("status") == H3_IMPORTED
    )
    if not valid_import:
        return {
            **ready,
            "status": "FAILED_POST_VALIDATION",
            "result": "FAILED",
            "backup": backup,
            "import_result": import_result,
            "post_import_readiness": post,
            "history_mutated": import_result.get("status") == "RUN",
            "reason": "History no quedó H3_IMPORTED para el contexto exacto",
        }, 1

    return {
        **ready,
        "status": "IMPORTED",
        "result": "PASS",
        "backup": backup,
        "import_result": import_result,
        "post_import_readiness": post,
        "history_mutated": import_result.get("status") == "RUN",
    }, 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importa un contexto H3 exacto con backup verificado de History."
    )
    parser.add_argument("--track", required=True)
    parser.add_argument("--track-layout", required=True)
    parser.add_argument("--vehicle-variant", required=True)
    parser.add_argument("--batches-root", type=Path, default=DEFAULT_BATCHES_ROOT)
    parser.add_argument("--history-db", type=Path, default=DEFAULT_HISTORY_DB)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--expected-input-fingerprint")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report, exit_code = import_context(
        H3Context(args.track, args.track_layout, args.vehicle_variant),
        batches_root=args.batches_root,
        history_db=args.history_db,
        backup_root=args.backup_root,
        apply=args.apply,
        expected_input_fingerprint=args.expected_input_fingerprint,
    )
    if args.output is not None:
        write_report(args.output, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code
    print("=" * 76)
    print(f"RACE ENGINEER - H3 CONTEXT IMPORTER v{H3_CONTEXT_IMPORTER_VERSION}")
    print("=" * 76)
    print(f"Mode:       {report['mode']}")
    print(f"Context:    {args.track} | {args.vehicle_variant}")
    print(f"Status:     {report['status']}")
    print(f"History:    {'MUTATED' if report['history_mutated'] else 'UNCHANGED'}")
    if isinstance(report.get("backup"), dict):
        print(f"Backup:     {report['backup'].get('path')}")
        print(f"SHA-256:    {report['backup'].get('sha256')}")
    if report.get("reason"):
        print(f"Reason:     {report['reason']}")
    print(f"RESULT:     {report['result']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
