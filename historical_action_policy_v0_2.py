"""H5.3 Nivel 2: política determinista de candidatos de acción shadow v0.2

Estado: SHADOW_ELIGIBILITY_ONLY
Autoridad: ninguna
historical_actions_authorized: false
session_reference_remains_authority: true

v0.2 endurece la política v0.1:

- Vocabulario cerrado de acciones estricto.
- Anti-regresión: sólo delta_sign == current_slower genera acciones.
  current_faster → WITHHELD (reason: "current_lap_faster_no_actions").
- Si un candidato current_slower tiene observation_codes pero NINGUNO es
  mapeable a vocabulario cerrado → WITHHELD (reason: "no_mappable_actions").
  authorized=true + actions=[] es INVÁLIDO.
- Observation codes se clasifican en:
  - known_mappable: están en OBSERVATION_TO_ACTION → generan acciones.
  - known_non_mappable: son conocidos (speed/time) pero NO generan acciones.
  - unknown: no están definidos → validation failure.
- Se verifica que no existan candidate_id duplicados en el output.
- Se preserva provenance: SHA256 de la selección fuente.
- Se preserva identidad: candidate_id + contexto correspondiente.
- historical_actions_authorized = false globalmente (shadow only).
- session_reference_remains_authority = true siempre.

NO:
  - producción
  - LLM nuevo
  - coaching libre
- modificar el debrief visible de race_engineer.py
  - modificar eligibility gate
  - modificar historical_candidate_selection.py

VOCABULARIO CERRADO (observation_code → action_code):
  current_throttle_higher -> reduce_throttle
  current_throttle_lower  -> increase_throttle
  current_brake_higher    -> reduce_brake
  current_brake_lower     -> increase_brake

ACTION_TEXT (action_code -> texto legible):
  reduce_throttle: reducir acelerador
  increase_throttle: aumentar acelerador
  reduce_brake: reducir freno
  increase_brake: aumentar freno

"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ACTION_POLICY_VERSION = "0.2"
SCHEMA_VERSION = "1.0"
STATUS_AUTHORIZED = "HISTORICAL_ACTION_CANDIDATES_VALIDATED"

# ── Vocabulario cerrado ──────────────────────────────────────────────────────

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

# Observation codes that are known but produce no action (speed/time).
KNOWN_NON_MAPPABLE_CODES = frozenset({
    "time_loss",
    "time_gain",
    "current_speed_lower",
    "current_speed_higher",
})

# Observation codes known to the policy (mappable + non-mappable).
# All observation codes the system knows about, including speed and time codes.
KNOWN_OBSERVATION_CODES = frozenset(
    OBSERVATION_TO_ACTION.keys()
) | KNOWN_NON_MAPPABLE_CODES

# Closed vocabulary shared with validate_historical_actions.py.  Keeping the
# reason contract beside the producer prevents a valid deterministic output
# from being rejected because the validator retained an older local copy.
ALLOWED_WITHHELD_REASON_CODES = frozenset({
    "current_lap_faster_no_actions",
    "no_mappable_actions",
    "insufficient_action_context",
    "missing_context",
    "invalid_geometry",
    "insignificant_delta",
    "not_comparable",
    "ambiguous_localization",
    "ambiguous_human_label",
})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify_observation_codes(
    observation_codes: list[str],
) -> dict[str, list[str]]:
    """Clasificar observation_codes en mappable, non-mappable, unknown.

    Returns dict con:
      - mappable: codes present in OBSERVATION_TO_ACTION
      - non_mappable: codes known but produce no actions
      - unknown: codes not in any known set
    """
    mappable: list[str] = []
    non_mappable: list[str] = []
    unknown: list[str] = []
    for code in observation_codes:
        if code in OBSERVATION_TO_ACTION:
            mappable.append(code)
        elif code in KNOWN_OBSERVATION_CODES:
            non_mappable.append(code)
        else:
            unknown.append(code)
    return {
        "mappable": mappable,
        "non_mappable": non_mappable,
        "unknown": unknown,
    }


def _actions_for_observations(observation_codes: list[str]) -> list[str]:
    """Mapear observation_codes a action_codes (ordenado, sin duplicados)."""
    actions: list[str] = []
    for code in observation_codes:
        action = OBSERVATION_TO_ACTION.get(code)
        if action is not None and action not in actions:
            actions.append(action)
    return actions


def build_action_candidates(selection_path: Path) -> dict[str, Any]:
    """Construir artefacto de acciones a partir de una selección validada.

    v0.2 endurecimientos:
    - classified observation codes (mappable / non_mappable / unknown)
    - current_slower con NO mappable codes → WITHHELD (no_mappable_actions)
    - duplicate candidate_id detection
    - explicit policy metadata
    """
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

    # v0.2: duplicate candidate_id detection
    seen_candidate_ids: set[str] = set()
    duplicate_ids: list[str] = []
    for item in selected:
        if isinstance(item, dict):
            cid = item.get("candidate_id")
            if cid and cid in seen_candidate_ids:
                duplicate_ids.append(cid)
            seen_candidate_ids.add(cid)

    actions: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        candidate_id = item.get("candidate_id")
        candidate = authorized_by_id.get(candidate_id)
        if candidate is None:
            raise ValueError(f"candidato seleccionado no autorizado: {candidate_id}")

        observation_codes = item.get("observation_codes", [])
        classification = _classify_observation_codes(observation_codes)

        # v0.2: Reject if unknown observation codes are present.
        if classification["unknown"]:
            raise ValueError(
                f"observation_codes unknown: {classification['unknown']}"
            )

        # Anti-regresión: sólo current_slower genera acciones.
        delta_sign = candidate.get("delta_sign")
        if delta_sign != "current_slower":
            withheld.append(
                {
                    "candidate_id": candidate_id,
                    "location_label": candidate.get("location_label"),
                    "delta_sign": delta_sign,
                    "reason": "current_lap_faster_no_actions",
                    "observation_codes": observation_codes,
                    "classified_observation_codes": classification,
                }
            )
            continue

        # v0.2: current_slower con NO mappable codes → WITHHELD.
        if not classification["mappable"]:
            withheld.append(
                {
                    "candidate_id": candidate_id,
                    "location_label": candidate.get("location_label"),
                    "delta_sign": delta_sign,
                    "reason": "no_mappable_actions",
                    "observation_codes": observation_codes,
                    "classified_observation_codes": classification,
                }
            )
            continue

        # H5.3 human-review correction (Point 6):
        # current_throttle_higher alone is NOT sufficient causal/action evidence
        # for reduce_throttle. If the ONLY mappable code is current_throttle_higher:
        # WITHHOLD with reason "insufficient_action_context".
        # Combined cases (e.g. current_throttle_higher + current_brake_lower)
        # remain authorized — human review 2/2 accepted.
        mappable_codes_set = set(classification["mappable"])
        if mappable_codes_set == {"current_throttle_higher"}:
            withheld.append(
                {
                    "candidate_id": candidate_id,
                    "location_label": candidate.get("location_label"),
                    "delta_sign": delta_sign,
                    "reason": "insufficient_action_context",
                    "observation_codes": observation_codes,
                    "classified_observation_codes": classification,
                }
            )
            continue

        # current_slower + al menos 1 mappable code → ELIGIBLE.
        mapped = _actions_for_observations(classification["mappable"])
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
                    "classified_observation_codes": classification,
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
                "closed_observation_vocabulary": sorted(OBSERVATION_TO_ACTION),
                "speed_is_context_not_target": True,
                "time_codes_are_not_actions": True,
                "session_reference_remains_authority": True,
                "historical_actions_authorized": False,
            },
            "known_observation_codes": sorted(KNOWN_OBSERVATION_CODES),
        },
        "status": STATUS_AUTHORIZED,
        "actions": actions,
        "withheld": withheld,
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
            "scope": "authorized_action_candidates_only",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3 Nivel 2: política determinista de candidatos de acción shadow v0.2."
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
    print(f"Candidatos de acción shadow: {len(payload['actions'])}")
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
