from __future__ import annotations

import llm_analysis_deepseek as legacy
from deterministic_debrief_dataset import build_debrief_dataset


def representative_source():
    return {
        "metadata": {
            "analysis_version": "3.8",
            "track": "Spa",
            "session_type": "Practice",
            "timestamp_utc": "2026-09-02T00:00:00Z",
            "same_vehicle": True,
            "lap_comparison_model": "same_vehicle_different_laps",
            "reference_lap": 1,
            "valid_laps": [1, 2, 3],
            "discarded_laps": [],
            "reference_distance_m": "7004.0",
            "temporal_validation_status": "PASS",
            "objective_analysis_validation": "PASS",
        },
        "comparisons": [
            {
                "comparison_lap": 2,
                "driver_analysis_priority_rank": 2,
                "objective_analysis": {
                    "driver_action_episode_ranking": [
                        {
                            "rank": "1",
                            "action_channels": ["brake", "speed"],
                            "speed_propagation": [
                                {"kind": index} for index in range(6)
                            ],
                        }
                    ],
                    "loss_ranking": [{"rank": index} for index in range(10)],
                },
            },
            {
                "comparison_lap": 3,
                "driver_analysis_priority_rank": 1,
                "loss_episode_ranking": [{"rank": "1"}],
            },
        ],
    }


def test_dataset_matches_legacy_contract_exactly():
    source = representative_source()
    lap_times = {1: 90.0, 2: 90.4, 3: 90.2}
    assert build_debrief_dataset(source, lap_times) == legacy.build_llm_dataset(
        source, lap_times
    )


def test_dataset_preserves_priority_order_and_semantic_safety():
    dataset = build_debrief_dataset(
        representative_source(), {1: 90.0, 2: 90.4, 3: 90.2}
    )
    assert [item["comparison_lap"] for item in dataset["comparisons"]] == [3, 2]
    episode = dataset["comparisons"][1]["objective_analysis"][
        "driver_action_episode_ranking"
    ][0]
    assert episode["action_channels"] == ["brake"]
    assert len(episode["speed_propagation"]) == 4
    assert len(dataset["comparisons"][1]["objective_analysis"]["loss_ranking"]) == 8
