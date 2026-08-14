from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from historical_llm_analysis import (
    build_authorized_evidence,
    build_output,
    validate_response,
)
from runtime_paths import historical_llm_debug_dir, historical_llm_output_path
from validate_historical_llm_analysis import validate


def write_source(tmp_path: Path) -> tuple[Path, dict]:
    historical = tmp_path / "historical.duckdb"
    current = tmp_path / "current.duckdb"
    historical.write_bytes(b"historical")
    current.write_bytes(b"current")
    document = {
        "metadata": {"schema_version": "1.0", "cross_session_version": "0.1"},
        "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
        "context": {
            "track": "Fuji Speedway",
            "track_layout": "Fuji Speedway",
            "vehicle_variant": "LMP2_ELMS",
            "car_name_raw": "IDEC Sport",
        },
        "historical_reference": {
            "session_id": 1,
            "lap": 8,
            "source_database": str(historical),
        },
        "current_session_reference": {
            "session_id": 2,
            "lap": 5,
            "source_database": str(current),
        },
        "temporal_validation": {
            "status": "OK",
            "calculated_current_minus_historical_s": 1.28,
            "error_s": 0.0,
            "tolerance_s": 1e-6,
        },
        "spatial_comparison": {
            "zone_summary_count": 2,
            "zone_summaries": [
                {
                    "type": "loss",
                    "start_distance": 100.0,
                    "end_distance": 200.0,
                    "delta_change": 0.32,
                    "speed_delta_avg": -4.5,
                    "throttle_delta_avg": -2.0,
                    "brake_delta_avg": 1.5,
                    "steering_delta_avg": 0.4,
                },
                {
                    "type": "gain",
                    "start_distance": 200.0,
                    "end_distance": 260.0,
                    "delta_change": -0.12,
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
    path = tmp_path / "cross_session_comparison.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, document


def valid_response() -> dict:
    return {
        "overview_code": "current_lap_slower",
        "selected_zones": [
            {
                "zone_id": "zone_001",
                "significance": "primary",
                "observation_codes": ["time_loss", "current_speed_lower"],
            }
        ],
        "limitation_codes": ["single_lap_pair", "no_causal_inference"],
    }


def test_builds_and_validates_observational_output(tmp_path: Path):
    source_path, source = write_source(tmp_path)
    evidence = build_authorized_evidence(source)
    output = build_output(
        source_path,
        source,
        evidence,
        valid_response(),
        backend="ollama",
        model="ingenierov3",
    )

    assert validate(output) == []
    assert output["coaching_authority"]["historical_actions_authorized"] is False
    assert output["selected_evidence"] == [evidence["zones"][0]]
    assert "+1.280 s" in output["rendered_analysis"]


def test_rejects_unknown_zones_and_free_text_keys(tmp_path: Path):
    _, source = write_source(tmp_path)
    evidence = build_authorized_evidence(source)

    unknown = valid_response()
    unknown["selected_zones"][0]["zone_id"] = "zone_999"
    assert any("no existe" in error for error in validate_response(unknown, evidence))

    free_text = valid_response()
    free_text["recommendation"] = "frenar antes"
    assert "claves raíz fuera de contrato" in validate_response(free_text, evidence)


def test_rejects_unauthorized_overview_and_observation_codes(tmp_path: Path):
    _, source = write_source(tmp_path)
    evidence = build_authorized_evidence(source)
    wrong_overview = valid_response()
    wrong_overview["overview_code"] = "current_lap_faster"
    assert "overview_code no coincide con Python" in validate_response(
        wrong_overview, evidence
    )

    invented_claim = valid_response()
    invented_claim["selected_zones"][0]["observation_codes"] = [
        "time_gain",
        "current_speed_higher",
    ]
    assert any(
        "observation_codes no autorizados" in error
        for error in validate_response(invented_claim, evidence)
    )


def test_python_authorizes_only_deterministic_direction_codes(tmp_path: Path):
    _, source = write_source(tmp_path)
    evidence = build_authorized_evidence(source)

    assert evidence["contract"]["free_text_authorized"] is False
    assert evidence["authorized_overview_code"] == "current_lap_slower"
    assert evidence["zones"][0]["authorized_observations"] == [
        "time_loss",
        "current_speed_lower",
        "current_throttle_lower",
        "current_brake_higher",
    ]
    assert evidence["zones"][1]["authorized_observations"] == [
        "time_gain",
        "current_speed_higher",
        "current_throttle_higher",
        "current_brake_lower",
    ]


def test_validator_rejects_tampered_deterministic_evidence(tmp_path: Path):
    source_path, source = write_source(tmp_path)
    evidence = build_authorized_evidence(source)
    output = build_output(
        source_path,
        source,
        evidence,
        valid_response(),
        backend="deepseek",
        model="test-model",
    )
    tampered = copy.deepcopy(output)
    tampered["selected_evidence"][0]["delta_change_s"] = 99.0

    assert "selected_evidence no coincide exactamente con H5.2" in validate(tampered)


def test_runtime_paths_are_centralized_and_model_safe(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_GENERATED_DIR", str(tmp_path / "generated"))
    output = historical_llm_output_path(
        "telemetria/example.duckdb",
        backend="deepseek",
        model="model/name with spaces",
    )
    debug = historical_llm_debug_dir(
        "telemetria/example.duckdb",
        backend="deepseek",
    )

    assert output.parts[-3] == "h5_2_llm"
    assert output.name == "historical_comparison_v0_1_deepseek_model_name_with_spaces.json"
    assert debug.parts[-3:] == ("example", "debug", "deepseek")


def test_historical_llm_aliases_match_versioned_sources():
    root = Path(__file__).resolve().parents[1]
    contracts = {
        "historical_llm_analysis.py": "historical_llm_analysis_v0_1.py",
        "validate_historical_llm_analysis.py": (
            "validate_historical_llm_analysis_v0_1.py"
        ),
    }
    for alias_name, source_name in contracts.items():
        alias_hash = hashlib.sha256((root / alias_name).read_bytes()).digest()
        source_hash = hashlib.sha256((root / source_name).read_bytes()).digest()
        assert alias_hash == source_hash


def test_orchestrator_reuse_requires_historical_output_hash():
    root = Path(__file__).resolve().parents[1]
    source = (root / "race_engineer.py").read_text(encoding="utf-8")

    assert '"backend_script": script_signature(' in source
    assert "previous_h5_2_llm_sha" in source
    assert "== sha256_file(h5_2_llm_output)" in source
