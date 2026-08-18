from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build_historical_coaching_candidates import build_candidates
from historical_candidate_selection import (
    build_authorized_evidence,
    build_output,
    load_validated_sources,
    validate_response,
)
from label_h5_3_audit_candidates import (
    load_dataset,
    load_labels,
    save_labels,
    upsert_label,
)
from prepare_h5_3_audit_dataset import build_dataset
from validate_historical_candidate_selection import validate


def _context() -> dict:
    return {
        "track": "Autodromo Nazionale Monza",
        "track_layout": "Autodromo Nazionale Monza",
        "vehicle_variant": "LMP2_ELMS",
        "car_name_raw": "IDEC Sport #18",
    }


def _dual_reference() -> dict:
    return {
        "metadata": {
            "schema_version": "1.0",
            "dual_reference_version": "0.2",
        },
        "status": "DUAL_REFERENCE_AVAILABLE",
        "context": _context(),
        "target_session": {"session_id": 23},
        "session_reference": {"lap": 3, "duration_s": 99.28},
        "historical_reference": {"session_id": 19, "lap": 10, "duration_s": 97.5},
        "coaching_authority": {
            "active_reference": "session_reference",
            "historical_reference_can_change_driver_cues": False,
            "historical_reference_can_change_global_ABC_plan": False,
            "historical_reference_is_observational_only": True,
        },
    }


def _comparison() -> dict:
    return {
        "metadata": {
            "schema_version": "1.1",
            "cross_session_version": "0.2",
        },
        "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
        "context": _context(),
        "temporal_validation": {
            "status": "OK",
            "calculated_current_minus_historical_s": 1.78,
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
                "profile_track": "Autodromo Nazionale Monza",
                "profile_layout": "Autodromo Nazionale Monza",
            },
            "zone_summary_count": 2,
            "zone_summaries": [
                {
                    "source_trend_zone_id": "trend_001",
                    "scope": "track_profile_segment",
                    "location": {"label": "Z1 - Test", "profile_id": "audit-profile"},
                    "type": "loss",
                    "start_distance": 100.0,
                    "end_distance": 200.0,
                    "delta_change": 1.78,
                    "speed_delta_avg": -4.5,
                    "throttle_delta_avg": -2.0,
                    "brake_delta_avg": 1.5,
                    "steering_delta_avg": 0.4,
                },
                {
                    "source_trend_zone_id": "trend_002",
                    "scope": "track_profile_segment",
                    "location": {"label": "Z2 - Test", "profile_id": "audit-profile"},
                    "type": "loss",
                    "start_distance": 200.0,
                    "end_distance": 260.0,
                    "delta_change": 0.89,
                    "speed_delta_avg": -3.0,
                    "throttle_delta_avg": -1.0,
                    "brake_delta_avg": 0.5,
                    "steering_delta_avg": 0.2,
                },
            ],
        },
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
        },
    }


def _write_dataset_and_labels(tmp_path: Path) -> tuple[Path, Path, dict, dict]:
    dual_path = tmp_path / "dual.json"
    comparison_path = tmp_path / "comparison.json"
    dual_path.write_text(json.dumps(_dual_reference(), ensure_ascii=False), encoding="utf-8")
    comparison_path.write_text(
        json.dumps(_comparison(), ensure_ascii=False),
        encoding="utf-8",
    )
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(
        json.dumps(build_candidates(dual_path, comparison_path), ensure_ascii=False),
        encoding="utf-8",
    )

    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(build_dataset([artifact_path]), ensure_ascii=False),
        encoding="utf-8",
    )
    labels_path = tmp_path / "labels.json"
    dataset = load_dataset(dataset_path)
    labels = load_labels(labels_path, dataset_path, reviewer="test")
    for item in dataset["candidates"]:
        upsert_label(labels, item, "ACTIONABLE", "")
    save_labels(labels_path, labels)
    return dataset_path, labels_path, dataset, labels


def _valid_response(candidate_id: str) -> dict:
    return {
        "selected_candidates": [
            {
                "candidate_id": candidate_id,
                "significance": "primary",
                "observation_codes": [
                    "time_loss",
                    "current_speed_lower",
                    "current_throttle_lower",
                    "current_brake_higher",
                ],
            }
        ],
        "limitation_codes": [
            "no_historical_coaching_authority",
            "shadow_observational_only",
            "physical_points_not_attached",
        ],
    }


def test_build_authorized_evidence_only_includes_actionable(tmp_path: Path):
    dataset_path, labels_path, dataset, labels = _write_dataset_and_labels(tmp_path)
    evidence = build_authorized_evidence(dataset, labels)

    assert evidence["authorized_candidate_count"] == 2
    assert evidence["contract"]["free_text_authorized"] is False
    assert evidence["candidates"][0]["authorized_observations"] == [
        "time_loss",
        "current_speed_lower",
        "current_throttle_lower",
        "current_brake_higher",
    ]


def test_build_output_passes_validator(tmp_path: Path):
    dataset_path, labels_path, dataset, labels = _write_dataset_and_labels(tmp_path)
    evidence = build_authorized_evidence(dataset, labels)
    candidate_id = dataset["candidates"][0]["audit_id"]
    output = build_output(
        dataset_path,
        labels_path,
        dataset,
        labels,
        evidence,
        _valid_response(candidate_id),
        backend="ollama",
        model="test-model",
    )

    assert validate(output) == []
    assert output["coaching_authority"]["historical_actions_authorized"] is False
    assert output["selected_evidence"][0]["candidate_id"] == candidate_id


def test_validate_response_rejects_unknown_candidate(tmp_path: Path):
    _, _, dataset, labels = _write_dataset_and_labels(tmp_path)
    evidence = build_authorized_evidence(dataset, labels)
    candidate_id = dataset["candidates"][0]["audit_id"]
    response = _valid_response(candidate_id)
    response["selected_candidates"][0]["candidate_id"] = "cand_999"

    assert any(
        "no existe en la evidencia" in error
        for error in validate_response(response, evidence)
    )


def test_validate_response_rejects_unauthorized_observation_codes(tmp_path: Path):
    _, _, dataset, labels = _write_dataset_and_labels(tmp_path)
    evidence = build_authorized_evidence(dataset, labels)
    candidate_id = dataset["candidates"][0]["audit_id"]
    response = _valid_response(candidate_id)
    response["selected_candidates"][0]["observation_codes"] = [
        "time_loss",
        "current_speed_higher",
    ]

    assert any(
        "no autorizados" in error
        for error in validate_response(response, evidence)
    )


def test_validate_response_rejects_free_text_keys(tmp_path: Path):
    _, _, dataset, labels = _write_dataset_and_labels(tmp_path)
    evidence = build_authorized_evidence(dataset, labels)
    candidate_id = dataset["candidates"][0]["audit_id"]
    response = _valid_response(candidate_id)
    response["recommendation"] = "frenar antes"

    assert "claves raíz fuera de contrato" in validate_response(response, evidence)


def test_validator_rejects_tampered_selected_evidence(tmp_path: Path):
    dataset_path, labels_path, dataset, labels = _write_dataset_and_labels(tmp_path)
    evidence = build_authorized_evidence(dataset, labels)
    candidate_id = dataset["candidates"][0]["audit_id"]
    output = build_output(
        dataset_path,
        labels_path,
        dataset,
        labels,
        evidence,
        _valid_response(candidate_id),
        backend="deepseek",
        model="test-model",
    )
    output["selected_evidence"][0]["delta_change_s"] = 99.0

    assert any(
        "selected_evidence no coincide exactamente" in error
        for error in validate(output)
    )


def test_candidate_selection_aliases_match_versioned_sources():
    root = Path(__file__).resolve().parents[1]
    contracts = {
        "historical_candidate_selection.py": (
            "historical_candidate_selection_v0_1.py"
        ),
        "validate_historical_candidate_selection.py": (
            "validate_historical_candidate_selection_v0_1.py"
        ),
    }
    for alias_name, source_name in contracts.items():
        alias_hash = hashlib.sha256((root / alias_name).read_bytes()).digest()
        source_hash = hashlib.sha256((root / source_name).read_bytes()).digest()
        assert alias_hash == source_hash
