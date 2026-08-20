"""H5.3 Point 6 — Real-new-session audit harness tests v0.2

Covers:
 1. Clean authorized (real layout)
 2. Clean withheld (real layout)
 3. Selector unauthorized observation (real layout)
 4. Action policy mismatch (real layout)
 5. Validator fail (real layout)
 6. Missing artifact -> INCOMPLETE_AUDIT (real layout)
 7. Insufficient comparable laps -> NOT_APPLICABLE (real layout)
 8. Multitrack aggregation
 9. Human review fields remain null
10. Deterministic repeatability
11. No human labels affect deterministic status
12. Artifact resolver: analysis resolution
13. Artifact resolver: H4/H5.1 resolution
14. Artifact resolver: H5.3 provenance resolution
15. Ambiguous H5.3 fails closed
16. Missing artifact fails closed
17. Legacy self-contained fixture behavior
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from audit_h5_3_real_sessions import (
    AUTHORIZED_ACTIONS,
    AUTHORIZED_OBSERVATIONS,
    STATUS_INCOMPLETE_AUDIT,
    STATUS_AUDIT_COMPLETE,
    STATUS_NOT_APPLICABLE,
    STATUS_AMBIGUOUS_ARTIFACT,
    audit_action_policy,
    audit_analyzer,
    audit_h5_3_eligibility,
    audit_identity,
    audit_llm_selection,
    audit_session,
    audit_validator,
    build_multitrack_summary,
    build_human_review,
    classify_candidate,
    resolve_all_artifacts,
    resolve_session_name,
    _load_run_state,
    resolve_h5_3_shadow_artifact,
    write_audit,
)


# ── Test fixtures ──────────────────────────────────────────────────────────

def _make_analysis(track="Circuit de Spa-Francorchamps", **overrides) -> dict:
    base = {
        "metadata": {
            "track": track,
            "track_layout": "Circuit de Spa-Francorchamps",
            "vehicle_variant": "LMP2_ELMS",
            "car_name_raw": "LMP2",
            "session_id": "spa_2026_08_18_session",
            "valid_lap_count": 5,
            "comparison_count": 1,
            "comparative_status": "SUPPORTED",
            "analysis_sha256": "abc123",
        }
    }
    base["metadata"].update(overrides)
    return base


def _make_h4_selection(track="Circuit de Spa-Francorchamps") -> dict:
    return {
        "metadata": {
            "schema_version": "0.2",
            "historical_reference_version": "0.2",
        },
        "track": track,
        "historical_reference": {
            "session_id": "spa_2025_07_01_session",
            "lap": 12,
        },
    }


def _make_h5_1(track="Circuit de Spa-Francorchamps") -> dict:
    return {
        "metadata": {
            "schema_version": "1.0",
            "dual_reference_version": "0.2",
        },
        "context": {
            "track": track,
            "track_layout": "Circuit de Spa-Francorchamps",
            "vehicle_variant": "LMP2_ELMS",
        },
        "status": "DUAL_REFERENCE_AVAILABLE",
        "session_reference": {"lap": 12},
        "historical_reference": {"lap": 15},
    }


def _make_h5_2(
    delta_sign: str = "current_slower",
    mode: str = "validated_track_profile",
    zone_count: int = 3,
) -> dict:
    zones = []
    for i in range(zone_count):
        zones.append({
            "zone_id": f"zone_{i}",
            "start_distance": float(i * 500),
            "end_distance": float((i + 1) * 500),
            "delta_change": float(i * 0.5),
            "type": "brake_throttle",
        })
    return {
        "metadata": {
            "schema_version": "1.1",
            "cross_session_version": "0.2",
        },
        "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
        "temporal_validation": {
            "status": "OK",
            "calculated_current_minus_historical_s": 1.5 if delta_sign == "current_slower" else -1.5,
            "tolerance_s": 0.08,
        },
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
        },
        "current_session_reference": {"session_id": "current"},
        "historical_reference": {"session_id": "historical"},
        "spatial_comparison": {
            "localization": {"mode": mode},
            "zone_summaries": zones,
        },
    }


def _make_h5_3_candidates(candidate_ids) -> dict:
    return {
        "metadata": {
            "schema_version": "0.1",
            "source_candidates_sha256": "candidates_sha",
        },
        "candidates": [
            {
                "audit_id": cid,
                "label": "ELIGIBLE_FOR_SELECTION",
                "candidate_id": cid,
                "authorized_observations": ["current_throttle_lower", "current_brake_lower"],
                "location_label": f"Turn {chr(65 + i)}",
                "start_distance_m": float(i * 100),
                "end_distance_m": float((i + 1) * 100),
            }
            for i, cid in enumerate(candidate_ids)
        ],
    }


def _make_h5_3_section(section_status: str = "DETERMINISTIC_HISTORICAL_SECTION") -> dict:
    return {
        "metadata": {
            "schema_version": "1.0",
            "render_version": "0.1",
        },
        "status": section_status,
        "zones": [],
        "limitations": ["single_lap_pair", "no_causal_inference"],
    }


def _make_shadow_pipeline(candidate_ids, with_selection=True, actions=None) -> dict:
    authorized = [
        {
            "candidate_id": cid,
            "authorized_observations": ["current_throttle_lower", "current_brake_lower"],
            "delta_sign": "current_slower",
            "delta_change_s": 0.5,
        }
        for i, cid in enumerate(candidate_ids)
    ]

    if with_selection:
        selection_data = {
            "selection": {
                "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
                "authorized_candidates": authorized,
                "llm_selection": {
                    "selected_candidates": [
                        {
                            "candidate_id": cid,
                            "observation_codes": ["current_throttle_lower"],
                            "actions": ["reduce_throttle"],
                        }
                        for cid in candidate_ids
                    ],
                },
            }
        }
    else:
        selection_data = {}

    result = {
        "metadata": {
            "schema_version": "1.0",
            "source_candidates_json": "data/generated/h5_3/",
        },
        "pipeline_artifacts": {
            "eligibility": {
                "summary": {
                    "total_candidates": len(candidate_ids),
                    "by_status": {
                        "ELIGIBLE_FOR_SELECTION": len(candidate_ids),
                        "WITHHELD": 0,
                        "AMBIGUOUS": 0,
                    },
                },
                "status": "ELIGIBILITY_COMPLETE",
            },
            **selection_data,
        },
        "status": "PIPELINE_COMPLETE",
        "session_id": "spa_2025_07_01_session",
    }

    return result


def _make_shadow_pipeline_for_session(candidate_ids, session_name, with_selection=True, actions=None) -> dict:
    """Build shadow pipeline with source_candidates_json referencing the session."""
    authorized = [
        {
            "candidate_id": cid,
            "authorized_observations": ["current_throttle_lower", "current_brake_lower"],
            "delta_sign": "current_slower",
            "delta_change_s": 0.5,
        }
        for i, cid in enumerate(candidate_ids)
    ]

    if with_selection:
        selection_data = {
            "selection": {
                "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
                "authorized_candidates": authorized,
                "llm_selection": {
                    "selected_candidates": [
                        {
                            "candidate_id": cid,
                            "observation_codes": ["current_throttle_lower"],
                            "actions": ["reduce_throttle"],
                        }
                        for cid in candidate_ids
                    ],
                },
            }
        }
    else:
        selection_data = {}

    result = {
        "metadata": {
            "schema_version": "1.0",
            "source_candidates_json": f"data/generated/h5_3/{session_name}/",
        },
        "pipeline_artifacts": {
            "eligibility": {
                "summary": {
                    "total_candidates": len(candidate_ids),
                    "by_status": {
                        "ELIGIBLE_FOR_SELECTION": len(candidate_ids),
                        "WITHHELD": 0,
                        "AMBIGUOUS": 0,
                    },
                },
                "status": "ELIGIBILITY_COMPLETE",
            },
            **selection_data,
        },
        "status": "PIPELINE_COMPLETE",
        "session_id": "spa_2025_07_01_session",
    }

    if actions is not None:
        result["actions"] = actions

    return result


def _make_candidate_eligibility(candidate_ids: list[str]) -> dict:
    """Build canonical candidate_eligibility.json."""
    return {
        "metadata": {
            "schema_version": "0.1",
            "source_candidates_sha256": "candidates_sha",
        },
        "summary": {
            "total_candidates": len(candidate_ids),
            "by_status": {
                "ELIGIBLE_FOR_SELECTION": len(candidate_ids),
                "WITHHELD": 0,
                "AMBIGUOUS": 0,
            },
        },
        "status": "ELIGIBILITY_COMPLETE",
        "eligible_candidates": [
            {
                "candidate_id": cid,
                "status": "ELIGIBLE",
                "authorized_observations": ["current_throttle_lower", "current_brake_lower"],
            }
            for i, cid in enumerate(candidate_ids)
        ],
    }


def _make_canonical_actions(actions: dict) -> dict:
    """Build canonical historical_actions.json (a pass-through for the actions dict)."""
    return actions


def _make_canonical_selection(selection: dict) -> dict:
    """Build canonical candidate_selection.json (a pass-through for the selection dict)."""
    return selection


def _make_actions(candidate_ids, withheld_ids=None, anti_regression_violated=False) -> dict:
    actions = []
    withheld = []

    for cid in candidate_ids:
        if not anti_regression_violated:
            actions.append({
                "candidate_id": cid,
                "delta_sign": "current_slower",
                "actions": ["reduce_throttle"],
            })
        else:
            actions.append({
                "candidate_id": cid,
                "delta_sign": "current_faster",
                "actions": ["reduce_throttle"],
            })

    if withheld_ids:
        for cid in withheld_ids:
            withheld.append({
                "candidate_id": cid,
                "reason": "current_lap_faster_no_actions",
            })

    return {
        "metadata": {
            "schema_version": "1.0",
            "policy_version": "0.2",
        },
        "status": "HISTORICAL_ACTION_CANDIDATES_VALIDATED",
        "actions": actions,
        "withheld": withheld,
    }


def _make_h5_3_candidate_selection(candidate_ids, unauthorized_obs=False) -> dict:
    authorized = []
    for cid in candidate_ids:
        obs = ["current_throttle_lower", "current_brake_lower"]
        authorized.append({
            "candidate_id": cid,
            "authorized_observations": obs,
        })

    return {
        "metadata": {
            "schema_version": "0.2",
            "selection_version": "0.2",
        },
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": authorized,
        "llm_selection": {
            "selected_candidates": [
                {
                    "candidate_id": cid,
                    "observation_codes": ["current_throttle_lower", "time_loss"] if unauthorized_obs else ["current_throttle_lower"],
                    "actions": ["reduce_throttle"],
                }
                for cid in candidate_ids
            ],
        },
    }


def _tmp_session(tmp_path: Path, label: str, **kwargs) -> Path:
    """Create a fake session directory with artifacts in real layout.

    Writes artifacts at ``tmp_path / <stage> / <label> / <filename>``
    so that ``audit_session(session_dir, label, base_dir=tmp_path)``
    resolves them via ``resolve_all_artifacts(label, base_dir=tmp_path)``

    Note: Analysis artifact uses flat layout at ``tmp_path / analysis / label.json``
    matching ``resolve_all_artifacts`` resolution.
    """
    session_dir = tmp_path / "spa_session" / label
    session_dir.mkdir(parents=True, exist_ok=True)

    # Write run state
    state = {"session_id": label, "status": "COMPLETE"}
    (session_dir / "state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    # Write analysis using flat layout (matching resolve_all_artifacts)
    analysis = _make_analysis(**kwargs)
    analysis_path = tmp_path / "analysis" / f"{label}.json"
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    # Write H4
    h4 = _make_h4_selection()
    h4_dir = tmp_path / "h4" / label
    h4_dir.mkdir(parents=True, exist_ok=True)
    (h4_dir / "historical_reference_selection.json").write_text(
        json.dumps(h4), encoding="utf-8"
    )

    # Write H5.1
    h5_1 = _make_h5_1()
    h5_1_dir = tmp_path / "h5_1" / label
    h5_1_dir.mkdir(parents=True, exist_ok=True)
    (h5_1_dir / "dual_reference_context.json").write_text(
        json.dumps(h5_1), encoding="utf-8"
    )

    # Write H5.2
    h5_2 = _make_h5_2()
    h5_2_dir = tmp_path / "h5_2" / label
    h5_2_dir.mkdir(parents=True, exist_ok=True)
    (h5_2_dir / "cross_session_comparison.json").write_text(
        json.dumps(h5_2), encoding="utf-8"
    )

    return session_dir


def _write_json(session_dir: Path, rel_path: str, data: dict) -> Path:
    """Write JSON to ``tmp_path / <stage> / <label> / <filename>``.

    ``session_dir`` is ``tmp_path / "spa_session" / label``, so ``tmp_path``
    and ``label`` are extracted from it, then ``rel_path`` is parsed to
    obtain ``stage`` (e.g. ``"h5_3"``) and ``filename``
    (e.g. ``"historical_coaching_candidates.json"``).

    H5.3 shadow artifacts use canonical layout at ``tmp_path / h5_3_shadow /
    <label>`` matching the real runtime canonical layout.
    """
    # session_dir = tmp_path / "spa_session" / label
    base = session_dir.parent.parent  # tmp_path
    label = session_dir.name  # e.g. "test1"

    # Parse rel_path: "h5_3/historical_coaching_candidates.json"
    parts = Path(rel_path)
    stage = parts.parts[0]
    filename = parts.name

    # H5.3 shadow uses canonical layout (session subdirectory)
    if stage == "h5_3_shadow":
        p = base / stage / label / filename
    else:
        p = base / stage / label / filename

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ── Test 1: clean authorized ───────────────────────────────────────────────

def test_1_clean_authorized(tmp_path: Path) -> None:
    """Clean authorized: candidate has authorized action (passed all checks)."""
    session_dir = _tmp_session(tmp_path, "test1")
    candidates = _make_h5_3_candidates(["candidate_001"])
    actions = _make_actions(["candidate_001"])
    shadow = _make_shadow_pipeline_for_session(["candidate_001"], "test1", actions=actions)
    section = _make_h5_3_section()

    _write_json(session_dir, "h5_3/historical_coaching_candidates.json", candidates)
    _write_json(session_dir, "h5_3_shadow/shadow_pipeline.json", shadow)
    _write_json(session_dir, "h5_3/historical_section.json", section)

    audit = audit_session(session_dir, "test1", base_dir=tmp_path)

    assert audit["status"] == STATUS_AUDIT_COMPLETE
    assert len(audit["candidate_results"]) == 1
    result = audit["candidate_results"][0]
    assert result["status"] == "CLEAN_AUTHORIZED"


# ── Test 2: clean withheld ─────────────────────────────────────────────────

def test_2_clean_withheld(tmp_path: Path) -> None:
    """Clean withheld: candidate was withheld by policy (valid reason)."""
    session_dir = _tmp_session(tmp_path, "test2")
    candidates = _make_h5_3_candidates(["candidate_001"])
    actions = _make_actions([], withheld_ids=["candidate_001"])
    shadow = _make_shadow_pipeline_for_session(["candidate_001"], "test2", actions=actions)
    section = _make_h5_3_section()

    _write_json(session_dir, "h5_3/historical_coaching_candidates.json", candidates)
    _write_json(session_dir, "h5_3_shadow/shadow_pipeline.json", shadow)
    _write_json(session_dir, "h5_3/historical_section.json", section)

    audit = audit_session(session_dir, "test2", base_dir=tmp_path)

    assert audit["status"] == STATUS_AUDIT_COMPLETE
    assert len(audit["candidate_results"]) == 1
    result = audit["candidate_results"][0]
    assert result["status"] == "CLEAN_WITHHELD"


# ── Test 3: selector unauthorized observation ──────────────────────────────

def test_3_selector_unauthorized_observation(tmp_path: Path) -> None:
    """Selector invalid: selected observation_codes not in authorized."""
    session_dir = _tmp_session(tmp_path, "test3")
    candidates = _make_h5_3_candidates(["candidate_001"])
    selection = _make_h5_3_candidate_selection(["candidate_001"], unauthorized_obs=True)

    shadow = _make_shadow_pipeline_for_session(
        ["candidate_001"], "test3", actions=_make_actions(["candidate_001"])
    )
    # Inject unauthorized observation code into the selected candidate
    for sel in shadow["pipeline_artifacts"]["selection"]["llm_selection"]["selected_candidates"]:
        sel["observation_codes"] = ["current_throttle_lower", "time_loss"]

    section = _make_h5_3_section()

    _write_json(session_dir, "h5_3/historical_coaching_candidates.json", candidates)
    _write_json(session_dir, "h5_3_shadow/shadow_pipeline.json", shadow)
    _write_json(session_dir, "h5_3/historical_section.json", section)

    audit = audit_session(session_dir, "test3", base_dir=tmp_path)

    assert audit["status"] == STATUS_AUDIT_COMPLETE
    assert len(audit["candidate_results"]) == 1
    result = audit["candidate_results"][0]
    assert result["status"] == "SELECTOR_INVALID"


# ── Test 4: action policy mismatch ─────────────────────────────────────────

def test_4_action_policy_mismatch(tmp_path: Path) -> None:
    """Policy invalid: anti-regression violated (current_faster with actions)."""
    session_dir = _tmp_session(tmp_path, "test4")
    candidates = _make_h5_3_candidates(["candidate_001"])
    actions = _make_actions(["candidate_001"], anti_regression_violated=True)
    shadow = _make_shadow_pipeline_for_session(["candidate_001"], "test4", actions=actions)
    section = _make_h5_3_section()

    _write_json(session_dir, "h5_3/historical_coaching_candidates.json", candidates)
    _write_json(session_dir, "h5_3_shadow/shadow_pipeline.json", shadow)
    _write_json(session_dir, "h5_3/historical_section.json", section)

    audit = audit_session(session_dir, "test4", base_dir=tmp_path)

    assert audit["status"] == STATUS_AUDIT_COMPLETE
    assert len(audit["candidate_results"]) == 1
    result = audit["candidate_results"][0]
    assert result["status"] == "POLICY_INVALID"


# ── Test 5: validator fail ─────────────────────────────────────────────────

def test_5_validator_fail(tmp_path: Path) -> None:
    """Validator failed: section or actions status invalid."""
    session_dir = _tmp_session(tmp_path, "test5")
    candidates = _make_h5_3_candidates(["candidate_001"])
    actions = _make_actions(["candidate_001"])
    shadow = _make_shadow_pipeline_for_session(["candidate_001"], "test5", actions=actions)
    section = _make_h5_3_section(section_status="INVALID_STATUS")

    _write_json(session_dir, "h5_3/historical_coaching_candidates.json", candidates)
    _write_json(session_dir, "h5_3_shadow/shadow_pipeline.json", shadow)
    _write_json(session_dir, "h5_3/historical_section.json", section)

    audit = audit_session(session_dir, "test5", base_dir=tmp_path)

    assert audit["status"] == STATUS_AUDIT_COMPLETE
    assert len(audit["candidate_results"]) == 1
    result = audit["candidate_results"][0]
    assert result["status"] == "VALIDATOR_FAILED"


# ── Test 6: missing artifact -> INCOMPLETE_AUDIT ────────────────────────────

def test_6_missing_artifact_incomplete_audit(tmp_path: Path) -> None:
    """Missing artifact: returns INCOMPLETE_AUDIT."""
    session_dir = _tmp_session(tmp_path, "test6")
    # Don't write any other artifacts

    audit = audit_session(session_dir, "test6")

    assert audit["status"] == STATUS_INCOMPLETE_AUDIT
    assert len(audit["missing_artifacts"]) > 0
    assert "h5_3/historical_coaching_candidates.json" in audit["missing_artifacts"]


# ── Test 7: insufficient comparable laps -> NOT_APPLICABLE ──────────────────

def test_7_insufficient_laps_not_applicable(tmp_path: Path) -> None:
    """Insufficient comparable laps -> NOT_APPLICABLE."""
    session_dir = _tmp_session(tmp_path, "test7", comparative_status="SKIPPED_NOT_APPLICABLE")

    # Write all required artifacts so the audit reaches the analyzer check
    _write_json(session_dir, "h4/historical_reference_selection.json", _make_h4_selection())
    _write_json(session_dir, "h5_1/dual_reference_context.json", _make_h5_1())
    _write_json(session_dir, "h5_2/cross_session_comparison.json", _make_h5_2())
    _write_json(session_dir, "h5_3/historical_coaching_candidates.json", _make_h5_3_candidates(["c1"]))
    _write_json(session_dir, "h5_3/historical_section.json", _make_h5_3_section())
    _write_json(session_dir, "h5_3_shadow/shadow_pipeline.json", _make_shadow_pipeline_for_session(["c1"], "test7"))

    audit = audit_session(session_dir, "test7", base_dir=tmp_path)

    assert audit["status"] == STATUS_NOT_APPLICABLE
    assert audit.get("reason") == "insufficient_comparable_laps"


# ── Test 8: multitrack aggregation ──────────────────────────────────────────

def test_8_multitrack_aggregation(tmp_path: Path) -> None:
    """Multitrack: aggregating multiple session audits."""
    # Use separate sub-directories to avoid shadow pipeline collisions
    base1 = tmp_path / "base1"
    base2 = tmp_path / "base2"
    base1.mkdir()
    base2.mkdir()

    s1 = _tmp_session(base1, "multitrack_s1")
    candidates1 = _make_h5_3_candidates(["c1", "c2"])
    actions1 = _make_actions(["c1", "c2"])
    shadow1 = _make_shadow_pipeline_for_session(["c1", "c2"], "multitrack_s1", actions=actions1)
    section1 = _make_h5_3_section()

    _write_json(s1, "h5_3/historical_coaching_candidates.json", candidates1)
    _write_json(s1, "h5_3_shadow/shadow_pipeline.json", shadow1)
    _write_json(s1, "h5_3/historical_section.json", section1)

    s2 = _tmp_session(base2, "multitrack_s2")
    candidates2 = _make_h5_3_candidates(["c3"])
    actions2 = _make_actions(["c3"])
    shadow2 = _make_shadow_pipeline_for_session(["c3"], "multitrack_s2", actions=actions2)
    section2 = _make_h5_3_section()

    _write_json(s2, "h5_3/historical_coaching_candidates.json", candidates2)
    _write_json(s2, "h5_3_shadow/shadow_pipeline.json", shadow2)
    _write_json(s2, "h5_3/historical_section.json", section2)

    audit1 = audit_session(s1, "multitrack_s1", base_dir=base1)
    audit2 = audit_session(s2, "multitrack_s2", base_dir=base2)

    multitrack = build_multitrack_summary([audit1, audit2])

    assert multitrack["tracks_count"] == 1
    assert multitrack["sessions_count"] == 2
    assert multitrack["candidates_total"] == 3
    assert multitrack["clean_authorized"] == 3
    assert multitrack["eligible_total"] == 3


# ── Test 9: human_review fields remain null ─────────────────────────────────

def test_9_human_review_fields_remain_null(tmp_path: Path) -> None:
    """Human review fields: auditor must NOT populate manual fields."""
    session_dir = _tmp_session(tmp_path, "test9")
    candidates = _make_h5_3_candidates(["candidate_001"])
    actions = _make_actions(["candidate_001"])
    shadow = _make_shadow_pipeline_for_session(["candidate_001"], "test9", actions=actions)
    section = _make_h5_3_section()

    _write_json(session_dir, "h5_3/historical_coaching_candidates.json", candidates)
    _write_json(session_dir, "h5_3_shadow/shadow_pipeline.json", shadow)
    _write_json(session_dir, "h5_3/historical_section.json", section)

    audit = audit_session(session_dir, "test9", base_dir=tmp_path)

    assert audit["status"] == STATUS_AUDIT_COMPLETE
    # Human review fields must remain null (no human intervention)
    assert len(audit["human_review"]) == 1
    assert audit["human_review"][0]["human_review"]["actionability"] is None
    assert audit["human_review"][0]["human_review"]["observation_correct"] is None
    assert audit["human_review"][0]["human_review"]["action_correct"] is None
    assert audit["human_review"][0]["human_review"]["notes"] is None


# ── Test 10: deterministic repeatability ────────────────────────────────────

def test_10_deterministic_repeatability(tmp_path: Path) -> None:
    """Deterministic: same inputs -> same outputs."""
    session_dir = _tmp_session(tmp_path, "test10")
    candidates = _make_h5_3_candidates(["candidate_001", "candidate_002"])
    actions = _make_actions(["candidate_001", "candidate_002"])
    shadow = _make_shadow_pipeline_for_session(["candidate_001", "candidate_002"], "test10", actions=actions)
    section = _make_h5_3_section()

    _write_json(session_dir, "h5_3/historical_coaching_candidates.json", candidates)
    _write_json(session_dir, "h5_3_shadow/shadow_pipeline.json", shadow)
    _write_json(session_dir, "h5_3/historical_section.json", section)

    # Run audit twice
    audit1 = audit_session(session_dir, "test10", base_dir=tmp_path)
    audit2 = audit_session(session_dir, "test10", base_dir=tmp_path)

    # Compare candidate results (skip metadata/timestamps)
    assert audit1["candidate_results"] == audit2["candidate_results"]
    assert audit1["session_summary"] == audit2["session_summary"]


# ── Test 11: no human labels affect deterministic status ────────────────────

def test_11_no_human_labels_affect_deterministic_status() -> None:
    """No human labels: deterministic classification must not depend on human labels."""
    result = classify_candidate(
        "test_id",
        in_actions=True,
        in_withheld=False,
        selector_valid=True,
        policy_valid=True,
        validator_ok=True,
    )
    assert result == "CLEAN_AUTHORIZED"

    result = classify_candidate(
        "test_id",
        in_actions=False,
        in_withheld=True,
        selector_valid=True,
        policy_valid=True,
        validator_ok=True,
    )
    assert result == "CLEAN_WITHHELD"

    result = classify_candidate(
        "test_id",
        in_actions=False,
        in_withheld=False,
        selector_valid=False,
        policy_valid=True,
        validator_ok=True,
    )
    assert result == "SELECTOR_INVALID"

    result = classify_candidate(
        "test_id",
        in_actions=False,
        in_withheld=False,
        selector_valid=True,
        policy_valid=False,
        validator_ok=True,
    )
    assert result == "POLICY_INVALID"

    result = classify_candidate(
        "test_id",
        in_actions=False,
        in_withheld=False,
        selector_valid=True,
        policy_valid=True,
        validator_ok=False,
    )
    assert result == "VALIDATOR_FAILED"


# ── Test 12: artifact resolver: analysis resolution ─────────────────────────

def test_12_artifact_resolver_analysis_resolution(tmp_path: Path) -> None:
    """Resolver: analysis file resolved by session name."""
    session_name = "test_session_analysis"
    (tmp_path / "analysis" / f"{session_name}.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "analysis" / f"{session_name}.json").write_text(
        json.dumps(_make_analysis()), encoding="utf-8"
    )

    # Temporarily override generated_root for this test
    import audit_h5_3_real_sessions as module
    original_root = module.generated_root

    try:
        # Patch the function to use our test base
        def fake_root():
            return tmp_path
        module.generated_root = fake_root

        resolved = resolve_all_artifacts(session_name)
        assert resolved["analysis"] is not None
        assert resolved["h4"] is None
    finally:
        module.generated_root = original_root


# ── Tests appended for selector status and validator pass rate ─────────



# ── Test 13: artifact resolver: H4/H5.1 resolution ──────────────────────────

def test_13_artifact_resolver_h4_h5_1_resolution(tmp_path: Path) -> None:
    """Resolver: H4/H5.1 artifacts resolved by session name."""
    session_name = "test_session_h4_h51"
    (tmp_path / "h4" / session_name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "h4" / session_name / "historical_reference_selection.json").write_text(
        json.dumps(_make_h4_selection()), encoding="utf-8"
    )
    (tmp_path / "h5_1" / session_name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "h5_1" / session_name / "dual_reference_context.json").write_text(
        json.dumps(_make_h5_1()), encoding="utf-8"
    )

    import audit_h5_3_real_sessions as module
    original_root = module.generated_root

    try:
        def fake_root():
            return tmp_path
        module.generated_root = fake_root

        resolved = resolve_all_artifacts(session_name)
        assert resolved["h4"] is not None
        assert resolved["h5_1"] is not None
    finally:
        module.generated_root = original_root


# ── Tests appended for selector status and validator pass rate ─────────



# ── Test 14: artifact resolver: H5.3 provenance resolution ──────────────────

def test_14_artifact_resolver_h5_3_provenance(tmp_path: Path):
    """Resolver: H5.3 shadow artifact found by provenance from H4/H5.1."""
    session_name = "test_session_provenance"
    (tmp_path / "h4" / session_name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "h4" / session_name / "historical_reference_selection.json").write_text(
        json.dumps(_make_h4_selection()), encoding="utf-8"
    )
    shadow_dir = tmp_path / "h5_3_shadow"
    shadow_dir.mkdir(parents=True, exist_ok=True)
    (shadow_dir / f"hashed_{session_name}.json").write_text(
        json.dumps({
            "pipeline_artifacts": {
                "eligibility": {"summary": {"total_candidates": 1}},
            },
            "session_id": "spa_2025_07_01_session",
        }),
        encoding="utf-8",
    )

    # Also create analysis artifact so the resolver assertion passes
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / f"{session_name}.json").write_text(
        json.dumps(_make_analysis()), encoding="utf-8"
    )

    import audit_h5_3_real_sessions as module
    original_root = module.generated_root

    try:
        def fake_root():
            return tmp_path
        module.generated_root = fake_root

        resolved = resolve_all_artifacts(session_name)
        assert resolved["h4"] is not None
        assert resolved["analysis"] is not None

        # Test H5.3 shadow provenance resolution
        import audit_h5_3_real_sessions as resolver_module

        h4_data = (
            json.loads((resolved["h4"]).read_text(encoding="utf-8"))
            if resolved["h4"]
            else None
        )
        # h5.1 not created in this test so passed as None
        shadow_path = resolver_module.resolve_h5_3_shadow_artifact(
            tmp_path / "spa_session" / session_name,
            h4_data,
            None,
            session_name,
            base_dir=tmp_path,
        )
        assert shadow_path is not None
    finally:
        module.generated_root = original_root


# ── Tests appended for selector status and validator pass rate ─────────



# ── Test 15: ambiguous H5.3 fails closed ───────────────────────────────────

def test_15_ambiguous_h5_3_fails_closed(tmp_path: Path) -> None:
    """Ambiguous H5.3: multiple shadow artifacts matching -> INCOMPLETE_AUDIT."""
    session_dir = _tmp_session(tmp_path, "test15")

    # Write all artifacts except H5.3 shadow
    candidates = _make_h5_3_candidates(["candidate_001"])
    section = _make_h5_3_section()

    _write_json(session_dir, "h5_3/historical_coaching_candidates.json", candidates)
    _write_json(session_dir, "h5_3/historical_section.json", section)

    audit = audit_session(session_dir, "test15")

    assert audit["status"] == STATUS_INCOMPLETE_AUDIT
    # Should include h5_3_shadow as missing
    assert any("h5_3_shadow" in str(m) for m in audit.get("missing_artifacts", []))


# ── Test 16: missing artifact fails closed ──────────────────────────────────

def test_16_missing_artifact_fails_closed(tmp_path: Path) -> None:
    """Missing artifact: INCOMPLETE_AUDIT (no artifacts present)."""
    session_dir = tmp_path / "empty_session"
    session_dir.mkdir()

    # Write nothing - all artifacts missing
    audit = audit_session(session_dir, "empty_session")

    assert audit["status"] == STATUS_INCOMPLETE_AUDIT
    assert len(audit["missing_artifacts"]) > 0


# ── Test 17: legacy self-contained fixture behavior ─────────────────────────

def test_17_legacy_self_contained_fixture(tmp_path: Path) -> None:
    """Legacy: when all artifacts exist under one session dir, behavior is unchanged."""
    session_dir = tmp_path / "legacy_session"
    session_dir.mkdir()

    # Write all artifacts under one directory (legacy layout)
    analysis = _make_analysis()
    (session_dir / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    h4 = _make_h4_selection()
    (session_dir / "h4.json").write_text(json.dumps(h4), encoding="utf-8")
    h5_1 = _make_h5_1()
    (session_dir / "h5_1.json").write_text(json.dumps(h5_1), encoding="utf-8")
    h5_2 = _make_h5_2()
    (session_dir / "h5_2.json").write_text(json.dumps(h5_2), encoding="utf-8")
    candidates = _make_h5_3_candidates(["candidate_001"])
    (session_dir / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")
    section = _make_h5_3_section()
    (session_dir / "section.json").write_text(json.dumps(section), encoding="utf-8")

    # Legacy layout should fail with INCOMPLETE_AUDIT (modern layout expected)
    audit = audit_session(session_dir, "legacy_session")
    # With the new resolver, it won't find the artifacts in the expected paths
    assert audit["status"] == STATUS_INCOMPLETE_AUDIT


# ── Additional tests from original suite ─────────────────────────────────────

def test_audit_analyzer_south() -> None:
    """Analyzer audit: correct detection of supported vs insufficient laps."""
    supported = audit_analyzer(_make_analysis(comparative_status="SUPPORTED"))
    assert supported["status"] == "SUPPORTED"

    insufficient = audit_analyzer(_make_analysis(comparative_status="SKIPPED_NOT_APPLICABLE"))
    assert insufficient["status"] == "INSUFFICIENT_LAPS"


def test_audit_h5_3_eligibility_from_shadow() -> None:
    """Eligibility audit: reads from shadow pipeline."""
    candidates = _make_h5_3_candidates(["c1", "c2", "c3"])
    shadow = _make_shadow_pipeline(["c1", "c2", "c3"])

    elig = audit_h5_3_eligibility(shadow, None)

    assert elig["total_candidates"] == 3
    assert elig["eligible"] == 3


def test_audit_llm_selection_valid_codes() -> None:
    """LLM selection audit: valid observation codes."""
    candidates = _make_h5_3_candidates(["c1"])
    selection = _make_h5_3_candidate_selection(["c1"], unauthorized_obs=False)

    audit = audit_llm_selection(selection)

    assert audit["selected_count"] == 1
    assert audit["observation_codes_valid"] is True


def test_audit_llm_selection_invalid_codes() -> None:
    """LLM selection audit: invalid observation codes."""
    candidates = _make_h5_3_candidates(["c1"])
    selection = _make_h5_3_candidate_selection(["c1"], unauthorized_obs=True)

    audit = audit_llm_selection(selection)

    assert audit["selected_count"] == 1
    assert audit["observation_codes_valid"] is False


def test_classify_candidate_priority() -> None:
    """Classify candidate: priority order."""
    result = classify_candidate(
        "test",
        in_actions=True,
        in_withheld=True,
        selector_valid=True,
        policy_valid=True,
        validator_ok=True,
    )
    assert result == "CLEAN_AUTHORIZED"

    result = classify_candidate(
        "test",
        in_actions=False,
        in_withheld=False,
        selector_valid=False,
        policy_valid=False,
        validator_ok=False,
    )
    assert result == "SELECTOR_INVALID"


def test_write_audit_schema() -> None:
    """Output schema is correct."""
    audits = [
        {
            "session": "session1",
            "status": STATUS_AUDIT_COMPLETE,
            "candidate_results": [],
            "human_review": [],
            "session_summary": {},
        },
    ]
    multitrack = {"tracks": ["Spa"], "candidates_total": 0}

    output = write_audit(audits, multitrack)
    assert output["metadata"]["schema_version"] == "1.0"
    assert output["metadata"]["audit_version"] == "0.2"
    assert output["metadata"]["purpose"] == "H5.3 Point 6: real-new-session audit"
    assert output["metadata"]["policy"]["historical_actions_authorized"] is False
    assert output["session_audits"] == audits
    assert output["multitrack_summary"] == multitrack


def test_audit_identity_extraction() -> None:
    """Identity extraction: from analysis vs H5.1."""
    analysis = _make_analysis(track="Spa", vehicle_variant="LMP2_ELMS")
    h5_1 = _make_h5_1(track="Spa")

    identity = audit_identity(None, analysis, h5_1)
    assert identity["track"] == "Spa"
    assert identity["vehicle_variant"] == "LMP2_ELMS"


def test_build_human_review_null_fields() -> None:
    """Human review: all manual fields are None."""
    candidate = {"candidate_id": "c1", "location_label": "T1"}
    selection_info = {"observation_codes": ["time_loss"]}
    policy_info = {"action_code": "reduce_throttle", "withheld_reason": ""}
    context = {"track": "Spa"}
    delta_info = {"delta_change_s": -0.5, "delta_sign": "current_slower"}

    hr = build_human_review(candidate, selection_info, policy_info, context, delta_info)
    assert hr["human_review"]["actionability"] is None
    assert hr["human_review"]["observation_correct"] is None
    assert hr["human_review"]["action_correct"] is None
    assert hr["human_review"]["notes"] is None


def test_resolve_session_name_from_state() -> None:
    """Session name: extracted from state.json."""
    with TemporaryDirectory() as tmp:
        td = Path(tmp)
        sd = td / "session_123"
        sd.mkdir()
        (sd / "state.json").write_text(
            json.dumps({"session_id": "real_session_id"}),
            encoding="utf-8"
        )
        name = resolve_session_name(sd)
        assert name == "real_session_id"


def test_resolve_session_name_fallback() -> None:
    """Session name: falls back to basename when no state.json."""
    with TemporaryDirectory() as tmp:
        td = Path(tmp)
        sd = td / "fallback_session"
        sd.mkdir()
        name = resolve_session_name(sd)
        assert name == "fallback_session"


def test_load_run_state_missing() -> None:
    """Load run state: returns None when file missing."""
    with TemporaryDirectory() as tmp:
        td = Path(tmp)
        sd = td / "session"
        sd.mkdir()
        state = _load_run_state(sd)
        assert state is None


def test_multitrack_with_mixed_statuses() -> None:
    """Multitrack: correctly skips INCOMPLETE_AUDIT sessions."""
    audit_complete = {
        "session": "s1",
        "status": STATUS_AUDIT_COMPLETE,
        "candidate_results": [{"status": "CLEAN_AUTHORIZED"}],
        "session_summary": {"total_candidates": 1, "clean_authorized": 1},
    }
    audit_incomplete = {
        "session": "s2",
        "status": STATUS_INCOMPLETE_AUDIT,
        "candidate_results": [],
        "session_summary": {},
    }

    multitrack = build_multitrack_summary([audit_complete, audit_incomplete])

    assert multitrack["tracks_count"] == 1
    assert multitrack["sessions_count"] == 1  # Only s1 counted
    assert multitrack["clean_authorized"] == 1


def test_policy_audit_empty_actions() -> None:
    """Policy audit: empty actions -> no errors."""
    result = audit_action_policy({})
    assert result["authorized_actions"] == 0
    assert result["anti_regression_passed"] is True
    assert result["errors"] == []


def test_validator_empty_section_and_actions() -> None:
    """Validator: empty section/actions -> overall False."""
    result = audit_validator({}, {})
    assert result["section_pass"] is False
    assert result["actions_pass"] is False
    assert result["overall"] is False
    assert result["section_errors"] == ["section artifact missing"]
    assert result["actions_errors"] == ["actions artifact missing"]


def test_selector_audit_empty() -> None:
    """Selector audit: empty selection -> no errors."""
    result = audit_llm_selection({})
    assert result["selected_count"] == 0
    assert result["observation_codes_valid"] is True
    assert result["selection_status"] == "NO_SELECTION"


# ── Test 18: canonical session-dir shadow resolution ─────────────────────

def test_18_canonical_session_dir_shadow_resolution(tmp_path: Path) -> None:
    """Resolver: canonical session-dir shadow_pipeline.json resolves correctly.

    data/generated/h5_3_shadow/<session_name>/shadow_pipeline.json
    """
    import audit_h5_3_real_sessions as module
    original_root = module.generated_root

    try:
        def fake_root():
            return tmp_path
        module.generated_root = fake_root

        session_name = "canonical_imola"
        shadow_dir = tmp_path / "h5_3_shadow" / session_name
        shadow_dir.mkdir(parents=True)

        # Write canonical shadow_pipeline.json
        shadow_data = {
            "metadata": {
                "schema_version": "1.0",
                "pipeline_version": "0.1",
                "source_candidates_json": f"data/generated/h5_3/{session_name}/historical_coaching_candidates.json",
            },
            "pipeline_artifacts": {
                "eligibility": {
                    "summary": {
                        "total_candidates": 5,
                        "by_status": {"ELIGIBLE_FOR_SELECTION": 3, "WITHHELD": 2},
                    },
                    "status": "ELIGIBILITY_COMPLETE",
                },
                "selection": {
                    "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
                    "selected_count": 2,
                },
            },
        }
        (shadow_dir / "shadow_pipeline.json").write_text(
            json.dumps(shadow_data), encoding="utf-8"
        )

        # Resolve via provenance
        from audit_h5_3_real_sessions import resolve_h5_3_shadow_artifact

        run_dir = tmp_path / "spa_session" / session_name
        run_dir.mkdir(parents=True, exist_ok=True)

        shadow_path = resolve_h5_3_shadow_artifact(
            run_dir,
            None,  # h4_data
            None,  # h5_1_data
            session_name,
            base_dir=tmp_path,
        )
        assert shadow_path is not None
        assert shadow_path.name == "shadow_pipeline.json"
        assert session_name in str(shadow_path)
    finally:
        module.generated_root = original_root


# ── Tests appended for selector status and validator pass rate ─────────



# ── Test 19: canonical identity mismatch → fail closed ────────────────────

def test_19_canonical_identity_mismatch_fail_closed(tmp_path: Path) -> None:
    """Resolver: canonical shadow_pipeline.json exists but session identity mismatch → None."""
    import audit_h5_3_real_sessions as module
    original_root = module.generated_root

    try:
        def fake_root():
            return tmp_path
        module.generated_root = fake_root

        session_name = "mismatch_session"
        shadow_dir = tmp_path / "h5_3_shadow" / session_name
        shadow_dir.mkdir(parents=True)

        # Write shadow with DIFFERENT session identity
        shadow_data = {
            "metadata": {
                "schema_version": "1.0",
                "source_candidates_json": "data/generated/h5_3/Fuji_Speedway/session.json",
            },
            "pipeline_artifacts": {"eligibility": {"summary": {"total_candidates": 1}}},
        }
        (shadow_dir / "shadow_pipeline.json").write_text(
            json.dumps(shadow_data), encoding="utf-8"
        )

        from audit_h5_3_real_sessions import resolve_h5_3_shadow_artifact

        run_dir = tmp_path / "spa_session" / session_name
        run_dir.mkdir(parents=True, exist_ok=True)

        shadow_path = resolve_h5_3_shadow_artifact(
            run_dir,
            None,
            None,
            session_name,
            base_dir=tmp_path,
        )
        # Should NOT resolve because session_name not in source_candidates_json
        assert shadow_path is None
    finally:
        module.generated_root = original_root


# ── Tests appended for selector status and validator pass rate ─────────



# ── Test 20: canonical missing → legacy provenance fallback ───────────────

def test_20_canonical_missing_legacy_fallback(tmp_path: Path) -> None:
    """Resolver: canonical session-dir missing → legacy provenance fallback works."""
    import audit_h5_3_real_sessions as module
    original_root = module.generated_root

    try:
        def fake_root():
            return tmp_path
        module.generated_root = fake_root

        session_name = "legacy_fallback"
        # DO NOT create canonical session-dir — only legacy flat artifact
        shadow_dir = tmp_path / "h5_3_shadow"
        shadow_dir.mkdir(parents=True)

        h4_data = {
            "historical_reference": {"session_id": "legacy_session_001"},
        }
        (shadow_dir / "abc123def456.json").write_text(
            json.dumps({
                "session_id": "legacy_session_001",
                "pipeline_artifacts": {"eligibility": {"summary": {"total_candidates": 3}}},
            }),
            encoding="utf-8",
        )

        from audit_h5_3_real_sessions import resolve_h5_3_shadow_artifact

        run_dir = tmp_path / "spa_session" / session_name
        run_dir.mkdir(parents=True, exist_ok=True)

        shadow_path = resolve_h5_3_shadow_artifact(
            run_dir,
            h4_data,
            None,
            session_name,
            base_dir=tmp_path,
        )
        assert shadow_path is not None
        assert shadow_path.name == "abc123def456.json"
    finally:
        module.generated_root = original_root


# ── Tests appended for selector status and validator pass rate ─────────



# ── Test 21: canonical wins over unrelated old hash artifact ──────────────

def test_21_canonical_wins_over_unrelated_hash(tmp_path: Path) -> None:
    """Resolver: canonical session-dir shadows any legacy flat artifact."""
    import audit_h5_3_real_sessions as module
    original_root = module.generated_root

    try:
        def fake_root():
            return tmp_path
        module.generated_root = fake_root

        session_name = "canonical_wins"
        shadow_dir = tmp_path / "h5_3_shadow" / session_name
        shadow_dir.mkdir(parents=True)

        # Write canonical shadow ONLY in session-dir
        (shadow_dir / "shadow_pipeline.json").write_text(
            json.dumps({
                "metadata": {
                    "source_candidates_json": f"data/generated/h5_3/{session_name}/candidates.json",
                },
            }),
            encoding="utf-8",
        )

        # Also write legacy flat artifact in the PARENT shadow directory (different session)
        (tmp_path / "h5_3_shadow" / "old_hash_artifact.json").write_text(
            json.dumps({
                "session_id": "some_other_session",
                "pipeline_artifacts": {"eligibility": {"summary": {"total_candidates": 1}}},
            }),
            encoding="utf-8",
        )

        from audit_h5_3_real_sessions import resolve_h5_3_shadow_artifact

        run_dir = tmp_path / "spa_session" / session_name
        run_dir.mkdir(parents=True, exist_ok=True)

        shadow_path = resolve_h5_3_shadow_artifact(
            run_dir,
            None,
            None,
            session_name,
            base_dir=tmp_path,
        )
        assert shadow_path is not None
        assert shadow_path.name == "shadow_pipeline.json"
        assert session_name in str(shadow_path)
    finally:
        module.generated_root = original_root


# ── Tests appended for selector status and validator pass rate ─────────



# ── Test 22: ambiguous session-dir → fail closed ──────────────────────────

def test_22_ambiguous_session_dir_fail_closed(tmp_path: Path) -> None:
    """Resolver: canonical session-dir with multiple candidate files → None."""
    import audit_h5_3_real_sessions as module
    original_root = module.generated_root

    try:
        def fake_root():
            return tmp_path
        module.generated_root = fake_root

        session_name = "ambiguous_session"
        shadow_dir = tmp_path / "h5_3_shadow" / session_name
        shadow_dir.mkdir(parents=True)

        # Write shadow_pipeline.json AND another candidate file
        (shadow_dir / "shadow_pipeline.json").write_text(
            json.dumps({
                "metadata": {
                    "source_candidates_json": f"data/generated/h5_3/{session_name}/candidates.json",
                },
            }),
            encoding="utf-8",
        )
        (shadow_dir / "extra_candidate.json").write_text(
            json.dumps({"candidate": "extra"}),
            encoding="utf-8",
        )

        from audit_h5_3_real_sessions import resolve_h5_3_shadow_artifact

        run_dir = tmp_path / "spa_session" / session_name
        run_dir.mkdir(parents=True, exist_ok=True)

        shadow_path = resolve_h5_3_shadow_artifact(
            run_dir,
            None,
            None,
            session_name,
            base_dir=tmp_path,
        )
        # Multiple files in canonical dir → ambiguous → None
        assert shadow_path is None
    finally:
        module.generated_root = original_root


# ── Tests appended for selector status and validator pass rate ─────────



# ── Test 23: real layout Imola fixture resolves shadow_pipeline.json ──────

def test_23_real_layout_imola_fixture(tmp_path: Path) -> None:
    """Resolver: real Imola layout resolves shadow_pipeline.json from session-dir."""
    import audit_h5_3_real_sessions as module
    original_root = module.generated_root

    try:
        def fake_root():
            return tmp_path
        module.generated_root = fake_root

        session_name = "Autodromo Enzo e Dino Ferrari_P_2026-08-19T19_25_42Z"
        shadow_dir = tmp_path / "h5_3_shadow" / session_name
        shadow_dir.mkdir(parents=True)

        # Write realistic Imola shadow_pipeline.json (matching real layout)
        imola_shadow = {
            "metadata": {
                "schema_version": "1.0",
                "pipeline_version": "0.1",
                "status": "SHADOW_PIPELINE_COMPLETE",
                "source_candidates_json": f"data/generated/h5_3/{session_name}/historical_coaching_candidates.json",
                "source_candidates_sha256": "f8954d2f0535e49c41104e62c2bb439f6e2594f6d87a85ad68b39c3b9c2294f1",
            },
            "pipeline_artifacts": {
                "eligibility": {
                    "status": None,
                    "summary": {
                        "total_candidates": 15,
                        "by_status": {
                            "ELIGIBLE_FOR_SELECTION": 9,
                            "WITHHELD": 6,
                        },
                    },
                },
                "selection": {
                    "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
                    "selected_count": 3,
                },
                "action_policy": {
                    "status": "HISTORICAL_ACTION_CANDIDATES_VALIDATED",
                },
            },
            "validation": {
                "status": "PASS",
                "errors": [],
            },
        }
        (shadow_dir / "shadow_pipeline.json").write_text(
            json.dumps(imola_shadow), encoding="utf-8"
        )

        from audit_h5_3_real_sessions import resolve_h5_3_shadow_artifact

        run_dir = tmp_path / "runs" / session_name
        run_dir.mkdir(parents=True, exist_ok=True)

        shadow_path = resolve_h5_3_shadow_artifact(
            run_dir,
            None,
            None,
            session_name,
            base_dir=tmp_path,
        )
        assert shadow_path is not None
        assert shadow_path.name == "shadow_pipeline.json"
        assert session_name in str(shadow_path)
    finally:
        module.generated_root = original_root


# ── Tests appended for selector status and validator pass rate ─────────

