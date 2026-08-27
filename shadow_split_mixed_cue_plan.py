#!/usr/bin/env python3
"""Shadow split of combined brake+throttle cues (hypothesis, not production).

Los cues combinados ``combined_spatial_sequence`` (canal brake+throttle) son una
decisión determinista de Python en llm_analysis_deepseek.py: combina los cues
espaciales de ambos canales para no expulsar un steering secundario del límite
de dos cues por zona.

Este script NO cambia producción: aplica una hipótesis shadow de split — cada cue
combinado se descompone en un cue por canal a partir de los eventos deterministas
de ``coaching_sequence`` — y mide la estructura resultante con la misma taxonomía
de ``audit_session_plan_actionability`` (canal primario y directness). La salida
es evidencia observacional; no autoriza preferencia de canal ni score de
complejidad.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit_session_plan_actionability import classify_cue


SHADOW_VERSION = "shadow-split-mixed-cues-v0.2"
SHADOW_STATUS = "SHADOW_OBSERVATIONAL_ONLY"
MAX_CUES = 2
PHYSICAL_PATTERN_FIELDS = {
    "brake": ("braking_point_patterns", "brake_release_patterns"),
    "throttle": ("throttle_onset_patterns", "throttle_release_patterns"),
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: la raíz JSON debe ser un objeto")
    return payload


def current_validated_debrief_paths(runs_dir: Path) -> list[Path]:
    """Resolve current debrief outputs from orchestrator state, read-only."""
    paths: set[Path] = set()
    for state_path in runs_dir.glob("*/state.json"):
        try:
            state = load_json(state_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        stages = state.get("stages") or {}
        llm = stages.get("llm") or {}
        validator = stages.get("llm_validator") or {}
        if llm.get("status") not in {"RUN", "REUSED"}:
            continue
        if validator.get("status") not in {"RUN", "REUSED"}:
            continue
        output = llm.get("output")
        if output:
            path = Path(output)
            if path.is_file():
                paths.add(path.resolve())
    return sorted(paths, key=str)


def _events_by_channel(sequence: dict) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for event in sequence.get("events") or []:
        if not isinstance(event, dict):
            continue
        channel = str(event.get("channel") or "").strip()
        text = str(event.get("text") or "").strip()
        if channel and text:
            grouped.setdefault(channel, []).append(text)
    return grouped


def _channel_order(sequence: dict) -> list[str]:
    """Orden de canales según su primera aparición en la secuencia."""
    order: list[str] = []
    for event in sequence.get("events") or []:
        if not isinstance(event, dict):
            continue
        channel = str(event.get("channel") or "").strip()
        if channel and channel not in order:
            order.append(channel)
    return order


def split_combined_cues(cues: list[dict]) -> list[dict]:
    """Descompone cues combinados en un cue por canal (shadow)."""
    split_cues: list[dict] = []
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        if cue.get("kind") == "combined_spatial_sequence":
            sequence = cue.get("coaching_sequence")
            grouped = _events_by_channel(sequence) if isinstance(sequence, dict) else {}
            channel_order = (
                _channel_order(sequence) if isinstance(sequence, dict) else []
            )
            for channel in channel_order or ("brake", "throttle"):
                texts = grouped.get(channel)
                if not texts:
                    continue
                split_cues.append(
                    {
                        "channel": channel,
                        "kind": "spatial_points",
                        "text": " y ".join(texts),
                        "source": "deterministic_coaching_sequence_shadow_split",
                        "point_comparison_count": cue.get("point_comparison_count"),
                        "region_comparison_count": cue.get("region_comparison_count"),
                    }
                )
            continue
        split_cues.append(cue)
    return split_cues[:MAX_CUES]


def _primary_cue(cues: list[dict]) -> dict | None:
    for cue in cues:
        if isinstance(cue, dict):
            return cue
    return None


def _channel_events(sequence: dict, channel: str) -> list[dict]:
    return [
        event
        for event in sequence.get("events") or []
        if isinstance(event, dict) and event.get("channel") == channel
    ]


def _channel_point_support(item: dict, channel: str) -> int:
    """Return the strongest explicit physical-point support for one channel."""
    return max(
        (
            int(pattern.get("comparison_count") or 0)
            for field in PHYSICAL_PATTERN_FIELDS.get(channel, ())
            for pattern in item.get(field) or []
            if isinstance(pattern, dict)
        ),
        default=0,
    )


def _single_channel_cue(cue: dict, channel: str) -> dict | None:
    sequence = cue.get("coaching_sequence")
    if not isinstance(sequence, dict):
        return None
    events = _channel_events(sequence, channel)
    texts = [str(event.get("text") or "").strip() for event in events]
    texts = [text for text in texts if text]
    if not events or not texts:
        return None
    return {
        "channel": channel,
        "kind": "spatial_points",
        "text": " y ".join(texts),
        "source": "deterministic_coaching_sequence_shadow_focus",
        "point_comparison_count": cue.get("point_comparison_count"),
        "region_comparison_count": cue.get("region_comparison_count"),
        "channel_events": events,
    }


def compare_presentations(item: dict) -> dict[str, Any] | None:
    """Compare three read-only presentations of a combined physical sequence."""
    production_cues = [
        cue for cue in item.get("driver_cues") or [] if isinstance(cue, dict)
    ]
    combined = next(
        (
            cue
            for cue in production_cues
            if cue.get("kind") == "combined_spatial_sequence"
        ),
        None,
    )
    if combined is None:
        return None

    sequence = combined.get("coaching_sequence")
    if not isinstance(sequence, dict):
        return None
    channels = _channel_order(sequence)
    supports = {
        channel: _channel_point_support(item, channel)
        for channel in channels
        if channel in PHYSICAL_PATTERN_FIELDS
    }
    strongest_support = max(supports.values(), default=0)
    strongest_channels = [
        channel
        for channel, support in supports.items()
        if support == strongest_support
    ]
    dominant_channel = (
        strongest_channels[0] if len(strongest_channels) == 1 else None
    )
    profile = next(
        (
            cue
            for cue in production_cues
            if cue.get("kind") == "reference_action_profile"
        ),
        None,
    )
    focused = (
        _single_channel_cue(combined, dominant_channel)
        if dominant_channel is not None
        else None
    )
    split = split_combined_cues([combined])

    candidates = {
        "combined_sequence": {
            "available": True,
            "cue_count": min(len(production_cues), MAX_CUES),
            "physical_channels_preserved": channels,
            "inter_channel_order_preserved": True,
            "reference_profile_preserved": profile is not None,
        },
        "supported_channel_plus_profile": {
            "available": focused is not None and profile is not None,
            "cue_count": 2 if focused is not None and profile is not None else 0,
            "selected_channel": dominant_channel,
            "physical_channels_preserved": (
                [dominant_channel] if focused is not None else []
            ),
            "inter_channel_order_preserved": False,
            "reference_profile_preserved": profile is not None,
        },
        "split_channels_with_sequence_context": {
            "available": len(split) >= 2,
            "cue_count": min(len(split), MAX_CUES),
            "physical_channels_preserved": [
                cue.get("channel") for cue in split[:MAX_CUES]
            ],
            "inter_channel_order_preserved": True,
            "reference_profile_preserved": False,
            "full_sequence_attached_as_context": True,
        },
    }

    if candidates["supported_channel_plus_profile"]["available"]:
        preferred = "supported_channel_plus_profile"
        reason = "unique_stronger_physical_support_and_profile_preserved"
    else:
        preferred = "combined_sequence"
        reason = "no_unique_stronger_channel_fail_closed"

    return {
        "channel_point_support": supports,
        "dominant_channel": dominant_channel,
        "preferred_shadow_presentation": preferred,
        "preference_reason": reason,
        "candidates": candidates,
        "production_input_mutated": False,
    }


def compare_item(item: dict) -> dict[str, Any]:
    """Compara estructura producción vs split para una zona del plan."""
    production_cues = [cue for cue in item.get("driver_cues") or [] if isinstance(cue, dict)]
    split_cues = split_combined_cues(production_cues)
    production_primary = _primary_cue(production_cues)
    split_primary = _primary_cue(split_cues)

    production_class = (
        classify_cue(item, production_primary)
        if production_primary is not None
        else None
    )
    split_class = (
        classify_cue(item, split_primary)
        if split_primary is not None
        else None
    )

    return {
        "plan_label": item.get("plan_label"),
        "location": (item.get("track_location") or {}).get("label"),
        "production_cue_count": len(production_cues),
        "split_cue_count": len(split_cues),
        "had_combined_cue": any(
            cue.get("kind") == "combined_spatial_sequence" for cue in production_cues
        ),
        "production_primary_channel": (
            production_class["channel"] if production_class else None
        ),
        "production_primary_directness": (
            production_class["directness_class"] if production_class else None
        ),
        "split_primary_channel": split_class["channel"] if split_class else None,
        "split_primary_directness": split_class["directness_class"] if split_class else None,
        "presentation_comparison": compare_presentations(item),
    }


def audit_document(document: dict) -> dict[str, Any]:
    facts = document.get("session_coaching_facts")
    if not isinstance(facts, dict):
        raise ValueError("session_coaching_facts ausente")
    plan = facts.get("next_stint_plan")
    if not isinstance(plan, list):
        raise ValueError("next_stint_plan ausente o inválido")
    return {
        "zone_count": len(plan),
        "zones": [compare_item(item) for item in plan if isinstance(item, dict)],
    }


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    production_channels: Counter[str] = Counter()
    split_channels: Counter[str] = Counter()
    production_directness: Counter[str] = Counter()
    split_directness: Counter[str] = Counter()
    combined_count = 0
    zone_count = 0
    preferred_presentations: Counter[str] = Counter()
    preference_reasons: Counter[str] = Counter()
    dominant_channels: Counter[str] = Counter()
    profile_displacement_count = 0

    for result in results:
        for zone in result["zones"]:
            zone_count += 1
            if zone["had_combined_cue"]:
                combined_count += 1
            presentation = zone.get("presentation_comparison")
            if isinstance(presentation, dict):
                preferred_presentations[
                    str(presentation["preferred_shadow_presentation"])
                ] += 1
                preference_reasons[str(presentation["preference_reason"])] += 1
                dominant_channels[
                    str(presentation["dominant_channel"] or "none")
                ] += 1
                split_candidate = presentation["candidates"][
                    "split_channels_with_sequence_context"
                ]
                combined_candidate = presentation["candidates"]["combined_sequence"]
                if (
                    combined_candidate["reference_profile_preserved"]
                    and not split_candidate["reference_profile_preserved"]
                ):
                    profile_displacement_count += 1
            production_channels[str(zone["production_primary_channel"] or "none")] += 1
            split_channels[str(zone["split_primary_channel"] or "none")] += 1
            production_directness[str(zone["production_primary_directness"] or "none")] += 1
            split_directness[str(zone["split_primary_directness"] or "none")] += 1

    return {
        "artifact_count": len(results),
        "zone_count": zone_count,
        "combined_cue_zones": combined_count,
        "production_primary_channel_counts": dict(sorted(production_channels.items())),
        "split_primary_channel_counts": dict(sorted(split_channels.items())),
        "production_primary_directness_counts": dict(
            sorted(production_directness.items())
        ),
        "split_primary_directness_counts": dict(sorted(split_directness.items())),
        "preferred_shadow_presentation_counts": dict(
            sorted(preferred_presentations.items())
        ),
        "preference_reason_counts": dict(sorted(preference_reasons.items())),
        "dominant_channel_counts": dict(sorted(dominant_channels.items())),
        "split_profile_displacement_count": profile_displacement_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hipótesis shadow: split de cues combinados brake+throttle."
    )
    parser.add_argument("debrief_json", nargs="*", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--current-runs",
        action="store_true",
        help="Audita los outputs vigentes referenciados por state.json",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("data/generated/runs"),
    )
    args = parser.parse_args()

    try:
        paths = list(args.debrief_json)
        if args.current_runs:
            paths.extend(current_validated_debrief_paths(args.runs_dir))
        paths = sorted(set(paths), key=str)
        if not paths:
            raise ValueError("no se proporcionaron debriefs para auditar")
        results = []
        for path in paths:
            document = load_json(path)
            audit = audit_document(document)
            audit["source_path"] = str(path.resolve())
            results.append(audit)
        summary = build_summary(results)
        output = {
            "metadata": {
                "shadow_version": SHADOW_VERSION,
                "status": SHADOW_STATUS,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "policy": {
                    "production_changed": False,
                    "channel_preference_authorized": False,
                    "complexity_score_authorized": False,
                    "presentation_preference_authorized": False,
                    "historical_actions_authorized": False,
                },
            },
            "summary": summary,
            "artifacts": results,
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RESULT: FAIL — {exc}")
        return 2

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Output: {args.output.resolve()}")

    print("=" * 88)
    print(f"RACE ENGINEER - SHADOW SPLIT MIXED CUES {SHADOW_VERSION}")
    print("=" * 88)
    print(f"Artifacts: {summary['artifact_count']}  Zones: {summary['zone_count']}")
    print(f"Combined-cue zones: {summary['combined_cue_zones']}")
    print("Production primary channels:", summary["production_primary_channel_counts"])
    print("Split primary channels:     ", summary["split_primary_channel_counts"])
    print("Production directness:", summary["production_primary_directness_counts"])
    print("Split directness:     ", summary["split_primary_directness_counts"])
    print("Shadow presentation:   ", summary["preferred_shadow_presentation_counts"])
    print("Dominant channels:     ", summary["dominant_channel_counts"])
    print("Split profile displacement:", summary["split_profile_displacement_count"])
    print("Authority: SHADOW ONLY — no channel preference or priority changed")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
