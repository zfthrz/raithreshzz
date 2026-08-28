from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from cross_session_zone_localization import VALID_PROFILE_STATUSES, normalize_identity
from race_engineer_ui_model import load_calibration_summary


TRACK_READINESS_VERSION = "0.1"
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
    if not record.valid_turns:
        return "INVALID"
    return "PRESENT_UNVALIDATED"


def _analysis_path_from_state(state: dict[str, Any], state_path: Path) -> Path | None:
    analyze = _dict(_dict(state.get("stages")).get("analyze"))
    value = analyze.get("output")
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute():
        path = (state_path.parent / path).resolve()
    return path if path.is_file() else None


def discover_runtime_contexts(runs_root: Path) -> tuple[dict[ContextKey, dict[str, Any]], list[str]]:
    contexts: dict[ContextKey, dict[str, Any]] = {}
    errors: list[str] = []
    root = Path(runs_root)
    if not root.is_dir():
        return contexts, []

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
                or track
            ).strip()
            variant = str(
                identity.get("variant") or metadata.get("vehicle_variant") or ""
            ).strip()
            if not track or not layout or not variant:
                continue
            key = ContextKey(track, layout, variant)
            entry = contexts.setdefault(
                key,
                {
                    "sessions": 0,
                    "h4_reference_available": False,
                    "historical_evidence_available": False,
                },
            )
            entry["sessions"] += 1
            stages = _dict(state.get("stages"))
            h4 = _dict(stages.get("h4"))
            if (
                str(h4.get("status") or "") in READY_STAGE_STATUSES
                and h4.get("output")
            ):
                entry["h4_reference_available"] = True
            for stage_name, raw_stage in stages.items():
                stage = _dict(raw_stage)
                status = str(stage.get("status") or "")
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
    return contexts, errors


def _historical_status(runtime: dict[str, Any] | None) -> str:
    if not runtime:
        return "NO_REFERENCE"
    if runtime.get("historical_evidence_available"):
        return "EVIDENCE_AVAILABLE"
    if runtime.get("h4_reference_available"):
        return "REFERENCE_AVAILABLE"
    return "NO_REFERENCE"


def _derive_status(
    *,
    profile_status: str,
    sessions: int,
    calibration: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
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


def build_track_readiness(
    *,
    project_root: Path | None = None,
    profile_dir: Path | None = None,
    batches_root: Path | None = None,
    runs_root: Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root or Path(__file__).resolve().parent)
    profile_dir = Path(profile_dir or root / "track_profiles")
    batches_root = Path(batches_root or root / "calibration_batches")
    runs_root = Path(runs_root or root / "data" / "generated" / "runs")

    profiles, profile_errors = discover_profiles(profile_dir)
    runtime_contexts, runtime_errors = discover_runtime_contexts(runs_root)
    calibration_summary = load_calibration_summary(batches_root)
    calibration_rows = calibration_summary.get("rows") or []

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
        sessions = max(
            int((runtime or {}).get("sessions") or 0),
            int((calibration or {}).get("sessions") or 0),
        )
        overall_status, next_action = _derive_status(
            profile_status=profile_status,
            sessions=sessions,
            calibration=calibration,
        )
        rows.append(
            {
                "track": key.track,
                "track_layout": key.track_layout,
                "vehicle_variant": key.vehicle_variant,
                "profile_status": profile_status,
                "profile_id": profile.profile_id if profile else None,
                "profile_path": str(profile.path) if profile else None,
                "sessions": sessions,
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
                "historical_status": _historical_status(runtime),
                "overall_status": overall_status,
                "next_action": next_action,
            }
        )

    known_track_layouts = {
        (normalize_identity(row["track"]), normalize_identity(row["track_layout"]))
        for row in rows
    }
    orphan_profiles: list[dict[str, Any]] = []
    for identity, candidates in sorted(profile_groups.items()):
        if identity in known_track_layouts:
            continue
        profile = _best_profile(candidates)
        if profile is None:
            continue
        orphan_profiles.append(
            {
                "track": profile.track,
                "track_layout": profile.layout,
                "profile_status": _profile_state(profile),
                "profile_id": profile.profile_id,
                "profile_path": str(profile.path),
                "overall_status": "NEEDS_SESSIONS",
                "next_action": {
                    "code": "RECORD_MORE_SESSIONS",
                    "description": "No vehicle context has been discovered yet",
                },
            }
        )

    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["overall_status"]] += 1

    return {
        "version": TRACK_READINESS_VERSION,
        "read_only": True,
        "rows": rows,
        "track_only": orphan_profiles,
        "summary": {
            "tracks": len(
                {normalize_identity(row["track"]) for row in rows}
                | {normalize_identity(row["track"]) for row in orphan_profiles}
            ),
            "contexts": len(rows),
            "status_counts": dict(sorted(counts.items())),
        },
        "errors": profile_errors + runtime_errors,
    }
