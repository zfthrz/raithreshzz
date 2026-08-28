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
) -> None:
    _write_json(
        path,
        {
            "profile_id": "spa-v0.3",
            "track": track,
            "layout": layout,
            "status": status,
            "turns": [{"start_m": 1, "end_m": 2}] if turns else [],
        },
    )


def _runtime_session(
    root: Path,
    *,
    track: str = "Spa",
    layout: str = "Spa",
    variant: str = "LMP2_ELMS",
    h4: bool = False,
    evidence: bool = False,
) -> None:
    state = root / "run1" / "state.json"
    analysis = root / "run1" / "analysis.json"
    _write_json(
        analysis,
        {
            "metadata": {
                "track": track,
                "lmu_track_layout": layout,
                "vehicle_identity": {"variant": variant},
            }
        },
    )
    stages = {"analyze": {"status": "RUN", "output": str(analysis)}}
    if h4:
        stages["h4"] = {"status": "RUN", "output": "h4.json"}
    if evidence:
        stages["historical_telemetry_evidence"] = {
            "status": "RUN",
            "output": "data/generated/historical_telemetry_evidence/x.json",
        }
    _write_json(state, {"stages": stages})


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
    monkeypatch.setattr(
        tr, "load_calibration_summary", lambda _root: {"rows": rows}
    )
    return profiles, runs, batches


def test_missing_profile_is_needs_profile(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [_calibration()])
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["overall_status"] == "NEEDS_PROFILE"


def test_valid_profile_without_sessions_is_needs_sessions(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(profiles / "spa_v0_3.json")
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["track_only"][0]["overall_status"] == "NEEDS_SESSIONS"


def test_sessions_without_queue_need_calibration_queue(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [])
    _profile(profiles / "spa_v0_3.json")
    _runtime_session(runs)
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    row = payload["rows"][0]
    assert row["overall_status"] == "NEEDS_CALIBRATION_QUEUE"
    assert row["next_action"]["code"] == "GENERATE_CALIBRATION_QUEUE"


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


def test_highest_validated_profile_wins(tmp_path, monkeypatch):
    profiles, runs, batches = _roots(tmp_path, monkeypatch, [_calibration()])
    _write_json(
        profiles / "spa_v0_2.json",
        {
            "profile_id": "spa-v0.2",
            "track": "Spa",
            "layout": "Spa",
            "status": "VALIDATED",
            "turns": [{}],
        },
    )
    _write_json(
        profiles / "spa_v0_3.json",
        {
            "profile_id": "spa-v0.3",
            "track": "Spa",
            "layout": "Spa",
            "status": "VALIDATED_MULTI_SESSION",
            "turns": [{}],
        },
    )
    payload = tr.build_track_readiness(
        profile_dir=profiles, runs_root=runs, batches_root=batches
    )
    assert payload["rows"][0]["profile_id"] == "spa-v0.3"
