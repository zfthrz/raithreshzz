from __future__ import annotations

from pathlib import Path
from typing import Any

from audit_track_baseline_shadow import audit_batch
from track_baseline_shadow import resolve_track_baseline


MATCH_PROMOTION_POLICY_VERSION = "0.1"

# Conservative minimum evidence for inherited MATCH only.
MIN_CONFIRMED_AUTOMATIC_MATCHES = 4
MIN_TARGET_VARIANT_SESSIONS = 2


def evaluate_match_promotion(
    report: dict[str, Any],
    *,
    target_variant_sessions: int,
) -> dict[str, Any]:
    """Evaluate whether an inherited MATCH core is eligible for promotion.

    REJECT is explicitly outside this policy and remains variant-specific.
    """
    baseline = report.get("baseline") or {}
    match = baseline.get("match") or {}

    reasons: list[str] = []
    automatic_match_same = sum(
        1
        for row in report.get("pairs") or []
        if row.get("automatic") is True
        and row.get("human_label") == "SAME"
        and row.get("shadow_decision") == "MATCH"
    )
    false_match = sum(
        1
        for row in report.get("pairs") or []
        if row.get("automatic") is True
        and row.get("shadow_decision") == "MATCH"
        and row.get("human_label") != "SAME"
    )

    if baseline.get("status") != "TRACK_MATCH_BASELINE_SHADOW":
        reasons.append("baseline_not_track_match_shadow")

    if match.get("status") != "AVAILABLE":
        reasons.append("match_baseline_not_available")

    if report.get("contradictions"):
        reasons.append("decisive_human_contradictions_present")

    if false_match > 0:
        reasons.append("automatic_match_disagrees_with_human_label")

    if report.get("automatic_on_human_ambiguous"):
        reasons.append("automatic_decision_on_human_ambiguous")

    if automatic_match_same < MIN_CONFIRMED_AUTOMATIC_MATCHES:
        reasons.append(
            f"confirmed_automatic_matches_below_{MIN_CONFIRMED_AUTOMATIC_MATCHES}"
        )

    if int(target_variant_sessions) < MIN_TARGET_VARIANT_SESSIONS:
        reasons.append(
            f"target_variant_sessions_below_{MIN_TARGET_VARIANT_SESSIONS}"
        )

    eligible = not reasons

    return {
        "policy_version": MATCH_PROMOTION_POLICY_VERSION,
        "status": (
            "COVERED_BY_TRACK_MATCH_BASELINE"
            if eligible
            else "TRACK_MATCH_BASELINE_SHADOW"
        ),
        "eligible": eligible,
        "production_match_authorized": eligible,
        "production_reject_authorized": False,
        "confirmed_automatic_matches": automatic_match_same,
        "false_automatic_matches": false_match,
        "target_variant_sessions": int(target_variant_sessions),
        "minimum_confirmed_automatic_matches": MIN_CONFIRMED_AUTOMATIC_MATCHES,
        "minimum_target_variant_sessions": MIN_TARGET_VARIANT_SESSIONS,
        "source_variants": list(match.get("source_variants") or []),
        "reasons": reasons,
    }


def discover_promotion_for_context(
    *,
    batches_root: Path,
    track: str,
    track_layout: str,
    vehicle_variant: str,
    target_variant_sessions: int,
) -> dict[str, Any]:
    """Resolve promotion evidence from existing human-labeled batch artifacts."""
    baseline = resolve_track_baseline(
        track=track,
        track_layout=track_layout,
        vehicle_variant=vehicle_variant,
    )

    if baseline.get("status") != "TRACK_MATCH_BASELINE_SHADOW":
        return {
            "policy_version": MATCH_PROMOTION_POLICY_VERSION,
            "status": str(baseline.get("status") or "NO_TRACK_BASELINE"),
            "eligible": False,
            "production_match_authorized": (
                baseline.get("status") == "EXACT_VARIANT_CALIBRATION"
            ),
            "production_reject_authorized": (
                baseline.get("status") == "EXACT_VARIANT_CALIBRATION"
            ),
            "confirmed_automatic_matches": 0,
            "false_automatic_matches": 0,
            "target_variant_sessions": int(target_variant_sessions),
            "source_variants": list(
                (baseline.get("match") or {}).get("source_variants") or []
            ),
            "reasons": [],
            "batch_id": None,
        }

    candidates: list[dict[str, Any]] = []
    root = Path(batches_root)
    if root.is_dir():
        for status_path in sorted(root.glob("*/BATCH_STATUS.json")):
            batch_dir = status_path.parent
            labels_path = batch_dir / "pair_labels.json"
            if not labels_path.is_file():
                continue
            try:
                report = audit_batch(batch_dir)
            except (OSError, ValueError, TypeError):
                continue
            if (
                report.get("track") != track
                or report.get("track_layout") != track_layout
                or report.get("vehicle_variant") != vehicle_variant
            ):
                continue
            decision = evaluate_match_promotion(
                report,
                target_variant_sessions=target_variant_sessions,
            )
            decision["batch_id"] = report.get("batch_id")
            candidates.append(decision)

    if not candidates:
        return {
            "policy_version": MATCH_PROMOTION_POLICY_VERSION,
            "status": "TRACK_MATCH_BASELINE_SHADOW",
            "eligible": False,
            "production_match_authorized": False,
            "production_reject_authorized": False,
            "confirmed_automatic_matches": 0,
            "false_automatic_matches": 0,
            "target_variant_sessions": int(target_variant_sessions),
            "source_variants": list(
                (baseline.get("match") or {}).get("source_variants") or []
            ),
            "reasons": ["no_human_labeled_shadow_batch"],
            "batch_id": None,
        }

    # Strongest compatible evidence wins. An eligible batch wins over ineligible
    # batches; otherwise prefer more confirmed matches and then more sessions.
    return max(
        candidates,
        key=lambda item: (
            bool(item.get("eligible")),
            int(item.get("confirmed_automatic_matches") or 0),
            int(item.get("target_variant_sessions") or 0),
            str(item.get("batch_id") or ""),
        ),
    )
