from __future__ import annotations

from pathlib import Path

import llm_analysis_deepseek as legacy
from deterministic_track_context import load_track_location_context


ROOT = Path(__file__).resolve().parents[1]


def without_resolver(context):
    return {key: value for key, value in context.items() if key != "resolver"}


def test_missing_track_metadata_fails_closed():
    assert load_track_location_context({}, base_dir=str(ROOT)) == {
        "status": "NO_TRACK_METADATA",
        "track": None,
        "profile": None,
        "profile_path": None,
        "resolver": None,
    }


def test_real_validated_profile_matches_legacy_contract():
    metadata = {
        "track": "Circuit de Spa-Francorchamps",
        "track_layout": "Circuit de Spa-Francorchamps",
    }
    neutral = load_track_location_context(metadata, base_dir=str(ROOT))
    historical = legacy.load_track_location_context(metadata)
    assert without_resolver(neutral) == without_resolver(historical)
    assert neutral["status"] == "ACTIVE"
    assert callable(neutral["resolver"])
    assert neutral["resolver"](neutral["profile"], 0.0, 50.0) == historical[
        "resolver"
    ](historical["profile"], 0.0, 50.0)


def test_missing_module_fails_closed_before_profile_discovery(tmp_path):
    result = load_track_location_context({"track": "Spa"}, base_dir=str(tmp_path))
    assert result["status"] == "MODULE_NOT_FOUND"
    assert result["profile"] is None
    assert result["resolver"] is None
