"""Audit and explicitly import already-materialized official H3 bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from authorized_episode_pair_matcher import DEFAULT_BATCHES_ROOT
from h3_import_readiness import (
    H3_READY_TO_IMPORT,
    H3Context,
    clear_h3_import_readiness_cache,
    discover_h3_import_readiness,
)
from run_h3_pipeline import import_h3_outputs
from runtime_paths import local_root


H3_IMPORT_MAINTENANCE_VERSION = "0.2"
DEFAULT_HISTORY_DB = local_root() / "race_engineer_history.duckdb"
DEFAULT_STATE_PATH = local_root() / "h3_import_maintenance.json"
FINGERPRINT_FILENAMES = {
    "persistent_patterns.json",
    "episode_pair_matches.json",
    "h3_pipeline_report.json",
}


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Publish a complete audit snapshot without exposing a partial JSON file."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def audit_input_fingerprint(*, batches_root: Path, history_db: Path) -> str:
    """Cheap change detector only; production validators still own readiness."""

    paths = [Path(history_db)]
    root = Path(batches_root)
    if root.is_dir():
        paths.extend(
            path
            for path in root.rglob("*.json")
            if path.name in FINGERPRINT_FILENAMES
        )
    records = []
    for path in sorted(paths, key=lambda item: str(item).casefold()):
        try:
            stat = path.stat()
            records.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
        except OSError:
            records.append((str(path.resolve()), None, None))
    encoded = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def reusable_report(path: Path, *, input_fingerprint: str) -> dict[str, Any] | None:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(report, dict):
        return None
    if report.get("mode") != "AUDIT_READ_ONLY":
        return None
    if report.get("input_fingerprint") != input_fingerprint:
        return None
    if report.get("history_mutated") is not False:
        return None
    return report


def _context_payload(context: H3Context, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "track": context.track,
        "track_layout": context.track_layout,
        "vehicle_variant": context.vehicle_variant,
        **row,
    }


def audit_h3_imports(
    *,
    batches_root: Path = DEFAULT_BATCHES_ROOT,
    history_db: Path = DEFAULT_HISTORY_DB,
) -> dict[str, Any]:
    """Return the existing read-only readiness result in stable context order."""

    rows = discover_h3_import_readiness(
        batches_root=Path(batches_root),
        history_db=Path(history_db),
    )
    contexts = [
        _context_payload(context, row)
        for context, row in sorted(
            rows.items(),
            key=lambda item: (
                item[0].track,
                item[0].track_layout,
                item[0].vehicle_variant,
            ),
        )
    ]
    counts: dict[str, int] = {}
    for row in contexts:
        status = str(row.get("status") or "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return {
        "version": H3_IMPORT_MAINTENANCE_VERSION,
        "mode": "AUDIT_READ_ONLY",
        "batches_root": str(Path(batches_root).resolve()),
        "history_db": str(Path(history_db).resolve()),
        "context_count": len(contexts),
        "status_counts": counts,
        "contexts": contexts,
        "history_mutated": False,
        "historical_actions_authorized": False,
    }


def apply_ready_h3_imports(
    *,
    batches_root: Path = DEFAULT_BATCHES_ROOT,
    history_db: Path = DEFAULT_HISTORY_DB,
    importer: Callable[[Path, Path, Path], dict[str, Any]] = import_h3_outputs,
) -> tuple[dict[str, Any], int]:
    """Import only bundles that passed the existing production readiness gate."""

    audit = audit_h3_imports(batches_root=batches_root, history_db=history_db)
    results = []
    failed = 0
    for row in audit["contexts"]:
        if row.get("status") != H3_READY_TO_IMPORT:
            continue
        try:
            result = importer(
                Path(history_db),
                Path(str(row["patterns_path"])),
                Path(str(row["matches_path"])),
            )
            results.append({
                "track": row["track"],
                "track_layout": row["track_layout"],
                "vehicle_variant": row["vehicle_variant"],
                "batch_id": row.get("batch_id"),
                **result,
            })
        except Exception as exc:
            failed += 1
            results.append({
                "track": row["track"],
                "track_layout": row["track_layout"],
                "vehicle_variant": row["vehicle_variant"],
                "batch_id": row.get("batch_id"),
                "status": "FAILED",
                "reason": f"{type(exc).__name__}: {exc}",
            })

    clear_h3_import_readiness_cache()
    report = {
        **audit,
        "mode": "APPLY_EXPLICIT",
        "ready_before_apply": len(results),
        "import_results": results,
        "history_mutated": any(row.get("status") == "RUN" for row in results),
        "result": "FAILED" if failed else "PASS",
    }
    return report, 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audita bundles H3 existentes y, sólo con --apply, importa los que "
            "ya pasan el gate oficial de readiness."
        )
    )
    parser.add_argument("--batches-root", type=Path, default=DEFAULT_BATCHES_ROOT)
    parser.add_argument("--history-db", type=Path, default=DEFAULT_HISTORY_DB)
    parser.add_argument(
        "--output",
        type=Path,
        help="Guardar atómicamente el reporte JSON (audit o apply).",
    )
    parser.add_argument(
        "--reuse-unchanged-output",
        action="store_true",
        help="Reutilizar --output si el fingerprint barato de entradas no cambió.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Importación explícita de todos los bundles H3_READY_TO_IMPORT.",
    )
    parser.add_argument("--json", action="store_true", help="Imprimir JSON completo.")
    args = parser.parse_args()

    input_fingerprint = audit_input_fingerprint(
        batches_root=args.batches_root,
        history_db=args.history_db,
    )
    reused = False
    cached = (
        reusable_report(args.output, input_fingerprint=input_fingerprint)
        if args.reuse_unchanged_output and args.output is not None and not args.apply
        else None
    )
    if cached is not None:
        report = cached
        exit_code = 0
        reused = True
    elif args.apply:
        report, exit_code = apply_ready_h3_imports(
            batches_root=args.batches_root,
            history_db=args.history_db,
        )
    else:
        report = audit_h3_imports(
            batches_root=args.batches_root,
            history_db=args.history_db,
        )
        exit_code = 0

    report["input_fingerprint"] = input_fingerprint

    if args.output is not None and not reused:
        write_report(args.output, report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code

    print("=" * 76)
    print("RACE ENGINEER - H3 IMPORT MAINTENANCE v0.2")
    print("=" * 76)
    print(f"Mode:             {report['mode']}")
    print(f"Execution:        {'REUSED' if reused else 'RUN'}")
    print(f"Contexts:         {report['context_count']}")
    for status, count in sorted(report["status_counts"].items()):
        print(f"  {status}: {count}")
    if args.apply:
        print(f"Ready processed:  {report['ready_before_apply']}")
        for row in report["import_results"]:
            print(
                f"  {row['track']} | {row['vehicle_variant']}: "
                f"{row.get('status', 'UNKNOWN')}"
            )
        print(f"RESULT:           {report['result']}")
    else:
        print("History:          UNCHANGED")
        if args.output is not None:
            print(f"State:            {args.output.resolve()}")
        print("NEXT ACTION:      add --apply only after reviewing this audit")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
