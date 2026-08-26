"""Deterministic interval and spatial-overlap helpers for session coaching."""

import math

from deterministic_coaching import safe_float
from session_coaching_location import track_location_label

def _finite_number(value):
    value = safe_float(value)
    if value is None:
        return None
    try:
        if not math.isfinite(value):
            return None
    except Exception:
        return None
    return value

def _merge_distance_intervals(
    intervals,
):
    clean = sorted(
        [
            (float(start), float(end))
            for start, end in (
                intervals
                or []
            )
            if (
                _finite_number(start)
                and
                _finite_number(end)
                and
                float(end) > float(start)
            )
        ]
    )

    if not clean:
        return []

    merged = [
        [
            clean[0][0],
            clean[0][1],
        ]
    ]

    for start, end in clean[1:]:
        current = merged[-1]

        if start <= current[1]:
            current[1] = max(
                current[1],
                end,
            )
        else:
            merged.append(
                [start, end]
            )

    return [
        (start, end)
        for start, end in merged
    ]

def _interval_total_length(
    intervals,
):
    return sum(
        max(
            0.0,
            end - start,
        )
        for start, end in (
            intervals
            or []
        )
    )

def _interval_intersection_length(
    first,
    second,
):
    total = 0.0

    a = _merge_distance_intervals(
        first
    )
    b = _merge_distance_intervals(
        second
    )

    i = 0
    j = 0

    while (
        i < len(a)
        and
        j < len(b)
    ):
        start = max(
            a[i][0],
            b[j][0],
        )
        end = min(
            a[i][1],
            b[j][1],
        )

        if end > start:
            total += (
                end - start
            )

        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1

    return total

def _minimum_interval_gap(
    first,
    second,
):
    gaps = []

    for a0, a1 in (
        first
        or []
    ):
        for b0, b1 in (
            second
            or []
        ):
            if (
                a1 <= b0
            ):
                gaps.append(
                    b0 - a1
                )
            elif (
                b1 <= a0
            ):
                gaps.append(
                    a0 - b1
                )
            else:
                return 0.0

    if not gaps:
        return None

    return min(gaps)

def _plan_overlap_m(
    first,
    second,
):
    values = [
        safe_float(first.get("start_distance_m")),
        safe_float(first.get("end_distance_m")),
        safe_float(second.get("start_distance_m")),
        safe_float(second.get("end_distance_m")),
    ]

    if any(value is None for value in values):
        return 0.0

    a0, a1, b0, b1 = values

    if a1 < a0:
        a0, a1 = a1, a0

    if b1 < b0:
        b0, b1 = b1, b0

    return max(
        0.0,
        min(a1, b1) - max(a0, b0),
    )

def _same_plan_region(
    first,
    second,
):
    """
    Matcher descriptivo intra-sesión.

    Prioriza una ubicación de pista idéntica; si no existe, exige
    solapamiento espacial material. No se persiste entre sesiones.
    """
    first_label = track_location_label(
        first
    )
    second_label = track_location_label(
        second
    )

    if (
        first_label
        and second_label
        and first_label == second_label
    ):
        return True

    overlap = _plan_overlap_m(
        first,
        second,
    )

    if overlap <= 0.0:
        return False

    first_start = safe_float(
        first.get("start_distance_m")
    )
    first_end = safe_float(
        first.get("end_distance_m")
    )
    second_start = safe_float(
        second.get("start_distance_m")
    )
    second_end = safe_float(
        second.get("end_distance_m")
    )

    if any(
        value is None
        for value in (
            first_start,
            first_end,
            second_start,
            second_end,
        )
    ):
        return False

    first_len = max(
        abs(first_end - first_start),
        1.0,
    )
    second_len = max(
        abs(second_end - second_start),
        1.0,
    )

    required = min(
        20.0,
        0.20 * min(first_len, second_len),
    )

    return overlap >= required

def _channel_event_distance_intervals(
    evidence,
):
    intervals = []

    if not isinstance(evidence, dict):
        return intervals

    for event in (
        evidence.get("events", [])
        or []
    ):
        if not isinstance(event, dict):
            continue

        start = safe_float(
            event.get(
                "start_distance_m"
            )
        )
        end = safe_float(
            event.get(
                "end_distance_m"
            )
        )

        if start is None or end is None:
            continue

        if end < start:
            start, end = end, start

        if end <= start:
            continue

        intervals.append(
            (start, end)
        )

    intervals.sort()
    return intervals
