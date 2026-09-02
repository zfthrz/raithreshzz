from __future__ import annotations

import json
from datetime import datetime, timezone

import deterministic_debrief_output as output


def test_save_compatible_debrief_builds_and_writes_exact_contract(
    monkeypatch, tmp_path
):
    destination = tmp_path / "result.json"
    monkeypatch.setattr(
        output,
        "compatible_debrief_output_path",
        lambda input_path, model_name: (destination, destination.parent),
    )
    fixed = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    result_path, result_dir = output.save_compatible_debrief(
        "source.json",
        {"track": "Spa"},
        [],
        {"next_stint_plan": []},
        {"conclusion": "Conclusión"},
        "Render",
        {"status": "VALID"},
        model_name="deterministic",
        usage_summary={"calls": 0},
        context_size=0,
        temperature=0.0,
        anomaly_gate_config={"limit": 1},
        now=lambda: fixed,
    )
    document = json.loads(destination.read_text(encoding="utf-8"))
    assert result_path == str(destination)
    assert result_dir == str(destination.parent)
    assert document["metadata"]["analysis_timestamp"] == fixed.isoformat()
    assert document["metadata"]["model"] == "deterministic"
    assert document["global_analysis"] == "Render"


def test_save_provider_does_not_mutate_inputs(monkeypatch, tmp_path):
    destination = tmp_path / "result.json"
    monkeypatch.setattr(
        output,
        "compatible_debrief_output_path",
        lambda input_path, model_name: (destination, destination.parent),
    )
    facts = {"next_stint_plan": []}
    output.save_compatible_debrief(
        "source.json",
        {},
        [],
        facts,
        {},
        "",
        model_name="deterministic",
        usage_summary={},
        context_size=0,
        temperature=0.0,
        anomaly_gate_config={},
    )
    assert facts == {"next_stint_plan": []}
