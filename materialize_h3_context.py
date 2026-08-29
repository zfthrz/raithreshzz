"""Explicitly materialize one exact H3 context without importing History."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from audit_h3_materialization_readiness import (
    DEFAULT_HISTORY_DB,
    MATERIALIZATION_READY,
    audit_h3_materialization_readiness,
    audit_input_fingerprint,
)
from authorized_episode_pair_matcher import DEFAULT_BATCHES_ROOT
from h3_import_readiness import (
    H3_READY_TO_IMPORT,
    H3Context,
    clear_h3_import_readiness_cache,
    discover_h3_import_readiness,
)
from maintain_h3_imports import write_report
from run_h3_pipeline import run_h3_pipeline


MATERIALIZER_VERSION = "0.1"


def _same_context(row: dict[str, Any], context: H3Context) -> bool:
    return (
        row.get("track") == context.track
        and row.get("track_layout") == context.track_layout
        and row.get("vehicle_variant") == context.vehicle_variant
    )


def materialize_context(
    context: H3Context,
    *,
    batches_root: Path = DEFAULT_BATCHES_ROOT,
    history_db: Path = DEFAULT_HISTORY_DB,
    apply: bool = False,
    expected_input_fingerprint: str | None = None,
    readiness_auditor: Callable[..., dict[str, Any]] = (
        audit_h3_materialization_readiness
    ),
    pipeline_runner: Callable[..., tuple[dict[str, Any], int]] = run_h3_pipeline,
    readiness_discoverer: Callable[..., dict[H3Context, dict[str, Any]]] = (
        discover_h3_import_readiness
    ),
) -> tuple[dict[str, Any], int]:
    """Materialize one fresh, exact readiness row; never import History."""

    batches_root = Path(batches_root).resolve()
    history_db = Path(history_db).resolve()
    fingerprint = audit_input_fingerprint(
        batches_root=batches_root,
        history_db=history_db,
    )
    base = {
        "version": MATERIALIZER_VERSION,
        "mode": "APPLY_EXPLICIT" if apply else "AUDIT_READ_ONLY",
        "context": {
            "track": context.track,
            "track_layout": context.track_layout,
            "vehicle_variant": context.vehicle_variant,
        },
        "input_fingerprint": fingerprint,
        "files_written": [],
        "history_mutated": False,
        "historical_actions_authorized": False,
    }
    if (
        expected_input_fingerprint is not None
        and expected_input_fingerprint != fingerprint
    ):
        return {
            **base,
            "status": "BLOCKED_STALE_READINESS",
            "result": "BLOCKED",
            "reason": "input_fingerprint cambió desde la confirmación",
        }, 2

    readiness = readiness_auditor(
        batches_root=batches_root,
        history_db=history_db,
    )
    matching = [
        row
        for row in readiness.get("contexts", [])
        if isinstance(row, dict) and _same_context(row, context)
    ]
    if len(matching) != 1:
        return {
            **base,
            "status": "BLOCKED_CONTEXT_NOT_FOUND",
            "result": "BLOCKED",
            "reason": f"contextos exactos encontrados: {len(matching)}",
        }, 2

    selected = matching[0]
    if selected.get("status") != MATERIALIZATION_READY:
        return {
            **base,
            "status": "BLOCKED_NOT_READY",
            "result": "BLOCKED",
            "readiness": selected,
            "reason": f"estado actual: {selected.get('status')}",
        }, 2

    features_path = Path(str(selected.get("features_path") or "")).resolve()
    if not features_path.is_file():
        return {
            **base,
            "status": "FAILED",
            "result": "FAILED",
            "readiness": selected,
            "reason": f"features ausentes: {features_path}",
        }, 1

    ready_report = {
        **base,
        "status": "READY_TO_MATERIALIZE",
        "result": "PASS",
        "readiness": selected,
        "features_path": str(features_path),
        "output_dir": str(features_path.parent),
    }
    if not apply:
        return ready_report, 0

    try:
        pipeline, pipeline_code = pipeline_runner(
            features_path,
            output_dir=features_path.parent,
            batches_root=batches_root,
            history_db=None,
        )
    except Exception as exc:
        return {
            **ready_report,
            "status": "FAILED",
            "result": "FAILED",
            "reason": f"{type(exc).__name__}: {exc}",
        }, 1

    outputs = pipeline.get("outputs") if isinstance(pipeline, dict) else None
    written = []
    if isinstance(outputs, dict):
        written = [
            str(Path(outputs[key]).resolve())
            for key in (
                "episode_pair_matches",
                "persistent_patterns",
                "report",
            )
            if isinstance(outputs.get(key), str) and Path(outputs[key]).is_file()
        ]
    pipeline_valid = (
        isinstance(pipeline, dict)
        and pipeline_code == 0
        and pipeline.get("result") == "PASS"
        and pipeline.get("history_mutated") is False
        and pipeline.get("history_imported") is False
        and len(written) == 3
    )
    if not pipeline_valid:
        return {
            **ready_report,
            "status": "FAILED",
            "result": "FAILED",
            "pipeline": pipeline,
            "files_written": written,
            "reason": "el pipeline no cumplió el contrato de materialización",
        }, 1

    clear_h3_import_readiness_cache()
    post = readiness_discoverer(
        batches_root=batches_root,
        history_db=history_db,
    ).get(context)
    if not isinstance(post, dict) or post.get("status") != H3_READY_TO_IMPORT:
        return {
            **ready_report,
            "status": "FAILED_POST_VALIDATION",
            "result": "FAILED",
            "pipeline": pipeline,
            "files_written": written,
            "post_materialization_readiness": post,
            "reason": "el bundle materializado no quedó H3_READY_TO_IMPORT",
        }, 1

    return {
        **ready_report,
        "status": "MATERIALIZED_READY_TO_IMPORT",
        "result": "PASS",
        "pipeline": pipeline,
        "files_written": written,
        "post_materialization_readiness": post,
    }, 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materializa un contexto H3 exacto sin importar History."
    )
    parser.add_argument("--track", required=True)
    parser.add_argument("--track-layout", required=True)
    parser.add_argument("--vehicle-variant", required=True)
    parser.add_argument("--batches-root", type=Path, default=DEFAULT_BATCHES_ROOT)
    parser.add_argument("--history-db", type=Path, default=DEFAULT_HISTORY_DB)
    parser.add_argument("--expected-input-fingerprint")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report, exit_code = materialize_context(
        H3Context(args.track, args.track_layout, args.vehicle_variant),
        batches_root=args.batches_root,
        history_db=args.history_db,
        apply=args.apply,
        expected_input_fingerprint=args.expected_input_fingerprint,
    )
    if args.output is not None:
        write_report(args.output, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code
    print("=" * 76)
    print(f"RACE ENGINEER - H3 CONTEXT MATERIALIZER v{MATERIALIZER_VERSION}")
    print("=" * 76)
    print(f"Mode:       {report['mode']}")
    print(f"Context:    {args.track} | {args.vehicle_variant}")
    print(f"Status:     {report['status']}")
    print(f"History:    {'MUTATED' if report['history_mutated'] else 'UNCHANGED'}")
    print(f"Files:      {len(report['files_written'])} written")
    if report.get("reason"):
        print(f"Reason:     {report['reason']}")
    print(f"RESULT:     {report['result']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
