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

SPA_CALIBRATION_KEY = (
    "Circuit de Spa-Francorchamps",
    "Circuit de Spa-Francorchamps",
    "LMP2_ELMS",
)
IMOLA_CALIBRATION_KEY = (
    "Autodromo Enzo e Dino Ferrari",
    "Autodromo Enzo e Dino Ferrari",
    "LMP2_ELMS",
)
INTERLAGOS_CALIBRATION_KEY = (
    "Autódromo José Carlos Pace",
    "Autódromo José Carlos Pace",
    "LMP2_ELMS",
)

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

# Calibraciones por contexto exacto. Spa es la calibración original v0.3 (72
# labels). Imola LMP2_ELMS se derivó del batch 5a8126df14 (24 labels: 2 SAME,
# 6 DIFFERENT, 1 AMBIGUOUS en calibración) con un núcleo MATCH conservador
# (overlap fuerte) y REJECT para pares lejanos sin overlap; los SAME sin overlap
# espacial quedan AMBIGUOUS (fail-closed). Contextos sin entrada no producen
# MATCH/REJECT automáticos.
CALIBRATIONS: dict[tuple[str, str, str], dict[str, Any]] = {
    SPA_CALIBRATION_KEY: {
        "status": "CALIBRATED_PROVISIONAL_SINGLE_CONTEXT",
        "human_labels": 72,
        "thresholds": {
            "match_center_max_m": MATCH_CENTER_MAX_M,
            "match_overlap_shorter_min": MATCH_OVERLAP_SHORTER_MIN,
            "match_overlap_union_min": MATCH_OVERLAP_UNION_MIN,
            "match_shared_channel_min": MATCH_SHARED_CHANNEL_MIN,
            "extended_match_center_max_m": EXTENDED_MATCH_CENTER_MAX_M,
            "extended_match_overlap_shorter_min": EXTENDED_MATCH_OVERLAP_SHORTER_MIN,
            "extended_match_overlap_union_min": EXTENDED_MATCH_OVERLAP_UNION_MIN,
            "extended_match_channel_jaccard_min": EXTENDED_MATCH_CHANNEL_JACCARD_MIN,
            "shape_conflict_mean_sim_max": SHAPE_CONFLICT_MEAN_SIM_MAX,
            "shape_conflict_coverage_diff_min": SHAPE_CONFLICT_COVERAGE_DIFF_MIN,
            "shape_conflict_impact_sim_max": SHAPE_CONFLICT_IMPACT_SIM_MAX,
            "reject_center_gt_m": REJECT_CENTER_GT_M,
            "reject_overlap_union_max": REJECT_OVERLAP_UNION_MAX,
        },
    },
    IMOLA_CALIBRATION_KEY: {
        "status": "CALIBRATED_PROVISIONAL_LOW_EVIDENCE",
        "human_labels": 24,
        "provenance": {
            "batch_id": "5a8126df14",
            "calibration_pairs": 9,
            "evaluation_pairs": 1,
            "labels": {"SAME": 2, "DIFFERENT": 6, "AMBIGUOUS": 1},
        },
        "thresholds": {
            "match_center_max_m": 200.0,
            "match_overlap_shorter_min": 0.90,
            "match_overlap_union_min": 0.40,
            "match_shared_channel_min": 1,
            "extended_match_center_max_m": None,
            "shape_conflict_mean_sim_max": SHAPE_CONFLICT_MEAN_SIM_MAX,
            "shape_conflict_coverage_diff_min": SHAPE_CONFLICT_COVERAGE_DIFF_MIN,
            "shape_conflict_impact_sim_max": SHAPE_CONFLICT_IMPACT_SIM_MAX,
            "reject_center_gt_m": 300.0,
            "reject_overlap_union_max": 0.33,
        },
    },
    INTERLAGOS_CALIBRATION_KEY: {
        "status": "CALIBRATED_PROVISIONAL_LOW_EVIDENCE",
        "human_labels": 24,
        "provenance": {
            "batch_id": "40c70a4dd3",
            "calibration_pairs": 4,
            "evaluation_pairs": 5,
            "labels": {"SAME": 1, "DIFFERENT": 2, "AMBIGUOUS": 1},
        },
        "thresholds": {
            "match_center_max_m": 200.0,
            "match_overlap_shorter_min": 0.90,
            "match_overlap_union_min": 0.40,
            "match_shared_channel_min": 1,
            "extended_match_center_max_m": None,
            "shape_conflict_mean_sim_max": SHAPE_CONFLICT_MEAN_SIM_MAX,
            "shape_conflict_coverage_diff_min": SHAPE_CONFLICT_COVERAGE_DIFF_MIN,
            "shape_conflict_impact_sim_max": SHAPE_CONFLICT_IMPACT_SIM_MAX,
            "reject_center_gt_m": 500.0,
            "reject_overlap_union_max": 0.33,
        },
    },
}

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


def resolve_calibration(
    pair: dict[str, Any],
) -> dict[str, Any] | None:
    """Calibración exacta por contexto (track, layout, variante)."""
    key = (
        safe_str(pair.get("track")),
        safe_str(pair.get("track_layout")),
        safe_str(pair.get("vehicle_variant")),
    )
    return CALIBRATIONS.get(key)


def weak_shape_conflict_veto(
    pair: dict[str, Any],
    shape: dict[str, float | None],
    thresholds: dict[str, Any],
) -> bool:
    mean_sim = shape["mean_difference_similarity_mean"]
    coverage = shape["coverage_abs_diff_mean"]
    impact = safe_float(pair.get("action_time_loss_similarity"))

    # Missing secondary evidence never forces a veto.
    if mean_sim is None or coverage is None or impact is None:
        return False

    return (
        mean_sim < thresholds["shape_conflict_mean_sim_max"]
        and coverage > thresholds["shape_conflict_coverage_diff_min"]
        and impact < thresholds["shape_conflict_impact_sim_max"]
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

    calibration = resolve_calibration(pair)
    if calibration is None:
        return {
            "decision": "AMBIGUOUS",
            "rule_id": "NO_CALIBRATION_FOR_CONTEXT",
            "reasons": [
                f"context {safe_str(pair.get('track'))}/{safe_str(pair.get('track_layout'))}/"
                f"{safe_str(pair.get('vehicle_variant'))} sin calibracion",
            ],
            "automatic": False,
            "shape": aggregate_shape(pair),
        }
    thresholds = calibration["thresholds"]
    reject_center_gt_m = thresholds["reject_center_gt_m"]
    reject_overlap_union_max = thresholds["reject_overlap_union_max"]
    match_center_max_m = thresholds["match_center_max_m"]
    match_overlap_shorter_min = thresholds["match_overlap_shorter_min"]
    match_overlap_union_min = thresholds["match_overlap_union_min"]
    match_shared_channel_min = thresholds["match_shared_channel_min"]
    extended_center_max_m = thresholds.get("extended_match_center_max_m")
    extended_overlap_shorter_min = thresholds.get(
        "extended_match_overlap_shorter_min"
    )
    extended_overlap_union_min = thresholds.get("extended_match_overlap_union_min")
    extended_channel_jaccard_min = thresholds.get(
        "extended_match_channel_jaccard_min"
    )

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
    if (
        center > reject_center_gt_m
        and overlap_union <= reject_overlap_union_max + EPS
    ):
        return {
            "decision": "REJECT",
            "rule_id": "FAR_ZERO_OVERLAP",
            "reasons": [
                f"center_diff_m={center:.3f}>calibrated_reject_bound_{reject_center_gt_m}",
                f"overlap_union={overlap_union:.6f}",
            ],
            "automatic": True,
            "shape": shape,
        }

    core_spatial_match = (
        center <= match_center_max_m
        and overlap_shorter >= match_overlap_shorter_min
        and overlap_union >= match_overlap_union_min
        and shared_count >= match_shared_channel_min
    )

    channel_jaccard = safe_float(pair.get("channel_jaccard"))
    extended_spatial_channel_match = (
        extended_center_max_m is not None
        and extended_overlap_shorter_min is not None
        and extended_overlap_union_min is not None
        and extended_channel_jaccard_min is not None
        and center <= extended_center_max_m
        and overlap_shorter >= extended_overlap_shorter_min
        and overlap_union >= extended_overlap_union_min
        and channel_jaccard is not None
        and channel_jaccard >= extended_channel_jaccard_min
        and shared_count >= match_shared_channel_min
    )

    if core_spatial_match or extended_spatial_channel_match:
        if weak_shape_conflict_veto(pair, shape, thresholds):
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
                    f"center_diff_m={center:.3f}<={match_center_max_m}",
                    f"overlap_shorter={overlap_shorter:.6f}>={match_overlap_shorter_min}",
                    f"overlap_union={overlap_union:.6f}>={match_overlap_union_min}",
                    f"shared_channels={shared_count}>={match_shared_channel_min}",
                ],
                "automatic": True,
                "shape": shape,
            }

        return {
            "decision": "MATCH",
            "rule_id": "EXTENDED_SPATIAL_CHANNEL_MATCH",
            "reasons": [
                f"center_diff_m={center:.3f}<={extended_center_max_m}",
                f"overlap_shorter={overlap_shorter:.6f}>={extended_overlap_shorter_min}",
                f"overlap_union={overlap_union:.6f}>={extended_overlap_union_min}",
                f"channel_jaccard={channel_jaccard:.6f}>={extended_channel_jaccard_min}",
                f"shared_channels={shared_count}>={match_shared_channel_min}",
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

    calibration = resolve_calibration(pairs[0]) if pairs else None
    if calibration is not None:
        matcher_status = str(calibration["status"])
        resolved_context = {
            "track": safe_str(pairs[0].get("track")),
            "track_layout": safe_str(pairs[0].get("track_layout")),
            "vehicle_variant": safe_str(pairs[0].get("vehicle_variant")),
            "human_labels": calibration.get("human_labels"),
        }
        if calibration.get("provenance"):
            resolved_context["provenance"] = calibration["provenance"]
        resolved_thresholds = dict(calibration["thresholds"])
    else:
        matcher_status = "NO_CALIBRATION_FOR_CONTEXT"
        resolved_context = None
        resolved_thresholds = {}

    payload = {
        "metadata": {
            "matcher_version": MATCHER_VERSION,
            "matcher_status": matcher_status,
            "created_at_utc": utc_now_iso(),
            "source_features": str(source),
            "calibration_context": resolved_context,
            "policy": (
                "High-precision provisional matcher. Automatic MATCH/REJECT only in human-supported cores; "
                "unobserved boundary space remains AMBIGUOUS. No clustering or persistent_pattern creation."
            ),
            "thresholds": resolved_thresholds,
        },
        "counts": counts,
        "decisions": decisions,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 72)
    print(f"RACE ENGINEER - CROSS-SESSION EPISODE MATCHER v{MATCHER_VERSION}")
    print("=" * 72)
    print(f"Status: {matcher_status}")
    print(f"Pairs: {len(pairs)}")
    print(f"MATCH: {counts['MATCH']}")
    print(f"AMBIGUOUS: {counts['AMBIGUOUS']}")
    print(f"REJECT: {counts['REJECT']}")
    print(f"Output: {output}")
    print("persistent_pattern: NOT_IMPLEMENTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
