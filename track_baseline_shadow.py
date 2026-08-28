from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import episode_pair_matcher as matcher


TRACK_BASELINE_POLICY_VERSION = "0.2"

MATCH_THRESHOLD_KEYS = (
    "match_enabled",
    "match_center_max_m",
    "match_overlap_shorter_min",
    "match_overlap_union_min",
    "match_shared_channel_min",
    "extended_match_center_max_m",
    "extended_match_overlap_shorter_min",
    "extended_match_overlap_union_min",
    "extended_match_channel_jaccard_min",
    "shape_conflict_mean_sim_max",
    "shape_conflict_coverage_diff_min",
    "shape_conflict_impact_sim_max",
)

REJECT_THRESHOLD_KEYS = (
    "reject_center_gt_m",
    "reject_overlap_union_max",
)


def _fingerprint_subset(thresholds: dict[str, Any], keys: tuple[str, ...]) -> str:
    payload = {key: thresholds.get(key) for key in keys}
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _eligible_calibrations(
    track: str,
    track_layout: str,
) -> list[tuple[tuple[str, str, str], dict[str, Any]]]:
    rows = []
    for key, calibration in matcher.CALIBRATIONS.items():
        if key[0] != track or key[1] != track_layout:
            continue
        status = str(calibration.get("status") or "")
        thresholds = calibration.get("thresholds")
        if not status.startswith("CALIBRATED"):
            continue
        if not isinstance(thresholds, dict) or not thresholds:
            continue
        rows.append((key, calibration))
    return rows


def _resolve_capability(
    siblings: list[tuple[tuple[str, str, str], dict[str, Any]]],
    *,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    groups: dict[str, list[tuple[tuple[str, str, str], dict[str, Any]]]] = {}
    for key, calibration in siblings:
        fingerprint = _fingerprint_subset(calibration["thresholds"], keys)
        groups.setdefault(fingerprint, []).append((key, calibration))

    if len(groups) != 1:
        return {
            "status": "CONFLICT",
            "source_variants": sorted(key[2] for key, _ in siblings),
            "fingerprints": sorted(groups),
            "calibration": None,
        }

    group = next(iter(groups.values()))
    representative = max(
        group,
        key=lambda item: (
            int(item[1].get("human_labels") or 0),
            item[0][2],
        ),
    )[1]
    return {
        "status": "AVAILABLE",
        "source_variants": sorted(key[2] for key, _ in group),
        "fingerprint": _fingerprint_subset(representative["thresholds"], keys),
        "calibration": representative,
    }


def resolve_track_baseline(
    *,
    track: str,
    track_layout: str,
    vehicle_variant: str,
) -> dict[str, Any]:
    """Resolve exact calibration or split track/layout shadow capabilities.

    Inherited thresholds are never production-authorized here. MATCH and REJECT
    are resolved independently because current human evidence shows the spatial
    REJECT boundary is more variant-sensitive than the MATCH core.
    """
    exact_key = (track, track_layout, vehicle_variant)
    exact = matcher.CALIBRATIONS.get(exact_key)
    if exact is not None:
        return {
            "policy_version": TRACK_BASELINE_POLICY_VERSION,
            "status": "EXACT_VARIANT_CALIBRATION",
            "production_authorized": True,
            "track": track,
            "track_layout": track_layout,
            "vehicle_variant": vehicle_variant,
            "match": {
                "status": "EXACT",
                "production_authorized": True,
                "source_variants": [vehicle_variant],
            },
            "reject": {
                "status": "EXACT",
                "production_authorized": True,
                "source_variants": [vehicle_variant],
            },
            "calibration": exact,
        }

    siblings = _eligible_calibrations(track, track_layout)
    if not siblings:
        return {
            "policy_version": TRACK_BASELINE_POLICY_VERSION,
            "status": "NO_TRACK_BASELINE",
            "production_authorized": False,
            "track": track,
            "track_layout": track_layout,
            "vehicle_variant": vehicle_variant,
            "match": {"status": "UNAVAILABLE", "production_authorized": False},
            "reject": {"status": "UNAVAILABLE", "production_authorized": False},
            "calibration": None,
        }

    match = _resolve_capability(siblings, keys=MATCH_THRESHOLD_KEYS)
    reject = _resolve_capability(siblings, keys=REJECT_THRESHOLD_KEYS)

    # Policy v0.2 deliberately allows only MATCH inheritance in shadow.
    # REJECT remains observational even when sibling thresholds happen to agree.
    public_match = {
        key: value for key, value in match.items() if key != "calibration"
    }
    public_reject = {
        key: value for key, value in reject.items() if key != "calibration"
    }
    public_match["production_authorized"] = False
    public_reject["production_authorized"] = False
    public_reject["inheritance_policy"] = "VARIANT_SPECIFIC_UNTIL_VALIDATED"

    status = (
        "TRACK_MATCH_BASELINE_SHADOW"
        if match["status"] == "AVAILABLE"
        else "TRACK_MATCH_BASELINE_CONFLICT"
    )

    return {
        "policy_version": TRACK_BASELINE_POLICY_VERSION,
        "status": status,
        "production_authorized": False,
        "track": track,
        "track_layout": track_layout,
        "vehicle_variant": vehicle_variant,
        "match": public_match,
        "reject": public_reject,
        "calibration": match.get("calibration"),
    }


def match_only_calibration(calibration: dict[str, Any]) -> dict[str, Any]:
    """Return a shadow-only calibration that can MATCH but can never REJECT."""
    copied = copy.deepcopy(calibration)
    thresholds = copied["thresholds"]
    thresholds["reject_center_gt_m"] = float("inf")
    thresholds["reject_overlap_union_max"] = -1.0
    return copied


def classify_pair_track_baseline_shadow(pair: dict[str, Any]) -> dict[str, Any]:
    production = matcher.classify_pair(pair)

    resolution = resolve_track_baseline(
        track=str(pair.get("track") or "").strip(),
        track_layout=str(pair.get("track_layout") or "").strip(),
        vehicle_variant=str(pair.get("vehicle_variant") or "").strip(),
    )

    if resolution["status"] != "TRACK_MATCH_BASELINE_SHADOW":
        return {
            "policy_version": TRACK_BASELINE_POLICY_VERSION,
            "production": production,
            "baseline": {
                key: value
                for key, value in resolution.items()
                if key != "calibration"
            },
            "shadow": None,
        }

    inherited = match_only_calibration(resolution["calibration"])
    shadow = matcher.classify_pair(pair, calibration_override=inherited)
    shadow = dict(shadow)
    shadow["production_authorized"] = False
    shadow["calibration_scope"] = "TRACK_MATCH_BASELINE_SHADOW"

    return {
        "policy_version": TRACK_BASELINE_POLICY_VERSION,
        "production": production,
        "baseline": {
            key: value
            for key, value in resolution.items()
            if key != "calibration"
        },
        "shadow": shadow,
    }
