"""Group H5.3h candidates by exact zone and quantitative channel pattern."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from validate_h5_3_local_loss_policy import validate as validate_evaluation


AUDIT_VERSION = "0.1"
SCHEMA_VERSION = "1.0"
STATUS = "SHADOW_LOCAL_LOSS_RECURRENCE_AUDIT"
MIN_INDEPENDENT_OCCURRENCES = 2


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("evaluation JSON root must be an object")
    errors = validate_evaluation(document)
    if errors:
        raise ValueError("invalid H5.3h evaluation: " + "; ".join(errors))
    return document


def _direction(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "unavailable"
    if value > 0:
        return "higher"
    if value < 0:
        return "lower"
    return "neutral"


def _source_identity(candidate_id: Any) -> str:
    value = str(candidate_id or "")
    return value.split(":", 1)[0] if ":" in value else value


def _context_key(context: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(context.get("track") or ""),
        str(context.get("track_layout") or ""),
        str(context.get("vehicle_variant") or ""),
    )


def _canonical_context(context: dict[str, Any]) -> dict[str, str]:
    track, layout, vehicle = _context_key(context)
    return {
        "track": track,
        "track_layout": layout,
        "vehicle_variant": vehicle,
    }


def _pattern(occurrence: dict[str, Any]) -> dict[str, str]:
    return {
        "speed": _direction(occurrence.get("speed_delta_avg")),
        "throttle": _direction(occurrence.get("throttle_delta_avg")),
        "brake": _direction(occurrence.get("brake_delta_avg")),
    }


def _pattern_key(pattern: dict[str, str]) -> tuple[str, str, str]:
    return pattern["speed"], pattern["throttle"], pattern["brake"]


def build_audit(evaluation_path: Path) -> dict[str, Any]:
    evaluation_path = Path(evaluation_path).resolve()
    evaluation = _load(evaluation_path)
    records: list[dict[str, Any]] = []
    for case in evaluation.get("local_policy_candidates", []):
        context = case.get("context") or {}
        for occurrence in case.get("occurrences", []):
            pattern = _pattern(occurrence)
            records.append({
                "review_id": case.get("review_id"),
                "context": context,
                "location_label": case.get("location_label"),
                "candidate_id": occurrence.get("candidate_id"),
                "source_identity": _source_identity(occurrence.get("candidate_id")),
                "delta_change_s": occurrence.get("delta_change_s"),
                "channel_pattern": pattern,
            })

    exact: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    contextual: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        context_key = _context_key(record["context"])
        pattern_key = _pattern_key(record["channel_pattern"])
        exact[context_key + (str(record["location_label"]),) + pattern_key].append(record)
        contextual[context_key + pattern_key].append(record)

    exact_groups: list[dict[str, Any]] = []
    for key, items in sorted(exact.items()):
        source_count = len({item["source_identity"] for item in items})
        exact_groups.append({
            "context": _canonical_context(items[0]["context"]),
            "location_label": items[0]["location_label"],
            "channel_pattern": items[0]["channel_pattern"],
            "occurrence_count": len(items),
            "independent_source_count": source_count,
            "recurrence_status": (
                "EXACT_ZONE_RECURRENCE_OBSERVED"
                if source_count >= MIN_INDEPENDENT_OCCURRENCES
                else "SINGLE_SOURCE_ONLY"
            ),
            "occurrences": sorted(items, key=lambda item: str(item["candidate_id"])),
        })

    cross_zone_groups: list[dict[str, Any]] = []
    for key, items in sorted(contextual.items()):
        locations = sorted({str(item["location_label"]) for item in items})
        sources = {item["source_identity"] for item in items}
        if len(locations) < 2:
            continue
        cross_zone_groups.append({
            "context": _canonical_context(items[0]["context"]),
            "channel_pattern": items[0]["channel_pattern"],
            "distinct_location_count": len(locations),
            "independent_source_count": len(sources),
            "status": "CROSS_ZONE_PATTERN_ONLY",
            "location_labels": locations,
            "occurrences": sorted(items, key=lambda item: str(item["candidate_id"])),
        })

    recurrent_count = sum(
        group["recurrence_status"] == "EXACT_ZONE_RECURRENCE_OBSERVED"
        for group in exact_groups
    )
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "audit_version": AUDIT_VERSION,
            "status": STATUS,
            "source_evaluation_json": str(evaluation_path),
            "source_evaluation_sha256": file_sha256(evaluation_path),
        },
        "contract": {
            "shadow_only": True,
            "exact_zone_recurrence_requires_independent_sources": True,
            "cross_zone_patterns_do_not_confirm_zone_recurrence": True,
            "automatic_action_generation": False,
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        },
        "summary": {
            "candidate_occurrence_count": len(records),
            "exact_zone_group_count": len(exact_groups),
            "exact_zone_recurrence_count": recurrent_count,
            "cross_zone_pattern_count": len(cross_zone_groups),
        },
        "exact_zone_groups": exact_groups,
        "cross_zone_patterns": cross_zone_groups,
        "next_step": (
            "REVIEW_RECURRENT_EXACT_ZONE_PATTERNS"
            if recurrent_count
            else "COLLECT_MORE_EXACT_ZONE_CONFIRMATIONS"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit H5.3i local-loss recurrence.")
    parser.add_argument("local_loss_policy_evaluation_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_audit(Path(args.local_loss_policy_evaluation_json))
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("=" * 88)
    print("RACE ENGINEER - H5.3i LOCAL-LOSS RECURRENCE AUDIT v0.1")
    print("=" * 88)
    print(f"Candidate occurrences: {result['summary']['candidate_occurrence_count']}")
    print(f"Exact-zone recurrence: {result['summary']['exact_zone_recurrence_count']}")
    print(f"Cross-zone patterns: {result['summary']['cross_zone_pattern_count']}")
    print("Authority: SHADOW ONLY - NO ACTIONS AUTHORIZED")
    print(f"Output: {output}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
