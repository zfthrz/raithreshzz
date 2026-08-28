from __future__ import annotations

import pytest

from h2_authority_gate import validate_authorized_h2


def _feature():
    return {
        "session_a": 1,
        "session_b": 2,
        "episode_pk_a": 10,
        "episode_pk_b": 20,
    }


def _decision(
    *,
    decision="MATCH",
    scope="COVERED_BY_TRACK_MATCH_BASELINE",
    match_authorized=True,
    reject_authorized=False,
):
    return {
        "pair_index": 0,
        "session_a": 1,
        "session_b": 2,
        "episode_pk_a": 10,
        "episode_pk_b": 20,
        "decision": decision,
        "authority": {
            "calibration_scope": scope,
            "production_match_authorized": match_authorized,
            "production_reject_authorized": reject_authorized,
        },
    }


def test_accepts_promoted_match():
    gate = validate_authorized_h2(
        [_feature()],
        [_decision()],
        {"matcher_version": "0.3"},
    )
    assert gate["inherited_reject_count"] == 0
    assert gate["unauthorized_match_count"] == 0


def test_blocks_inherited_reject():
    with pytest.raises(RuntimeError, match="inherited REJECT"):
        validate_authorized_h2(
            [_feature()],
            [_decision(decision="REJECT")],
            {"matcher_version": "0.3"},
        )


def test_blocks_match_without_authority():
    with pytest.raises(RuntimeError, match="MATCH sin production_match_authorized"):
        validate_authorized_h2(
            [_feature()],
            [_decision(match_authorized=False)],
            {"matcher_version": "0.3"},
        )


def test_accepts_exact_reject():
    gate = validate_authorized_h2(
        [_feature()],
        [
            _decision(
                decision="REJECT",
                scope="EXACT_VARIANT_CALIBRATION",
                match_authorized=True,
                reject_authorized=True,
            )
        ],
        {"matcher_version": "0.3"},
    )
    assert gate["decision_counts"] == {"REJECT": 1}


def test_requires_matcher_v03():
    with pytest.raises(ValueError, match="matcher v0.3"):
        validate_authorized_h2(
            [_feature()],
            [_decision()],
            {"matcher_version": "0.2"},
        )
