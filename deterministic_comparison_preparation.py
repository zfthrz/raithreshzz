"""Backend-neutral preparation of one deterministic comparison."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreparedComparison:
    comparison_quality: dict[str, Any]
    session_plan_eligible: bool
    detected_episode_catalog: list[dict[str, Any]]
    episode_catalog: list[dict[str, Any]]
    excluded_anomalies: list[dict[str, Any]]


def prepare_comparison(
    comparison: dict[str, Any],
    *,
    comparison_quality: dict[str, Any],
    track_location_context: dict[str, Any],
    build_episode_catalog: Callable,
    enrich_track_location: Callable,
    split_for_coaching: Callable,
) -> PreparedComparison:
    """Build, localize and gate the episode catalog in the established order."""
    detected = build_episode_catalog(comparison)
    enrich_track_location(detected, track_location_context)
    eligible, excluded = split_for_coaching(comparison, detected)
    return PreparedComparison(
        comparison_quality=comparison_quality,
        session_plan_eligible=bool(
            comparison_quality.get("session_plan_eligible", True)
        ),
        detected_episode_catalog=detected,
        episode_catalog=eligible,
        excluded_anomalies=excluded,
    )


def require_detected_episodes(
    comparison: dict[str, Any],
    detected_episode_catalog: list[dict[str, Any]],
) -> None:
    if not detected_episode_catalog:
        raise RuntimeError(
            "No hay driver_action_episode disponibles "
            f"para {comparison['reference_lap']} -> {comparison['comparison_lap']}. "
            "La v3.10.8.5.4 requiere analyze_telemetry v3.8 con episodios primarios."
        )
