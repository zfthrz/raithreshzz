from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MATCHER_VERSION = "0.3"
MATCHER_STATUS = "CALIBRATED_PROVISIONAL_SINGLE_CONTEXT"
CALIBRATION_CONTEXT = {
    "track": "Circuit de Spa-Francorchamps",
    "track_layout": "Circuit de Spa-Francorchamps",
    "vehicle_variant": "LMP2_ELMS",
    "human_labels": 72,
}

# Conservative high-precision core learned from the 32 human-reviewed Spa/LMP2_ELMS pairs.
# These are provisional guardrails, not universal physics constants.
MATCH_CENTER_MAX_M = 5.5
MATCH_OVERLAP_SHORTER_MIN = 0.98
MATCH_OVERLAP_UNION_MIN = 0.33
MATCH_SHARED_CHANNEL_MIN = 1

# Secondary high-precision MATCH core added after 72 human labels.
# It intentionally requires substantial spatial overlap plus similar channel sets.
# Low/zero-overlap SAME examples remain AMBIGUOUS because human SAME and AMBIGUOUS
# are interleaved there.
EXTENDED_MATCH_CENTER_MAX_M = 66.0
EXTENDED_MATCH_OVERLAP_SHORTER_MIN = 2.0 / 3.0
EXTENDED_MATCH_OVERLAP_UNION_MIN = 0.33
EXTENDED_MATCH_CHANNEL_JACCARD_MIN = 2.0 / 3.0

# Shape-conflict veto. Temporal impact is secondary evidence only and can veto a weak-shape
# automatic MATCH; it never creates a MATCH by itself.
SHAPE_CONFLICT_MEAN_SIM_MAX = 0.20
SHAPE_CONFLICT_COVERAGE_DIFF_MIN = 0.50
SHAPE_CONFLICT_IMPACT_SIM_MAX = 0.45

# Conservative automatic REJECT bound learned from the 40 human-reviewed Spa/LMP2_ELMS pairs.
# Human labels show SAME at 46 m with non-zero overlap, AMBIGUOUS at 102/194 m with zero overlap,
# and DIFFERENT from 250.5 m upward with zero overlap. Therefore only >250 m + zero overlap
# is auto-rejected; the 0-250 m zero-overlap boundary remains AMBIGUOUS.
REJECT_CENTER_GT_M = 250.0
REJECT_OVERLAP_UNION_MAX = 0.0

EPS = 1e-12


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None




def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def stable_pair_id(pair: dict[str, Any]) -> str:
    """Must remain byte-for-byte compatible in semantics with pair_review_queue.py."""
    track = str(pair.get("track") or "")
    side_a = (safe_int(pair.get("session_a")), safe_int(pair.get("episode_pk_a")))
    side_b = (safe_int(pair.get("session_b")), safe_int(pair.get("episode_pk_b")))
    payload = {"track": track, "sides": sorted([side_a, side_b])}
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]

def safe_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def per_channel_values(pair: dict[str, Any], key: str) -> list[float]:
    pcm = pair.get("per_channel_metrics")
    if not isinstance(pcm, dict):
        return []
    out: list[float] = []
    for metrics in pcm.values():
        if not isinstance(metrics, dict):
            continue
        value = safe_float(metrics.get(key))
        if value is not None:
            out.append(value)
    return out


def mean_or_none(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def shared_channel_count(pair: dict[str, Any]) -> int:
    shared = pair.get("shared_channels")
    return len(shared) if isinstance(shared, list) else 0


def context_check(pair: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for key in ("track", "track_layout", "vehicle_variant"):
        if safe_str(pair.get(key)) is None:
            reasons.append(f"missing_{key}")
    return (not reasons, reasons)


def aggregate_shape(pair: dict[str, Any]) -> dict[str, float | None]:
    return {
        "coverage_abs_diff_mean": mean_or_none(per_channel_values(pair, "coverage_abs_diff")),
        "mean_difference_similarity_mean": mean_or_none(
            per_channel_values(pair, "mean_difference_similarity")
        ),
        "peak_difference_similarity_mean": mean_or_none(
            per_channel_values(pair, "peak_difference_similarity")
        ),
        "onset_offset_abs_diff_m_mean": mean_or_none(
            per_channel_values(pair, "onset_offset_abs_diff_m")
        ),
        "end_offset_abs_diff_m_mean": mean_or_none(
            per_channel_values(pair, "end_offset_abs_diff_m")
        ),
    }


def weak_shape_conflict_veto(pair: dict[str, Any], shape: dict[str, float | None]) -> bool:
    mean_sim = shape["mean_difference_similarity_mean"]
    coverage = shape["coverage_abs_diff_mean"]
    impact = safe_float(pair.get("action_time_loss_similarity"))

    # Missing secondary evidence never forces a veto.
    if mean_sim is None or coverage is None or impact is None:
        return False

    return (
        mean_sim < SHAPE_CONFLICT_MEAN_SIM_MAX
        and coverage > SHAPE_CONFLICT_COVERAGE_DIFF_MIN
        and impact < SHAPE_CONFLICT_IMPACT_SIM_MAX
    )


def classify_pair(pair: dict[str, Any]) -> dict[str, Any]:
    context_ok, context_reasons = context_check(pair)
    if not context_ok:
        return {
            "decision": "AMBIGUOUS",
            "rule_id": "CONTEXT_INCOMPLETE",
            "reasons": context_reasons,
            "automatic": False,
        }

    center = safe_float(pair.get("center_distance_abs_diff_m"))
    overlap_union = safe_float(pair.get("overlap_over_union"))
    overlap_shorter = safe_float(pair.get("overlap_over_shorter"))
    shared_count = shared_channel_count(pair)
    shape = aggregate_shape(pair)

    if center is None or overlap_union is None or overlap_shorter is None:
        return {
            "decision": "AMBIGUOUS",
            "rule_id": "MISSING_SPATIAL_FEATURES",
            "reasons": ["required_spatial_feature_missing"],
            "automatic": False,
            "shape": shape,
        }

    # Far, non-overlapping negatives only. Human labels support automatic rejection only
    # strictly above 250 m when there is no spatial overlap.
    if center > REJECT_CENTER_GT_M and overlap_union <= REJECT_OVERLAP_UNION_MAX + EPS:
        return {
            "decision": "REJECT",
            "rule_id": "FAR_ZERO_OVERLAP",
            "reasons": [
                f"center_diff_m={center:.3f}>calibrated_reject_bound_{REJECT_CENTER_GT_M}",
                f"overlap_union={overlap_union:.6f}",
            ],
            "automatic": True,
            "shape": shape,
        }

    core_spatial_match = (
        center <= MATCH_CENTER_MAX_M
        and overlap_shorter >= MATCH_OVERLAP_SHORTER_MIN
        and overlap_union >= MATCH_OVERLAP_UNION_MIN
        and shared_count >= MATCH_SHARED_CHANNEL_MIN
    )

    channel_jaccard = safe_float(pair.get("channel_jaccard"))
    extended_spatial_channel_match = (
        center <= EXTENDED_MATCH_CENTER_MAX_M
        and overlap_shorter >= EXTENDED_MATCH_OVERLAP_SHORTER_MIN
        and overlap_union >= EXTENDED_MATCH_OVERLAP_UNION_MIN
        and channel_jaccard is not None
        and channel_jaccard >= EXTENDED_MATCH_CHANNEL_JACCARD_MIN
        and shared_count >= MATCH_SHARED_CHANNEL_MIN
    )

    if core_spatial_match or extended_spatial_channel_match:
        if weak_shape_conflict_veto(pair, shape):
            return {
                "decision": "AMBIGUOUS",
                "rule_id": "MATCH_CORE_BUT_WEAK_SHAPE_CONFLICT",
                "reasons": [
                    "core_spatial_match" if core_spatial_match else "extended_spatial_channel_match",
                    "shared_shape_mean_similarity_low",
                    "shared_coverage_difference_high",
                    "secondary_impact_similarity_low",
                ],
                "automatic": False,
                "shape": shape,
            }

        if core_spatial_match:
            return {
                "decision": "MATCH",
                "rule_id": "CORE_SPATIAL_MATCH",
                "reasons": [
                    f"center_diff_m={center:.3f}<={MATCH_CENTER_MAX_M}",
                    f"overlap_shorter={overlap_shorter:.6f}>={MATCH_OVERLAP_SHORTER_MIN}",
                    f"overlap_union={overlap_union:.6f}>={MATCH_OVERLAP_UNION_MIN}",
                    f"shared_channels={shared_count}>={MATCH_SHARED_CHANNEL_MIN}",
                ],
                "automatic": True,
                "shape": shape,
            }

        return {
            "decision": "MATCH",
            "rule_id": "EXTENDED_SPATIAL_CHANNEL_MATCH",
            "reasons": [
                f"center_diff_m={center:.3f}<={EXTENDED_MATCH_CENTER_MAX_M}",
                f"overlap_shorter={overlap_shorter:.6f}>={EXTENDED_MATCH_OVERLAP_SHORTER_MIN}",
                f"overlap_union={overlap_union:.6f}>={EXTENDED_MATCH_OVERLAP_UNION_MIN}",
                f"channel_jaccard={channel_jaccard:.6f}>={EXTENDED_MATCH_CHANNEL_JACCARD_MIN}",
                f"shared_channels={shared_count}>={MATCH_SHARED_CHANNEL_MIN}",
            ],
            "automatic": True,
            "shape": shape,
        }

    return {
        "decision": "AMBIGUOUS",
        "rule_id": "UNRESOLVED_BOUNDARY",
        "reasons": [
            "not_in_high_precision_match_core",
            "not_in_calibrated_far_reject_core",
        ],
        "automatic": False,
        "shape": shape,
    }


def load_pairs(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("episode_pair_features debe ser una lista JSON.")
    return [p for p in raw if isinstance(p, dict)]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Matcher cross-session H2 v0.3 conservador: MATCH / AMBIGUOUS / REJECT."
    )
    ap.add_argument("features_json")
    ap.add_argument("--output", default="episode_pair_matches.json")
    args = ap.parse_args()

    source = Path(args.features_json).resolve()
    output = Path(args.output).resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    pairs = load_pairs(source)
    decisions: list[dict[str, Any]] = []
    counts = {"MATCH": 0, "AMBIGUOUS": 0, "REJECT": 0}

    for index, pair in enumerate(pairs):
        result = classify_pair(pair)
        decision = str(result["decision"])
        counts[decision] = counts.get(decision, 0) + 1
        decisions.append({
            "pair_index": index,
            "pair_id": stable_pair_id(pair),
            "session_a": pair.get("session_a"),
            "session_b": pair.get("session_b"),
            "episode_pk_a": pair.get("episode_pk_a"),
            "episode_pk_b": pair.get("episode_pk_b"),
            "track": pair.get("track"),
            "track_layout": pair.get("track_layout"),
            "vehicle_variant": pair.get("vehicle_variant"),
            **result,
        })

    payload = {
        "metadata": {
            "matcher_version": MATCHER_VERSION,
            "matcher_status": MATCHER_STATUS,
            "created_at_utc": utc_now_iso(),
            "source_features": str(source),
            "calibration_context": CALIBRATION_CONTEXT,
            "policy": (
                "High-precision provisional matcher. Automatic MATCH/REJECT only in human-supported cores; "
                "unobserved boundary space remains AMBIGUOUS. No clustering or persistent_pattern creation."
            ),
            "thresholds": {
                "match_center_max_m": MATCH_CENTER_MAX_M,
                "match_overlap_shorter_min": MATCH_OVERLAP_SHORTER_MIN,
                "match_overlap_union_min": MATCH_OVERLAP_UNION_MIN,
                "match_shared_channel_min": MATCH_SHARED_CHANNEL_MIN,
                "extended_match_center_max_m": EXTENDED_MATCH_CENTER_MAX_M,
                "extended_match_overlap_shorter_min": EXTENDED_MATCH_OVERLAP_SHORTER_MIN,
                "extended_match_overlap_union_min": EXTENDED_MATCH_OVERLAP_UNION_MIN,
                "extended_match_channel_jaccard_min": EXTENDED_MATCH_CHANNEL_JACCARD_MIN,
                "shape_conflict_mean_similarity_max": SHAPE_CONFLICT_MEAN_SIM_MAX,
                "shape_conflict_coverage_diff_min": SHAPE_CONFLICT_COVERAGE_DIFF_MIN,
                "shape_conflict_impact_similarity_max": SHAPE_CONFLICT_IMPACT_SIM_MAX,
                "reject_center_gt_m": REJECT_CENTER_GT_M,
                "reject_overlap_union_max": REJECT_OVERLAP_UNION_MAX,
            },
        },
        "counts": counts,
        "decisions": decisions,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 72)
    print(f"RACE ENGINEER - CROSS-SESSION EPISODE MATCHER v{MATCHER_VERSION}")
    print("=" * 72)
    print(f"Status: {MATCHER_STATUS}")
    print(f"Pairs: {len(pairs)}")
    print(f"MATCH: {counts['MATCH']}")
    print(f"AMBIGUOUS: {counts['AMBIGUOUS']}")
    print(f"REJECT: {counts['REJECT']}")
    print(f"Output: {output}")
    print("persistent_pattern: NOT_IMPLEMENTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
