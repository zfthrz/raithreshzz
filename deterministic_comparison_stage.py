"""Product-owned preparation stage for one deterministic lap comparison."""

from __future__ import annotations

from deterministic_comparison_preparation import PreparedComparison, prepare_comparison
from session_coaching_location import enrich_items_with_track_location
from session_coaching_quality import (
    _session_comparison_key,
    build_episode_catalog,
    split_episode_catalog_for_coaching,
)


def prepare_runtime_comparison(
    comparison,
    quality_by_key,
    track_location_context,
) -> PreparedComparison:
    """Resolve quality, catalog, localization and coaching eligibility."""
    comparison_key = _session_comparison_key(comparison)
    return prepare_comparison(
        comparison,
        comparison_quality=quality_by_key.get(comparison_key, {}),
        track_location_context=track_location_context,
        build_episode_catalog=build_episode_catalog,
        enrich_track_location=enrich_items_with_track_location,
        split_for_coaching=split_episode_catalog_for_coaching,
    )
