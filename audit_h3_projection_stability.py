"""Read-only stability audit for H3.2 calibrated projection artifacts."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_paths import generated_root


AUDIT_VERSION = "0.1"
SELECTION_FILENAME = "persistent_pattern_selection.json"
EXPECTED_BASIS = "calibrated_h2_match_to_pattern_representative"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _context(metadata: dict[str, Any]) -> tuple[str, str, str] | None:
    value = metadata.get("context")
    if not isinstance(value, dict):
        return None
    result = (
        value.get("track"),
        value.get("track_layout"),
        value.get("vehicle_variant"),
    )
    if not all(isinstance(item, str) and item for item in result):
        return None
    return result


def _authority_valid(metadata: dict[str, Any]) -> bool:
    return (
        metadata.get("observational_only") is True
        and metadata.get("affects_next_stint_plan") is False
        and metadata.get("historical_actions_authorized") is False
    )


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def audit_h3_projection_stability(generated: Path) -> dict[str, Any]:
    paths = sorted((generated / "h3_1").glob(f"*/{SELECTION_FILENAME}"))
    exact_sessions: dict[tuple[str, str, str, str], set[int]] = defaultdict(set)
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    pattern_contexts: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    rule_edge_counts: Counter[str] = Counter()
    state_edge_counts: Counter[str] = Counter()
    invalid_artifact_count = 0
    authority_violation_count = 0
    projection_contract_violation_count = 0
    duplicate_edge_count = 0
    seen_edges: set[tuple[Any, ...]] = set()

    documents: list[tuple[dict[str, Any], tuple[str, str, str]]] = []
    for path in paths:
        document = _load(path)
        metadata = document.get("metadata") if isinstance(document, dict) else None
        if not isinstance(metadata, dict):
            invalid_artifact_count += 1
            continue
        context = _context(metadata)
        exact = document.get("matched_patterns")
        projected = document.get("projected_pattern_matches")
        if context is None or not isinstance(exact, list) or not isinstance(projected, list):
            invalid_artifact_count += 1
            continue
        if not _authority_valid(metadata):
            authority_violation_count += 1
        documents.append((document, context))
        session_id = metadata.get("session_id")
        if not isinstance(session_id, int):
            continue
        for item in exact:
            pattern_id = item.get("pattern_id") if isinstance(item, dict) else None
            if isinstance(pattern_id, str) and pattern_id:
                exact_sessions[(*context, pattern_id)].add(session_id)

    for document, context in documents:
        metadata = document["metadata"]
        session_id = metadata.get("session_id")
        if not isinstance(session_id, int):
            continue
        provenance = document.get("provenance")
        bundle_hash = (
            provenance.get("source_bundle_sha256")
            if isinstance(provenance, dict)
            else None
        )
        for item in document["projected_pattern_matches"]:
            if not isinstance(item, dict):
                projection_contract_violation_count += 1
                continue
            pattern_id = item.get("pattern_id")
            current = item.get("current_session_episode")
            episode_pk = current.get("episode_pk") if isinstance(current, dict) else None
            decision = item.get("matcher_decision")
            contract_valid = (
                isinstance(pattern_id, str)
                and bool(pattern_id)
                and item.get("match_basis") == EXPECTED_BASIS
                and isinstance(decision, dict)
                and decision.get("decision") == "MATCH"
                and decision.get("automatic") is True
                and episode_pk is not None
            )
            if not contract_valid:
                projection_contract_violation_count += 1
                continue
            edge_identity = (*context, pattern_id, session_id, episode_pk)
            if edge_identity in seen_edges:
                duplicate_edge_count += 1
                continue
            seen_edges.add(edge_identity)
            key = (*context, pattern_id)
            pattern_contexts[pattern_id].add(context)
            group = groups.setdefault(
                key,
                {
                    "context": {
                        "track": context[0],
                        "track_layout": context[1],
                        "vehicle_variant": context[2],
                    },
                    "pattern_id": pattern_id,
                    "pattern_states": set(),
                    "projected_session_ids": set(),
                    "projected_edge_count": 0,
                    "current_episode_pks": set(),
                    "matcher_rule_ids": set(),
                    "source_bundle_sha256": set(),
                    "declared_independent_session_counts": set(),
                },
            )
            state = str(item.get("state") or "STATE_UNAVAILABLE")
            rule_id = str(decision.get("rule_id") or "RULE_UNAVAILABLE")
            state_edge_counts[state] += 1
            rule_edge_counts[rule_id] += 1
            group["pattern_states"].add(state)
            group["projected_session_ids"].add(session_id)
            group["projected_edge_count"] += 1
            group["current_episode_pks"].add(int(episode_pk))
            group["matcher_rule_ids"].add(rule_id)
            if isinstance(bundle_hash, str) and bundle_hash:
                group["source_bundle_sha256"].add(bundle_hash)
            support = item.get("independent_session_count")
            if isinstance(support, int):
                group["declared_independent_session_counts"].add(support)

    rows: list[dict[str, Any]] = []
    session_distribution: Counter[str] = Counter()
    context_summary: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key in sorted(groups):
        group = groups[key]
        projected_sessions = sorted(group["projected_session_ids"])
        exact = sorted(exact_sessions.get(key, set()))
        session_distribution[str(len(projected_sessions))] += 1
        context_key = key[:3]
        context_row = context_summary.setdefault(
            context_key,
            {
                "context": group["context"],
                "projected_pattern_count": 0,
                "projected_edge_count": 0,
                "projected_session_ids": set(),
                "patterns_in_multiple_projected_sessions": 0,
                "patterns_also_seen_as_exact_runtime_membership": 0,
            },
        )
        context_row["projected_pattern_count"] += 1
        context_row["projected_edge_count"] += group["projected_edge_count"]
        context_row["projected_session_ids"].update(projected_sessions)
        context_row["patterns_in_multiple_projected_sessions"] += (
            len(projected_sessions) > 1
        )
        context_row["patterns_also_seen_as_exact_runtime_membership"] += bool(exact)
        rows.append(
            {
                "context": group["context"],
                "pattern_id": group["pattern_id"],
                "pattern_states": sorted(group["pattern_states"]),
                "projected_session_ids": projected_sessions,
                "projected_independent_session_count": len(projected_sessions),
                "projected_edge_count": group["projected_edge_count"],
                "current_episode_pks": sorted(group["current_episode_pks"]),
                "matcher_rule_ids": sorted(group["matcher_rule_ids"]),
                "source_bundle_sha256": sorted(group["source_bundle_sha256"]),
                "declared_independent_session_counts": sorted(
                    group["declared_independent_session_counts"]
                ),
                "exact_runtime_membership_session_ids": exact,
                "also_seen_as_exact_runtime_membership": bool(exact),
            }
        )

    context_rows = []
    for key in sorted(context_summary):
        row = context_summary[key]
        row["projected_session_ids"] = sorted(row["projected_session_ids"])
        row["projected_session_count"] = len(row["projected_session_ids"])
        context_rows.append(row)
    cross_context_ids = sorted(
        pattern_id
        for pattern_id, contexts in pattern_contexts.items()
        if len(contexts) > 1
    )
    return {
        "metadata": {
            "audit_version": AUDIT_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "H3_PROJECTION_STABILITY_AUDIT",
            "observational_only": True,
            "input_artifacts_mutated": False,
            "history_opened": False,
            "matcher_called": False,
            "llm_called": False,
            "threshold_applied": False,
            "labels_generated": False,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
        },
        "summary": {
            "selection_artifact_count": len(paths),
            "invalid_artifact_count": invalid_artifact_count,
            "projected_pattern_count": len(rows),
            "projected_edge_count": len(seen_edges),
            "projected_session_count": len({
                session_id
                for row in rows
                for session_id in row["projected_session_ids"]
            }),
            "patterns_in_multiple_projected_sessions": sum(
                row["projected_independent_session_count"] > 1 for row in rows
            ),
            "patterns_also_seen_as_exact_runtime_membership": sum(
                row["also_seen_as_exact_runtime_membership"] for row in rows
            ),
            "projected_session_count_distribution": _sorted_counter(
                session_distribution
            ),
            "matcher_rule_edge_counts": _sorted_counter(rule_edge_counts),
            "pattern_state_edge_counts": _sorted_counter(state_edge_counts),
        },
        "review_signals": {
            "authority_contract_violation_count": authority_violation_count,
            "projection_contract_violation_count": projection_contract_violation_count,
            "duplicate_projection_edge_count": duplicate_edge_count,
            "cross_context_pattern_id_collision_count": len(cross_context_ids),
            "cross_context_pattern_id_collisions": cross_context_ids,
            "interpretation": (
                "Repeated projection is observational stability evidence only. "
                "No count is a threshold, label, membership or promotion decision."
            ),
        },
        "contexts": context_rows,
        "patterns": rows,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita estabilidad de proyecciones H3.2 sin promover evidencia."
    )
    parser.add_argument("--generated-root", type=Path, default=generated_root())
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            generated_root()
            / "diagnostics"
            / "h3_projection_stability_audit.json"
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit_h3_projection_stability(args.generated_root)
    write_report(args.output, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    summary = report["summary"]
    review = report["review_signals"]
    print("=" * 76)
    print(f"RACE ENGINEER - H3.2 PROJECTION STABILITY AUDIT v{AUDIT_VERSION}")
    print("=" * 76)
    print(f"Projection edges:       {summary['projected_edge_count']}")
    print(f"Projected patterns:     {summary['projected_pattern_count']}")
    print(f"Projected sessions:     {summary['projected_session_count']}")
    print(
        "Multi-session patterns: "
        f"{summary['patterns_in_multiple_projected_sessions']}"
    )
    print(f"Rule edges:             {summary['matcher_rule_edge_counts']}")
    print(
        "Review signals:         "
        f"authority={review['authority_contract_violation_count']} "
        f"contract={review['projection_contract_violation_count']} "
        f"duplicates={review['duplicate_projection_edge_count']}"
    )
    print("Authority:              OBSERVATIONAL ONLY")
    print(f"Output:                 {args.output.resolve()}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
