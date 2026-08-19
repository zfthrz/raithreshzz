"""Track profile validator v0.2 — dual v1/v2 schema validation.

Schema v1: turns only (existing v0.1 behavior, preserved exactly).
Schema v2: turns + segments (new checks for segments).

This module extends v0.1 behavior with segment-specific validation while
preserving all v1 checks. v1 profiles validate identically to v0.1.

Segment schema (v2):
    segments: [
        {
            "segment_id": str  — unique across the profile
            "type": "straight" | "transition"
            "start_distance_m": float
            "end_distance_m": float
            "name": str (optional)
            "group": str (optional)
            "related_turn_ids": list[str]
            "confidence": "low" | "medium" | "high"
            "provenance": str
            "evidence": dict (required for v2)
        }
    ]

V2 invariants:
    - segments are OPTIONAL — a v2 profile may have 0 segments
    - segment.start_distance_m < segment.end_distance_m
    - segments ordered by start_distance_m ascending
    - segments mutually exclusive with turns (no overlap)
    - turns + segments globally ordered by start_m ascending
    - wraparound is forbidden (segments cannot cross [0, lap_length])
    - uncovered regions are valid
    - type must be "straight" or "transition"
    - provenance/evidence required per design spec
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__version__ = "0.2"


def validate_profile_v0_2(
    profile: dict[str, Any],
    lap_length_m: float | None = None,
) -> dict[str, Any]:
    """Validate a track profile (v1 or v2) and return result dict.

    Dispatches to v1 checks for schema v1 profiles.
    Dispatches to v2 checks for schema v2 profiles (adds segment validation).

    Returns dict compatible with v0.1 validate() output.
    """
    from validate_track_profiles import (
        TrackProfileValidator,
        Finding,
    )

    schema_version = profile.get("schema_version")
    turns = profile.get("turns", [])
    segments = profile.get("segments", [])

    # v1 profile: delegate to v0.1 validator (preserves v1 behavior exactly)
    if schema_version == 1:
        validator = TrackProfileValidator(profile, lap_length_m)
        result = validator.validate()
        result["validator_version"] = __version__
        return result

    # v2 profile: run v1 turn-ordering checks + segment-specific checks
    # v1 profile-level checks (layout, profile_id, status, calibration,
    #   gps_coverage, display_policy) are v1-only and do NOT apply to v2.
    # We reuse only the turn-ordering logic (gap/overlap/bounds checks on turns)
    # and add v2 segment-specific validation.
    if schema_version == 2:
        findings = _validate_segments(profile, segments, lap_length_m)
        turn_findings = _validate_turns_only(profile, turns, lap_length_m)
        all_findings = list(turn_findings) + list(findings)
        error_count = sum(1 for f in all_findings if f["severity"] == "error")
        warning_count = sum(1 for f in all_findings if f["severity"] == "warning")
        informational_count = sum(1 for f in all_findings if f["severity"] == "informational")
        status = "INVALID" if error_count > 0 else "VALID"
        if error_count == 0 and warning_count > 0:
            status = "VALID_WITH_WARNINGS"
        return {
            "status": status,
            "findings": all_findings,
            "error_count": error_count,
            "warning_count": warning_count,
            "informational_count": informational_count,
            "validator_version": __version__,
            "schema_version": 2,
        }

    # Unknown schema: fail closed
    return {
        "status": "INVALID",
        "findings": [{
            "code": "SCHEMA_VERSION",
            "severity": "error",
            "deterministic_message": (
                f"unknown schema_version: {schema_version}, "
                f"expected 1 or 2"
            ),
        }],
        "error_count": 1,
        "warning_count": 0,
        "informational_count": 0,
        "validator_version": __version__,
        "schema_version": schema_version,
    }


def _validate_turns_only(
    profile: dict[str, Any],
    turns: list[dict],
    lap_length_m: float | None,
) -> list[dict]:
    """Validate v2 turns using only v1 turn-ordering checks (gaps/overlap/bounds).

    Skips v1 profile-level checks (layout, calibration, provenance, etc.)
    which are v1-only. Reuses the turn-checking logic from v0.1 validator.

    Returns list of dict findings compatible with v0.1 output.
    """
    lap_len = lap_length_m or 7000.0  # default
    findings: list[dict] = []

    # ── Turn type validation ──
    VALID_TYPES = {"right", "left", "unknown", "hairpin", "chicane", "unknown_turn"}
    for i, turn in enumerate(turns):
        turn_type = turn.get("type")
        if turn_type is not None and turn_type not in VALID_TYPES:
            findings.append({
                "code": "TURN_TYPE",
                "severity": "error",
                "entity_id": turn.get("turn"),
                "entity_name": turn.get("name"),
                "deterministic_message": (
                    f"invalid turn type '{turn_type}' — "
                    f"must be one of {sorted(VALID_TYPES)}"
                ),
                "evidence": {"type": turn_type},
            })

    # ── Turn ordering (start < end) ──
    for i, turn in enumerate(turns):
        start = turn.get("start_m")
        end = turn.get("end_m")
        if start is None or end is None:
            findings.append({
                "code": "TURN_ORDERING",
                "severity": "error",
                "entity_id": turn.get("turn"),
                "entity_name": turn.get("name"),
                "deterministic_message": (
                    f"missing start_m or end_m for {turn.get('name', 'turn')}"
                ),
                "evidence": {"start_m": start, "end_m": end},
            })
            continue
        if start >= end:
            findings.append({
                "code": "TURN_ORDERING",
                "severity": "error",
                "entity_id": turn.get("turn"),
                "entity_name": turn.get("name"),
                "deterministic_message": (
                    f"{turn.get('name', 'turn')} start_m ({start}) >= "
                    f"end_m ({end})"
                ),
                "evidence": {"start_m": start, "end_m": end},
            })

    # ── Turn gaps between consecutive turns ──
    # Skip gap check for v2 profiles when segments are present
    # (segments fill the gaps between turns).
    has_segments = bool(profile.get("segments"))
    if not has_segments:
        for i in range(len(turns) - 1):
            curr_end = turns[i].get("end_m")
            next_start = turns[i + 1].get("start_m")
            if curr_end is not None and next_start is not None:
                gap = next_start - curr_end
                if gap > 0:
                    findings.append({
                        "code": "ORDERING_GAP",
                        "severity": "warning",
                        "entity_id": turns[i + 1].get("turn"),
                        "entity_name": turns[i + 1].get("name"),
                        "distance_start_m": curr_end,
                        "distance_end_m": next_start,
                        "deterministic_message": (
                            f"gap {gap:.1f} m between end of "
                            f"{turns[i].get('name', 'turn')} and "
                            f"start of {turns[i + 1].get('name', 'turn')}"
                        ),
                        "evidence": {
                            "prev_turn": turns[i].get("name"),
                            "next_turn": turns[i + 1].get("name"),
                            "gap_m": gap,
                            "lap_length_m": lap_len,
                        },
                    })

    # ── Turn overlap detection ──
    for i in range(len(turns) - 1):
        curr_start = turns[i].get("start_m")
        curr_end = turns[i].get("end_m")
        next_start = turns[i + 1].get("start_m")
        next_end = turns[i + 1].get("end_m")
        if (curr_start is not None and curr_end is not None
                and next_start is not None and next_end is not None):
            # Overlap: current.start < next.end AND current.end > next.start
            if curr_start < next_end and curr_end > next_start:
                overlap_start = max(curr_start, next_start)
                overlap_end = min(curr_end, next_end)
                overlap_m = overlap_end - overlap_start
                findings.append({
                    "code": "TURN_OVERLAP",
                    "severity": "error",
                    "entity_id": turns[i + 1].get("turn"),
                    "entity_name": turns[i + 1].get("name"),
                    "distance_start_m": overlap_start,
                    "distance_end_m": overlap_end,
                    "deterministic_message": (
                        f"{turns[i].get('name', 'turn')} overlaps "
                        f"{turns[i + 1].get('name', 'turn')}"
                        f" (overlap={overlap_m:.1f} m)"
                    ),
                    "evidence": {
                        "prev_turn": turns[i].get("turn"),
                        "next_turn": turns[i + 1].get("turn"),
                        "overlap_m": overlap_m,
                        "lap_length_m": lap_len,
                    },
                })

    # ── Turn bounds (start >= 0, end <= lap_length) ──
    for i, turn in enumerate(turns):
        start = turn.get("start_m")
        end = turn.get("end_m")
        if start is not None and start < 0:
            findings.append({
                "code": "TURN_BOUNDS",
                "severity": "error",
                "entity_id": turn.get("turn"),
                "deterministic_message": (
                    f"{turn.get('name', 'turn')} start_m ({start}) < 0"
                ),
                "evidence": {"start_m": start, "lap_length_m": lap_len},
            })
        if end is not None and lap_len > 0 and end > lap_len:
            findings.append({
                "code": "TURN_BOUNDS",
                "severity": "error",
                "entity_id": turn.get("turn"),
                "deterministic_message": (
                    f"{turn.get('name', 'turn')} end_m ({end}) > "
                    f"lap_length_m ({lap_len:.1f})"
                ),
                "evidence": {"end_m": end, "lap_length_m": lap_len},
            })

    return findings


def _validate_segments(
    profile: dict[str, Any],
    segments: list[dict],
    lap_length_m: float | None,
) -> list[dict]:
    """Validate v2 segments against invariants.

    Returns list of dict findings compatible with v0.1 output.
    """
    findings: list[dict] = []

    if not segments:
        # Segments are optional — no error if absent
        return findings

    turns = profile.get("turns", [])
    lap_len = lap_length_m if lap_length_m else 7000.0

    # ── Schema recognition ──
    if profile.get("schema_version") != 2:
        findings.append({
            "code": "SCHEMA_VERSION",
            "severity": "error",
            "deterministic_message": (
                f"schema_version is {profile.get('schema_version')}, "
                f"expected 2 for segments"
            ),
        })

    # ── Segment IDs unique ──
    seen_ids: set[str] = set()
    for i, seg in enumerate(segments):
        seg_id = seg.get("segment_id")
        if seg_id is None:
            findings.append({
                "code": "SEGMENT_ID",
                "severity": "error",
                "deterministic_message": "segment missing segment_id",
                "evidence": {"segment_index": i},
            })
        elif seg_id in seen_ids:
            findings.append({
                "code": "SEGMENT_ID",
                "severity": "error",
                "entity_id": seg_id,
                "deterministic_message": (
                    f"duplicate segment_id: {seg_id}"
                ),
                "evidence": {"segment_index": i},
            })
        else:
            seen_ids.add(seg_id)

    # ── Type validation ──
    VALID_SEGMENT_TYPES = {"straight", "transition"}
    for i, seg in enumerate(segments):
        seg_type = seg.get("type")
        if seg_type not in VALID_SEGMENT_TYPES:
            findings.append({
                "code": "SEGMENT_TYPE",
                "severity": "error",
                "entity_id": seg.get("segment_id"),
                "entity_name": seg.get("name"),
                "deterministic_message": (
                    f"invalid segment type '{seg_type}' — "
                    f"must be one of {sorted(VALID_SEGMENT_TYPES)}"
                ),
                "evidence": {"type": seg_type},
            })

    # ── start < end, bounds ──
    for i, seg in enumerate(segments):
        start = seg.get("start_distance_m")
        end = seg.get("end_distance_m")

        if start is None or end is None:
            findings.append({
                "code": "SEGMENT_BOUNDS",
                "severity": "error",
                "entity_id": seg.get("segment_id"),
                "deterministic_message": (
                    f"segment missing start_distance_m or end_distance_m"
                ),
                "evidence": {"segment_index": i},
            })
            continue

        if start >= end:
            findings.append({
                "code": "SEGMENT_ORDERING",
                "severity": "error",
                "entity_id": seg.get("segment_id"),
                "entity_name": seg.get("name"),
                "deterministic_message": (
                    f"start_distance_m ({start}) >= end_distance_m ({end})"
                ),
                "evidence": {"start": start, "end": end},
            })

        if start is not None and start < 0:
            findings.append({
                "code": "SEGMENT_BOUNDS",
                "severity": "error",
                "entity_id": seg.get("segment_id"),
                "deterministic_message": (
                    f"start_distance_m ({start}) < 0"
                ),
                "evidence": {"start": start},
            })

        if end is not None and lap_len > 0 and end > lap_len:
            findings.append({
                "code": "SEGMENT_BOUNDS",
                "severity": "error",
                "entity_id": seg.get("segment_id"),
                "deterministic_message": (
                    f"end_distance_m ({end}) > lap_length_m ({lap_len:.1f})"
                ),
                "evidence": {"end": end, "lap_length_m": lap_len},
            })

    # ── Ordering: segments ordered by start_distance_m ascending ──
    for i in range(len(segments) - 1):
        curr = segments[i]
        nxt = segments[i + 1]
        curr_end = curr.get("end_distance_m")
        nxt_start = nxt.get("start_distance_m")

        if curr_end is not None and nxt_start is not None:
            # segments must not overlap: curr.end <= nxt.start
            if curr_end > nxt_start:
                overlap = curr_end - nxt_start
                findings.append({
                    "code": "SEGMENT_ORDERING",
                    "severity": "error",
                    "entity_id": nxt.get("segment_id"),
                    "entity_name": nxt.get("name"),
                    "deterministic_message": (
                        f"segments overlap: {curr.get('segment_id')} "
                        f"ends at {curr_end}, but {nxt.get('segment_id')} "
                        f"starts at {nxt_start} (overlap={overlap:.1f} m)"
                    ),
                    "evidence": {
                        "prev_segment_id": curr.get("segment_id"),
                        "next_segment_id": nxt.get("segment_id"),
                        "overlap_m": overlap,
                    },
                })

    # ── No turn/segment overlap ──
    for seg in segments:
        seg_start = seg.get("start_distance_m")
        seg_end = seg.get("end_distance_m")
        if seg_start is None or seg_end is None:
            continue

        for turn in turns:
            turn_start = turn.get("start_m")
            turn_end = turn.get("end_m")
            if turn_start is None or turn_end is None:
                continue

            # Check overlap: segments must be disjoint from turns
            if seg_start < turn_end and seg_end > turn_start:
                overlap_start = max(seg_start, turn_start)
                overlap_end = min(seg_end, turn_end)
                overlap_m = overlap_end - overlap_start

                findings.append({
                    "code": "TURN_SEGMENT_OVERLAP",
                    "severity": "error",
                    "entity_id": f"{seg.get('segment_id')}/{turn.get('turn')}",
                    "entity_name": f"{seg.get('name')}/{turn.get('name')}",
                    "distance_start": overlap_start,
                    "distance_end": overlap_end,
                    "deterministic_message": (
                        f"segment overlaps turn: {seg.get('segment_id')} "
                        f"[{seg_start}, {seg_end}] overlaps "
                        f"{turn.get('name')} [{turn_start}, {turn_end}] "
                        f"(overlap={overlap_m:.1f} m)"
                    ),
                    "evidence": {
                        "segment_id": seg.get("segment_id"),
                        "segment_start": seg_start,
                        "segment_end": seg_end,
                        "turn": turn.get("turn"),
                        "turn_name": turn.get("name"),
                        "turn_start": turn_start,
                        "turn_end": turn_end,
                        "overlap_m": overlap_m,
                    },
                })

    # ── Provenance/evidence required ──
    for i, seg in enumerate(segments):
        provenance = seg.get("provenance")
        evidence = seg.get("evidence")

        if not provenance:
            findings.append({
                "code": "SEGMENT_PROVENANCE",
                "severity": "error",
                "entity_id": seg.get("segment_id"),
                "entity_name": seg.get("name"),
                "deterministic_message": (
                    "segment missing required provenance"
                ),
                "evidence": {"segment_index": i},
            })

        if not evidence or not isinstance(evidence, dict):
            findings.append({
                "code": "SEGMENT_EVIDENCE",
                "severity": "error",
                "entity_id": seg.get("segment_id"),
                "entity_name": seg.get("name"),
                "deterministic_message": (
                    "segment missing required evidence dict"
                ),
                "evidence": {"segment_index": i},
            })

    # ── Confidence required ──
    VALID_CONFIDENCE = {"low", "medium", "high"}
    for i, seg in enumerate(segments):
        confidence = seg.get("confidence")
        if confidence not in VALID_CONFIDENCE:
            findings.append({
                "code": "SEGMENT_CONFIDENCE",
                "severity": "error",
                "entity_id": seg.get("segment_id"),
                "deterministic_message": (
                    f"invalid confidence '{confidence}' — "
                    f"must be one of {sorted(VALID_CONFIDENCE)}"
                ),
                "evidence": {"confidence": confidence},
            })

    return findings
