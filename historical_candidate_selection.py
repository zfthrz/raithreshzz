from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_h5_3_audit_labels import validate as validate_audit_labels


CANDIDATE_SELECTION_VERSION = "0.1"
SCHEMA_VERSION = "1.0"
MAX_VALIDATION_ATTEMPTS = 3
MAX_SELECTED_CANDIDATES = 3
ALLOWED_SIGNIFICANCE = {"primary", "secondary", "context"}
ALLOWED_LIMITATIONS = {
    "single_lap_pair",
    "zone_averages_only",
    "no_causal_inference",
    "no_historical_coaching_authority",
    "shadow_observational_only",
    "physical_points_not_attached",
}
REQUIRED_LIMITATIONS = (
    "no_historical_coaching_authority",
    "shadow_observational_only",
    "physical_points_not_attached",
)

OBSERVATION_TEXT = {
    "time_loss": "la vuelta actual pierde tiempo dentro del candidato",
    "time_gain": "la vuelta actual recupera tiempo dentro del candidato",
    "current_speed_lower": "la velocidad media actual es menor",
    "current_speed_higher": "la velocidad media actual es mayor",
    "current_throttle_lower": "el acelerador medio actual es menor",
    "current_throttle_higher": "el acelerador medio actual es mayor",
    "current_brake_lower": "el freno medio actual es menor",
    "current_brake_higher": "el freno medio actual es mayor",
}
LIMITATION_TEXT = {
    "single_lap_pair": "La comparación cubre una sola vuelta actual y una sola histórica.",
    "zone_averages_only": "Las observaciones de canales describen promedios de cada zona.",
    "no_causal_inference": "Las coincidencias observadas no demuestran relaciones causales.",
    "no_historical_coaching_authority": "La vuelta histórica no tiene autoridad de coaching.",
    "shadow_observational_only": "Los candidatos son evidencia shadow, sin acciones.",
    "physical_points_not_attached": (
        "Los puntos físicos onset/release y perfiles de acción no están adjuntos."
    ),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_validated_sources(
    dataset_path: Path,
    labels_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    errors, _, _ = validate_audit_labels(dataset_path, labels_path)
    if errors:
        raise ValueError("Auditoría H5.3b inválida: " + "; ".join(errors))
    return dataset, labels


def _signed_observation(value: Any, lower: str, higher: str) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return lower
    if number > 0:
        return higher
    return None


def build_authorized_evidence(
    dataset: dict[str, Any],
    labels: dict[str, Any],
) -> dict[str, Any]:
    label_by_audit_id = {
        item["audit_id"]: item
        for item in labels.get("labels", [])
        if isinstance(item, dict)
    }
    candidates: list[dict[str, Any]] = []
    for candidate in dataset.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        record = label_by_audit_id.get(candidate["audit_id"])
        if record is None or record.get("human_label") != "ACTIONABLE":
            continue
        channel = candidate.get("observational_channel_evidence") or {}
        delta_change = candidate["evidence"]["delta_change_s"]
        observations = ["time_loss" if delta_change > 0 else "time_gain"]
        signed = (
            (channel.get("speed_delta_avg"), "current_speed_lower", "current_speed_higher"),
            (
                channel.get("throttle_delta_avg"),
                "current_throttle_lower",
                "current_throttle_higher",
            ),
            (
                channel.get("brake_delta_avg"),
                "current_brake_lower",
                "current_brake_higher",
            ),
        )
        for value, lower, higher in signed:
            observation = _signed_observation(value, lower, higher)
            if observation:
                observations.append(observation)
        context = candidate.get("context") or {}
        candidates.append(
            {
                "candidate_id": candidate["audit_id"],
                "source_candidate_id": candidate.get("candidate_id"),
                "context": {
                    "track": context.get("track"),
                    "track_layout": context.get("track_layout"),
                    "vehicle_variant": context.get("vehicle_variant"),
                    "car_name_raw": context.get("car_name_raw"),
                },
                "delta_sign": candidate.get("delta_sign"),
                "location_label": candidate.get("location_label"),
                "start_distance_m": candidate["evidence"]["start_distance_m"],
                "end_distance_m": candidate["evidence"]["end_distance_m"],
                "delta_change_s": delta_change,
                "speed_delta_avg": channel.get("speed_delta_avg"),
                "throttle_delta_avg": channel.get("throttle_delta_avg"),
                "brake_delta_avg": channel.get("brake_delta_avg"),
                "authorized_observations": observations,
            }
        )

    return {
        "contract": {
            "candidates_are_shadow": True,
            "historical_actions_authorized": False,
            "causal_claims_authorized": False,
            "free_text_authorized": False,
        },
        "authorized_candidate_count": len(candidates),
        "authorized_limitation_codes": sorted(ALLOWED_LIMITATIONS),
        "required_limitation_codes": list(REQUIRED_LIMITATIONS),
        "candidates": candidates,
    }


def response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["selected_candidates", "limitation_codes"],
        "properties": {
            "selected_candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_SELECTED_CANDIDATES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["candidate_id", "significance", "observation_codes"],
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "significance": {
                            "type": "string",
                            "enum": sorted(ALLOWED_SIGNIFICANCE),
                        },
                        "observation_codes": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "limitation_codes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {"type": "string"},
            },
        },
    }


def system_prompt() -> str:
    return """Sos un selector de candidatos históricos en modo shadow.

Python ya calculó, auditó y autorizó los candidatos y códigos. Seleccioná hasta tres
candidatos relevantes, ordenalos por importancia y usá solamente candidate_id y
observation_codes que ya figuren como autorizados.

Reglas obligatorias:
- Cada candidato tiene una lista `authorized_observations` (array de strings).
- Tus `observation_codes` para ese candidate_id DEBEN ser un SUBCONJUNTO estricto de
  `authorized_observations` de ese MISMO candidato.
- NO copies observation_codes de un candidato a otro.
- NO inventes códigos. NO uses aliases ni traducciones.
- Cada observation_code debe existir tal cual aparece en `authorized_observations` del
  candidato específico que estás seleccionando.
- Elegí limitation_codes únicamente desde la lista autorizada.
- No escribas texto libre, cifras, recomendaciones, causas ni claves adicionales.
- La selección no convierte la vuelta histórica en autoridad de coaching.

Respondé únicamente con JSON válido."""


def user_prompt(evidence: dict[str, Any], correction: list[str] | None = None) -> str:
    correction_block = ""
    if correction:
        correction_block = (
            "\nLa respuesta anterior fue rechazada por estas razones:\n- "
            + "\n- ".join(correction)
            + "\nCorregí solamente esos incumplimientos.\n"
        )
    # Build a compact candidate->authorized_observations mapping for the LLM.
    candidate_obs_block = ""
    for candidate in evidence.get("candidates", []):
        cid = candidate.get("candidate_id", "UNKNOWN")
        obs = candidate.get("authorized_observations", [])
        candidate_obs_block += (
            f"  candidate_id: {cid} | authorized_observations: {json.dumps(obs, ensure_ascii=False)}\n"
        )
    return (
        "EVIDENCIA AUTORIZADA H5.3:\n"
        + json.dumps(evidence, ensure_ascii=False, indent=2)
        + "\n\nPOR CADA CANDIDATO, ESTAS SON SUS OBSERVATIONS AUTORIZADAS:\n"
        + candidate_obs_block
        + "\nSCHEMA DE RESPUESTA:\n"
        + json.dumps(response_schema(), ensure_ascii=False, indent=2)
        + correction_block
        + "\nRespondé únicamente con el objeto JSON solicitado."
    )


def parse_response(raw_content: str) -> dict[str, Any]:
    if not isinstance(raw_content, str):
        raise ValueError("La respuesta del LLM no es texto")
    text = raw_content.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("La raíz de la respuesta LLM no es un objeto")
    return parsed


def validate_response(
    response: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if set(response) != {"selected_candidates", "limitation_codes"}:
        errors.append("claves raíz fuera de contrato")

    candidates_by_id = {
        candidate["candidate_id"]: candidate
        for candidate in evidence.get("candidates", [])
    }
    selected = response.get("selected_candidates")
    if not isinstance(selected, list):
        errors.append("selected_candidates debe ser una lista")
    elif not 1 <= len(selected) <= min(MAX_SELECTED_CANDIDATES, len(candidates_by_id)):
        errors.append(
            "selected_candidates debe contener entre uno y tres candidatos existentes"
        )
    else:
        seen: set[str] = set()
        for index, item in enumerate(selected):
            field = f"selected_candidates[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{field} debe ser objeto")
                continue
            if set(item) != {"candidate_id", "significance", "observation_codes"}:
                errors.append(f"{field} contiene claves fuera de contrato")
            candidate_id = item.get("candidate_id")
            candidate = candidates_by_id.get(candidate_id)
            if candidate is None:
                errors.append(f"{field}.candidate_id no existe en la evidencia")
            elif candidate_id in seen:
                errors.append(f"{field}.candidate_id duplicado")
            else:
                seen.add(candidate_id)
            if item.get("significance") not in ALLOWED_SIGNIFICANCE:
                errors.append(f"{field}.significance inválida")
            codes = item.get("observation_codes")
            if not isinstance(codes, list) or not 1 <= len(codes) <= 4:
                errors.append(f"{field}.observation_codes inválidos")
            elif len(codes) != len(set(codes)):
                errors.append(f"{field}.observation_codes duplicados")
            elif candidate is not None and not set(codes).issubset(
                set(candidate["authorized_observations"])
            ):
                errors.append(
                    f"{field}.observation_codes no autorizados: "
                    f"{codes} no es subconjunto de "
                    f"{candidate['authorized_observations']} "
                    f"para candidate_id {candidate_id}"
                )

    limitations = response.get("limitation_codes")
    if not isinstance(limitations, list) or not 1 <= len(limitations) <= 4:
        errors.append("limitation_codes debe contener entre uno y cuatro códigos")
    elif len(limitations) != len(set(limitations)):
        errors.append("limitation_codes contiene duplicados")
    elif not set(limitations).issubset(ALLOWED_LIMITATIONS):
        errors.append("limitation_codes contiene códigos no autorizados")
    elif not set(evidence.get("required_limitation_codes", [])).issubset(
        set(limitations)
    ):
        errors.append("limitation_codes omite una limitación requerida por Python")
    return errors


def selected_evidence(
    response: dict[str, Any],
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id = {candidate["candidate_id"]: candidate for candidate in evidence["candidates"]}
    return [
        dict(by_id[item["candidate_id"]])
        for item in response["selected_candidates"]
    ]


def render_analysis(
    response: dict[str, Any],
    evidence: dict[str, Any],
) -> str:
    lines = [
        "Selección histórica observacional (shadow)",
        f"Candidatos autorizados: {evidence['authorized_candidate_count']}",
    ]
    by_id = {candidate["candidate_id"]: candidate for candidate in evidence["candidates"]}
    for item in response["selected_candidates"]:
        candidate = by_id[item["candidate_id"]]
        label = candidate.get("location_label") or item["candidate_id"]
        observations = "; ".join(
            OBSERVATION_TEXT[code] for code in item["observation_codes"]
        )
        lines.append(
            f"{label} [{item['candidate_id']}] "
            f"({candidate['delta_sign']}, cambio {candidate['delta_change_s']:+.3f} s): "
            f"{observations}."
        )
    limitations = " ".join(
        LIMITATION_TEXT[code] for code in response["limitation_codes"]
    )
    lines.append("Limitaciones: " + limitations)
    lines.append(
        "La selección no autoriza acciones ni reemplaza la referencia de la sesión."
    )
    return "\n".join(lines)


def build_output(
    dataset_path: Path,
    labels_path: Path,
    dataset: dict[str, Any],
    labels: dict[str, Any],
    evidence: dict[str, Any],
    response: dict[str, Any],
    *,
    backend: str,
    model: str,
) -> dict[str, Any]:
    errors = validate_response(response, evidence)
    if errors:
        raise ValueError("Respuesta de candidatos inválida: " + "; ".join(errors))
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "candidate_selection_version": CANDIDATE_SELECTION_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_dataset_json": str(dataset_path.resolve()),
            "source_dataset_sha256": sha256_file(dataset_path),
            "source_labels_json": str(labels_path.resolve()),
            "source_labels_sha256": sha256_file(labels_path),
            "backend": backend,
            "model": model,
        },
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": evidence["candidates"],
        "llm_selection": response,
        "selected_evidence": selected_evidence(response, evidence),
        "rendered_analysis": render_analysis(response, evidence),
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_reference_is_observational": True,
            "historical_actions_authorized": False,
            "causal_claims_authorized": False,
            "candidate_selection_is_shadow": True,
        },
    }


def call_backend(backend: str, system: str, user: str) -> tuple[str, str]:
    if backend == "llamacpp":
        import llm_analysis_llamacpp as implementation

        raw = implementation.llamacpp_chat(
            system,
            user,
            temperature=0.0,
            format_schema=response_schema(),
        )
        return raw, str(implementation.MODEL_NAME)
    if backend == "ollama":
        import llm_analysis as implementation

        raw = implementation.ollama_chat(
            system,
            user,
            temperature=0.0,
            format_schema=response_schema(),
            num_predict=500,
        )
        return raw, str(implementation.MODEL_NAME)
    if backend == "deepseek":
        import llm_analysis_deepseek as implementation

        raw = implementation.deepseek_chat(
            system,
            user,
            temperature=0.0,
            format_schema=response_schema(),
        )
        return raw, str(implementation.MODEL_NAME)
    raise ValueError(f"Backend no soportado: {backend}")


def generate_response(
    evidence: dict[str, Any],
    *,
    backend: str,
    debug_dir: Path,
) -> tuple[dict[str, Any], str]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] | None = None
    model = "unknown"
    for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
        prompt = user_prompt(evidence, errors)
        (debug_dir / f"attempt_{attempt:02d}_prompt.txt").write_text(
            prompt + "\n",
            encoding="utf-8",
        )
        raw, model = call_backend(backend, system_prompt(), prompt)
        (debug_dir / f"attempt_{attempt:02d}_raw.txt").write_text(
            raw + "\n",
            encoding="utf-8",
        )
        try:
            response = parse_response(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            errors = [str(exc)]
            continue
        errors = validate_response(response, evidence)
        if not errors:
            return response, model
    raise RuntimeError(
        "El LLM no produjo una selección de candidatos válida: "
        + "; ".join(errors or [])
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Selección LLM controlada de candidatos históricos H5.3c"
    )
    parser.add_argument("dataset_json")
    parser.add_argument("labels_json")
    parser.add_argument("--backend", choices=("deepseek", "ollama"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--debug-dir", required=True)
    args = parser.parse_args()

    dataset_path = Path(args.dataset_json).resolve()
    labels_path = Path(args.labels_json).resolve()
    dataset, labels = load_validated_sources(dataset_path, labels_path)
    evidence = build_authorized_evidence(dataset, labels)
    response, model = generate_response(
        evidence,
        backend=args.backend,
        debug_dir=Path(args.debug_dir).resolve(),
    )
    output = build_output(
        dataset_path,
        labels_path,
        dataset,
        labels,
        evidence,
        response,
        backend=args.backend,
        model=model,
    )
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("=" * 88)
    print(
        "RACE ENGINEER - H5.3c HISTORICAL CANDIDATE SELECTION "
        f"v{CANDIDATE_SELECTION_VERSION}"
    )
    print("=" * 88)
    print(f"Backend/model: {args.backend} / {model}")
    print(f"Authorized candidates: {evidence['authorized_candidate_count']}")
    print(f"Selected candidates: {len(response['selected_candidates'])}")
    print("Free text from LLM: DISABLED")
    print("Historical coaching: DISABLED")
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
