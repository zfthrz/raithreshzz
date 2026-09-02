from __future__ import annotations

import json

import pytest

from deterministic_input_contract import (
    build_lap_time_map,
    load_json,
    resolve_comparison_laps,
    validate_data_model,
    validate_lap_times,
)


def test_input_contract_loads_and_validates_supported_model(tmp_path):
    document = {
        "metadata": {
            "same_vehicle": True,
            "reference_lap": 1,
            "lap_times_s": {"1": 90.0, "2": 90.5},
        },
        "comparisons": [
            {
                "reference_lap": 1,
                "comparison_lap": 2,
                "comparison_minus_reference_s": 0.5,
            }
        ],
    }
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    loaded = load_json(path)
    metadata, comparisons = validate_data_model(loaded)
    assert validate_lap_times(loaded, metadata, comparisons) == {1: 90.0, 2: 90.5}


def test_input_contract_preserves_legacy_lap_identity_and_fail_closed():
    assert resolve_comparison_laps({"lap_a": 3, "lap_b": 4}, {}) == (3, 4)
    assert build_lap_time_map({"metadata": {}, "laps": [{"lap": 3, "duration": 91}]}) == {3: 91.0}
    with pytest.raises(ValueError, match="reference_lap"):
        resolve_comparison_laps({}, {})
    with pytest.raises(ValueError, match="mismo vehículo"):
        validate_data_model({"metadata": {}, "comparisons": []})
