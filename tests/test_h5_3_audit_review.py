from __future__ import annotations

import json
from pathlib import Path

import pytest

from build_historical_coaching_candidates import build_candidates
from label_h5_3_audit_candidates import (
    load_dataset,
    load_labels,
    save_labels,
    upsert_label,
)
from prepare_h5_3_audit_dataset import build_dataset
from validate_h5_3_audit_labels import validate


def _context(track: str) -> dict:
    return {
        "track": track,
        "track_layout": track,
        "vehicle_variant": "LMP2_ELMS",
        "car_name_raw": "IDEC Sport #18",
    }


def _dual_reference(track: str, lap: int, duration: float) -> dict:
    return {
        "metadata": {
            "schema_version": "1.0",
            "dual_reference_version": "0.2",
        },
        "status": "DUAL_REFERENCE_AVAILABLE",
        "context": _context(track),
        "target_session": {"session_id": 23},
        "session_reference": {"lap": lap, "duration_s": duration},
        "historical_reference": {"session_id": 19, "lap": 10, "duration_s": 97.5},
        "coaching_authority": {
            "active_reference": "session_reference",
            "historical_reference_can_change_driver_cues": False,
            "historical_reference_can_change_global_ABC_plan": False,
            "historical_reference_is_observational_only": True,
        },
    }


def _comparison(
    track: str,
    delta: float,
    zone_delta: float,
    zone_sign: str,
) -> dict:
    return {
        "metadata": {
            "schema_version": "1.1",
            "cross_session_version": "0.2",
        },
        "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
        "context": _context(track),
        "temporal_validation": {
            "status": "OK",
            "calculated_current_minus_historical_s": delta,
            "tolerance_s": 1e-6,
        },
        "spatial_comparison": {
            "trend_zone_summary_count": 2,
            "trend_zone_summaries": [
                {"trend_zone_id": "trend_001"},
                {"trend_zone_id": "trend_002"},
            ],
            "localization": {
                "mode": "validated_track_profile",
                "profile_id": "audit-profile",
                "profile_status": "VALIDATED_MULTI_SESSION",
                "profile_track": track,
                "profile_layout": track,
            },
            "zone_summary_count": 2,
            "zone_summaries": [
                {
                    "source_trend_zone_id": "trend_001",
                    "scope": "track_profile_segment",
                    "location": {"label": "Z1 - Test", "profile_id": "audit-profile"},
                    "type": zone_sign,
                    "start_distance": 100.0,
                    "end_distance": 200.0,
                    "delta_change": zone_delta,
                    "speed_delta_avg": -4.5,
                    "throttle_delta_avg": -2.0,
                    "brake_delta_avg": 1.5,
                    "steering_delta_avg": 0.4,
                },
                {
                    "source_trend_zone_id": "trend_002",
                    "scope": "track_profile_segment",
                    "location": {"label": "Z2 - Test", "profile_id": "audit-profile"},
                    "type": zone_sign,
                    "start_distance": 200.0,
                    "end_distance": 260.0,
                    "delta_change": zone_delta * 0.5,
                    "speed_delta_avg": 3.0,
                    "throttle_delta_avg": 0.5,
                    "brake_delta_avg": -0.2,
                    "steering_delta_avg": -0.1,
                },
            ],
        },
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
        },
    }


def _write_h5_3a_artifact(
    tmp_path: Path,
    stem: str,
    *,
    delta: float,
) -> Path:
    track = "Autodromo Nazionale Monza" if delta > 0 else "Imola"
    dual_path = tmp_path / f"{stem}_dual.json"
    comparison_path = tmp_path / f"{stem}_comparison.json"
    dual_path.write_text(
        json.dumps(_dual_reference(track, 3, 99.28), ensure_ascii=False),
        encoding="utf-8",
    )
    zone_sign = "loss" if delta > 0 else "gain"
    comparison_path.write_text(
        json.dumps(
            _comparison(track, delta, delta, zone_sign),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    artifact = build_candidates(dual_path, comparison_path)
    artifact_path = tmp_path / f"{stem}.json"
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False),
        encoding="utf-8",
    )
    return artifact_path


def test_dataset_covers_both_signs_and_is_deterministic(tmp_path: Path):
    slower = _write_h5_3a_artifact(tmp_path, "monza", delta=1.78)
    faster = _write_h5_3a_artifact(tmp_path, "imola", delta=-0.6)

    first = build_dataset([slower, faster])
    second = build_dataset([faster, slower])

    assert first["coverage"]["candidate_count"] == 4
    assert first["coverage"]["both_signs_covered"] is True
    assert set(first["coverage"]["delta_signs"]) == {
        "current_slower",
        "current_faster",
    }
    assert first["candidates"][0]["observational_channel_evidence"][
        "speed_delta_avg"
    ] == -4.5
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second,
        ensure_ascii=False,
        sort_keys=True,
    )


def test_label_round_trip_passes_validator(tmp_path: Path):
    artifact = _write_h5_3a_artifact(tmp_path, "monza", delta=1.78)
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(build_dataset([artifact]), ensure_ascii=False),
        encoding="utf-8",
    )
    labels_path = tmp_path / "labels.json"
    dataset_data = load_dataset(dataset_path)
    labels_data = load_labels(labels_path, dataset_path, reviewer="test")
    for item in dataset_data["candidates"]:
        upsert_label(labels_data, item, "OBSERVATIONAL_ONLY", "")
    save_labels(labels_path, labels_data)

    errors, _, summary = validate(dataset_path, labels_path)

    assert errors == []
    assert summary["unreviewed"] == 0
    assert summary["counts"]["OBSERVATIONAL_ONLY"] == 2


def test_upsert_rejects_invalid_label(tmp_path: Path):
    artifact = _write_h5_3a_artifact(tmp_path, "monza", delta=1.78)
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(build_dataset([artifact]), ensure_ascii=False),
        encoding="utf-8",
    )
    dataset_data = load_dataset(dataset_path)
    labels_data = load_labels(tmp_path / "labels.json", dataset_path, None)

    with pytest.raises(ValueError, match="human_label inválido"):
        upsert_label(labels_data, dataset_data["candidates"][0], "WRONG", "")


def test_validator_rejects_unknown_audit_id(tmp_path: Path):
    artifact = _write_h5_3a_artifact(tmp_path, "monza", delta=1.78)
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(build_dataset([artifact]), ensure_ascii=False),
        encoding="utf-8",
    )
    labels_path = tmp_path / "labels.json"
    dataset_data = load_dataset(dataset_path)
    labels_data = load_labels(labels_path, dataset_path, "test")
    for item in dataset_data["candidates"]:
        upsert_label(labels_data, item, "OBSERVATIONAL_ONLY", "")
    labels_data["labels"][0]["audit_id"] = "unknown_id"
    save_labels(labels_path, labels_data)

    errors, _, _ = validate(dataset_path, labels_path)

    assert any("fuera del dataset" in error for error in errors)


def test_validator_rejects_changed_dataset_hash(tmp_path: Path):
    artifact = _write_h5_3a_artifact(tmp_path, "monza", delta=1.78)
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(build_dataset([artifact]), ensure_ascii=False),
        encoding="utf-8",
    )
    labels_path = tmp_path / "labels.json"
    dataset_data = load_dataset(dataset_path)
    labels_data = load_labels(labels_path, dataset_path, "test")
    labels_data["metadata"]["source_dataset_sha256"] = "0" * 64
    save_labels(labels_path, labels_data)

    errors, _, _ = validate(dataset_path, labels_path)

    assert any("source_dataset_sha256" in error for error in errors)


def test_skipped_artifact_produces_source_without_candidates(tmp_path: Path):
    artifact = _write_h5_3a_artifact(tmp_path, "monza", delta=1.78)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["prerequisites"]["applicable"] = False
    payload["prerequisites"]["skip_reason"] = "no_exact_validated_track_profile"
    payload["candidates"] = []
    artifact.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    dataset = build_dataset([artifact])

    assert dataset["coverage"]["candidate_count"] == 0
    assert dataset["sources"][0]["skip_reason"] == "no_exact_validated_track_profile"
    assert dataset["sources"][0]["candidate_count"] == 0
