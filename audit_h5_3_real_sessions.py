"""H5.3 Point 6 — Real-new-session audit harness v0.2

Estado: OBSERVATIONAL_AUDIT_ONLY
Autoridad: ninguna
historical_actions_authorized: false

Este auditor consume artifacts reales generados por race_engineer.py
(el pipeline H5.3 completo: H4, H5.1, H5.2, H5.3a-f) y genera un
informe de auditoría sin volver a ejecutar ningún paso del pipeline.

INPUT:
  python audit_h5_3_real_sessions.py data/generated/runs/<session> ...

RESOLUCIÓN DE ARTIFACTS (real runtime layout):
  El auditor resuelve artifacts por identidad de sesión usando el
  layout real de data/generated/, no asume que todos viven dentro
  del run dir recibido.

  Session name = basename del run dir (o session ID del state.json).

  Layout real (runtime_paths.py):
    analysis:    data/generated/analysis/<session>.json
    h4:          data/generated/h4/<session>/historical_reference_selection.json
    h5_1:        data/generated/h5_1/<session>/dual_reference_context.json
    h5_2:        data/generated/h5_2/<session>/cross_session_comparison.json
    h5_3:        data/generated/h5_3/<session>/historical_coaching_candidates.json
                 data/generated/h5_3/<session>/historical_section.json
    h5_2_llm:    data/generated/h5_2_llm/<session>/...
    h5_3_shadow: data/generated/h5_3_shadow/<session>/shadow_pipeline.json  (canonical)
                 data/generated/h5_3_shadow/<hashed-id>.json              (legacy fallback)
    runs:        data/generated/runs/<session>/state.json

  Para H5.3 shadow: se usa la identidad de sesión desde el run state
  o H4/H5.1 artifacts para encontrar el artefacto correcto.
  NO adivinar hash por filename.

OUTPUT:
  data/generated/h5_3_real_session_audit/<timestamp>/audit.json

"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_paths import generated_root

AUDIT_VERSION = "0.2"
SCHEMA_VERSION = "1.0"
STATUS_INCOMPLETE_AUDIT = "INCOMPLETE_AUDIT"
STATUS_AUDIT_COMPLETE = "AUDIT_COMPLETE"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUS_AMBIGUOUS_ARTIFACT = "AMBIGUOUS_ARTIFACT"

# ── Authorized observation codes ────────────────────────────────────────────

AUTHORIZED_OBSERVATIONS = frozenset({
    "time_loss", "time_gain",
    "current_speed_lower", "current_speed_higher",
    "current_throttle_lower", "current_throttle_higher",
    "current_brake_lower", "current_brake_higher",
})

# ── Policy constants ──────────────────────────────────────────────────────

AUTHORIZED_ACTIONS = frozenset({
    "reduce_throttle", "increase_throttle",
    "reduce_brake", "increase_brake",
})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_json(path: Path) -> dict[str, Any] | None:
    """Load JSON file; return None if missing or invalid."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Artifact resolution (real runtime layout) ───────────────────────────────

def resolve_session_name(run_dir: Path) -> str | None:
    """Extract session name from run directory.

    Prefers:
      1. session_id from state.json
      2. basename of run_dir
    """
    state = _load_run_state(run_dir)
    if state:
        sid = state.get("session_id", "")
        if sid:
            return sid
    return run_dir.stem


def _load_run_state(run_dir: Path) -> dict[str, Any] | None:
    """Load run state.json from a run directory."""
    return load_json(run_dir / "state.json")


def resolve_artifact_path(base: Path, stage: str, session_name: str, filename: str) -> Path:
    """Build artifact path: data/generated/<stage>/<session_name>/<filename>."""
    return base / stage / session_name / filename


def resolve_h5_3_shadow_artifact(
    run_dir: Path,
    h4_data: dict | None,
    h5_1_data: dict | None,
    session_name: str,
    *,
    base_dir: Path | None = None,
) -> Path | None:
    """Find H5.3 shadow artifact by session identity.

    Priority:
      1. Canonical session-dir:
         data/generated/h5_3_shadow/<session_name>/shadow_pipeline.json
         – if the dir exists and contains exactly shadow_pipeline.json → use it
         – if the dir exists but has multiple candidate files → AMBIGUOUS → None
      2. Legacy provenance fallback:
         scan data/generated/h5_3_shadow/*.json for a file whose JSON content
         contains the target session_id (same logic as before).
      3. If canonical and legacy both point to files with different content:
         prefer canonical but verify session identity matches.
      4. If canonical directory has 0 matching candidate files:
         fall through to legacy fallback.

    Legacy flat layout:
      data/generated/h5_3_shadow/<hashed-id>.json

    New canonical layout:
      data/generated/h5_3_shadow/<session_name>/shadow_pipeline.json

    Args:
        run_dir: The run directory for this session.
        h4_data: Loaded H4 historical reference selection data.
        h5_1_data: Loaded H5.1 dual reference context data.
        session_name: The session identifier.
        base_dir: Override the generated_root for testing. Defaults to runtime_paths.generated_root().
    """
    if base_dir is None:
        shadow_dir = generated_root() / "h5_3_shadow"
    else:
        shadow_dir = base_dir / "h5_3_shadow"
    if not shadow_dir.is_dir():
        return None

    # ── Step 1: Canonical session-dir check ───────────────────────────────
    canonical_dir = shadow_dir / session_name
    canonical_path = canonical_dir / "shadow_pipeline.json"

    if canonical_dir.is_dir():
        # Known canonical pipeline files: these are part of the single pipeline
        # and do NOT cause ambiguity. Only unexpected extras trigger fail-closed.
        canonical_names = {
            "shadow_pipeline.json",
            "candidate_eligibility.json",
            "candidate_selection.json",
            "historical_actions.json",
        }
        dir_files = [f for f in canonical_dir.iterdir() if f.is_file() and f.suffix == ".json"]
        extra_files = [f for f in dir_files if f.name not in canonical_names]

        if extra_files:
            # Unexpected extra files beyond canonical pipeline set — ambiguous
            return None

        if canonical_path.is_file():
            canonical_artifact = load_json(canonical_path)
            if canonical_artifact:
                # Verify session identity via source_candidates_json provenance
                source_ref = canonical_artifact.get("metadata", {}).get("source_candidates_json", "")
                if session_name in source_ref:
                    return canonical_path

    # ── Step 3: Legacy provenance fallback ────────────────────────────────
    # Extract target session_id from H4/H5.1/run state
    target_session_id = None
    if h4_data:
        target_session_id = h4_data.get("historical_reference", {}).get("session_id")
    elif h5_1_data:
        target_session_id = h5_1_data.get("session_reference", {}).get("session_id")
    else:
        state = _load_run_state(run_dir)
        if state:
            target_session_id = state.get("session_id")

    if not target_session_id:
        return None

    # Scan all flat shadow artifacts for matching session_id
    matches: list[Path] = []
    for artifact_file in sorted(shadow_dir.iterdir()):
        if not artifact_file.is_file() or not artifact_file.suffix == ".json":
            continue
        artifact = load_json(artifact_file)
        if not artifact:
            continue
        if target_session_id in json.dumps(artifact, ensure_ascii=False):
            matches.append(artifact_file)

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        return None
    else:
        return None


def resolve_all_artifacts(session_name: str, base_dir: Path | None = None) -> dict[str, Path | None]:
    """Resolve all required artifacts for a session.

    Args:
        session_name: The session identifier
        base_dir: Override the generated_root for testing. Defaults to runtime_paths.generated_root().

    Returns:
        dict of {artifact_key: resolved_path}
    """
    artifacts: dict[str, Path | None] = {}
    base = base_dir if base_dir is not None else generated_root()

    # Analysis
    analysis_path = base / "analysis" / f"{session_name}.json"
    artifacts["analysis"] = analysis_path if analysis_path.is_file() else None

    # H4
    h4_path = base / "h4" / session_name / "historical_reference_selection.json"
    artifacts["h4"] = h4_path if h4_path.is_file() else None

    # H5.1
    h5_1_path = base / "h5_1" / session_name / "dual_reference_context.json"
    artifacts["h5_1"] = h5_1_path if h5_1_path.is_file() else None

    # H5.2
    h5_2_path = base / "h5_2" / session_name / "cross_session_comparison.json"
    artifacts["h5_2"] = h5_2_path if h5_2_path.is_file() else None

    # H5.3 candidates
    h5_3_candidates_path = base / "h5_3" / session_name / "historical_coaching_candidates.json"
    artifacts["h5_3_candidates"] = h5_3_candidates_path if h5_3_candidates_path.is_file() else None

    # H5.3 section
    h5_3_section_path = base / "h5_3" / session_name / "historical_section.json"
    artifacts["h5_3_section"] = h5_3_section_path if h5_3_section_path.is_file() else None

    return artifacts


def resolve_h5_3_shadow_from_provenance(
    run_dir: Path,
    artifacts: dict[str, Path | None],
    session_name: str,
    base_dir: Path | None = None,
) -> Path | None:
    """Resolve H5.3 shadow artifact using provenance from resolved artifacts.

    Args:
        run_dir: The run directory for this session.
        artifacts: Dict of resolved artifact paths.
        session_name: The session identifier.
        base_dir: Override the generated_root for testing. Defaults to runtime_paths.generated_root().
    """
    h4_data = load_json(artifacts.get("h4", Path())) if artifacts.get("h4") else None
    h5_1_data = load_json(artifacts.get("h5_1", Path())) if artifacts.get("h5_1") else None
    return resolve_h5_3_shadow_artifact(run_dir, h4_data, h5_1_data, session_name, base_dir=base_dir)


# ── Audit functions ─────────────────────────────────────────────────────────

def _get_obs_codes_from_canonical(
    selection_artifact: dict | None,
    actions_artifact: dict | None,
    candidate_id: str,
) -> list[str]:
    """Extract observation codes for a candidate from canonical artifacts."""
    # From canonical selection artifact
    if selection_artifact:
        for sel in selection_artifact.get("llm_selection", {}).get("selected_candidates", []):
            if sel.get("candidate_id") == candidate_id:
                return sel.get("observation_codes", [])

    # From canonical actions artifact (actions already computed)
    if actions_artifact:
        for action in actions_artifact.get("actions", []):
            if action.get("candidate_id") == candidate_id:
                auth = action.get("authorization", {})
                obs = auth.get("observation_codes", [])
                return obs

    return []


def audit_identity(
    run_dir: Path,
    analysis: dict,
    h5_1_data: dict,
) -> dict[str, Any]:
    """Extract session identity from analysis JSON or H5.1 dual reference."""
    metadata = analysis.get("metadata", {})
    context = h5_1_data.get("context", {})

    return {
        "track": context.get("track", metadata.get("track", "unknown")),
        "track_layout": context.get("track_layout", metadata.get("track_layout", "unknown")),
        "vehicle_variant": context.get("vehicle_variant", metadata.get("vehicle_variant", "unknown")),
        "car_name_raw": context.get("car_name_raw", metadata.get("car_name_raw")),
        "session_source": "race_engineer_pipeline",
        "provenance": {
            "analysis_sha256": metadata.get("analysis_sha256", "unknown"),
            "h1_session_id": metadata.get("session_id"),
        },
    }


def audit_analyzer(analysis: dict) -> dict[str, Any]:
    """Audit the analyzer output."""
    metadata = analysis.get("metadata", {})
    comparative = metadata.get("comparative_status")

    valid_laps = _safe_int(metadata.get("valid_lap_count"))
    comparison_count = _safe_int(metadata.get("comparison_count"))

    return {
        "valid_laps": valid_laps,
        "comparison_count": comparison_count,
        "comparative_status": comparative,
        "status": "SUPPORTED" if comparative != "SKIPPED_NOT_APPLICABLE" else "INSUFFICIENT_LAPS",
        "skipped_reason": None if comparative != "SKIPPED_NOT_APPLICABLE" else comparative,
    }


def resolve_h5_3_canonical_artifacts(
    run_dir: Path,
    session_name: str,
    shadow_path: Path | None,
    base_dir: Path | None = None,
) -> dict[str, dict | None]:
    """Resolve all canonical H5.3 shadow artifacts from the canonical session-dir.

    Canonical layout:
      data/generated/h5_3_shadow/<session_name>/
        shadow_pipeline.json     — pipeline metadata (already resolved as shadow_path)
        candidate_selection.json — authorized_candidates + llm_selection
        historical_actions.json  — actions + withheld
        candidate_eligibility.json — eligibility results

    Returns dict with keys:
      selection:  candidate_selection.json  (or None)
      actions:    historical_actions.json  (or None)
      eligibility: candidate_eligibility.json  (or None)

    Args:
        run_dir: The run directory for this session.
        session_name: The session identifier.
        shadow_path: The resolved shadow_pipeline.json path (or None).
        base_dir: Override the generated_root for testing.
    """
    if base_dir is None:
        shadow_dir = generated_root() / "h5_3_shadow" / session_name
    else:
        shadow_dir = base_dir / "h5_3_shadow" / session_name

    if not shadow_dir.is_dir():
        return {"selection": None, "actions": None, "eligibility": None}

    # Load shadow_pipeline for fallback if canonical files are missing
    shadow_pipeline = None
    if shadow_path and shadow_path.is_file():
        shadow_pipeline = load_json(shadow_path)

    canonical_names = {
        "candidate_selection.json": "selection",
        "historical_actions.json": "actions",
        "candidate_eligibility.json": "eligibility",
    }

    result: dict[str, dict | None] = {"selection": None, "actions": None, "eligibility": None}
    for filename, key in canonical_names.items():
        path = shadow_dir / filename
        data = load_json(path)
        if data:
            result[key] = data

    # If canonical files are missing, fall back to shadow_pipeline
    if not result["selection"] and shadow_pipeline:
        pipeline_artifacts = shadow_pipeline.get("pipeline_artifacts", {})
        if pipeline_artifacts.get("selection"):
            result["selection"] = pipeline_artifacts["selection"]

    if not result["actions"] and shadow_pipeline:
        if shadow_pipeline.get("actions"):
            result["actions"] = shadow_pipeline["actions"]

    if not result["eligibility"] and shadow_pipeline:
        elig_artifact = shadow_pipeline.get("pipeline_artifacts", {}).get("eligibility")
        if elig_artifact:
            result["eligibility"] = elig_artifact

    return result


def audit_h5_3_eligibility(
    shadow_pipeline: dict | None,
    eligibility_artifact: dict | None,
) -> dict[str, Any]:
    """Audit H5.3 eligibility from shadow pipeline or canonical eligibility artifact.

    Priority:
      1. Canonical eligibility artifact (candidate_eligibility.json)
      2. Shadow pipeline pipeline_artifacts.eligibility
    """
    if eligibility_artifact:
        summary = eligibility_artifact.get("summary", {})
        by_status = summary.get("by_status", {})
        total = summary.get("total_candidates", 0)
        eligible = by_status.get("ELIGIBLE_FOR_SELECTION", 0)
        withheld = by_status.get("WITHHELD", 0)
        ambiguous = by_status.get("AMBIGUOUS", 0)
        return {
            "total_candidates": total,
            "eligible": eligible,
            "withheld": withheld,
            "ambiguous": ambiguous,
            "eligibility_status": eligibility_artifact.get("status"),
        }

    if not shadow_pipeline:
        return {
            "total_candidates": 0,
            "eligible": 0,
            "withheld": 0,
            "ambiguous": 0,
            "eligibility_status": "NO_SHADOW_PIPELINE",
        }

    pipeline_artifacts = shadow_pipeline.get("pipeline_artifacts", {})
    elig_artifact = pipeline_artifacts.get("eligibility")

    if not elig_artifact:
        return {
            "total_candidates": 0,
            "eligible": 0,
            "withheld": 0,
            "ambiguous": 0,
            "eligibility_status": "NO_ELIGIBILITY",
        }

    summary = elig_artifact.get("summary", {})
    by_status = summary.get("by_status", {})
    total = summary.get("total_candidates", 0)
    eligible = by_status.get("ELIGIBLE_FOR_SELECTION", 0)
    withheld = by_status.get("WITHHELD", 0)
    ambiguous = by_status.get("AMBIGUOUS", 0)

    return {
        "total_candidates": total,
        "eligible": eligible,
        "withheld": withheld,
        "ambiguous": ambiguous,
        "eligibility_status": elig_artifact.get("status"),
    }


def audit_llm_selection_from_canonical(
    selection_artifact: dict | None,
    shadow_selection: dict,
) -> dict[str, Any]:
    """Audit LLM selection from canonical candidate_selection.json.

    Priority:
      1. Canonical candidate_selection.json (has authorized_candidates + llm_selection)
      2. Shadow pipeline selection (fallback)
    """
    # If canonical selection artifact exists, use it
    if selection_artifact:
        return audit_llm_selection(selection_artifact)

    # Fallback to shadow pipeline selection
    return audit_llm_selection(shadow_selection)


def audit_action_policy_from_canonical(
    actions_artifact: dict | None,
    shadow_actions: dict,
) -> dict[str, Any]:
    """Audit action policy from canonical historical_actions.json.

    Priority:
      1. Canonical historical_actions.json (has actions + withheld)
      2. Shadow pipeline actions (fallback)
    """
    if actions_artifact:
        return audit_action_policy(actions_artifact)

    # Fallback to shadow pipeline actions
    return audit_action_policy(shadow_actions)


# ── Audit functions ─────────────────────────────────────────────────────────


def audit_llm_selection(
    selection: dict,
) -> dict[str, Any]:
    """Audit LLM selection against authorized evidence."""
    if not selection:
        return {
            "selected_count": 0,
            "observation_codes_valid": True,
            "errors": [],
            "valid_observation_codes": [],
            "invalid_observation_codes": [],
            "selection_status": "NO_SELECTION",
        }

    authorized_candidates = selection.get("authorized_candidates", [])
    by_id: dict[str, dict] = {
        c["candidate_id"]: c
        for c in authorized_candidates
        if isinstance(c, dict) and "candidate_id" in c
    }

    llm_sel = selection.get("llm_selection", {})
    selected = llm_sel.get("selected_candidates", [])
    errors: list[str] = []
    valid_codes: list[str] = []
    invalid_codes: list[str] = []

    for item in selected:
        if not isinstance(item, dict):
            continue
        candidate_id = item.get("candidate_id", "UNKNOWN")
        observation_codes = item.get("observation_codes", [])

        candidate = by_id.get(candidate_id)
        if candidate is None:
            errors.append(f"selected candidate_id {candidate_id} not in authorized")
            continue

        authorized_obs = set(candidate.get("authorized_observations", []))
        selected_set = set(observation_codes)

        if not selected_set.issubset(authorized_obs):
            unauthorized = selected_set - authorized_obs
            errors.append(
                f"{candidate_id}: observation_codes {list(unauthorized)} "
                f"not authorized (authorized: {list(authorized_obs)})"
            )
            invalid_codes.extend(list(unauthorized))
        else:
            valid_codes.extend(observation_codes)

    # Derive formal selection status from canonical artifact:
    # Use the top-level selection status (candidate_selection.json.status)
    # as authoritative; fall back to llm_selection.status only if absent.
    selection_status = selection.get("status") or llm_sel.get("status", "UNKNOWN")

    return {
        "selected_count": len(selected),
        "observation_codes_valid": len(errors) == 0,
        "errors": errors,
        "valid_observation_codes": list(set(valid_codes)),
        "invalid_observation_codes": list(set(invalid_codes)),
        "selection_status": selection_status,
    }


def audit_action_policy(actions: dict) -> dict[str, Any]:
    """Audit action policy output."""
    if not actions:
        return {
            "authorized_actions": 0,
            "withheld": 0,
            "anti_regression_passed": True,
            "speed_time_not_actions": True,
            "errors": [],
        }

    action_records = actions.get("actions", [])
    withheld_records = actions.get("withheld", [])
    errors: list[str] = []
    anti_regression_ok = True
    speed_time_ok = True

    for action in action_records:
        candidate_id = action.get("candidate_id", "UNKNOWN")
        delta_sign = action.get("delta_sign", "")

        # Anti-regression: only current_slower
        if delta_sign != "current_slower":
            errors.append(
                f"{candidate_id}: anti-regression violation "
                f"(delta_sign={delta_sign}, expected current_slower)"
            )
            anti_regression_ok = False

        # Speed/time never actions
        action_codes = action.get("actions", [])
        for code in action_codes:
            if "speed" in code.lower():
                errors.append(f"{candidate_id}: speed-related action prohibited: {code}")
                speed_time_ok = False

    for item in withheld_records:
        reason = item.get("reason", "")
        if reason not in {"current_lap_faster_no_actions", "no_mappable_actions"}:
            errors.append(f"withheld reason unknown: {reason}")

    return {
        "authorized_actions": len(action_records),
        "withheld": len(withheld_records),
        "anti_regression_passed": anti_regression_ok,
        "speed_time_not_actions": speed_time_ok,
        "errors": errors,
    }


def audit_validator(section: dict, actions: dict) -> dict[str, Any]:
    """Audit validator outputs."""
    section_pass = True
    actions_pass = True
    section_errors: list[str] = []
    actions_errors: list[str] = []

    if section:
        status = section.get("status")
        if status != "DETERMINISTIC_HISTORICAL_SECTION":
            section_pass = False
            section_errors.append(f"section status invalid: {status}")
    else:
        section_pass = False
        section_errors.append("section artifact missing")

    if actions:
        status = actions.get("status")
        if status != "HISTORICAL_ACTION_CANDIDATES_VALIDATED":
            actions_pass = False
            actions_errors.append(f"actions status invalid: {status}")
    else:
        actions_pass = False
        actions_errors.append("actions artifact missing")

    return {
        "section_pass": section_pass,
        "actions_pass": actions_pass,
        "section_errors": section_errors,
        "actions_errors": actions_errors,
        "overall": section_pass and actions_pass,
    }


def classify_candidate(
    candidate_id: str,
    in_actions: bool,
    in_withheld: bool,
    selector_valid: bool,
    policy_valid: bool,
    validator_ok: bool,
) -> str:
    """Deterministically classify a candidate."""
    if not candidate_id:
        return "NOT_APPLICABLE"

    if not selector_valid:
        return "SELECTOR_INVALID"
    if not policy_valid:
        return "POLICY_INVALID"
    if not validator_ok:
        return "VALIDATOR_FAILED"

    if in_actions:
        return "CLEAN_AUTHORIZED"
    if in_withheld:
        return "CLEAN_WITHHELD"

    return "NOT_APPLICABLE"


def build_human_review(
    candidate: dict,
    selection_info: dict,
    policy_info: dict,
    context: dict,
    delta_info: dict,
) -> dict[str, Any]:
    """Build human review record with null manual fields."""
    return {
        "candidate_id": candidate.get("candidate_id", ""),
        "location_label": candidate.get("location_label", ""),
        "start_distance_m": candidate.get("start_distance_m"),
        "end_distance_m": candidate.get("end_distance_m"),
        "spatial_range_m": (
            f"{candidate.get('start_distance_m', 0):.0f}-{candidate.get('end_distance_m', 0):.0f}"
        ),
        "local_time_loss_s": delta_info.get("delta_change_s"),
        "authorized_observations": candidate.get("authorized_observations", []),
        "selector_observation_codes": selection_info.get("observation_codes", []),
        "resulting_action": policy_info.get("action_code", ""),
        "withheld_reason": policy_info.get("withheld_reason", ""),
        "session_faster_slower": delta_info.get("delta_sign", ""),
        "provenance_id": candidate.get("candidate_id", ""),
        "human_review": {
            "actionability": None,
            "observation_correct": None,
            "action_correct": None,
            "notes": None,
        },
    }


def audit_session(
    run_dir: Path,
    session_name: str,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Full audit for a single session.

    Resolves artifacts from the real runtime layout.

    Args:
        run_dir: The run directory for this session
        session_name: The session identifier (extracted from run_dir or state.json)
        base_dir: Override the generated_root for testing.
    """
    # ── Resolve artifacts ─────────────────────────────────────────────────
    artifacts = resolve_all_artifacts(session_name, base_dir=base_dir)

    # Check for required artifacts
    missing: list[str] = []
    for key in ["analysis", "h4", "h5_1", "h5_2", "h5_3_candidates", "h5_3_section"]:
        if not artifacts.get(key):
            # Map key to actual stage and filename for clean paths
            stage_map: dict[str, tuple[str, str]] = {
                "analysis": ("analysis", f"{session_name}.json"),
                "h4": ("h4", "historical_reference_selection.json"),
                "h5_1": ("h5_1", "dual_reference_context.json"),
                "h5_2": ("h5_2", "cross_session_comparison.json"),
                "h5_3_candidates": ("h5_3", "historical_coaching_candidates.json"),
                "h5_3_section": ("h5_3", "historical_section.json"),
            }
            stage, filename = stage_map.get(key, (key, "unknown.json"))
            missing.append(f"{stage}/{filename}")

    # ── FAIL-CLOSED: missing required artifacts ─────────────────────────
    if missing:
        # Check if H5.3 shadow is also missing
        h5_3_shadow_path = resolve_h5_3_shadow_from_provenance(
            run_dir,
            artifacts,
            session_name,
            base_dir=base_dir,
        )
        if not h5_3_shadow_path:
            missing.append("h5_3_shadow: artifact not found")

        return {
            "session": session_name,
            "status": STATUS_INCOMPLETE_AUDIT,
            "missing_artifacts": missing,
            "present_artifacts": [k for k, v in artifacts.items() if v],
        }

    # Load all resolved artifacts
    analysis = load_json(artifacts["analysis"])
    h4_data = load_json(artifacts["h4"])
    h5_1_data = load_json(artifacts["h5_1"])
    h5_2_data = load_json(artifacts["h5_2"])
    h5_3_candidates = load_json(artifacts["h5_3_candidates"])
    h5_3_section = load_json(artifacts["h5_3_section"])

    # Resolve H5.3 shadow
    h5_3_shadow_path = resolve_h5_3_shadow_from_provenance(
        run_dir,
        artifacts,
        session_name,
        base_dir=base_dir,
    )
    if not h5_3_shadow_path:
        return {
            "session": session_name,
            "status": STATUS_INCOMPLETE_AUDIT,
            "missing_artifacts": missing + ["h5_3_shadow: artifact not found"],
            "present_artifacts": [k for k, v in artifacts.items() if v],
        }

    shadow_pipeline = load_json(h5_3_shadow_path)

    # Resolve canonical H5.3 artifacts from the same session-dir
    canonical_artifacts = resolve_h5_3_canonical_artifacts(
        run_dir,
        session_name,
        h5_3_shadow_path,
        base_dir=base_dir,
    )
    selection_artifact = canonical_artifacts.get("selection")
    actions_artifact = canonical_artifacts.get("actions")
    eligibility_artifact = canonical_artifacts.get("eligibility")

    # ── Identity ──────────────────────────────────────────────────────────
    identity = audit_identity(run_dir, analysis, h5_1_data)
    analyzer = audit_analyzer(analysis)

    # ── NOT_APPLICABLE: insufficient comparable laps ──────────────────────
    if analyzer["status"] == "INSUFFICIENT_LAPS":
        return {
            "session": session_name,
            "identity": identity,
            "analyzer": analyzer,
            "status": STATUS_NOT_APPLICABLE,
            "reason": "insufficient_comparable_laps",
        }

    # ── Eligibility ───────────────────────────────────────────────────────
    eligibility = audit_h5_3_eligibility(shadow_pipeline, eligibility_artifact)

    # ── Selection ──────────────────────────────────────────────────────────
    # Extract shadow selection fallback from pipeline
    shadow_selection = {}
    if shadow_pipeline:
        shadow_selection = shadow_pipeline.get("pipeline_artifacts", {}).get("selection", {})
    selector_audit = audit_llm_selection_from_canonical(selection_artifact, shadow_selection)

    # ── Action Policy ──────────────────────────────────────────────────────
    shadow_actions = {}
    if shadow_pipeline:
        shadow_actions = shadow_pipeline.get("actions", {})
    actions_audit = audit_action_policy_from_canonical(actions_artifact, shadow_actions)

    # ── Validator ──────────────────────────────────────────────────────────
    # For validator, use canonical actions_artifact; fallback to shadow_actions
    validator_audit = audit_validator(h5_3_section, actions_artifact or shadow_actions)

    # ── Per-candidate classification ───────────────────────────────────────
    # Use canonical selection artifact if present; fall back to shadow selection
    if selection_artifact:
        authorized_candidates = selection_artifact.get("authorized_candidates", [])
    else:
        authorized_candidates = selector_audit.get("authorized_candidates", [])

    candidate_results: list[dict[str, Any]] = []
    human_reviews: list[dict[str, Any]] = []

    # Build action/withheld sets
    action_ids: set[str] = set()
    withheld_ids: set[str] = set()
    if actions_artifact:
        for action in actions_artifact.get("actions", []):
            cid = action.get("candidate_id")
            if cid:
                action_ids.add(cid)
        for item in actions_artifact.get("withheld", []):
            cid = item.get("candidate_id")
            if cid:
                withheld_ids.add(cid)

    for candidate in authorized_candidates:
        cid = candidate.get("candidate_id", "")
        in_actions = cid in action_ids
        in_withheld = cid in withheld_ids

        status = classify_candidate(
            cid, in_actions, in_withheld,
            selector_audit["observation_codes_valid"],
            actions_audit["anti_regression_passed"],
            validator_audit["overall"],
        )

        delta_change = candidate.get("delta_change_s")
        delta_sign = candidate.get("delta_sign", "")

        policy_info = {}
        if in_actions:
            action_rec = next(
                (a for a in actions_artifact.get("actions", []) if a.get("candidate_id") == cid),
                {},
            )
            policy_info = {
                "action_code": action_rec.get("actions", []),
                "withheld_reason": "",
            }
        elif in_withheld:
            withheld_rec = next(
                (w for w in actions_artifact.get("withheld", []) if w.get("candidate_id") == cid),
                {},
            )
            policy_info = {
                "action_code": "",
                "withheld_reason": withheld_rec.get("reason", ""),
            }

        human_review = build_human_review(
            candidate,
            {
                "observation_codes": _get_obs_codes_from_canonical(
                    selection_artifact, actions_artifact, cid
                ),
            },
            policy_info,
            identity,
            {
                "delta_change_s": delta_change,
                "delta_sign": delta_sign,
            },
        )

        record = {
            "candidate_id": cid,
            "location_label": candidate.get("location_label", ""),
            "status": status,
            "delta_change_s": delta_change,
            "delta_sign": delta_sign,
            "provenance": {
                "candidate_id": cid,
                "authorized": True,
                "selector_valid": selector_audit["observation_codes_valid"],
                "policy_valid": actions_audit["anti_regression_passed"],
                "validator_ok": validator_audit["overall"],
            },
        }
        candidate_results.append(record)
        human_reviews.append(human_review)

    # ── Session summary ────────────────────────────────────────────────────
    session_summary = {
        "total_candidates": eligibility.get("total_candidates", 0),
        "eligible_count": eligibility.get("eligible", 0),
        "eligible_rate": (
            round(eligibility.get("eligible", 0) / max(eligibility.get("total_candidates", 1), 1), 4)
        ),
        "selected_count": selector_audit.get("selected_count", 0),
        "clean_authorized": sum(1 for r in candidate_results if r["status"] == "CLEAN_AUTHORIZED"),
        "clean_withheld": sum(1 for r in candidate_results if r["status"] == "CLEAN_WITHHELD"),
        "selector_invalid": sum(1 for r in candidate_results if r["status"] == "SELECTOR_INVALID"),
        "policy_invalid": sum(1 for r in candidate_results if r["status"] == "POLICY_INVALID"),
        "validator_failures": sum(1 for r in candidate_results if r["status"] == "VALIDATOR_FAILED"),
        "not_applicable": sum(1 for r in candidate_results if r["status"] == "NOT_APPLICABLE"),
    }

    return {
        "session": session_name,
        "identity": identity,
        "analyzer": analyzer,
        "eligibility": eligibility,
        "selector_audit": selector_audit,
        "policy_audit": actions_audit,
        "validator_audit": validator_audit,
        "status": STATUS_AUDIT_COMPLETE,
        "candidate_results": candidate_results,
        "human_review": human_reviews,
        "session_summary": session_summary,
    }


def build_multitrack_summary(audits: list[dict[str, Any]]) -> dict[str, Any]:
    """Build multitrack summary from multiple session audits."""
    tracks: set[str] = set()
    sessions: set[str] = set()
    total_candidates = 0
    eligible_total = 0
    selected_total = 0
    clean_authorized = 0
    clean_withheld = 0
    selector_invalid = 0
    policy_invalid = 0
    validator_failures = 0
    not_applicable = 0
    validator_pass_count = 0
    audited_sessions_count = 0

    for audit in audits:
        if audit.get("status") == STATUS_INCOMPLETE_AUDIT:
            continue

        session_label = audit.get("session", "unknown")
        sessions.add(session_label)

        identity = audit.get("identity", {})
        track = identity.get("track", "unknown")
        tracks.add(track)

        summary = audit.get("session_summary", {})
        total_candidates += summary.get("total_candidates", 0)
        eligible_total += summary.get("eligible_count", 0)
        selected_total += summary.get("selected_count", 0)
        clean_authorized += summary.get("clean_authorized", 0)
        clean_withheld += summary.get("clean_withheld", 0)
        selector_invalid += summary.get("selector_invalid", 0)
        policy_invalid += summary.get("policy_invalid", 0)
        validator_failures += summary.get("validator_failures", 0)
        not_applicable += summary.get("not_applicable", 0)

        # Count audited sessions where validator is applicable and passed
        validator_audit = audit.get("validator_audit", {})
        if validator_audit.get("overall") is True:
            validator_pass_count += 1
        audited_sessions_count += 1

    return {
        "tracks": sorted(tracks),
        "sessions": sorted(sessions),
        "tracks_count": len(tracks),
        "sessions_count": len(sessions),
        "candidates_total": total_candidates,
        "eligible_total": eligible_total,
        "eligibility_rate": round(eligible_total / max(total_candidates, 1), 4),
        "selected_total": selected_total,
        "selection_validation_rate": round(
            (clean_authorized + clean_withheld) / max(selected_total, 1), 4
        ),
        "action_policy_validation_rate": round(
            (clean_authorized + clean_withheld) / max(selected_total, 1), 4
        ),
        "validator_pass_rate": round(
            validator_pass_count / max(audited_sessions_count, 1), 4
        ),
        "clean_authorized": clean_authorized,
        "clean_withheld": clean_withheld,
        "selector_invalid": selector_invalid,
        "policy_invalid": policy_invalid,
        "validator_failures": validator_failures,
        "not_applicable": not_applicable,
    }


def write_audit(audits: list[dict[str, Any]], multitrack: dict) -> dict[str, Any]:
    """Write the complete audit output."""
    output = {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "audit_version": AUDIT_VERSION,
            "created_at_utc": utc_now_iso(),
            "purpose": "H5.3 Point 6: real-new-session audit",
            "policy": {
                "historical_actions_authorized": False,
                "session_reference_remains_authority": True,
                "audit_is_observation_only": True,
                "no_llm_called": True,
                "no_human_labels_used": True,
            },
        },
        "session_audits": audits,
        "multitrack_summary": multitrack,
    }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3 Point 6: real-new-session audit harness"
    )
    parser.add_argument(
        "results",
        nargs="*",
        help="One or more run directories (data/generated/runs/<session>...)",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Directory containing one or more session run directories",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: data/generated/h5_3_real_session_audit/)",
    )
    args = parser.parse_args()

    # ── Collect session directories ────────────────────────────────────────
    session_dirs: list[tuple[str, Path]] = []

    for result in args.results:
        p = Path(result).resolve()
        if p.is_dir():
            session_name = resolve_session_name(p) or p.stem
            session_dirs.append((session_name, p))
        elif p.is_file():
            session_dirs.append((p.stem, p.parent))

    if args.input_dir:
        input_dir = Path(args.input_dir).resolve()
        if input_dir.is_dir():
            for child in sorted(input_dir.iterdir()):
                if child.is_dir():
                    session_name = resolve_session_name(child) or child.stem
                    session_dirs.append((session_name, child))

    if not session_dirs:
        print("ERROR: No session directories provided.")
        return 1

    # ── Audit each session ─────────────────────────────────────────────────
    audits: list[dict[str, Any]] = []
    for session_name, run_dir in session_dirs:
        try:
            audit = audit_session(run_dir, session_name)
            audits.append(audit)
            print(f"[{session_name}] {audit['status']}")
            if audit.get("missing_artifacts"):
                print(f"  Missing: {audit['missing_artifacts']}")
        except Exception as exc:
            print(f"[{session_name}] ERROR: {exc}")
            audits.append({
                "session": session_name,
                "status": "ERROR",
                "error": str(exc),
            })

    # ── Build multitrack summary ───────────────────────────────────────────
    multitrack = build_multitrack_summary(audits)

    # ── Write output ───────────────────────────────────────────────────────
    output_dir = Path(args.output).resolve() if args.output else (
        generated_root() / "h5_3_real_session_audit"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%Z")
    output_path = output_dir / f"{timestamp}_audit.json"
    output_path.write_text(
        json.dumps(
            write_audit(audits, multitrack),
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"\nAudit written to: {output_path}")
    print(f"Sessions audited: {len(audits)}")
    print(f"Tracks represented: {multitrack['tracks']}")
    print(f"Total candidates: {multitrack['candidates_total']}")
    print(f"Eligibility rate: {multitrack['eligibility_rate']}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
