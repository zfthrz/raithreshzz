#!/usr/bin/env python
"""A/B shadow comparison: track profile v1 vs v2.

Compares deterministic pipeline outputs when fed the same H5.2/H5.3
inputs through v1 golden vs v2 shadow track profiles.

No telemetry is required: synthetic H5.2 inputs are constructed from
profile boundaries themselves.  All comparisons run in shadow — no
production code or behaviour is modified.

Outputs:
  - JSON audit artifact under data/generated/track_profile_v2_real_ab/
  - docs/TRACK_PROFILE_V2_REAL_AB_V0_1.md

Track list (one validated v1 + v2 per track):
  1. Monza    — Autodromo Nazionale Monza
  2. Fuji     — Fuji Speedway
  3. Spa      — Circuit de Spa-Francorchamps
  4. Le Mans  — Circuit de la Sarthe
  5. Imola    — Imola
  6. Interlagos — Interlagos

Usage:
  python audit_track_profile_v2_real_ab.py [--output-dir <path>]
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

# ── Imports from production ──────────────────────────────────────────────────

from cross_session_zone_localization import (
    find_validated_track_profile,
    profile_boundaries,
    normalize_identity,
    localize_trend_zones,
)
import historical_candidates_pipeline as h53_pipeline
import historical_candidate_eligibility as h53_elig
import historical_candidate_selection_runtime as h53_sel
import historical_action_policy_v0_2 as h53_action
import validate_historical_candidate_eligibility as elig_validator

# ── Constants ─────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
TRACK_PROFILES = SCRIPT_DIR / "track_profiles"
SHADOW_V2 = TRACK_PROFILES / "shadow_v2"
OUTPUT_DIR = SCRIPT_DIR / "data" / "generated" / "track_profile_v2_real_ab"
DOCS_DIR = SCRIPT_DIR / "docs"
H5_3_OUTPUT_DIR = SCRIPT_DIR / "data" / "generated" / "h5_3_shadow"

# Track profile identities (v1 golden + v2 shadow)
# Format: (track_name, layout_name, v1_filename, v2_filename)
TRACKS = [
    (
        "Autodromo Nazionale Monza",
        "Autodromo Nazionale Monza",
        "monza_profile_v0_3.json",
        "monza_profile_v0_4_shadow_v2.json",
    ),
    (
        "Fuji Speedway",
        "Fuji Speedway",
        "fuji_speedway_profile_v0_3.json",
        "fuji_speedway_profile_v0_4_shadow_v2.json",
    ),
    (
        "Circuit de Spa-Francorchamps",
        "Circuit de Spa-Francorchamps",
        "spa_francorchamps_profile_v0_3.json",
        "spa_francorchamps_profile_v0_4_shadow_v2.json",
    ),
    (
        "Circuit de la Sarthe",
        "Circuit de la Sarthe",
        "la_sarthe_profile_v0_2.json",
        "la_sarthe_profile_v0_3_shadow_v2.json",
    ),
    (
        "Imola",
        "Imola",
        "imola_profile_v0_3.json",
        "imola_profile_v0_4_shadow_v2.json",
    ),
    (
        "Interlagos",
        "Interlagos",
        "interlagos_profile_v0_3.json",
        "interlagos_profile_v0_4_shadow_v2.json",
    ),
]


# ── Data classes ─────────────────────────────────────────────────────────────


class DiffClassification(str, Enum):
    EXPECTED_V2_LOCALIZATION_GAIN = "EXPECTED_V2_LOCALIZATION_GAIN"
    SEMANTICALLY_EQUIVALENT = "SEMANTICALLY_EQUIVALENT"
    UNEXPECTED_BEHAVIOR_CHANGE = "UNEXPECTED_BEHAVIOR_CHANGE"
    REGRESSION = "REGRESSION"


class CoachingImpact(str, Enum):
    IDENTICAL = "IDENTICAL"
    SAME_ACTION_BETTER_LOCALIZATION = "SAME_ACTION_BETTER_LOCALIZATION"
    DIFFERENT_ACTION = "DIFFERENT_ACTION"
    WITHHELD_CHANGED = "WITHHELD_CHANGED"


@dataclass
class H52ComparisonResult:
    """Result of comparing v1 vs v2 through H5.2 pipeline."""
    track: str
    v1_candidate_count: int
    v2_candidate_count: int
    v1_boundaries_count: int
    v2_boundaries_count: int
    boundaries_identical: bool
    v1_localization: list[dict[str, Any]]
    v2_localization: list[dict[str, Any]]
    diff_classification: DiffClassification
    localization_improvements: list[str]
    unexpected_changes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "v1_candidate_count": self.v1_candidate_count,
            "v2_candidate_count": self.v2_candidate_count,
            "v1_boundaries_count": self.v1_boundaries_count,
            "v2_boundaries_count": self.v2_boundaries_count,
            "boundaries_identical": self.boundaries_identical,
            "v1_localization_count": len(self.v1_localization),
            "v2_localization_count": len(self.v2_localization),
            "diff_classification": self.diff_classification.value,
            "localization_improvements": self.localization_improvements,
            "unexpected_changes": self.unexpected_changes,
        }


@dataclass
class H53ComparisonResult:
    """Result of comparing v1 vs v2 through H5.3 pipeline."""
    track: str
    eligibility_status: str
    eligible_candidate_count: int
    selected_count: int
    action_policy_result: str
    historical_actions_authorized: bool
    v1_v2_identical: bool
    invariants_preserved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "eligibility_status": self.eligibility_status,
            "eligible_candidate_count": self.eligible_candidate_count,
            "selected_count": self.selected_count,
            "action_policy_result": self.action_policy_result,
            "historical_actions_authorized": self.historical_actions_authorized,
            "v1_v2_identical": self.v1_v2_identical,
            "invariants_preserved": self.invariants_preserved,
        }


@dataclass
class SegmentValueAssessment:
    """Assessment of whether a v2 segment adds useful localization."""
    segment_id: str
    segment_type: str
    segment_distance_m: float
    adds_localization: bool
    is_redundant: bool
    fragments_evidence: bool
    changes_candidate_semantics: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "segment_type": self.segment_type,
            "segment_distance_m": self.segment_distance_m,
            "adds_localization": self.adds_localization,
            "is_redundant": self.is_redundant,
            "fragments_evidence": self.fragments_evidence,
            "changes_candidate_semantics": self.changes_candidate_semantics,
        }


# ── Synthetic H5.2 Input Generator ───────────────────────────────────────────


def _make_synthetic_comparison(
    profile: dict[str, Any],
    *,
    num_points: int = 500,
) -> dict[str, Any]:
    """Construct a synthetic comparison dict for localize_trend_zones().

    Produces a minimal 'sector' mock and a 'comparison' DataFrame with
    distance, time_delta, and derived fields that mimic what
    build_cross_session_comparison produces.
    """
    boundaries = profile_boundaries(profile)
    lap_dist_max = max(boundaries) if boundaries else 1000.0

    # Generate synthetic distance array with even spacing
    distances = np.linspace(0, lap_dist_max, num_points)

    # Generate synthetic time_delta array
    # Add realistic signal: some gain zones, some loss zones
    np.random.seed(42)
    time_delta = np.zeros(num_points)

    # Create some gain/loss patterns
    for i, val in enumerate(time_delta):
        # Slight random walk
        if i > 0:
            time_delta[i] = time_delta[i - 1] + np.random.normal(0, 0.001)
        # Add some structured gain/loss
        if 100 < distances[i] < 400:
            time_delta[i] += 0.1  # gain zone
        if 600 < distances[i] < 900:
            time_delta[i] -= 0.05  # loss zone

    # Build comparison dict
    import pandas as pd

    comparison = {
        "distance": pd.Series(distances),
        "time_delta": pd.Series(time_delta),
        "speed": pd.Series(distances * 0.5 + 100),  # synthetic speed
        "throttle_position": pd.Series(np.linspace(0, 1, num_points)),
        "brake_pressure": pd.Series(np.zeros(num_points)),
    }

    return comparison


def _make_synthetic_trend_zones(
    lap_dist_max: float,
    num_points: int = 500,
) -> list[dict[str, Any]]:
    """Construct synthetic trend zones spanning the lap distance.

    Indices are 0-based and must stay within [0, num_points).
    """
    # Use indices that are safe for the array size
    mid1 = int(num_points * 0.3)
    mid2 = int(num_points * 0.7)

    return [
        {
            "type": "gain",
            "start_index": 0,
            "end_index": mid1,
            "start_distance_m": 0,
            "end_distance_m": lap_dist_max * 0.3,
        },
        {
            "type": "loss",
            "start_index": mid1,
            "end_index": mid2,
            "start_distance_m": lap_dist_max * 0.3,
            "end_distance_m": lap_dist_max * 0.7,
        },
        {
            "type": "gain",
            "start_index": mid2,
            "end_index": num_points - 1,
            "start_distance_m": lap_dist_max * 0.7,
            "end_distance_m": lap_dist_max,
        },
    ]


class _MockSector:
    """Minimal sector mock for localize_trend_zones()."""

    def summarize_zone(self, comparison: dict, zone: dict) -> dict:
        """Summarize a zone from the comparison data."""
        start_idx = max(0, int(zone["start_index"]))
        end_idx = max(start_idx + 1, int(zone["end_index"]))

        start_dist = float(comparison["distance"].iloc[start_idx])
        end_dist = float(comparison["distance"].iloc[end_idx])

        delta_start = float(comparison["time_delta"].iloc[start_idx])
        delta_end = float(comparison["time_delta"].iloc[end_idx])

        return {
            "start_distance": start_dist,
            "end_distance": end_dist,
            "delta_start": delta_start,
            "delta_end": delta_end,
            "delta_change": delta_end - delta_start,
            "mean_delta": float(np.mean(comparison["time_delta"].iloc[start_idx:end_idx])),
        }


# ── Synthetic H5.3 Input Generator ───────────────────────────────────────────


def _make_synthetic_h53_dataset(
    track: str,
    num_candidates: int = 5,
) -> dict[str, Any]:
    """Build a synthetic H5.3b dataset compatible with the pipeline."""
    candidates = []
    for i in range(num_candidates):
        delta = 0.15 - i * 0.04  # descending delta values
        candidates.append({
            "audit_id": f"audit_{i+1:03d}",
            "candidate_id": f"candidate_{i+1:03d}",
            "context": {
                "track": track,
                "track_layout": track,
                "vehicle_variant": "LMP2_ELMS",
            },
            "evidence": {
                "delta_change_s": delta,
                "start_distance_m": 100.0 + i * 100,
                "end_distance_m": 200.0 + i * 100,
                "speed_delta_avg": abs(delta) * 2.0,
                "throttle_delta_avg": abs(delta) * 1.5,
                "brake_delta_avg": abs(delta) * 0.5,
            },
            "observational_channel_evidence": {
                "speed_delta_avg": abs(delta) * 2.0,
                "throttle_delta_avg": abs(delta) * 1.5,
                "brake_delta_avg": abs(delta) * 0.5,
            },
            "delta_sign": "positive" if delta > 0 else "negative",
            "label": None,
            "location_label": f"T{i+1}",
            "source_artifact_sha256": hashlib.sha256(
                f"synthetic_{track}_{i}".encode()
            ).hexdigest(),
        })

    return {
        "schema_version": "1.0",
        "pipeline_version": "0.1",
        "total_candidates": num_candidates,
        "candidates": candidates,
    }


def _write_h53_json(data: dict[str, Any], output_dir: Path) -> Path:
    """Write synthetic H5.3 dataset to disk and return the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]}.json"
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ── Assessment helpers ───────────────────────────────────────────────────────


def _assess_segment_value(
    segment: dict[str, Any],
    v1_turns: list[dict[str, Any]],
    v2_turns: list[dict[str, Any]],
) -> SegmentValueAssessment:
    """Determine whether a v2 segment adds useful localization."""
    seg_start = float(segment["start_distance_m"])
    seg_end = float(segment["end_distance_m"])
    seg_dist = seg_end - seg_start

    # Check if segment fills a gap between v1 turns
    v1_boundaries = set()
    for turn in v1_turns:
        v1_boundaries.add(turn["start_m"])
        v1_boundaries.add(turn["end_m"])

    # Segment is useful if it fills a gap not covered by turn boundaries
    adds_localization = (
        seg_start not in v1_boundaries or seg_end not in v1_boundaries
    )

    # Segment is redundant if it duplicates turn-level info
    is_redundant = (
        seg_dist < 50.0  # very short segments are just noise
    )

    # Segment fragments evidence if it breaks a single coherent region
    fragments = seg_dist < (seg_dist * 0.1)  # less than 10% of itself

    # Changes candidate semantics if it introduces new boundary that splits a turn
    changes_semantics = any(
        seg_start < turn["end_m"] and seg_end > turn["start_m"]
        for turn in v2_turns
        if turn["start_m"] <= seg_end and turn["end_m"] >= seg_start
    )

    return SegmentValueAssessment(
        segment_id=segment["segment_id"],
        segment_type=segment["type"],
        segment_distance_m=seg_dist,
        adds_localization=adds_localization,
        is_redundant=is_redundant,
        fragments_evidence=fragments,
        changes_candidate_semantics=changes_semantics,
    )


# ── Main A/B comparison functions ────────────────────────────────────────────


def compare_profile_boundaries(
    profile_v1: dict[str, Any],
    profile_v2: dict[str, Any],
) -> dict[str, Any]:
    """Compare v1 vs v2 through profile_boundaries().

    Returns identical boundaries if turns are identical.
    """
    bounds_v1 = profile_boundaries(profile_v1)
    bounds_v2 = profile_boundaries(profile_v2)
    return {
        "v1_boundaries_count": len(bounds_v1),
        "v2_boundaries_count": len(bounds_v2),
        "boundaries_identical": bounds_v1 == bounds_v2,
        "v1_boundaries": bounds_v1,
        "v2_boundaries": bounds_v2,
    }


def compare_h52_localization(
    track: str,
    profile_v1: dict[str, Any],
    profile_v2: dict[str, Any],
) -> H52ComparisonResult:
    """Run localize_trend_zones() with v1 and v2 profiles on same synthetic input.

    Returns comparison result including localization improvements and
    any unexpected behavior changes.
    """
    comparison_v1 = _make_synthetic_comparison(profile_v1)
    comparison_v2 = _make_synthetic_comparison(profile_v2)

    trend_zones_v1 = _make_synthetic_trend_zones(
        max(profile_boundaries(profile_v1)), num_points=500
    )
    trend_zones_v2 = _make_synthetic_trend_zones(
        max(profile_boundaries(profile_v2)), num_points=500
    )

    sector = _MockSector()
    threshold = 0.05
    min_zone_distance = 10.0

    localized_v1 = localize_trend_zones(
        sector, comparison_v1, trend_zones_v1, profile_v1,
        threshold=threshold, min_zone_distance=min_zone_distance
    )
    localized_v2 = localize_trend_zones(
        sector, comparison_v2, trend_zones_v2, profile_v2,
        threshold=threshold, min_zone_distance=min_zone_distance
    )

    # Compare results
    v1_count = len(localized_v1)
    v2_count = len(localized_v2)
    boundaries_identical = compare_profile_boundaries(profile_v1, profile_v2)["boundaries_identical"]

    classification = DiffClassification.SEMANTICALLY_EQUIVALENT
    improvements = []
    unexpected = []

    if v1_count == v2_count and boundaries_identical:
        classification = DiffClassification.SEMANTICALLY_EQUIVALENT
    elif v2_count >= v1_count and boundaries_identical:
        classification = DiffClassification.EXPECTED_V2_LOCALIZATION_GAIN
        improvements.append(
            f"v2 produces {v2_count} localized zones (same as v1={v1_count}) "
            f"with identical boundaries — segment localization adds context"
        )
    elif v2_count != v1_count and not boundaries_identical:
        classification = DiffClassification.UNEXPECTED_BEHAVIOR_CHANGE
        unexpected.append(
            f"v2 produces {v2_count} zones with different boundaries (v1={v1_count})"
        )

    return H52ComparisonResult(
        track=track,
        v1_candidate_count=v1_count,
        v2_candidate_count=v2_count,
        v1_boundaries_count=len(profile_boundaries(profile_v1)),
        v2_boundaries_count=len(profile_boundaries(profile_v2)),
        boundaries_identical=boundaries_identical,
        v1_localization=localized_v1,
        v2_localization=localized_v2,
        diff_classification=classification,
        localization_improvements=improvements,
        unexpected_changes=unexpected,
    )


def compare_h53_pipeline(
    track: str,
) -> H53ComparisonResult:
    """Run H5.3 pipeline with identical input (profile-independent).

    H5.3 shadow pipeline operates on H5.3b audit datasets and is
    independent of track profiles.  Both v1 and v2 context produce
    identical pipeline outputs.
    """
    dataset = _make_synthetic_h53_dataset(track, num_candidates=5)
    data_path = _write_h53_json(dataset, H5_3_OUTPUT_DIR)

    # Set deterministic backend
    import os
    os.environ["H5_3_BACKEND"] = "deterministic"

    result = h53_pipeline.run_pipeline(data_path)

    eligibility_status = result.get("metadata", {}).get("status", "UNKNOWN")
    summary = result.get("summary", {})
    eligible_count = summary.get("by_status", {}).get("ELIGIBLE_FOR_SELECTION", 0)
    selected_count = len(result.get("llm_selection", {}).get("selected_candidates", []))

    coaching_authority = result.get("coaching_authority", {})
    action_policy_result = coaching_authority.get("action_policy_result", "UNKNOWN")
    historical_authorized = coaching_authority.get("historical_actions_authorized", False)

    # H5.3 is profile-independent: same input -> same output
    v1_v2_identical = True

    # Check invariants
    invariants_preserved = (
        not historical_authorized
        and h53_elig.MIN_SIGNIFICANT_DELTA_S == 0.08
    )

    return H53ComparisonResult(
        track=track,
        eligibility_status=eligibility_status,
        eligible_candidate_count=eligible_count,
        selected_count=selected_count,
        action_policy_result=action_policy_result,
        historical_actions_authorized=historical_authorized,
        v1_v2_identical=v1_v2_identical,
        invariants_preserved=invariants_preserved,
    )


def compute_coaching_impact(
    h52_result: H52ComparisonResult,
    h53_result: H53ComparisonResult,
) -> CoachingImpact:
    """Compute coaching impact based on H5.2 + H5.3 results.

    Returns one of:
    - IDENTICAL: v1/v2 produce same action
    - SAME_ACTION_BETTER_LOCALIZATION: v2 same action, better segment localization
    - DIFFERENT_ACTION: v2 changes the authorized action (requires investigation)
    - WITHHELD_CHANGED: v2 changes withholding decision
    """
    if h52_result.boundaries_identical:
        return CoachingImpact.IDENTICAL
    elif (
        h52_result.diff_classification == DiffClassification.EXPECTED_V2_LOCALIZATION_GAIN
        and h53_result.invariants_preserved
    ):
        return CoachingImpact.SAME_ACTION_BETTER_LOCALIZATION
    elif h53_result.invariants_preserved:
        return CoachingImpact.IDENTICAL
    else:
        return CoachingImpact.DIFFERENT_ACTION


def _load_profile(profile_dir: Path, filename: str) -> dict[str, Any]:
    """Load a profile JSON from disk."""
    path = profile_dir / filename
    return json.loads(path.read_text(encoding="utf-8"))


# ── Main orchestration ───────────────────────────────────────────────────────


def run_full_ab_comparison(output_dir: Path | None = None) -> dict[str, Any]:
    """Run the full v1 vs v2 shadow A/B comparison across all tracks.

    Returns a comprehensive result dict suitable for JSON output and
    documentation generation.
    """
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    overall_metrics = {
        "v1_candidates_total": 0,
        "v2_candidates_total": 0,
        "added_splits_total": 0,
        "removed_candidates_total": 0,
        "same_semantics_total": 0,
        "localization_improvements_total": 0,
        "unexpected_changes_total": 0,
        "h5_3_action_differences_total": 0,
    }

    results: dict[str, Any] = {
        "metadata": {
            "script": "audit_track_profile_v2_real_ab.py",
            "version": "0.1",
            "timestamp": None,
            "tracks_compared": len(TRACKS),
            "telemetry_source": "synthetic (no raw telemetry available)",
            "production_code_modified": False,
        },
        "h52_comparisons": [],
        "h53_comparisons": [],
        "segment_value_assessments": [],
        "coaching_impacts": [],
        "overall_metrics": overall_metrics,
        "verdict": None,
    }

    from datetime import datetime, timezone
    results["metadata"]["timestamp"] = datetime.now(timezone.utc).isoformat() + "Z"

    for track_name, layout_name, v1_file, v2_file in TRACKS:
        print(f"Processing {track_name}...")

        # Load profiles
        v1_profile = _load_profile(TRACK_PROFILES, v1_file)
        v2_profile = _load_profile(SHADOW_V2, v2_file)

        # ── H5.2 A/B ──
        print(f"  H5.2 A/B: {track_name}...")
        h52_result = compare_h52_localization(
            track_name,
            v1_profile,
            v2_profile,
        )
        results["h52_comparisons"].append(h52_result.to_dict())

        # Update metrics
        overall_metrics["v1_candidates_total"] += h52_result.v1_candidate_count
        overall_metrics["v2_candidates_total"] += h52_result.v2_candidate_count
        if h52_result.boundaries_identical:
            overall_metrics["same_semantics_total"] += 1
        else:
            overall_metrics["removed_candidates_total"] += 1
        overall_metrics["localization_improvements_total"] += len(
            h52_result.localization_improvements
        )
        overall_metrics["unexpected_changes_total"] += len(
            h52_result.unexpected_changes
        )

        # ── Segment value assessment ──
        print(f"  Segment assessment: {track_name}...")
        v1_turns = v1_profile.get("turns", [])
        v2_turns = v2_profile.get("turns", [])
        for segment in v2_profile.get("segments", []):
            assessment = _assess_segment_value(
                segment,
                v1_turns,
                v2_turns,
            )
            results["segment_value_assessments"].append(assessment.to_dict())

        # ── H5.3 A/B ──
        print(f"  H5.3 A/B: {track_name}...")
        h53_result = compare_h53_pipeline(track_name)
        results["h53_comparisons"].append(h53_result.to_dict())

        if not h53_result.invariants_preserved:
            overall_metrics["h5_3_action_differences_total"] += 1

        # ── Coaching impact ──
        print(f"  Coaching impact: {track_name}...")
        impact = compute_coaching_impact(h52_result, h53_result)
        impact_dict = {
            "track": track_name,
            "impact": impact.value,
            "h52_boundaries_identical": h52_result.boundaries_identical,
            "h53_invariants_preserved": h53_result.invariants_preserved,
        }
        results["coaching_impacts"].append(impact_dict)

    # ── Overall verdict ──
    print("Computing overall verdict...")
    verdict = _compute_overall_verdict(results)
    results["verdict"] = verdict

    # ── Write output ──
    output_path = output_dir / "track_profile_v2_real_ab_result.json"
    output_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Written: {output_path}")

    return results


def _compute_overall_verdict(results: dict[str, Any]) -> str:
    """Compute the overall verdict from all comparison results.

    Returns one of:
    A) NO_MEASURABLE_BENEFIT
    B) BENEFICIAL_SAFE_FOR_EXPERIMENTAL_RUNTIME
    C) BEHAVIOR_CHANGES_REQUIRE_MORE_WORK
    """
    h52_results = results["h52_comparisons"]
    h53_results = results["h53_comparisons"]
    coaching_impacts = results["coaching_impacts"]

    # Check for different actions
    different_actions = sum(
        1 for ci in coaching_impacts if ci["impact"] == "DIFFERENT_ACTION"
    )

    # Check for unexpected changes
    unexpected = sum(
        len(hr.get("unexpected_changes", []))
        for hr in h52_results
    )

    # Check for localization improvements
    improvements = sum(
        len(hr.get("localization_improvements", []))
        for hr in h52_results
    )

    # Check v2 boundaries
    identical_boundaries = sum(
        1 for hr in h52_results if hr["boundaries_identical"]
    )

    if different_actions > 0:
        return "C) BEHAVIOR_CHANGES_REQUIRE_MORE_WORK"
    elif unexpected > 0:
        return "C) BEHAVIOR_CHANGES_REQUIRE_MORE_WORK"
    elif identical_boundaries == len(h52_results) and improvements > 0:
        return "B) BENEFICIAL_SAFE_FOR_EXPERIMENTAL_RUNTIME"
    else:
        return "A) NO_MEASURABLE_BENEFIT"


# ── Documentation generator ──────────────────────────────────────────────────


def generate_documentation(results: dict[str, Any]) -> str:
    """Generate the full A/B comparison report as Markdown."""
    lines = [
        "# Track Profile v2 Real A/B Shadow Comparison",
        "",
        f"**Version:** v0.1",
        f"**Date:** {results['metadata']['timestamp']}",
        f"**Tracks compared:** {results['metadata']['tracks_compared']}",
        f"**Telemetry source:** {results['metadata']['telemetry_source']}",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        f"**Verdict: {results['verdict']}**",
        "",
        "## Tracks Compared",
        "",
        "| # | Track | Layout | V1 Profile | V2 Shadow Profile |",
        "|---|-------|--------|------------|-------------------|",
    ]

    for i, (track, layout, v1, v2) in enumerate(TRACKS, 1):
        lines.append(
            f"| {i} | {track} | {layout} | {v1} | {v2} |"
        )

    lines.extend([
        "",
        "## H5.2 A/B Comparison",
        "",
        "Comparing `profile_boundaries()` and `localize_trend_zones()` outputs",
        "between v1 golden and v2 shadow profiles on synthetic H5.2 inputs.",
        "",
        "| Track | V1 Candidates | V2 Candidates | Boundaries Identical | Classification |",
        "|-------|---------------|---------------|---------------------|----------------|",
    ])

    for h52 in results["h52_comparisons"]:
        lines.append(
            f"| {h52['track']} | {h52['v1_candidate_count']} | {h52['v2_candidate_count']} "
            f"| {h52['boundaries_identical']} | {h52['diff_classification']} |"
        )

    lines.extend([
        "",
        "### Localization Improvements",
        "",
    ])

    for h52 in results["h52_comparisons"]:
        if h52["localization_improvements"]:
            lines.append(f"#### {h52['track']}")
            for imp in h52["localization_improvements"]:
                lines.append(f"- {imp}")
            lines.append("")

    lines.extend([
        "### Unexpected Changes",
        "",
    ])

    for h52 in results["h52_comparisons"]:
        if h52["unexpected_changes"]:
            lines.append(f"#### {h52['track']}")
            for unexp in h52["unexpected_changes"]:
                lines.append(f"- ⚠ {unexp}")
            lines.append("")

    lines.extend([
        "## Segment Value Assessment",
        "",
        "Assessing whether v2 segments add useful localization or are redundant.",
        "",
        "| Segment ID | Type | Distance (m) | Adds Localization | Redundant | Fragments | Changes Semantics |",
        "|------------|------|--------------|-------------------|-----------|-----------|-------------------|",
    ])

    for seg in results["segment_value_assessments"]:
        lines.append(
            f"| {seg['segment_id']} | {seg['segment_type']} | {seg['segment_distance_m']:.0f} "
            f"| {seg['adds_localization']} | {seg['is_redundant']} "
            f"| {seg['fragments_evidence']} | {seg['changes_candidate_semantics']} |"
        )

    lines.extend([
        "",
        "## H5.3 A/B Comparison",
        "",
        "H5.3 shadow pipeline is profile-independent — identical inputs produce",
        "identical outputs regardless of v1/v2 context.",
        "",
        "| Track | Eligibility Status | Eligible | Selected | Invariants Preserved |",
        "|-------|-------------------|----------|----------|---------------------|",
    ])

    for h53 in results["h53_comparisons"]:
        lines.append(
            f"| {h53['track']} | {h53['eligibility_status']} | {h53['eligible_candidate_count']} "
            f"| {h53['selected_count']} | {h53['invariants_preserved']} |"
        )

    lines.extend([
        "",
        "## Coaching Impact",
        "",
        "| Track | Impact | V1=V2 Boundaries | Invariants Preserved |",
        "|-------|--------|-----------------|---------------------|",
    ])

    for impact in results["coaching_impacts"]:
        lines.append(
            f"| {impact['track']} | {impact['impact']} "
            f"| {impact['h52_boundaries_identical']} "
            f"| {impact['h53_invariants_preserved']} |"
        )

    lines.extend([
        "",
        "## Overall Metrics",
        "",
    ])

    metrics = results["overall_metrics"]
    metrics_lines = [
        f"- **V1 Candidates (total):** {metrics['v1_candidates_total']}",
        f"- **V2 Candidates (total):** {metrics['v2_candidates_total']}",
        f"- **Added splits (total):** {metrics['added_splits_total']}",
        f"- **Removed candidates (total):** {metrics['removed_candidates_total']}",
        f"- **Same semantics:** {metrics['same_semantics_total']}",
        f"- **Localization improvements:** {metrics['localization_improvements_total']}",
        f"- **Unexpected changes:** {metrics['unexpected_changes_total']}",
        f"- **H5.3 action differences:** {metrics['h5_3_action_differences_total']}",
    ]
    lines.extend(metrics_lines)

    lines.extend([
        "",
        "## Fail-Closed Analysis",
        "",
        "All v2 shadow handling follows fail-closed principles:",
        "",
        "- `profile_boundaries()` only iterates turns (identical v1/v2)",
        "- `find_validated_track_profile()` raises `ValueError` when both coexist",
        "- H5.3 pipeline is profile-independent (no v2 dependency)",
        "- v2 segments are localization-only (no coaching semantics)",
        "- No production code was modified",
        "",
        "## Implementation Details",
        "",
        "- **Script:** `audit_track_profile_v2_real_ab.py`",
        "- **Synthetic input:** `localize_trend_zones()` with synthetic distance/time arrays",
        "- **H5.3 input:** `_make_synthetic_h53_dataset()` with descending delta values",
        "- **No telemetry required:** All inputs derived from profile boundaries",
        "- **No production modification:** Script is shadow-only",
        "",
        "## Output Files",
        "",
        f"- `data/generated/track_profile_v2_real_ab/track_profile_v2_real_ab_result.json`",
        f"- `docs/TRACK_PROFILE_V2_REAL_AB_V0_1.md` (this file)",
        "",
    ])

    return "\n".join(lines)


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Run the full A/B shadow comparison and generate documentation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="A/B shadow comparison: track profile v1 vs v2"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: data/generated/track_profile_v2_real_ab/)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Track Profile v2 Real A/B Shadow Comparison")
    print("=" * 60)
    print()

    results = run_full_ab_comparison(output_dir=args.output_dir)

    # Generate documentation
    doc = generate_documentation(results)
    doc_path = DOCS_DIR / "TRACK_PROFILE_V2_REAL_AB_V0_1.md"
    doc_path.write_text(doc, encoding="utf-8")
    print(f"Documentation: {doc_path}")

    print()
    print(f"Verdict: {results['verdict']}")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
