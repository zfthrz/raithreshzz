from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit_h5_3_actionability_features import (
    VALID_HUMAN_LABELS,
    _serialize_item,
    run_audit,
)


# ─── Fixtures mínimas ──────────────────────────────────────────────────────


def _build_dataset_path(tmp_path: Path, candidates: list[dict]) -> Path:
    data = {
        "metadata": {
            "schema_version": "1.0",
            "dataset_version": "0.1",
        },
        "sources": [],
        "coverage": {
            "candidate_count": len(candidates),
            "source_artifact_count": 0,
            "tracks": {},
            "delta_signs": {},
            "contexts": {},
            "both_signs_covered": False,
        },
        "candidates": candidates,
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _build_labels_path(
    tmp_path: Path, labels: list[dict], dataset_hash: str = "0" * 64
) -> Path:
    data = {
        "metadata": {
            "label_schema_version": "1.0",
            "created_at_utc": "2026-08-17T00:00:00+00:00",
            "updated_at_utc": "2026-08-17T00:00:00+00:00",
            "source_dataset_sha256": dataset_hash,
            "reviewer": "test",
        },
        "labels": labels,
    }
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _sample_candidate(
    audit_id: str,
    candidate_id: str,
    track: str,
    delta_sign: str,
    delta_change: float,
    start: float,
    end: float,
    channels: dict | None = None,
    location: str | None = "T1 - Test",
) -> dict:
    return {
        "audit_id": audit_id,
        "candidate_id": candidate_id,
        "context": {
            "track": track,
            "track_layout": track,
            "vehicle_variant": "LMP2_ELMS",
            "car_name_raw": "Test Car",
        },
        "delta_sign": delta_sign,
        "current_minus_historical_s": 1.5,
        "location_label": location or "UNNAMED",
        "evidence": {
            "delta_change_s": delta_change,
            "start_distance_m": start,
            "end_distance_m": end,
        },
        "observational_channel_evidence": channels or {},
    }


def _sample_label(audit_id: str, label: str) -> dict:
    return {
        "audit_id": audit_id,
        "human_label": label,
        "review_notes": "",
        "reviewed_at_utc": "2026-08-17T00:00:00+00:00",
        "candidate_snapshot": {"audit_id": audit_id},
    }


# ─── Tests ─────────────────────────────────────────────────────────────────


def test_valid_labels(tmp_path: Path):
    """Labels válidos: solo ACTIONABLE, OBSERVATIONAL_ONLY, NOT_COMPARABLE, AMBIGUOUS."""
    candidates = [_sample_candidate("a1", "c1", "Test", "current_slower", 1.0, 0, 100)]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, dataset_path.read_bytes().__hash__() if False else "0" * 64)

    result = run_audit(dataset_path, labels_path)

    assert result["status"] == "SHADOW_AUDIT_ONLY"
    assert result["summary"]["total_labeled_candidates"] == 1
    assert result["summary"]["count_by_label"]["ACTIONABLE"] == 1


def test_actionable_label(tmp_path: Path):
    """Un candidato ACTIONABLE con delta positivo y canales presentes."""
    channels = {
        "speed_delta_avg": -2.0,
        "throttle_delta_avg": -1.5,
        "brake_delta_avg": 1.0,
        "steering_delta_avg": 0.3,
    }
    candidates = [_sample_candidate("a1", "c1", "Imola", "current_slower", 1.2, 50, 200, channels)]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    assert result["summary"]["count_by_label"]["ACTIONABLE"] == 1
    assert result["labeled_items"][0]["channel_count"] == 4
    assert result["labeled_items"][0]["zone_length_m"] == 150.0


def test_observational_label(tmp_path: Path):
    """Un candidato OBSERVATIONAL_ONLY."""
    candidates = [_sample_candidate("a1", "c1", "Monza", "current_slower", 0.05, 0, 100)]
    labels = [_sample_label("a1", "OBSERVATIONAL_ONLY")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    assert result["summary"]["count_by_label"]["OBSERVATIONAL_ONLY"] == 1
    assert result["summary"]["count_by_label"].get("ACTIONABLE", 0) == 0


def test_ambiguous_label(tmp_path: Path):
    """Un candidato AMBIGUOUS."""
    candidates = [_sample_candidate("a1", "c1", "Fuji", "current_slower", 0.08, 0, 100)]
    labels = [_sample_label("a1", "AMBIGUOUS")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    assert result["summary"]["count_by_label"]["AMBIGUOUS"] == 1


def test_not_comparable_label(tmp_path: Path):
    """Un candidato NOT_COMPARABLE."""
    candidates = [_sample_candidate("a1", "c1", "Interlagos", "current_slower", 0.02, 0, 100)]
    labels = [_sample_label("a1", "NOT_COMPARABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    assert result["summary"]["count_by_label"]["NOT_COMPARABLE"] == 1


def test_missing_numerical_channel(tmp_path: Path):
    """Candidato sin canales numéricos (solo evidencia delta)."""
    candidate_no_channels = _sample_candidate(
        "a1", "c1", "Test", "current_slower", 1.0, 0, 100, channels={}
    )
    candidates = [candidate_no_channels]
    labels = [_sample_label("a1", "OBSERVATIONAL_ONLY")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    assert result["labeled_items"][0]["channel_count"] == 0
    assert result["labeled_items"][0]["channel_presence"] == {
        "speed_delta_avg": False,
        "throttle_delta_avg": False,
        "brake_delta_avg": False,
        "steering_delta_avg": False,
    }


def test_zero_delta(tmp_path: Path):
    """Candidato con delta_change_s = 0."""
    candidate = _sample_candidate("a1", "c1", "Test", "current_faster", 0.0, 0, 100)
    candidates = [candidate]
    labels = [_sample_label("a1", "OBSERVATIONAL_ONLY")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    assert result["labeled_items"][0]["delta_change_s"] == 0.0
    assert result["labeled_items"][0]["delta_sign"] == "current_faster"


def test_invalid_tampered_labels_rejected(tmp_path: Path):
    """Labels con human_label inválido deben ser excluidos del audit (no producen error)."""
    invalid_label = {
        "audit_id": "bad_id",
        "human_label": "INVALID_LABEL",
        "review_notes": "",
        "reviewed_at_utc": "2026-08-17T00:00:00+00:00",
        "candidate_snapshot": {"audit_id": "bad_id"},
    }
    candidates = [
        _sample_candidate("a1", "c1", "Test", "current_slower", 1.0, 0, 100),
    ]
    labels = [invalid_label]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    # El label inválido no aparece en count_by_label
    assert result["summary"]["total_labeled_candidates"] == 0
    assert "INVALID_LABEL" not in result["summary"]["count_by_label"]


def test_deterministic_output(tmp_path: Path):
    """Dos ejecuciones con mismo input producen JSON determinista (excepto timestamp)."""
    channels = {
        "speed_delta_avg": -2.0,
        "throttle_delta_avg": -1.5,
        "brake_delta_avg": 1.0,
        "steering_delta_avg": 0.3,
    }
    candidates = [_sample_candidate("a1", "c1", "Imola", "current_slower", 1.2, 50, 200, channels)]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result1 = run_audit(dataset_path, labels_path)
    result2 = run_audit(dataset_path, labels_path)

    # Remover timestamp para comparar
    del result1["metadata"]["generated_at_utc"]
    del result2["metadata"]["generated_at_utc"]

    assert json.dumps(result1, sort_keys=True) == json.dumps(result2, sort_keys=True)


def test_contract_fields(tmp_path: Path):
    """Verificar que los campos del contract están presentes y correctos."""
    candidates = [_sample_candidate("a1", "c1", "Test", "current_slower", 1.0, 0, 100)]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    policy = result["metadata"]["policy"]
    assert policy["production_policy_changed"] is False
    assert policy["historical_actions_authorized"] is False
    assert policy["thresholds_promoted"] is False
    assert policy["human_labels_are_ground_truth"] is True
    assert result["status"] == "SHADOW_AUDIT_ONLY"


def test_channel_availability_distribution(tmp_path: Path):
    """Verificar que la distribución de canales se calcula correctamente."""
    # Dos candidatos: uno con canales throttle+brake, otro con solo speed
    ch1 = {"throttle_delta_avg": -1.0, "brake_delta_avg": 0.5}
    ch2 = {"speed_delta_avg": -3.0}

    candidates = [
        _sample_candidate("a1", "c1", "Imola", "current_slower", 1.2, 0, 100, ch1),
        _sample_candidate("a2", "c2", "Imola", "current_faster", -0.5, 0, 100, ch2),
    ]
    labels = [
        _sample_label("a1", "ACTIONABLE"),
        _sample_label("a2", "OBSERVATIONAL_ONLY"),
    ]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    availability = result["distributions"]["channel_availability_by_label"]
    assert availability["ACTIONABLE"]["speed_delta_avg"] == 0
    assert availability["ACTIONABLE"]["throttle_delta_avg"] == 1
    assert availability["ACTIONABLE"]["brake_delta_avg"] == 1


def test_delta_sign_by_label(tmp_path: Path):
    """Verificar que los signos de delta se distribuyen correctamente por label."""
    candidates = [
        _sample_candidate("a1", "c1", "Imola", "current_slower", 1.0, 0, 100),
        _sample_candidate("a2", "c2", "Imola", "current_faster", -0.5, 0, 100),
    ]
    labels = [
        _sample_label("a1", "ACTIONABLE"),
        _sample_label("a2", "ACTIONABLE"),
    ]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    delta_dist = result["distributions"]["count_by_delta_sign_and_label"]
    assert "current_slower" in delta_dist
    assert "current_faster" in delta_dist
    assert delta_dist["current_slower"]["ACTIONABLE"] == 1
    assert delta_dist["current_faster"]["ACTIONABLE"] == 1


def test_serialize_item(tmp_path: Path):
    """_serialize_item produce un diccionario serializable."""
    item = {
        "audit_id": "test_1",
        "human_label": "ACTIONABLE",
        "review_notes": "test notes",
        "candidate_id": "c1",
        "context": {"track": "Test", "track_layout": "Test", "vehicle_variant": "LMP2_ELMS", "car_name_raw": "Test"},
        "delta_sign": "current_slower",
        "delta_change_s": 1.0,
        "start_distance_m": 0.0,
        "end_distance_m": 100.0,
        "zone_length_m": 100.0,
        "speed_delta_avg": -2.0,
        "throttle_delta_avg": -1.0,
        "brake_delta_avg": 0.5,
        "channel_presence": {"speed_delta_avg": True, "throttle_delta_avg": True, "brake_delta_avg": True, "steering_delta_avg": False},
        "channel_count": 3,
        "location_label": "T1",
        "profile_localization": "not_available",
    }

    serialized = _serialize_item(item)

    assert serialized["audit_id"] == "test_1"
    assert serialized["human_label"] == "ACTIONABLE"
    assert serialized["channel_count"] == 3
    assert set(serialized.keys()) == {
        "audit_id", "human_label", "candidate_id", "context",
        "delta_sign", "delta_change_s", "start_distance_m", "end_distance_m",
        "zone_length_m", "speed_delta_avg", "throttle_delta_avg", "brake_delta_avg",
        "channel_presence", "channel_count", "location_label", "profile_localization",
    }


def test_missing_feature_inventory(tmp_path: Path):
    """Verificar que el inventario de features faltantes contiene los campos esperados."""
    candidates = [_sample_candidate("a1", "c1", "Test", "current_slower", 1.0, 0, 100)]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    # El inventario debe incluir los campos esperados
    missing = set(result["missing_feature_inventory"])
    assert "human_label" in missing
    assert "candidate_id" in missing
    assert "track" in missing
    assert "delta_sign" in missing
    assert "zone_length_m" in missing


def test_missing_feature_inventory(tmp_path: Path):
    """Verificar que el inventario de features faltantes contiene los campos esperados."""
    channels = {
        "speed_delta_avg": -2.0,
        "throttle_delta_avg": -1.5,
        "brake_delta_avg": 1.0,
        "steering_delta_avg": 0.3,
    }
    candidates = [_sample_candidate("a1", "c1", "Test", "current_slower", 1.0, 0, 100, channels)]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    # Todos los campos esperados están presentes en los items — inventario vacío
    missing = set(result["missing_feature_inventory"])
    assert missing == set()  # no features should be missing


def test_missing_feature_inventory_records_absent_field(tmp_path: Path):
    """Si un campo esperado falta en el corpus, debe quedar registrado."""
    # Construir un dataset donde NO hay channels ni delta — todos los items tendrán None
    # para speed_delta_avg, throttle_delta_avg, brake_delta_avg, etc.
    candidates = [
        {
            "audit_id": "a1",
            "candidate_id": "c1",
            "context": {
                "track": "Test",
                "track_layout": "Test",
                "vehicle_variant": "LMP2_ELMS",
                "car_name_raw": "Test Car",
            },
            "delta_sign": "current_slower",
            "evidence": {
                "delta_change_s": 1.0,
                "start_distance_m": 0.0,
                "end_distance_m": 100.0,
            },
            "observational_channel_evidence": {},
        },
    ]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    # speed_delta_avg, throttle_delta_avg, brake_delta_avg deben aparecer como ausentes
    missing = set(result["missing_feature_inventory"])
    assert "speed_delta_avg" in missing
    assert "throttle_delta_avg" in missing
    assert "brake_delta_avg" in missing
    # Pero no deberían faltar los campos estructurales base
    assert "human_label" not in missing
    assert "delta_sign" not in missing


def test_channel_sign_counts_correct(tmp_path: Path):
    """Los conteos de signo positivos/negativos/zero de brake/throttle/speed deben ser correctos."""
    # Simular 3 candidatos con canales conocidos
    ch1 = {"speed_delta_avg": -5.0, "throttle_delta_avg": -1.0, "brake_delta_avg": 2.0}
    ch2 = {"speed_delta_avg": -3.0, "throttle_delta_avg": 1.5, "brake_delta_avg": -0.5}
    ch3 = {"speed_delta_avg": 0.0, "throttle_delta_avg": 0.0, "brake_delta_avg": 0.0}

    candidates = [
        _sample_candidate("a1", "c1", "Test", "current_slower", 1.0, 0, 100, ch1),
        _sample_candidate("a2", "c2", "Test", "current_slower", 2.0, 0, 200, ch2),
        _sample_candidate("a3", "c3", "Test", "current_slower", 0.5, 0, 50, ch3),
    ]
    labels = [
        _sample_label("a1", "ACTIONABLE"),
        _sample_label("a2", "ACTIONABLE"),
        _sample_label("a3", "ACTIONABLE"),
    ]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    sigs = result["distributions"]["channel_sign_distribution_by_label"]["ACTIONABLE"]

    # brake_delta_avg: ch1=positive, ch2=negative, ch3=zero_or_none
    assert sigs["brake_delta_avg"]["positive"] == 1
    assert sigs["brake_delta_avg"]["negative"] == 1
    assert sigs["brake_delta_avg"]["zero_or_none"] == 1

    # speed_delta_avg: ch1=negative, ch2=negative, ch3=zero
    assert sigs["speed_delta_avg"]["negative"] == 2
    assert sigs["speed_delta_avg"]["positive"] == 0
    assert sigs["speed_delta_avg"]["zero_or_none"] == 1

    # throttle_delta_avg: ch1=negative, ch2=positive, ch3=zero
    assert sigs["throttle_delta_avg"]["negative"] == 1
    assert sigs["throttle_delta_avg"]["positive"] == 1
    assert sigs["throttle_delta_avg"]["zero_or_none"] == 1


def test_brake_throttle_cross_tabs(tmp_path: Path):
    """Presencia y signos brake x throttle se cruzan correctamente por label."""
    ch1 = {"throttle_delta_avg": -1.0, "brake_delta_avg": 0.5}
    ch2 = {"throttle_delta_avg": 2.0}
    ch3 = {"brake_delta_avg": -1.0}
    ch4 = {}

    candidates = [
        _sample_candidate("a1", "c1", "Test", "current_slower", 1.0, 0, 100, ch1),
        _sample_candidate("a2", "c2", "Test", "current_slower", 1.0, 0, 100, ch2),
        _sample_candidate("a3", "c3", "Test", "current_slower", 1.0, 0, 100, ch3),
        _sample_candidate("a4", "c4", "Test", "current_slower", 1.0, 0, 100, ch4),
    ]
    labels = [_sample_label(audit_id, "ACTIONABLE") for audit_id in ("a1", "a2", "a3", "a4")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    presence = result["distributions"]["brake_throttle_presence_by_label"]["ACTIONABLE"]
    assert presence == {
        "both": 1,
        "brake_only": 1,
        "neither": 1,
        "throttle_only": 1,
    }

    signs = result["distributions"]["brake_throttle_sign_by_label"]["ACTIONABLE"]
    assert signs == {
        "brake_neg_throttle_zero": 1,
        "brake_pos_throttle_neg": 1,
        "brake_zero_throttle_pos": 1,
        "brake_zero_throttle_zero": 1,
    }


def test_present_fields_not_in_missing_inventory(tmp_path: Path):
    """Los campos presentes no deben aparecer en missing_feature_inventory."""
    channels = {
        "speed_delta_avg": -2.0,
        "throttle_delta_avg": -1.5,
        "brake_delta_avg": 1.0,
        "steering_delta_avg": 0.3,
    }
    candidates = [_sample_candidate("a1", "c1", "Imola", "current_slower", 1.2, 50, 200, channels)]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    missing = set(result["missing_feature_inventory"])
    # Todos los campos deberían estar presentes
    assert missing == set()

    # Verificar explícitamente que los campos clave no están en missing
    assert "human_label" not in missing
    assert "candidate_id" not in missing
    assert "track" not in missing
    assert "delta_sign" not in missing
    assert "zone_length_m" not in missing
    assert "speed_delta_avg" not in missing


def test_deterministic_output_preserved(tmp_path: Path):
    """Verificar que las dos ejecuciones con mismo input producen JSON determinista (excepto timestamp)."""
    channels = {
        "speed_delta_avg": -2.0,
        "throttle_delta_avg": -1.5,
        "brake_delta_avg": 1.0,
        "steering_delta_avg": 0.3,
    }
    candidates = [_sample_candidate("a1", "c1", "Imola", "current_slower", 1.2, 50, 200, channels)]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result1 = run_audit(dataset_path, labels_path)
    result2 = run_audit(dataset_path, labels_path)

    # Remover timestamp para comparar
    del result1["metadata"]["generated_at_utc"]
    del result2["metadata"]["generated_at_utc"]

    assert json.dumps(result1, sort_keys=True) == json.dumps(result2, sort_keys=True)


def test_no_llm_call_no_scores_no_thresholds(tmp_path: Path):
    """Verificar que el output no contiene scores ni ranking global."""
    candidates = [_sample_candidate("a1", "c1", "Test", "current_slower", 1.0, 0, 100)]
    labels = [_sample_label("a1", "ACTIONABLE")]

    dataset_path = _build_dataset_path(tmp_path, candidates)
    labels_path = _build_labels_path(tmp_path, labels, "0" * 64)

    result = run_audit(dataset_path, labels_path)

    output_text = json.dumps(result, sort_keys=True)

    # Verificar que no hay campos de score o ranking
    assert "actionability_score" not in output_text
    assert '"ranking"' not in output_text
    assert "classifier" not in output_text
    # Verificar que thresholds_promoted es false, no que la palabra threshold aparece como campo
    assert result["metadata"]["policy"]["thresholds_promoted"] is False
