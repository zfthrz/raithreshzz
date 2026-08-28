from race_engineer_gui import (
    READINESS_STATUS_COLORS,
    READINESS_STATUS_LABELS,
    track_readiness_status_tooltip,
)


def test_gui_distinguishes_hierarchical_track_readiness_states():
    assert READINESS_STATUS_COLORS["CURRENT_REQUIREMENTS_SATISFIED"] != (
        READINESS_STATUS_COLORS["COVERED_BY_TRACK_MATCH_BASELINE"]
    )
    assert READINESS_STATUS_COLORS["COVERED_BY_TRACK_MATCH_BASELINE"] != (
        READINESS_STATUS_COLORS["TRACK_MATCH_BASELINE_SHADOW"]
    )
    assert "exacta" in READINESS_STATUS_LABELS[
        "CURRENT_REQUIREMENTS_SATISFIED"
    ].casefold()
    assert "match-only" in READINESS_STATUS_LABELS[
        "COVERED_BY_TRACK_MATCH_BASELINE"
    ].casefold()


def test_promoted_match_tooltip_does_not_claim_full_calibration():
    text = track_readiness_status_tooltip({
        "overall_status": "COVERED_BY_TRACK_MATCH_BASELINE",
        "baseline_source_variants": ["LMP2_ELMS"],
    })

    assert "sólo para MATCH" in text
    assert "REJECT sigue siendo específico" in text
    assert "No significa fully calibrated" in text
    assert "LMP2_ELMS" in text


def test_shadow_tooltip_keeps_match_and_reject_unauthorized():
    text = track_readiness_status_tooltip({
        "overall_status": "TRACK_MATCH_BASELINE_SHADOW",
    })

    assert "shadow" in text
    assert "No autoriza MATCH productivo" in text
    assert "nunca hereda REJECT" in text
