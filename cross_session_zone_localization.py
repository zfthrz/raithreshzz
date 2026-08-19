from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np

from track_location import resolve_interval


LOCALIZATION_VERSION = "0.1"
VALID_PROFILE_STATUSES = {
    "VALIDATED",
    "VALIDATED_MULTI_SESSION",
}

# Regex matching v{major}.{minor} anywhere inside a profile_id string.
_PROFILE_VERSION_RE = re.compile(r"v(\d+)\.(\d+)")


def _parse_profile_version(profile: dict[str, Any]) -> tuple[int, int] | None:
    """Return (major, minor) from the highest ``v{M}.{N}`` in ``profile_id``.

    Returns ``None`` when no version segment can be extracted reliably.
    """
    raw = profile.get("profile_id", "")
    matches = _PROFILE_VERSION_RE.findall(raw)
    if not matches:
        return None
    # Pick the numerically highest (major, minor) found.
    return max((int(m), int(n)) for m, n in matches)


def normalize_identity(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.casefold().split())


def find_validated_track_profile(
    profile_dir: Path,
    *,
    track: str,
    layout: str,
) -> tuple[dict[str, Any] | None, Path | None]:
    if not profile_dir.is_dir():
        return None, None

    expected_track = normalize_identity(track)
    expected_layout = normalize_identity(layout)
    matches: list[tuple[dict[str, Any], Path]] = []

    for path in sorted(profile_dir.glob("*.json")):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if profile.get("status") not in VALID_PROFILE_STATUSES:
            continue
        if normalize_identity(profile.get("track")) != expected_track:
            continue
        if normalize_identity(profile.get("layout")) != expected_layout:
            continue
        if not isinstance(profile.get("turns"), list) or not profile["turns"]:
            continue
        matches.append((profile, path.resolve()))

    if not matches:
        return None, None
    if len(matches) == 1:
        return matches[0]

    # --- multiple exact track+layout matches: select highest version ---
    versions: list[tuple[tuple[int, int] | None, dict[str, Any], Path]] = [
        (_parse_profile_version(prof), prof, pth) for prof, pth in matches
    ]

    parseable = [v for v in versions if v[0] is not None]
    unparseable = [v for v in versions if v[0] is None]

    if not parseable:
        # None of the candidates have a parseable version → fail closed.
        names = ", ".join(p.name for _, p in matches)
        raise ValueError(
            "No se pudo determinar la versión contractual de múltiples perfiles: "
            + names
        )

    # Group parseable by version tuple; pick the highest version group.
    max_version = max(v[0] for v in parseable)
    top = [v for v in parseable if v[0] == max_version]

    if len(top) > 1:
        # Two *distinct* profiles share the exact same highest version →
        # true ambiguity — fail closed.
        names = ", ".join(p.name for _, _, p in top)
        raise ValueError(
            "Múltiples perfiles distintos comparten la misma versión contractual "
            "más alta (ambigüedad): " + names
        )

    _, selected_profile, selected_path = top[0]
    return selected_profile, selected_path


def profile_boundaries(profile: dict[str, Any]) -> list[float]:
    boundaries: set[float] = set()
    for turn in profile.get("turns") or []:
        for key in ("start_m", "end_m"):
            try:
                value = float(turn[key])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(value):
                boundaries.add(value)
    return sorted(boundaries)


def build_trend_zone_summaries(
    sector: Any,
    comparison: Any,
    zones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for index, zone in enumerate(zones, start=1):
        summary = dict(sector.summarize_zone(comparison, zone))
        summary["trend_zone_id"] = f"trend_{index:03d}"
        summary["scope"] = "delta_trend"
        summaries.append(summary)
    return summaries


def _split_indices(
    distance: np.ndarray,
    *,
    start_index: int,
    end_index: int,
    boundaries: list[float],
) -> list[int]:
    start_distance = float(distance[start_index])
    end_distance = float(distance[end_index])
    cuts = {int(start_index), int(end_index)}
    for boundary in boundaries:
        if not start_distance < boundary < end_distance:
            continue
        index = int(np.searchsorted(distance, boundary, side="left"))
        if start_index < index < end_index:
            cuts.add(index)
    return sorted(cuts)


def localize_trend_zones(
    sector: Any,
    comparison: Any,
    zones: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    threshold: float,
    min_zone_distance: float,
) -> list[dict[str, Any]]:
    distance = comparison["distance"].to_numpy(dtype=float)
    boundaries = profile_boundaries(profile)
    localized: list[dict[str, Any]] = []

    for trend_index, trend_zone in enumerate(zones, start=1):
        indices = _split_indices(
            distance,
            start_index=int(trend_zone["start_index"]),
            end_index=int(trend_zone["end_index"]),
            boundaries=boundaries,
        )
        for start_index, end_index in zip(indices, indices[1:]):
            if end_index <= start_index:
                continue
            start_distance = float(distance[start_index])
            end_distance = float(distance[end_index])
            if end_distance - start_distance < min_zone_distance:
                continue
            delta_start = float(comparison["time_delta"].iloc[start_index])
            delta_end = float(comparison["time_delta"].iloc[end_index])
            delta_change = delta_end - delta_start
            if abs(delta_change) < threshold:
                continue
            zone_type = "loss" if delta_change > 0 else "gain"
            summary = dict(
                sector.summarize_zone(
                    comparison,
                    {
                        "type": zone_type,
                        "start_index": start_index,
                        "end_index": end_index,
                    },
                )
            )
            summary["source_trend_zone_id"] = f"trend_{trend_index:03d}"
            summary["scope"] = "track_profile_segment"
            summary["location"] = resolve_interval(
                profile,
                summary["start_distance"],
                summary["end_distance"],
            )
            localized.append(summary)

    return localized


def unlocalized_zone_summaries(
    trend_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in trend_summaries:
        summary = dict(item)
        summary["source_trend_zone_id"] = summary["trend_zone_id"]
        summary["scope"] = "unlocalized_delta_trend"
        summary["location"] = None
        result.append(summary)
    return result
