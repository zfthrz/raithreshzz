"""Deterministic driver-facing precision helpers for Race Engineer coaching.

This module never changes detector truth.  Absolute LMU lap-distance remains the
source coordinate; the helpers derive a human-facing corner-relative coordinate
and lap-support provenance from already-authorized physical-point patterns.
"""
from __future__ import annotations

import math
import copy

import re
import statistics
from typing import Any

PRECISION_EVIDENCE_VERSION = "0.5"
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



def _driver_anchor_candidates(turn: dict[str, Any], event_kind: str) -> list[tuple[str, float]]:
    if event_kind == "braking_onset":
        return [("turn_start", turn["start_m"])]
    if event_kind in {"brake_release", "throttle_onset"}:
        return [("apex", turn["apex_m"]), ("turn_end", turn["end_m"])]
    if event_kind == "throttle_release":
        return [("turn_start", turn["start_m"]), ("apex", turn["apex_m"])]
    return [("apex", turn["apex_m"])]


def _select_driver_anchor(turn: dict[str, Any], point_m: float, event_kind: str) -> tuple[str, float]:
    return min(_driver_anchor_candidates(turn, event_kind), key=lambda x: abs(point_m - x[1]))


def _driver_anchor_label(turn_label: str, anchor_type: str, offset: float) -> tuple[str, str]:
    magnitude = int(round(abs(offset)))
    if magnitude == 0:
        relation = "at"
        if anchor_type == "turn_start":
            return relation, f"en la entrada de {turn_label}"
        if anchor_type == "turn_end":
            return relation, f"en la salida de {turn_label}"
        return relation, f"en el ápice de {turn_label}"
    if offset < 0:
        relation = "before"
        if anchor_type == "turn_start":
            return relation, f"~{magnitude} m antes de {turn_label}"
        if anchor_type == "turn_end":
            return relation, f"~{magnitude} m antes de la salida de {turn_label}"
        return relation, f"~{magnitude} m antes del ápice de {turn_label}"
    relation = "after"
    if anchor_type == "turn_start":
        return relation, f"~{magnitude} m después de la entrada de {turn_label}"
    if anchor_type == "turn_end":
        return relation, f"~{magnitude} m después de la salida de {turn_label}"
    return relation, f"~{magnitude} m después del ápice de {turn_label}"


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

    anchor_type, anchor_m = _select_driver_anchor(turn, point, event_kind)
    offset = point - anchor_m
    magnitude = int(round(abs(offset)))
    turn_label = f"T{turn['turn']} — {turn.get('name') or 'Turn'}"
    relation, driver_label = _driver_anchor_label(turn_label, anchor_type, offset)

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

def _constrained_anchor_locality(
    anchor: dict[str, Any] | None,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Require a P4-reselected anchor to remain local to its target turn.

    The gate is geometry-derived rather than a fixed metre threshold: the
    absolute cue offset must not exceed the validated span of the target turn.
    This applies only to constrained reselection; ordinary P1/P2 anchors are
    unchanged.
    """
    if not isinstance(anchor, dict) or not isinstance(profile, dict):
        return {"status": "UNAVAILABLE"}

    try:
        anchor_turn = int(anchor.get("anchor_turn"))
    except (TypeError, ValueError):
        return {"status": "UNAVAILABLE"}

    offset = _finite_float(anchor.get("relative_offset_m"))
    target = next(
        (turn for turn in _turns(profile) if turn["turn"] == anchor_turn),
        None,
    )
    if offset is None or target is None:
        return {"status": "UNAVAILABLE", "anchor_turn": anchor_turn}

    turn_span_m = target["end_m"] - target["start_m"]
    if turn_span_m <= 0:
        return {"status": "UNAVAILABLE", "anchor_turn": anchor_turn}

    abs_offset_m = abs(offset)
    result = {
        "anchor_turn": anchor_turn,
        "abs_offset_m": abs_offset_m,
        "turn_span_m": turn_span_m,
    }
    if abs_offset_m > turn_span_m:
        return {"status": "NONLOCAL", **result}
    return {"status": "LOCAL", **result}


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
            locality = _constrained_anchor_locality(constrained_anchor, profile)
            if locality.get("status") == "LOCAL":
                anchor = constrained_anchor
                coherence = {
                    "status": "RESELECTED_WITHIN_LOCATION",
                    "anchor_turn": constrained_anchor.get("anchor_turn"),
                    "original_anchor_turn": original_anchor_turn,
                    "allowed_turns": sorted(allowed_turns),
                    "locality": locality,
                }
            else:
                anchor = None
                coherence = {
                    "status": "WITHHELD_NONLOCAL_RESELECTION",
                    "anchor_turn": original_anchor_turn,
                    "candidate_anchor_turn": constrained_anchor.get("anchor_turn"),
                    "allowed_turns": sorted(allowed_turns),
                    "locality": locality,
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

COACHING_SEQUENCE_VERSION = "0.1"

_SEQUENCE_EVENT_SPECS = (
    ("braking_onset", "braking_point_patterns", "brake", "frená"),
    ("brake_release", "brake_release_patterns", "brake", "soltá el freno"),
    ("throttle_release", "throttle_release_patterns", "throttle", "soltá el acelerador"),
    ("throttle_onset", "throttle_onset_patterns", "throttle", "reaplicá el acelerador"),
)


def _coaching_sequence_event(
    item: dict[str, Any],
    spec: tuple[str, str, str, str],
) -> dict[str, Any] | None:
    event_kind, field, channel, verb = spec
    values = item.get(field, []) or []
    pattern = values[0] if values and isinstance(values[0], dict) else None
    if not isinstance(pattern, dict):
        return None

    magnitude = _finite_float(pattern.get("coaching_magnitude_m"))
    direction = str(pattern.get("coaching_direction") or "")
    evidence = pattern.get("precision_evidence")
    if magnitude is None or magnitude <= 0 or direction not in {"later", "earlier"}:
        return None
    if not isinstance(evidence, dict):
        return None

    anchor = evidence.get("corner_relative_reference")
    if not isinstance(anchor, dict):
        return None
    point = _finite_float(anchor.get("event_distance_m"))
    if point is None:
        return None

    coherence = evidence.get("anchor_coherence")
    coherence_status = (
        str(coherence.get("status") or "")
        if isinstance(coherence, dict)
        else ""
    )
    if coherence_status.startswith("WITHHELD"):
        return None

    magnitude_i = int(round(abs(magnitude)))
    timing = "más tarde" if direction == "later" else "más temprano"
    anchor_label = str(anchor.get("driver_label") or "").strip()
    text = f"{verb} aproximadamente {magnitude_i} m {timing}"
    if anchor_label:
        text += f" ({anchor_label})"

    return {
        "event_kind": event_kind,
        "channel": channel,
        "event_distance_m": point,
        "coaching_direction": direction,
        "coaching_magnitude_m": magnitude_i,
        "anchor_turn": anchor.get("anchor_turn"),
        "anchor_type": anchor.get("anchor_type"),
        "driver_label": anchor_label or None,
        "text": text,
        "precision_evidence": evidence,
    }


def build_coaching_sequence(
    item: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build an additive deterministic multi-event driver sequence."""
    if not isinstance(item, dict):
        return None

    events = [
        event
        for spec in _SEQUENCE_EVENT_SPECS
        if (event := _coaching_sequence_event(item, spec)) is not None
    ]
    if len(events) < 2:
        return None

    events.sort(key=lambda row: (row["event_distance_m"], row["event_kind"]))
    points = [row["event_distance_m"] for row in events]
    if any(b <= a for a, b in zip(points, points[1:])):
        return None

    by_kind = {row["event_kind"]: row for row in events}
    brake_on = by_kind.get("braking_onset")
    brake_release = by_kind.get("brake_release")
    if (
        brake_on
        and brake_release
        and brake_on["event_distance_m"] >= brake_release["event_distance_m"]
    ):
        return None

    throttle_release = by_kind.get("throttle_release")
    throttle_on = by_kind.get("throttle_onset")
    if (
        throttle_release
        and throttle_on
        and throttle_release["event_distance_m"] >= throttle_on["event_distance_m"]
    ):
        return None

    return {
        "version": COACHING_SEQUENCE_VERSION,
        "status": "COMBINED",
        "event_count": len(events),
        "events": events,
        "driver_summary": "; después, ".join(row["text"] for row in events),
    }


def enrich_plan_items_with_coaching_sequence(
    plan: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if not isinstance(plan, list):
        return plan
    for item in plan:
        if not isinstance(item, dict):
            continue
        sequence = build_coaching_sequence(item)
        if sequence is not None:
            item["coaching_sequence"] = sequence
        else:
            item.pop("coaching_sequence", None)
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

        # Preserve authoritative zone identity after P9/P10 presentation
        # reordering. Legacy/pre-P9 items may not carry plan_label, so keep
        # the historical positional label only as a compatibility fallback.
        raw_plan_label = item.get("plan_label")
        plan_label = (
            raw_plan_label.strip().upper()
            if isinstance(raw_plan_label, str)
            else ""
        )

        if re.fullmatch(r"[A-Z]", plan_label):
            zone_label = f"ZONA {plan_label}"
        else:
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


# ============================================================
# H5.4 P8 - DETERMINISTIC DRIVER-FACING CUE PRIORITY
# ============================================================

_P8_VERSION = "0.1"

# Priority classes mapped to integer rank (lower = higher priority).
# Only kinds that can actually appear in build_driver_cues output are
# included; unrecognized kinds sink to the bottom.
_PRIORITY_KINDS = {
    "combined_spatial_sequence": 1,
    "spatial_points": 2,
    "reference_action_profile": 3,
    "qualitative_reference_level": 4,
    "validated_llm_steering": 5,
    "repeated_steering_secondary": 5,
}

_SPATIAL_EVENT_LABELS = {
    "braking_onset": "frenada",
    "brake_release": "liberación",
    "throttle_onset": "reaplicación",
    "throttle_release": "levantada",
}


def _render_spatial_anchor_context(cue: dict) -> dict:
    """Append validated corner-relative anchors to a copied physical cue."""

    if cue.get("kind") != "spatial_points":
        return cue
    anchors: list[tuple[str, str]] = []
    for evidence in cue.get("precision_evidence", []) or []:
        if not isinstance(evidence, dict):
            continue
        anchor = evidence.get("corner_relative_reference")
        if not isinstance(anchor, dict):
            continue
        driver_label = str(anchor.get("driver_label") or "").strip()
        if not driver_label:
            continue
        event_kind = str(evidence.get("event_kind") or "").strip()
        event_label = _SPATIAL_EVENT_LABELS.get(event_kind, "punto")
        anchors.append((event_label, driver_label))
    if not anchors:
        return cue

    text = str(cue.get("text") or "").strip()
    if all(driver_label in text for _, driver_label in anchors):
        return cue
    if len(anchors) == 1:
        suffix = f" (referencia: {anchors[0][1]})"
    else:
        rendered = "; ".join(
            f"{event_label}: {driver_label}"
            for event_label, driver_label in anchors
        )
        suffix = f". Referencias: {rendered}"
    cue["text"] = text + suffix
    return cue


def _cue_priority_rank(cue: dict) -> int:
    """Return the integer priority rank for a cue; unrecognized kinds sink."""
    kind = str(cue.get("kind") or "").strip()
    return _PRIORITY_KINDS.get(kind, 999)


def _spatial_event_distance_m(cue: dict) -> float | None:
    """Return the event_distance_m that represents physical event order for a spatial cue.

    Used for Rule R3: ordering independent spatial cues by physical event order.
    """
    if not isinstance(cue, dict):
        return None
    if cue.get("kind") != "spatial_points":
        return None
    precision_evidence = cue.get("precision_evidence", [])
    if isinstance(precision_evidence, list) and precision_evidence:
        first = precision_evidence[0]
        if isinstance(first, dict):
            anchor = first.get("corner_relative_reference")
            if isinstance(anchor, dict):
                distance_m = _finite_float(anchor.get("event_distance_m"))
                if distance_m is not None and distance_m >= 0.0:
                    return distance_m
    distance_m = _finite_float(cue.get("event_distance_m"))
    return distance_m if distance_m is not None and distance_m >= 0.0 else None


def _remove_suppressed_spatial_cues(
    cues: list[dict],
) -> list[dict]:
    """Rule R2: remove spatial_points cues subsumed by combined_spatial_sequence.

    When a combined_spatial_sequence exists (Rule R1), the individual spatial
    cue that is its component must not appear alongside it.
    """
    if not cues:
        return cues

    # Check if combined_spatial_sequence is present.
    if not any(cue.get("kind") == "combined_spatial_sequence" for cue in cues):
        return cues

    # Filter: remove spatial_points cues that share brake or throttle channel.
    result = []
    for cue in cues:
        if cue.get("kind") == "spatial_points":
            channels = cue.get("channels", [])
            if isinstance(channels, list) and channels:
                channel_set = set(channels)
            elif isinstance(cue.get("channel"), str):
                channel_set = {cue["channel"]}
            else:
                channel_set = set()
            # A spatial_points cue is suppressed if its brake/throttle channel
            # is already covered by a combined_spatial_sequence.
            if "brake" in channel_set or "throttle" in channel_set:
                continue
        result.append(cue)

    return result


def _deduplicate_coaching_cues(
    cues: list[dict],
) -> list[dict]:
    """Remove duplicate cue kinds beyond the first occurrence.

    This prevents reference_action_profile or spatial_points for the same
    channel from appearing twice when a combined_spatial_sequence is present.
    Only the first cue per (kind, channel) pair survives; this is a
    pre-filter applied before priority sorting so that independent spatial
    cues for different channels (e.g. brake and throttle) are both retained.
    """
    seen: dict[str, int] = {}
    result: list[dict] = []
    for cue in cues:
        kind = cue.get("kind")
        channel = cue.get("channel")
        key = (kind, channel)
        if key in seen:
            continue
        seen[key] = 1
        result.append(cue)
    return result


def _prioritize_cues(
    cues: list[dict],
) -> list[dict]:
    """Apply deterministic priority ordering to a cue list (Rule R1, R3, R4, R5).

    Priority classes:
        1. combined_spatial_sequence
        2. spatial_points
        3. reference_action_profile
        4. qualitative_reference_level
        5. validated_llm_steering

    Independent spatial cues are ordered by physical event order
    (event_distance_m), not hard-coded channel order.

    Steering is never allowed to displace physical evidence.
    """
    if len(cues) <= 1:
        return cues

    # Deduplicate first.
    cues = _deduplicate_coaching_cues(cues)

    # Sort by priority rank, then physical event order for spatial cues.
    def sort_key(cue: dict) -> tuple[int, float]:
        event_distance_m = _spatial_event_distance_m(cue)
        return (
            _cue_priority_rank(cue),
            float("inf") if event_distance_m is None else event_distance_m,
        )

    cues.sort(key=sort_key)

    return cues


def enrich_cues_with_deterministic_priority(
    cues: list[dict],
) -> list[dict]:
    """Apply H5.4 P8 deterministic cue priority ordering to a cue list.

    This function:
        1. Removes spatial cues suppressed by combined_spatial_sequence (Rule R2).
        2. Sorts by priority rank (Rules R1, R3, R4, R5).
        3. Deduplicates cue kinds.
        4. Adds P8 metadata to each cue for auditability.

    Returns a new cue list; does not trim to max_cues.
    """
    if not isinstance(cues, list):
        return cues

    # P8 is an enrichment/presentation layer. Preserve the caller-owned list and
    # cue dictionaries so audits or alternative renderers can still inspect the
    # original authorized evidence after this function returns.
    cues = [
        _render_spatial_anchor_context(dict(cue))
        if isinstance(cue, dict)
        else cue
        for cue in cues
    ]

    # Apply rules in order: suppression, then priority ordering.
    cues = _remove_suppressed_spatial_cues(cues)
    cues = _prioritize_cues(cues)

    # Enrich each cue with P8 metadata.
    for cue in cues:
        cue["_p8_priority_rank"] = _cue_priority_rank(cue)

    return cues


# ============================================================
# H5.4 P9 - DETERMINISTIC CROSS-ZONE DRIVER-PLAN DIVERSITY
# ============================================================

# Closed action families for driver-plan diversity presentation.
_ACTION_FAMILIES = frozenset({
    "BRAKE_THROTTLE_SEQUENCE",
    "BRAKE_TIMING",
    "BRAKE_PROFILE",
    "THROTTLE_TIMING",
    "THROTTLE_PROFILE",
    "STEERING",
    "OTHER_AUTHORIZED",
})


def _derive_action_family(cue: dict) -> str:
    """Derive the closed primary action family from a P8 driver cue.

    Mapping:
      combined_spatial_sequence -> BRAKE_THROTTLE_SEQUENCE
      spatial_points brake      -> BRAKE_TIMING
      spatial_points throttle   -> THROTTLE_TIMING
      reference_action_profile brake  -> BRAKE_PROFILE
      reference_action_profile throttle -> THROTTLE_PROFILE
      validated_llm_steering / repeated_steering_secondary -> STEERING
      otherwise                   -> OTHER_AUTHORIZED

    Speed is context only and never creates an action family.
    Steering only if already authorized by P8.
    """
    kind = str(cue.get("kind") or "").strip()
    channel = str(cue.get("channel") or "").strip()

    # Distinguish timing vs profile for spatial_points and reference_action_profile.
    if kind == "spatial_points":
        return "BRAKE_TIMING" if channel == "brake" else "THROTTLE_TIMING"
    if kind == "reference_action_profile":
        return "BRAKE_PROFILE" if channel == "brake" else "THROTTLE_PROFILE"
    if kind == "qualitative_reference_level":
        channels = cue.get("channels", [])
        if isinstance(channels, list):
            if "brake" in channels and "throttle" in channels:
                return "OTHER_AUTHORIZED"
            return "BRAKE_PROFILE" if "brake" in channels else "THROTTLE_PROFILE"
        return "BRAKE_PROFILE" if channel == "brake" else "THROTTLE_PROFILE"
    if kind == "combined_spatial_sequence":
        return "BRAKE_THROTTLE_SEQUENCE"
    if kind in {"validated_llm_steering", "repeated_steering_secondary"}:
        return "STEERING"

    return "OTHER_AUTHORIZED"


def _derive_primary_action_family(cues: list[dict]) -> str:
    """Derive the primary action family from the first authorized cue.

    Fails closed (returns "OTHER_AUTHORIZED") when there is no authorized cue.
    """
    if not isinstance(cues, list):
        return "OTHER_AUTHORIZED"

    for cue in cues:
        if not isinstance(cue, dict):
            continue
        family = _derive_action_family(cue)
        if family != "OTHER_AUTHORIZED":
            return family

    return "OTHER_AUTHORIZED"


def derive_p9_presentation_metadata(cues: list[dict]) -> dict:
    """Derive deterministic P9 presentation metadata from P8 driver cues.

    Returns a dict with:
      primary_action_family: the closed action family of the first cue
      has_authorized_cue: whether at least one cue is not OTHER_AUTHORIZED
    """
    if not isinstance(cues, list):
        return {
            "primary_action_family": "OTHER_AUTHORIZED",
            "has_authorized_cue": False,
        }

    family = _derive_primary_action_family(cues)
    return {
        "primary_action_family": family,
        "has_authorized_cue": family != "OTHER_AUTHORIZED",
    }


def build_p9_presentation_order(plan: list[dict]) -> list[dict]:
    """Apply deterministic cross-zone driver-plan diversity ordering.

    This function:
      1. Derives primary_action_family from P8 driver_cues[0] for each plan item.
      2. Preserves original H5.2 order for the first occurrence of each family.
      3. Places repeated families afterward, preserving their relative order.
      4. Items with no authorized cue (OTHER_AUTHORIZED) must not displace
         authorized items.
      5. Adds deterministic presentation metadata (primary_action_family,
         original_plan_rank, presentation_rank, redundancy_status).

    Returns a new plan list with presentation metadata added; does not modify
    H5.2 ranks or remove items.
    """
    if not isinstance(plan, list):
        return plan

    # Step 1: enrich each item with primary_action_family.
    enriched: list[dict] = []
    for idx, item in enumerate(plan):
        if not isinstance(item, dict):
            item = dict(item)
        cues = item.get("driver_cues", [])
        family = _derive_primary_action_family(cues) if isinstance(cues, list) else "OTHER_AUTHORIZED"
        enriched.append({**item, "_p9_original_index": idx, "_p9_family": family})

    # Step 2: derive presentation order — first occurrence of each family
    # preserves original H5.2 order, repeated families come after.
    # Algorithm: two passes.
    #   Pass 1: collect indices of first occurrences in original order.
    #   Pass 2: append remaining items by original order, grouped by family.

    # Collect first occurrence index per family.
    family_first_index: dict[str, int] = {}
    for item in enriched:
        family = item["_p9_family"]
        if family not in family_first_index:
            family_first_index[family] = item["_p9_original_index"]

    # Collect remaining items per family (non-first occurrences).
    family_remaining: dict[str, list[dict]] = {family: [] for family in _ACTION_FAMILIES}
    for item in enriched:
        family = item["_p9_family"]
        idx = item["_p9_original_index"]
        if family_first_index.get(family) != idx:
            family_remaining.setdefault(family, []).append(item)

    # Step 3: build presentation order.
    # First occurrences in original order, then remaining items grouped by family.
    presentation_order: list[dict] = []
    for family, idx in family_first_index.items():
        item = enriched[idx]
        presentation_order.append(item)

    # Remaining items: group by family (in family insertion order), then by
    # original index within each family.
    for family in family_remaining:
        remaining = sorted(family_remaining[family], key=lambda x: x["_p9_original_index"])
        presentation_order.extend(remaining)

    # Step 4: assign presentation metadata.
    result: list[dict] = []
    seen_families: list[str] = []
    for item in presentation_order:
        family = item["_p9_family"]
        original_idx = item["_p9_original_index"]
        is_redundant = family in seen_families

        # Track families seen so far in presentation order.
        if not is_redundant:
            seen_families.append(family)

        metadata = {
            "primary_action_family": family,
            "original_plan_rank": original_idx,
            "presentation_rank": len(result),
            "redundancy_status": "REPEATED_FAMILY" if is_redundant else "FIRST_OCCURRENCE",
        }

        result.append({**item, "_p9_presentation_metadata": metadata})

    return result


# Alias for mirrors: enrich plan items with P9 presentation metadata.
enrich_plan_with_p9_presentation_metadata = build_p9_presentation_order


# ============================================================
# H5.4 P11 - DETERMINISTIC DRIVER FOCUS SLOTS
# ============================================================

_P11_POLICY_VERSION = "0.1"
_P11_STATUS_ACTIVE = "ACTIVE"
_P11_STATUS_UNAVAILABLE = "UNAVAILABLE"
_P11_MAX_FOCUS_ITEMS = 2


def build_p11_plan_focus(
    next_stint_plan: list[dict],
    next_stint_plan_presentation: dict,
) -> dict:
    """Derive a presentation-only driver focus view from P10 projection.

    This function:
      1. Takes at most the first _MAX_FOCUS_ITEMS items from P10 presentation.
      2. Deep-copies them into focus items.
      3. Preserves all existing structured fields and driver_cues exactly.
      4. Never uses time_loss, magnitude, speed, or LLM score.
      5. Returns UNAVAILABLE if P10 is not ACTIVE or presentation is invalid.
      6. Never mutates next_stint_plan or next_stint_plan_presentation.

    Returns a dict with:
      - "status": "ACTIVE" | "UNAVAILABLE"
      - "policy_version": "0.1"
      - "focus_count": number of items in items list
      - "items": list of deep-copied plan items (at most 2)

    This is presentation-only.  next_stint_plan and next_stint_plan_presentation
    are NEVER reordered, mutated, filtered, or re-ranked by this function.
    """
    p10_meta = next_stint_plan_presentation.get("_p10_presentation", {})
    if p10_meta.get("status") != _P10_STATUS_ACTIVE:
        return {
            "status": _P11_STATUS_UNAVAILABLE,
            "policy_version": _P11_POLICY_VERSION,
            "focus_count": 0,
            "items": [],
        }

    presentation = next_stint_plan_presentation.get("presentation", [])
    if not isinstance(presentation, list):
        return {
            "status": _P11_STATUS_UNAVAILABLE,
            "policy_version": _P11_POLICY_VERSION,
            "focus_count": 0,
            "items": [],
        }

    # Take at most the first N items from P10 presentation.
    focus_items = [copy.deepcopy(presentation[i]) for i in range(min(_P11_MAX_FOCUS_ITEMS, len(presentation)))]

    return {
        "status": _P11_STATUS_ACTIVE,
        "policy_version": _P11_POLICY_VERSION,
        "focus_count": len(focus_items),
        "items": focus_items,
    }


# ============================================================
# H5.4 P10 - DETERMINISTIC DRIVER-FACING PLAN PROJECTION
# ============================================================

_P10_STATUS_ACTIVE = "ACTIVE"
_P10_STATUS_FALLBACK = "FALLBACK_ORIGINAL_ORDER"
_P10_POLICY_VERSION = "0.1"

# Closed failure reason codes.
_REASON_MISSING_P9_METADATA = "MISSING_P9_METADATA"
_REASON_INVALID_PRESENTATION_RANK = "INVALID_PRESENTATION_RANK"
_REASON_DUPLICATE_PRESENTATION_RANK = "DUPLICATE_PRESENTATION_RANK"
_REASON_NON_CONTIGUOUS_PRESENTATION_RANK = "NON_CONTIGUOUS_PRESENTATION_RANK"

_VALID_REASONS = {
    _REASON_MISSING_P9_METADATA,
    _REASON_INVALID_PRESENTATION_RANK,
    _REASON_DUPLICATE_PRESENTATION_RANK,
    _REASON_NON_CONTIGUOUS_PRESENTATION_RANK,
}


def build_p10_plan_presentation(next_stint_plan: list[dict]) -> dict:
    """Derive a presentation-only view of next_stint_plan, projected by P9 ranks.

    This function:
      1. Reads the _p9_presentation_metadata.presentation_rank from every item.
      2. Validates that all ranks exist, are unique integers in {0..n-1}.
      3. If validation passes: returns a NEW list (deepcopy) sorted by presentation_rank.
      4. If validation fails: returns the original plan as a copy with FALLBACK metadata.

    Returns a dict with:
      - "presentation": the projected plan list
      - "_p10_presentation": deterministic metadata dict

    This is presentation-only.  The authoritative next_stint_plan is NEVER
    reordered, mutated, filtered, or re-ranked by this function.
    """
    if not isinstance(next_stint_plan, list):
        return {
            "presentation": next_stint_plan if isinstance(next_stint_plan, list) else [],
            "_p10_presentation": {
                "status": _P10_STATUS_FALLBACK,
                "policy_version": _P10_POLICY_VERSION,
                "item_count": 0,
                "reordered": False,
                "reason": _REASON_MISSING_P9_METADATA,
            },
        }

    n = len(next_stint_plan)

    # Step 1: extract and validate presentation_ranks.
    ranks: list[int | None] = []
    for item in next_stint_plan:
        if not isinstance(item, dict):
            return {
                "presentation": list(next_stint_plan),
                "_p10_presentation": {
                    "status": _P10_STATUS_FALLBACK,
                    "policy_version": _P10_POLICY_VERSION,
                    "item_count": n,
                    "reordered": False,
                    "reason": _REASON_MISSING_P9_METADATA,
                },
            }
        p9_meta = item.get("_p9_presentation_metadata")
        if not isinstance(p9_meta, dict):
            return {
                "presentation": list(next_stint_plan),
                "_p10_presentation": {
                    "status": _P10_STATUS_FALLBACK,
                    "policy_version": _P10_POLICY_VERSION,
                    "item_count": n,
                    "reordered": False,
                    "reason": _REASON_MISSING_P9_METADATA,
                },
            }
        rank = p9_meta.get("presentation_rank")
        if not isinstance(rank, int):
            return {
                "presentation": list(next_stint_plan),
                "_p10_presentation": {
                    "status": _P10_STATUS_FALLBACK,
                    "policy_version": _P10_POLICY_VERSION,
                    "item_count": n,
                    "reordered": False,
                    "reason": _REASON_INVALID_PRESENTATION_RANK,
                },
            }
        ranks.append(rank)

    # Step 2: check for duplicates.
    if len(set(ranks)) != len(ranks):
        return {
            "presentation": list(next_stint_plan),
            "_p10_presentation": {
                "status": _P10_STATUS_FALLBACK,
                "policy_version": _P10_POLICY_VERSION,
                "item_count": n,
                "reordered": False,
                "reason": _REASON_DUPLICATE_PRESENTATION_RANK,
            },
        }

    # Step 3: check ranks form exactly {0..n-1}.
    expected = set(range(n))
    rank_set = set(ranks)
    if rank_set != expected:
        return {
            "presentation": list(next_stint_plan),
            "_p10_presentation": {
                "status": _P10_STATUS_FALLBACK,
                "policy_version": _P10_POLICY_VERSION,
                "item_count": n,
                "reordered": False,
                "reason": _REASON_NON_CONTIGUOUS_PRESENTATION_RANK,
            },
        }

    # Step 4: build presentation view as a deepcopy sorted by presentation_rank.
    indexed = list(enumerate(next_stint_plan))
    indexed.sort(key=lambda ix: ranks[ix[0]])

    presentation = [copy.deepcopy(next_stint_plan[idx]) for idx, _ in indexed]

    # Determine if presentation order differs from original by comparing indices.
    original_order = [idx for idx, _ in indexed]
    reordered = original_order != list(range(n))

    # Infer a human-readable reason from the ordering.
    reason_text = None
    if reordered:
        # Check if there are repeated families.
        families = [
            item.get("_p9_presentation_metadata", {}).get("primary_action_family", "UNKNOWN")
            for item in presentation
        ]
        if len(set(families)) < n:
            reason_text = "REPETITION_ELIMINATION"
        else:
            reason_text = "DIVERSITY_REORDERING"
    else:
        reason_text = "DIVERSITY_NO_CHANGE"

    return {
        "presentation": presentation,
        "_p10_presentation": {
            "status": _P10_STATUS_ACTIVE,
            "policy_version": _P10_POLICY_VERSION,
            "item_count": n,
            "reordered": reordered,
            "reason": reason_text,
        },
    }
