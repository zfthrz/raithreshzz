"""Named promotion requirements for H5.3f v0.2 reviewed-action evidence gate.

This module externalises every hard-coded requirement that the v0.2 gate checks.
It is read-only data: changing a value changes the gate's verdict for the same
inputs. The gate remains the authority. The manifest only declares what it
evaluates.

No policy promotion, no threshold change, no validator or tolerance update.
"""
from __future__ import annotations

from typing import Any, Sequence

PROMOTION_REQUIREMENTS: dict[str, Any] = {
    "h5_3f_v0_2": {
        "required_tracks": [
            "Fuji Speedway",
            "Autodromo Enzo e Dino Ferrari",
            "Autódromo José Carlos Pace",
            "Autodromo Nazionale Monza",
        ],
        "required_delta_signs": [
            "current_slower",
            "current_faster",
        ],
        "required_action_codes": [
            "increase_brake",
            "increase_throttle",
            "reduce_brake",
            "reduce_throttle",
        ],
        "required_authorized_single_actions": [
            ["increase_brake"],
            ["increase_throttle"],
            ["reduce_brake"],
        ],
        "affirmative_labels": {
            "AUTHORIZED_SHADOW_ACTION": "ACTION_USEFUL",
            "WITHHELD": "CORRECTLY_WITHHELD",
        },
        "max_non_affirmative_labels": None,
        "min_reviewed_items": None,
        "isolated_reduce_throttle_withheld": {
            "decision": "WITHHELD",
            "reason": "insufficient_action_context",
            "observation_code": "current_throttle_higher",
        },
    },
}


def get_manifest(key: str = "h5_3f_v0_2") -> dict[str, Any]:
    """Return the manifest dict for *key* (default: h5_3f_v0_2)."""
    try:
        return PROMOTION_REQUIREMENTS[key]
    except KeyError:
        raise KeyError(f"Unknown promotion manifest key: {key}")
