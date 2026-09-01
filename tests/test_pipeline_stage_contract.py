from pipeline_stage_contract import (
    DEBRIEF_STAGE,
    DEBRIEF_VALIDATOR_STAGE,
    canonical_stage_name,
    canonical_stage_names,
    stage_payload,
)


def test_legacy_primary_names_map_to_product_names():
    assert canonical_stage_name("llm") == DEBRIEF_STAGE
    assert canonical_stage_name("llm_validator") == DEBRIEF_VALIDATOR_STAGE
    assert canonical_stage_name("h5_2_llm") == "h5_2_llm"


def test_stage_payload_prefers_canonical_and_falls_back_to_legacy():
    legacy = {"llm": {"status": "REUSED"}}
    mixed = {
        "llm": {"status": "REUSED"},
        "debrief": {"status": "RUN"},
    }

    assert stage_payload(legacy, DEBRIEF_STAGE)["status"] == "REUSED"
    assert stage_payload(mixed, DEBRIEF_STAGE)["status"] == "RUN"
    assert stage_payload(None, DEBRIEF_STAGE) == {}


def test_canonical_stage_names_preserve_order_without_alias_duplicates():
    assert canonical_stage_names(
        {"analyze": {}, "llm": {}, "history": {}},
        {"debrief": {}, "llm_validator": {}},
    ) == ("analyze", "debrief", "history", "debrief_validator")
