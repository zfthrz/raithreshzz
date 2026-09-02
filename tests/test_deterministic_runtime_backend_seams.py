from __future__ import annotations

import llm_analysis_deepseek as backend
from deterministic_comparison_preparation import PreparedComparison


def test_global_runtime_stage_bypasses_legacy_provider_and_transport(monkeypatch):
    monkeypatch.setattr(
        backend,
        "get_validated_global_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy global provider reached")
        ),
    )
    monkeypatch.setattr(
        backend,
        "deepseek_chat",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("transport reached")
        ),
    )
    monkeypatch.setattr(
        backend,
        "validate_global_llm_response",
        lambda response, comparisons, facts: [],
    )
    monkeypatch.setattr(
        backend,
        "build_deterministic_next_session_priorities",
        lambda facts: ["prioridad determinista"],
    )

    result = backend._stage_get_global_response(
        {"track": "Spa"},
        [],
        {"next_stint_plan": []},
        "unused-debug-dir",
    )

    assert result["status"] == "VALID"
    assert result["attempts"] == 0
    assert result["deterministic_first"] is True
    assert result["response"]["next_session_priorities"] == [
        "prioridad determinista"
    ]


def test_comparison_runtime_stage_bypasses_legacy_provider_and_transport(monkeypatch):
    monkeypatch.setattr(
        backend,
        "get_validated_comparison_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy comparison provider reached")
        ),
    )
    monkeypatch.setattr(
        backend,
        "deepseek_chat",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("transport reached")
        ),
    )
    pipeline_calls = []

    def fake_pipeline(*args, **kwargs):
        pipeline_calls.append(kwargs)
        return {
            "status": "VALID",
            "attempts": 0,
            "response": {"episode_assessments": []},
        }

    monkeypatch.setattr(backend, "build_validated_comparison_response", fake_pipeline)
    monkeypatch.setattr(
        backend,
        "render_comparison_analysis",
        lambda comparison, episodes, response: "rendered",
    )
    comparison = {
        "reference_lap": 1,
        "comparison_lap": 2,
        "reference_time_s": 90.0,
        "comparison_time_s": 90.5,
        "comparison_minus_reference_s": 0.5,
    }
    prepared = PreparedComparison(
        comparison_quality={},
        session_plan_eligible=True,
        detected_episode_catalog=[{"episode_id": 1}],
        episode_catalog=[{"episode_id": 1}],
        excluded_anomalies=[],
    )

    execution = backend._stage_execute_comparison(
        comparison,
        prepared,
        {"track": "Spa"},
        "unused-debug-dir",
    )

    assert execution.route == "ELIGIBLE"
    assert execution.result["analysis"] == "rendered"
    assert len(pipeline_calls) == 1
    assert callable(pipeline_calls[0]["get_episode_response"])
    assert callable(pipeline_calls[0]["get_ranker_response"])
    assert callable(pipeline_calls[0]["get_summary_response"])


def test_input_runtime_stage_bypasses_legacy_load_and_validation(monkeypatch, tmp_path):
    source = {
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
    import json
    path.write_text(json.dumps(source), encoding="utf-8")
    for name in ("load_json", "validate_data_model", "validate_lap_times"):
        monkeypatch.setattr(
            backend,
            name,
            lambda *args, _name=name, **kwargs: (_ for _ in ()).throw(
                AssertionError(f"legacy {_name} reached")
            ),
        )
    monkeypatch.setattr(
        backend,
        "build_llm_dataset",
        lambda data, laps: {
            "metadata": data["metadata"],
            "comparisons": data["comparisons"],
        },
    )
    monkeypatch.setattr(
        backend,
        "load_track_location_context",
        lambda metadata: {"status": "NO_TRACK_PROFILE"},
    )
    prepared = backend._stage_prepare_input(str(path))
    assert prepared.comparisons[0]["reference_lap"] == 1
    assert prepared.comparisons[0]["comparison_lap"] == 2
    assert prepared.comparisons[0]["comparison_minus_reference_s"] == 0.5


def test_input_runtime_stage_bypasses_legacy_dataset_builder(monkeypatch, tmp_path):
    import json

    source = {
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
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(
        backend,
        "build_llm_dataset",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy dataset builder reached")
        ),
    )
    monkeypatch.setattr(
        backend,
        "load_track_location_context",
        lambda metadata: {"status": "NO_TRACK_PROFILE"},
    )
    prepared = backend._stage_prepare_input(str(path))
    assert prepared.comparisons[0]["comparison_lap"] == 2


def test_input_runtime_stage_bypasses_legacy_track_context_loader(
    monkeypatch, tmp_path
):
    import json

    source = {
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
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(
        backend,
        "load_track_location_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy track context loader reached")
        ),
    )
    prepared = backend._stage_prepare_input(str(path))
    assert prepared.track_location_context["status"] == "NO_TRACK_METADATA"
