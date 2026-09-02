from __future__ import annotations

from copy import deepcopy

import pytest

from deterministic_debrief_finalize import finalize_validated_global_debrief


def test_finalize_preserves_render_and_compacts_audit_without_mutation():
    validated = {
        "status": "VALID",
        "attempts": 0,
        "response": {"conclusion": "ok"},
        "fallback": None,
        "deterministic_repairs": {},
        "pruned_global_items": ["x"],
        "llm_validation_errors": [],
    }
    before = deepcopy(validated)
    calls = []

    structured, audit, analysis = finalize_validated_global_debrief(
        global_validated=validated,
        metadata={"track": "Spa"},
        comparison_results=[{"comparison_lap": 2}],
        session_coaching_facts={"next_stint_plan": [{"plan_label": "A"}]},
        track_location_context={"profile": {"profile_id": "spa"}},
        render_global=lambda metadata, comparisons, facts, response: "Global  ",
        render_track_reference=lambda profile, plan: calls.append((profile, plan))
        or "Track reference",
    )

    assert structured is validated["response"]
    assert audit == {
        "status": "VALID",
        "attempts": 0,
        "pruned_global_items": ["x"],
    }
    assert analysis == "Global\n\nTrack reference"
    assert calls == [
        ({"profile_id": "spa"}, [{"plan_label": "A"}])
    ]
    assert validated == before


def test_finalize_keeps_global_render_when_track_section_is_empty():
    _, _, analysis = finalize_validated_global_debrief(
        global_validated={"status": "VALID", "response": {}},
        metadata={},
        comparison_results=[],
        session_coaching_facts={},
        track_location_context={},
        render_global=lambda *args: "Global\n",
        render_track_reference=lambda *args: "",
    )
    assert analysis == "Global\n"


@pytest.mark.parametrize(
    "validated",
    [
        {"status": "REJECTED", "response": {}},
        {"status": "VALID", "response": None},
    ],
)
def test_finalize_rejects_invalid_contract(validated):
    with pytest.raises(ValueError):
        finalize_validated_global_debrief(
            global_validated=validated,
            metadata={},
            comparison_results=[],
            session_coaching_facts={},
            track_location_context={},
            render_global=lambda *args: "",
            render_track_reference=lambda *args: "",
        )
