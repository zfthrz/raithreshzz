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
    fuji = {
        "track": "Fuji Speedway",
        "track_layout": "Fuji Speedway",
        "vehicle_variant": "LMP2_ELMS",
    }
    result = classify_pair(pair(fuji, center=0.0, overlap_union=1.0, overlap_shorter=1.0))

    assert result["decision"] == "AMBIGUOUS"
    assert result["rule_id"] == "NO_CALIBRATION_FOR_CONTEXT"
    assert resolve_calibration(pair(fuji, center=0.0, overlap_union=1.0, overlap_shorter=1.0)) is None
