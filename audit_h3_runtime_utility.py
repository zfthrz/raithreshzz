"""Read-only corpus audit for H3 runtime coverage and utility.

The audit consumes generated H3.1/H4/H5.2 JSON artifacts.  It never opens
History, runs the matcher, changes a selection, or authorizes coaching.
"""

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
H3_SELECTION_FILENAME = "persistent_pattern_selection.json"
H4_SELECTION_FILENAME = "historical_reference_selection.json"
H5_COMPARISON_FILENAME = "cross_session_comparison.json"
RECURRENT_STATES = {"persistent_pattern", "cross_session_repeat"}


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _counter(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _context_key(context: dict[str, Any]) -> tuple[str, str, str] | None:
    values = (
        context.get("track"),
        context.get("track_layout"),
        context.get("vehicle_variant"),
    )
    if not all(isinstance(value, str) and value for value in values):
        return None
    return values


def _same_context(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _context_key(left) is not None and _context_key(left) == _context_key(right)


def _h4_status(path: Path, context: dict[str, Any]) -> tuple[bool, str]:
    document = _load_json(path)
    if document is None:
        return False, "MISSING_OR_INVALID"
    status = document.get("selection_status")
    target = document.get("target_session")
    if not isinstance(target, dict) or not _same_context(context, target):
        return False, "CONTEXT_INVALID"
    return status == "HISTORICAL_REFERENCE_SELECTED", str(
        status or "STATUS_UNAVAILABLE"
    )


def _h5_status(path: Path, context: dict[str, Any]) -> tuple[bool, str]:
    document = _load_json(path)
    if document is None:
        return False, "MISSING_OR_INVALID"
    status = document.get("status")
    h5_context = document.get("context")
    metadata = document.get("metadata")
    policy = metadata.get("policy") if isinstance(metadata, dict) else None
    if not isinstance(h5_context, dict) or not _same_context(context, h5_context):
        return False, "CONTEXT_INVALID"
    if not isinstance(policy, dict) or policy.get("historical_coaching_enabled") is not False:
        return False, "AUTHORITY_INVALID"
    return status == "RAW_CROSS_SESSION_COMPARISON_AVAILABLE", str(
        status or "STATUS_UNAVAILABLE"
    )


def audit_h3_runtime_utility(generated: Path) -> dict[str, Any]:
    h3_root = generated / "h3_1"
    paths = sorted(h3_root.glob(f"*/{H3_SELECTION_FILENAME}"))
    status_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    basis_counts: Counter[str] = Counter()
    availability_counts: Counter[str] = Counter()
    support_counts: Counter[str] = Counter()
    invalid_artifact_count = 0
    authority_contract_violation_count = 0
    duplicate_match_count = 0
    context_pattern_sessions: dict[
        tuple[str, str, str, str], set[int]
    ] = defaultdict(set)
    pattern_contexts: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    sessions: list[dict[str, Any]] = []

    for path in paths:
        document = _load_json(path)
        if document is None:
            invalid_artifact_count += 1
            continue
        metadata = document.get("metadata")
        summary = document.get("summary")
        exact = document.get("matched_patterns")
        projected = document.get("projected_pattern_matches")
        if not (
            isinstance(metadata, dict)
            and isinstance(summary, dict)
            and isinstance(exact, list)
            and isinstance(projected, list)
        ):
            invalid_artifact_count += 1
            continue

        session_id = metadata.get("session_id")
        context = metadata.get("context")
        context = context if isinstance(context, dict) else {}
        context_key = _context_key(context)
        status = str(metadata.get("status") or "STATUS_UNAVAILABLE")
        status_counts[status] += 1
        authority_valid = (
            metadata.get("observational_only") is True
            and metadata.get("affects_next_stint_plan") is False
            and metadata.get("historical_actions_authorized") is False
        )
        if not authority_valid:
            authority_contract_violation_count += 1

        recurrent_count = 0
        seen: set[tuple[Any, ...]] = set()
        for item in exact:
            if not isinstance(item, dict):
                continue
            state = str(item.get("state") or "STATE_UNAVAILABLE")
            state_counts[state] += 1
            basis = str(item.get("match_basis") or "BASIS_UNAVAILABLE")
            basis_counts[basis] += 1
            if state in RECURRENT_STATES:
                recurrent_count += 1
            support_counts[state] += 1
            pattern_id = item.get("pattern_id")
            member = item.get("current_session_member")
            episode_pk = member.get("episode_pk") if isinstance(member, dict) else None
            identity = ("exact", pattern_id, episode_pk)
            if identity in seen:
                duplicate_match_count += 1
            seen.add(identity)
            if (
                context_key is not None
                and isinstance(pattern_id, str)
                and pattern_id
                and isinstance(session_id, int)
            ):
                context_pattern_sessions[(*context_key, pattern_id)].add(session_id)
                pattern_contexts[pattern_id].add(context_key)

        projected_pattern_ids: set[str] = set()
        for item in projected:
            if not isinstance(item, dict):
                continue
            basis = str(item.get("match_basis") or "BASIS_UNAVAILABLE")
            basis_counts[basis] += 1
            pattern_id = item.get("pattern_id")
            if isinstance(pattern_id, str) and pattern_id:
                projected_pattern_ids.add(pattern_id)
            current = item.get("current_session_episode")
            episode_pk = current.get("episode_pk") if isinstance(current, dict) else None
            identity = ("projected", pattern_id, episode_pk)
            if identity in seen:
                duplicate_match_count += 1
            seen.add(identity)

        stem = path.parent.name
        h4_available, h4_status = _h4_status(
            generated / "h4" / stem / H4_SELECTION_FILENAME,
            context,
        )
        h5_available, h5_status = _h5_status(
            generated / "h5_2" / stem / H5_COMPARISON_FILENAME,
            context,
        )
        has_recurrent = recurrent_count > 0 or bool(projected_pattern_ids)
        if has_recurrent and h5_available:
            contribution = "H3_AND_H5_AVAILABLE"
        elif has_recurrent:
            contribution = "H3_AVAILABLE_WITHOUT_H5"
        elif h5_available:
            contribution = "H5_AVAILABLE_WITHOUT_H3_RECURRENT"
        else:
            contribution = "NEITHER_H3_RECURRENT_NOR_H5"
        availability_counts[contribution] += 1
        sessions.append(
            {
                "session_key": stem,
                "session_id": session_id,
                "context": context,
                "h3_status": status,
                "authority_contract_valid": authority_valid,
                "exact_match_count": len(exact),
                "recurrent_pattern_count": recurrent_count,
                "projected_match_edge_count": len(projected),
                "projected_pattern_count": len(projected_pattern_ids),
                "h4_available": h4_available,
                "h4_status": h4_status,
                "h5_available": h5_available,
                "h5_status": h5_status,
                "observational_contribution": contribution,
            }
        )

    runtime_occurrence_counts = Counter(
        len(session_ids) for session_ids in context_pattern_sessions.values()
    )
    cross_context_pattern_ids = sorted(
        pattern_id
        for pattern_id, contexts in pattern_contexts.items()
        if len(contexts) > 1
    )
    exact_edges = sum(
        session["exact_match_count"] for session in sessions
    )
    projected_edges = sum(
        session["projected_match_edge_count"] for session in sessions
    )
    return {
        "metadata": {
            "audit_version": AUDIT_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "H3_RUNTIME_UTILITY_AUDIT",
            "observational_only": True,
            "input_artifacts_mutated": False,
            "history_opened": False,
            "matcher_called": False,
            "llm_called": False,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
            "generated_root": str(generated.resolve()),
        },
        "summary": {
            "h3_artifact_count": len(paths),
            "valid_h3_artifact_count": len(sessions),
            "invalid_h3_artifact_count": invalid_artifact_count,
            "session_status_counts": _counter(status_counts),
            "exact_match_edge_count": exact_edges,
            "projected_match_edge_count": projected_edges,
            "recurrent_exact_match_count": sum(
                session["recurrent_pattern_count"] for session in sessions
            ),
            "sessions_with_h3_recurrent_or_projected": sum(
                session["recurrent_pattern_count"] > 0
                or session["projected_pattern_count"] > 0
                for session in sessions
            ),
            "pattern_state_counts": _counter(state_counts),
            "match_basis_counts": _counter(basis_counts),
            "h3_h5_availability": _counter(availability_counts),
        },
        "stability": {
            "unique_context_pattern_count": len(context_pattern_sessions),
            "runtime_session_occurrence_distribution": {
                str(count): total
                for count, total in sorted(runtime_occurrence_counts.items())
            },
            "patterns_seen_in_multiple_runtime_sessions": sum(
                len(session_ids) > 1
                for session_ids in context_pattern_sessions.values()
            ),
            "state_support_counts": _counter(support_counts),
        },
        "review_signals": {
            "authority_contract_violation_count": authority_contract_violation_count,
            "duplicate_match_identity_count": duplicate_match_count,
            "cross_context_pattern_id_collision_count": len(cross_context_pattern_ids),
            "cross_context_pattern_id_collisions": cross_context_pattern_ids,
            "projected_edges_require_observational_review_count": projected_edges,
            "two_session_repeat_edge_count": state_counts["cross_session_repeat"],
            "persistent_pattern_edge_count": state_counts["persistent_pattern"],
            "interpretation": (
                "These are diagnostic review signals, not false-positive labels or "
                "promotion evidence. No threshold is applied."
            ),
        },
        "sessions": sessions,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita cobertura y utilidad runtime H3 sin mutar producción."
    )
    parser.add_argument("--generated-root", type=Path, default=generated_root())
    parser.add_argument(
        "--output",
        type=Path,
        default=generated_root() / "diagnostics" / "h3_runtime_utility_audit.json",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit_h3_runtime_utility(args.generated_root)
    write_report(args.output, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    summary = report["summary"]
    review = report["review_signals"]
    print("=" * 76)
    print(f"RACE ENGINEER - H3 RUNTIME UTILITY AUDIT v{AUDIT_VERSION}")
    print("=" * 76)
    print(f"Artifacts:             {summary['valid_h3_artifact_count']}")
    print(f"Invalid artifacts:     {summary['invalid_h3_artifact_count']}")
    print(f"Exact match edges:     {summary['exact_match_edge_count']}")
    print(f"Projected match edges: {summary['projected_match_edge_count']}")
    print(f"Sessions with H3:      {summary['sessions_with_h3_recurrent_or_projected']}")
    print(f"H3/H5 availability:    {summary['h3_h5_availability']}")
    print(f"Review signals:        authority={review['authority_contract_violation_count']} "
          f"duplicates={review['duplicate_match_identity_count']} "
          f"cross_context={review['cross_context_pattern_id_collision_count']}")
    print("Authority:             OBSERVATIONAL ONLY")
    print(f"Output:                {args.output.resolve()}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
