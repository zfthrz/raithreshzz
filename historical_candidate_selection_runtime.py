"""H5.3 runtime shadow selector — controlled LLM selection WITHOUT human labels.

Estado: RUNTIME_LLM_SELECTOR
Autoridad: ninguna
historical_actions_authorized: false
session_reference_remains_authority: true

Reutiliza el mecanismo de H5.3c (historical_candidate_selection.py) adaptado
para runtime, eliminando la dependencia de human labels.

Flujo:
1. Cargar candidatos H5.3a (historical_coaching_candidates.json)
2. Filtrar ELIGIBLE_FOR_SELECTION (delta_change_s > MIN_SIGNIFICANT_DELTA_S)
3. Construir authorized evidence SIN human labels (todos los ELIGIBLE)
4. Llamar al LLM con prompt cerrado, schema y validator de H5.3c
5. Validar respuesta con validator compartido
6. Output compatible con H5.3c contract:
   - status == "VALIDATED_HISTORICAL_CANDIDATE_SELECTION"
   - authorized_candidates
   - llm_selection.selected_candidates
   - selected_evidence

Backend configurable:
- H5_3_BACKEND (deepseek / ollama / llamacpp / deterministic)
- Default: deterministic (sin llamadas LLM)
- Los backends LLM requieren selección explícita mediante H5_3_BACKEND

Reutilización de H5.3c:
- response_schema()
- system_prompt()
- user_prompt()
- parse_response()
- validate_response()
- call_backend()

NO:
- usa human labels
- genera coaching ni acciones
- llama causal inference
- modifica historical_candidate_selection.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Reutilización directa del módulo H5.3c ──────────────────────────────────

import historical_candidate_selection as h53c


# ── Policy constants ──────────────────────────────────────────────────────

SELECTION_VERSION = "0.2"
SCHEMA_VERSION = "1.0"

MAX_SELECTED_CANDIDATES = h53c.MAX_SELECTED_CANDIDATES
MIN_SIGNIFICANT_DELTA_S = 0.08  # mismo threshold que eligibiltiy v0.1

# Backend configurable via environment variable.
SUPPORTED_BACKENDS = ("deepseek", "ollama", "llamacpp", "deterministic")
DEFAULT_BACKEND = "deterministic"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_numeric(value: Any) -> bool:
    """Return True for int/float (but NOT bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _get_backend() -> str:
    """Read backend from environment variable."""
    backend = os.environ.get("H5_3_BACKEND", "").strip() or DEFAULT_BACKEND
    if backend not in SUPPORTED_BACKENDS:
        backend = DEFAULT_BACKEND
    return backend


# ── Runtime evidence builder (NO human labels) ──────────────────────────────

def _signed_observation(value: Any, lower: str, higher: str) -> str | None:
    """Determine signed observation from numeric value."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return lower
    if number > 0:
        return higher
    return None


def build_runtime_evidence(
    candidates_path: Path,
) -> dict[str, Any]:
    """Construir authorized evidence para runtime SIN human labels.

    Reutiliza el resultado explícito de eligibility.evaluate_candidates()
    en lugar de recalcular eligibility por su cuenta.

    Args:
        candidates_path: Path al archivo H5.3a/H5.3b candidates JSON.

    Returns dict con:
        - contract: shadow/historical_actions_authorized=false
        - authorized_candidate_count: cantidad ELIGIBLE_FOR_SELECTION
        - authorized_limitation_codes: de H5.3c ALLOWED_LIMITATIONS
        - required_limitation_codes: de H5.3c REQUIRED_LIMITATIONS
        - candidates: lista de candidatos ELIGIBLE con authorized_observations
    """
    import historical_candidate_eligibility as elig_mod

    # Consume the EXPLICIT eligibility result (calculated ONCE by eligibility)
    elig_result = elig_mod.evaluate_candidates(candidates_path)
    results = elig_result.get("results", [])

    # Build a map from audit_id -> provenance for ELIGIBLE candidates
    eligible_by_audit_id: dict[str, dict[str, Any]] = {}
    for result in results:
        if result.get("eligibility_status") != "ELIGIBLE_FOR_SELECTION":
            continue
        audit_id = result.get("provenance", {}).get("audit_id", "UNKNOWN")
        if audit_id == "UNKNOWN":
            continue
        eligible_by_audit_id[audit_id] = result

    if not eligible_by_audit_id:
        return {
            "contract": {
                "candidates_are_shadow": True,
                "historical_actions_authorized": False,
                "causal_claims_authorized": False,
                "free_text_authorized": False,
            },
            "authorized_candidate_count": 0,
            "authorized_limitation_codes": sorted(h53c.ALLOWED_LIMITATIONS),
            "required_limitation_codes": list(h53c.REQUIRED_LIMITATIONS),
            "candidates": [],
        }

    # Build authorized evidence records from ELIGIBLE candidates
    candidates_out: list[dict[str, Any]] = []
    for result in results:
        if result.get("eligibility_status") != "ELIGIBLE_FOR_SELECTION":
            continue

        audit_id = result.get("provenance", {}).get("audit_id", "UNKNOWN")
        if audit_id == "UNKNOWN":
            continue

        # Pull delta_change_s from the explicit eligibility result
        delta_change_s = result.get("delta_change_s")
        if not _is_numeric(delta_change_s) or delta_change_s <= 0:
            continue

        # Get original candidate data from the eligibility result
        candidate_context = result.get("candidate_context", {})
        geometry = result.get("geometry", {})
        channel_evidence = result.get("observational_channel_evidence", {})

        # Build authorized observations from deterministic evidence
        observations: list[str] = []

        # time_loss / time_gain (basado en delta_change_s > 0)
        if delta_change_s > 0:
            observations.append("time_loss")
        else:
            observations.append("time_gain")

        # Speed -> current_speed_lower / current_speed_higher
        speed = _signed_observation(
            channel_evidence.get("speed_delta_avg"),
            "current_speed_lower",
            "current_speed_higher",
        )
        if speed:
            observations.append(speed)

        # Throttle -> current_throttle_lower / current_throttle_higher
        throttle = _signed_observation(
            channel_evidence.get("throttle_delta_avg"),
            "current_throttle_lower",
            "current_throttle_higher",
        )
        if throttle:
            observations.append(throttle)

        # Brake -> current_brake_lower / current_brake_higher
        brake = _signed_observation(
            channel_evidence.get("brake_delta_avg"),
            "current_brake_lower",
            "current_brake_higher",
        )
        if brake:
            observations.append(brake)

        if not observations:
            continue

        candidates_out.append({
            "candidate_id": audit_id,
            "source_candidate_id": audit_id,
            "context": {
                "track": candidate_context.get("track"),
                "track_layout": candidate_context.get("track_layout"),
                "vehicle_variant": candidate_context.get("vehicle_variant"),
                "car_name_raw": candidate_context.get("car_name_raw"),
            },
            "delta_sign": result.get("delta_sign"),
            "location_label": result.get("localization", {}).get("location_label"),
            "start_distance_m": geometry.get("start_distance_m"),
            "end_distance_m": geometry.get("end_distance_m"),
            "delta_change_s": float(delta_change_s),
            "speed_delta_avg": channel_evidence.get("speed_delta_avg"),
            "throttle_delta_avg": channel_evidence.get("throttle_delta_avg"),
            "brake_delta_avg": channel_evidence.get("brake_delta_avg"),
            "authorized_observations": observations,
        })

    return {
        "contract": {
            "candidates_are_shadow": True,
            "historical_actions_authorized": False,
            "causal_claims_authorized": False,
            "free_text_authorized": False,
        },
        "authorized_candidate_count": len(candidates_out),
        "authorized_limitation_codes": sorted(h53c.ALLOWED_LIMITATIONS),
        "required_limitation_codes": list(h53c.REQUIRED_LIMITATIONS),
        "candidates": candidates_out,
    }


# ── LLM selector (reutiliza H5.3c) ──────────────────────────────────────

def _call_backend(backend: str, system: str, user: str) -> tuple[str, str]:
    """Llamar al backend configurado. Reutiliza call_backend de H5.3c."""
    return h53c.call_backend(backend, system, user)


def _parse_response(raw_content: str) -> dict[str, Any]:
    """Parsear respuesta del LLM. Reutiliza parse_response de H5.3c."""
    return h53c.parse_response(raw_content)


def _validate_response(response: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    """Validar respuesta del LLM. Reutiliza validate_response de H5.3c."""
    return h53c.validate_response(response, evidence)


def generate_llm_selection(
    evidence: dict[str, Any],
    *,
    backend: str = "deepseek",
    max_attempts: int = h53c.MAX_VALIDATION_ATTEMPTS,
) -> dict[str, Any]:
    """Generar selección LLM controlada sin human labels.

    Reutiliza el prompt cerrado, schema y validator de H5.3c.

    Args:
        evidence: authorized evidence from build_runtime_evidence().
        backend: backend a usar (deepseek / ollama / llamacpp).
        max_attempts: máximo intentos de validación.

    Returns dict con selected_candidates y limitation_codes.

    Raises:
        RuntimeError: si el LLM no produce una selección válida.
    """
    system = h53c.system_prompt()
    prompt = h53c.user_prompt(evidence)

    errors: list[str] | None = None
    model = "unknown"

    for attempt in range(1, max_attempts + 1):
        try:
            raw, model = _call_backend(backend, system, prompt)
        except ImportError as exc:
            errors = [f"Backend no disponible: {exc}"]
            continue

        try:
            response = _parse_response(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            errors = [str(exc)]
            continue

        errors = _validate_response(response, evidence)
        if not errors:
            return response

    raise RuntimeError(
        "El LLM no produjo una selección de candidatos válida: "
        + "; ".join(errors or [])
    )


# ── Runtime selection ──────────────────────────────────────────────────────

def _build_selection_document(
    candidates_path: Path,
    evidence: dict[str, Any],
    response: dict[str, Any],
    *,
    backend: str,
) -> dict[str, Any]:
    """Build the single runtime-selection contract used by every backend."""
    by_id = {
        candidate["candidate_id"]: candidate
        for candidate in evidence["candidates"]
    }
    selected = [
        dict(by_id[item["candidate_id"]])
        for item in response["selected_candidates"]
    ]
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "candidate_selection_version": SELECTION_VERSION,
            "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
            "source_candidates_json": str(candidates_path),
            "source_candidates_sha256": sha256_file(candidates_path),
            "created_at_utc": utc_now_iso(),
            "selection_method": (
                "deterministic_top_n"
                if backend == "deterministic"
                else "controlled_llm_runtime"
            ),
            "backend": backend,
            "no_human_labels_involved": True,
            "no_llm_involved": backend == "deterministic",
            "policy": {
                "max_selected_candidates": MAX_SELECTED_CANDIDATES,
            },
        },
        "status": "VALIDATED_HISTORICAL_CANDIDATE_SELECTION",
        "authorized_candidates": evidence["candidates"],
        "llm_selection": response,
        "selected_evidence": selected,
        "selected_count": len(selected),
        "limitations": response["limitation_codes"],
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_reference_is_observational": True,
            "historical_actions_authorized": False,
        },
    }

def select_candidates(
    candidates_path: Path,
    *,
    backend: str | None = None,
    max_selected: int = MAX_SELECTED_CANDIDATES,
) -> dict[str, Any]:
    """Seleccionar candidatos ELIGIBLE mediante controlled LLM selection.

    Si backend == "deterministic", usa _deterministic_top_n() directamente.
    De lo contrario, construye authorized evidence y llama al LLM selector.

    Flujo:
    1. Cargar candidatos H5.3a
    2. Filtrar ELIGIBLE (delta_change_s > threshold)
    3. Si deterministic: top-N por delta_change_s
    4. Si no: construir authorized evidence SIN human labels, llamar al LLM
    5. Construir output compatible con H5.3c contract

    Args:
        candidates_path: Path al archivo H5.3a candidates JSON.
        backend: Backend a usar (default: from H5_3_BACKEND env).
        max_selected: máximo candidatos a seleccionar (default: 3).

    Returns dict con:
        - metadata (schema, version, provenance)
        - status: "VALIDATED_HISTORICAL_CANDIDATE_SELECTION" o "DETERMINISTIC_FALLBACK"
        - authorized_candidates: candidatos ELIGIBLE con authorized_observations
        - llm_selection: selected_candidates + limitation_codes
        - selected_evidence: candidatos seleccionados con evidencia completa
        - coaching_authority
    """
    if backend is None:
        backend = _get_backend()

    # Deterministic is the safe runtime default: no API/local-model call.
    if backend == "deterministic":
        return _deterministic_top_n(
            candidates_path,
            max_candidates=max_selected,
        )

    # Stage 1: Build runtime evidence (no human labels)
    evidence = build_runtime_evidence(candidates_path)

    if not evidence["authorized_candidate_count"]:
        raise ValueError("build_runtime_evidence: no authorized candidates")

    # Stage 2: Call LLM selector (reutiliza prompt/schema/validator de H5.3c)
    response = generate_llm_selection(evidence, backend=backend)

    # Validate response
    errors = _validate_response(response, evidence)
    if errors:
        raise ValueError(
            "Respuesta de candidatos inválida: " + "; ".join(errors)
        )

    return _build_selection_document(
        candidates_path,
        evidence,
        response,
        backend=backend,
    )


# ── Deterministic fallback (backward-compatible audit mode) ──────────────────

def _deterministic_top_n(
    candidates_path: Path,
    *,
    max_candidates: int = MAX_SELECTED_CANDIDATES,
) -> dict[str, Any]:
    """Select deterministic top-N using the same contract as LLM backends."""
    evidence = build_runtime_evidence(candidates_path)
    candidates = sorted(
        evidence["candidates"],
        key=lambda candidate: float(candidate["delta_change_s"]),
        reverse=True,
    )
    selected = candidates[:max_candidates]
    if not selected:
        raise ValueError("build_runtime_evidence: no authorized candidates")
    response = {
        "selected_candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "significance": "primary" if index == 0 else "secondary",
                "observation_codes": candidate["authorized_observations"][:4],
            }
            for index, candidate in enumerate(selected)
        ],
        "limitation_codes": list(h53c.REQUIRED_LIMITATIONS),
    }
    errors = _validate_response(response, evidence)
    if errors:
        raise ValueError("Selección determinista inválida: " + "; ".join(errors))
    return _build_selection_document(
        candidates_path,
        evidence,
        response,
        backend="deterministic",
    )


# ── CLI entry point ──────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3 runtime shadow selector: controlled LLM selection WITHOUT human labels."
    )
    parser.add_argument(
        "candidates_json",
        help="H5.3a candidates archivo JSON (historical_coaching_candidates.json).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Ruta de salida JSON.",
    )
    parser.add_argument(
        "--backend",
        choices=SUPPORTED_BACKENDS,
        default=None,
        help=f"Backend a usar (default: env H5_3_BACKEND, or {DEFAULT_BACKEND}).",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=MAX_SELECTED_CANDIDATES,
        help=f"Máximo candidatos (default {MAX_SELECTED_CANDIDATES}).",
    )
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Usar fallback determinista (sin LLM, para audit).",
    )
    args = parser.parse_args()

    candidates_path = Path(args.candidates_json).resolve()

    if not candidates_path.is_file():
        raise FileNotFoundError(f"No encontrado: {candidates_path}")

    backend = args.backend or _get_backend()

    if args.deterministic or backend == "deterministic":
        result = _deterministic_top_n(
            candidates_path,
            max_candidates=args.max,
        )
    else:
        result = select_candidates(
            candidates_path,
            backend=backend,
            max_selected=args.max,
        )

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Output: {output_path}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    print("=" * 88)
    print(f"RACE ENGINEER - H5.3 RUNTIME SELECTOR v{SELECTION_VERSION}")
    print("=" * 88)
    print(f"Source candidates: {candidates_path}")
    print(f"Backend: {backend}")
    print(f"Status: {result.get('status', 'N/A')}")
    print(f"LLM: {'NOT CALLED' if args.deterministic or backend == 'deterministic' else 'CALLED'}")
    print(f"Human labels: NOT INVOLVED")
    print(f"historical_actions_authorized: false")
    print(f"session_reference_remains_authority: true")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
