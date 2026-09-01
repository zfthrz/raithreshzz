"""Backend-neutral orchestration for one structured lap comparison."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_validated_comparison_response(
    metadata: dict[str, Any],
    comparison: dict[str, Any],
    episode_catalog: list[dict[str, Any]],
    output_dir: str,
    *,
    get_episode_response: Callable[..., dict[str, Any]],
    get_ranker_response: Callable[..., dict[str, Any]],
    build_ranker_shadow: Callable[..., dict[str, Any]],
    apply_classifications: Callable[..., list[dict[str, Any]]],
    get_summary_response: Callable[..., dict[str, Any]],
    validate_response: Callable[..., list[str]],
    derive_classifications: Callable[..., list[dict[str, Any]]],
    emit: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Assemble the historical structured comparison contract.

    Model access, deterministic builders and validators are supplied by the
    caller. This function owns only sequencing, rejection propagation and the
    stable audit document.
    """
    episode_assessments = []
    attempt_counts = []
    episode_audit = []

    emit(
        "  Modo aislado v3.8.18: interpretación por episodio + "
        "ranker comparativo separado."
    )

    for episode in episode_catalog:
        validated = get_episode_response(
            metadata, comparison, episode, output_dir
        )
        attempt_counts.append(validated["attempts"])
        episode_audit.append({
            "episode_id": episode["episode_id"],
            "attempts": validated["attempts"],
            "fallback": validated.get("fallback"),
            "deterministic_repairs": validated.get("deterministic_repairs", {}),
            "pruned_hypothesis_indexes": validated.get(
                "pruned_hypothesis_indexes", []
            ),
            "original_validation_errors": validated.get(
                "original_validation_errors", []
            ),
        })

        if validated["status"] != "VALID":
            return {
                "status": "REJECTED",
                "attempts": max(attempt_counts or [1]),
                "response": None,
                "validation_errors": [
                    f"Episodio {episode['episode_id']}: {error}"
                    for error in validated["validation_errors"]
                ],
                "audit": {"episodes": episode_audit},
            }
        episode_assessments.append(validated["response"])

    emit("    Clasificando prioridad relativa entre episodios...")
    ranker = get_ranker_response(
        episode_catalog, episode_assessments, comparison, output_dir
    )
    attempt_counts.append(ranker["attempts"])
    if ranker["status"] != "VALID":
        return {
            "status": "REJECTED",
            "attempts": max(attempt_counts or [1]),
            "response": None,
            "validation_errors": [
                f"Ranker: {error}" for error in ranker["validation_errors"]
            ],
            "audit": {
                "episodes": episode_audit,
                "priority_ranking": {"attempts": ranker["attempts"]},
            },
        }

    try:
        deterministic_ranker_shadow = build_ranker_shadow(
            episode_catalog, ranker["response"]
        )
    except Exception as exc:
        deterministic_ranker_shadow = {"status": "ERROR", "error": str(exc)}

    classified_assessments = apply_classifications(
        episode_assessments, episode_catalog, ranker["response"]
    )
    summary = get_summary_response(
        classified_assessments, episode_catalog, comparison, output_dir
    )
    attempt_counts.append(summary["attempts"])
    priority_audit = {
        "attempts": ranker["attempts"],
        "deterministic_shadow": deterministic_ranker_shadow,
    }
    if summary["status"] != "VALID":
        return {
            "status": "REJECTED",
            "attempts": max(attempt_counts or [1]),
            "response": None,
            "validation_errors": [
                f"Resumen: {error}" for error in summary["validation_errors"]
            ],
            "audit": {
                "episodes": episode_audit,
                "priority_ranking": priority_audit,
                "summary": {"attempts": summary["attempts"]},
            },
        }

    structured = {
        "episode_assessments": classified_assessments,
        "comparison_observations": summary["response"]["comparison_observations"],
        "limitations": summary["response"]["limitations"],
        "conclusion": summary["response"]["conclusion"],
    }
    final_errors = validate_response(structured, episode_catalog)
    if final_errors:
        return {
            "status": "REJECTED",
            "attempts": max(attempt_counts or [1]),
            "response": None,
            "validation_errors": final_errors,
            "audit": {
                "episodes": episode_audit,
                "priority_ranking": priority_audit,
                "summary": {"attempts": summary["attempts"]},
            },
        }

    priority_audit.update({
        "ordered_episode_ids": ranker["response"]["ordered_episode_ids"],
        "priority_cut_rank": ranker["response"]["priority_cut_rank"],
        "no_actionable_start_rank": ranker["response"][
            "no_actionable_start_rank"
        ],
        "classifications": derive_classifications(
            ranker["response"], episode_catalog
        ),
    })
    return {
        "status": "VALID",
        "attempts": max(attempt_counts or [1]),
        "response": structured,
        "validation_errors": [],
        "audit": {
            "episodes": episode_audit,
            "priority_ranking": priority_audit,
            "summary": {
                "attempts": summary["attempts"],
                "fallback": summary.get("fallback"),
                "pruned_summary_items": summary.get("pruned_summary_items", {}),
                "deterministic_repairs": summary.get("deterministic_repairs", {}),
            },
        },
    }
