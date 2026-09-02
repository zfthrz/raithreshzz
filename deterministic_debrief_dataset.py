"""Deterministic normalization of analyzer output for the debrief runtime."""

from __future__ import annotations

from deterministic_coaching import safe_float, safe_int
from deterministic_input_contract import resolve_comparison_laps


MAX_DRIVER_ACTION_EPISODES = 8
MAX_LEGACY_LOSS_EPISODES = 5
MAX_LOSS_ZONES = 8
MAX_SPEED_PROPAGATIONS_PER_EPISODE = 4


def trim_list(items, limit):
    if not isinstance(items, list):
        return []
    return items[:limit]


def compact_speed_propagation(propagation):
    if not isinstance(propagation, (list, dict)):
        return propagation
    if isinstance(propagation, list):
        return [
            item
            for item in propagation[:MAX_SPEED_PROPAGATIONS_PER_EPISODE]
            if isinstance(item, dict)
        ]
    return propagation


def clean_driver_action_episode(episode):
    if not isinstance(episode, dict):
        return None
    result = {
        "rank": safe_int(episode.get("rank")),
        "global_rank": safe_int(episode.get("global_rank")),
        "zone_id": safe_int(episode.get("zone_id")),
        "parent_zone_rank": safe_int(episode.get("parent_zone_rank")),
        "start_distance_m": safe_float(episode.get("start_distance_m")),
        "end_distance_m": safe_float(episode.get("end_distance_m")),
        "length_m": safe_float(episode.get("length_m")),
        "delta_start_s": safe_float(episode.get("delta_start_s")),
        "delta_end_s": safe_float(episode.get("delta_end_s")),
        "action_time_loss_s": safe_float(episode.get("action_time_loss_s")),
        "parent_zone_delta_loss_s": safe_float(
            episode.get("parent_zone_delta_loss_s")
        ),
        "parent_zone_net_loss_equivalent_percent": safe_float(
            episode.get("parent_zone_net_loss_equivalent_percent")
        ),
        "evidence_strength": episode.get("evidence_strength"),
        "action_channel_count": safe_int(episode.get("action_channel_count")),
        "action_channels": episode.get("action_channels", []),
        "action_evidence_by_channel": episode.get(
            "action_evidence_by_channel", {}
        ),
        "braking_point_comparison": episode.get("braking_point_comparison"),
        "brake_release_point_comparison": episode.get(
            "brake_release_point_comparison"
        ),
        "throttle_onset_point_comparison": episode.get(
            "throttle_onset_point_comparison"
        ),
        "throttle_release_point_comparison": episode.get(
            "throttle_release_point_comparison"
        ),
        "throttle_full_throttle_attainment_comparison": episode.get(
            "throttle_full_throttle_attainment_comparison"
        ),
        "throttle_partial_lift_comparison": episode.get(
            "throttle_partial_lift_comparison"
        ),
        "concurrent_speed_events": episode.get("concurrent_speed_events", []),
        "speed_propagation": compact_speed_propagation(
            episode.get("speed_propagation")
        ),
        "supporting_loss_clusters": episode.get("supporting_loss_clusters", []),
        "interpretation": episode.get(
            "interpretation",
            {
                "primary_unit": "driver_action_episode",
                "causal_claim": False,
                "speed_is_not_used_to_merge_actions": True,
                "speed_propagation_is_consequence_candidate": True,
                "action_time_is_computed_once_from_time_delta": True,
            },
        ),
    }
    action_channels = result.get("action_channels")
    if isinstance(action_channels, list):
        result["action_channels"] = [
            channel for channel in action_channels if channel != "speed"
        ]
    return result


def clean_legacy_loss_episode(episode):
    if not isinstance(episode, dict):
        return None
    return {
        "rank": safe_int(episode.get("rank")),
        "global_rank": safe_int(episode.get("global_rank")),
        "zone_id": safe_int(episode.get("zone_id")),
        "start_distance_m": safe_float(episode.get("start_distance_m")),
        "end_distance_m": safe_float(episode.get("end_distance_m")),
        "length_m": safe_float(episode.get("length_m")),
        "episode_time_loss_s": safe_float(episode.get("episode_time_loss_s")),
        "evidence_strength": episode.get("evidence_strength"),
        "evidence_channels": episode.get("evidence_channels", []),
        "evidence_by_channel": episode.get("evidence_by_channel", {}),
    }


def extract_objective_analysis(comparison):
    objective = comparison.get("objective_analysis", {})
    if not isinstance(objective, dict):
        objective = {}
    driver_action_episodes = objective.get("driver_action_episode_ranking")
    if not isinstance(driver_action_episodes, list):
        driver_action_episodes = comparison.get("driver_action_episode_ranking", [])
    cleaned_driver_episodes = []
    for episode in trim_list(driver_action_episodes, MAX_DRIVER_ACTION_EPISODES):
        cleaned = clean_driver_action_episode(episode)
        if cleaned is not None:
            cleaned_driver_episodes.append(cleaned)
    legacy_episodes = objective.get(
        "loss_episode_ranking", comparison.get("loss_episode_ranking", [])
    )
    cleaned_legacy = []
    for episode in trim_list(legacy_episodes, MAX_LEGACY_LOSS_EPISODES):
        cleaned = clean_legacy_loss_episode(episode)
        if cleaned is not None:
            cleaned_legacy.append(cleaned)
    loss_ranking = objective.get(
        "loss_ranking", comparison.get("loss_ranking", [])
    )
    if not isinstance(loss_ranking, list):
        loss_ranking = []
    summary = objective.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    return {
        "priority": objective.get("priority", "time_loss"),
        "driver_action_episode_ranking": cleaned_driver_episodes,
        "legacy_loss_episode_ranking": cleaned_legacy,
        "loss_ranking": trim_list(loss_ranking, MAX_LOSS_ZONES),
        "loss_cluster_ranking": objective.get("loss_cluster_ranking", []),
        "braking_point_detection": objective.get("braking_point_detection", {}),
        "throttle_point_detection": objective.get("throttle_point_detection", {}),
        "summary": summary,
    }


def clean_comparison(comparison, metadata, lap_times):
    if not isinstance(comparison, dict):
        raise ValueError("Comparación inválida.")
    reference_lap, comparison_lap = resolve_comparison_laps(comparison, metadata)
    reference_time = safe_float(comparison.get("reference_time_s"))
    comparison_time = safe_float(comparison.get("comparison_time_s"))
    if reference_time is None:
        reference_time = lap_times.get(reference_lap)
    if comparison_time is None:
        comparison_time = lap_times.get(comparison_lap)
    if reference_time is None or comparison_time is None:
        raise ValueError(
            f"Comparación sin tiempos {reference_lap} -> {comparison_lap}."
        )
    real_delta = safe_float(comparison.get("comparison_minus_reference_s"))
    if real_delta is None:
        real_delta = comparison_time - reference_time
    objective = extract_objective_analysis(comparison)
    analysis_mode = (
        "driver_action_episode_v3_8"
        if objective["driver_action_episode_ranking"]
        else "legacy_loss_episode_fallback"
    )
    return {
        "same_vehicle": comparison.get("same_vehicle", True),
        "reference_lap": reference_lap,
        "comparison_lap": comparison_lap,
        "reference_time_s": reference_time,
        "comparison_time_s": comparison_time,
        "comparison_minus_reference_s": real_delta,
        "calculated_delta_s": safe_float(comparison.get("calculated_delta_s")),
        "distance_m": safe_float(comparison.get("distance_m")),
        "temporal_validation": comparison.get("temporal_validation", {}),
        "driver_analysis_priority": comparison.get("driver_analysis_priority"),
        "driver_analysis_priority_rank": safe_int(
            comparison.get("driver_analysis_priority_rank")
        ),
        "analysis_mode": analysis_mode,
        "objective_analysis": objective,
    }


def build_debrief_dataset(data, lap_times):
    metadata = data["metadata"]
    comparisons = [
        clean_comparison(raw_comparison, metadata, lap_times)
        for raw_comparison in data["comparisons"]
    ]

    def comparison_sort_key(item):
        priority_rank = item.get("driver_analysis_priority_rank")
        if priority_rank is None:
            priority_rank = 999999
        delta = abs(item.get("comparison_minus_reference_s") or 0.0)
        return priority_rank, delta

    comparisons = sorted(comparisons, key=comparison_sort_key)
    return {
        "metadata": {
            "analysis_version": metadata.get("analysis_version"),
            "track": metadata.get("track"),
            "session_type": metadata.get("session_type"),
            "timestamp_utc": metadata.get("timestamp_utc"),
            "same_vehicle": metadata.get("same_vehicle", True),
            "lap_comparison_model": metadata.get("lap_comparison_model"),
            "reference_lap": safe_int(metadata.get("reference_lap")),
            "valid_laps": metadata.get("valid_laps", []),
            "discarded_laps": metadata.get("discarded_laps", []),
            "reference_distance_m": safe_float(
                metadata.get("reference_distance_m")
            ),
            "temporal_validation_status": metadata.get(
                "temporal_validation_status"
            ),
            "objective_analysis_validation": metadata.get(
                "objective_analysis_validation"
            ),
            "lap_times_s": {
                str(lap): safe_float(duration) for lap, duration in lap_times.items()
            },
        },
        "comparisons": comparisons,
    }
