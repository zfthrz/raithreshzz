from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from authorized_episode_pair_matcher import (
    DEFAULT_BATCHES_ROOT,
    classify_features_authorized,
)
from build_persistent_patterns import (
    DEFAULT_PERSISTENT_MIN_INDEPENDENT_SESSIONS,
    H3_VERSION,
    PATTERN_SCHEMA_VERSION,
    build_patterns,
)
from h2_authority_gate import validate_authorized_h2

H3_PIPELINE_VERSION = "0.1"
DEFAULT_MATCHES_FILENAME = "episode_pair_matches.json"
DEFAULT_PATTERNS_FILENAME = "persistent_patterns.json"
DEFAULT_REPORT_FILENAME = "h3_pipeline_report.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_features(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("episode_pair_features debe ser una lista JSON.")
    return [row for row in raw if isinstance(row, dict)]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_h3_pipeline(
    features_path: Path,
    *,
    output_dir: Path | None = None,
    batches_root: Path = DEFAULT_BATCHES_ROOT,
    persistent_min_sessions: int = DEFAULT_PERSISTENT_MIN_INDEPENDENT_SESSIONS,
) -> tuple[dict[str, Any], int]:
    """Official H2 -> H3 batch path.

    Uses the production authorization layer for every context. Exact variant
    calibration remains exact; promoted track/layout baseline may contribute
    production MATCH only. No History import is performed here.
    """
    features_path = Path(features_path).resolve()
    if not features_path.is_file():
        raise FileNotFoundError(features_path)
    if persistent_min_sessions < 3:
        raise ValueError("persistent_min_sessions debe ser >= 3.")

    target_dir = (
        Path(output_dir).resolve()
        if output_dir is not None
        else features_path.parent
    )
    batches_root = Path(batches_root).resolve()

    features = load_features(features_path)
    decisions, matcher_metadata = classify_features_authorized(
        features,
        batches_root=batches_root,
    )

    matcher_metadata = dict(matcher_metadata)
    matcher_metadata.update({
        "created_at_utc": utc_now_iso(),
        "source_features": str(features_path),
        "source_features_sha256": sha256_file(features_path),
        "pipeline_version": H3_PIPELINE_VERSION,
        "policy": (
            "Production-authorized H2 decisions. Exact variant calibration keeps "
            "its calibrated MATCH/REJECT authority; promoted track baseline can "
            "authorize MATCH only; inherited REJECT remains forbidden."
        ),
    })

    gate = validate_authorized_h2(features, decisions, matcher_metadata)

    matches_path = target_dir / DEFAULT_MATCHES_FILENAME
    patterns_path = target_dir / DEFAULT_PATTERNS_FILENAME
    report_path = target_dir / DEFAULT_REPORT_FILENAME

    matches_payload = {
        "metadata": matcher_metadata,
        # Preserve the historical top-level counts contract for existing tools.
        "counts": dict(matcher_metadata.get("decision_counts") or {}),
        "decisions": decisions,
    }
    write_json(matches_path, matches_payload)

    patterns, summary = build_patterns(
        features,
        decisions,
        persistent_min_sessions=persistent_min_sessions,
    )

    patterns_payload = {
        "metadata": {
            "schema_version": PATTERN_SCHEMA_VERSION,
            "h3_version": H3_VERSION,
            "h3_pipeline_version": H3_PIPELINE_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_features": str(features_path),
            "source_matches": str(matches_path),
            "matcher_version": gate["matcher_version"],
            "matcher_status": matcher_metadata.get("matcher_status"),
            "authorized_matcher_version": matcher_metadata.get(
                "authorized_matcher_version"
            ),
            "track_baseline_policy_version": matcher_metadata.get(
                "track_baseline_policy_version"
            ),
            "match_promotion_policy_version": matcher_metadata.get(
                "match_promotion_policy_version"
            ),
            "persistent_min_independent_sessions": persistent_min_sessions,
            "h2_authority_gate": gate,
            "equivalence_policy": (
                "MATCH is transitive: A=B and B=C implies A=C. Internal "
                "AMBIGUOUS pairs are resolved by equivalence closure; internal "
                "REJECT pairs are contradictions requiring audit."
            ),
            "within_session_repeat_evidence_available": False,
            "history_imported": False,
            "policy": (
                "Derived H3 evidence only. Does not mutate History DB, does not "
                "select historical_reference, and does not alter coaching."
            ),
        },
        "summary": summary,
        "patterns": patterns,
    }
    write_json(patterns_path, patterns_payload)

    conflict_count = int(summary.get("conflict_review_required_count") or 0)
    result = "REVIEW_REQUIRED" if conflict_count else "PASS"
    exit_code = 2 if conflict_count else 0

    report = {
        "pipeline_version": H3_PIPELINE_VERSION,
        "created_at_utc": utc_now_iso(),
        "result": result,
        "source_features": str(features_path),
        "output_dir": str(target_dir),
        "outputs": {
            "episode_pair_matches": str(matches_path),
            "persistent_patterns": str(patterns_path),
        },
        "h2_gate": gate,
        "h3_summary": summary,
        "history_imported": False,
        "history_mutated": False,
    }
    write_json(report_path, report)
    report["outputs"]["report"] = str(report_path)
    return report, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "H3 batch pipeline: production-authorized H2 -> persistent pattern "
            "builder. Does not import History."
        )
    )
    parser.add_argument("features_json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--batches-root",
        type=Path,
        default=DEFAULT_BATCHES_ROOT,
    )
    parser.add_argument(
        "--persistent-min-sessions",
        type=int,
        default=DEFAULT_PERSISTENT_MIN_INDEPENDENT_SESSIONS,
    )
    args = parser.parse_args()

    report, exit_code = run_h3_pipeline(
        args.features_json,
        output_dir=args.output_dir,
        batches_root=args.batches_root,
        persistent_min_sessions=args.persistent_min_sessions,
    )

    h2 = report["h2_gate"]
    h3 = report["h3_summary"]
    print("=" * 78)
    print(f"RACE ENGINEER - H3 PIPELINE v{H3_PIPELINE_VERSION}")
    print("=" * 78)
    print(
        "H2 decisions: "
        f"MATCH={h2['decision_counts'].get('MATCH', 0)} "
        f"AMBIGUOUS={h2['decision_counts'].get('AMBIGUOUS', 0)} "
        f"REJECT={h2['decision_counts'].get('REJECT', 0)}"
    )
    print(f"H2 authority scopes:        {h2['authority_scope_counts']}")
    print(f"Inherited REJECT escaped:   {h2['inherited_reject_count']}")
    print(f"Unauthorized MATCH:         {h2['unauthorized_match_count']}")
    print(f"H3 patterns/classes:        {h3.get('pattern_count', 0)}")
    print(f"H3 states:                  {h3.get('state_counts') or {}}")
    print(f"H3 conflicts:               {h3.get('conflict_review_required_count', 0)}")
    print(f"History imported:           {report['history_imported']}")
    print(f"Result:                     {report['result']}")
    print(f"Matches:                    {report['outputs']['episode_pair_matches']}")
    print(f"Patterns:                   {report['outputs']['persistent_patterns']}")
    print(f"Report:                     {report['outputs']['report']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
