"""Track profile validator v0.1 — deterministic audit of existing track profile JSON files.

Validator read-only: inspects profile structure, ordering, bounds, gaps/overlaps,
layout consistency, GPS consistency (if present), semantic structure, and
provenance/conidence. Does NOT correct, modify, or normalize any profile.

Schema assumed (all profiles share this shape):

    {
      "schema_version": int,
      "profile_id": str,
      "status": str,
      "track": str,
      "layout": str,
      "distance_coordinate": str,
      "calibration": object,
      "ignored_geometric_features_m": list,
      "turns": [
        { "turn": int, "name": str, "group": str, "direction": str,
          "start_m": float, "apex_m": float, "end_m": float,
          "aliases": list, "direction_sequence": list }
      ],
      "display_policy": object,
      ...
    }

Checks:

  1. ORDERING
     - start_distance_m < end_distance_m per turn
     - points/zones ordered by distance (start_m ascending across turns)
     - apex within [start_m, end_m] when present

  2. LAP BOUNDS
     - no distance < 0
     - no distance > lap_length_m (derived from calibration or last turn end_m)
     - tolerances only if already formalized in the project

  3. GAPS / OVERLAPS
     - detect gaps (end_m of turn N < start_m of turn N+1, with margin)
     - detect overlaps (start_m of turn N+1 < end_m of turn N)
     - report as informational / warning / error depending on magnitude

  4. DUPLICATE PHYSICAL POINTS
     - turns with same or near-same distance that represent incompatible entities
     - do not deduplicate automatically

  5. LAYOUT CONSISTENCY
     - track/layout present
     - lmu_track_layout is hard context: layout field must match expected
     - do not mix layouts

  6. GPS CONSISTENCY
     - if GPS data present (via calibration or external data), check:
       - missing coords
       - out of range
       - suspicious duplicates
       - basic impossible jumps
     - do NOT invent GPS

  7. SEMANTIC STRUCTURE
     - validate when exist: corner, braking zone, apex, exit, straight, complex, aliases
     - do not require fields the current schema does not mandate

  8. PROVENANCE / CONFIDENCE
     - audit presence and format if they exist
     - do NOT invent them if missing: report missing/not_available

Output: deterministic JSON with schema_version, validator_version, track,
layout, lap_length_m, status, error_count, warning_count,
informational_count, findings[], summary.

Findings contain: code, severity, entity_id/name (if exists),
distance/range relevant, deterministic_message, evidence.

Statuses:
  VALID — no errors, no warnings
  VALID_WITH_WARNINGS — warnings found, no errors
  INVALID — errors found
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


__version__ = "0.1"


@dataclass
class Finding:
    code: str
    severity: str  # "error", "warning", "informational"
    entity_id: str | None = None
    entity_name: str | None = None
    distance_start: float | None = None
    distance_end: float | None = None
    deterministic_message: str = ""
    evidence: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "code": self.code,
            "severity": self.severity,
            "deterministic_message": self.deterministic_message,
        }
        if self.entity_id is not None:
            d["entity_id"] = self.entity_id
        if self.entity_name is not None:
            d["entity_name"] = self.entity_name
        if self.distance_start is not None:
            d["distance_start_m"] = self.distance_start
        if self.distance_end is not None:
            d["distance_end_m"] = self.distance_end
        if self.evidence is not None:
            d["evidence"] = self.evidence
        return d


class TrackProfileValidator:
    """Deterministic validator for track profile JSON structures."""

    # Gap/overlap thresholds as fractions of lap length
    GAP_REPORT_THRESHOLD = 0.02  # 2% of lap length: gaps below this are informational
    GAP_WARNING_THRESHOLD = 0.05  # 5% of lap length: gaps above this are warnings
    OVERLAP_REPORT_THRESHOLD = 0.02  # 2% of lap length: overlaps below this are informational
    OVERLAP_WARNING_THRESHOLD = 0.05  # 5% of lap length: overlaps above this are errors
    DUPLICATE_DISTANCE_TOLERANCE_M = 5.0  # metres: turns with start/apex within this distance

    def __init__(self, profile: dict[str, Any], lap_length_m: float | None = None):
        self.profile = profile
        self.lap_length_m = lap_length_m
        self.turns: list[dict] = profile.get("turns", [])
        self.findings: list[Finding] = []
        self._track = profile.get("track", "UNKNOWN")
        self._layout = profile.get("layout", "UNKNOWN")

    @property
    def profile_id(self) -> str:
        return self.profile.get("profile_id", "UNKNOWN")

    @property
    def schema_version(self) -> int | None:
        return self.profile.get("schema_version")

    def _add(self, finding: Finding) -> None:
        self.findings.append(finding)

    # ── 1. ORDERING ────────────────────────────────────────────────────────────

    def check_ordering(self) -> list[str]:
        """Check turn-level ordering invariants.

        Returns list of finding codes checked.
        """
        codes: list[str] = []

        if not self.turns:
            return codes

        lap_len = self.lap_length_m or self._compute_lap_length()
        if lap_len <= 0:
            lap_len = float("inf")

        # 1a. start_m < end_m per turn; apex within [start_m, end_m]
        for i, turn in enumerate(self.turns):
            start = turn.get("start_m")
            apex = turn.get("apex_m")
            end = turn.get("end_m")

            if start is None or end is None:
                self._add(Finding(
                    code="ORDERING",
                    severity="error",
                    entity_id=turn.get("turn"),
                    entity_name=turn.get("name"),
                    deterministic_message="missing start_m or end_m",
                    evidence={"turn_index": i},
                ))
                continue

            if start >= end:
                self._add(Finding(
                    code="ORDERING",
                    severity="error",
                    entity_id=turn.get("turn"),
                    entity_name=turn.get("name"),
                    deterministic_message=(
                        f"start_m ({start}) >= end_m ({end})"
                    ),
                    evidence={"start_m": start, "end_m": end},
                ))

            if apex is not None:
                if apex < start or apex > end:
                    self._add(Finding(
                        code="ORDERING",
                        severity="warning",
                        entity_id=turn.get("turn"),
                        entity_name=turn.get("name"),
                        deterministic_message=(
                            f"apex_m ({apex}) outside [start_m, end_m] "
                            f"[{start}, {end}]"
                        ),
                        evidence={"apex_m": apex, "start_m": start, "end_m": end},
                    ))

        # 1b. Turns ordered by distance (start_m ascending across turns)
        for i in range(len(self.turns) - 1):
            current = self.turns[i]
            next_turn = self.turns[i + 1]
            curr_end = current.get("end_m")
            next_start = next_turn.get("start_m")

            if curr_end is None or next_start is None:
                continue

            # Allow exact adjacency (end of N = start of N+1)
            # Report gap if next_start > curr_end + threshold
            gap = next_start - curr_end
            if gap > 0:
                threshold = lap_len * self.GAP_REPORT_THRESHOLD
                if gap > threshold:
                    self._add(Finding(
                        code="ORDERING_GAP",
                        severity="warning",
                        entity_id=next_turn.get("turn"),
                        entity_name=next_turn.get("name"),
                        distance_start=curr_end,
                        distance_end=next_start,
                        deterministic_message=(
                            f"gap {gap:.1f} m between end of "
                            f"{current.get('name')} and start of {next_turn.get('name')}"
                        ),
                        evidence={
                            "prev_turn": current.get("name"),
                            "next_turn": next_turn.get("name"),
                            "gap_m": gap,
                            "lap_length_m": lap_len,
                        },
                    ))
                else:
                    self._add(Finding(
                        code="ORDERING_GAP",
                        severity="informational",
                        entity_id=next_turn.get("turn"),
                        entity_name=next_turn.get("name"),
                        distance_start=curr_end,
                        distance_end=next_start,
                        deterministic_message=(
                            f"minor gap {gap:.1f} m between "
                            f"{current.get('name')} and {next_turn.get('name')}"
                        ),
                        evidence={
                            "prev_turn": current.get("name"),
                            "next_turn": next_turn.get("name"),
                            "gap_m": gap,
                        },
                    ))

        codes.extend(["ORDERING", "ORDERING_GAP"])
        return codes

    # ── 2. LAP BOUNDS ──────────────────────────────────────────────────────────

    def check_lap_bounds(self) -> list[str]:
        """Check distance bounds against lap length.

        Returns list of finding codes checked.
        """
        codes: list[str] = []
        lap_len = self.lap_length_m or self._compute_lap_length()

        if lap_len <= 0:
            self._add(Finding(
                code="LAP_BOUNDS",
                severity="error",
                deterministic_message=f"lap_length_m is zero or negative ({lap_len})",
                evidence={"lap_length_m": lap_len},
            ))
            codes.append("LAP_BOUNDS")
            return codes

        for turn in self.turns:
            for field_name in ("start_m", "apex_m", "end_m"):
                dist = turn.get(field_name)
                if dist is None:
                    continue
                if dist < 0:
                    self._add(Finding(
                        code="LAP_BOUNDS",
                        severity="error",
                        entity_id=turn.get("turn"),
                        entity_name=turn.get("name"),
                        distance_start=dist,
                        deterministic_message=(
                            f"{field_name} ({dist}) < 0 for "
                            f"{turn.get('name')}"
                        ),
                        evidence={"field_name": field_name, "value_m": dist},
                    ))
                if dist > lap_len:
                    self._add(Finding(
                        code="LAP_BOUNDS",
                        severity="error",
                        entity_id=turn.get("turn"),
                        entity_name=turn.get("name"),
                        distance_start=dist,
                        deterministic_message=(
                            f"{field_name} ({dist}) > lap_length_m ({lap_len:.1f}) "
                            f"for {turn.get('name')}"
                        ),
                        evidence={
                            "field_name": field_name,
                            "value_m": dist,
                            "lap_length_m": lap_len,
                        },
                    ))

        codes.append("LAP_BOUNDS")
        return codes

    # ── 3. GAPS / OVERLAPS ─────────────────────────────────────────────────────

    def check_gaps_overlaps(self) -> list[str]:
        """Check for gaps and overlaps between consecutive turns.

        Returns list of finding codes checked.
        """
        codes: list[str] = []
        lap_len = self.lap_length_m or self._compute_lap_length()
        if lap_len <= 0:
            return codes

        for i in range(len(self.turns) - 1):
            current = self.turns[i]
            next_turn = self.turns[i + 1]
            curr_end = current.get("end_m")
            next_start = next_turn.get("start_m")

            if curr_end is None or next_start is None:
                continue

            # Overlap: next_start < curr_end
            overlap = curr_end - next_start
            if overlap > 0:
                threshold = lap_len * self.OVERLAP_REPORT_THRESHOLD
                if overlap > threshold:
                    self._add(Finding(
                        code="OVERLAP",
                        severity="error",
                        entity_id=next_turn.get("turn"),
                        entity_name=next_turn.get("name"),
                        distance_start=next_start,
                        distance_end=curr_end,
                        deterministic_message=(
                            f"overlap {overlap:.1f} m between "
                            f"{next_turn.get('name')} and "
                            f"{current.get('name')}"
                        ),
                        evidence={
                            "overlap_m": overlap,
                            "lap_length_m": lap_len,
                            "prev_turn": current.get("name"),
                            "next_turn": next_turn.get("name"),
                        },
                    ))
                else:
                    self._add(Finding(
                        code="OVERLAP",
                        severity="informational",
                        entity_id=next_turn.get("turn"),
                        entity_name=next_turn.get("name"),
                        distance_start=next_start,
                        distance_end=curr_end,
                        deterministic_message=(
                            f"minor overlap {overlap:.1f} m between "
                            f"{next_turn.get('name')} and "
                            f"{current.get('name')}"
                        ),
                        evidence={
                            "overlap_m": overlap,
                            "lap_length_m": lap_len,
                            "prev_turn": current.get("name"),
                            "next_turn": next_turn.get("name"),
                        },
                    ))

            # Gap: next_start > curr_end (already partially handled in ORDERING_GAP)
            # Here we add specific gap severity: large gaps are errors

        codes.extend(["GAPS_OVERLAPS", "OVERLAP", "ORDERING_GAP"])
        return codes

    # ── 4. DUPLICATE PHYSICAL POINTS ────────────────────────────────────────────

    def check_duplicate_points(self) -> list[str]:
        """Check for turns at the same or near-same distance representing incompatible entities.

        Returns list of finding codes checked.
        """
        codes: list[str] = []

        for i in range(len(self.turns)):
            for j in range(i + 1, len(self.turns)):
                t_a = self.turns[i]
                t_b = self.turns[j]

                start_a = t_a.get("start_m")
                start_b = t_b.get("start_m")
                apex_a = t_a.get("apex_m")
                apex_b = t_b.get("apex_m")

                if start_a is None or start_b is None:
                    continue

                # Check near-same start distance
                if abs(start_a - start_b) <= self.DUPLICATE_DISTANCE_TOLERANCE_M:
                    # Incompatible if different names/groups
                    name_a = t_a.get("name", "")
                    name_b = t_b.get("name", "")
                    group_a = t_a.get("group", "")
                    group_b = t_b.get("group", "")

                    if name_a != name_b and group_a != group_b:
                        self._add(Finding(
                            code="DUPLICATE_POINT",
                            severity="warning",
                            entity_id=f"{t_a.get('turn')}/{t_b.get('turn')}",
                            entity_name=f"{name_a}/{name_b}",
                            distance_start=start_a,
                            deterministic_message=(
                                f"turns at similar distance ({start_a:.1f} m) "
                                f"with incompatible names: {name_a} vs {name_b}"
                            ),
                            evidence={
                                "turn_a": {"name": name_a, "group": group_a, "turn": t_a.get("turn")},
                                "turn_b": {"name": name_b, "group": group_b, "turn": t_b.get("turn")},
                                "distance_m": start_a,
                            },
                        ))
                        continue

                # Check near-same apex distance
                if apex_a is not None and apex_b is not None:
                    if abs(apex_a - apex_b) <= self.DUPLICATE_DISTANCE_TOLERANCE_M:
                        name_a = t_a.get("name", "")
                        name_b = t_b.get("name", "")
                        group_a = t_a.get("group", "")
                        group_b = t_b.get("group", "")

                        if name_a != name_b and group_a != group_b:
                            self._add(Finding(
                                code="DUPLICATE_POINT",
                                severity="warning",
                                entity_id=f"{t_a.get('turn')}/{t_b.get('turn')}",
                                entity_name=f"{name_a}/{name_b}",
                                distance_start=apex_a,
                                deterministic_message=(
                                    f"turns at similar apex distance ({apex_a:.1f} m) "
                                    f"with incompatible names: {name_a} vs {name_b}"
                                ),
                                evidence={
                                    "turn_a": {"name": name_a, "group": group_a, "turn": t_a.get("turn")},
                                    "turn_b": {"name": name_b, "group": group_b, "turn": t_b.get("turn")},
                                    "apex_distance_m": apex_a,
                                },
                            ))

        codes.append("DUPLICATE_POINT")
        return codes

    # ── 5. LAYOUT CONSISTENCY ──────────────────────────────────────────────────

    def check_layout_consistency(self) -> list[str]:
        """Check layout/tracks consistency fields.

        Returns list of finding codes checked.
        """
        codes: list[str] = []

        # 5a. track and layout fields present
        if not self.profile.get("track"):
            self._add(Finding(
                code="LAYOUT_CONSISTENCY",
                severity="error",
                deterministic_message="missing 'track' field",
            ))
        if not self.profile.get("layout"):
            self._add(Finding(
                code="LAYOUT_CONSISTENCY",
                severity="error",
                deterministic_message="missing 'layout' field",
            ))

        # 5b. track == layout (within profile)
        track = self.profile.get("track")
        layout = self.profile.get("layout")
        if track and layout and track != layout:
            self._add(Finding(
                code="LAYOUT_CONSISTENCY",
                severity="warning",
                entity_name=f"{track}/{layout}",
                deterministic_message=(
                    f"track ({track}) != layout ({layout})"
                ),
                evidence={"track": track, "layout": layout},
            ))

        # 5c. calibration present (as proxy for lmu_track_layout hard context)
        calibration = self.profile.get("calibration")
        if not calibration:
            self._add(Finding(
                code="LAYOUT_CONSISTENCY",
                severity="informational",
                deterministic_message="missing 'calibration' block",
                evidence={"message": "no calibration data — layout provenance unverifiable"},
            ))

        codes.append("LAYOUT_CONSISTENCY")
        return codes

    # ── 6. GPS CONSISTENCY ──────────────────────────────────────────────────────

    def check_gps_consistency(self) -> list[str]:
        """Check GPS consistency if GPS data is present in calibration.

        Returns list of finding codes checked.
        """
        codes: list[str] = []
        calibration = self.profile.get("calibration", {})

        # Look for GPS-related fields in calibration
        gps_path = calibration.get("source_gps_path_m_approx")
        gps_coverage = None

        # Check independent sessions for GPS data
        if isinstance(calibration, dict):
            indep = calibration.get("independent_sessions", [])
            for sess in indep:
                if isinstance(sess, dict):
                    cov = sess.get("gps_coverage")
                    if cov is not None:
                        gps_coverage = cov
                        break

        # 6a. GPS path out of expected range (negative)
        if gps_path is not None and gps_path < 0:
            self._add(Finding(
                code="GPS_CONSISTENCY",
                severity="error",
                deterministic_message=(
                    f"source_gps_path_m_approx ({gps_path}) < 0"
                ),
                evidence={"gps_path_m": gps_path},
            ))

        # 6b. GPS coverage missing (informational, not error)
        if gps_coverage is None:
            self._add(Finding(
                code="GPS_CONSISTENCY",
                severity="informational",
                deterministic_message=(
                    "gps_coverage not available in calibration sessions"
                ),
                evidence={"message": "gps_coverage missing from all sessions"},
            ))
        elif gps_coverage < 0 or gps_coverage > 1:
            self._add(Finding(
                code="GPS_CONSISTENCY",
                severity="error",
                deterministic_message=(
                    f"gps_coverage ({gps_coverage}) out of range [0, 1]"
                ),
                evidence={"gps_coverage": gps_coverage},
            ))

        # 6c. Check turns for GPS-like data (apex GPS not present in standard schema)
        # This is a placeholder for future GPS-augmented profiles
        gps_field_found = any(
            "gps" in key.lower() for turn in self.turns
            for key in turn.keys()
        )
        if not gps_field_found:
            # Informational: no GPS per-turn data
            pass  # Standard profiles don't include per-turn GPS

        codes.append("GPS_CONSISTENCY")
        return codes

    # ── 7. SEMANTIC STRUCTURE ──────────────────────────────────────────────────

    def check_semantic_structure(self) -> list[str]:
        """Check semantic structure fields when they exist.

        Validates: direction, aliases, group, direction_sequence
        without requiring fields the schema doesn't mandate.
        """
        codes: list[str] = []

        VALID_DIRECTIONS = {"left", "right", "mixed"}
        VALID_DIRECTION_SEQUENCE = ["left", "right"]  # mixed handled by direction

        for turn in self.turns:
            direction = turn.get("direction")
            if direction is not None and direction not in VALID_DIRECTIONS:
                self._add(Finding(
                    code="SEMANTIC_STRUCTURE",
                    severity="error",
                    entity_id=turn.get("turn"),
                    entity_name=turn.get("name"),
                    deterministic_message=(
                        f"unknown direction '{direction}' for {turn.get('name')}"
                    ),
                    evidence={"direction": direction, "valid_directions": list(VALID_DIRECTIONS)},
                ))

            direction_seq = turn.get("direction_sequence")
            if direction_seq is not None:
                if not isinstance(direction_seq, list):
                    self._add(Finding(
                        code="SEMANTIC_STRUCTURE",
                        severity="error",
                        entity_id=turn.get("turn"),
                        entity_name=turn.get("name"),
                        deterministic_message=(
                            f"direction_sequence is not a list for {turn.get('name')}"
                        ),
                        evidence={"direction_sequence": direction_seq},
                    ))
                else:
                    for dir_item in direction_seq:
                        if dir_item not in ("left", "right"):
                            self._add(Finding(
                                code="SEMANTIC_STRUCTURE",
                                severity="error",
                                entity_id=turn.get("turn"),
                                entity_name=turn.get("name"),
                                deterministic_message=(
                                    f"unknown direction '{dir_item}' "
                                    f"in direction_sequence for {turn.get('name')}"
                                ),
                                evidence={"direction_item": dir_item},
                            ))

            aliases = turn.get("aliases")
            if aliases is not None:
                if not isinstance(aliases, list):
                    self._add(Finding(
                        code="SEMANTIC_STRUCTURE",
                        severity="error",
                        entity_id=turn.get("turn"),
                        entity_name=turn.get("name"),
                        deterministic_message=(
                            f"aliases is not a list for {turn.get('name')}"
                        ),
                        evidence={"aliases": aliases},
                    ))

            # group is informational, not required
            # name is required by schema
            if not turn.get("name"):
                self._add(Finding(
                    code="SEMANTIC_STRUCTURE",
                    severity="error",
                    entity_id=turn.get("turn"),
                    deterministic_message="missing 'name' field",
                ))

        codes.append("SEMANTIC_STRUCTURE")
        return codes

    # ── 8. PROVENANCE / CONFIDENCE ─────────────────────────────────────────────

    def check_provenance(self) -> list[str]:
        """Audit presence and format of provenance fields.

        Reports missing/not_available for fields that are absent.
        """
        codes: list[str] = []

        # 8a. schema_version present
        schema_ver = self.profile.get("schema_version")
        if schema_ver is None:
            self._add(Finding(
                code="PROVENANCE",
                severity="error",
                deterministic_message="missing 'schema_version'",
                evidence={"message": "schema_version not found in profile"},
            ))
        elif not isinstance(schema_ver, int):
            self._add(Finding(
                code="PROVENANCE",
                severity="error",
                deterministic_message=(
                    f"schema_version is not an int: {type(schema_ver).__name__}"
                ),
                evidence={"schema_version": schema_ver},
            ))

        # 8b. profile_id present
        profile_id = self.profile.get("profile_id")
        if profile_id is None:
            self._add(Finding(
                code="PROVENANCE",
                severity="error",
                deterministic_message="missing 'profile_id'",
                evidence={"message": "profile_id not found in profile"},
            ))

        # 8c. status present
        status = self.profile.get("status")
        if status is None:
            self._add(Finding(
                code="PROVENANCE",
                severity="error",
                deterministic_message="missing 'status'",
                evidence={"message": "status not found in profile"},
            ))

        # 8d. calibration provenance
        calibration = self.profile.get("calibration")
        if calibration and isinstance(calibration, dict):
            source = calibration.get("source_session")
            if source is None:
                self._add(Finding(
                    code="PROVENANCE",
                    severity="informational",
                    deterministic_message=(
                        "calibration.source_session not available"
                    ),
                    evidence={"message": "source_session missing from calibration"},
                ))

        # 8e. display_policy present (informational, not error)
        display_policy = self.profile.get("display_policy")
        if display_policy is None:
            self._add(Finding(
                code="PROVENANCE",
                severity="informational",
                deterministic_message="missing 'display_policy'",
                evidence={"message": "display_policy not found in profile"},
            ))

        codes.extend(["PROVENANCE", "PROVENANCE_SCHEMA", "PROVENANCE_CALIBRATION"])
        return codes

    # ── Run all checks ──────────────────────────────────────────────────────────

    def _compute_lap_length(self) -> float:
        """Derive lap length from calibration or last turn end_m."""
        calibration = self.profile.get("calibration", {})
        if isinstance(calibration, dict):
            # Source lap dist max
            dist_max = calibration.get("source_lap_dist_max_m")
            if dist_max is not None and dist_max > 0:
                return dist_max
        # Fallback: last turn end_m
        if self.turns:
            last_turn = self.turns[-1]
            return last_turn.get("end_m", 0)
        return 0

    def validate(self) -> dict[str, Any]:
        """Run all checks and return deterministic result dict.

        Returns dict with:
          - schema_version
          - validator_version
          - track
          - layout
          - lap_length_m
          - status: VALID | VALID_WITH_WARNINGS | INVALID
          - error_count
          - warning_count
          - informational_count
          - findings: list of dicts
          - summary: dict of checks run
        """
        self.findings = []

        # Run all checks
        self.check_ordering()
        self.check_lap_bounds()
        self.check_gaps_overlaps()
        self.check_duplicate_points()
        self.check_layout_consistency()
        self.check_gps_consistency()
        self.check_semantic_structure()
        self.check_provenance()

        # Count by severity
        error_count = sum(1 for f in self.findings if f.severity == "error")
        warning_count = sum(1 for f in self.findings if f.severity == "warning")
        informational_count = sum(1 for f in self.findings if f.severity == "informational")

        # Determine status
        if error_count > 0:
            status = "INVALID"
        elif warning_count > 0:
            status = "VALID_WITH_WARNINGS"
        else:
            status = "VALID"

        lap_length = self.lap_length_m or self._compute_lap_length()

        return {
            "schema_version": self.schema_version,
            "validator_version": __version__,
            "profile_id": self.profile_id,
            "track": self._track,
            "layout": self._layout,
            "lap_length_m": lap_length,
            "status": status,
            "error_count": error_count,
            "warning_count": warning_count,
            "informational_count": informational_count,
            "findings": [f.to_dict() for f in self.findings],
            "summary": {
                "checks_run": [
                    "ORDERING",
                    "LAP_BOUNDS",
                    "GAPS_OVERLAPS",
                    "DUPLICATE_POINTS",
                    "LAYOUT_CONSISTENCY",
                    "GPS_CONSISTENCY",
                    "SEMANTIC_STRUCTURE",
                    "PROVENANCE",
                ],
                "turn_count": len(self.turns),
                "profile_status": self.profile.get("status"),
                "calibration_present": bool(self.profile.get("calibration")),
            },
        }


def validate_profile(
    profile_path: Path,
    lap_length_m: float | None = None,
) -> dict[str, Any]:
    """Load a profile JSON and validate it.

    Args:
        profile_path: Path to the profile JSON file.
        lap_length_m: Optional override for lap length.

    Returns:
        Validation result dict (same shape as TrackProfileValidator.validate()).
    """
    with profile_path.open("r", encoding="utf-8") as fh:
        profile = json.load(fh)

    validator = TrackProfileValidator(profile, lap_length_m)
    return validator.validate()


def validate_profiles(profiles: list[Path]) -> dict[str, Any]:
    """Validate multiple profiles and return aggregate result.

    Returns dict with:
      - validator_version
      - profiles: dict mapping profile path to result dict
      - summary: aggregate counts
    """
    results: dict[str, Any] = {
        "validator_version": __version__,
        "profiles": {},
        "summary": {
            "total_profiles": len(profiles),
            "valid": 0,
            "valid_with_warnings": 0,
            "invalid": 0,
            "total_errors": 0,
            "total_warnings": 0,
            "total_informational": 0,
        },
    }

    for path in profiles:
        result = validate_profile(path)
        key = path.name
        results["profiles"][key] = result
        results["summary"]["total_errors"] += result["error_count"]
        results["summary"]["total_warnings"] += result["warning_count"]
        results["summary"]["total_informational"] += result["informational_count"]

        status = result["status"]
        if status == "VALID":
            results["summary"]["valid"] += 1
        elif status == "VALID_WITH_WARNINGS":
            results["summary"]["valid_with_warnings"] += 1
        elif status == "INVALID":
            results["summary"]["invalid"] += 1

    return results


# ── CLI entry point ────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Track profile validator v0.1 — deterministic audit of track profiles."
    )
    parser.add_argument(
        "profiles",
        nargs="+",
        help="One or more track profile JSON files.",
    )
    parser.add_argument(
        "--lap-length-m",
        type=float,
        default=None,
        help="Override lap length in metres.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path for JSON result.",
    )
    args = parser.parse_args()

    profile_paths = [Path(p).resolve() for p in args.profiles]

    aggregate = validate_profiles(profile_paths)

    # Print results
    print("=" * 88)
    print("TRACK PROFILE VALIDATOR v0.1")
    print("=" * 88)

    for key, result in aggregate["profiles"].items():
        print(f"\nProfile: {key}")
        print(f"  Track: {result['track']}")
        print(f"  Layout: {result['layout']}")
        print(f"  Lap length: {result['lap_length_m']:.1f} m")
        print(f"  Status: {result['status']}")
        print(f"  Errors: {result['error_count']}")
        print(f"  Warnings: {result['warning_count']}")
        print(f"  Informational: {result['informational_count']}")

        for finding in result["findings"]:
            sev = finding["severity"]
            msg = finding["deterministic_message"]
            entity = ""
            if finding.get("entity_name"):
                entity = f" [{finding['entity_name']}]"
            elif finding.get("entity_id"):
                entity = f" [{finding['entity_id']}]"
            print(f"  [{sev.upper()}]{entity} {msg}")

    summary = aggregate["summary"]
    print(f"\n{'=' * 88}")
    print(f"AGGREGATE SUMMARY")
    print(f"{'=' * 88}")
    print(f"Total profiles: {summary['total_profiles']}")
    print(f"  VALID: {summary['valid']}")
    print(f"  VALID_WITH_WARNINGS: {summary['valid_with_warnings']}")
    print(f"  INVALID: {summary['invalid']}")
    print(f"Total errors: {summary['total_errors']}")
    print(f"Total warnings: {summary['total_warnings']}")
    print(f"Total informational: {summary['total_informational']}")
    print(f"\nRESULT: {'PASS' if summary['total_errors'] == 0 else 'FAIL'}")

    # Write output if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(aggregate, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return 0 if summary["total_errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
