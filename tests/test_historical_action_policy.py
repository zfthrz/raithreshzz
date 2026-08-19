"""tests/test_historical_action_policy.py — tests unitarios v0.2

Cubre:
  1. Vocabulary cerrado: throttle/brake mapean a acciones correctas.
  2. Anti-regresión: current_faster → WITHHELD.
  3. No authorized-empty: current_slower con speed/time → WITHHELD.
  4. Multiple actions: candidate con throttle + brake → ambas acciones.
  5. Speed/time never actions: speed/time observations no generan acciones.
  6. Unknown observation code: validator failure.
  7. Observation codes known vs unknown.
  8. No mapped action → WITHHELD.
  9. Candidate IDs únicos: duplicate → validator FAIL.
  10. Tampered source hash → validator FAIL.
  11. authorized=true + actions=[] → validator FAIL.
  12. Deterministic output.
  13. Session reference remains authority.
  14. historical_actions_authorized = false.
  15. Backward compatibility with v0.1 alias.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import historical_action_policy
from historical_action_policy import (
    ACTION_POLICY_VERSION,
    SCHEMA_VERSION,
    STATUS_AUTHORIZED,
    OBSERVATION_TO_ACTION,
    ACTION_TEXT,
    KNOWN_OBSERVATION_CODES,
    KNOWN_NON_MAPPABLE_CODES,
    build_action_candidates,
)
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
            {
                "candidate_id": "slow:cand_speedonly",
                "context": _context(),
                "delta_sign": "current_slower",
                "location_label": "T3 - Speed Only",
                "delta_change_s": 0.5,
                "authorized_observations": [
                    "time_loss",
                    "current_speed_lower",
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
                {
                    "candidate_id": "slow:cand_speedonly",
                    "significance": "secondary",
                    "observation_codes": [
                        "time_loss",
                        "current_speed_lower",
                    ],
                },
            ]
        },
    }


def _write_selection(tmp_path: Path, selection: dict | None = None) -> Path:
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(selection or _selection(), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ── Constants verification ──────────────────────────────────────────────────


def test_policy_version_is_0_2():
    assert ACTION_POLICY_VERSION == "0.2"


def test_status_is_authorized():
    assert STATUS_AUTHORIZED == "HISTORICAL_ACTION_CANDIDATES_VALIDATED"


def test_closed_vocabulary_mapping():
    assert OBSERVATION_TO_ACTION == {
        "current_throttle_higher": "reduce_throttle",
        "current_throttle_lower": "increase_throttle",
        "current_brake_higher": "reduce_brake",
        "current_brake_lower": "increase_brake",
    }


def test_action_text_coverage():
    assert set(ACTION_TEXT) == {"reduce_throttle", "increase_throttle", "reduce_brake", "increase_brake"}


def test_known_observation_codes():
    """All observation codes in mapping are known."""
    for code in OBSERVATION_TO_ACTION:
        assert code in KNOWN_OBSERVATION_CODES


def test_known_non_mappable_codes():
    """Speed and time codes are known non-mappable."""
    assert KNOWN_NON_MAPPABLE_CODES == {"time_loss", "time_gain", "current_speed_lower", "current_speed_higher"}


# ── Core behavior ───────────────────────────────────────────────────────────


def test_actions_only_for_slower_lap_and_speed_time_never_actions(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))

    assert output["status"] == "HISTORICAL_ACTION_CANDIDATES_VALIDATED"
    assert len(output["actions"]) == 1
    assert output["actions"][0]["candidate_id"] == "slow:cand_001"
    assert output["actions"][0]["actions"] == ["reduce_throttle", "reduce_brake"]
    assert len(output["withheld"]) == 2


def test_anti_regression_current_faster_withheld(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))
    # fast:cand_001 is withheld (current_lap_faster_no_actions)
    # slow:cand_speedonly is also withheld (no_mappable_actions)
    assert len(output["withheld"]) == 2
    assert any(w["candidate_id"] == "fast:cand_001" for w in output["withheld"])


def test_speed_time_never_actions(tmp_path: Path):
    """current_slower con speed/time → WITHHELD (no_mappable_actions)."""
    selection = _selection()
    # slow:cand_speedonly is current_slower with only speed observations
    output = build_action_candidates(_write_selection(tmp_path, selection))

    assert len(output["withheld"]) == 2
    # Check that the speed-only candidate is withheld
    speed_only_withheld = [w for w in output["withheld"] if w["candidate_id"] == "slow:cand_speedonly"]
    assert len(speed_only_withheld) == 1
    assert speed_only_withheld[0]["reason"] == "no_mappable_actions"


def test_multiple_actions_from_multiple_channels(tmp_path: Path):
    """current_slower con throttle + brake → ambas acciones."""
    selection = _selection()
    output = build_action_candidates(_write_selection(tmp_path, selection))
    actions = output["actions"][0]

    assert actions["candidate_id"] == "slow:cand_001"
    # Both throttle and brake are mappable
    assert len(actions["actions"]) == 2
    assert set(actions["actions"]) == {"reduce_throttle", "reduce_brake"}


def test_no_mappable_action_withheld(tmp_path: Path):
    """current_slower con observation_codes pero ninguno mappable → WITHHELD."""
    selection = {
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": [
            {
                "candidate_id": "slow:cand_speedonly",
                "context": _context(),
                "delta_sign": "current_slower",
                "location_label": "T3 - Speed Only",
                "delta_change_s": 0.5,
                "authorized_observations": ["time_loss", "current_speed_lower"],
            },
        ],
        "llm_selection": {
            "selected_candidates": [
                {
                    "candidate_id": "slow:cand_speedonly",
                    "significance": "primary",
                    "observation_codes": ["time_loss", "current_speed_lower"],
                },
            ]
        },
    }
    output = build_action_candidates(_write_selection(tmp_path, selection))

    assert len(output["withheld"]) == 1
    assert output["withheld"][0]["reason"] == "no_mappable_actions"


def test_unknown_observation_code_raises(tmp_path: Path):
    """current_slower con observation code unknown → ValueError."""
    selection = {
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": [
            {
                "candidate_id": "slow:cand_unknown",
                "context": _context(),
                "delta_sign": "current_slower",
                "location_label": "T4 - Unknown",
                "delta_change_s": 0.5,
                "authorized_observations": ["time_loss", "unknown_code"],
            },
        ],
        "llm_selection": {
            "selected_candidates": [
                {
                    "candidate_id": "slow:cand_unknown",
                    "significance": "primary",
                    "observation_codes": ["time_loss", "unknown_code"],
                },
            ]
        },
    }
    path = _write_selection(tmp_path, selection)

    with pytest.raises(ValueError, match="unknown"):
        build_action_candidates(path)


def test_deterministic_output(tmp_path: Path):
    """Ejecutar dos veces → mismo SHA."""
    path = _write_selection(tmp_path)
    output1 = build_action_candidates(path)
    output2 = build_action_candidates(path)

    assert output1 == output2


def test_session_reference_remains_authority(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))
    assert output["coaching_authority"]["session_reference_remains_authority"] is True
    assert output["metadata"]["policy"]["session_reference_remains_authority"] is True


def test_historical_actions_authorized_false(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))
    assert output["coaching_authority"]["historical_actions_authorized"] is False
    assert output["metadata"]["policy"]["historical_actions_authorized"] is False


def test_classified_observation_codes_present(tmp_path: Path):
    """v0.2: classified_observation_codes debe estar en actions y withheld."""
    output = build_action_candidates(_write_selection(tmp_path))

    # Check actions
    for action in output["actions"]:
        classification = action["authorization"]["classified_observation_codes"]
        assert set(classification) == {"mappable", "non_mappable", "unknown"}
        assert isinstance(classification["mappable"], list)
        assert isinstance(classification["non_mappable"], list)
        assert isinstance(classification["unknown"], list)

    # Check withheld
    for item in output["withheld"]:
        classification = item["classified_observation_codes"]
        assert set(classification) == {"mappable", "non_mappable", "unknown"}


# ── Validator tests ─────────────────────────────────────────────────────────


def test_validator_passes_on_valid_output(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))
    errors = validate(output)
    assert errors == []


def test_validator_rejects_tampered_actions(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))
    tampered = copy.deepcopy(output)
    tampered["actions"][0]["actions"] = ["reduce_throttle", "increase_speed"]

    errors = validate(tampered)
    assert any("no coinciden" in e for e in errors)


def test_validator_rejects_internally_valid_but_source_divergent_action(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))
    tampered = copy.deepcopy(output)
    tampered["actions"][0]["location_label"] = "ubicación alterada"

    errors = validate(tampered)

    assert "actions no coinciden con la política determinista" in errors


def test_validator_rejects_anti_regression_violation(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))
    tampered = copy.deepcopy(output)
    tampered["actions"].append(
        {
            "candidate_id": "fast:cand_001",
            "delta_sign": "current_faster",
            "actions": ["reduce_throttle"],
        }
    )

    errors = validate(tampered)
    assert any("anti-regresión" in e for e in errors)


def test_validator_rejects_empty_authorization(tmp_path: Path):
    """authorized=true + actions=[] → validator FAIL."""
    output = build_action_candidates(_write_selection(tmp_path))
    # Inject an action with empty actions list
    tampered = copy.deepcopy(output)
    tampered["actions"].append({
        "candidate_id": "slow:cand_empty",
        "actions": [],
        "authorization": {"authorized": True, "policy_version": ACTION_POLICY_VERSION},
        "delta_sign": "current_slower",
    })

    errors = validate(tampered)
    assert any("empty authorization" in e for e in errors)


def test_validator_rejects_wrong_source_hash(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))
    output["metadata"]["source_selection_sha256"] = "0" * 64

    errors = validate(output)
    assert any("sha256 no coincide" in e for e in errors)


def test_validator_rejects_unknown_observation_code(tmp_path: Path):
    """validator rejects document with unknown observation codes in actions."""
    output = build_action_candidates(_write_selection(tmp_path))
    tampered = copy.deepcopy(output)
    tampered["actions"][0]["authorization"]["observation_codes"].append("unknown_code")

    errors = validate(tampered)
    assert any("desconocido" in e for e in errors)


def test_validator_rejects_duplicate_candidate_id(tmp_path: Path):
    """duplicate candidate_id → validator FAIL."""
    output = build_action_candidates(_write_selection(tmp_path))
    tampered = copy.deepcopy(output)
    # Add duplicate candidate_id
    tampered["actions"].append(dict(tampered["actions"][0]))
    tampered["actions"][-1]["candidate_id"] = "slow:cand_001"

    errors = validate(tampered)
    assert any("duplicado" in e for e in errors)


def test_validator_rejects_speed_action(tmp_path: Path):
    """speed actions are prohibited."""
    output = build_action_candidates(_write_selection(tmp_path))
    tampered = copy.deepcopy(output)
    tampered["actions"][0]["actions"].append("increase_speed")

    errors = validate(tampered)
    assert any("velocidad" in e or "prohibido" in e for e in errors)


def test_validator_rejects_wrong_policy_version(tmp_path: Path):
    output = build_action_candidates(_write_selection(tmp_path))
    tampered = copy.deepcopy(output)
    tampered["actions"][0]["authorization"]["policy_version"] = "0.1"

    errors = validate(tampered)
    assert any("policy_version" in e for e in errors)


def test_cross_check_no_overlap_actions_withheld(tmp_path: Path):
    """Un candidate_id no debe aparecer en ambos arrays."""
    # Build output and tamper to create overlap
    output = build_action_candidates(_write_selection(tmp_path))
    tampered = copy.deepcopy(output)
    # Move a candidate from withheld to actions
    fast_candidate = output["withheld"][0]
    tampered["actions"].append({
        "candidate_id": fast_candidate["candidate_id"],
        "actions": ["reduce_throttle"],
        "authorization": {"authorized": True, "policy_version": ACTION_POLICY_VERSION},
        "delta_sign": "current_slower",
        "location_label": fast_candidate["location_label"],
    })

    errors = validate(tampered)
    assert any("aparece en actions y withheld" in e for e in errors)


def test_validator_rejects_historical_actions_authorized_true(tmp_path: Path):
    """historical_actions_authorized debe ser false."""
    output = build_action_candidates(_write_selection(tmp_path))
    tampered = copy.deepcopy(output)
    tampered["coaching_authority"]["historical_actions_authorized"] = True

    errors = validate(tampered)
    assert any("historical_actions_authorized" in e for e in errors)


# ── Backward compatibility ──────────────────────────────────────────────────


def test_alias_matches_versioned_source():
    """historical_action_policy.py es thin wrapper → imports v0.2 symbols."""
    root = Path(__file__).resolve().parents[1]
    import historical_action_policy as alias
    import historical_action_policy_v0_2 as source

    # Verify alias re-exports from source
    assert alias.ACTION_POLICY_VERSION == source.ACTION_POLICY_VERSION
    assert alias.ACTION_TEXT == source.ACTION_TEXT
    assert alias.OBSERVATION_TO_ACTION == source.OBSERVATION_TO_ACTION
    assert alias.KNOWN_OBSERVATION_CODES == source.KNOWN_OBSERVATION_CODES
    assert alias.KNOWN_NON_MAPPABLE_CODES == source.KNOWN_NON_MAPPABLE_CODES
    assert alias.build_action_candidates == source.build_action_candidates
    assert alias.main == source.main


def test_backward_compatible_imports():
    """Los imports del alias son compatibles con v0.2."""
    assert historical_action_policy.ACTION_POLICY_VERSION == "0.2"
    assert historical_action_policy.STATUS_AUTHORIZED == "HISTORICAL_ACTION_CANDIDATES_VALIDATED"
    assert historical_action_policy.KNOWN_OBSERVATION_CODES == KNOWN_OBSERVATION_CODES
    assert historical_action_policy.KNOWN_NON_MAPPABLE_CODES == KNOWN_NON_MAPPABLE_CODES


def test_build_action_candidates_via_alias(tmp_path: Path):
    """build_action_candidates a través del alias funciona correctamente."""
    output = historical_action_policy.build_action_candidates(_write_selection(tmp_path))
    assert output["status"] == "HISTORICAL_ACTION_CANDIDATES_VALIDATED"
