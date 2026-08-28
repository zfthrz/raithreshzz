"""Read-only audit of exact contexts that could produce an official H3 bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from authorized_episode_pair_matcher import (
    DEFAULT_BATCHES_ROOT,
    classify_features_authorized,
)
from build_persistent_patterns import (
    DEFAULT_PERSISTENT_MIN_INDEPENDENT_SESSIONS,
    build_patterns,
)
from h2_authority_gate import validate_authorized_h2
from h3_import_readiness import H3_IMPORTED, discover_h3_import_readiness
from run_h3_pipeline import load_features
from runtime_paths import local_root


H3_MATERIALIZATION_READINESS_VERSION = "0.1"
MATERIALIZATION_READY = "MATERIALIZATION_READY"
NO_AUTHORIZED_MATCH = "NO_AUTHORIZED_MATCH"
CONFLICT_REVIEW_REQUIRED = "CONFLICT_REVIEW_REQUIRED"
MATERIALIZATION_FAILED = "MATERIALIZATION_FAILED"
ALREADY_MATERIALIZED = "ALREADY_MATERIALIZED"
DEFAULT_HISTORY_DB = local_root() / "race_engineer_history.duckdb"


def inspect_feature_materialization(
    features_path: Path,
    *,
    batches_root: Path,
    classifier: Callable = classify_features_authorized,
    gate_validator: Callable = validate_authorized_h2,
    pattern_builder: Callable = build_patterns,
) -> dict[str, Any]:
    """Run production H2/H3 logic in memory without writing its outputs."""

    features = load_features(Path(features_path))
    decisions, metadata = classifier(features, batches_root=Path(batches_root))
    gate = gate_validator(features, decisions, metadata)
    match_count = int(gate["decision_counts"].get("MATCH") or 0)
    if match_count == 0:
        return {
            "status": NO_AUTHORIZED_MATCH,
            "feature_count": len(features),
            "h2_gate": gate,
            "reason": "el matcher autorizado no produjo MATCH",
        }

    _patterns, summary = pattern_builder(
        features,
        decisions,
        persistent_min_sessions=DEFAULT_PERSISTENT_MIN_INDEPENDENT_SESSIONS,
    )
    conflict_count = int(summary.get("conflict_review_required_count") or 0)
    return {
        "status": (
            CONFLICT_REVIEW_REQUIRED if conflict_count else MATERIALIZATION_READY
        ),
        "feature_count": len(features),
        "h2_gate": gate,
        "h3_summary": summary,
        "reason": (
            "conflict_review_required"
            if conflict_count
            else "H2 autorizado y H3 sin conflictos"
        ),
    }


def audit_h3_materialization_readiness(
    *,
    batches_root: Path = DEFAULT_BATCHES_ROOT,
    history_db: Path = DEFAULT_HISTORY_DB,
    inspector: Callable = inspect_feature_materialization,
) -> dict[str, Any]:
    """Audit the newest/largest exact-context feature set selected by readiness."""

    readiness = discover_h3_import_readiness(
        batches_root=Path(batches_root),
        history_db=Path(history_db),
    )
    rows = []
    for context, existing in sorted(
        readiness.items(),
        key=lambda item: (
            item[0].track,
            item[0].track_layout,
            item[0].vehicle_variant,
        ),
    ):
        base = {
            "track": context.track,
            "track_layout": context.track_layout,
            "vehicle_variant": context.vehicle_variant,
            "batch_id": existing.get("batch_id"),
            "features_path": existing.get("features_path"),
            "existing_h3_status": existing.get("status"),
        }
        if existing.get("status") == H3_IMPORTED:
            rows.append({**base, "status": ALREADY_MATERIALIZED})
            continue
        try:
            inspection = inspector(
                Path(str(existing["features_path"])),
                batches_root=Path(batches_root),
            )
            rows.append({**base, **inspection})
        except Exception as exc:
            rows.append({
                **base,
                "status": MATERIALIZATION_FAILED,
                "reason": f"{type(exc).__name__}: {exc}",
            })

    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "version": H3_MATERIALIZATION_READINESS_VERSION,
        "mode": "AUDIT_READ_ONLY",
        "context_count": len(rows),
        "status_counts": counts,
        "contexts": rows,
        "files_written": 0,
        "history_mutated": False,
        "historical_actions_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita en memoria qué contextos pueden materializar H3 oficial."
    )
    parser.add_argument("--batches-root", type=Path, default=DEFAULT_BATCHES_ROOT)
    parser.add_argument("--history-db", type=Path, default=DEFAULT_HISTORY_DB)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit_h3_materialization_readiness(
        batches_root=args.batches_root,
        history_db=args.history_db,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print("=" * 76)
    print("RACE ENGINEER - H3 MATERIALIZATION READINESS v0.1")
    print("=" * 76)
    print(f"Mode:       {report['mode']}")
    print(f"Contexts:   {report['context_count']}")
    for status, count in sorted(report["status_counts"].items()):
        print(f"  {status}: {count}")
    for row in report["contexts"]:
        print(
            f"{row['track']} | {row['vehicle_variant']}: {row['status']}"
        )
    print("Files:      0 written")
    print("History:    UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
