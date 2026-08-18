from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


AUDIT_VERSION = "0.1"
SCHEMA_VERSION = "1.0"
STATUS_SHADOW = "SHADOW_OBSERVATIONAL_ONLY"

BRAKE_ACTIONS = {"reduce_brake", "increase_brake"}
THROTTLE_ACTIONS = {"reduce_throttle", "increase_throttle"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify(actions: list[str]) -> str:
    brake = any(action in BRAKE_ACTIONS for action in actions)
    throttle = any(action in THROTTLE_ACTIONS for action in actions)
    if brake and throttle:
        return "mixed_brake_throttle"
    if brake:
        return "brake_only"
    if throttle:
        return "throttle_only"
    return "no_action"


def build_audit(actions_path: Path) -> dict[str, Any]:
    actions_path = Path(actions_path).resolve()
    payload = json.loads(actions_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Artefacto de acciones inválido.")
    if payload.get("status") != "HISTORICAL_ACTIONS_AUTHORIZED":
        raise ValueError("El artefacto no es de acciones autorizadas.")

    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    context_counts: Counter[str] = Counter()
    mixed: list[str] = []
    for index, action in enumerate(payload.get("actions", [])):
        if not isinstance(action, dict):
            continue
        classification = _classify(action.get("actions", []))
        counts[classification] += 1
        context = action.get("context") or {}
        track = str(context.get("track") or "UNKNOWN")
        context_counts[f"{track}|{classification}"] += 1
        if classification == "mixed_brake_throttle":
            mixed.append(str(action.get("location_label") or f"actions[{index}]"))
        records.append(
            {
                "candidate_id": action.get("candidate_id"),
                "location_label": action.get("location_label"),
                "actions": action.get("actions", []),
                "classification": classification,
            }
        )

    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "audit_version": AUDIT_VERSION,
            "source_actions_json": str(actions_path),
            "source_actions_sha256": sha256_file(actions_path),
            "policy": {
                "shadow_observational_only": True,
                "no_channel_preference_authorized": True,
                "no_ranking_formula_authorized": True,
            },
        },
        "status": STATUS_SHADOW,
        "counts": dict(counts),
        "context_counts": dict(context_counts),
        "mixed_cue_candidates": mixed,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auditoría shadow de actionability de acciones históricas H5.3."
    )
    parser.add_argument("actions_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_audit(Path(args.actions_json))
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 88)
    print(f"RACE ENGINEER - HISTORICAL ACTIONS ACTIONABILITY AUDIT v{AUDIT_VERSION}")
    print("=" * 88)
    print(f"Status: {payload['status']}")
    print(f"Counts: {payload['counts']}")
    print(f"Mixed cue candidates: {payload['mixed_cue_candidates']}")
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
