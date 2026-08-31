from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


RENDER_VERSION = "0.2"
SCHEMA_VERSION = "1.0"
STATUS_SECTION = "DETERMINISTIC_HISTORICAL_SECTION"

EXPECTED_H5_1_SCHEMA = "1.0"
EXPECTED_H5_1_VERSION = "0.2"
EXPECTED_H5_2_SCHEMA = "1.1"
EXPECTED_H5_2_VERSION = "0.2"
EXPECTED_TELEMETRY_EVIDENCE_VERSION = "0.6"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: la raíz JSON debe ser un objeto.")
    return payload


def _known(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _delta_sign(delta: float, tolerance: float) -> str:
    if delta > tolerance:
        return "current_slower"
    if delta < -tolerance:
        return "current_faster"
    return "equivalent_within_tolerance"


def load_validated_sources(
    dual_reference_path: Path,
    comparison_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    h5_1 = load_json(dual_reference_path)
    h5_2 = load_json(comparison_path)

    h5_1_meta = h5_1.get("metadata") or {}
    if h5_1_meta.get("schema_version") != EXPECTED_H5_1_SCHEMA:
        raise ValueError("H5.1 metadata.schema_version no soportada")
    if h5_1_meta.get("dual_reference_version") != EXPECTED_H5_1_VERSION:
        raise ValueError("H5.1 dual_reference_version no soportada")
    if h5_1.get("status") != "DUAL_REFERENCE_AVAILABLE":
        raise ValueError("H5.1 status no es DUAL_REFERENCE_AVAILABLE")
    if not isinstance(h5_1.get("session_reference"), dict):
        raise ValueError("H5.1 session_reference ausente")
    if not isinstance(h5_1.get("historical_reference"), dict):
        raise ValueError("H5.1 historical_reference ausente")

    h5_2_meta = h5_2.get("metadata") or {}
    if h5_2_meta.get("schema_version") != EXPECTED_H5_2_SCHEMA:
        raise ValueError("H5.2 metadata.schema_version no soportada")
    if h5_2_meta.get("cross_session_version") != EXPECTED_H5_2_VERSION:
        raise ValueError("H5.2 cross_session_version no soportada")
    if h5_2.get("status") != "RAW_CROSS_SESSION_COMPARISON_AVAILABLE":
        raise ValueError("H5.2 status no soportado")
    temporal = h5_2.get("temporal_validation") or {}
    if temporal.get("status") != "OK":
        raise ValueError("H5.2 temporal_validation no es OK")
    authority = h5_2.get("coaching_authority") or {}
    if authority.get("session_reference_remains_authority") is not True:
        raise ValueError("H5.2 session_reference dejó de ser autoridad")
    if authority.get("historical_actions_authorized") is not False:
        raise ValueError("H5.2 historical_actions_authorized debe ser false")
    return h5_1, h5_2


def _fmt_duration(value: Any) -> str:
    return f"{float(value):.3f} s"


def render_section_text(
    labels: dict[str, Any],
    zones: list[dict[str, Any]],
    limitations: list[str],
) -> str:
    lines = [
        "COMPARACIÓN HISTÓRICA (OBSERVACIONAL)",
        (
            f"Vuelta actual: vuelta {labels['current_session']['lap']} "
            f"(sesión {labels['current_session']['session_id']}) — "
            f"{_fmt_duration(labels['current_session']['duration_s'])}"
        ),
        (
            f"Vuelta histórica: vuelta {labels['historical_reference']['lap']} "
            f"(sesión {labels['historical_reference']['session_id']}) — "
            f"{_fmt_duration(labels['historical_reference']['duration_s'])}"
        ),
        (
            f"Delta actual − histórica: "
            f"{labels['current_minus_historical_s']:+.3f} s"
        ),
        f"Zonas comparables: {len(zones)} "
        f"(perfil: {labels['localization_mode']})",
    ]
    for zone in zones:
        location = (zone.get("location") or {}).get("label") or zone.get(
            "source_trend_zone_id"
        )
        zone_type = zone.get("type") or "desconocida"
        delta = float(zone.get("delta_change", 0.0))
        lines.append(
            f"- {location} ({zone_type}, cambio {delta:+.3f} s, "
            f"{zone.get('start_distance', 0.0):.0f}-"
            f"{zone.get('end_distance', 0.0):.0f} m): observacional"
        )
        steering_trace = zone.get("steering_trace_observation")
        if isinstance(steering_trace, dict):
            lines.append(
                "  Volante (forma observada): variación/100 m "
                f"actual {steering_trace['current_total_variation_per_100m']:.1f} p.p., "
                f"referencia {steering_trace['reference_total_variation_per_100m']:.1f} p.p.; "
                "cruces de signo actual/referencia "
                f"{steering_trace['current_sign_change_count']}/"
                f"{steering_trace['reference_sign_change_count']}."
            )
    lines.append("Limitaciones: " + "; ".join(limitations))
    lines.append(
        "Autoridad: la referencia de la sesión no cambia; las acciones "
        "históricas siguen deshabilitadas."
    )
    return "\n".join(lines)


def build_section(
    dual_reference_path: Path,
    comparison_path: Path,
    telemetry_evidence_path: Path | None = None,
) -> dict[str, Any]:
    dual_reference_path = Path(dual_reference_path).resolve()
    comparison_path = Path(comparison_path).resolve()
    h5_1, h5_2 = load_validated_sources(dual_reference_path, comparison_path)
    telemetry_evidence = None
    if telemetry_evidence_path is not None:
        telemetry_evidence_path = Path(telemetry_evidence_path).resolve()
        telemetry_evidence = load_json(telemetry_evidence_path)
        evidence_metadata = telemetry_evidence.get("metadata") or {}
        evidence_contract = telemetry_evidence.get("contract") or {}
        if evidence_metadata.get("version") != EXPECTED_TELEMETRY_EVIDENCE_VERSION:
            raise ValueError("telemetry evidence metadata.version no soportada")
        if evidence_contract != {
            "observational_only": True,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
            "llm_called": False,
        }:
            raise ValueError("telemetry evidence perdió autoridad observacional")
        if not isinstance(telemetry_evidence.get("interval_evidence"), list):
            raise ValueError("telemetry evidence interval_evidence inválido")

    current = h5_2.get("current_session_reference") or {}
    historical = h5_2.get("historical_reference") or {}
    session_ref = h5_1["session_reference"]
    historical_ref = h5_1["historical_reference"]

    temporal = h5_2["temporal_validation"]
    delta = float(temporal["calculated_current_minus_historical_s"])
    tolerance = float(temporal.get("tolerance_s", 0.0))
    spatial = h5_2.get("spatial_comparison") or {}
    localization = spatial.get("localization") or {}
    mode = localization.get("mode")
    zones = spatial.get("zone_summaries")
    if not isinstance(zones, list):
        raise ValueError("H5.2 zone_summaries ausente/inválido")

    limitations = [
        "single_lap_pair",
        "zone_averages_only",
        "no_causal_inference",
        "no_historical_coaching_authority",
    ]
    if mode != "validated_track_profile":
        limitations.append("track_profile_localization_unavailable")

    zone_records = []
    evidence_intervals = (
        telemetry_evidence["interval_evidence"]
        if telemetry_evidence is not None
        else []
    )
    if evidence_intervals and len(evidence_intervals) != len(zones):
        raise ValueError("telemetry evidence no coincide con las zonas H5.2")
    for index, zone in enumerate(zones):
        record = dict(zone)
        record["observational_only"] = True
        record["action_authorized"] = False
        if evidence_intervals:
            evidence = evidence_intervals[index]
            if not isinstance(evidence, dict):
                raise ValueError("telemetry evidence contiene un intervalo inválido")
            if not (
                math.isclose(
                    float(record.get("start_distance")),
                    float(evidence.get("start_distance_m")),
                )
                and math.isclose(
                    float(record.get("end_distance")),
                    float(evidence.get("end_distance_m")),
                )
            ):
                raise ValueError("telemetry evidence no coincide físicamente con H5.2")
            if evidence.get("steering_trace_scope") == "COMPARABLE_CORNER":
                record["steering_trace_observation"] = {
                    "scope": "COMPARABLE_CORNER",
                    "current_total_variation_per_100m": float(
                        evidence["current_steering_total_variation_per_100m"]
                    ),
                    "reference_total_variation_per_100m": float(
                        evidence["reference_steering_total_variation_per_100m"]
                    ),
                    "total_variation_delta_per_100m": float(
                        evidence["steering_total_variation_delta_per_100m"]
                    ),
                    "sign_change_relation": evidence[
                        "steering_sign_change_relation"
                    ],
                    "current_sign_change_count": int(
                        evidence["current_steering_sign_change_count"]
                    ),
                    "reference_sign_change_count": int(
                        evidence["reference_steering_sign_change_count"]
                    ),
                    "observed_span_m": float(evidence["steering_observed_span_m"]),
                    "observational_only": True,
                    "action_authorized": False,
                    "interpretation_authorized": False,
                }
        zone_records.append(record)

    labels = {
        "current_session": {
            "session_id": current.get("session_id"),
            "lap": session_ref.get("lap") or current.get("lap"),
            "duration_s": session_ref.get("duration_s") or current.get("duration_s"),
        },
        "historical_reference": {
            "session_id": historical.get("session_id")
            or historical_ref.get("session_id"),
            "lap": historical_ref.get("lap") or historical.get("lap"),
            "duration_s": historical_ref.get("duration_s")
            or historical.get("duration_s"),
        },
        "current_minus_historical_s": delta,
        "delta_sign": _delta_sign(delta, tolerance),
        "localization_mode": mode,
        "zone_count": len(zone_records),
    }

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "render_version": RENDER_VERSION,
        "source_dual_reference_json": str(dual_reference_path),
        "source_dual_reference_sha256": sha256_file(dual_reference_path),
        "source_comparison_json": str(comparison_path),
        "source_comparison_sha256": sha256_file(comparison_path),
        "policy": {
            "no_llm_called": True,
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        },
    }
    if telemetry_evidence_path is not None:
        metadata.update({
            "source_telemetry_evidence_json": str(telemetry_evidence_path),
            "source_telemetry_evidence_sha256": sha256_file(
                telemetry_evidence_path
            ),
        })
    return {
        "metadata": metadata,
        "status": STATUS_SECTION,
        "labels": labels,
        "zones": zone_records,
        "limitations": limitations,
        "rendered_section": render_section_text(
            labels,
            zone_records,
            limitations,
        ),
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_reference_is_observational": True,
            "historical_actions_authorized": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3d: render determinista de la sección histórica observacional."
    )
    parser.add_argument("dual_reference_json")
    parser.add_argument("comparison_json")
    parser.add_argument("--telemetry-evidence")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_section(
        Path(args.dual_reference_json),
        Path(args.comparison_json),
        (
            Path(args.telemetry_evidence)
            if args.telemetry_evidence is not None
            else None
        ),
    )
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 88)
    print(f"RACE ENGINEER - H5.3d DETERMINISTIC HISTORICAL SECTION v{RENDER_VERSION}")
    print("=" * 88)
    print(f"Status: {payload['status']}")
    print(f"Delta actual - historica: {payload['labels']['current_minus_historical_s']:+.3f} s")
    print(f"Zonas comparables: {payload['labels']['zone_count']}")
    print(f"Limitaciones: {len(payload['limitations'])}")
    print("LLM: NOT CALLED")
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
