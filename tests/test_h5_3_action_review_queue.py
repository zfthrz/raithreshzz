from __future__ import annotations

import json
from pathlib import Path

import pytest

from historical_action_policy import build_action_candidates
from prepare_h5_3_action_review_queue import build_queue


def _write_artifact(tmp_path: Path, name: str, candidate_id: str, codes: list[str]) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    selection_path = directory / "candidate_selection.json"
    selection = {
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": [{
            "candidate_id": candidate_id,
            "context": {
                "track": "Test Track",
                "track_layout": "Test Layout",
                "vehicle_variant": "LMP2",
                "car_name_raw": "Test Car",
            },
            "delta_sign": "current_slower",
            "location_label": "T1 - Test",
            "delta_change_s": 0.25,
            "authorized_observations": codes,
        }],
        "llm_selection": {"selected_candidates": [{
            "candidate_id": candidate_id,
            "significance": "primary",
            "observation_codes": codes,
        }]},
    }
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    artifact_path = directory / "historical_actions.json"
    artifact_path.write_text(
        json.dumps(build_action_candidates(selection_path)),
        encoding="utf-8",
    )
    return artifact_path


def test_queue_groups_equivalent_actions_and_preserves_occurrences(tmp_path: Path):
    first = _write_artifact(
        tmp_path, "session_a", "session-a:candidate", ["time_loss", "current_brake_higher"]
    )
    second = _write_artifact(
        tmp_path, "session_b", "session-b:candidate", ["current_brake_higher", "time_loss"]
    )

    queue = build_queue([second, first], input_root=tmp_path)

    assert queue["metadata"]["historical_actions_authorized"] is False
    assert queue["metadata"]["session_reference_remains_authority"] is True
    assert queue["summary"] == {
        "review_item_count": 1,
        "source_occurrence_count": 2,
        "by_decision": {"AUTHORIZED_SHADOW_ACTION": 1},
    }
    item = queue["review_items"][0]
    assert item["actions"] == ["reduce_brake"]
    assert item["occurrence_count"] == 2
    assert [occurrence["candidate_id"] for occurrence in item["occurrences"]] == [
        "session-a:candidate",
        "session-b:candidate",
    ]


def test_queue_includes_withheld_context_from_selection(tmp_path: Path):
    artifact = _write_artifact(
        tmp_path,
        "session_a",
        "session-a:withheld",
        ["time_loss", "current_throttle_higher"],
    )

    queue = build_queue([artifact], input_root=tmp_path)

    item = queue["review_items"][0]
    assert item["decision"] == "WITHHELD"
    assert item["reason"] == "insufficient_action_context"
    assert item["context"]["track"] == "Test Track"
    assert item["actions"] == []


def test_queue_rejects_invalid_or_authorized_artifact(tmp_path: Path):
    artifact = _write_artifact(
        tmp_path, "session_a", "session-a:candidate", ["current_brake_higher"]
    )
    document = json.loads(artifact.read_text(encoding="utf-8"))
    document["coaching_authority"]["historical_actions_authorized"] = True
    artifact.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid historical actions"):
        build_queue([artifact], input_root=tmp_path)
