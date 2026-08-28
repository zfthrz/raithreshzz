import json
from pathlib import Path

import pytest

from label_episode_pairs import load_queue
from prepare_h3_projection_review import (
    build_review_items,
    collect_projection_references,
)


CONTEXT = {
    "track": "Test Track",
    "track_layout": "Test Layout",
    "vehicle_variant": "GT3",
}


def _write_selection(
    generated: Path,
    stem: str,
    *,
    session_id: int,
    automatic: bool = True,
    context: dict | None = None,
) -> Path:
    path = generated / "h3_1" / stem / "persistent_pattern_selection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "metadata": {
                "session_id": session_id,
                "context": context or CONTEXT,
                "observational_only": True,
                "affects_next_stint_plan": False,
                "historical_actions_authorized": False,
            },
            "provenance": {"source_bundle_sha256": "a" * 64},
            "projected_pattern_matches": [{
                "pattern_id": "pat_1",
                "state": "persistent_pattern",
                "match_basis": "calibrated_h2_match_to_pattern_representative",
                "representative_member": {"session_id": 1, "episode_pk": 10},
                "current_session_episode": {"episode_pk": session_id * 10},
                "matcher_decision": {
                    "decision": "MATCH",
                    "automatic": automatic,
                    "rule_id": "CORE_SPATIAL_MATCH",
                },
            }],
        }),
        encoding="utf-8",
    )
    return path


def _features(reference: dict) -> dict:
    return {
        "track": reference["context"]["track"],
        "track_layout": reference["context"]["track_layout"],
        "vehicle_variant": reference["context"]["vehicle_variant"],
        "session_a": reference["representative_session_id"],
        "episode_pk_a": reference["representative_episode_pk"],
        "episode_id_a": 1,
        "session_b": reference["current_session_id"],
        "episode_pk_b": reference["current_episode_pk"],
        "episode_id_b": 2,
        "channels_a": ["brake"],
        "channels_b": ["brake"],
        "shared_channels": ["brake"],
        "per_channel_metrics": {},
    }


def test_collects_only_exact_filtered_valid_automatic_projections(tmp_path: Path):
    generated = tmp_path / "generated"
    _write_selection(generated, "a", session_id=2)
    _write_selection(generated, "b", session_id=3, automatic=False)
    _write_selection(
        generated,
        "c",
        session_id=4,
        context={
            "track": "Other",
            "track_layout": "Other",
            "vehicle_variant": "GT3",
        },
    )

    references, errors = collect_projection_references(
        generated,
        track="Test Track",
        track_layout="Test Layout",
        vehicle_variant="GT3",
    )

    assert len(references) == 1
    assert references[0]["current_session_id"] == 2
    assert len(errors) == 1
    assert errors[0].startswith("projection_contract_invalid:")


def test_queue_is_compatible_with_existing_h2_labeler(tmp_path: Path):
    generated = tmp_path / "generated"
    _write_selection(generated, "a", session_id=2)
    references, errors = collect_projection_references(generated)
    assert errors == []

    items = build_review_items(references, _features)
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(
        json.dumps({"metadata": {"review_scope": "H3_2_PROJECTION_VALIDATION_ONLY"}, "queue": items}),
        encoding="utf-8",
    )

    loaded = load_queue(queue_path)
    assert len(loaded["queue"]) == 1
    assert loaded["queue"][0]["features"]["session_a"] == 1
    assert loaded["queue"][0]["features"]["session_b"] == 2
    assert loaded["queue"][0]["review_scope"] == "H3_2_PROJECTION_VALIDATION_ONLY"


def test_deduplicates_same_physical_pair_and_preserves_projection_evidence():
    reference = {
        "context": CONTEXT,
        "pattern_id": "pat_1",
        "pattern_state": "persistent_pattern",
        "representative_session_id": 1,
        "representative_episode_pk": 10,
        "current_session_id": 2,
        "current_episode_pk": 20,
        "matcher_decision": {"decision": "MATCH", "automatic": True},
        "source_selection_path": "a.json",
        "source_selection_sha256": "a" * 64,
        "source_bundle_sha256": "b" * 64,
        "projection_snapshot_sha256": "c" * 64,
    }
    second = dict(reference, pattern_id="pat_2")

    items = build_review_items([reference, second], _features)

    assert len(items) == 1
    assert [item["pattern_id"] for item in items[0]["h3_projection_evidence"]] == [
        "pat_1",
        "pat_2",
    ]


def test_reconstructed_pair_identity_must_match_projection():
    reference = {
        "context": CONTEXT,
        "pattern_id": "pat_1",
        "pattern_state": "persistent_pattern",
        "representative_session_id": 1,
        "representative_episode_pk": 10,
        "current_session_id": 2,
        "current_episode_pk": 20,
        "matcher_decision": {"decision": "MATCH", "automatic": True},
        "source_selection_path": "a.json",
        "source_selection_sha256": "a" * 64,
        "source_bundle_sha256": "b" * 64,
        "projection_snapshot_sha256": "c" * 64,
    }

    def wrong_features(item):
        value = _features(item)
        value["episode_pk_b"] = 999
        return value

    with pytest.raises(ValueError, match="no coincide"):
        build_review_items([reference], wrong_features)
