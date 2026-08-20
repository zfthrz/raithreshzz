"""Deterministic driver-facing precision helpers for Race Engineer coaching.

This module never changes detector truth.  Absolute LMU lap-distance remains the
source coordinate; the helpers derive a human-facing corner-relative coordinate
and lap-support provenance from already-authorized physical-point patterns.
"""
from __future__ import annotations

import math
import re
import statistics
from typing import Any

PRECISION_EVIDENCE_VERSION = "0.1"
_COMPARISON_RE = re.compile(r"^\s*(\d+)\s*(?:->|→)\s*(\d+)\s*$")


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def lap_support_from_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    """Derive reference/supporting laps and observed delta range.

    Only consumes explicit comparison ids and deltas already present in the
    deterministic repeated-point pattern.  Ambiguous reference laps fail closed.
    """
    refs: set[int] = set()
    supporting: set[int] = set()
    for raw in pattern.get("comparisons", []) or []:
        match = _COMPARISON_RE.match(str(raw))
        if not match:
            continue
        refs.add(int(match.group(1)))
        supporting.add(int(match.group(2)))

    deltas = [
        value
        for value in (_finite_float(v) for v in (pattern.get("deltas_m", []) or []))
        if value is not None
    ]
    abs_deltas = sorted(abs(value) for value in deltas)

    return {
        "reference_lap": next(iter(refs)) if len(refs) == 1 else None,
        "supporting_laps": sorted(supporting),
        "support_count": len(supporting),
        "observed_delta_min_m": min(abs_deltas) if abs_deltas else None,
        "observed_delta_max_m": max(abs_deltas) if abs_deltas else None,
        "representative_delta_m": (
            int(round(abs(_finite_float(pattern.get("median_delta_m")))))
            if _finite_float(pattern.get("median_delta_m")) is not None
            else (
                int(round(statistics.median(abs_deltas))) if abs_deltas else None
            )
        ),
    }


def _turns(profile: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for turn in profile.get("turns", []) or []:
        if not isinstance(turn, dict):
            continue
        start = _finite_float(turn.get("start_m"))
        apex = _finite_float(turn.get("apex_m"))
        end = _finite_float(turn.get("end_m"))
        try:
            number = int(turn.get("turn"))
        except (TypeError, ValueError):
            continue
        if start is None or apex is None or end is None or not (start <= apex <= end):
            continue
        result.append({**turn, "turn": number, "start_m": start, "apex_m": apex, "end_m": end})
    return sorted(result, key=lambda row: row["start_m"])


def _select_turn(profile: dict[str, Any], point_m: float, event_kind: str) -> dict[str, Any] | None:
    turns = _turns(profile)
    if not turns:
        return None

    containing = [t for t in turns if t["start_m"] <= point_m <= t["end_m"]]
    if containing:
        return min(containing, key=lambda t: abs(t["apex_m"] - point_m))

    if event_kind == "braking_onset":
        # A braking point is normally before corner entry; prefer the next turn.
        after = [t for t in turns if t["start_m"] > point_m]
        if after:
            return min(after, key=lambda t: t["start_m"] - point_m)

    # For releases/throttle points prefer the closest geometric apex.
    return min(turns, key=lambda t: abs(t["apex_m"] - point_m))


def corner_relative_anchor(
    profile: dict[str, Any] | None,
    point_m: Any,
    *,
    event_kind: str,
) -> dict[str, Any] | None:
    """Translate an absolute event point to a deterministic corner-relative label."""
    if not isinstance(profile, dict):
        return None
    point = _finite_float(point_m)
    if point is None:
        return None
    turn = _select_turn(profile, point, event_kind)
    if turn is None:
        return None

    anchor_type = "turn_start" if event_kind == "braking_onset" else "apex"
    anchor_m = turn["start_m"] if anchor_type == "turn_start" else turn["apex_m"]
    offset = point - anchor_m
    magnitude = int(round(abs(offset)))
    turn_label = f"T{turn['turn']} — {turn.get('name') or 'Turn'}"

    if magnitude == 0:
        relation = "at"
        if anchor_type == "turn_start":
            driver_label = f"en la entrada de {turn_label}"
        else:
            driver_label = f"en el ápice de {turn_label}"
    elif offset < 0:
        relation = "before"
        if anchor_type == "turn_start":
            driver_label = f"~{magnitude} m antes de {turn_label}"
        else:
            driver_label = f"~{magnitude} m antes del ápice de {turn_label}"
    else:
        relation = "after"
        if anchor_type == "turn_start":
            driver_label = f"~{magnitude} m después de la entrada de {turn_label}"
        else:
            driver_label = f"~{magnitude} m después del ápice de {turn_label}"

    return {
        "event_distance_m": point,
        "anchor_turn": turn["turn"],
        "anchor_name": turn.get("name"),
        "anchor_type": anchor_type,
        "anchor_distance_m": anchor_m,
        "relative_offset_m": offset,
        "relative_magnitude_m": magnitude,
        "relation": relation,
        "driver_label": driver_label,
    }


def build_precision_evidence(
    pattern: dict[str, Any],
    profile: dict[str, Any] | None,
    *,
    event_kind: str,
    point_key: str,
) -> dict[str, Any]:
    evidence = {
        "version": PRECISION_EVIDENCE_VERSION,
        "event_kind": event_kind,
        **lap_support_from_pattern(pattern),
        "corner_relative_reference": corner_relative_anchor(
            profile,
            pattern.get(point_key),
            event_kind=event_kind,
        ),
    }
    return evidence


def enrich_patterns_with_precision(
    patterns: list[dict[str, Any]] | None,
    profile: dict[str, Any] | None,
    *,
    event_kind: str,
    point_key: str,
) -> list[dict[str, Any]] | None:
    """Attach deterministic precision evidence in-place to valid point patterns."""
    if not isinstance(patterns, list):
        return patterns
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        pattern["precision_evidence"] = build_precision_evidence(
            pattern,
            profile,
            event_kind=event_kind,
            point_key=point_key,
        )
    return patterns
