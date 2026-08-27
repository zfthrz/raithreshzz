# ============================================================
# H5.4 P10 - DETERMINISTIC DRIVER-FACING PLAN PROJECTION
# ============================================================

from coaching_precision import build_p10_plan_presentation


def _p10_plan_item(presentation_rank=None):
    return {"_p9_presentation_metadata": {"presentation_rank": presentation_rank} if presentation_rank is not None else {}}


def test_p10_ranks_reorder_presentation_but_original_unchanged():
    """Test A: ranks [0,2,1] reorder presentation but original unchanged."""
    plan = [_p10_plan_item(r) for r in [0, 2, 1]]
    result = build_p10_plan_presentation(plan)
    presentation = result["presentation"]
    # Presentation should be reordered: 0, 2, 1 -> indices should be 0, 2, 1
    assert presentation[0] is not plan[0]  # deepcopy
    assert presentation[1] is not plan[2]  # rank 2 goes to position 1
    assert presentation[2] is not plan[1]  # rank 1 goes to position 2
    # Original plan is unchanged
    assert plan[0] == _p10_plan_item(0)
    assert plan[1] == _p10_plan_item(2)
    assert plan[2] == _p10_plan_item(1)


def test_p10_already_correct_order_reordered_false():
    """Test B: already-correct order => reordered=false."""
    plan = [_p10_plan_item(r) for r in [0, 1, 2]]
    result = build_p10_plan_presentation(plan)
    assert result["_p10_presentation"]["reordered"] is False
    assert result["_p10_presentation"]["status"] == "ACTIVE"


def test_p10_missing_p9_metadata_fallback():
    """Test C: missing P9 metadata => fallback."""
    plan = [_p10_plan_item(None), _p10_plan_item(1), _p10_plan_item(2)]
    result = build_p10_plan_presentation(plan)
    assert result["_p10_presentation"]["status"] == "FALLBACK_ORIGINAL_ORDER"
    assert result["_p10_presentation"]["reason"] == "INVALID_PRESENTATION_RANK"


def test_p10_duplicate_rank_fallback():
    """Test D: duplicate rank => fallback."""
    plan = [_p10_plan_item(r) for r in [0, 1, 1]]
    result = build_p10_plan_presentation(plan)
    assert result["_p10_presentation"]["status"] == "FALLBACK_ORIGINAL_ORDER"
    assert result["_p10_presentation"]["reason"] == "DUPLICATE_PRESENTATION_RANK"


def test_p10_invalid_non_contiguous_rank_fallback():
    """Test E: invalid/non-contiguous rank => fallback."""
    plan = [_p10_plan_item(r) for r in [0, 2, 3]]  # missing rank 1
    result = build_p10_plan_presentation(plan)
    assert result["_p10_presentation"]["status"] == "FALLBACK_ORIGINAL_ORDER"
    assert result["_p10_presentation"]["reason"] == "NON_CONTIGUOUS_PRESENTATION_RANK"


def test_p10_input_not_mutated():
    """Test F: input list/dicts are not mutated."""
    import copy
    original_plan = [_p10_plan_item(r) for r in [0, 1, 2]]
    plan_copy = copy.deepcopy(original_plan)
    result = build_p10_plan_presentation(original_plan)
    assert original_plan == plan_copy  # input unchanged


def test_p10_deterministic_repeated_result():
    """Test G: repeated calls deterministic."""
    plan = [_p10_plan_item(r) for r in [0, 2, 1]]
    result1 = build_p10_plan_presentation(plan)
    result2 = build_p10_plan_presentation(plan)
    assert result1["presentation"] == result2["presentation"]
    assert result1["_p10_presentation"] == result2["_p10_presentation"]


def test_p10_p8_p9_fields_preserved():
    """Test H: P8/P9 fields preserved."""
    plan = [
        {
            "_p9_presentation_metadata": {"presentation_rank": 0},
            "driver_cues": [{"kind": "spatial_points", "channel": "brake", "text": "test"}],
            "actionable_cue_count": 1,
        },
        {
            "_p9_presentation_metadata": {"presentation_rank": 1},
            "driver_cues": [{"kind": "spatial_points", "channel": "throttle", "text": "test"}],
            "actionable_cue_count": 1,
        },
    ]
    result = build_p10_plan_presentation(plan)
    assert result["presentation"][0]["_p9_presentation_metadata"]["presentation_rank"] == 0
    assert result["presentation"][0]["driver_cues"] == [{"kind": "spatial_points", "channel": "brake", "text": "test"}]
    assert result["presentation"][0]["actionable_cue_count"] == 1
