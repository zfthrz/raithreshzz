from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ACTION_POLICY_VERSION = "0.1"
SCHEMA_VERSION = "1.0"
STATUS_AUTHORIZED = "HISTORICAL_ACTIONS_AUTHORIZED"

OBSERVATION_TO_ACTION = {
    "current_throttle_higher": "reduce_throttle",
    "current_throttle_lower": "increase_throttle",
    "current_brake_higher": "reduce_brake",
    "current_brake_lower": "increase_brake",
}
ACTION_TEXT = {
    "reduce_throttle": "reducir acelerador",
    "increase_throttle": "aumentar acelerador",
    "reduce_brake": "reducir freno",
    "increase_brake": "aumentar freno",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _actions_for_observations(observation_codes: list[str]) -> list[str]:
    actions: list[str] = []
    for code in observation_codes:
        action = OBSERVATION_TO_ACTION.get(code)
        if action is not None and action not in actions:
            actions.append(action)
    return actions


def build_action_candidates(selection_path: Path) -> dict[str, Any]:
    selection_path = Path(selection_path).resolve()
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if not isinstance(selection, dict):
        raise ValueError("Selección H5.3c inválida: la raíz debe ser un objeto.")
    if selection.get("status") != "VALIDATED_HISTORICAL_CANDIDATE_SELECTION":
        raise ValueError("Selección H5.3c no validada.")

    authorized_by_id = {
        candidate["candidate_id"]: candidate
        for candidate in selection.get("authorized_candidates", [])
        if isinstance(candidate, dict)
    }
    selected = selection.get("llm_selection", {}).get("selected_candidates", [])
    if not isinstance(selected, list):
        raise ValueError("llm_selection.selected_candidates inválido.")

    actions: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        candidate_id = item.get("candidate_id")
        candidate = authorized_by_id.get(candidate_id)
        if candidate is None:
            raise ValueError(f"candidato seleccionado no autorizado: {candidate_id}")
        delta_sign = candidate.get("delta_sign")
        if delta_sign != "current_slower":
            withheld.append(
                {
                    "candidate_id": candidate_id,
                    "location_label": candidate.get("location_label"),
                    "delta_sign": delta_sign,
                    "reason": "current_lap_faster_no_actions",
                }
            )
            continue
        observation_codes = item.get("observation_codes", [])
        mapped = _actions_for_observations(observation_codes)
        context = candidate.get("context") or {}
        actions.append(
            {
                "candidate_id": candidate_id,
                "context": {
                    "track": context.get("track"),
                    "track_layout": context.get("track_layout"),
                    "vehicle_variant": context.get("vehicle_variant"),
                    "car_name_raw": context.get("car_name_raw"),
                },
                "location_label": candidate.get("location_label"),
                "delta_sign": delta_sign,
                "delta_change_s": candidate.get("delta_change_s"),
                "actions": mapped,
                "actions_text": [ACTION_TEXT[action] for action in mapped],
                "authorization": {
                    "authorized": True,
                    "policy_version": ACTION_POLICY_VERSION,
                    "observation_codes": observation_codes,
                    "anti_regression_guard": "current_slower_only",
                },
            }
        )

    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "action_policy_version": ACTION_POLICY_VERSION,
            "source_selection_json": str(selection_path),
            "source_selection_sha256": sha256_file(selection_path),
            "policy": {
                "closed_action_vocabulary": sorted(ACTION_TEXT),
                "speed_is_context_not_target": True,
                "time_codes_are_not_actions": True,
                "session_reference_remains_authority": True,
            },
        },
        "status": STATUS_AUTHORIZED,
        "actions": actions,
        "withheld": withheld,
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": True,
            "scope": "authorized_action_candidates_only",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3 Nivel 2: política determinista de acciones históricas autorizadas."
    )
    parser.add_argument("selection_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_action_candidates(Path(args.selection_json))
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 88)
    print(f"RACE ENGINEER - H5.3 ACTION POLICY v{ACTION_POLICY_VERSION}")
    print("=" * 88)
    print(f"Status: {payload['status']}")
    print(f"Acciones autorizadas: {len(payload['actions'])}")
    print(f"Retenidas (anti-regresión): {len(payload['withheld'])}")
    for item in payload["actions"]:
        print(
            f"- {item['location_label']}: {', '.join(item['actions_text'])}"
        )
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
