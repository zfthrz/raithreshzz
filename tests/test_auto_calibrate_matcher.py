import auto_calibrate_matcher as auto
import episode_pair_matcher as matcher


def test_evaluation_metrics_reward_safe_decisions_and_count_abstentions():
    thresholds = {
        "match_enabled": True,
        "match_center_max_m": 200.0,
        "match_overlap_shorter_min": 0.9,
        "match_overlap_union_min": 0.4,
        "match_shared_channel_min": 1,
        "extended_match_center_max_m": None,
        "shape_conflict_mean_sim_max": 0.2,
        "shape_conflict_coverage_diff_min": 0.5,
        "shape_conflict_impact_sim_max": 0.45,
        "reject_center_gt_m": 600.0,
        "reject_overlap_union_max": 0.33,
    }
    context = {
        "track": "Test Track", "track_layout": "Test Layout",
        "vehicle_variant": "LMP2_ELMS", "shared_channels": ["brake"],
    }
    records = [
        {"human_label": "SAME", "features": {**context, "center_distance_abs_diff_m": 5, "overlap_over_shorter": 1, "overlap_over_union": 1}},
        {"human_label": "DIFFERENT", "features": {**context, "center_distance_abs_diff_m": 1000, "overlap_over_shorter": 0, "overlap_over_union": 0}},
        {"human_label": "AMBIGUOUS", "features": {**context, "center_distance_abs_diff_m": 300, "overlap_over_shorter": 0.5, "overlap_over_union": 0.2}},
    ]
    metrics = auto.evaluate_thresholds(records, thresholds)
    assert metrics["exact_three_way_accuracy"] == 1.0
    assert metrics["match_precision"] == 1.0
    assert metrics["reject_precision"] == 1.0
    assert metrics["dangerous_cross_class_errors"] == 0
    assert metrics["promotion_authorized"] is False


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


def test_classify_pair_default_path_still_resolves_production_calibration(monkeypatch):
    pair = {
        "track": "Test Track",
        "track_layout": "Test Layout",
        "vehicle_variant": "LMP2_ELMS",
        "shared_channels": ["brake"],
        "center_distance_abs_diff_m": 5.0,
        "overlap_over_shorter": 1.0,
        "overlap_over_union": 1.0,
    }
    calibration = {
        "thresholds": {
            "match_enabled": True,
            "match_center_max_m": 200.0,
            "match_overlap_shorter_min": 0.9,
            "match_overlap_union_min": 0.4,
            "match_shared_channel_min": 1,
            "extended_match_center_max_m": None,
            "shape_conflict_mean_sim_max": 0.2,
            "shape_conflict_coverage_diff_min": 0.5,
            "shape_conflict_impact_sim_max": 0.45,
            "reject_center_gt_m": 600.0,
            "reject_overlap_union_max": 0.33,
        }
    }

    calls = []

    def fake_resolve(value):
        calls.append(value)
        return calibration

    monkeypatch.setattr(matcher, "resolve_calibration", fake_resolve)

    result = matcher.classify_pair(pair)

    assert calls == [pair]
    assert result["decision"] == "MATCH"


def test_explicit_calibration_override_does_not_read_production_calibration(monkeypatch):
    pair = {
        "track": "Test Track",
        "track_layout": "Test Layout",
        "vehicle_variant": "LMP2_ELMS",
        "shared_channels": ["brake"],
        "center_distance_abs_diff_m": 5.0,
        "overlap_over_shorter": 1.0,
        "overlap_over_union": 1.0,
    }
    override = {
        "thresholds": {
            "match_enabled": False,
            "match_center_max_m": 200.0,
            "match_overlap_shorter_min": 0.9,
            "match_overlap_union_min": 0.4,
            "match_shared_channel_min": 1,
            "extended_match_center_max_m": None,
            "shape_conflict_mean_sim_max": 0.2,
            "shape_conflict_coverage_diff_min": 0.5,
            "shape_conflict_impact_sim_max": 0.45,
            "reject_center_gt_m": 600.0,
            "reject_overlap_union_max": 0.33,
        }
    }

    def forbidden_resolve(_pair):
        raise AssertionError("production calibration must not be read")

    monkeypatch.setattr(matcher, "resolve_calibration", forbidden_resolve)

    result = matcher.classify_pair(
        pair,
        calibration_override=override,
    )

    assert result["decision"] == "AMBIGUOUS"
