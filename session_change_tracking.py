from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from deterministic_coaching import safe_float


CHANGE_TRACKING_VERSION = "0.1"

STATUS_AVAILABLE = "AVAILABLE"
STATUS_UNAVAILABLE = "UNAVAILABLE"

CHANGE_NEW = "NEW"
CHANGE_REPEATED = "REPEATED"
CHANGE_RESOLVED = "RESOLVED"

_ACTION_PATTERN_FIELDS = (
    ("braking_point_patterns", "braking_point"),
    ("brake_release_patterns", "brake_release"),
    ("throttle_onset_patterns", "throttle_onset"),
    ("throttle_release_patterns", "throttle_release"),
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root inválido: {path}")
    return payload


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip().replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def analysis_context(analysis_path: Path) -> dict[str, Any]:
    payload = _load_json(analysis_path)
    metadata = _dict(payload.get("metadata"))
    vehicle = _dict(metadata.get("vehicle_identity"))
    session = _dict(metadata.get("session_context"))

    return {
        "timestamp_utc": metadata.get("timestamp_utc"),
        "timestamp": _timestamp(metadata.get("timestamp_utc")),
        "track": metadata.get("track"),
        "lmu_track_name": session.get("lmu_track_name"),
        "lmu_track_layout": session.get("lmu_track_layout"),
        "vehicle_family": vehicle.get("family"),
        "vehicle_variant": vehicle.get("variant"),
        "car_name_raw": vehicle.get("car_name_raw"),
    }


def compatible_context(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> bool:
    required = (
        "lmu_track_name",
        "lmu_track_layout",
        "vehicle_variant",
    )

    for key in required:
        current_value = current.get(key)
        previous_value = previous.get(key)

        if not current_value or not previous_value:
            return False

        if str(current_value) != str(previous_value):
            return False

    return True


def find_previous_compatible_session(
    current_record: Any,
    sessions: list[Any],
) -> Any | None:
    if current_record.analysis_path is None:
        return None

    current_context = analysis_context(current_record.analysis_path)
    current_timestamp = current_context.get("timestamp")

    if current_timestamp is None:
        return None

    candidates = []

    for record in sessions:
        if record.session_key == current_record.session_key:
            continue

        if (
            record.analysis_path is None
            or not getattr(record, "has_validated_debrief", False)
        ):
            continue

        try:
            previous_context = analysis_context(record.analysis_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue

        previous_timestamp = previous_context.get("timestamp")

        if previous_timestamp is None:
            continue

        if previous_timestamp >= current_timestamp:
            continue

        if not compatible_context(current_context, previous_context):
            continue

        candidates.append((previous_timestamp, record))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _interval(item: dict[str, Any]) -> tuple[float, float] | None:
    start = safe_float(item.get("start_distance_m"))
    end = safe_float(item.get("end_distance_m"))

    if start is None or end is None:
        track_location = _dict(item.get("track_location"))
        start = safe_float(track_location.get("start_m"))
        end = safe_float(track_location.get("end_m"))

    if start is None or end is None:
        return None

    if end < start:
        start, end = end, start

    return start, end


def _intervals_overlap(
    left: tuple[float, float],
    right: tuple[float, float],
) -> bool:
    return min(left[1], right[1]) > max(left[0], right[0])


def _action_signatures(item: dict[str, Any]) -> set[tuple[str, str]]:
    signatures: set[tuple[str, str]] = set()

    for field, family in _ACTION_PATTERN_FIELDS:
        for pattern in _list(item.get(field)):
            if not isinstance(pattern, dict):
                continue

            direction = pattern.get("coaching_direction")
            if isinstance(direction, str) and direction:
                signatures.add((family, direction))

    return signatures


def same_observational_zone(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> bool:
    current_interval = _interval(current)
    previous_interval = _interval(previous)

    if current_interval is None or previous_interval is None:
        return False

    return _intervals_overlap(current_interval, previous_interval)


def _action_atom(
    *,
    family: str,
    direction: str,
) -> dict[str, Any]:
    return {
        "family": family,
        "coaching_direction": direction,
    }


def _public_action_atoms(
    item: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _action_atom(
            family=family,
            direction=direction,
        )
        for family, direction in sorted(_action_signatures(item))
    ]



def same_observational_action(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> bool:
    if not same_observational_zone(current, previous):
        return False

    current_actions = _action_signatures(current)
    previous_actions = _action_signatures(previous)

    return bool(
        current_actions
        and current_actions == previous_actions
    )

def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_label": item.get("plan_label"),
        "kind": item.get("kind"),
        "start_distance_m": item.get("start_distance_m"),
        "end_distance_m": item.get("end_distance_m"),
        "track_location": item.get("track_location"),
        "driver_cues": item.get("driver_cues"),
        "action_signatures": [
            {
                "family": family,
                "coaching_direction": direction,
            }
            for family, direction in sorted(_action_signatures(item))
        ],
    }


def compare_plans(
    current_plan: list[dict[str, Any]],
    previous_plan: list[dict[str, Any]],
) -> dict[str, Any]:
    current_items = [
        item
        for item in current_plan
        if isinstance(item, dict)
    ]
    previous_items = [
        item
        for item in previous_plan
        if isinstance(item, dict)
    ]

    used_previous: set[int] = set()
    changes = []

    for current_item in current_items:
        matching_previous_indices = [
            previous_index
            for previous_index, previous_item in enumerate(previous_items)
            if (
                previous_index not in used_previous
                and same_observational_zone(
                    current_item,
                    previous_item,
                )
            )
        ]

        if not matching_previous_indices:
            for family, direction in sorted(
                _action_signatures(current_item)
            ):
                changes.append({
                    "status": CHANGE_NEW,
                    "action": _action_atom(
                        family=family,
                        direction=direction,
                    ),
                    "current_item": _public_item(current_item),
                    "previous_item": None,
                })
            continue

        # Un único plan item previo puede representar la misma zona física.
        # No elegimos por ranking ni texto: tomamos el primero por orden
        # determinista del plan anterior.
        previous_index = matching_previous_indices[0]
        previous_item = previous_items[previous_index]
        used_previous.add(previous_index)

        current_actions = _action_signatures(current_item)
        previous_actions = _action_signatures(previous_item)

        for family, direction in sorted(
            current_actions & previous_actions
        ):
            changes.append({
                "status": CHANGE_REPEATED,
                "action": _action_atom(
                    family=family,
                    direction=direction,
                ),
                "current_item": _public_item(current_item),
                "previous_item": _public_item(previous_item),
            })

        for family, direction in sorted(
            current_actions - previous_actions
        ):
            changes.append({
                "status": CHANGE_NEW,
                "action": _action_atom(
                    family=family,
                    direction=direction,
                ),
                "current_item": _public_item(current_item),
                "previous_item": _public_item(previous_item),
            })

        for family, direction in sorted(
            previous_actions - current_actions
        ):
            changes.append({
                "status": CHANGE_RESOLVED,
                "action": _action_atom(
                    family=family,
                    direction=direction,
                ),
                "current_item": _public_item(current_item),
                "previous_item": _public_item(previous_item),
            })

    for previous_index, previous_item in enumerate(previous_items):
        if previous_index in used_previous:
            continue

        for family, direction in sorted(
            _action_signatures(previous_item)
        ):
            changes.append({
                "status": CHANGE_RESOLVED,
                "action": _action_atom(
                    family=family,
                    direction=direction,
                ),
                "current_item": None,
                "previous_item": _public_item(previous_item),
            })

    return {
        "status": STATUS_AVAILABLE,
        "policy_version": CHANGE_TRACKING_VERSION,
        "observational_only": True,
        "affects_next_stint_plan": False,
        "historical_actions_authorized": False,
        "change_counts": {
            CHANGE_NEW: sum(
                1 for item in changes if item["status"] == CHANGE_NEW
            ),
            CHANGE_REPEATED: sum(
                1 for item in changes if item["status"] == CHANGE_REPEATED
            ),
            CHANGE_RESOLVED: sum(
                1 for item in changes if item["status"] == CHANGE_RESOLVED
            ),
        },
        "changes": changes,
    }


def build_session_change_tracking(
    current_record: Any,
    sessions: list[Any],
) -> dict[str, Any]:
    previous_record = find_previous_compatible_session(
        current_record,
        sessions,
    )

    if previous_record is None:
        return {
            "status": STATUS_UNAVAILABLE,
            "policy_version": CHANGE_TRACKING_VERSION,
            "observational_only": True,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
            "reason": "no_previous_compatible_session",
            "changes": [],
        }

    if not getattr(current_record, "has_validated_debrief", False):
        return {
            "status": STATUS_UNAVAILABLE,
            "policy_version": CHANGE_TRACKING_VERSION,
            "observational_only": True,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
            "reason": "current_debrief_unavailable",
            "changes": [],
        }

    current_debrief = _load_json(current_record.debrief_path)
    previous_debrief = _load_json(previous_record.debrief_path)

    current_facts = _dict(current_debrief.get("session_coaching_facts"))
    previous_facts = _dict(previous_debrief.get("session_coaching_facts"))

    result = compare_plans(
        _list(current_facts.get("next_stint_plan")),
        _list(previous_facts.get("next_stint_plan")),
    )

    result["current_session_key"] = current_record.session_key
    result["previous_session_key"] = previous_record.session_key

    return result
