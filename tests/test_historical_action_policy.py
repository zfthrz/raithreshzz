from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from historical_action_policy import build_action_candidates
from validate_historical_actions import validate


def _context() -> dict:
    return {
        "track": "Autodromo Nazionale Monza",
        "track_layout": "Autodromo Nazionale Monza",
        "vehicle_variant": "LMP2_ELMS",
        "car_name_raw": "IDEC Sport #18",
    }


def _selection() -> dict:
    return {
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": [
            {
                "candidate_id": "slow:cand_001",
                "context": _context(),
                "delta_sign": "current_slower",
                "location_label": "T1 - Test",
                "delta_change_s": 0.337,
                "authorized_observations": [
                    "time_loss",
                    "current_speed_lower",
                    "current_throttle_higher",
                    "current_brake_higher",
                ],
            },
            {
                "candidate_id": "fast:cand_001",
                "context": _context(),
                "delta_sign": "current_faster",
                "location_label": "T2 - Test",
                "delta_change_s": -0.2,
                "authorized_observations": [
                    "time_gain",
                    "current_speed_higher",
                    "current_throttle_higher",
                ],
            },
        ],
        "llm_selection": {
            "selected_candidates": [
                {
                    "candidate_id": "slow:cand_001",
                    "significance": "primary",
                    "observation_codes": [
                        "time_loss",
                        "current_speed_lower",
                        "current_throttle_higher",
                        "current_brake_higher",
                    ],
                },
                {
                    "candidate_id": "fast:cand_001",
                    "significance": "secondary",
                    "observation_codes": ["time_gain", "current_speed_higher"],
                },
            ]
        },
    }


def _write_selection(tmp_path: Path) -> Path:
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(_selection(), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_actions_only_for_slower_lap_and_speed_time_never_actions(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))

    assert output["status"] == "HISTORICAL_ACTIONS_AUTHORIZED"
    assert len(output["actions"]) == 1
    assert output["actions"][0]["candidate_id"] == "slow:cand_001"
    assert output["actions"][0]["actions"] == ["reduce_throttle", "reduce_brake"]
    assert output["actions"][0]["actions_text"] == [
        "reducir acelerador",
        "reducir freno",
    ]
    assert len(output["withheld"]) == 1
    assert output["withheld"][0]["reason"] == "current_lap_faster_no_actions"


def test_actions_artifact_passes_validator(tmp_path: Path):
    selection_path = _write_selection(tmp_path)
    output = build_action_candidates(selection_path)

    assert validate(output) == []
    assert output["coaching_authority"]["session_reference_remains_authority"] is True
    assert output["coaching_authority"]["historical_actions_authorized"] is True


def test_validator_rejects_tampered_actions(tmp_path: Path):
    selection_path = _write_selection(tmp_path)
    output = build_action_candidates(selection_path)
    tampered = copy.deepcopy(output)
    tampered["actions"][0]["actions"] = ["reduce_throttle", "increase_speed"]

    assert any("actions no coinciden" in error for error in validate(tampered))


def test_validator_rejects_anti_regression_violation(tmp_path: Path):
    selection_path = _write_selection(tmp_path)
    output = build_action_candidates(selection_path)
    tampered = copy.deepcopy(output)
    tampered["actions"].append(
        {
            "candidate_id": "fast:cand_001",
            "delta_sign": "current_faster",
            "actions": ["reduce_throttle"],
        }
    )

    errors = validate(tampered)
    assert any("anti-regresión" in error for error in errors)


def test_validator_rejects_wrong_source_hash(tmp_path: Path):
    selection_path = _write_selection(tmp_path)
    output = build_action_candidates(selection_path)
    output["metadata"]["source_selection_sha256"] = "0" * 64

    assert any("source_selection_sha256 no coincide" in error for error in validate(output))


def test_action_policy_aliases_match_versioned_sources():
    root = Path(__file__).resolve().parents[1]
    contracts = {
        "historical_action_policy.py": "historical_action_policy_v0_1.py",
        "validate_historical_actions.py": "validate_historical_actions_v0_1.py",
    }
    for alias_name, source_name in contracts.items():
        alias_hash = hashlib.sha256((root / alias_name).read_bytes()).digest()
        source_hash = hashlib.sha256((root / source_name).read_bytes()).digest()
        assert alias_hash == source_hash


def test_missing_selection_status_is_rejected(tmp_path: Path):
    selection = _selection()
    selection["status"] = "INVALID"
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(selection, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="no validada"):
        build_action_candidates(path)
