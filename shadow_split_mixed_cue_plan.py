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


SHADOW_VERSION = "shadow-split-mixed-cues-v0.1"
SHADOW_STATUS = "SHADOW_OBSERVATIONAL_ONLY"
MAX_CUES = 2


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: la raíz JSON debe ser un objeto")
    return payload


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

    for result in results:
        for zone in result["zones"]:
            zone_count += 1
            if zone["had_combined_cue"]:
                combined_count += 1
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
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hipótesis shadow: split de cues combinados brake+throttle."
    )
    parser.add_argument("debrief_json", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        results = []
        for path in args.debrief_json:
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
    print("Authority: SHADOW ONLY — no channel preference or priority changed")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
