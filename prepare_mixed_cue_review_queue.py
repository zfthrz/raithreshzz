"""Build a deterministic human-review queue for mixed-cue shadow v0.2."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from shadow_split_mixed_cue_plan import (
    compare_presentations,
    current_validated_debrief_paths,
    load_json,
)


SCHEMA_VERSION = "1.0"
STATUS = "MIXED_CUE_PRESENTATION_REVIEW_READY"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _review_id(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _review_item(path: Path, document: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    comparison = compare_presentations(item)
    if not isinstance(comparison, dict):
        return None
    if comparison["preferred_shadow_presentation"] != "supported_channel_plus_profile":
        return None
    cues = [cue for cue in item.get("driver_cues") or [] if isinstance(cue, dict)]
    combined = next(cue for cue in cues if cue.get("kind") == "combined_spatial_sequence")
    profile = next(cue for cue in cues if cue.get("kind") == "reference_action_profile")
    channel = comparison["dominant_channel"]
    events = [
        event
        for event in (combined.get("coaching_sequence") or {}).get("events") or []
        if isinstance(event, dict) and event.get("channel") == channel
    ]
    metadata = document.get("metadata") or {}
    snapshot = {
        "source_artifact": str(path.resolve()),
        "source_artifact_sha256": file_sha256(path),
        "track": metadata.get("track"),
        "session": path.parent.name,
        "plan_label": item.get("plan_label"),
        "location": (item.get("track_location") or {}).get("label"),
        "dominant_channel": channel,
        "channel_point_support": comparison["channel_point_support"],
        "combined_text": combined.get("text"),
        "focused_event_texts": [event.get("text") for event in events],
        "reference_profile_text": profile.get("text"),
        "preference_reason": comparison["preference_reason"],
    }
    return {"review_id": _review_id(snapshot), **snapshot}


def build_queue(paths: Iterable[Path]) -> dict[str, Any]:
    resolved = sorted({Path(path).resolve() for path in paths}, key=str)
    items: list[dict[str, Any]] = []
    for path in resolved:
        document = load_json(path)
        facts = document.get("session_coaching_facts") or {}
        for plan_item in facts.get("next_stint_plan") or []:
            if not isinstance(plan_item, dict):
                continue
            review_item = _review_item(path, document, plan_item)
            if review_item is not None:
                items.append(review_item)
    items.sort(key=lambda item: (str(item["track"]), str(item["location"]), item["review_id"]))
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "status": STATUS,
            "source_artifact_count": len(resolved),
            "shadow_only": True,
            "production_changed": False,
            "presentation_preference_authorized": False,
        },
        "summary": {
            "review_item_count": len(items),
            "brake_dominant": sum(item["dominant_channel"] == "brake" for item in items),
            "throttle_dominant": sum(item["dominant_channel"] == "throttle" for item in items),
        },
        "review_items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare mixed-cue presentation review queue.")
    parser.add_argument("--runs-dir", default="data/generated/runs", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    paths = current_validated_debrief_paths(args.runs_dir)
    queue = build_queue(paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("=" * 88)
    print("RACE ENGINEER - MIXED CUE PRESENTATION REVIEW QUEUE v1.0")
    print("=" * 88)
    print(f"Validated current artifacts: {len(paths)}")
    print(f"Review items: {queue['summary']['review_item_count']}")
    print(f"Brake dominant: {queue['summary']['brake_dominant']}")
    print(f"Throttle dominant: {queue['summary']['throttle_dominant']}")
    print(f"Output: {args.output.resolve()}")
    print("Authority: SHADOW ONLY")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
