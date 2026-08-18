from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


BUILDER_VERSION = "0.1"
SCHEMA_VERSION = "1.0"
STATUS_SHADOW = "SHADOW_OBSERVATIONAL_ONLY"

EXPECTED_H5_1_SCHEMA = "1.0"
EXPECTED_H5_1_VERSION = "0.2"
EXPECTED_H5_2_SCHEMA = "1.1"
EXPECTED_H5_2_VERSION = "0.2"

H5_1_STATUS_HISTORICAL = "DUAL_REFERENCE_AVAILABLE"
H5_1_STATUS_SESSION_ONLY = "SESSION_REFERENCE_ONLY"
H5_2_STATUS_AVAILABLE = "RAW_CROSS_SESSION_COMPARISON_AVAILABLE"

CHANNEL_DELTA_KEYS = (
    "speed_delta_avg",
    "throttle_delta_avg",
    "brake_delta_avg",
    "steering_delta_avg",
)


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


def _context_matches(
    h5_1_context: dict[str, Any],
    h5_2_context: dict[str, Any],
) -> None:
    for key in ("track", "track_layout", "vehicle_variant", "car_name_raw"):
        left = _known(h5_1_context.get(key))
        right = _known(h5_2_context.get(key))
        if left is not None and right is not None and left != right:
            raise ValueError(
                f"Context mismatch en {key}: H5.1={left!r} H5.2={right!r}"
            )


def _skip(reason: str, *, sources: dict[str, Any], h5_1: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "status": STATUS_SHADOW,
        "source_h5_1_json": str(sources["h5_1_path"].resolve()),
        "source_h5_1_sha256": sources["h5_1_sha256"],
        "source_h5_2_json": str(sources["h5_2_path"].resolve()),
        "source_h5_2_sha256": sources["h5_2_sha256"],
        "policy": {
            "python_owns_candidates": True,
            "no_llm_called": True,
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        },
    }
    context = h5_1.get("context") or {}
    return {
        "metadata": metadata,
        "status": STATUS_SHADOW,
        "prerequisites": {
            "h5_1_status": h5_1.get("status"),
            "h5_2_status": None,
            "temporal_validation": None,
            "localization_mode": None,
            "applicable": False,
            "skip_reason": reason,
        },
        "context": {
            "track": context.get("track"),
            "track_layout": context.get("track_layout"),
            "vehicle_variant": context.get("vehicle_variant"),
            "car_name_raw": context.get("car_name_raw"),
        },
        "session_reference": None,
        "historical_reference": None,
        "total_delta": None,
        "candidates": [],
        "limitations": [reason],
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
        },
    }


def _delta_sign(delta: float, tolerance: float) -> str:
    if delta > tolerance:
        return "current_slower"
    if delta < -tolerance:
        return "current_faster"
    return "equivalent_within_tolerance"


def build_candidates(
    dual_reference_path: Path,
    comparison_path: Path,
) -> dict[str, Any]:
    dual_reference_path = Path(dual_reference_path).resolve()
    comparison_path = Path(comparison_path).resolve()
    h5_1 = load_json(dual_reference_path)
    h5_2 = load_json(comparison_path)

    h5_1_meta = h5_1.get("metadata") or {}
    if h5_1_meta.get("schema_version") != EXPECTED_H5_1_SCHEMA:
        raise ValueError("H5.1 metadata.schema_version no soportada")
    if h5_1_meta.get("dual_reference_version") != EXPECTED_H5_1_VERSION:
        raise ValueError("H5.1 dual_reference_version no soportada")

    sources = {
        "h5_1_path": dual_reference_path,
        "h5_1_sha256": sha256_file(dual_reference_path),
        "h5_2_path": comparison_path,
        "h5_2_sha256": sha256_file(comparison_path),
    }

    h5_1_status = h5_1.get("status")
    if h5_1_status == H5_1_STATUS_SESSION_ONLY:
        return _skip("historical_reference_unavailable", sources=sources, h5_1=h5_1)
    if h5_1_status != H5_1_STATUS_HISTORICAL:
        raise ValueError(f"H5.1 status no soportado: {h5_1_status!r}")

    h5_1_authority = h5_1.get("coaching_authority") or {}
    if h5_1_authority.get("historical_reference_can_change_driver_cues") is not False:
        raise ValueError("H5.1 autoriza cambiar cues históricos; no permitido")
    if h5_1_authority.get("historical_reference_can_change_global_ABC_plan") is not False:
        raise ValueError("H5.1 autoriza cambiar el plan A/B/C; no permitido")
    if h5_1_authority.get("historical_reference_is_observational_only") is not True:
        raise ValueError("H5.1 historical_reference debe ser observacional")

    session_reference = h5_1.get("session_reference")
    historical_reference = h5_1.get("historical_reference")
    if not isinstance(session_reference, dict) or not isinstance(historical_reference, dict):
        return _skip("historical_reference_unavailable", sources=sources, h5_1=h5_1)
    if not isinstance(session_reference.get("lap"), int) or not isinstance(
        session_reference.get("duration_s"), (int, float)
    ):
        raise ValueError("H5.1 session_reference inválida")
    if not isinstance(historical_reference.get("session_id"), int) or not isinstance(
        historical_reference.get("lap"), int
    ):
        raise ValueError("H5.1 historical_reference inválida")

    h5_2_meta = h5_2.get("metadata") or {}
    if h5_2_meta.get("schema_version") != EXPECTED_H5_2_SCHEMA:
        raise ValueError("H5.2 metadata.schema_version no soportada")
    if h5_2_meta.get("cross_session_version") != EXPECTED_H5_2_VERSION:
        raise ValueError("H5.2 cross_session_version no soportada")
    if h5_2.get("status") != H5_2_STATUS_AVAILABLE:
        raise ValueError("H5.2 status no es RAW_CROSS_SESSION_COMPARISON_AVAILABLE")

    h5_2_authority = h5_2.get("coaching_authority") or {}
    if h5_2_authority.get("session_reference_remains_authority") is not True:
        raise ValueError("H5.2 session_reference dejó de ser autoridad")
    if h5_2_authority.get("historical_actions_authorized") is not False:
        raise ValueError("H5.2 historical_actions_authorized debe ser false")

    temporal = h5_2.get("temporal_validation") or {}
    if temporal.get("status") != "OK":
        raise ValueError("H5.2 temporal_validation no es OK")
    calculated_delta = temporal.get("calculated_current_minus_historical_s")
    tolerance = temporal.get("tolerance_s")
    if not isinstance(calculated_delta, (int, float)) or not isinstance(
        tolerance, (int, float)
    ):
        raise ValueError("H5.2 temporal_validation inválida")

    _context_matches(h5_1.get("context") or {}, h5_2.get("context") or {})

    spatial = h5_2.get("spatial_comparison") or {}
    localization = spatial.get("localization") or {}
    mode = localization.get("mode")
    zone_summaries = spatial.get("zone_summaries")

    if mode == "validated_track_profile":
        if not isinstance(zone_summaries, list):
            raise ValueError("H5.2 zone_summaries ausente/inválido")
        candidates: list[dict[str, Any]] = []
        for index, zone in enumerate(zone_summaries, start=1):
            if not isinstance(zone, dict):
                raise ValueError(f"H5.2 zone_summaries[{index}] inválido")
            if zone.get("scope") != "track_profile_segment":
                raise ValueError(f"H5.2 zone_summaries[{index}].scope inválido")
            source_trend_zone_id = zone.get("source_trend_zone_id")
            location = zone.get("location")
            if not isinstance(source_trend_zone_id, str) or not isinstance(location, dict):
                raise ValueError(f"H5.2 zone_summaries[{index}] no localizada")
            delta_change = zone.get("delta_change")
            start_distance = zone.get("start_distance")
            end_distance = zone.get("end_distance")
            if not all(
                isinstance(value, (int, float))
                for value in (delta_change, start_distance, end_distance)
            ):
                raise ValueError(f"H5.2 zone_summaries[{index}] evidencia incompleta")
            evidence = {
                key: zone[key]
                for key in CHANNEL_DELTA_KEYS
                if isinstance(zone.get(key), (int, float))
            }
            candidates.append(
                {
                    "candidate_id": f"cand_{index:03d}",
                    "source_trend_zone_id": source_trend_zone_id,
                    "source_zone_index": index - 1,
                    "location": dict(location),
                    "current_minus_historical": {
                        "delta_change_s": float(delta_change),
                        "start_distance_m": float(start_distance),
                        "end_distance_m": float(end_distance),
                        "distance_m": float(
                            end_distance - start_distance
                        ),
                    },
                    "observational_channel_evidence": evidence,
                    "authorization": {
                        "action_authorized": False,
                        "observational_only": True,
                    },
                    "limitations": [
                        "physical_onset_release_and_action_profile_not_attached_in_h5_3a_v0_1"
                    ],
                }
            )
        applicable = True
        skip_reason = None
    elif mode == "unavailable":
        applicable = False
        skip_reason = "no_exact_validated_track_profile"
        candidates = []
    else:
        raise ValueError(f"H5.2 localization.mode no soportado: {mode!r}")

    h5_1_context = h5_1.get("context") or {}
    h5_2_context = h5_2.get("context") or {}
    context = {
        "track": _known(h5_2_context.get("track")) or _known(h5_1_context.get("track")),
        "track_layout": _known(h5_2_context.get("track_layout"))
        or _known(h5_1_context.get("track_layout")),
        "vehicle_variant": _known(h5_2_context.get("vehicle_variant"))
        or _known(h5_1_context.get("vehicle_variant")),
        "car_name_raw": _known(h5_2_context.get("car_name_raw"))
        or _known(h5_1_context.get("car_name_raw")),
    }

    limitations = [
        "physical_onset_release_and_action_profile_not_attached_in_h5_3a_v0_1",
        "single_pair_evidence_not_generalized",
    ]
    if not candidates:
        limitations.append("no_localized_candidates")

    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "builder_version": BUILDER_VERSION,
            "status": STATUS_SHADOW,
            "source_h5_1_json": str(dual_reference_path),
            "source_h5_1_sha256": sources["h5_1_sha256"],
            "source_h5_2_json": str(comparison_path),
            "source_h5_2_sha256": sources["h5_2_sha256"],
            "policy": {
                "python_owns_candidates": True,
                "no_llm_called": True,
                "historical_actions_authorized": False,
                "session_reference_remains_authority": True,
            },
        },
        "status": STATUS_SHADOW,
        "prerequisites": {
            "h5_1_status": h5_1_status,
            "h5_2_status": h5_2.get("status"),
            "temporal_validation": temporal.get("status"),
            "localization_mode": mode,
            "applicable": applicable,
            "skip_reason": skip_reason,
        },
        "context": context,
        "session_reference": {
            "session_id": (h5_1.get("target_session") or {}).get("session_id"),
            "lap": session_reference.get("lap"),
            "duration_s": session_reference.get("duration_s"),
        },
        "historical_reference": {
            "session_id": historical_reference.get("session_id"),
            "lap": historical_reference.get("lap"),
            "duration_s": historical_reference.get("duration_s"),
        },
        "total_delta": {
            "current_minus_historical_s": float(calculated_delta),
            "sign": _delta_sign(float(calculated_delta), float(tolerance)),
            "tolerance_s": float(tolerance),
        },
        "candidates": candidates,
        "limitations": limitations,
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_reference_is_observational": True,
            "historical_actions_authorized": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3a: construye candidatos históricos deterministas en shadow."
    )
    parser.add_argument("dual_reference_json")
    parser.add_argument("comparison_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_candidates(
        Path(args.dual_reference_json),
        Path(args.comparison_json),
    )
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    prerequisites = payload["prerequisites"]
    print("=" * 88)
    print(f"RACE ENGINEER - H5.3a HISTORICAL SHADOW CANDIDATES v{BUILDER_VERSION}")
    print("=" * 88)
    print(f"Status: {payload['status']}")
    print(f"Applicable: {prerequisites['applicable']}")
    if prerequisites["skip_reason"]:
        print(f"Skip reason: {prerequisites['skip_reason']}")
    print(f"Candidates: {len(payload['candidates'])}")
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
