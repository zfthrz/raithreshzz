from build_h2_evaluation_review_queue import select_evaluation_pairs


def feature(pair_id, a, b, center, shorter, union, shared=True):
    return {
        "pair_id": pair_id,
        "session_a": a,
        "session_b": b,
        "center_distance_abs_diff_m": center,
        "overlap_over_shorter": shorter,
        "overlap_over_union": union,
        "shared_channels": ["brake"] if shared else [],
    }


def test_selects_balanced_unlabeled_evaluation_pairs():
    items = [
        feature("same1", 1, 2, 5, 1, 1),
        feature("same2", 1, 2, 8, .95, .8),
        feature("far1", 1, 2, 1000, 0, 0),
        feature("far2", 1, 2, 900, .1, .1),
        feature("edge1", 1, 2, 205, .89, .39),
        feature("edge2", 1, 2, 210, .85, .35),
        feature("labeled", 1, 2, 1, 1, 1),
        feature("wrong_split", 1, 3, 1, 1, 1),
    ]
    queue, counts = select_evaluation_pairs(items, {"labeled"}, {1, 2}, per_lens=2)
    assert [item["pair_id"] for item in queue] == [
        "same1", "same2", "far1", "far2", "edge1", "edge2"
    ]
    assert counts == {
        "high_precision_core": 2,
        "clear_spatial_reject": 2,
        "decision_boundary": 2,
    }
    assert all(item["features"]["pair_id"] == item["pair_id"] for item in queue)


def test_selection_is_deterministic():
    items = [
        feature("b", 1, 2, 5, 1, 1),
        feature("a", 1, 2, 5, 1, 1),
    ]
    first, _ = select_evaluation_pairs(items, set(), {1, 2}, per_lens=1)
    second, _ = select_evaluation_pairs(list(reversed(items)), set(), {1, 2}, per_lens=1)
    assert [item["pair_id"] for item in first] == ["a"]
    assert first == second
