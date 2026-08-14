from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VALID_STATES = {
    "single_observation",
    "cross_session_repeat",
    "persistent_pattern",
    "conflict_review_required",
}


def safe_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def node_key(s: Any, e: Any) -> tuple[int, int]:
    s, e = safe_int(s), safe_int(e)
    if s is None or e is None:
        raise ValueError("episode identity incompleta")
    return s, e


class UF:
    def __init__(self) -> None:
        self.p = {}
    def add(self, x):
        self.p.setdefault(x, x)
    def find(self, x):
        self.add(x)
        if self.p[x] != x:
            self.p[x] = self.find(self.p[x])
        return self.p[x]
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida H3 persistent_patterns contra features y matcher.")
    ap.add_argument("patterns_json")
    ap.add_argument("features_json")
    ap.add_argument("matches_json")
    args = ap.parse_args()

    patterns_doc = load(Path(args.patterns_json).resolve())
    features = load(Path(args.features_json).resolve())
    matches_doc = load(Path(args.matches_json).resolve())

    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(patterns_doc, dict) or not isinstance(patterns_doc.get("patterns"), list):
        raise ValueError("patterns_json inválido")
    if not isinstance(features, list):
        raise ValueError("features_json inválido")
    decisions = matches_doc.get("decisions") if isinstance(matches_doc, dict) else None
    if not isinstance(decisions, list):
        raise ValueError("matches_json inválido")

    metadata = patterns_doc.get("metadata") or {}
    min_sessions = safe_int(metadata.get("persistent_min_independent_sessions"))
    if min_sessions is None or min_sessions < 3:
        errors.append("persistent_min_independent_sessions inválido")

    # Reconstruct source episode universe + source transitive closure.
    uf = UF()
    all_nodes = set()
    endpoints = {}
    for idx, pair in enumerate(features):
        try:
            a = node_key(pair.get("session_a"), pair.get("episode_pk_a"))
            b = node_key(pair.get("session_b"), pair.get("episode_pk_b"))
        except ValueError:
            errors.append(f"feature pair {idx}: endpoint inválido")
            continue
        all_nodes.update((a, b))
        uf.add(a); uf.add(b)
        endpoints[idx] = (a, b)

    by_index = {}
    for d in decisions:
        idx = safe_int(d.get("pair_index"))
        if idx is None:
            errors.append("decision sin pair_index")
            continue
        if idx in by_index:
            errors.append(f"decision pair_index duplicado: {idx}")
        by_index[idx] = d
        if d.get("decision") == "MATCH" and idx in endpoints:
            uf.union(*endpoints[idx])

    if len(by_index) != len(features):
        errors.append(
            f"cantidad decisions/features distinta: {len(by_index)} != {len(features)}"
        )

    expected_components = defaultdict(set)
    for node in all_nodes:
        expected_components[uf.find(node)].add(node)
    expected_sets = {frozenset(v) for v in expected_components.values()}

    # Validate output partition and states.
    seen_nodes = set()
    output_sets = set()
    pattern_ids = set()
    member_to_pattern = {}

    for pidx, pat in enumerate(patterns_doc["patterns"]):
        pid = pat.get("pattern_id")
        if not isinstance(pid, str) or not pid:
            errors.append(f"pattern[{pidx}] pattern_id inválido")
            continue
        if pid in pattern_ids:
            errors.append(f"pattern_id duplicado: {pid}")
        pattern_ids.add(pid)

        state = pat.get("state")
        if state not in VALID_STATES:
            errors.append(f"{pid}: state inválido {state!r}")

        members = pat.get("members")
        if not isinstance(members, list) or not members:
            errors.append(f"{pid}: members vacío/inválido")
            continue

        nodes = set()
        sessions = set()
        for m in members:
            try:
                node = node_key(m.get("session_id"), m.get("episode_pk"))
            except Exception:
                errors.append(f"{pid}: member identity inválida")
                continue
            if node in seen_nodes:
                errors.append(f"episode aparece en múltiples patterns: {node}")
            seen_nodes.add(node)
            nodes.add(node)
            sessions.add(node[0])
            member_to_pattern[node] = pid

        output_sets.add(frozenset(nodes))

        obs = safe_int(pat.get("observation_count"))
        sess = safe_int(pat.get("independent_session_count"))
        if obs != len(nodes):
            errors.append(f"{pid}: observation_count {obs} != {len(nodes)}")
        if sess != len(sessions):
            errors.append(f"{pid}: independent_session_count {sess} != {len(sessions)}")

        uncertainty = pat.get("uncertainty") or {}
        eq = pat.get("equivalence_evidence") or {}
        internal_reject = safe_int(eq.get("internal_reject_pair_count")) or 0
        missing = safe_int(eq.get("missing_internal_cross_session_pair_count")) or 0

        if state == "persistent_pattern":
            if sess is None or min_sessions is None or sess < min_sessions:
                errors.append(f"{pid}: persistent_pattern sin suficientes sesiones")
            if internal_reject or missing:
                errors.append(f"{pid}: persistent_pattern contiene conflicto/incompletitud")
        elif state == "cross_session_repeat":
            if sess is None or min_sessions is None or not (2 <= sess < min_sessions):
                errors.append(f"{pid}: cross_session_repeat con session_count inválido")
            if internal_reject or missing:
                errors.append(f"{pid}: cross_session_repeat contiene conflicto/incompletitud")
        elif state == "single_observation":
            if len(nodes) != 1:
                errors.append(f"{pid}: single_observation con {len(nodes)} miembros")
        elif state == "conflict_review_required":
            if not (internal_reject or missing):
                errors.append(f"{pid}: conflict_review_required sin conflicto detectable")

        if state != "conflict_review_required" and uncertainty.get("has_internal_reject_contradiction"):
            errors.append(f"{pid}: contradicción REJECT no reflejada en state")

    if seen_nodes != all_nodes:
        errors.append(
            f"partición no cubre universo: output={len(seen_nodes)} source={len(all_nodes)}"
        )

    if output_sets != expected_sets:
        errors.append(
            f"componentes output != cierre transitivo MATCH: output={len(output_sets)} expected={len(expected_sets)}"
        )

    # Every MATCH must be inside same output class. Internal REJECT is a contradiction.
    match_cross_pattern = 0
    reject_inside_pattern = 0
    ambiguous_inside_pattern = 0
    for idx, d in by_index.items():
        if idx not in endpoints:
            continue
        a, b = endpoints[idx]
        pa = member_to_pattern.get(a)
        pb = member_to_pattern.get(b)
        decision = d.get("decision")
        if decision == "MATCH" and pa != pb:
            match_cross_pattern += 1
        if decision == "REJECT" and pa is not None and pa == pb:
            reject_inside_pattern += 1
        if decision == "AMBIGUOUS" and pa is not None and pa == pb:
            ambiguous_inside_pattern += 1

    if match_cross_pattern:
        errors.append(f"MATCH entre patterns distintos: {match_cross_pattern}")

    declared_conflicts = sum(
        p.get("state") == "conflict_review_required" for p in patterns_doc["patterns"]
    )
    if reject_inside_pattern and not declared_conflicts:
        errors.append(
            f"REJECT internos={reject_inside_pattern} pero no hay conflict_review_required"
        )

    state_counts = Counter(p.get("state") for p in patterns_doc["patterns"])
    summary = patterns_doc.get("summary") or {}
    if summary.get("state_counts") != dict(sorted(state_counts.items())):
        errors.append("summary.state_counts no coincide con patterns")

    print("=" * 78)
    print("RACE ENGINEER - H3 PERSISTENT PATTERN VALIDATION v0.1")
    print("=" * 78)
    print(f"Source episodes:              {len(all_nodes)}")
    print(f"Source MATCH edges:           {sum(d.get('decision') == 'MATCH' for d in decisions)}")
    print(f"Output patterns/classes:      {len(patterns_doc['patterns'])}")
    for state, count in sorted(state_counts.items()):
        print(f"{state:28s} {count:6d}")
    print(f"AMBIG internal/transitive:    {ambiguous_inside_pattern}")
    print(f"REJECT internal contradictions:{reject_inside_pattern}")
    print(f"MATCH crossing classes:       {match_cross_pattern}")
    print(f"Errors:                       {len(errors)}")
    for err in errors[:30]:
        print(f"  - {err}")
    if len(errors) > 30:
        print(f"  ... {len(errors)-30} more")

    if errors:
        print("RESULT: FAIL")
        return 2

    if reject_inside_pattern:
        print("RESULT: REVIEW_REQUIRED")
        return 3

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
