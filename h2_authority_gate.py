from __future__ import annotations

from collections import Counter
from typing import Any

EXPECTED_MATCHER_VERSION = "0.3"


def validate_authorized_h2(
    features: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Fail-closed gate between production-authorized H2 and H3.

    Allowed:
    - exact calibrated MATCH/REJECT;
    - promoted inherited MATCH.

    Forbidden:
    - inherited REJECT;
    - MATCH without explicit production MATCH authority.
    """
    matcher_version = str(metadata.get("matcher_version") or "")
    if matcher_version != EXPECTED_MATCHER_VERSION:
        raise ValueError(
            f"H2/H3 gate requiere matcher v{EXPECTED_MATCHER_VERSION}; "
            f"recibido {matcher_version!r}."
        )

    by_index: dict[int, dict[str, Any]] = {}
    inherited_rejects: list[int] = []
    unauthorized_matches: list[int] = []
    authority_scope_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()

    for row in decisions:
        try:
            index = int(row.get("pair_index"))
        except (TypeError, ValueError):
            raise ValueError("Decision H2 sin pair_index válido.") from None

        if index in by_index:
            raise ValueError(f"pair_index duplicado en H2 autorizado: {index}")
        by_index[index] = row

        decision = str(row.get("decision") or "AMBIGUOUS")
        decision_counts[decision] += 1

        authority = row.get("authority")
        if not isinstance(authority, dict):
            authority = {}

        scope = str(authority.get("calibration_scope") or "UNKNOWN")
        authority_scope_counts[scope] += 1

        if scope == "COVERED_BY_TRACK_MATCH_BASELINE" and decision == "REJECT":
            inherited_rejects.append(index)

        if (
            decision == "MATCH"
            and authority.get("production_match_authorized") is not True
        ):
            unauthorized_matches.append(index)

    if len(by_index) != len(features):
        raise ValueError(
            "Feature/decision count mismatch antes de H3: "
            f"features={len(features)} decisions={len(by_index)}"
        )

    expected_indices = set(range(len(features)))
    actual_indices = set(by_index)
    if actual_indices != expected_indices:
        missing = sorted(expected_indices - actual_indices)
        extra = sorted(actual_indices - expected_indices)
        raise ValueError(
            "pair_index incompleto/no canónico antes de H3: "
            f"missing={missing[:10]} extra={extra[:10]}"
        )

    if inherited_rejects:
        raise RuntimeError(
            "Gate H2->H3 bloqueado: inherited REJECT escapó del wrapper "
            f"en pair_index={inherited_rejects[:10]}"
        )

    if unauthorized_matches:
        raise RuntimeError(
            "Gate H2->H3 bloqueado: MATCH sin production_match_authorized=True "
            f"en pair_index={unauthorized_matches[:10]}"
        )

    return {
        "matcher_version": matcher_version,
        "decision_counts": dict(sorted(decision_counts.items())),
        "authority_scope_counts": dict(sorted(authority_scope_counts.items())),
        "inherited_reject_count": len(inherited_rejects),
        "unauthorized_match_count": len(unauthorized_matches),
    }
