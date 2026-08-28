from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import episode_pair_matcher as matcher
from track_baseline_shadow import (
    TRACK_BASELINE_POLICY_VERSION,
    match_only_calibration,
    resolve_track_baseline,
)
from track_match_baseline_promotion import (
    MATCH_PROMOTION_POLICY_VERSION,
    discover_promotion_for_context,
)


AUTHORIZED_MATCHER_VERSION = "0.1"
DEFAULT_BATCHES_ROOT = Path(__file__).resolve().parent / "calibration_batches"


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def pair_context(pair: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _safe_str(pair.get("track")),
        _safe_str(pair.get("track_layout")),
        _safe_str(pair.get("vehicle_variant")),
    )


def context_session_count(
    pairs: list[dict[str, Any]],
    *,
    context: tuple[str, str, str],
) -> int:
    """Count independent sessions represented by features for one exact context."""
    sessions: set[int] = set()
    for pair in pairs:
        if pair_context(pair) != context:
            continue
        for key in ("session_a", "session_b"):
            value = _safe_int(pair.get(key))
            if value is not None:
                sessions.add(value)
    return len(sessions)


def _authority_metadata(
    *,
    scope: str,
    production_match_authorized: bool,
    production_reject_authorized: bool,
    promotion: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "authorized_matcher_version": AUTHORIZED_MATCHER_VERSION,
        "calibration_scope": scope,
        "production_match_authorized": bool(production_match_authorized),
        "production_reject_authorized": bool(production_reject_authorized),
        "track_baseline_policy_version": TRACK_BASELINE_POLICY_VERSION,
        "match_promotion_policy_version": MATCH_PROMOTION_POLICY_VERSION,
        "baseline_source_variants": list(
            ((baseline or {}).get("match") or {}).get("source_variants")
            or (promotion or {}).get("source_variants")
            or []
        ),
        "promotion_batch_id": (promotion or {}).get("batch_id"),
        "promotion_status": (promotion or {}).get("status"),
        "promotion_confirmed_matches": int(
            (promotion or {}).get("confirmed_automatic_matches") or 0
        ),
    }


def classify_pair_authorized(
    pair: dict[str, Any],
    *,
    batches_root: Path = DEFAULT_BATCHES_ROOT,
    target_variant_sessions: int,
) -> dict[str, Any]:
    """Production H2 authorization layer.

    Exact calibration keeps the original matcher result unchanged in authority.
    Without exact calibration, only an explicitly promoted inherited MATCH may
    become automatic production output. Inherited REJECT is never authorized.
    Any missing/malformed promotion evidence fails closed to the original result.
    """
    exact_calibration = matcher.resolve_calibration(pair)
    if exact_calibration is not None:
        result = dict(matcher.classify_pair(pair))
        result["authority"] = _authority_metadata(
            scope="EXACT_VARIANT_CALIBRATION",
            production_match_authorized=True,
            production_reject_authorized=True,
        )
        return result

    original = dict(matcher.classify_pair(pair))

    track, layout, variant = pair_context(pair)
    if not track or not layout or not variant or target_variant_sessions < 1:
        original["authority"] = _authority_metadata(
            scope="NO_AUTHORIZED_CALIBRATION",
            production_match_authorized=False,
            production_reject_authorized=False,
        )
        return original

    try:
        promotion = discover_promotion_for_context(
            batches_root=Path(batches_root),
            track=track,
            track_layout=layout,
            vehicle_variant=variant,
            target_variant_sessions=int(target_variant_sessions),
        )
    except Exception as exc:
        original["authority"] = _authority_metadata(
            scope="PROMOTION_EVIDENCE_ERROR",
            production_match_authorized=False,
            production_reject_authorized=False,
        )
        original["authority"]["promotion_error"] = type(exc).__name__
        return original

    if promotion.get("production_match_authorized") is not True:
        original["authority"] = _authority_metadata(
            scope="TRACK_MATCH_BASELINE_NOT_AUTHORIZED",
            production_match_authorized=False,
            production_reject_authorized=False,
            promotion=promotion,
        )
        return original

    try:
        baseline = resolve_track_baseline(
            track=track,
            track_layout=layout,
            vehicle_variant=variant,
        )
        calibration = baseline.get("calibration")
        if (
            baseline.get("status") != "TRACK_MATCH_BASELINE_SHADOW"
            or not isinstance(calibration, dict)
        ):
            raise ValueError("promoted context has no usable MATCH baseline")

        inherited = dict(
            matcher.classify_pair(
                pair,
                calibration_override=match_only_calibration(calibration),
            )
        )
    except Exception as exc:
        original["authority"] = _authority_metadata(
            scope="PROMOTED_BASELINE_RESOLUTION_ERROR",
            production_match_authorized=False,
            production_reject_authorized=False,
            promotion=promotion,
        )
        original["authority"]["baseline_error"] = type(exc).__name__
        return original

    # The only inherited automatic decision allowed through production is MATCH.
    if inherited.get("decision") == "MATCH" and inherited.get("automatic") is True:
        inherited["authority"] = _authority_metadata(
            scope="COVERED_BY_TRACK_MATCH_BASELINE",
            production_match_authorized=True,
            production_reject_authorized=False,
            promotion=promotion,
            baseline=baseline,
        )
        return inherited

    # Defensive gate: even if a future regression re-enables inherited REJECT,
    # it may not escape this wrapper.
    if inherited.get("decision") == "REJECT":
        original["rule_id"] = "INHERITED_REJECT_BLOCKED"
        original["reasons"] = [
            "track MATCH baseline is authorized for MATCH only",
            "inherited REJECT is variant-specific and fail-closed",
        ]
        original["decision"] = "AMBIGUOUS"
        original["automatic"] = False

    original["authority"] = _authority_metadata(
        scope="COVERED_BY_TRACK_MATCH_BASELINE",
        production_match_authorized=True,
        production_reject_authorized=False,
        promotion=promotion,
        baseline=baseline,
    )
    return original


def classify_features_authorized(
    pairs: list[dict[str, Any]],
    *,
    batches_root: Path = DEFAULT_BATCHES_ROOT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Classify a feature list while deriving session evidence per exact context."""
    contexts = {pair_context(pair) for pair in pairs}
    counts = {
        context: context_session_count(pairs, context=context)
        for context in contexts
    }

    decisions: list[dict[str, Any]] = []
    scope_counts: dict[str, int] = {}
    match_count = reject_count = ambiguous_count = 0

    for index, pair in enumerate(pairs):
        context = pair_context(pair)
        result = classify_pair_authorized(
            pair,
            batches_root=batches_root,
            target_variant_sessions=counts.get(context, 0),
        )
        authority = result.get("authority") or {}
        scope = str(authority.get("calibration_scope") or "UNKNOWN")
        scope_counts[scope] = scope_counts.get(scope, 0) + 1

        decision = str(result.get("decision") or "AMBIGUOUS")
        if decision == "MATCH":
            match_count += 1
        elif decision == "REJECT":
            reject_count += 1
        else:
            ambiguous_count += 1

        row = {
            "pair_index": index,
            "pair_id": matcher.stable_pair_id(pair),
            "session_a": pair.get("session_a"),
            "session_b": pair.get("session_b"),
            "episode_pk_a": pair.get("episode_pk_a"),
            "episode_pk_b": pair.get("episode_pk_b"),
            **result,
        }
        decisions.append(row)

    metadata = {
        "matcher_version": matcher.MATCHER_VERSION,
        "matcher_status": getattr(matcher, "MATCHER_STATUS", None),
        "authorized_matcher_version": AUTHORIZED_MATCHER_VERSION,
        "track_baseline_policy_version": TRACK_BASELINE_POLICY_VERSION,
        "match_promotion_policy_version": MATCH_PROMOTION_POLICY_VERSION,
        "decision_counts": {
            "MATCH": match_count,
            "AMBIGUOUS": ambiguous_count,
            "REJECT": reject_count,
        },
        "authority_scope_counts": dict(sorted(scope_counts.items())),
        "context_session_counts": {
            " | ".join(context): count
            for context, count in sorted(counts.items())
        },
        "production_contract": {
            "exact_variant": "MATCH_AND_REJECT_AS_CALIBRATED",
            "promoted_track_baseline": "MATCH_ONLY",
            "inherited_reject": "NEVER_AUTHORIZED",
        },
    }
    return decisions, metadata


def load_pairs(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("episode_pair_features debe ser una lista JSON.")
    return [row for row in raw if isinstance(row, dict)]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "H2 production authorization wrapper: exact calibration plus "
            "promoted track/layout MATCH baseline; inherited REJECT disabled."
        )
    )
    parser.add_argument("features_json")
    parser.add_argument("--output", default="episode_pair_matches.json")
    parser.add_argument(
        "--batches-root",
        type=Path,
        default=DEFAULT_BATCHES_ROOT,
    )
    args = parser.parse_args()

    source = Path(args.features_json).resolve()
    output = Path(args.output).resolve()
    pairs = load_pairs(source)
    decisions, metadata = classify_features_authorized(
        pairs,
        batches_root=args.batches_root,
    )
    metadata["source_features"] = str(source)
    metadata["source_features_sha256"] = sha256_file(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {"metadata": metadata, "decisions": decisions},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    counts = metadata["decision_counts"]
    print(
        "Authorized H2: "
        f"MATCH={counts['MATCH']} "
        f"AMBIGUOUS={counts['AMBIGUOUS']} "
        f"REJECT={counts['REJECT']}"
    )
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
