from copy import deepcopy

from steering_coaching_shadow import build_steering_coaching_shadow


def _finding(direction="higher_in_comparison_lap"):
    return {
        "comparison": "1 -> 2",
        "episode_id": 3,
        "start_distance_m": 100.0,
        "end_distance_m": 140.0,
        "track_location": {"corner_name": "Test"},
        "evidence_strength": "strong",
        "steering_coaching_requested": False,
        "channels": [{
            "channel": "steering_magnitude",
            "direction": direction,
            "quantitative": {"mean_difference": 8.0, "unit": "%"},
        }],
    }


def test_shadow_observes_python_direction_without_llm_authorization():
    finding = _finding()
    original = deepcopy(finding)

    result = build_steering_coaching_shadow([finding])

    assert finding == original
    assert result["status"] == "SHADOW_OBSERVATIONAL_ONLY"
    assert result["llm_called"] is False
    assert result["observed_direction_count"] == 1
    observation = result["observations"][0]
    assert observation["status"] == "OBSERVED_DIRECTION"
    assert observation["action_toward_reference"] == (
        "reduce_steering_magnitude_toward_reference"
    )
    assert observation["llm_requested_steering"] is False
    assert observation["observational_only"] is True
    assert observation["affects_next_stint_plan"] is False
    assert observation["steering_action_authorized"] is False


def test_shadow_fails_closed_for_mixed_direction():
    result = build_steering_coaching_shadow([_finding("mixed")])

    observation = result["observations"][0]
    assert observation["status"] == "WITHHELD"
    assert observation["action_toward_reference"] is None
    assert observation["reason_codes"] == [
        "non_unambiguous_python_direction"
    ]


def test_shadow_requires_comparable_physical_interval():
    finding = _finding("lower_in_comparison_lap")
    finding["start_distance_m"] = None

    result = build_steering_coaching_shadow([finding])

    observation = result["observations"][0]
    assert observation["status"] == "WITHHELD"
    assert observation["reason_codes"] == ["missing_physical_interval"]


def test_shadow_ignores_findings_without_steering():
    finding = _finding()
    finding["channels"] = [{"channel": "brake", "direction": "higher"}]

    result = build_steering_coaching_shadow([finding])

    assert result["observation_count"] == 0
    assert result["observations"] == []


def test_repeated_exact_direction_becomes_secondary_candidate():
    regions = [{
        "start_distance_m": 100.0,
        "end_distance_m": 150.0,
        "comparisons": ["1 -> 2", "1 -> 3"],
        "repeated_differences": [{
            "channel": "steering_magnitude",
            "direction": "lower_in_comparison_lap",
            "comparison_count": 2,
            "recurrence_episode_count": 2,
        }],
    }]

    result = build_steering_coaching_shadow([], regions)

    assert result["repeated_candidate_count"] == 1
    candidate = result["repeated_candidates"][0]
    assert candidate["status"] == "REPEATED_DIRECTION_CANDIDATE"
    assert candidate["action_toward_reference"] == (
        "increase_steering_magnitude_toward_reference"
    )
    assert candidate["selection_basis"] == (
        "existing_recurrence_region_exact_direction"
    )
    assert candidate["steering_action_authorized"] is False
    selected = result["selected_secondary_candidate"]
    assert selected["region_index"] == 0
    assert selected["selection_scope"] == (
        "at_most_one_secondary_candidate_per_session"
    )


def test_repeated_mixed_direction_is_withheld():
    regions = [{
        "start_distance_m": 100.0,
        "end_distance_m": 150.0,
        "comparisons": ["1 -> 2", "1 -> 3"],
        "repeated_differences": [{
            "channel": "steering_magnitude",
            "direction": "mixed_across_comparisons",
            "comparison_count": 2,
            "recurrence_episode_count": 2,
        }],
    }]

    result = build_steering_coaching_shadow([], regions)

    assert result["repeated_candidate_count"] == 0
    assert result["repeated_withheld_count"] == 1
    candidate = result["repeated_candidates"][0]
    assert candidate["status"] == "WITHHELD"
    assert candidate["reason_codes"] == [
        "contradictory_or_ambiguous_recurrence"
    ]
    assert result["selected_secondary_candidate"] is None


def test_secondary_selection_preserves_existing_region_order():
    regions = []
    for start, direction in (
        (300.0, "higher_in_comparison_lap"),
        (100.0, "lower_in_comparison_lap"),
    ):
        regions.append({
            "start_distance_m": start,
            "end_distance_m": start + 20.0,
            "comparisons": ["1 -> 2", "1 -> 3"],
            "repeated_differences": [{
                "channel": "steering_magnitude",
                "direction": direction,
                "comparison_count": 2,
                "recurrence_episode_count": 2,
            }],
        })

    result = build_steering_coaching_shadow([], regions)

    assert result["repeated_candidate_count"] == 2
    assert result["selected_secondary_candidate"]["start_distance_m"] == 300.0
    assert result["selected_secondary_candidate"]["region_index"] == 0
