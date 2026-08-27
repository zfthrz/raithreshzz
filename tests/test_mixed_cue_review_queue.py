from __future__ import annotations

import json
from pathlib import Path

from label_mixed_cue_review_queue import load_labels, pending, save, upsert
from prepare_mixed_cue_review_queue import build_queue
from validate_mixed_cue_review_labels import validate


def debrief(path: Path) -> Path:
    payload = {
        "metadata": {"track": "Test Track"},
        "session_coaching_facts": {
            "next_stint_plan": [
                {
                    "plan_label": "A",
                    "track_location": {"label": "T1"},
                    "braking_point_patterns": [
                        {"comparison_count": 3}
                    ],
                    "brake_release_patterns": [],
                    "throttle_onset_patterns": [],
                    "throttle_release_patterns": [
                        {"comparison_count": 1}
                    ],
                    "driver_cues": [
                        {
                            "channel": "brake+throttle",
                            "kind": "combined_spatial_sequence",
                            "text": "frená y después acelerá",
                            "coaching_sequence": {
                                "events": [
                                    {
                                        "channel": "brake",
                                        "text": "frená más tarde",
                                    },
                                    {
                                        "channel": "throttle",
                                        "text": "acelerá más tarde",
                                    },
                                ]
                            },
                        },
                        {
                            "channel": "throttle",
                            "kind": "reference_action_profile",
                            "text": "sostené como la referencia",
                        },
                    ],
                }
            ]
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_queue_contains_only_supported_channel_plus_profile_cases(tmp_path: Path):
    queue = build_queue([debrief(tmp_path / "debrief.json")])

    assert queue["metadata"]["shadow_only"] is True
    assert queue["summary"] == {
        "review_item_count": 1,
        "brake_dominant": 1,
        "throttle_dominant": 0,
    }
    item = queue["review_items"][0]
    assert item["dominant_channel"] == "brake"
    assert item["focused_event_texts"] == ["frená más tarde"]
    assert item["reference_profile_text"] == "sostené como la referencia"


def test_queue_excludes_support_ties(tmp_path: Path):
    source = debrief(tmp_path / "debrief.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["session_coaching_facts"]["next_stint_plan"][0][
        "throttle_release_patterns"
    ][0]["comparison_count"] = 3
    source.write_text(json.dumps(payload), encoding="utf-8")

    assert build_queue([source])["review_items"] == []


def test_labels_are_resumable_and_validate_exact_snapshot(tmp_path: Path):
    queue_path = tmp_path / "queue.json"
    queue = build_queue([debrief(tmp_path / "debrief.json")])
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    labels_path = tmp_path / "labels.json"
    labels = load_labels(labels_path, queue_path)
    item = queue["review_items"][0]

    upsert(labels, item, "FOCUSED_PLUS_PROFILE_BETTER", "más claro")
    save(labels_path, labels)

    assert pending(queue, labels) == []
    errors, warnings, summary = validate(queue_path, labels_path)
    assert errors == []
    assert warnings == []
    assert summary["reviewed"] == 1
    assert summary["counts"] == {"FOCUSED_PLUS_PROFILE_BETTER": 1}


def test_validator_rejects_tampered_snapshot(tmp_path: Path):
    queue_path = tmp_path / "queue.json"
    queue = build_queue([debrief(tmp_path / "debrief.json")])
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    labels_path = tmp_path / "labels.json"
    labels = load_labels(labels_path, queue_path)
    item = queue["review_items"][0]
    upsert(labels, item, "AMBIGUOUS", "")
    labels["labels"][0]["item_snapshot"]["dominant_channel"] = "throttle"
    save(labels_path, labels)

    errors, _, _ = validate(queue_path, labels_path)
    assert any("item_snapshot no coincide" in error for error in errors)
