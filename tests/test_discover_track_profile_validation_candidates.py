from __future__ import annotations

import json
from pathlib import Path

import discover_track_profile_validation_candidates as discovery


def _write_profile(directory: Path, *, status: str = "VALIDATED_SINGLE_SESSION") -> Path:
    path = directory / "test_profile_v0_1.json"
    path.write_text(json.dumps({
        "profile_id": "test-v0.1",
        "status": status,
        "track": "Test Track",
        "layout": "Test Layout",
        "lap_length_m": 3600.0,
        "calibration": {"source_session": "source_session"},
    }), encoding="utf-8")
    return path


def _probe(path: Path) -> dict:
    return {
        "metadata": {"TrackName": "Test Track", "TrackLayout": "Test Layout"},
        "missing_channels": [],
        "selected_lap": 2,
        "selected_lap_metrics": {
            "gps_coverage": 1.0,
            "duration_s": 90.0,
            "lap_dist_span_m": 3590.0,
            "gps_path_m": 3580.0,
        },
        "usable_gps_lap": True,
    }


def _metadata(path: Path) -> dict:
    return _probe(path)["metadata"]


def test_discovery_excludes_source_and_reports_stable_independent_candidate(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    telemetry = tmp_path / "telemetry"
    profiles.mkdir()
    telemetry.mkdir()
    _write_profile(profiles)
    source = telemetry / "source_session.duckdb"
    independent = telemetry / "independent session.duckdb"
    source.write_bytes(b"source")
    independent.write_bytes(b"candidate")

    report = discovery.discover_candidates(
        profiles, telemetry, settle_seconds=600,
        now_s=independent.stat().st_mtime + 601, probe=_probe,
        metadata_probe=_metadata,
    )

    row = report["profiles"][0]
    assert row["source_session_excluded"] == "source_session"
    assert row["candidate_count"] == 1
    assert row["ready_count"] == 1
    assert row["candidates"][0]["status"] == "READY_FOR_GPS_EXPORT"
    assert "independent session.duckdb" in row["candidates"][0]["extract_command"]
    assert report["automatic_export"] is False
    assert report["automatic_promotion"] is False


def test_discovery_waits_for_stability_without_hiding_candidate(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    telemetry = tmp_path / "telemetry"
    profiles.mkdir()
    telemetry.mkdir()
    _write_profile(profiles)
    candidate = telemetry / "candidate.duckdb"
    candidate.write_bytes(b"candidate")

    report = discovery.discover_candidates(
        profiles, telemetry, settle_seconds=600,
        now_s=candidate.stat().st_mtime + 20, probe=_probe,
        metadata_probe=_metadata,
    )

    assert report["profiles"][0]["candidates"][0]["status"] == "WAITING_STABILITY"
    assert report["profiles"][0]["ready_count"] == 0


def test_discovery_requires_exact_layout_and_provisional_status(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    telemetry = tmp_path / "telemetry"
    profiles.mkdir()
    telemetry.mkdir()
    _write_profile(profiles, status="VALIDATED_MULTI_SESSION")
    candidate = telemetry / "candidate.duckdb"
    candidate.write_bytes(b"candidate")

    report = discovery.discover_candidates(
        profiles, telemetry, settle_seconds=0, probe=_probe,
        metadata_probe=_metadata,
    )

    assert report["provisional_profile_count"] == 0
    assert report["profiles"] == []

    _write_profile(profiles)

    def other_layout(path: Path) -> dict:
        result = _probe(path)
        result["metadata"]["TrackLayout"] = "Other Layout"
        return result

    report = discovery.discover_candidates(
        profiles, telemetry, settle_seconds=0, probe=other_layout,
        metadata_probe=lambda path: other_layout(path)["metadata"],
    )
    assert report["provisional_profile_count"] == 1
    assert report["profiles"][0]["candidate_count"] == 0


def test_discovery_fails_closed_for_missing_gps_channels(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    telemetry = tmp_path / "telemetry"
    profiles.mkdir()
    telemetry.mkdir()
    _write_profile(profiles)
    candidate = telemetry / "candidate.duckdb"
    candidate.write_bytes(b"candidate")

    def missing(_path: Path) -> dict:
        result = _probe(_path)
        result["missing_channels"] = ["GPS Latitude"]
        result["usable_gps_lap"] = False
        return result

    report = discovery.discover_candidates(
        profiles, telemetry, settle_seconds=0, probe=missing,
        metadata_probe=_metadata,
    )

    row = report["profiles"][0]["candidates"][0]
    assert row["status"] == "NOT_USABLE_FOR_GPS_EXPORT"
    assert row["missing_channels"] == ["GPS Latitude"]


def test_discovery_rejects_a_long_but_incomplete_selected_lap(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    telemetry = tmp_path / "telemetry"
    profiles.mkdir()
    telemetry.mkdir()
    _write_profile(profiles)
    candidate = telemetry / "candidate.duckdb"
    candidate.write_bytes(b"candidate")

    def partial(path: Path) -> dict:
        result = _probe(path)
        result["selected_lap_metrics"]["lap_dist_span_m"] = 2500.0
        result["selected_lap_metrics"]["gps_path_m"] = 2490.0
        return result

    report = discovery.discover_candidates(
        profiles, telemetry, settle_seconds=0, probe=partial,
        metadata_probe=_metadata,
    )

    row = report["profiles"][0]["candidates"][0]
    assert row["status"] == "NOT_USABLE_FOR_GPS_EXPORT"
    assert row["lap_distance_coverage"] < 0.90
    assert row["gps_path_coverage"] < 0.90
