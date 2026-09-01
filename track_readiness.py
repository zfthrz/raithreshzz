from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from cross_session_zone_localization import VALID_PROFILE_STATUSES, normalize_identity
from h3_import_readiness import H3Context, discover_h3_import_readiness
from race_engineer_ui_model import load_calibration_summary
from track_baseline_shadow import resolve_track_baseline
from track_match_baseline_promotion import discover_promotion_for_context


TRACK_READINESS_VERSION = "0.9"
READY_STAGE_STATUSES = {"RUN", "REUSED"}
PROFILE_VERSION_RE = re.compile(r"v(\d+)[._](\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class ContextKey:
    track: str
    track_layout: str
    vehicle_variant: str


@dataclass(frozen=True)
class ProfileRecord:
    track: str
    layout: str
    status: str
    profile_id: str
    path: Path
    version: tuple[int, int] | None
    valid_turns: bool


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root is not an object")
    return payload


def _profile_version(payload: dict[str, Any], path: Path) -> tuple[int, int] | None:
    candidates = [str(payload.get("profile_id") or ""), path.stem]
    versions: list[tuple[int, int]] = []
    for candidate in candidates:
        for major, minor in PROFILE_VERSION_RE.findall(candidate):
            versions.append((int(major), int(minor)))
    return max(versions) if versions else None


def discover_profiles(profile_dir: Path) -> tuple[list[ProfileRecord], list[str]]:
    records: list[ProfileRecord] = []
    errors: list[str] = []
    root = Path(profile_dir)
    if not root.is_dir():
        return records, [f"Track profile directory missing: {root.resolve()}"]

    for path in sorted(root.glob("*.json")):
        try:
            payload = _json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
            continue

        track = str(payload.get("track") or "").strip()
        layout = str(payload.get("layout") or "").strip()
        if not track or not layout:
            errors.append(f"{path}: missing track/layout")
            continue

        turns = payload.get("turns")
        records.append(
            ProfileRecord(
                track=track,
                layout=layout,
                status=str(payload.get("status") or "UNKNOWN"),
                profile_id=str(payload.get("profile_id") or path.stem),
                path=path.resolve(),
                version=_profile_version(payload, path),
                valid_turns=isinstance(turns, list) and bool(turns),
            )
        )
    return records, errors


def _best_profile(records: Iterable[ProfileRecord]) -> ProfileRecord | None:
    items = list(records)
    if not items:
        return None
    validated = [
        item for item in items if item.status in VALID_PROFILE_STATUSES and item.valid_turns
    ]
    pool = validated or items
    return max(
        pool,
        key=lambda item: (
            item.version is not None,
            item.version or (-1, -1),
            item.status in VALID_PROFILE_STATUSES,
            item.valid_turns,
            item.path.name.casefold(),
        ),
    )


def _profile_state(record: ProfileRecord | None) -> str:
    if record is None:
        return "MISSING"
    if record.status in VALID_PROFILE_STATUSES and record.valid_turns:
        return "VALIDATED"
    if record.status == "VALIDATED_SINGLE_SESSION" and record.valid_turns:
        return "PROVISIONAL_SINGLE_SESSION"
    if not record.valid_turns:
        return "INVALID"
    return "PRESENT_UNVALIDATED"


def _validated_profile_layout_hints(
    profiles: list[ProfileRecord],
) -> dict[str, str]:
    """Resolve track -> layout only when validated profiles prove one unique layout."""
    layouts_by_track: dict[str, set[str]] = defaultdict(set)
    display_by_normalized: dict[tuple[str, str], str] = {}

    for profile in profiles:
        if profile.status not in VALID_PROFILE_STATUSES or not profile.valid_turns:
            continue
        track_key = normalize_identity(profile.track)
        layout_key = normalize_identity(profile.layout)
        layouts_by_track[track_key].add(layout_key)
        display_by_normalized[(track_key, layout_key)] = profile.layout

    hints: dict[str, str] = {}
    for track_key, layout_keys in layouts_by_track.items():
        if len(layout_keys) != 1:
            continue
        layout_key = next(iter(layout_keys))
        hints[track_key] = display_by_normalized[(track_key, layout_key)]
    return hints


def _analysis_path_from_state(state: dict[str, Any], state_path: Path) -> Path | None:
    analyze = _dict(_dict(state.get("stages")).get("analyze"))
    value = analyze.get("output")
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute():
        path = (state_path.parent / path).resolve()
    return path if path.is_file() else None


def _stage_status(state: dict[str, Any], stage_name: str) -> str:
    summary = _dict(state.get("last_summary"))
    stage = _dict(_dict(state.get("stages")).get(stage_name))
    return str(summary.get(stage_name) or stage.get("status") or "UNKNOWN")


def discover_runtime_contexts(
    runs_root: Path,
    *,
    validated_profile_layout_hints: dict[str, str] | None = None,
) -> tuple[
    dict[ContextKey, dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    contexts: dict[ContextKey, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    errors: list[str] = []
    root = Path(runs_root)
    hints = validated_profile_layout_hints or {}

    if not root.is_dir():
        return contexts, unresolved, []

    for state_path in root.rglob("state.json"):
        try:
            state = _json(state_path)
            analysis_path = _analysis_path_from_state(state, state_path)
            if analysis_path is None:
                continue

            analysis = _json(analysis_path)
            metadata = _dict(analysis.get("metadata"))
            identity = _dict(metadata.get("vehicle_identity"))
            track = str(metadata.get("track") or "").strip()
            layout = str(
                metadata.get("lmu_track_layout")
                or metadata.get("track_layout")
                or ""
            ).strip()
            variant = str(
                identity.get("variant") or metadata.get("vehicle_variant") or ""
            ).strip()

            if not track or not variant:
                continue

            layout_resolution = "runtime_metadata"
            if not layout:
                layout = hints.get(normalize_identity(track), "")
                if layout:
                    layout_resolution = "validated_track_profile"

            if not layout:
                unresolved.append(
                    {
                        "track": track,
                        "vehicle_variant": variant,
                        "reason": "MISSING_TRACK_LAYOUT",
                        "session_key": state_path.parent.name,
                        "state_path": str(state_path.resolve()),
                        "database": state.get("database"),
                    }
                )
                continue

            key = ContextKey(track, layout, variant)
            entry = contexts.setdefault(
                key,
                {
                    "sessions": 0,
                    "layout_resolution_counts": defaultdict(int),
                    "h4_reference_available": False,
                    "historical_evidence_available": False,
                },
            )
            entry["sessions"] += 1
            entry["layout_resolution_counts"][layout_resolution] += 1

            stages = _dict(state.get("stages"))
            h4 = _dict(stages.get("h4"))
            if _stage_status(state, "h4") in READY_STAGE_STATUSES and h4.get("output"):
                entry["h4_reference_available"] = True

            for stage_name, raw_stage in stages.items():
                stage = _dict(raw_stage)
                status = _stage_status(state, str(stage_name))
                output = str(stage.get("output") or "")
                if status not in READY_STAGE_STATUSES:
                    continue
                if (
                    "historical_telemetry_evidence" in str(stage_name).casefold()
                    or "historical_telemetry_evidence" in output.casefold()
                ):
                    entry["historical_evidence_available"] = True

        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{state_path}: {exc}")

    # Convert defaultdicts so output remains JSON-ready.
    for entry in contexts.values():
        entry["layout_resolution_counts"] = dict(
            sorted(entry["layout_resolution_counts"].items())
        )

    return contexts, unresolved, errors


def _historical_status(runtime: dict[str, Any] | None) -> str:
    if not runtime:
        return "NO_REFERENCE"
    if runtime.get("historical_evidence_available"):
        return "EVIDENCE_AVAILABLE"
    if runtime.get("h4_reference_available"):
        return "REFERENCE_AVAILABLE"
    return "NO_REFERENCE"



def _baseline_resolution(
    *,
    track: str,
    track_layout: str,
    vehicle_variant: str,
) -> dict[str, Any]:
    return resolve_track_baseline(
        track=track,
        track_layout=track_layout,
        vehicle_variant=vehicle_variant,
    )


def _derive_status(
    *,
    profile_status: str,
    sessions: int,
    calibration: dict[str, Any] | None,
    baseline: dict[str, Any],
    promotion: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if profile_status == "PROVISIONAL_SINGLE_SESSION":
        return "NEEDS_INDEPENDENT_PROFILE_SESSION", {
            "code": "RECORD_INDEPENDENT_PROFILE_SESSION",
            "description": (
                "Record an independent session to validate and promote the "
                "existing single-session track profile"
            ),
        }
    if profile_status != "VALIDATED":
        return "NEEDS_PROFILE", {
            "code": "CREATE_OR_VALIDATE_TRACK_PROFILE",
            "description": "Create or validate the track profile",
        }

    if sessions <= 0:
        return "NEEDS_SESSIONS", {
            "code": "RECORD_MORE_SESSIONS",
            "description": "Record at least one analyzed session for this context",
        }

    baseline_status = str(baseline.get("status") or "NO_TRACK_BASELINE")
    promotion_status = str(promotion.get("status") or "")
    if (
        baseline_status == "TRACK_MATCH_BASELINE_SHADOW"
        and promotion_status == "COVERED_BY_TRACK_MATCH_BASELINE"
    ):
        return "COVERED_BY_TRACK_MATCH_BASELINE", {
            "code": "NONE_MATCH_ONLY",
            "description": (
                "Inherited MATCH core passed promotion policy; REJECT remains "
                "variant-specific and fail-closed"
            ),
            "source_variants": list(promotion.get("source_variants") or []),
        }

    if baseline_status == "TRACK_MATCH_BASELINE_SHADOW":
        return "TRACK_MATCH_BASELINE_SHADOW", {
            "code": "COLLECT_MATCH_SHADOW_EVIDENCE",
            "description": (
                "Collect MATCH-core evidence against the track/layout baseline; "
                "REJECT remains variant-specific and fail-closed"
            ),
            "source_variants": list(
                (baseline.get("match") or {}).get("source_variants") or []
            ),
        }

    if baseline_status == "TRACK_MATCH_BASELINE_CONFLICT":
        return "MATCH_BASELINE_CONFLICT", {
            "code": "REVIEW_MATCH_BASELINE_CONFLICT",
            "description": (
                "Sibling calibrated variants disagree on MATCH-core thresholds; "
                "review before inheriting a MATCH baseline"
            ),
            "source_variants": list(baseline.get("source_variants") or []),
        }

    if calibration is None:
        return "NEEDS_CALIBRATION_QUEUE", {
            "code": "GENERATE_CALIBRATION_QUEUE",
            "description": "Generate the H2 calibration review queue",
        }

    queue_pairs = int(calibration.get("queue_pairs") or 0)
    labeled_pairs = int(calibration.get("labeled_pairs") or 0)
    matcher_status = str(calibration.get("matcher_status") or "NO_MATCHER_STATUS")
    evaluation_status = str(calibration.get("evaluation_status") or "NO_EVALUATION")
    evaluation_pairs = int(calibration.get("evaluation_pairs") or 0)

    if queue_pairs <= 0 and "CALIBRATED" not in matcher_status:
        return "NEEDS_CALIBRATION_QUEUE", {
            "code": "GENERATE_CALIBRATION_QUEUE",
            "description": "Generate the H2 calibration review queue",
        }

    if queue_pairs > labeled_pairs:
        return "NEEDS_LABELS", {
            "code": "LABEL_CALIBRATION_QUEUE",
            "description": "Complete the human calibration labels",
            "current": labeled_pairs,
            "required": queue_pairs,
        }

    if (
        "CANDIDATE_CALIBRATED" in matcher_status
        or "CANDIDATE_CALIBRATED" in evaluation_status
    ):
        return "CANDIDATE_CALIBRATED", {
            "code": "REVIEW_SHADOW_METRICS",
            "description": "Review shadow metrics before any manual promotion",
        }

    if "CALIBRATED" in matcher_status:
        return "CURRENT_REQUIREMENTS_SATISFIED", {
            "code": "NONE",
            "description": "Current deterministic readiness requirements are satisfied",
        }

    if queue_pairs > 0 and labeled_pairs >= queue_pairs:
        return "NEEDS_EVALUATION", {
            "code": (
                "COLLECT_EVALUATION_EVIDENCE"
                if evaluation_pairs <= 0
                else "REVIEW_SHADOW_METRICS"
            ),
            "description": (
                "Collect independent H2 evaluation evidence"
                if evaluation_pairs <= 0
                else "Review existing H2 evaluation and shadow metrics"
            ),
        }

    return "UNKNOWN", {
        "code": "UNKNOWN",
        "description": "Readiness cannot be derived safely from current artifacts",
    }


def _identity_warnings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    by_track_variant: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        by_track_variant[
            (normalize_identity(row["track"]), normalize_identity(row["vehicle_variant"]))
        ].append(row)

    for group in by_track_variant.values():
        layouts = {normalize_identity(row["track_layout"]) for row in group}
        if len(layouts) <= 1:
            continue
        warnings.append(
            {
                "code": "MULTIPLE_LAYOUTS_FOR_TRACK_VARIANT",
                "track": group[0]["track"],
                "vehicle_variant": group[0]["vehicle_variant"],
                "layouts": sorted({row["track_layout"] for row in group}),
                "message": (
                    "Same track + vehicle_variant was discovered under multiple hard "
                    "track layouts; contexts were intentionally kept separate."
                ),
            }
        )
    return warnings


def _build_track_summary(
    *,
    rows: list[dict[str, Any]],
    profiles: list[ProfileRecord],
    unresolved_sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_profiles: dict[str, list[ProfileRecord]] = defaultdict(list)
    grouped_unresolved: dict[str, list[dict[str, Any]]] = defaultdict(list)
    display_names: dict[str, str] = {}

    for row in rows:
        key = normalize_identity(row["track"])
        grouped_rows[key].append(row)
        display_names.setdefault(key, row["track"])

    for profile in profiles:
        key = normalize_identity(profile.track)
        grouped_profiles[key].append(profile)
        display_names.setdefault(key, profile.track)

    for item in unresolved_sessions:
        key = normalize_identity(item["track"])
        grouped_unresolved[key].append(item)
        display_names.setdefault(key, item["track"])

    result: list[dict[str, Any]] = []

    for key in sorted(display_names, key=lambda value: display_names[value].casefold()):
        context_rows = sorted(
            grouped_rows.get(key, []),
            key=lambda row: (
                row["vehicle_variant"].casefold(),
                row["track_layout"].casefold(),
            ),
        )
        track_profiles = grouped_profiles.get(key, [])
        profile_states = [_profile_state(record) for record in track_profiles]

        if "VALIDATED" in profile_states:
            track_profile_status = "VALIDATED"
        elif "PROVISIONAL_SINGLE_SESSION" in profile_states:
            track_profile_status = "PROVISIONAL_SINGLE_SESSION"
        elif "PRESENT_UNVALIDATED" in profile_states:
            track_profile_status = "PRESENT_UNVALIDATED"
        elif "INVALID" in profile_states:
            track_profile_status = "INVALID"
        else:
            track_profile_status = "MISSING"

        unresolved = grouped_unresolved.get(key, [])
        unresolved_reasons: dict[str, int] = defaultdict(int)
        for item in unresolved:
            unresolved_reasons[str(item["reason"])] += 1

        pending_contexts = sum(
            1
            for row in context_rows
            if row["overall_status"] not in {
                "CURRENT_REQUIREMENTS_SATISFIED",
                "COVERED_BY_TRACK_MATCH_BASELINE",
            }
        )
        satisfied_contexts = sum(
            1
            for row in context_rows
            if row["overall_status"] in {
                "CURRENT_REQUIREMENTS_SATISFIED",
                "COVERED_BY_TRACK_MATCH_BASELINE",
            }
        )

        result.append(
            {
                "track": display_names[key],
                "profile_status": track_profile_status,
                "context_count": len(context_rows),
                "pending_contexts": pending_contexts,
                "satisfied_contexts": satisfied_contexts,
                "unresolved_sessions": len(unresolved),
                "unresolved_reasons": dict(sorted(unresolved_reasons.items())),
                "contexts": context_rows,
            }
        )

    return result


def build_track_readiness(
    *,
    project_root: Path | None = None,
    profile_dir: Path | None = None,
    batches_root: Path | None = None,
    runs_root: Path | None = None,
    history_db: Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root or Path(__file__).resolve().parent)
    profile_dir = Path(profile_dir or root / "track_profiles")
    batches_root = Path(batches_root or root / "calibration_batches")
    runs_root = Path(runs_root or root / "data" / "generated" / "runs")
    history_db = Path(history_db or root / "data" / "local" / "race_engineer_history.duckdb")

    profiles, profile_errors = discover_profiles(profile_dir)
    layout_hints = _validated_profile_layout_hints(profiles)

    runtime_contexts, unresolved_sessions, runtime_errors = discover_runtime_contexts(
        runs_root,
        validated_profile_layout_hints=layout_hints,
    )

    calibration_summary = load_calibration_summary(batches_root)
    calibration_rows = calibration_summary.get("rows") or []
    h3_by_context = discover_h3_import_readiness(
        batches_root=batches_root,
        history_db=history_db,
    )

    calibration_by_key: dict[ContextKey, dict[str, Any]] = {}
    for row in calibration_rows:
        if not isinstance(row, dict):
            continue
        key = ContextKey(
            str(row.get("track") or ""),
            str(row.get("track_layout") or ""),
            str(row.get("vehicle_variant") or ""),
        )
        calibration_by_key[key] = row

    profile_groups: dict[tuple[str, str], list[ProfileRecord]] = defaultdict(list)
    for profile in profiles:
        profile_groups[
            (normalize_identity(profile.track), normalize_identity(profile.layout))
        ].append(profile)

    context_keys = set(runtime_contexts) | set(calibration_by_key)
    rows: list[dict[str, Any]] = []

    for key in sorted(
        context_keys,
        key=lambda item: (
            item.track.casefold(),
            item.vehicle_variant.casefold(),
            item.track_layout.casefold(),
        ),
    ):
        candidates = profile_groups.get(
            (normalize_identity(key.track), normalize_identity(key.track_layout)), []
        )
        profile = _best_profile(candidates)
        profile_status = _profile_state(profile)
        runtime = runtime_contexts.get(key)
        calibration = calibration_by_key.get(key)
        h3 = h3_by_context.get(
            H3Context(key.track, key.track_layout, key.vehicle_variant),
            {
                "status": "H3_NOT_APPLICABLE",
                "read_only": True,
                "historical_actions_authorized": False,
            },
        )

        runtime_sessions = int((runtime or {}).get("sessions") or 0)
        calibration_sessions = int((calibration or {}).get("sessions") or 0)
        sessions = max(runtime_sessions, calibration_sessions)

        baseline = _baseline_resolution(
            track=key.track,
            track_layout=key.track_layout,
            vehicle_variant=key.vehicle_variant,
        )
        promotion = discover_promotion_for_context(
            batches_root=batches_root,
            track=key.track,
            track_layout=key.track_layout,
            vehicle_variant=key.vehicle_variant,
            target_variant_sessions=sessions,
        )
        overall_status, next_action = _derive_status(
            profile_status=profile_status,
            sessions=sessions,
            calibration=calibration,
            baseline=baseline,
            promotion=promotion,
        )

        sources = []
        if runtime is not None:
            sources.append("runtime")
        if calibration is not None:
            sources.append("calibration_batches")

        rows.append(
            {
                "track": key.track,
                "track_layout": key.track_layout,
                "vehicle_variant": key.vehicle_variant,
                "sources": sources,
                "profile_status": profile_status,
                "profile_id": profile.profile_id if profile else None,
                "profile_path": str(profile.path) if profile else None,
                "sessions": sessions,
                "runtime_sessions": runtime_sessions,
                "calibration_sessions": calibration_sessions,
                "layout_resolution_counts": dict(
                    (runtime or {}).get("layout_resolution_counts") or {}
                ),
                "queue_pairs": int((calibration or {}).get("queue_pairs") or 0),
                "labeled_pairs": int((calibration or {}).get("labeled_pairs") or 0),
                "evaluation_status": str(
                    (calibration or {}).get("evaluation_status") or "NO_EVALUATION"
                ),
                "evaluation_pairs": int(
                    (calibration or {}).get("evaluation_pairs") or 0
                ),
                "matcher_status": str(
                    (calibration or {}).get("matcher_status")
                    or "NO_CALIBRATION_FOR_CONTEXT"
                ),
                "baseline_status": str(
                    baseline.get("status") or "NO_TRACK_BASELINE"
                ),
                "baseline_source_variants": list(
                    (baseline.get("match") or {}).get("source_variants")
                    or baseline.get("source_variants")
                    or []
                ),
                "match_baseline_status": str(
                    (baseline.get("match") or {}).get("status") or "UNAVAILABLE"
                ),
                "reject_baseline_status": str(
                    (baseline.get("reject") or {}).get("status") or "UNAVAILABLE"
                ),
                "reject_inheritance_policy": str(
                    (baseline.get("reject") or {}).get("inheritance_policy") or ""
                ),
                "baseline_production_authorized": bool(
                    baseline.get("production_authorized") is True
                ),
                "match_promotion_status": str(
                    promotion.get("status") or "NOT_EVALUATED"
                ),
                "match_promotion_batch_id": promotion.get("batch_id"),
                "match_promotion_confirmed_matches": int(
                    promotion.get("confirmed_automatic_matches") or 0
                ),
                "match_promotion_reasons": list(
                    promotion.get("reasons") or []
                ),
                "production_match_authorized": bool(
                    promotion.get("production_match_authorized") is True
                ),
                "production_reject_authorized": bool(
                    promotion.get("production_reject_authorized") is True
                ),
                "historical_status": _historical_status(runtime),
                "h3_import": h3,
                "h3_import_status": str(
                    h3.get("status") or "H3_NOT_APPLICABLE"
                ),
                "overall_status": overall_status,
                "next_action": next_action,
            }
        )

    # When a track/layout has no calibrated baseline yet, avoid asking every
    # vehicle variant for its own human queue. Select one deterministic baseline
    # candidate; sibling variants wait for that baseline instead.
    by_track_layout: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_track_layout[
            (
                normalize_identity(row["track"]),
                normalize_identity(row["track_layout"]),
            )
        ].append(row)

    for group in by_track_layout.values():
        if any(
            row.get("baseline_status") in {
                "EXACT_VARIANT_CALIBRATION",
                "TRACK_BASELINE_SHADOW",
                "TRACK_BASELINE_CONFLICT",
            }
            for row in group
        ):
            continue

        eligible = [
            row
            for row in group
            if row.get("profile_status") == "VALIDATED"
            and int(row.get("sessions") or 0) > 0
        ]
        if len(eligible) <= 1:
            continue

        candidate = max(
            eligible,
            key=lambda row: (
                int(row.get("labeled_pairs") or 0)
                >= int(row.get("queue_pairs") or 0)
                > 0,
                int(row.get("labeled_pairs") or 0),
                int(row.get("queue_pairs") or 0),
                int(row.get("sessions") or 0),
                str(row.get("vehicle_variant") or ""),
            ),
        )
        candidate_variant = str(candidate.get("vehicle_variant") or "")

        for row in eligible:
            if row is candidate:
                row["baseline_candidate"] = True
                continue
            row["baseline_candidate"] = False
            row["overall_status"] = "WAITING_FOR_TRACK_BASELINE"
            row["next_action"] = {
                "code": "ESTABLISH_TRACK_BASELINE_FIRST",
                "description": (
                    f"Wait for {candidate_variant} to establish the track/layout "
                    "baseline before creating a variant-specific queue"
                ),
                "baseline_candidate_variant": candidate_variant,
            }

    counts: dict[str, int] = defaultdict(int)
    h3_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["overall_status"]] += 1
        h3_counts[row["h3_import_status"]] += 1

    tracks = _build_track_summary(
        rows=rows,
        profiles=profiles,
        unresolved_sessions=unresolved_sessions,
    )

    resolved_by_profile = sum(
        int((row.get("layout_resolution_counts") or {}).get("validated_track_profile", 0))
        for row in rows
    )

    return {
        "version": TRACK_READINESS_VERSION,
        "read_only": True,
        "rows": rows,
        "tracks": tracks,
        "unresolved_sessions": unresolved_sessions,
        "summary": {
            "tracks": len(tracks),
            "contexts": len(rows),
            "resolved_missing_layout_from_profile": resolved_by_profile,
            "unresolved_sessions": len(unresolved_sessions),
            "status_counts": dict(sorted(counts.items())),
            "h3_import_status_counts": dict(sorted(h3_counts.items())),
        },
        "identity_warnings": _identity_warnings(rows),
        "errors": profile_errors + runtime_errors,
    }
