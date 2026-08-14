from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

H3_VERSION = "0.1"
PATTERN_SCHEMA_VERSION = "1.0"
EXPECTED_MATCHER_VERSION = "0.3"
DEFAULT_PERSISTENT_MIN_INDEPENDENT_SESSIONS = 3


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_float(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def safe_str(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def median_or_none(values: list[float]) -> float | None:
    values = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.median(values) if values else None


def min_or_none(values: list[float]) -> float | None:
    values = [v for v in values if v is not None and math.isfinite(v)]
    return min(values) if values else None


def max_or_none(values: list[float]) -> float | None:
    values = [v for v in values if v is not None and math.isfinite(v)]
    return max(values) if values else None


def node_key(session_id: Any, episode_pk: Any) -> tuple[int, int]:
    s = safe_int(session_id)
    e = safe_int(episode_pk)
    if s is None or e is None:
        raise ValueError(f"Episode identity incompleta: session={session_id!r} episode_pk={episode_pk!r}")
    return (s, e)


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple[int, int], tuple[int, int]] = {}
        self.rank: dict[tuple[int, int], int] = {}

    def add(self, x: tuple[int, int]) -> None:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x: tuple[int, int]) -> tuple[int, int]:
        self.add(x)
        p = self.parent[x]
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent[x]

    def union(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def load_features(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("episode_pair_features debe ser una lista JSON.")
    return [x for x in raw if isinstance(x, dict)]


def load_matches(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("episode_pair_matches debe ser un objeto JSON.")
    metadata = raw.get("metadata")
    decisions = raw.get("decisions")
    if not isinstance(metadata, dict) or not isinstance(decisions, list):
        raise ValueError("episode_pair_matches inválido: faltan metadata/decisions.")
    return metadata, [x for x in decisions if isinstance(x, dict)]


def add_episode_snapshot(
    episodes: dict[tuple[int, int], dict[str, Any]],
    pair: dict[str, Any],
    side: str,
) -> tuple[int, int]:
    key = node_key(pair.get(f"session_{side}"), pair.get(f"episode_pk_{side}"))
    snapshot = {
        "session_id": key[0],
        "episode_pk": key[1],
        "episode_id": safe_int(pair.get(f"episode_id_{side}")),
        "timestamp_utc": safe_str(pair.get(f"timestamp_{side}")),
        "session_type": safe_str(pair.get(f"session_type_{side}")),
        "track": safe_str(pair.get("track")),
        "track_layout": safe_str(pair.get("track_layout")),
        "vehicle_family": safe_str(pair.get("vehicle_family")),
        "vehicle_variant": safe_str(pair.get("vehicle_variant")),
        "car_class_raw": safe_str(pair.get(f"car_class_raw_{side}")),
        "car_name_raw": safe_str(pair.get(f"car_name_raw_{side}")),
        "setup_sha256": safe_str(pair.get(f"setup_sha256_{side}")),
        "weather_conditions": pair.get(f"weather_conditions_{side}"),
        "start_distance_m": safe_float(pair.get(f"start_distance_{side}_m")),
        "end_distance_m": safe_float(pair.get(f"end_distance_{side}_m")),
        "center_distance_m": safe_float(pair.get(f"center_distance_{side}_m")),
        "action_time_loss_s": safe_float(pair.get(f"action_time_loss_{side}_s")),
        "evidence_strength": safe_str(pair.get(f"evidence_strength_{side}")),
        "speed_propagation": pair.get(f"speed_propagation_{side}"),
        "channels": sorted({
            str(x) for x in (pair.get(f"channels_{side}") or [])
            if isinstance(x, str) and x
        }),
    }

    old = episodes.get(key)
    if old is None:
        episodes[key] = snapshot
        return key

    # Repeated pair rows must describe the same episode. Missing values are tolerated,
    # conflicting non-null identity/context/spatial values are not.
    strict_keys = (
        "track", "track_layout", "vehicle_variant", "episode_id",
        "start_distance_m", "end_distance_m", "center_distance_m",
    )
    for field in strict_keys:
        a, b = old.get(field), snapshot.get(field)
        if a is not None and b is not None and a != b:
            raise ValueError(
                f"Snapshot inconsistente para episode {key}, field={field}: {a!r} != {b!r}"
            )

    for field, value in snapshot.items():
        if old.get(field) is None and value is not None:
            old[field] = value
    if snapshot["channels"]:
        old["channels"] = sorted(set(old.get("channels") or []) | set(snapshot["channels"]))
    return key


def context_tuple(ep: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    return (
        safe_str(ep.get("track")),
        safe_str(ep.get("track_layout")),
        safe_str(ep.get("vehicle_variant")),
    )


def pattern_id_for(context: tuple[Any, Any, Any], members: list[tuple[int, int]]) -> str:
    payload = {
        "context": list(context),
        "members": [[s, e] for s, e in sorted(members)],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "pat_" + hashlib.sha256(raw).hexdigest()[:20]


def episode_member(ep: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": ep["session_id"],
        "episode_pk": ep["episode_pk"],
        "episode_id": ep.get("episode_id"),
        "timestamp_utc": ep.get("timestamp_utc"),
        "session_type": ep.get("session_type"),
        "start_distance_m": ep.get("start_distance_m"),
        "end_distance_m": ep.get("end_distance_m"),
        "center_distance_m": ep.get("center_distance_m"),
        "action_time_loss_s": ep.get("action_time_loss_s"),
        "channels": ep.get("channels") or [],
    }


def choose_representative(members: list[dict[str, Any]], center_median: float | None) -> dict[str, Any] | None:
    if not members:
        return None
    if center_median is None:
        chosen = min(members, key=lambda x: (x["session_id"], x["episode_pk"]))
    else:
        chosen = min(
            members,
            key=lambda x: (
                abs((x.get("center_distance_m") if x.get("center_distance_m") is not None else center_median) - center_median),
                x["session_id"],
                x["episode_pk"],
            ),
        )
    return {
        "session_id": chosen["session_id"],
        "episode_pk": chosen["episode_pk"],
        "episode_id": chosen.get("episode_id"),
        "reason": "member_closest_to_median_center_then_stable_identity",
    }


def build_patterns(
    features: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    *,
    persistent_min_sessions: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if persistent_min_sessions < 3:
        raise ValueError("persistent_min_sessions debe ser >= 3 para distinguir repeat de persistent.")

    episodes: dict[tuple[int, int], dict[str, Any]] = {}
    uf = UnionFind()

    # pair_index is the canonical join because matcher output was generated from this exact list.
    decision_by_index: dict[int, dict[str, Any]] = {}
    for d in decisions:
        idx = safe_int(d.get("pair_index"))
        if idx is None:
            raise ValueError("Decision sin pair_index.")
        if idx in decision_by_index:
            raise ValueError(f"pair_index duplicado en decisions: {idx}")
        decision_by_index[idx] = d

    if len(decision_by_index) != len(features):
        raise ValueError(
            f"Feature/decision count mismatch: features={len(features)} decisions={len(decision_by_index)}"
        )

    pair_endpoints: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {}
    pair_contexts: dict[int, tuple[Any, Any, Any]] = {}

    for idx, pair in enumerate(features):
        a = add_episode_snapshot(episodes, pair, "a")
        b = add_episode_snapshot(episodes, pair, "b")
        uf.add(a)
        uf.add(b)
        pair_endpoints[idx] = (a, b)

        ca = context_tuple(episodes[a])
        cb = context_tuple(episodes[b])
        if ca != cb:
            raise ValueError(f"Pair {idx} cruza contextos: {ca} != {cb}")
        if any(x is None for x in ca):
            raise ValueError(f"Pair {idx} tiene contexto incompleto: {ca}")
        pair_contexts[idx] = ca

        d = decision_by_index[idx]
        # Strong source-integrity check.
        da = node_key(d.get("session_a"), d.get("episode_pk_a"))
        db = node_key(d.get("session_b"), d.get("episode_pk_b"))
        if {a, b} != {da, db}:
            raise ValueError(f"Decision {idx} no corresponde a los endpoints de features.")

        if d.get("decision") == "MATCH":
            uf.union(a, b)

    components: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for key in sorted(episodes):
        components[uf.find(key)].append(key)

    # Build a pattern lookup before internal-pair audit.
    component_of: dict[tuple[int, int], tuple[int, int]] = {}
    for root, members in components.items():
        for member in members:
            component_of[member] = root

    internal_decisions: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    external_match_count = 0
    for idx, d in decision_by_index.items():
        a, b = pair_endpoints[idx]
        if component_of[a] == component_of[b]:
            internal_decisions[component_of[a]].append({"pair_index": idx, **d})
        elif d.get("decision") == "MATCH":
            external_match_count += 1

    if external_match_count:
        raise RuntimeError("Union-Find inconsistente: existe MATCH entre componentes distintos.")

    patterns: list[dict[str, Any]] = []
    contradiction_count = 0

    for root, member_keys in sorted(components.items(), key=lambda x: min(x[1])):
        eps = [episodes[k] for k in sorted(member_keys)]
        contexts = {context_tuple(ep) for ep in eps}
        if len(contexts) != 1:
            raise ValueError(f"Componente cruza contextos: {contexts}")
        context = next(iter(contexts))

        sessions = sorted({ep["session_id"] for ep in eps})
        per_session_counts = Counter(ep["session_id"] for ep in eps)
        observation_count = len(eps)
        independent_session_count = len(sessions)

        internal = internal_decisions.get(root, [])
        decision_counts = Counter(str(x.get("decision")) for x in internal)
        reject_rows = [x for x in internal if x.get("decision") == "REJECT"]
        ambiguous_rows = [x for x in internal if x.get("decision") == "AMBIGUOUS"]
        match_rows = [x for x in internal if x.get("decision") == "MATCH"]

        possible_cross_session_pairs = 0
        counts = list(per_session_counts.values())
        for i in range(len(counts)):
            for j in range(i + 1, len(counts)):
                possible_cross_session_pairs += counts[i] * counts[j]

        missing_internal_cross_session_pairs = possible_cross_session_pairs - len(internal)
        if missing_internal_cross_session_pairs < 0:
            raise RuntimeError("Conteo interno de pares imposible.")

        conflict_reasons: list[str] = []
        if reject_rows:
            conflict_reasons.append("INTERNAL_REJECT_CONTRADICTS_TRANSITIVE_EQUIVALENCE")
        if missing_internal_cross_session_pairs:
            conflict_reasons.append("MISSING_INTERNAL_CROSS_SESSION_PAIR_DECISIONS")

        if conflict_reasons:
            state = "conflict_review_required"
            contradiction_count += 1
        elif independent_session_count >= persistent_min_sessions:
            state = "persistent_pattern"
        elif independent_session_count >= 2:
            state = "cross_session_repeat"
        else:
            # Current H2 source contains only cross-session pair relations, so a component
            # with one session can only be an isolated observation. within_session_repeat
            # needs a future within-session evidence source.
            state = "single_observation"

        starts = [safe_float(ep.get("start_distance_m")) for ep in eps]
        ends = [safe_float(ep.get("end_distance_m")) for ep in eps]
        centers = [safe_float(ep.get("center_distance_m")) for ep in eps]
        impacts = [safe_float(ep.get("action_time_loss_s")) for ep in eps]

        center_median = median_or_none([x for x in centers if x is not None])
        member_rows = [episode_member(ep) for ep in eps]

        channel_sets = [set(ep.get("channels") or []) for ep in eps]
        common_channels = sorted(set.intersection(*channel_sets)) if channel_sets else []
        union_channels = sorted(set.union(*channel_sets)) if channel_sets else []
        channel_episode_counts = {
            ch: sum(ch in s for s in channel_sets)
            for ch in union_channels
        }
        channel_session_counts = {
            ch: len({
                ep["session_id"]
                for ep in eps
                if ch in set(ep.get("channels") or [])
            })
            for ch in union_channels
        }

        timestamps = sorted(
            [str(ep["timestamp_utc"]) for ep in eps if ep.get("timestamp_utc")]
        )

        pat = {
            "pattern_id": pattern_id_for(context, member_keys),
            "state": state,
            "context": {
                "track": context[0],
                "track_layout": context[1],
                "vehicle_variant": context[2],
                "vehicle_family_values": sorted({
                    ep["vehicle_family"] for ep in eps if ep.get("vehicle_family")
                }),
            },
            "observation_count": observation_count,
            "independent_session_count": independent_session_count,
            "session_ids": sessions,
            "session_observation_counts": {
                str(k): per_session_counts[k] for k in sorted(per_session_counts)
            },
            "members": member_rows,
            "representative_member": choose_representative(member_rows, center_median),
            "spatial_summary": {
                "start_median_m": median_or_none([x for x in starts if x is not None]),
                "start_min_m": min_or_none([x for x in starts if x is not None]),
                "start_max_m": max_or_none([x for x in starts if x is not None]),
                "end_median_m": median_or_none([x for x in ends if x is not None]),
                "end_min_m": min_or_none([x for x in ends if x is not None]),
                "end_max_m": max_or_none([x for x in ends if x is not None]),
                "center_median_m": center_median,
                "center_min_m": min_or_none([x for x in centers if x is not None]),
                "center_max_m": max_or_none([x for x in centers if x is not None]),
                "center_spread_m": (
                    max_or_none([x for x in centers if x is not None])
                    - min_or_none([x for x in centers if x is not None])
                    if [x for x in centers if x is not None] else None
                ),
            },
            "impact_summary": {
                "action_time_loss_median_s": median_or_none([x for x in impacts if x is not None]),
                "action_time_loss_min_s": min_or_none([x for x in impacts if x is not None]),
                "action_time_loss_max_s": max_or_none([x for x in impacts if x is not None]),
            },
            "channel_summary": {
                "common_action_channels": common_channels,
                "union_action_channels": union_channels,
                "episode_prevalence_count": channel_episode_counts,
                "session_prevalence_count": channel_session_counts,
            },
            "temporal_summary": {
                "first_observed_utc": timestamps[0] if timestamps else None,
                "last_observed_utc": timestamps[-1] if timestamps else None,
                "session_types": sorted({
                    ep["session_type"] for ep in eps if ep.get("session_type")
                }),
            },
            "equivalence_evidence": {
                "direct_match_edge_count": len(match_rows),
                "internal_ambiguous_pair_count": len(ambiguous_rows),
                "internal_reject_pair_count": len(reject_rows),
                "possible_cross_session_pair_count": possible_cross_session_pairs,
                "observed_internal_cross_session_pair_count": len(internal),
                "missing_internal_cross_session_pair_count": missing_internal_cross_session_pairs,
                "transitively_resolved_ambiguous_pair_count": len(ambiguous_rows),
                "same_session_member_pair_count_inferred": sum(
                    n * (n - 1) // 2 for n in per_session_counts.values()
                ),
                "decision_counts": dict(sorted(decision_counts.items())),
            },
            "uncertainty": {
                "has_internal_reject_contradiction": bool(reject_rows),
                "has_missing_internal_pair_decisions": bool(missing_internal_cross_session_pairs),
                "conflict_reasons": conflict_reasons,
                "internal_reject_pairs": [
                    {
                        "pair_index": x.get("pair_index"),
                        "pair_id": x.get("pair_id"),
                        "session_a": x.get("session_a"),
                        "episode_pk_a": x.get("episode_pk_a"),
                        "session_b": x.get("session_b"),
                        "episode_pk_b": x.get("episode_pk_b"),
                        "rule_id": x.get("rule_id"),
                    }
                    for x in reject_rows
                ],
            },
        }
        patterns.append(pat)

    patterns.sort(
        key=lambda p: (
            {"conflict_review_required": 0, "persistent_pattern": 1, "cross_session_repeat": 2, "single_observation": 3}.get(p["state"], 9),
            -p["independent_session_count"],
            -p["observation_count"],
            p["spatial_summary"]["center_median_m"] if p["spatial_summary"]["center_median_m"] is not None else float("inf"),
            p["pattern_id"],
        )
    )

    summary = {
        "episode_count": len(episodes),
        "pattern_count": len(patterns),
        "state_counts": dict(sorted(Counter(p["state"] for p in patterns).items())),
        "persistent_pattern_count": sum(p["state"] == "persistent_pattern" for p in patterns),
        "cross_session_repeat_count": sum(p["state"] == "cross_session_repeat" for p in patterns),
        "single_observation_count": sum(p["state"] == "single_observation" for p in patterns),
        "conflict_review_required_count": contradiction_count,
        "match_edge_count": sum(d.get("decision") == "MATCH" for d in decisions),
        "transitively_resolved_ambiguous_pair_count": sum(
            p["equivalence_evidence"]["transitively_resolved_ambiguous_pair_count"] for p in patterns
        ),
    }
    return patterns, summary


def main() -> int:
    ap = argparse.ArgumentParser(
        description="H3 v0.1: construye clases transitivas de episodios y estados de recurrencia."
    )
    ap.add_argument("features_json")
    ap.add_argument("matches_json")
    ap.add_argument("--output", default="persistent_patterns.json")
    ap.add_argument(
        "--persistent-min-sessions",
        type=int,
        default=DEFAULT_PERSISTENT_MIN_INDEPENDENT_SESSIONS,
        help="Definición de persistent_pattern; default 3 sesiones independientes.",
    )
    args = ap.parse_args()

    features_path = Path(args.features_json).resolve()
    matches_path = Path(args.matches_json).resolve()
    output_path = Path(args.output).resolve()

    features = load_features(features_path)
    matcher_metadata, decisions = load_matches(matches_path)

    matcher_version = str(matcher_metadata.get("matcher_version") or "")
    if matcher_version != EXPECTED_MATCHER_VERSION:
        raise ValueError(
            f"H3 v{H3_VERSION} requiere matcher v{EXPECTED_MATCHER_VERSION}; recibido {matcher_version!r}."
        )

    patterns, summary = build_patterns(
        features,
        decisions,
        persistent_min_sessions=args.persistent_min_sessions,
    )

    payload = {
        "metadata": {
            "schema_version": PATTERN_SCHEMA_VERSION,
            "h3_version": H3_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_features": str(features_path),
            "source_matches": str(matches_path),
            "matcher_version": matcher_version,
            "matcher_status": matcher_metadata.get("matcher_status"),
            "persistent_min_independent_sessions": args.persistent_min_sessions,
            "equivalence_policy": (
                "MATCH is transitive: A=B and B=C implies A=C. "
                "Internal AMBIGUOUS pairs are resolved by equivalence closure; "
                "internal REJECT pairs are contradictions requiring audit."
            ),
            "within_session_repeat_evidence_available": False,
            "policy": (
                "Derived H3 evidence only. Does not mutate History DB, does not select historical_reference, "
                "and does not alter coaching."
            ),
        },
        "summary": summary,
        "patterns": patterns,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 78)
    print(f"RACE ENGINEER - H3 PERSISTENT PATTERN BUILDER v{H3_VERSION}")
    print("=" * 78)
    print(f"Matcher version:             {matcher_version}")
    print(f"Episodes:                    {summary['episode_count']}")
    print(f"Patterns/classes:            {summary['pattern_count']}")
    for state, count in summary["state_counts"].items():
        print(f"{state:28s} {count:6d}")
    print(f"MATCH edges:                 {summary['match_edge_count']}")
    print(f"AMBIG resolved transitively: {summary['transitively_resolved_ambiguous_pair_count']}")
    print(f"Conflicts requiring review:  {summary['conflict_review_required_count']}")
    print(f"Output: {output_path}")

    if summary["conflict_review_required_count"]:
        print("RESULT: REVIEW_REQUIRED")
        return 2

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
