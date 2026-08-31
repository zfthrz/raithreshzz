from __future__ import annotations

from pathlib import Path

import pytest

import build_historical_telemetry_evidence as builder
from race_engineer_track_map import TrackMapData, TrackMapPoint, TrackMapZone
from validate_historical_telemetry_evidence import validate_document


def track_map(path: Path, *, track: str = "Spa", speed: float = 180.0) -> TrackMapData:
    points = tuple(
        TrackMapPoint(0.0, 0.0, distance, speed, 60.0, 20.0, 3)
        for distance in (0.0, 50.0, 100.0, 150.0, 200.0)
    )
    return TrackMapData(
        database_path=path,
        track=track,
        layout=track,
        lap=4,
        requested_lap=4,
        selection_reason="preferred_lap",
        duration_s=120.0,
        points=points,
        width_m=1.0,
        height_m=1.0,
    )


def test_builder_uses_existing_h5_zones_and_validates_output(tmp_path, monkeypatch):
    current = track_map(tmp_path / "current.duckdb", speed=180.0)
    reference = track_map(tmp_path / "reference.duckdb", speed=200.0)
    monkeypatch.setattr(
        builder,
        "load_track_zones",
        lambda _path: (
            TrackMapZone("zone_001", "T1", "loss", 50.0, 150.0, 0.2),
        ),
    )

    document = builder.build_artifact(
        current,
        reference,
        track_profiles_dir=tmp_path / "profiles",
        zones_path=tmp_path / "zones.json",
    )

    assert validate_document(document) == []
    assert document["metadata"]["interval_basis"] == "h5_2_zones"
    assert document["metadata"]["current"]["lap"] == 4
    assert document["interval_evidence"][0]["interval_id"] == "zone:zone_001"
    assert document["interval_evidence"][0]["delta_change_s"] == pytest.approx(0.2)


def test_builder_rejects_different_track_layouts(tmp_path):
    with pytest.raises(ValueError, match="mismo circuito/layout"):
        builder.build_artifact(
            track_map(tmp_path / "current.duckdb", track="Spa"),
            track_map(tmp_path / "reference.duckdb", track="Monza"),
            track_profiles_dir=tmp_path / "profiles",
        )


def test_validator_rejects_authority_and_nonfinite_evidence(tmp_path, monkeypatch):
    current = track_map(tmp_path / "current.duckdb", speed=180.0)
    reference = track_map(tmp_path / "reference.duckdb", speed=200.0)
    monkeypatch.setattr(
        builder,
        "load_track_zones",
        lambda _path: (TrackMapZone("z", "Z", "loss", 0.0, 200.0, 0.2),),
    )
    document = builder.build_artifact(
        current,
        reference,
        track_profiles_dir=tmp_path,
        zones_path=tmp_path / "zones.json",
    )
    document["contract"]["historical_actions_authorized"] = True
    document["interval_evidence"][0]["speed_delta_mean_kmh"] = float("nan")

    errors = validate_document(document)

    assert "contract no conserva autoridad observacional read-only" in errors
    assert any("speed_delta_mean_kmh" in error for error in errors)


def test_validator_rejects_duplicate_interval_ids():
    document = {
        "metadata": {
            "version": "0.3",
            "status": "NO_COMMON_COVERAGE",
            "current_coverage_ratio": 0.0,
            "reference_coverage_ratio": 0.0,
        },
        "contract": {
            "observational_only": True,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
            "llm_called": False,
        },
        "interval_evidence": [
            {
                "interval_id": "same",
                "start_distance_m": 0.0,
                "end_distance_m": 1.0,
                "status": "UNAVAILABLE",
                "coverage_ratio": 0.0,
                "sample_count": 0,
                "delta_change_s": None,
                "speed_delta_mean_kmh": None,
                "throttle_delta_mean_percent": None,
                "brake_delta_mean_percent": None,
                "steering_signed_delta_mean_percent": None,
                "steering_magnitude_delta_mean_percent": None,
                "steering_magnitude_delta_peak_percent": None,
                "steering_comparable_sample_count": 0,
            },
            {
                "interval_id": "same",
                "start_distance_m": 1.0,
                "end_distance_m": 2.0,
                "status": "UNAVAILABLE",
                "coverage_ratio": 0.0,
                "sample_count": 0,
                "delta_change_s": None,
                "speed_delta_mean_kmh": None,
                "throttle_delta_mean_percent": None,
                "brake_delta_mean_percent": None,
                "steering_signed_delta_mean_percent": None,
                "steering_magnitude_delta_mean_percent": None,
                "steering_magnitude_delta_peak_percent": None,
                "steering_comparable_sample_count": 0,
            },
        ],
    }

    assert any("duplicado" in error for error in validate_document(document))


@pytest.mark.parametrize(
    ("status", "coverage", "delta", "expected"),
    [
        ("FULL_COVERAGE", 0.5, 0.1, "FULL_COVERAGE requiere"),
        ("PARTIAL_COVERAGE", 1.0, 0.1, "PARTIAL_COVERAGE requiere"),
        ("UNAVAILABLE", 0.5, None, "UNAVAILABLE requiere"),
        ("UNAVAILABLE", 0.0, 0.1, "debe ser null cuando UNAVAILABLE"),
    ],
)
def test_validator_rejects_contradictory_interval_status(
    status,
    coverage,
    delta,
    expected,
):
    document = {
        "metadata": {
            "version": "0.3",
            "status": "FULL_COMMON_COVERAGE",
            "current_coverage_ratio": 1.0,
            "reference_coverage_ratio": 1.0,
        },
        "contract": {
            "observational_only": True,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
            "llm_called": False,
        },
        "interval_evidence": [{
            "interval_id": "zone:test",
            "start_distance_m": 10.0,
            "end_distance_m": 20.0,
            "status": status,
            "coverage_ratio": coverage,
            "sample_count": 0 if status == "UNAVAILABLE" else 2,
            "delta_change_s": delta,
            "speed_delta_mean_kmh": None,
            "throttle_delta_mean_percent": None,
            "brake_delta_mean_percent": None,
            "steering_signed_delta_mean_percent": None,
            "steering_magnitude_delta_mean_percent": None,
            "steering_magnitude_delta_peak_percent": None,
            "steering_comparable_sample_count": 0,
        }],
    }

    assert any(expected in error for error in validate_document(document))


def test_validator_requires_explicit_steering_fields_in_v0_3(
    tmp_path,
    monkeypatch,
):
    current = track_map(tmp_path / "current.duckdb", speed=180.0)
    reference = track_map(tmp_path / "reference.duckdb", speed=200.0)
    monkeypatch.setattr(
        builder,
        "load_track_zones",
        lambda _path: (TrackMapZone("z", "Z", "loss", 0.0, 200.0, 0.2),),
    )
    document = builder.build_artifact(
        current,
        reference,
        track_profiles_dir=tmp_path,
        zones_path=tmp_path / "zones.json",
    )
    document["interval_evidence"][0].pop(
        "steering_magnitude_delta_mean_percent"
    )

    assert any(
        "steering_magnitude_delta_mean_percent ausente en schema v0.3" in error
        for error in validate_document(document)
    )
