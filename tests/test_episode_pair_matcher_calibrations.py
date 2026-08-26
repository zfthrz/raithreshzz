from __future__ import annotations

from episode_pair_matcher import classify_pair, resolve_calibration

SPA = {
    "track": "Circuit de Spa-Francorchamps",
    "track_layout": "Circuit de Spa-Francorchamps",
    "vehicle_variant": "LMP2_ELMS",
}
IMOLA = {
    "track": "Autodromo Enzo e Dino Ferrari",
    "track_layout": "Autodromo Enzo e Dino Ferrari",
    "vehicle_variant": "LMP2_ELMS",
}
INTERLAGOS = {
    "track": "Autódromo José Carlos Pace",
    "track_layout": "Autódromo José Carlos Pace",
    "vehicle_variant": "LMP2_ELMS",
}
MONZA_HYPER = {
    "track": "Autodromo Nazionale Monza",
    "track_layout": "Autodromo Nazionale Monza",
    "vehicle_variant": "HYPER",
}
MONZA_LMP2 = {
    "track": "Autodromo Nazionale Monza",
    "track_layout": "Autodromo Nazionale Monza",
    "vehicle_variant": "LMP2_ELMS",
}
FUJI_LMP2 = {
    "track": "Fuji Speedway",
    "track_layout": "Fuji Speedway",
    "vehicle_variant": "LMP2_ELMS",
}


def pair(context: dict, *, center: float, overlap_union: float, overlap_shorter: float, shared: int = 1, jaccard: float | None = 1.0) -> dict:
    return {
        **context,
        "center_distance_abs_diff_m": center,
        "overlap_over_union": overlap_union,
        "overlap_over_shorter": overlap_shorter,
        "shared_channels": ["brake"] * shared,
        "channel_jaccard": jaccard,
        "per_channel_metrics": {
            "brake": {
                "coverage_abs_diff": 0.1,
                "mean_difference_similarity": 0.9,
                "peak_difference_similarity": 0.9,
                "onset_offset_abs_diff_m": 2.0,
                "end_offset_abs_diff_m": 2.0,
            }
        },
    }


def test_spa_calibration_keeps_v0_3_behavior():
    assert resolve_calibration(pair(SPA, center=2.0, overlap_union=1.0, overlap_shorter=1.0))[
        "status"
    ] == "CALIBRATED_PROVISIONAL_SINGLE_CONTEXT"
    assert classify_pair(pair(SPA, center=2.0, overlap_union=1.0, overlap_shorter=1.0))["decision"] == "MATCH"
    assert classify_pair(pair(SPA, center=300.0, overlap_union=0.0, overlap_shorter=0.0))["decision"] == "REJECT"
    assert classify_pair(pair(SPA, center=150.0, overlap_union=0.0, overlap_shorter=0.0))["decision"] == "AMBIGUOUS"


def test_imola_calibration_is_provisional_low_evidence():
    calibration = resolve_calibration(pair(IMOLA, center=0.0, overlap_union=0.58, overlap_shorter=1.0))
    assert calibration["status"] == "CALIBRATED_PROVISIONAL_LOW_EVIDENCE"
    assert calibration["provenance"]["batch_id"] == "5a8126df14"


def test_imola_match_requires_strong_overlap():
    assert classify_pair(pair(IMOLA, center=0.0, overlap_union=0.58, overlap_shorter=1.0))["decision"] == "MATCH"
    # SAME real con overlap cero: fail-closed a AMBIGUOUS
    assert classify_pair(pair(IMOLA, center=162.5, overlap_union=0.0, overlap_shorter=0.0))["decision"] == "AMBIGUOUS"
    # AMBIGUOUS humano con overlap bajo: AMBIGUOUS
    assert classify_pair(pair(IMOLA, center=0.0, overlap_union=0.12, overlap_shorter=1.0))["decision"] == "AMBIGUOUS"


def test_imola_reject_far_zero_overlap():
    assert classify_pair(pair(IMOLA, center=1000.0, overlap_union=0.0, overlap_shorter=0.0))["decision"] == "REJECT"
    # Borde conservador: entre 162.5 (SAME) y 600 (DIFFERENT min) queda AMBIGUOUS
    assert classify_pair(pair(IMOLA, center=250.0, overlap_union=0.0, overlap_shorter=0.0))["decision"] == "AMBIGUOUS"


def test_uncalibrated_context_fails_closed_to_ambiguous():
    uncalibrated = {
        "track": "Fictional Track",
        "track_layout": "Fictional Track",
        "vehicle_variant": "LMP3",
    }
    result = classify_pair(pair(uncalibrated, center=0.0, overlap_union=1.0, overlap_shorter=1.0))

    assert result["decision"] == "AMBIGUOUS"
    assert result["rule_id"] == "NO_CALIBRATION_FOR_CONTEXT"
    assert resolve_calibration(pair(uncalibrated, center=0.0, overlap_union=1.0, overlap_shorter=1.0)) is None


def test_fuji_calibration_is_provisional_and_evidence_backed():
    calibration = resolve_calibration(
        pair(FUJI_LMP2, center=0.0, overlap_union=1.0, overlap_shorter=1.0)
    )
    assert calibration["status"] == "CALIBRATED_PROVISIONAL_LOW_EVIDENCE"
    assert calibration["provenance"]["batch_id"] == "b0b0f526f9"
    assert calibration["provenance"]["evaluation_pairs"] == 0
    assert classify_pair(
        pair(FUJI_LMP2, center=0.0, overlap_union=1.0, overlap_shorter=1.0)
    )["decision"] == "MATCH"
    assert classify_pair(
        pair(FUJI_LMP2, center=400.0, overlap_union=0.0, overlap_shorter=0.0)
    )["decision"] == "REJECT"


def test_interlagos_calibration_is_provisional_low_evidence():
    calibration = resolve_calibration(
        pair(INTERLAGOS, center=5.0, overlap_union=0.85, overlap_shorter=1.0)
    )
    assert calibration["status"] == "CALIBRATED_PROVISIONAL_LOW_EVIDENCE"
    assert calibration["provenance"]["batch_id"] == "40c70a4dd3"
    assert calibration["provenance"]["evaluation_pairs"] == 5


def test_interlagos_match_reject_ambiguous():
    assert classify_pair(
        pair(INTERLAGOS, center=5.0, overlap_union=0.85, overlap_shorter=1.0)
    )["decision"] == "MATCH"
    # AMBIGUOUS humano a 378 m sin overlap: queda AMBIGUOUS (borde conservador)
    assert classify_pair(
        pair(INTERLAGOS, center=378.0, overlap_union=0.0, overlap_shorter=0.0)
    )["decision"] == "AMBIGUOUS"
    # DIFFERENT lejanos sin overlap: REJECT
    assert classify_pair(
        pair(INTERLAGOS, center=1941.0, overlap_union=0.0, overlap_shorter=0.0)
    )["decision"] == "REJECT"


def test_monza_calibration_is_reject_only_without_same_evidence():
    for context in (MONZA_HYPER, MONZA_LMP2):
        calibration = resolve_calibration(
            pair(context, center=3000.0, overlap_union=0.0, overlap_shorter=0.0)
        )
        assert calibration["status"] == "CALIBRATED_PROVISIONAL_LOW_EVIDENCE"
        assert calibration["thresholds"]["match_enabled"] is False
        assert calibration["provenance"]["match_core_disabled"]


def test_monza_rejects_far_pairs_and_fails_closed_without_match_core():
    # DIFFERENT lejanos sin overlap -> REJECT
    assert classify_pair(
        pair(MONZA_HYPER, center=2412.0, overlap_union=0.0, overlap_shorter=0.0)
    )["decision"] == "REJECT"
    assert classify_pair(
        pair(MONZA_LMP2, center=2468.0, overlap_union=0.0, overlap_shorter=0.0)
    )["decision"] == "REJECT"
    # Sin núcleo MATCH: un par cercano con overlap fuerte queda AMBIGUOUS (fail-closed)
    assert classify_pair(
        pair(MONZA_HYPER, center=5.0, overlap_union=0.9, overlap_shorter=1.0)
    )["decision"] == "AMBIGUOUS"
