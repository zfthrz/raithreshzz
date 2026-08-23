from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_cross_session_comparison import validate as validate_cross_session


HISTORICAL_LLM_VERSION = "0.1"
SCHEMA_VERSION = "1.0"
MAX_VALIDATION_ATTEMPTS = 3
BACKEND_CHOICES = ("deepseek", "ollama", "llamacpp")
ALLOWED_SIGNIFICANCE = {"primary", "secondary", "context"}
ALLOWED_LIMITATIONS = {
    "single_lap_pair",
    "zone_averages_only",
    "external_conditions_not_observed",
    "no_causal_inference",
    "no_historical_coaching_authority",
    "track_profile_localization_unavailable",
}

OBSERVATION_TEXT = {
    "time_loss": "la vuelta actual pierde tiempo dentro de la zona",
    "time_gain": "la vuelta actual recupera tiempo dentro de la zona",
    "current_speed_lower": "la velocidad media actual es menor",
    "current_speed_higher": "la velocidad media actual es mayor",
    "current_throttle_lower": "el acelerador medio actual es menor",
    "current_throttle_higher": "el acelerador medio actual es mayor",
    "current_brake_lower": "el freno medio actual es menor",
    "current_brake_higher": "el freno medio actual es mayor",
}
OVERVIEW_TEXT = {
    "current_lap_slower": "La vuelta actual es más lenta que la histórica.",
    "current_lap_faster": "La vuelta actual es más rápida que la histórica.",
    "current_lap_equal": "Ambas vueltas tienen la misma duración dentro de la tolerancia.",
}
LIMITATION_TEXT = {
    "single_lap_pair": "La comparación cubre una sola vuelta actual y una sola histórica.",
    "zone_averages_only": "Las observaciones de canales describen promedios de cada zona.",
    "external_conditions_not_observed": "Las condiciones externas no forman parte de esta evidencia.",
    "no_causal_inference": "Las coincidencias observadas no demuestran relaciones causales.",
    "no_historical_coaching_authority": "La vuelta histórica no tiene autoridad de coaching.",
    "track_profile_localization_unavailable": (
        "No existe un track profile validado exacto; las zonas conservan "
        "el alcance amplio de la tendencia de delta."
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


def load_validated_source(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_cross_session(document)
    if errors:
        raise ValueError("H5.2 source inválido: " + "; ".join(errors))
    return document


def _signed_observation(value: float, lower: str, higher: str) -> str | None:
    if value < 0:
        return lower
    if value > 0:
        return higher
    return None


def build_authorized_evidence(source: dict[str, Any]) -> dict[str, Any]:
    lap_delta = source["temporal_validation"][
        "calculated_current_minus_historical_s"
    ]
    if lap_delta > 0:
        overview = "current_lap_slower"
    elif lap_delta < 0:
        overview = "current_lap_faster"
    else:
        overview = "current_lap_equal"

    authorized_zones = []
    for index, zone in enumerate(
        source["spatial_comparison"]["zone_summaries"], start=1
    ):
        observations = ["time_loss" if zone["type"] == "loss" else "time_gain"]
        signed = (
            (zone["speed_delta_avg"], "current_speed_lower", "current_speed_higher"),
            (
                zone["throttle_delta_avg"],
                "current_throttle_lower",
                "current_throttle_higher",
            ),
            (zone["brake_delta_avg"], "current_brake_lower", "current_brake_higher"),
        )
        for value, lower, higher in signed:
            observation = _signed_observation(float(value), lower, higher)
            if observation:
                observations.append(observation)
        authorized_zones.append(
            {
                "zone_id": f"zone_{index:03d}",
                "source_trend_zone_id": zone["source_trend_zone_id"],
                "scope": zone["scope"],
                "location_label": (
                    (zone.get("location") or {}).get("label")
                ),
                "type": zone["type"],
                "start_distance_m": zone["start_distance"],
                "end_distance_m": zone["end_distance"],
                "delta_change_s": zone["delta_change"],
                "speed_delta_avg_kmh": zone["speed_delta_avg"],
                "throttle_delta_avg_pct": zone["throttle_delta_avg"],
                "brake_delta_avg_pct": zone["brake_delta_avg"],
                "authorized_observations": observations,
            }
        )

    required_limitations = []
    if source["spatial_comparison"]["localization"]["mode"] == "unavailable":
        required_limitations.append("track_profile_localization_unavailable")

    return {
        "contract": {
            "delta_sign": "current_minus_historical",
            "historical_actions_authorized": False,
            "causal_claims_authorized": False,
            "free_text_authorized": False,
        },
        "context": source["context"],
        "localization": source["spatial_comparison"]["localization"],
        "lap_comparison": {
            "historical_session_id": source["historical_reference"]["session_id"],
            "historical_lap": source["historical_reference"]["lap"],
            "current_session_id": source["current_session_reference"]["session_id"],
            "current_lap": source["current_session_reference"]["lap"],
            "current_minus_historical_s": lap_delta,
        },
        "authorized_overview_code": overview,
        "authorized_limitation_codes": sorted(ALLOWED_LIMITATIONS),
        "required_limitation_codes": required_limitations,
        "zones": authorized_zones,
    }


def response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["overview_code", "selected_zones", "limitation_codes"],
        "properties": {
            "overview_code": {"type": "string"},
            "selected_zones": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["zone_id", "significance", "observation_codes"],
                    "properties": {
                        "zone_id": {"type": "string"},
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
                "maxItems": 3,
                "items": {"type": "string"},
            },
        },
    }


def system_prompt() -> str:
    return """Sos un selector de evidencia observacional de telemetría.

Python ya calculó y validó todos los hechos y códigos autorizados. Seleccioná hasta
tres zonas relevantes, ordenalas por importancia y elegí solamente códigos que ya
figuren como autorizados para cada zona.

Reglas obligatorias:
- Copiá literalmente el único authorized_overview_code.
- Copiá zone_id y observation_codes únicamente desde la evidencia de esa zona.
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
    return (
        "EVIDENCIA AUTORIZADA H5.2:\n"
        + json.dumps(evidence, ensure_ascii=False, indent=2)
        + "\n\nSCHEMA DE RESPUESTA:\n"
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
    response: dict[str, Any], evidence: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if set(response) != {"overview_code", "selected_zones", "limitation_codes"}:
        errors.append("claves raíz fuera de contrato")
    if response.get("overview_code") != evidence.get("authorized_overview_code"):
        errors.append("overview_code no coincide con Python")

    zones_by_id = {zone["zone_id"]: zone for zone in evidence.get("zones", [])}
    selected = response.get("selected_zones")
    if not isinstance(selected, list):
        errors.append("selected_zones debe ser una lista")
    elif not 1 <= len(selected) <= min(3, len(zones_by_id)):
        errors.append("selected_zones debe contener entre una y tres zonas existentes")
    else:
        seen: set[str] = set()
        for index, item in enumerate(selected):
            field = f"selected_zones[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{field} debe ser objeto")
                continue
            if set(item) != {"zone_id", "significance", "observation_codes"}:
                errors.append(f"{field} contiene claves fuera de contrato")
            zone_id = item.get("zone_id")
            zone = zones_by_id.get(zone_id)
            if zone is None:
                errors.append(f"{field}.zone_id no existe en la evidencia")
            elif zone_id in seen:
                errors.append(f"{field}.zone_id duplicado")
            else:
                seen.add(zone_id)
            if item.get("significance") not in ALLOWED_SIGNIFICANCE:
                errors.append(f"{field}.significance inválida")
            codes = item.get("observation_codes")
            if not isinstance(codes, list) or not 1 <= len(codes) <= 4:
                errors.append(f"{field}.observation_codes inválidos")
            elif len(codes) != len(set(codes)):
                errors.append(f"{field}.observation_codes duplicados")
            elif zone is not None and not set(codes).issubset(
                set(zone["authorized_observations"])
            ):
                errors.append(f"{field}.observation_codes no autorizados")

    limitations = response.get("limitation_codes")
    if not isinstance(limitations, list) or not 1 <= len(limitations) <= 3:
        errors.append("limitation_codes debe contener entre uno y tres códigos")
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
    response: dict[str, Any], evidence: dict[str, Any]
) -> list[dict[str, Any]]:
    by_id = {zone["zone_id"]: zone for zone in evidence["zones"]}
    return [dict(by_id[item["zone_id"]]) for item in response["selected_zones"]]


def render_analysis(response: dict[str, Any], evidence: dict[str, Any]) -> str:
    lap_delta = evidence["lap_comparison"]["current_minus_historical_s"]
    lines = [
        "Comparación histórica observacional",
        f"Vuelta actual menos histórica: {lap_delta:+.3f} s.",
        OVERVIEW_TEXT[response["overview_code"]],
    ]
    zones = {zone["zone_id"]: zone for zone in evidence["zones"]}
    for item in response["selected_zones"]:
        zone = zones[item["zone_id"]]
        zone_label = zone.get("location_label") or item["zone_id"]
        observations = "; ".join(
            OBSERVATION_TEXT[code] for code in item["observation_codes"]
        )
        lines.append(
            f"{zone_label} [{item['zone_id']}] "
            f"({zone['start_distance_m']:.0f}-"
            f"{zone['end_distance_m']:.0f} m, cambio {zone['delta_change_s']:+.3f} s): "
            f"{observations}."
        )
    limitations = " ".join(LIMITATION_TEXT[code] for code in response["limitation_codes"])
    lines.append("Limitaciones: " + limitations)
    lines.append("Esta comparación no autoriza acciones ni reemplaza la referencia de la sesión.")
    return "\n".join(lines)


def build_output(
    source_path: Path,
    source: dict[str, Any],
    evidence: dict[str, Any],
    response: dict[str, Any],
    *,
    backend: str,
    model: str,
) -> dict[str, Any]:
    errors = validate_response(response, evidence)
    if errors:
        raise ValueError("Respuesta histórica inválida: " + "; ".join(errors))
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "historical_llm_version": HISTORICAL_LLM_VERSION,
            "created_at_utc": utc_now_iso(),
            "source_h5_2_json": str(source_path.resolve()),
            "source_h5_2_sha256": sha256_file(source_path),
            "backend": backend,
            "model": model,
        },
        "status": "VALIDATED_HISTORICAL_OBSERVATION",
        "context": evidence["context"],
        "localization": evidence["localization"],
        "lap_comparison": evidence["lap_comparison"],
        "llm_selection": response,
        "selected_evidence": selected_evidence(response, evidence),
        "rendered_analysis": render_analysis(response, evidence),
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_reference_is_observational": True,
            "historical_actions_authorized": False,
            "causal_claims_authorized": False,
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
    evidence: dict[str, Any], *, backend: str, debug_dir: Path
) -> tuple[dict[str, Any], str]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] | None = None
    model = "unknown"
    for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
        prompt = user_prompt(evidence, errors)
        (debug_dir / f"attempt_{attempt:02d}_prompt.txt").write_text(
            prompt + "\n", encoding="utf-8"
        )
        raw, model = call_backend(backend, system_prompt(), prompt)
        (debug_dir / f"attempt_{attempt:02d}_raw.txt").write_text(
            raw + "\n", encoding="utf-8"
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
        "El LLM no produjo una selección histórica válida: " + "; ".join(errors or [])
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Selección LLM observacional para comparación raw H5.2"
    )
    parser.add_argument("comparison_json")
    parser.add_argument("--backend", choices=BACKEND_CHOICES, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--debug-dir", required=True)
    args = parser.parse_args()

    source_path = Path(args.comparison_json).resolve()
    source = load_validated_source(source_path)
    evidence = build_authorized_evidence(source)
    response, model = generate_response(
        evidence,
        backend=args.backend,
        debug_dir=Path(args.debug_dir).resolve(),
    )
    output = build_output(
        source_path,
        source,
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
    print(f"RACE ENGINEER - H5.2 HISTORICAL LLM v{HISTORICAL_LLM_VERSION}")
    print("=" * 88)
    print(f"Backend/model: {args.backend} / {model}")
    print(f"Selected zones: {len(response['selected_zones'])}")
    print("Free text from LLM: DISABLED")
    print("Historical coaching: DISABLED")
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
