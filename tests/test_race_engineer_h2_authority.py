from __future__ import annotations

import episode_pair_matcher
import race_engineer
import track_readiness


CONTEXT = ("Track", "Layout", "GT3")


def test_h2_authority_for_h3_prefers_exact_calibration(monkeypatch):
    monkeypatch.setattr(
        episode_pair_matcher,
        "CALIBRATIONS",
        {CONTEXT: {"status": "CALIBRATED_PROVISIONAL_LOW_EVIDENCE"}},
    )

    def must_not_run(**kwargs):
        raise AssertionError("readiness must not be consulted for exact calibration")

    monkeypatch.setattr(track_readiness, "build_track_readiness", must_not_run)

    scope, authorized = race_engineer.h2_authority_for_h3(*CONTEXT)

    assert scope == "EXACT_VARIANT_CALIBRATION"
    assert authorized is True


def test_h2_authority_for_h3_accepts_promoted_match_baseline(monkeypatch):
    monkeypatch.setattr(episode_pair_matcher, "CALIBRATIONS", {})
    monkeypatch.setattr(
        track_readiness,
        "build_track_readiness",
        lambda **kwargs: {
            "rows": [
                {
                    "track": CONTEXT[0],
                    "track_layout": CONTEXT[1],
                    "vehicle_variant": CONTEXT[2],
                    "overall_status": "COVERED_BY_TRACK_MATCH_BASELINE",
                }
            ]
        },
    )

    scope, authorized = race_engineer.h2_authority_for_h3(*CONTEXT)

    assert scope == "COVERED_BY_TRACK_MATCH_BASELINE"
    assert authorized is True


def test_h2_authority_for_h3_keeps_shadow_fail_closed(monkeypatch):
    monkeypatch.setattr(episode_pair_matcher, "CALIBRATIONS", {})
    monkeypatch.setattr(
        track_readiness,
        "build_track_readiness",
        lambda **kwargs: {
            "rows": [
                {
                    "track": CONTEXT[0],
                    "track_layout": CONTEXT[1],
                    "vehicle_variant": CONTEXT[2],
                    "overall_status": "TRACK_MATCH_BASELINE_SHADOW",
                }
            ]
        },
    )

    scope, authorized = race_engineer.h2_authority_for_h3(*CONTEXT)

    assert scope == "TRACK_MATCH_BASELINE_SHADOW"
    assert authorized is False


def test_h2_authority_for_h3_readiness_error_fails_closed(monkeypatch):
    monkeypatch.setattr(episode_pair_matcher, "CALIBRATIONS", {})

    def explode(**kwargs):
        raise ValueError("bad readiness evidence")

    monkeypatch.setattr(track_readiness, "build_track_readiness", explode)

    scope, authorized = race_engineer.h2_authority_for_h3(*CONTEXT)

    assert scope == "H2_AUTHORITY_UNAVAILABLE"
    assert authorized is False
