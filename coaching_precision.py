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

PRECISION_EVIDENCE_VERSION = "0.3"
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


def _select_turn(
    profile: dict[str, Any],
    point_m: float,
    event_kind: str,
    *,
    allowed_turns: set[int] | None = None,
) -> dict[str, Any] | None:
    turns = _turns(profile)
    if allowed_turns:
        turns = [turn for turn in turns if turn["turn"] in allowed_turns]
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
    allowed_turns: set[int] | None = None,
) -> dict[str, Any] | None:
    """Translate an absolute event point to a deterministic corner-relative label."""
    if not isinstance(profile, dict):
        return None
    point = _finite_float(point_m)
    if point is None:
        return None
    turn = _select_turn(
        profile,
        point,
        event_kind,
        allowed_turns=allowed_turns,
    )
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




def _location_turns(location: dict[str, Any] | None) -> set[int]:
    """Return deterministic turn ids represented by a resolved track location.

    Prefer resolver overlaps because they are structured.  Labels are used only
    as a fallback for transition/between-corner locations with no meaningful
    overlap.  Empty means the location cannot safely constrain an anchor.
    """
    if not isinstance(location, dict) or location.get("status") not in {None, "RESOLVED"}:
        return set()

    turns: set[int] = set()
    for row in location.get("overlaps", []) or []:
        if not isinstance(row, dict):
            continue
        try:
            turn = int(row.get("turn"))
        except (TypeError, ValueError):
            continue
        overlap_m = _finite_float(row.get("overlap_m"))
        overlap_share = _finite_float(row.get("overlap_share"))
        if (overlap_m is not None and overlap_m >= 8.0) or (
            overlap_share is not None and overlap_share >= 0.10
        ):
            turns.add(turn)

    if turns:
        return turns

    label = str(location.get("label") or "")
    return {int(value) for value in re.findall(r"\bT(\d+)\b", label)}


def _coherent_anchor(
    anchor: dict[str, Any] | None,
    expected_location: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Fail closed when a relative anchor points to a different corner.

    The parent plan item's validated track_location is authoritative for the
    driver-facing region.  If it identifies turns and the derived anchor turn is
    outside that set, suppress only the relative label; lap provenance/delta
    evidence remains valid and renderable.
    """
    if not isinstance(anchor, dict):
        return None, {"status": "NO_ANCHOR"}

    allowed_turns = _location_turns(expected_location)
    if not allowed_turns:
        return anchor, {"status": "NOT_CONSTRAINED"}

    try:
        anchor_turn = int(anchor.get("anchor_turn"))
    except (TypeError, ValueError):
        return None, {
            "status": "WITHHELD_UNRESOLVED_ANCHOR_TURN",
            "allowed_turns": sorted(allowed_turns),
        }

    if anchor_turn not in allowed_turns:
        return None, {
            "status": "WITHHELD_LOCATION_MISMATCH",
            "anchor_turn": anchor_turn,
            "allowed_turns": sorted(allowed_turns),
            "expected_label": (
                expected_location.get("label")
                if isinstance(expected_location, dict)
                else None
            ),
        }

    return anchor, {
        "status": "MATCHED",
        "anchor_turn": anchor_turn,
        "allowed_turns": sorted(allowed_turns),
    }

def build_precision_evidence(
    pattern: dict[str, Any],
    profile: dict[str, Any] | None,
    *,
    event_kind: str,
    point_key: str,
    expected_location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_anchor = corner_relative_anchor(
        profile,
        pattern.get(point_key),
        event_kind=event_kind,
    )
    anchor, coherence = _coherent_anchor(raw_anchor, expected_location)

    if coherence.get("status") == "WITHHELD_LOCATION_MISMATCH":
        allowed_turns = _location_turns(expected_location)
        constrained_anchor = corner_relative_anchor(
            profile,
            pattern.get(point_key),
            event_kind=event_kind,
            allowed_turns=allowed_turns,
        )
        constrained_anchor, constrained_coherence = _coherent_anchor(
            constrained_anchor,
            expected_location,
        )
        if (
            isinstance(constrained_anchor, dict)
            and constrained_coherence.get("status") == "MATCHED"
        ):
            original_anchor_turn = coherence.get("anchor_turn")
            anchor = constrained_anchor
            coherence = {
                "status": "RESELECTED_WITHIN_LOCATION",
                "anchor_turn": constrained_anchor.get("anchor_turn"),
                "original_anchor_turn": original_anchor_turn,
                "allowed_turns": sorted(allowed_turns),
            }

    evidence = {
        "version": PRECISION_EVIDENCE_VERSION,
        "event_kind": event_kind,
        **lap_support_from_pattern(pattern),
        "corner_relative_reference": anchor,
        "anchor_coherence": coherence,
    }
    return evidence


def enrich_patterns_with_precision(
    patterns: list[dict[str, Any]] | None,
    profile: dict[str, Any] | None,
    *,
    event_kind: str,
    point_key: str,
    expected_location: dict[str, Any] | None = None,
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
            expected_location=expected_location,
        )
    return patterns


def enrich_plan_items_with_precision(
    plan: list[dict[str, Any]] | None,
    profile: dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """Attach precision evidence to every physical-point pattern in a plan.

    Repeated patterns may already be enriched upstream; rebuilding the same
    deterministic evidence is harmless. SINGLE patterns are enriched only when
    their parent finding preserved an explicit comparison id and signed delta.
    """
    if not isinstance(plan, list):
        return plan

    specs = (
        ("braking_point_patterns", "braking_onset", "reference_onset_m"),
        ("brake_release_patterns", "brake_release", "reference_release_m"),
        ("throttle_onset_patterns", "throttle_onset", "reference_onset_m"),
        ("throttle_release_patterns", "throttle_release", "reference_release_m"),
    )

    for item in plan:
        if not isinstance(item, dict):
            continue
        for field, event_kind, point_key in specs:
            enrich_patterns_with_precision(
                item.get(field),
                profile,
                event_kind=event_kind,
                point_key=point_key,
                expected_location=item.get("track_location"),
            )
    return plan
# ============================================================
# H5.4 P3 - DETERMINISTIC TRACK REFERENCE
# ============================================================

_TRACK_REFERENCE_VALID_STATUSES = {
    "VALIDATED_MULTI_SESSION",
    "VALIDATED",
}


def _track_reference_turn_label(start_turn: int, end_turn: int) -> str:
    if start_turn == end_turn:
        return f"T{start_turn}"
    return f"T{start_turn}\u2013T{end_turn}"


def _track_reference_label_turns(
    location: dict[str, Any] | None,
) -> set[int]:
    if not isinstance(location, dict):
        return set()

    label = str(location.get("label") or "")
    return {
        int(value)
        for value in re.findall(r"\bT(\d+)\b", label)
    }


def _track_reference_plan_zones(
    plan: list[dict[str, Any]] | None,
) -> dict[int, list[str]]:
    if not isinstance(plan, list):
        return {}

    by_turn: dict[int, list[str]] = {}
    for index, item in enumerate(plan[:26]):
        if not isinstance(item, dict):
            continue

        zone_label = f"ZONA {chr(ord('A') + index)}"
        location = item.get("track_location")

        turns = _track_reference_label_turns(location)
        if not turns:
            turns = _location_turns(location)

        for turn in sorted(turns):
            labels = by_turn.setdefault(turn, [])
            if zone_label not in labels:
                labels.append(zone_label)

    return by_turn


def build_track_reference_rows(
    profile: dict[str, Any] | None,
    plan: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(profile, dict):
        return []
    if str(profile.get("status") or "") not in _TRACK_REFERENCE_VALID_STATUSES:
        return []

    turns = _turns(profile)
    if not turns:
        return []

    zone_by_turn = _track_reference_plan_zones(plan)
    rows: list[dict[str, Any]] = []

    for turn in turns:
        number = int(turn["turn"])
        raw_name = str(turn.get("name") or "").strip()
        name = raw_name or f"Turn {number}"
        zone_labels = list(zone_by_turn.get(number, []))

        if (
            rows
            and rows[-1]["end_turn"] + 1 == number
            and rows[-1]["name"] == name
            and rows[-1]["plan_zones"] == zone_labels
        ):
            rows[-1]["end_turn"] = number
            for label in zone_labels:
                if label not in rows[-1]["plan_zones"]:
                    rows[-1]["plan_zones"].append(label)
            continue

        rows.append({
            "start_turn": number,
            "end_turn": number,
            "name": name,
            "plan_zones": zone_labels,
        })

    return rows


def render_track_reference_section(
    profile: dict[str, Any] | None,
    plan: list[dict[str, Any]] | None = None,
) -> str:
    rows = build_track_reference_rows(profile, plan)
    if not rows:
        return ""

    lines = [
        "## Referencia rápida del circuito",
        "",
    ]
    for row in rows:
        turn_label = _track_reference_turn_label(
            row["start_turn"],
            row["end_turn"],
        )
        line = f"- {turn_label} — {row['name']}"
        if row["plan_zones"]:
            line += " \u2190 " + " / ".join(row["plan_zones"])
        lines.append(line)

    return "\n".join(lines)
