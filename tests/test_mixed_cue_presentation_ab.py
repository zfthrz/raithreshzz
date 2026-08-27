from __future__ import annotations

import json
from pathlib import Path

from build_mixed_cue_presentation_ab import build_report, render_markdown
from label_mixed_cue_review_queue import load_labels, save, upsert
from prepare_mixed_cue_review_queue import build_queue
from tests.test_mixed_cue_review_queue import debrief


def inputs(tmp_path: Path, *, label: str = "FOCUSED_PLUS_PROFILE_BETTER") -> tuple[Path, Path]:
    source = debrief(tmp_path / "debrief.json")
    document = json.loads(source.read_text(encoding="utf-8"))
    item = document["session_coaching_facts"]["next_stint_plan"][0]
    item["brake_release_patterns"] = [{"comparison_count": 2}]
    item["driver_cues"][0]["coaching_sequence"]["events"].insert(
        1,
        {"channel": "brake", "text": "soltá el freno más tarde"},
    )
    source.write_text(json.dumps(document), encoding="utf-8")
    queue = build_queue([source])
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    labels_path = tmp_path / "labels.json"
    labels = load_labels(labels_path, queue_path)
    upsert(labels, queue["review_items"][0], label, "")
    save(labels_path, labels)
    return queue_path, labels_path


def test_builds_ab_only_for_human_favorable_multi_event_case(tmp_path: Path):
    queue_path, labels_path = inputs(tmp_path)

    report = build_report(queue_path, labels_path)

    assert report["metadata"]["policy"]["production_changed"] is False
    assert report["summary"]["ab_case_count"] == 1
    case = report["cases"][0]
    assert case["dominant_channel"] == "brake"
    assert case["dominant_event_count"] == 2
    assert len(case["a_production"]["driver_cues"]) == 2
    assert [cue["channel"] for cue in case["b_shadow"]["driver_cues"]] == [
        "brake",
        "throttle",
    ]
    assert case["b_shadow"]["driver_cues"][0]["full_sequence_context"]


def test_non_favorable_human_label_is_not_rendered(tmp_path: Path):
    queue_path, labels_path = inputs(tmp_path, label="COMBINED_BETTER")

    report = build_report(queue_path, labels_path)

    assert report["summary"]["ab_case_count"] == 0


def test_markdown_contains_both_presentations(tmp_path: Path):
    queue_path, labels_path = inputs(tmp_path)

    rendered = render_markdown(build_report(queue_path, labels_path))

    assert "### A — Producción" in rendered
    assert "### B — Focused + perfil" in rendered
    assert "frená y después acelerá" in rendered
    assert "soltá el freno más tarde" in rendered


def test_source_hash_change_fails_closed(tmp_path: Path):
    queue_path, labels_path = inputs(tmp_path)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    source = Path(queue["review_items"][0]["source_artifact"])
    source.write_text("{}", encoding="utf-8")

    try:
        build_report(queue_path, labels_path)
    except ValueError as exc:
        assert "Source artifact changed" in str(exc)
    else:
        raise AssertionError("source hash drift must fail closed")
