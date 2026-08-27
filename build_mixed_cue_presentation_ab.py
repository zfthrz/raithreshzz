"""Build read-only A/B artifacts for the reviewed multi-event mixed-cue hypothesis."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from prepare_mixed_cue_review_queue import file_sha256
from shadow_split_mixed_cue_plan import compare_presentations, load_json
from validate_mixed_cue_review_labels import validate as validate_labels


VERSION = "0.1"
STATUS = "SHADOW_AB_READY"
FAVORABLE_LABEL = "FOCUSED_PLUS_PROFILE_BETTER"
MIN_DOMINANT_EVENTS = 2


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_plan_item(document: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    plan = (document.get("session_coaching_facts") or {}).get("next_stint_plan") or []
    matches = [
        item
        for item in plan
        if isinstance(item, dict)
        and item.get("plan_label") == snapshot.get("plan_label")
        and (item.get("track_location") or {}).get("label") == snapshot.get("location")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{snapshot.get('session')}: expected one exact plan item, found {len(matches)}"
        )
    return matches[0]


def _build_case(snapshot: dict[str, Any], human_label: str) -> dict[str, Any] | None:
    if human_label != FAVORABLE_LABEL:
        return None
    if len(snapshot.get("focused_event_texts") or []) < MIN_DOMINANT_EVENTS:
        return None
    source_path = Path(snapshot["source_artifact"])
    if file_sha256(source_path) != snapshot["source_artifact_sha256"]:
        raise ValueError(f"Source artifact changed: {source_path}")
    document = load_json(source_path)
    item = _resolve_plan_item(document, snapshot)
    comparison = compare_presentations(item)
    if not isinstance(comparison, dict):
        raise ValueError(f"Mixed-cue comparison unavailable: {source_path}")
    if comparison.get("dominant_channel") != snapshot.get("dominant_channel"):
        raise ValueError(f"Dominant channel changed: {source_path}")
    if comparison.get("channel_point_support") != snapshot.get("channel_point_support"):
        raise ValueError(f"Physical support changed: {source_path}")

    cues = [cue for cue in item.get("driver_cues") or [] if isinstance(cue, dict)]
    combined = next(cue for cue in cues if cue.get("kind") == "combined_spatial_sequence")
    profile = next(cue for cue in cues if cue.get("kind") == "reference_action_profile")
    sequence = combined.get("coaching_sequence") or {}
    channel = snapshot["dominant_channel"]
    channel_events = [
        copy.deepcopy(event)
        for event in sequence.get("events") or []
        if isinstance(event, dict) and event.get("channel") == channel
    ]
    if len(channel_events) < MIN_DOMINANT_EVENTS:
        raise ValueError(f"Multi-event condition no longer holds: {source_path}")
    focused = {
        "channel": channel,
        "kind": "spatial_points",
        "text": "; después, ".join(str(event.get("text") or "") for event in channel_events),
        "source": "deterministic_multi_event_focus_shadow",
        "channel_events": channel_events,
        "full_sequence_context": copy.deepcopy(sequence),
    }
    return {
        "review_id": snapshot["review_id"],
        "track": snapshot.get("track"),
        "session": snapshot.get("session"),
        "plan_label": snapshot.get("plan_label"),
        "location": snapshot.get("location"),
        "dominant_channel": channel,
        "dominant_event_count": len(channel_events),
        "channel_point_support": snapshot.get("channel_point_support"),
        "human_label": human_label,
        "a_production": {"driver_cues": copy.deepcopy(cues)},
        "b_shadow": {"driver_cues": [focused, copy.deepcopy(profile)]},
        "production_input_mutated": False,
    }


def build_report(queue_path: Path, labels_path: Path) -> dict[str, Any]:
    errors, warnings, validation = validate_labels(queue_path, labels_path)
    if errors or validation.get("pending"):
        detail = "; ".join(errors + warnings) or "review is incomplete"
        raise ValueError(f"Mixed-cue labels are not complete and valid: {detail}")
    queue = load_json(queue_path)
    labels = load_json(labels_path)
    by_id = {item["review_id"]: item for item in queue["review_items"]}
    cases: list[dict[str, Any]] = []
    for record in labels["labels"]:
        snapshot = by_id[record["review_id"]]
        case = _build_case(snapshot, record["human_label"])
        if case is not None:
            cases.append(case)
    cases.sort(key=lambda case: (str(case["track"]), str(case["location"])))
    return {
        "metadata": {
            "version": VERSION,
            "status": STATUS,
            "source_queue": str(queue_path.resolve()),
            "source_queue_sha256": _sha256(queue_path),
            "source_labels": str(labels_path.resolve()),
            "source_labels_sha256": _sha256(labels_path),
            "policy": {
                "unique_dominant_channel_required": True,
                "minimum_dominant_event_count": MIN_DOMINANT_EVENTS,
                "reference_action_profile_required": True,
                "human_label_required": FAVORABLE_LABEL,
                "production_changed": False,
                "next_stint_plan_changed": False,
                "presentation_authorized": False,
            },
        },
        "summary": {
            "reviewed_items": validation["reviewed"],
            "ab_case_count": len(cases),
            "by_dominant_channel": {
                "brake": sum(case["dominant_channel"] == "brake" for case in cases),
                "throttle": sum(case["dominant_channel"] == "throttle" for case in cases),
            },
        },
        "cases": cases,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Mixed cue presentation A/B — shadow v0.1",
        "",
        f"Casos: {report['summary']['ab_case_count']}",
        "",
        "No modifica producción, `next_stint_plan` ni autoridad de coaching.",
    ]
    for index, case in enumerate(report["cases"], 1):
        a_cues = case["a_production"]["driver_cues"]
        b_cues = case["b_shadow"]["driver_cues"]
        lines.extend(
            [
                "",
                f"## {index}. {case['track']} — {case['location']}",
                "",
                f"Canal dominante: `{case['dominant_channel']}` · eventos: {case['dominant_event_count']}",
                "",
                "### A — Producción",
                "",
                *[f"- {cue.get('text')}" for cue in a_cues],
                "",
                "### B — Focused + perfil",
                "",
                *[f"- {cue.get('text')}" for cue in b_cues],
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build reviewed multi-event mixed-cue A/B shadow.")
    parser.add_argument("queue_json", type=Path)
    parser.add_argument("labels_json", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    report = build_report(args.queue_json.resolve(), args.labels_json.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print("=" * 88)
    print("RACE ENGINEER - MIXED CUE MULTI-EVENT A/B SHADOW v0.1")
    print("=" * 88)
    print(f"Reviewed labels: {report['summary']['reviewed_items']}")
    print(f"A/B cases: {report['summary']['ab_case_count']}")
    print(f"Dominant channels: {report['summary']['by_dominant_channel']}")
    print(f"Output: {args.output.resolve()}")
    print("Authority: SHADOW ONLY")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
