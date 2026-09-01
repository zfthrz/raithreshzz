from __future__ import annotations

import json
from pathlib import Path

import track_readiness as tr


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _profile(
    path: Path,
    *,
    track: str = "Spa",
    layout: str = "Spa",
    status: str = "VALIDATED_MULTI_SESSION",
    turns: bool = True,
    profile_id: str = "spa-v0.3",
) -> None:
    _write_json(
        path,
        {
            "profile_id": profile_id,
            "track": track,
            "layout": layout,
            "status": status,
            "turns": [{"start_m": 1, "end_m": 2}] if turns else [],
        },
    )


def _runtime_session(
    root: Path,
    *,
    run_name: str = "run1",
    track: str = "Spa",
    layout: str | None = "Spa",
    variant: str = "LMP2_ELMS",
    h4: bool = False,
    evidence: bool = False,
) -> None:
    state = root / run_name / "state.json"
    analysis = root / run_name / "analysis.json"
    metadata = {
        "track": track,
        "vehicle_identity": {"variant": variant},
    }
    if layout is not None:
        metadata["lmu_track_layout"] = layout

    _write_json(analysis, {"metadata": metadata})

    stages = {"analyze": {"status": "RUN", "output": str(analysis)}}
    if h4:
        stages["h4"] = {"status": "RUN", "output": "h4.json"}
    if evidence:
        stages["historical_telemetry_evidence"] = {
            "status": "RUN",
            "output": "data/generated/historical_telemetry_evidence/x.json",
        }
    _write_json(state, {"database": f"{run_name}.duckdb", "stages": stages})


def _calibration(**overrides) -> dict:
    row = {
        "track": "Spa",
        "track_layout": "Spa",
        "vehicle_variant": "LMP2_ELMS",
        "sessions": 2,
        "labeled_pairs": 24,
        "queue_pairs": 24,
        "evaluation_status": "NO_EVALUATION",
        "evaluation_pairs": 0,
        "matcher_status": "NO_CALIBRATION_FOR_CONTEXT",
    }
    row.update(overrides)
    return row


def _roots(tmp_path: Path, monkeypatch, rows: list[dict]):
    profiles = tmp_path / "track_profiles"
    runs = tmp_path / "runs"
    batches = tmp_path / "batches"
    profiles.mkdir()
    runs.mkdir()
    batches.mkdir()
    monkeypatch.setattr(tr, "load_calibration_summary", lambda _root: {"rows": rows})
    monkeypatch.setattr(tr, "discover_h3_import_readiness", lambda **_kwargs: {})
    return profiles, runs, batches


def test_missing_profile_is_needs_profile(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [_calibration()])
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["overall_status"] == "NEEDS_PROFILE"


def test_profile_without_context_is_visible_track_level(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(profiles / "spa_v0_3.json")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    track = payload["tracks"][0]
    assert track["profile_status"] == "VALIDATED"
    assert track["context_count"] == 0


def test_single_session_profile_is_reported_as_provisional(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(
        profiles / "spa_v0_1.json",
        status="VALIDATED_SINGLE_SESSION",
        profile_id="spa-v0.1",
    )
    _runtime_session(runs)

    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )

    row = payload["rows"][0]
    assert row["profile_status"] == "PROVISIONAL_SINGLE_SESSION"
    assert row["overall_status"] == "NEEDS_INDEPENDENT_PROFILE_SESSION"
    assert row["next_action"]["code"] == "RECORD_INDEPENDENT_PROFILE_SESSION"
    assert payload["tracks"][0]["profile_status"] == "PROVISIONAL_SINGLE_SESSION"


def test_sessions_without_queue_need_calibration_queue(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(profiles / "spa_v0_3.json")
    _runtime_session(runs)
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["overall_status"] == "NEEDS_CALIBRATION_QUEUE"


def test_zero_pair_calibration_row_still_needs_queue(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(
        tmp_path, monkeypatch, [_calibration(labeled_pairs=0, queue_pairs=0)]
    )
    _profile(profiles / "spa_v0_3.json")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["overall_status"] == "NEEDS_CALIBRATION_QUEUE"


def test_incomplete_queue_needs_labels(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(
        tmp_path, monkeypatch, [_calibration(labeled_pairs=15, queue_pairs=24)]
    )
    _profile(profiles / "spa_v0_3.json")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    row = payload["rows"][0]
    assert row["overall_status"] == "NEEDS_LABELS"
    assert row["next_action"]["current"] == 15
    assert row["next_action"]["required"] == 24


def test_complete_queue_without_evaluation_needs_evaluation(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [_calibration()])
    _profile(profiles / "spa_v0_3.json")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["overall_status"] == "NEEDS_EVALUATION"


def test_candidate_calibrated_requests_manual_review(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(
        tmp_path,
        monkeypatch,
        [_calibration(evaluation_status="CANDIDATE_CALIBRATED", evaluation_pairs=21)],
    )
    _profile(profiles / "spa_v0_3.json")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    row = payload["rows"][0]
    assert row["overall_status"] == "CANDIDATE_CALIBRATED"
    assert row["next_action"]["code"] == "REVIEW_SHADOW_METRICS"


def test_calibrated_is_not_called_ready(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(
        tmp_path,
        monkeypatch,
        [_calibration(matcher_status="CALIBRATED_PROVISIONAL_MULTI_CONTEXT")],
    )
    _profile(profiles / "spa_v0_3.json")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["overall_status"] == "CURRENT_REQUIREMENTS_SATISFIED"
    assert payload["rows"][0]["overall_status"] != "READY"


def test_runtime_historical_evidence_is_reported(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(profiles / "spa_v0_3.json")
    _runtime_session(runs, evidence=True)
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["historical_status"] == "EVIDENCE_AVAILABLE"


def test_multiple_variants_remain_separate(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(
        tmp_path,
        monkeypatch,
        [
            _calibration(vehicle_variant="LMP2_ELMS"),
            _calibration(
                vehicle_variant="HYPER",
                matcher_status="CALIBRATED_PROVISIONAL_MULTI_CONTEXT",
            ),
        ],
    )
    _profile(profiles / "spa_v0_3.json")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert {row["vehicle_variant"] for row in payload["rows"]} == {
        "LMP2_ELMS",
        "HYPER",
    }


def test_missing_layout_resolves_from_unique_validated_profile(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(
        profiles / "spa_v0_3.json",
        track="Spa",
        layout="Spa GP",
    )
    _runtime_session(runs, track="Spa", layout=None)
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert len(payload["rows"]) == 1
    row = payload["rows"][0]
    assert row["track_layout"] == "Spa GP"
    assert row["layout_resolution_counts"] == {"validated_track_profile": 1}
    assert payload["summary"]["unresolved_sessions"] == 0
    assert payload["summary"]["resolved_missing_layout_from_profile"] == 1


def test_profile_resolved_layout_preserves_historical_state(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(profiles / "spa_v0_3.json", track="Spa", layout="Spa GP")
    _runtime_session(runs, track="Spa", layout=None, h4=True, evidence=True)
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["historical_status"] == "EVIDENCE_AVAILABLE"


def test_missing_layout_without_validated_profile_remains_unresolved(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _runtime_session(runs, track="Daytona", layout=None)
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"] == []
    assert payload["summary"]["unresolved_sessions"] == 1
    assert payload["unresolved_sessions"][0]["reason"] == "MISSING_TRACK_LAYOUT"


def test_multiple_validated_profile_layouts_do_not_guess(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(
        profiles / "spa_a_v0_3.json",
        track="Spa",
        layout="Layout A",
        profile_id="spa-a-v0.3",
    )
    _profile(
        profiles / "spa_b_v0_3.json",
        track="Spa",
        layout="Layout B",
        profile_id="spa-b-v0.3",
    )
    _runtime_session(runs, track="Spa", layout=None)
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"] == []
    assert payload["summary"]["unresolved_sessions"] == 1


def test_runtime_metadata_layout_is_not_overridden_by_profile(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(profiles / "spa_v0_3.json", track="Spa", layout="Profile Layout")
    _runtime_session(runs, track="Spa", layout="Runtime Layout")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    row = payload["rows"][0]
    assert row["track_layout"] == "Runtime Layout"
    assert row["layout_resolution_counts"] == {"runtime_metadata": 1}
    assert row["profile_status"] == "MISSING"


def test_runtime_and_calibration_sources_are_reported(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [_calibration()])
    _profile(profiles / "spa_v0_3.json")
    _runtime_session(runs)
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["sources"] == ["runtime", "calibration_batches"]


def test_multiple_layouts_are_not_merged_and_emit_warning(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _runtime_session(runs, run_name="a", layout="Layout A")
    _runtime_session(runs, run_name="b", layout="Layout B")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert len(payload["rows"]) == 2
    assert payload["identity_warnings"][0]["code"] == "MULTIPLE_LAYOUTS_FOR_TRACK_VARIANT"


def test_track_summary_counts_pending_and_satisfied_contexts(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(
        tmp_path,
        monkeypatch,
        [
            _calibration(
                vehicle_variant="LMP2_ELMS",
                matcher_status="CALIBRATED_PROVISIONAL_MULTI_CONTEXT",
            ),
            _calibration(
                vehicle_variant="GT3",
                labeled_pairs=0,
                queue_pairs=0,
                matcher_status="NO_CALIBRATION_FOR_CONTEXT",
            ),
        ],
    )
    _profile(profiles / "spa_v0_3.json")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    track = payload["tracks"][0]
    assert track["context_count"] == 2
    assert track["satisfied_contexts"] == 1
    assert track["pending_contexts"] == 1


def test_highest_validated_profile_wins(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [_calibration()])
    _profile(
        profiles / "spa_v0_2.json",
        status="VALIDATED",
        profile_id="spa-v0.2",
    )
    _profile(
        profiles / "spa_v0_3.json",
        status="VALIDATED_MULTI_SESSION",
        profile_id="spa-v0.3",
    )
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["profile_id"] == "spa-v0.3"


def test_h3_import_readiness_is_exposed_without_changing_overall_status(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(
        tmp_path, monkeypatch,
        [_calibration(matcher_status="CALIBRATED_PROVISIONAL_MULTI_CONTEXT")],
    )
    _profile(profiles / "spa_v0_3.json")
    monkeypatch.setattr(tr, "discover_h3_import_readiness", lambda **_kwargs: {
        tr.H3Context("Spa", "Spa", "LMP2_ELMS"): {
            "status": "H3_READY_TO_IMPORT", "read_only": True,
            "historical_actions_authorized": False,
        }
    })
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches,
        history_db=tmp_path / "history.duckdb",
    )
    row = payload["rows"][0]
    assert row["overall_status"] == "CURRENT_REQUIREMENTS_SATISFIED"
    assert row["h3_import_status"] == "H3_READY_TO_IMPORT"
    assert row["h3_import"]["historical_actions_authorized"] is False
    assert payload["summary"]["h3_import_status_counts"] == {"H3_READY_TO_IMPORT": 1}
