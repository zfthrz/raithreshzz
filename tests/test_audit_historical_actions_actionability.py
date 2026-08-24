from __future__ import annotations

import hashlib
import json
from pathlib import Path

from audit_historical_actions_actionability import build_audit


def _actions_fixture() -> dict:
    return {
        "status": "HISTORICAL_ACTIONS_AUTHORIZED",
        "actions": [
            {
                "candidate_id": "a",
                "context": {"track": "T1"},
                "location_label": "Freno",
                "actions": ["reduce_brake"],
            },
            {
                "candidate_id": "b",
                "context": {"track": "T2"},
                "location_label": "Acelerador",
                "actions": ["increase_throttle"],
            },
            {
                "candidate_id": "c",
                "context": {"track": "T3"},
                "location_label": "Mixto",
                "actions": ["reduce_throttle", "reduce_brake"],
            },
        ],
    }


def _write_actions(tmp_path: Path) -> Path:
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(_actions_fixture(), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_classifies_brake_throttle_and_mixed(tmp_path: Path):
    audit = build_audit(_write_actions(tmp_path))

    assert audit["status"] == "SHADOW_OBSERVATIONAL_ONLY"
    assert audit["counts"] == {
        "brake_only": 1,
        "throttle_only": 1,
        "mixed_brake_throttle": 1,
    }
    assert audit["mixed_cue_candidates"] == ["Mixto"]
    assert audit["records"][0]["classification"] == "brake_only"
    assert audit["records"][1]["classification"] == "throttle_only"
    assert audit["records"][2]["classification"] == "mixed_brake_throttle"


def test_rejects_non_action_artifact(tmp_path: Path):
    payload = _actions_fixture()
    payload["status"] = "SHADOW_OBSERVATIONAL_ONLY"
    path = tmp_path / "actions.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    try:
        build_audit(path)
    except ValueError as exc:
        assert "no es de acciones autorizadas" in str(exc)
    else:
        raise AssertionError("artefacto no autorizado fue aceptado")


def test_accepts_validated_candidate_artifact_with_shadow_authority(tmp_path: Path):
    payload = _actions_fixture()
    payload["status"] = "HISTORICAL_ACTION_CANDIDATES_VALIDATED"
    payload["coaching_authority"] = {
        "session_reference_remains_authority": True,
        "historical_actions_authorized": False,
    }
    path = tmp_path / "actions.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    audit = build_audit(path)

    assert audit["status"] == "SHADOW_OBSERVATIONAL_ONLY"
    assert audit["counts"] == {
        "brake_only": 1,
        "throttle_only": 1,
        "mixed_brake_throttle": 1,
    }


def test_rejects_artifact_with_authorized_actions(tmp_path: Path):
    payload = _actions_fixture()
    payload["status"] = "HISTORICAL_ACTION_CANDIDATES_VALIDATED"
    payload["coaching_authority"] = {"historical_actions_authorized": True}
    path = tmp_path / "actions.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    try:
        build_audit(path)
    except ValueError as exc:
        assert "autoriza acciones históricas" in str(exc)
    else:
        raise AssertionError("artefacto con autorización fue aceptado")


def test_audit_aliases_match_versioned_sources():
    root = Path(__file__).resolve().parents[1]
    alias_hash = hashlib.sha256(
        (root / "audit_historical_actions_actionability.py").read_bytes()
    ).digest()
    source_hash = hashlib.sha256(
        (root / "audit_historical_actions_actionability_v0_1.py").read_bytes()
    ).digest()
    assert alias_hash == source_hash
