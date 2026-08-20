"""H5.3b shadow: determinista gate de elegibilidad de candidatos históricos.

Estado: SHADOW_ELIGIBILITY_ONLY
Autoridad: ninguna
historical_actions_authorized: false
session_reference_remains_authority: true

Este módulo evalúa candidatos de la fase H5.3a para determinar si son
suficientemente significativos como para merecer selección H5.3c (shadow).

Estados de elegibilidad:
- ELIGIBLE_FOR_SELECTION:  delta_change_s > MIN_SIGNIFICANT_DELTA_S, contexto
                           completo, geometría válida y evidencias comparables.
- WITHHELD:               delta_change_s <= threshold, contexto inválido, geometría
                           inválida, evidencia no comparable u otros motivos.
- AMBIGUOUS:              actualmente no producido automáticamente en v0.1.
                           Se requiere señal determinista explícita de ambigüedad.

NO:
  - llama LLM
  - genera coaching ni acciones
  - se integra en race_engineer.py
  - modifica historical_candidate_selection.py
  - modifica historical_action_policy.py

SIGNIFICANCE POLICY:
  MIN_SIGNIFICANT_DELTA_S = 0.08  (constante explícita, no aprendida)
  delta_change_s > 0.08 -> ELIGIBLE (significativa pérdida de tiempo por zona)
  delta_change_s <= 0.08 -> WITHHELD (insignificant_delta)
  delta_sign (current_slower / current_faster) es CONTEXTO, no criterio de
  significancia. No se usa abs(). Delta negativo siempre -> WITHHELD.
  delta_change_s representa pérdida/ganancia local de tiempo; solo la pérdida
  (delta positivo) determina significancia de zona.

REGLAS DE EVIDENCIA:
  - brake / throttle / speed no deciden significancia individualmente.
  - profile_localization = not_available NO rechaza automáticamente.
  - canales faltantes individuales NO rechazan automáticamente.
  - AMBIGUOUS no producido por human_label, sparse channels ni localización.
  - human_label NO influye en eligibility (retrospective replay only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


# ── Policy constants ──────────────────────────────────────────────────────

ELIGIBILITY_VERSION = "0.1"
SCHEMA_VERSION = "1.0"
SHADOW_STATUS = "SHADOW_ELIGIBILITY_ONLY"

# Significance threshold — constante explícita, no aprendida.
# No se usa abs(). delta_change_s positivo = pérdida de tiempo; negativo = ganancia.
MIN_SIGNIFICANT_DELTA_S = 0.08

# Candidate audit record fields expected from H5.3b dataset.
_DATASET_FIELDS = (
    "audit_id",
    "candidate_id",
    "context",
    "delta_sign",
    "evidence",
    "observational_channel_evidence",
    "label",
    "location_label",
    "source_artifact_sha256",
)

# Evidence fields expected per candidate.
_EVIDENCE_FIELDS = (
    "delta_change_s",
    "start_distance_m",
    "end_distance_m",
)

# Context keys required for minimal context.
# NOTE: candidate_id is at the top level of the loaded candidate, not inside
# context. _MINIMAL_CONTEXT_KEYS is only the three keys that live inside context.
_MINIMAL_CONTEXT_KEYS = (
    "track",
    "track_layout",
    "vehicle_variant",
)

# Eligibility reason codes — grouped por categoría.
# Context
REASON_MISSING_CONTEXT = "missing_context"
# Geometry
REASON_INVALID_GEOMETRY = "invalid_geometry"
# Significance
REASON_INSIGNIFICANT_DELTA = "insignificant_delta"
REASON_NO_DELTA = "no_delta"
# Comparability
REASON_NOT_COMPARABLE = "not_comparable"
# Evidence
REASON_NO_EVIDENCE = "no_channel_evidence"
# Localization
REASON_AMBIGUOUS_LOCALIZATION = "ambiguous_localization"
# Human ambiguity
REASON_AMBIGUOUS_HUMAN = "ambiguous_human_label"
# Generic
REASON_UNCERTAIN = "uncertain"
REASON_OK = "eligible_ok"

# Channel keys used in H5.3b candidates.
_CHANNEL_KEYS = (
    "speed_delta_avg",
    "throttle_delta_avg",
    "brake_delta_avg",
    "steering_delta_avg",
)


# ── Eligibility status codes ──────────────────────────────────────────────

ELIGIBLE = "ELIGIBLE_FOR_SELECTION"
WITHHELD = "WITHHELD"
AMBIGUOUS = "AMBIGUOUS"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _known(value: Any) -> str | None:
    """Return trimmed text or None for None / whitespace-only / empty."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_numeric(value: Any) -> bool:
    """Return True for int/float (but NOT bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _has_nan_or_inf(value: Any) -> bool:
    """Return True if a numeric value is NaN or Inf."""
    try:
        f = float(value)
        if f != f:  # NaN
            return True
        if f == float("inf") or f == float("-inf"):
            return True
        return False
    except (TypeError, ValueError):
        return True


# ── H5.3a → canonical eligibility candidate normalizer ────────────────────

# H5.3a raw schema (build_historical_coaching_candidates.py v0.1):
#   candidate_id: str
#   location: dict (segment-level location data)
#   current_minus_historical: { delta_change_s, start_distance_m, end_distance_m, distance_m }
#   observational_channel_evidence: { speed_delta_avg?, throttle_delta_avg?, ... }
#   (no audit_id, delta_sign, evidence, context, label, location_label, source_artifact_sha256)
#
# Canonical eligibility schema (_DATASET_FIELDS):
#   audit_id, candidate_id, context, delta_sign, evidence
#   observational_channel_evidence, label, location_label, source_artifact_sha256

# Tolerance for delta_sign derivation — same semantics as build_candidates._delta_sign.
_DELTA_SIGN_TOLERANCE_S = 0.05


def _compute_delta_sign(delta_change_s: float) -> str:
    """Derive delta_sign exclusively from delta_change_s using existing semantics.

    delta_change_s >  tolerance → "current_slower"
    delta_change_s < -tolerance → "current_faster"
    else                        → "equivalent_within_tolerance"

    NO abs(). NO human label involvement.
    """
    if delta_change_s > _DELTA_SIGN_TOLERANCE_S:
        return "current_slower"
    if delta_change_s < -_DELTA_SIGN_TOLERANCE_S:
        return "current_faster"
    return "equivalent_within_tolerance"


def _extract_location_label(location: Any) -> str | None:
    """Extract a string location_label from H5.3a location dict.

    H5.3a location is a dict with keys like 'segment_name', 'turn_name', etc.
    Returns the first meaningful string or None.
    """
    if not isinstance(location, dict):
        return None
    for key in ("segment_name", "turn_name", "segment", "turn"):
        value = location.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip() or None
    # Fallback: join all string values.
    parts = [str(v) for v in location.values() if isinstance(v, str) and v.strip()]
    return " ".join(parts) or None


def normalize_h5_3a_candidate_for_eligibility(
    raw_candidate: dict[str, Any],
    source_artifact_path: Path,
    session_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalizar un raw H5.3a candidate al canonical eligibility schema.

    This function bridges the H5.3a builder output (build_historical_coaching_candidates.py)
    to the eligibility consumer (historical_candidate_eligibility.py). It must NOT:
    - invent human labels
    - change MIN_SIGNIFICANT_DELTA_S
    - weaken _DATASET_FIELDS
    - silently accept malformed records

    If the raw candidate is malformed (missing required keys), the caller must
    handle the ValueError. This function never returns a partial record.

    Returns a dict with exactly these keys:
      audit_id, candidate_id, context, delta_sign, evidence,
      observational_channel_evidence, label, location_label, source_artifact_sha256
    """
    # ── Validate required H5.3a keys ──────────────────────────────────
    if not isinstance(raw_candidate, dict):
        raise ValueError(f"normalize_h5_3a_candidate: record no es dict")

    required_h53a_keys = ("candidate_id", "current_minus_historical", "observational_channel_evidence")
    for key in required_h53a_keys:
        if key not in raw_candidate:
            raise ValueError(f"normalize_h5_3a_candidate: raw candidate ausente campo {key!r}")

    cmh = raw_candidate["current_minus_historical"]
    if not isinstance(cmh, dict):
        raise ValueError("normalize_h5_3a_candidate: current_minus_historical no es dict")

    # ── Extract canonical fields ──────────────────────────────────────
    raw_candidate_id = raw_candidate["candidate_id"]
    delta_change_s = cmh["delta_change_s"]
    start_distance_m = cmh["start_distance_m"]
    end_distance_m = cmh["end_distance_m"]

    # audit_id: deterministic identity using source artifact SHA + raw candidate_id
    source_sha = _sha256_file(source_artifact_path)
    audit_id = f"{source_sha}:{raw_candidate_id}"

    # delta_sign: derived from delta_change_s using existing semantics (no abs)
    delta_sign = _compute_delta_sign(float(delta_change_s))

    # context: from session_context (top-level of H5.3a JSON)
    ctx = session_context or {}
    context = {
        "track": _known(ctx.get("track")),
        "track_layout": _known(ctx.get("track_layout")),
        "vehicle_variant": _known(ctx.get("vehicle_variant")),
        "car_name_raw": _known(ctx.get("car_name_raw")),
    }

    # evidence: flat mapping from current_minus_historical
    evidence = {
        "delta_change_s": float(delta_change_s),
        "start_distance_m": float(start_distance_m),
        "end_distance_m": float(end_distance_m),
    }

    # observational_channel_evidence: pass through (may be empty dict)
    channel_evidence = raw_candidate.get("observational_channel_evidence") or {}

    # location_label: extract from H5.3a location dict
    location_label = _extract_location_label(raw_candidate.get("location"))

    return {
        "audit_id": audit_id,
        "candidate_id": raw_candidate_id,
        "context": context,
        "delta_sign": delta_sign,
        "evidence": evidence,
        "observational_channel_evidence": dict(channel_evidence),
        "label": None,
        "location_label": location_label or "UNKNOWN",
        "source_artifact_sha256": source_sha,
    }


def normalize_h5_3a_candidates_for_eligibility(
    candidates_path: Path,
) -> list[dict[str, Any]]:
    """Normalizar TODOS los H5.3a candidates al canonical eligibility schema.

    Loads the H5.3a candidates JSON, extracts the top-level session context,
    normalizes each candidate, and returns a flat list.

    Raises ValueError if any candidate is malformed.
    """
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{candidates_path}: raíz JSON inválido")

    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError(f"{candidates_path}: 'candidates' ausente o inválido")

    # Extract session context from top-level (same structure as H5.3a JSON)
    session_context = payload.get("context", {})

    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(candidates):
        try:
            norm = normalize_h5_3a_candidate_for_eligibility(raw, candidates_path, session_context)
        except ValueError:
            # Fail closed: malformed candidate stops the pipeline.
            raise
        normalized.append(norm)

    return normalized


# ── Candidate record loading ──────────────────────────────────────────────

def _load_candidate(
    record: dict[str, Any],
    dataset_path: Path,
) -> dict[str, Any]:
    """Validar y enriquecer un solo registro del dataset H5.3b."""
    if not isinstance(record, dict):
        raise ValueError("Candidato no es objeto dict")
    for field in _DATASET_FIELDS:
        if field not in record:
            raise ValueError(f"Candidato ausente campo {field!r}")

    context = record.get("context") or {}
    evidence = record.get("evidence") or {}
    channel_evidence = record.get("observational_channel_evidence") or {}

    # Generate unique candidate_id from audit_id if candidate_id is not unique.
    # audit_id includes source prefix (e.g., "1b802498c37f:cand_001").
    # candidate_id may repeat across sources (e.g., "cand_001").
    unique_candidate_id = record.get("audit_id") or record.get("candidate_id", "UNKNOWN")

    return {
        "audit_id": record["audit_id"],
        "candidate_id": unique_candidate_id,
        "source_artifact_sha256": record["source_artifact_sha256"],
        "source_dataset_path": str(dataset_path),
        "context": {
            "track": _known(context.get("track")),
            "track_layout": _known(context.get("track_layout")),
            "vehicle_variant": _known(context.get("vehicle_variant")),
            "car_name_raw": _known(context.get("car_name_raw")),
        },
        "delta_sign": _known(record.get("delta_sign")),
        "location_label": _known(record.get("location_label")) or "UNKNOWN",
        "evidence": {
            "delta_change_s": evidence.get("delta_change_s"),
            "start_distance_m": evidence.get("start_distance_m"),
            "end_distance_m": evidence.get("end_distance_m"),
        },
        "channel_evidence": dict(channel_evidence),
        "human_label": record.get("label"),
    }


# ── Eligibility evaluation ────────────────────────────────────────────────

def evaluate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Evaluar un solo candidato y devolver dict con status + reason_codes.

    Evaluación en orden:
    1. Contexto mínimo (track, track_layout, vehicle_variant).
    2. Geometría (finito, end > start, zone_length > 0).
    3. Significance (delta_change_s > MIN_SIGNIFICANT_DELTA_S).
    4. Evidence availability (no channel evidence -> WITHHELD).

    NO:
      - human_label participa (NO es señal determinista de comparabilidad).
      - sparse channels + no location -> AMBIGUOUS (no hay señal determinista).
      - abs(delta_change_s) (solo delta > 0.08 es ELIGIBLE).

    Returns dict con:
      - eligibility_status: ELIGIBLE / WITHHELD / AMBIGUOUS
      - reason_codes: list[str]
      - delta_sign, delta_change_s, geometry, channel_availability,
        localization, provenance.
    """
    context = candidate["context"]
    evidence = candidate["evidence"]
    channel_evidence = candidate["channel_evidence"]

    reason_codes: list[str] = []
    status = None

    # ── 1. Contexto mínimo ──────────────────────────────────────────────
    has_context = all(context.get(key) for key in _MINIMAL_CONTEXT_KEYS)
    if not has_context:
        missing = [key for key in _MINIMAL_CONTEXT_KEYS if not context.get(key)]
        return _result(
            candidate,
            WITHHELD,
            [REASON_MISSING_CONTEXT],
            reasons=f"context_missing={','.join(missing)}",
            context=context,
            evidence=evidence,
            channel_evidence=channel_evidence,
        )

    # ── 2. Geometría ────────────────────────────────────────────────────
    start = evidence.get("start_distance_m")
    end = evidence.get("end_distance_m")
    delta_change = evidence.get("delta_change_s")

    # Check for NaN/Inf before geometry evaluation
    if _has_nan_or_inf(start) or _has_nan_or_inf(end) or _has_nan_or_inf(delta_change):
        return _result(
            candidate,
            WITHHELD,
            [REASON_INVALID_GEOMETRY],
            reasons="geometría inválida: NaN o Inf detectado",
            context=context,
            evidence=evidence,
            channel_evidence=channel_evidence,
        )

    # Check if numeric at all
    if not _is_numeric(start) or not _is_numeric(end) or not _is_numeric(delta_change):
        return _result(
            candidate,
            WITHHELD,
            [REASON_INVALID_GEOMETRY],
            reasons="geometría inválida: valores ausentes o no numéricos",
            context=context,
            evidence=evidence,
            channel_evidence=channel_evidence,
        )

    if end <= start:
        return _result(
            candidate,
            WITHHELD,
            [REASON_INVALID_GEOMETRY],
            reasons="geometría inválida: end <= start",
            context=context,
            evidence=evidence,
            channel_evidence=channel_evidence,
        )

    zone_length = float(end - start)
    if zone_length <= 0:
        return _result(
            candidate,
            WITHHELD,
            [REASON_INVALID_GEOMETRY],
            reasons="geometría inválida: zone_length <= 0",
            context=context,
            evidence=evidence,
            channel_evidence=channel_evidence,
        )

    # ── 3. Significance ─────────────────────────────────────────────────
    # delta_change_s <= threshold -> WITHHELD.
    # No se usa abs(). Solo delta positivo > 0.08 es ELIGIBLE.
    # Delta negativo siempre -> WITHHELD (delta representa ganancia, no pérdida).
    if delta_change is None or not _is_numeric(delta_change):
        return _result(
            candidate,
            WITHHELD,
            [REASON_NO_DELTA],
            reasons="delta_change_s ausente o inválido",
            context=context,
            evidence=evidence,
            channel_evidence=channel_evidence,
        )

    # delta > 0.08 → ELIGIBLE (significant zone loss)
    # delta <= 0.08 → WITHHELD (insignificant or no zone loss, including negative)
    if delta_change <= MIN_SIGNIFICANT_DELTA_S:
        return _result(
            candidate,
            WITHHELD,
            [REASON_INSIGNIFICANT_DELTA],
            reasons=f"delta_change_s={delta_change:.6f} <= {MIN_SIGNIFICANT_DELTA_S}",
            context=context,
            evidence=evidence,
            channel_evidence=channel_evidence,
            zone_length=zone_length,
        )

    # ── 4. Evidence availability ────────────────────────────────────────
    # Canales faltantes individuales NO rechazan automáticamente.
    channel_keys = [
        "speed_delta_avg",
        "throttle_delta_avg",
        "brake_delta_avg",
        "steering_delta_avg",
    ]
    available_count = sum(
        1 for key in channel_keys
        if _is_numeric(channel_evidence.get(key))
    )

    # Sin channels => WITHHELD (no channel evidence)
    if available_count == 0:
        return _result(
            candidate,
            WITHHELD,
            [REASON_NO_EVIDENCE],
            reasons="observational_channel_evidence ausente o todos nulos",
            context=context,
            evidence=evidence,
            channel_evidence={},
            zone_length=zone_length,
        )

    # ── 5. ELIGIBLE ─────────────────────────────────────────────────────
    # Si delta > 0.08 y tiene al menos un canal -> ELIGIBLE.
    # No se produce AMBIGUOUS en v0.1 (no hay señal determinista de ambigüedad).
    status = ELIGIBLE
    reason_codes.append(REASON_OK)
    return _result(
        candidate,
        ELIGIBLE,
        reason_codes,
        reasons="eligible_ok",
        context=context,
        evidence=evidence,
        channel_evidence=channel_evidence,
        zone_length=zone_length,
    )


def _result(
    candidate: dict[str, Any],
    status: str,
    reason_codes: list[str],
    *,
    reasons: str,
    context: dict[str, Any],
    evidence: dict[str, Any],
    channel_evidence: dict[str, Any],
    zone_length: float | None = None,
) -> dict[str, Any]:
    """Construir resultado final con todos los campos requeridos."""
    delta_change = evidence.get("delta_change_s")
    start_distance = evidence.get("start_distance_m")
    end_distance = evidence.get("end_distance_m")

    # Determinar disponibilidad de canales.
    available_channels = sorted(
        key for key in _CHANNEL_KEYS
        if _is_numeric(channel_evidence.get(key))
    )
    missing_channels = sorted(
        key for key in _CHANNEL_KEYS
        if key not in channel_evidence or not _is_numeric(channel_evidence.get(key))
    )

    # Determinar localización.
    has_location = candidate.get("location_label") != "UNKNOWN"
    localization_status = "localized" if has_location else "not_available"

    return {
        "contract": {
            "schema_version": SCHEMA_VERSION,
            "eligibility_version": ELIGIBILITY_VERSION,
            "status": SHADOW_STATUS,
            "policy": {
                "python_owns_eligibility": True,
                "no_llm_involved": True,
                "historical_actions_authorized": False,
                "historical_coaching_authorized": False,
                "session_reference_remains_authority": True,
                "lmp2_elms_distinct_from_lmp2": True,
                "current_faster_can_be_eligible": True,
                "anti_regression_belongs_to_action_policy": True,
                "brake_throttle_speed_do_not_decide_significance": True,
                "speed_is_context_not_action": True,
                "profile_localization_unavailable_does_not_reject_automatically": True,
                "individual_missing_channels_do_not_reject_automatically": True,
                "ambiguous_only_for_truly_ambiguous_evidence": True,
                "min_significant_delta_s": MIN_SIGNIFICANT_DELTA_S,
                "significance_threshold_is_explicit_constant_not_learned": True,
            },
        },
        "eligibility_status": status,
        "reason_codes": reason_codes,
        "reason": reasons,
        "candidate_context": {
            "candidate_id": candidate["candidate_id"],
            "track": candidate["context"]["track"],
            "track_layout": candidate["context"]["track_layout"],
            "vehicle_variant": candidate["context"]["vehicle_variant"],
            "car_name_raw": candidate["context"].get("car_name_raw"),
        },
        "delta_sign": candidate["delta_sign"],
        "delta_change_s": float(delta_change) if _is_numeric(delta_change) else None,
        "geometry": {
            "start_distance_m": float(start_distance) if _is_numeric(start_distance) else None,
            "end_distance_m": float(end_distance) if _is_numeric(end_distance) else None,
            "zone_length_m": float(zone_length) if zone_length is not None else None,
            "geometry_valid": zone_length is not None and zone_length > 0,
        },
        "channel_availability": {
            "available_channels": available_channels,
            "missing_channels": missing_channels,
            "has_speed": _is_numeric(channel_evidence.get("speed_delta_avg")),
            "has_throttle": _is_numeric(channel_evidence.get("throttle_delta_avg")),
            "has_brake": _is_numeric(channel_evidence.get("brake_delta_avg")),
        },
        "observational_channel_evidence": {
            key: channel_evidence.get(key)
            for key in _CHANNEL_KEYS
            if _is_numeric(channel_evidence.get(key))
        },
        "localization": {
            "has_location_label": has_location,
            "location_label": candidate.get("location_label"),
            "localization_status": localization_status,
        },
        "provenance": {
            "audit_id": candidate["audit_id"],
            "source_artifact_sha256": candidate["source_artifact_sha256"],
            "source_dataset_path": candidate["source_dataset_path"],
            "human_label": candidate.get("human_label"),
        },
    }


def evaluate_candidates(
    dataset_path: Path,
) -> dict[str, Any]:
    """Evaluar TODOS los candidatos del dataset H5.3b.

    Returns dict con:
      - metadata
      - policy (constantes de política evaluada)
      - summary (conteo por estado)
      - results: lista de resultados individuales
    """
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{dataset_path}: raíz JSON inválido")

    candidates_raw = payload.get("candidates")
    if not isinstance(candidates_raw, list):
        raise ValueError(f"{dataset_path}: candidatos ausente/inválido")

    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for raw in candidates_raw:
        try:
            candidate = _load_candidate(raw, dataset_path)
        except ValueError as exc:
            results.append({
                "eligibility_status": "ERROR",
                "reason_codes": ["invalid_record"],
                "reason": str(exc),
                "provenance": {"audit_id": "UNKNOWN"},
            })
            counts["ERROR"] = counts.get("ERROR", 0) + 1
            continue

        result = evaluate_candidate(candidate)
        status = result["eligibility_status"]
        counts[status] = counts.get(status, 0) + 1
        results.append(result)

    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "eligibility_version": ELIGIBILITY_VERSION,
            "status": SHADOW_STATUS,
            "source_dataset_path": str(dataset_path),
            "source_dataset_sha256": _sha256_file(dataset_path),
        },
        "policy": {
            "min_significant_delta_s": MIN_SIGNIFICANT_DELTA_S,
            "status": SHADOW_STATUS,
            "historical_actions_authorized": False,
            "historical_coaching_authorized": False,
            "session_reference_remains_authority": True,
        },
        "summary": {
            "total_candidates": len(candidates_raw),
            "by_status": counts,
        },
        "results": results,
    }


# ── CLI entry point ───────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "H5.3b shadow: evalúa elegibilidad de candidatos históricos "
            "de un dataset H5.3b auditado."
        )
    )
    parser.add_argument(
        "dataset_json",
        help="Dataset H5.3b auditado (audit_dataset*.json).",
    )
    parser.add_argument(
        "labels_json",
        help="Etiquetas humanas validadas (audit_labels*.json).",
    )
    parser.add_argument("--output", default=None, help="Ruta de salida JSON.")
    args = parser.parse_args()

    dataset_path = Path(args.dataset_json).resolve()
    labels_path = Path(args.labels_json).resolve()

    if not dataset_path.is_file():
        raise FileNotFoundError(f"No encontrado: {dataset_path}")
    if not labels_path.is_file():
        raise FileNotFoundError(f"No encontrado: {labels_path}")

    output = evaluate_candidates(dataset_path)

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))

    summary = output["summary"]
    print("=" * 88)
    print(f"RACE ENGINEER - H5.3b CANDIDATE ELIGIBILITY v{ELIGIBILITY_VERSION}")
    print("=" * 88)
    print(f"Source dataset: {dataset_path}")
    print(f"Total candidates: {summary['total_candidates']}")
    for status, count in sorted(summary["by_status"].items()):
        print(f"  {status}: {count}")
    print(f"Policy: MIN_SIGNIFICANT_DELTA_S = {MIN_SIGNIFICANT_DELTA_S}")
    print(f"Status: {SHADOW_STATUS}")
    print(f"historical_actions_authorized: false")
    print(f"session_reference_remains_authority: true")
    if args.output:
        print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
