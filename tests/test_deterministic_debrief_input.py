from __future__ import annotations

from deterministic_debrief_input import prepare_debrief_input


def test_prepare_input_preserves_pipeline_order_and_outputs():
    calls = []
    source = {"raw": True}
    raw_metadata = {"raw": "metadata"}
    raw_comparisons = [{"raw": "comparison"}]
    prepared_metadata = {"track": "Spa"}
    comparisons = [{"reference_lap": 1, "comparison_lap": 2}]

    def load(path):
        calls.append(("load", path))
        return source

    def validate(data):
        calls.append(("validate", data))
        return raw_metadata, raw_comparisons

    def laps(data, metadata, raw):
        calls.append(("laps", data, metadata, raw))
        return {1: 90.0, 2: 91.0}

    def dataset(data, lap_times):
        calls.append(("dataset", data, lap_times))
        return {"metadata": prepared_metadata, "comparisons": comparisons}

    def context(metadata):
        calls.append(("context", metadata))
        return {"status": "ACTIVE"}

    result = prepare_debrief_input(
        "input.json",
        load_json=load,
        validate_data_model=validate,
        validate_lap_times=laps,
        build_dataset=dataset,
        load_track_location_context=context,
    )
    assert result.source_data is source
    assert result.metadata is prepared_metadata
    assert result.comparisons is comparisons
    assert result.track_location_context == {"status": "ACTIVE"}
    assert [call[0] for call in calls] == [
        "load",
        "validate",
        "laps",
        "dataset",
        "context",
    ]


def test_prepare_input_preserves_track_context_call_before_empty_failure():
    context_calls = []
    try:
        prepare_debrief_input(
            "input.json",
            load_json=lambda path: {},
            validate_data_model=lambda data: ({}, []),
            validate_lap_times=lambda data, metadata, raw: {},
            build_dataset=lambda data, laps: {"metadata": {}, "comparisons": []},
            load_track_location_context=lambda metadata: context_calls.append(True),
        )
    except RuntimeError as exc:
        assert str(exc) == "El JSON no contiene comparaciones."
    else:
        raise AssertionError("empty comparisons must fail closed")
    assert context_calls == [True]
