import auto_calibrate_matcher as auto


def test_pair_count_alone_never_authorizes():
    status, reasons = auto.choose_status(
        records=[{}] * 100,
        sessions=[{}] * 10,
        calibration=[{}] * 50,
        evaluation=[{}] * 20,
        cal_counts={"SAME": 0, "DIFFERENT": 50, "AMBIGUOUS": 0},
        eval_counts={"SAME": 0, "DIFFERENT": 20, "AMBIGUOUS": 0},
        thresholds={"match_enabled": False},
    )
    assert status is None
    assert "no_same_in_calibration" in reasons


def test_72_labels_can_become_a_calibrated_shadow_candidate():
    status, reasons = auto.choose_status(
        records=[{}] * 72,
        sessions=[{}] * 8,
        calibration=[{}] * 20,
        evaluation=[{}] * 6,
        cal_counts={"SAME": 5, "DIFFERENT": 10, "AMBIGUOUS": 5},
        eval_counts={"SAME": 2, "DIFFERENT": 3, "AMBIGUOUS": 1},
        thresholds={"match_enabled": True},
    )
    assert status == "CANDIDATE_CALIBRATED"
    assert reasons == []


def test_shadow_report_never_authorizes_production(monkeypatch, tmp_path):
    records = [{
        "pair_id": f"pair-{index}",
        "human_label": "SAME" if index % 2 == 0 else "DIFFERENT",
        "features": {
            "session_a": index,
            "session_b": index + 100,
            "center_distance_abs_diff_m": 2.0,
            "overlap_over_shorter": 1.0,
            "overlap_over_union": 0.8,
            "shared_channels": ["brake"],
        },
    } for index in range(24)]
    key = ("Test Track", "Test Layout", "LMP2_ELMS")
    monkeypatch.setattr(auto, "collect_records", lambda root: ({key: records}, {}))

    report = auto.build_registry(tmp_path)

    assert report["authority"] == "SHADOW_ONLY"
    assert report["policy"]["production_matcher_reads_this_output"] is False
    assert report["contexts"][0]["authorized"] is False
