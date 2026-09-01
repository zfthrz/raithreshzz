from __future__ import annotations

import csv
import json
from pathlib import Path

import validate_track_profile_session as validator


def _profile() -> dict:
    return {
        "profile_id": "test-v0.1",
        "status": "VALIDATED_SINGLE_SESSION",
        "track": "Test Track",
        "layout": "Test Layout",
        "calibration": {"source_session": "source"},
        "turns": [
            {"turn": 1, "name": "Left", "direction": "left", "start_m": 0, "apex_m": 20, "end_m": 40},
            {"turn": 2, "name": "Right", "direction": "right", "start_m": 50, "apex_m": 70, "end_m": 90},
        ],
    }


def _summary(session: str = "independent") -> dict:
    return {
        "source_file": f"C:/telemetry/{session}.duckdb",
        "track_name": "Test Track",
        "track_layout": "Test Layout",
        "selected_lap": 3,
    }


def test_turn_result_uses_nearest_same_direction_peak() -> None:
    samples = [{"d": float(value)} for value in (10, 18, 28, 35)]
    signed = [0.2, 0.5, -0.9, 0.8]
    strength = [0.2, 0.5, 0.9, 0.8]
    turn = {"turn": 1, "name": "Left", "direction": "left", "start_m": 0, "apex_m": 20, "end_m": 40}

    result = validator._turn_result(turn, samples, signed, strength, [0, 1, 2, 3])

    assert result["observed_apex_m"] == 18.0
    assert result["offset_m"] == -2.0
    assert result["status"] == "PASS"


def test_turn_result_fails_closed_without_expected_direction() -> None:
    samples = [{"d": 20.0}]
    result = validator._turn_result(
        _profile()["turns"][0], samples, [-0.5], [0.5], [0]
    )
    assert result["status"] == "FAIL"
    assert result["observed_apex_m"] is None


def test_build_report_rejects_source_session_before_geometry(tmp_path: Path) -> None:
    missing_csv = tmp_path / "missing.csv"
    report = validator.build_report(_profile(), _summary("source"), missing_csv)
    assert report["overall_status"] == "BLOCKED_CONTRACT"
    assert report["promotion_readiness"] == "NOT_READY"
    assert report["automatic_promotion"] is False
    assert report["profile_mutated"] is False


def test_build_report_rejects_track_or_layout_mismatch(tmp_path: Path) -> None:
    summary = _summary()
    summary["track_layout"] = "Other Layout"
    report = validator.build_report(_profile(), summary, tmp_path / "missing.csv")
    assert report["overall_status"] == "BLOCKED_CONTRACT"
    assert "layout mismatch" in report["contract_errors"][0]


def test_cli_writes_report_but_never_mutates_profile(tmp_path: Path, monkeypatch) -> None:
    profile_path = tmp_path / "profile.json"
    summary_path = tmp_path / "candidate_track_gps_summary.json"
    csv_path = tmp_path / "candidate_track_gps.csv"
    output_path = tmp_path / "report.json"
    profile_path.write_text(json.dumps(_profile()), encoding="utf-8")
    summary_path.write_text(json.dumps(_summary()), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["lap_distance_m", "x_east_m", "y_north_m"])
        writer.writeheader()
        for distance in range(100):
            writer.writerow({"lap_distance_m": distance, "x_east_m": distance, "y_north_m": 0})
    before = profile_path.read_bytes()

    exit_code = validator.main([
        str(profile_path), str(csv_path), "--summary", str(summary_path),
        "--output", str(output_path),
    ])

    assert exit_code == 2
    assert profile_path.read_bytes() == before
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "AUDIT_READ_ONLY"
    assert payload["automatic_promotion"] is False
