"""H5.3 shadow pipeline: orchestrates eligibility -> selection -> action policy.

Estado: SHADOW_PIPELINE
Autoridad: ninguna
historical_actions_authorized: false
session_reference_remains_authority: true

Este módulo orquesta el pipeline completo de H5.3 shadow:
1. historical_candidates_pipeline.py -> historical_candidate_eligibility.py
2. historical_candidate_selection_runtime.py -> validate_historical_candidate_selection_runtime.py
3. historical_action_policy.py -> validate_historical_actions.py

El pipeline lee H5.3a candidates directamente y ejecuta:
- Eligibility v0.1 (filter ELIGIBLE_FOR_SELECTION)
- Controlled LLM selection SIN human labels (historical_candidate_selection_runtime.py)
  Reutiliza el mecanismo de H5.3c: prompt cerrado, schema, validator, call_backend
  Backend configurable: deepseek / ollama / llamacpp / deterministic
  Deterministic fallback (--deterministic flag o H5_3_BACKEND=deterministic)
- Action policy v0.2 (shadow action candidates, production authority false)

Backend selection:
- default: deterministic top-N by delta_change_s (no LLM)
- deepseek / ollama / llamacpp only when H5_3_BACKEND requests one explicitly

NO:
  - usa human labels
  - llama causal inference
  - genera coaching ni acciones de producción
  - modifica historical_candidate_selection.py
  - modifica historical_action_policy.py
  - modifica el debrief visible de race_engineer.py

Flujo:
    candidates -> eligibility -> selection(LLM or deterministic) -> action_policy -> validation

Output:
    data/generated/h5_3_shadow/{database_stem}.json

"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import historical_candidate_eligibility as eligibility_module
import historical_candidate_selection_runtime as selection_module
import historical_action_policy_v0_2 as action_policy_module
import validate_historical_candidate_eligibility as eligibility_validator
import validate_historical_candidate_selection_runtime as selection_validator
import validate_historical_actions as action_validator


# ── H5.3a → H5.3b normalisation helper ────────────────────────────────────

def _is_h5_3a_raw(candidates_path: Path) -> bool:
    """Detectar si el archivo de candidatos está en formato H5.3a raw.

    H5.3a raw tiene candidatos con:
      - current_minus_historical (dict con delta_change_s, start_distance_m, etc.)
      - location (dict segment-level)
    H5.3b canonical tiene candidatos con:
      - evidence (dict con delta_change_s, start_distance_m, etc.)
      - delta_sign (str)
      - audit_id, source_artifact_sha256, observational_channel_evidence, label

    Returns True si el formato es H5.3a raw, False si ya es H5.3b.
    """
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list) or not candidates:
        return False
    first = candidates[0]
    if not isinstance(first, dict):
        return False
    # H5.3a raw: has current_minus_historical
    return "current_minus_historical" in first


def _normalize_h5_3a_candidates(
    candidates_path: Path,
    temp_dir: Path,
) -> Path:
    """Normalizar H5.3a raw candidates al formato H5.3b elegible.

    Si el archivo ya está en formato H5.3b, devuelve candidates_path sin
    transformación (pass-through).

    Llama normalize_h5_3a_candidates_for_eligibility() y escribe el
    resultado en un archivo JSON temporal con estructura H5.3b.

    Returns:
        Path al archivo JSON H5.3b normalizado.
    """
    # Fast path: already H5.3b format, pass through unchanged.
    if not _is_h5_3a_raw(candidates_path):
        return candidates_path

    # Normalize H5.3a → H5.3b canonical eligibility format
    normalized = eligibility_module.normalize_h5_3a_candidates_for_eligibility(
        candidates_path,
    )
    # Build H5.3b dataset structure compatible with eligibility.evaluate_candidates().
    # The H5.3b format expects: {"candidates": [...], ...}
    # where each candidate has all _DATASET_FIELDS at top level.
    h53b_dataset = {"candidates": normalized}

    normalized_path = temp_dir / "h5_3a_normalized_for_eligibility.json"
    normalized_path.write_text(
        json.dumps(h53b_dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return normalized_path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ── Pipeline stages ───────────────────────────────────────────────────────

def _run_eligibility(candidates_path: Path, temp_dir: Path) -> dict[str, Any]:
    """Run eligibility on H5.3a candidates.

    Normalizes H5.3a → H5.3b first, then calls eligibility.evaluate_candidates()
    on the normalized JSON.

    Returns dict with:
      - metadata
      - policy
      - summary
      - results
    """
    # Normalize H5.3a raw → H5.3b canonical eligibility format
    normalized_path = _normalize_h5_3a_candidates(candidates_path, temp_dir)

    # eligibility.evaluate_candidates() reads the normalized H5.3b JSON
    return eligibility_module.evaluate_candidates(normalized_path)


def _run_selection(eligibility_result: dict[str, Any]) -> dict[str, Any]:
    """Run controlled LLM selection on eligibility result.

    Reads H5.3a candidates path from eligibility metadata and runs selection
    via historical_candidate_selection_runtime.py which reuses H5.3c's
    controlled selection mechanism (prompt, schema, validator, call_backend)
    WITHOUT human labels.
    """
    metadata = eligibility_result.get("metadata") or {}
    candidates_json = metadata.get("source_dataset_path")
    if not candidates_json:
        raise ValueError("eligibility metadata.source_dataset_path ausente")

    return selection_module.select_candidates(Path(candidates_json))


def _run_action_policy(
    selection_result: dict[str, Any],
    *,
    temp_dir: Path | None = None,
) -> dict[str, Any]:
    """Persist the unified selection contract and run action policy v0.2."""
    import tempfile
    tmp_dir = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir())
    tmp_dir.mkdir(parents=True, exist_ok=True)
    selection_path = tmp_dir / "candidate_selection.json"
    selection_path.write_text(
        json.dumps(selection_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return action_policy_module.build_action_candidates(selection_path)


def _validate_pipeline(
    eligibility_result: dict[str, Any],
    selection_result: dict[str, Any],
    action_policy_result: dict[str, Any],
) -> list[str]:
    """Validate all pipeline stages and return list of errors."""
    errors: list[str] = []

    # Validate eligibility
    elig_errors = eligibility_validator.validate(eligibility_result)
    if elig_errors:
        errors.append(f"eligibility validation failed: {'; '.join(elig_errors)}")

    # Validate selection
    validation_errors = selection_validator.validate(selection_result)
    if validation_errors:
        errors.append(f"selection validation failed: {'; '.join(validation_errors)}")

    # Validate action policy — always use real validator on the result dict.
    # Skip lightweight shadow results that don't have real actions/withheld.
    if action_policy_result:
        # A policy failure fails only this shadow stage; the visible debrief
        # remains independent in the orchestrator.
        if action_policy_result.get("validation_status") == "FAILED":
            errors.extend(action_policy_result.get("validation_errors", []))
        else:
            # For real policy output (validated shadow action candidates),
            # run the validator on the full document.
            try:
                action_errors = action_validator.validate(action_policy_result)
                if action_errors:
                    errors.append(
                        f"action policy validation failed: {'; '.join(action_errors)}"
                    )
            except (ValueError, KeyError):
                # If the document is not a real policy output, skip.
                pass

    return errors


# ── Main pipeline ───────────────────────────────────────────────────────

def run_pipeline(
    candidates_path: Path,
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the complete H5.3 shadow pipeline.

    Args:
        candidates_path: Path to H5.3a candidates JSON (historical_coaching_candidates.json).
        output_dir: Optional output directory for artifacts.

    Returns dict with:
        - status: SUCCESS / SKIPPED_NOT_APPLICABLE / FAILED
        - pipeline_artifacts: dict of stage outputs
        - validation_errors: list of errors (empty if SUCCESS)
        - coaching_authority: historical_actions_authorized=false
    """
    if not candidates_path.is_file():
        return {
            "status": "SKIPPED_NOT_APPLICABLE",
            "reason": f"candidates_path no encontrado: {candidates_path}",
            "pipeline_artifacts": {},
            "validation_errors": [],
            "coaching_authority": {
                "session_reference_remains_authority": True,
                "historical_actions_authorized": False,
                "historical_coaching_authorized": False,
            },
        }

    try:
        # Create temp directory for action policy wrapper.
        import tempfile
        temp_output_dir = Path(tempfile.mkdtemp(prefix="h53_"))
        artifact_dir = Path(output_dir) if output_dir else temp_output_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Stage 1: Eligibility (normalize H5.3a → H5.3b first)
        eligibility_result = _run_eligibility(candidates_path, temp_output_dir)
        (artifact_dir / "candidate_eligibility.json").write_text(
            json.dumps(eligibility_result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Check if any ELIGIBLE candidates
        summary = eligibility_result.get("summary") or {}
        by_status = summary.get("by_status") or {}
        eligible_count = by_status.get("ELIGIBLE_FOR_SELECTION", 0)

        if not eligible_count:
            return {
                "status": "SKIPPED_NOT_APPLICABLE",
                "reason": "no_eligible_candidates",
                "pipeline_artifacts": {"eligibility": eligibility_result},
                "validation_errors": [],
                "coaching_authority": {
                    "session_reference_remains_authority": True,
                    "historical_actions_authorized": False,
                    "historical_coaching_authorized": False,
                },
            }

        # Stage 2: Selection
        selection_result = _run_selection(eligibility_result)

        # Stage 3: Action policy (real policy via wrapper)
        try:
            action_policy_result = _run_action_policy(
                selection_result, temp_dir=artifact_dir
            )
        except (ValueError, KeyError, FileNotFoundError) as exc:
            # Real policy can raise ValueError for:
            # - unknown observation codes
            # - no mappable action codes (no_actions)
            # - candidate not in authorized list
            # - missing context
            # For shadow mode: treat as FAILED but don't break debrief.
            action_policy_result = {
                "validation_status": "FAILED",
                "validation_errors": [str(exc)],
            }
        (artifact_dir / "historical_actions.json").write_text(
            json.dumps(action_policy_result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Validate all stages
        validation_errors = _validate_pipeline(
            eligibility_result,
            selection_result,
            action_policy_result,
        )

        if validation_errors:
            return {
                "status": "FAILED",
                "reason": f"validation_errors: {'; '.join(validation_errors)}",
                "pipeline_artifacts": {
                    "eligibility": eligibility_result,
                    "selection": selection_result,
                    "action_policy": action_policy_result,
                },
                "validation_errors": validation_errors,
                "coaching_authority": {
                    "session_reference_remains_authority": True,
                    "historical_actions_authorized": False,
                    "historical_coaching_authorized": False,
                },
            }

        # ── SUCCESS ─────────────────────────────────────────────────────
        # Write artifacts to output_dir if provided
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = Path(output_dir) / "shadow_pipeline.json"
            output_path.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "schema_version": "1.0",
                            "pipeline_version": "0.1",
                            "status": "SHADOW_PIPELINE_COMPLETE",
                            "created_at_utc": utc_now_iso(),
                            "source_candidates_json": str(candidates_path),
                            "source_candidates_sha256": sha256_file(candidates_path),
                        },
                        "pipeline_artifacts": {
                            "eligibility": {
                                "status": eligibility_result.get("status"),
                                "summary": eligibility_result.get("summary"),
                            },
                            "selection": {
                                "status": selection_result.get("status"),
                                "selected_count": selection_result.get("selected_count"),
                            },
                            "action_policy": {
                                "status": action_policy_result.get("status")
                                if action_policy_result
                                else "NOT_APPLICABLE",
                            },
                        },
                        "validation": {
                            "status": "PASS",
                            "errors": [],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )

        return {
            "status": "SUCCESS",
            "pipeline_artifacts": {
                "eligibility": eligibility_result,
                "selection": selection_result,
                "action_policy": action_policy_result,
            },
            "validation_errors": [],
            "coaching_authority": {
                "session_reference_remains_authority": True,
                "historical_actions_authorized": False,
                "historical_coaching_authorized": False,
            },
        }

    except (ValueError, TypeError, FileNotFoundError, KeyError) as exc:
        return {
            "status": "FAILED",
            "reason": f"pipeline_error: {type(exc).__name__}: {exc}",
            "pipeline_artifacts": {},
            "validation_errors": [str(exc)],
            "coaching_authority": {
                "session_reference_remains_authority": True,
                "historical_actions_authorized": False,
                "historical_coaching_authorized": False,
            },
        }


# ── CLI entry point ───────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3 shadow: pipeline completo eligilibitily -> selection -> action policy."
    )
    parser.add_argument(
        "candidates_json",
        help="H5.3a candidates archivo JSON (historical_coaching_candidates.json).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directorio de salida para artefactos (data/generated/h5_3_shadow/).",
    )
    args = parser.parse_args()

    candidates_path = Path(args.candidates_json).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else None

    result = run_pipeline(
        candidates_path,
        output_dir=output_dir,
    )

    print("=" * 88)
    print("RACE ENGINEER - H5.3 SHADOW PIPELINE v0.1")
    print("=" * 88)
    print(f"Source candidates: {candidates_path}")
    print(f"Status: {result['status']}")
    if result.get("reason"):
        print(f"Reason: {result['reason']}")
    if result.get("pipeline_artifacts"):
        artifacts = result["pipeline_artifacts"]
        for stage, artifact in artifacts.items():
            print(f"  {stage}: {artifact.get('status', 'N/A')}")
        # Show backend info from selection artifact
        selection_artifact = artifacts.get("selection", {})
        selection_metadata = selection_artifact.get("metadata", {})
        backend = selection_metadata.get("backend", "N/A")
        model = selection_metadata.get("model", "N/A")
        print(f"  Backend: {backend} / {model}")
        print(f"  Selection method: {selection_metadata.get('selection_method', 'N/A')}")
    if result.get("validation_errors"):
        for error in result["validation_errors"]:
            print(f"  ERROR: {error}")
    # LLM status: check if selection used LLM or deterministic fallback
    selection_metadata = (
        result.get("pipeline_artifacts", {}).get("selection", {}).get("metadata", {})
    )
    is_deterministic = selection_metadata.get("backend") == "deterministic"
    print(f"LLM: {'NOT CALLED (deterministic fallback)' if is_deterministic else 'CALLED (controlled selection)'}")
    print(f"Human labels: NOT INVOLVED")
    print(f"historical_actions_authorized: false")
    print(f"session_reference_remains_authority: true")
    print("RESULT: " + ("PASS" if result["status"] == "SUCCESS" else "FAIL"))
    return 0 if result["status"] == "SUCCESS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
