"""Backend-neutral preparation of deterministic debrief input data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreparedDebriefInput:
    source_data: dict[str, Any]
    metadata: dict[str, Any]
    comparisons: list[dict[str, Any]]
    track_location_context: dict[str, Any]


def prepare_debrief_input(
    input_path: str,
    *,
    load_json: Callable,
    validate_data_model: Callable,
    validate_lap_times: Callable,
    build_dataset: Callable,
    load_track_location_context: Callable,
) -> PreparedDebriefInput:
    """Execute the established input pipeline with explicit dependencies."""
    source_data = load_json(input_path)
    metadata, raw_comparisons = validate_data_model(source_data)
    lap_times = validate_lap_times(
        source_data,
        metadata,
        raw_comparisons,
    )
    dataset = build_dataset(source_data, lap_times)
    prepared_metadata = dataset["metadata"]
    comparisons = dataset["comparisons"]
    track_context = load_track_location_context(prepared_metadata)
    if not comparisons:
        raise RuntimeError("El JSON no contiene comparaciones.")
    return PreparedDebriefInput(
        source_data=source_data,
        metadata=prepared_metadata,
        comparisons=comparisons,
        track_location_context=track_context,
    )
