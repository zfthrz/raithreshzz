"""Fail-closed deterministic providers for the comparison response pipeline."""

from __future__ import annotations

from collections.abc import Callable


def build_episode_response(
    episode,
    *,
    build_fallback: Callable,
    validate_response: Callable,
    emit: Callable[[str], None] = print,
):
    episode_id = episode["episode_id"]
    response = build_fallback(episode)
    if response is not None:
        errors = validate_response(response, episode)
        if not errors:
            emit(
                f"    Episodio {episode_id}: modo deterministic-first "
                "(default); sin llamada LLM."
            )
            return {
                "status": "VALID",
                "attempts": 0,
                "response": response,
                "validation_errors": [],
                "deterministic": True,
                "deterministic_first": True,
                "fallback": "DETERMINISTIC_GROUNDED_EPISODE_TEXT",
            }
    return {
        "status": "REJECTED",
        "attempts": 0,
        "response": None,
        "validation_errors": [
            "deterministic-first: el episodio es genuinamente interpretativo "
            "y Python no puede reconstruir el contrato de forma segura"
        ],
    }


def build_ranker_response(
    episode_catalog,
    *,
    build_ranker: Callable,
    validate_response: Callable,
    emit: Callable[[str], None] = print,
):
    try:
        response = build_ranker(episode_catalog)
    except Exception as exc:
        return {
            "status": "REJECTED",
            "attempts": 0,
            "response": None,
            "validation_errors": [f"Ranker determinista D2.9: {exc}"],
        }
    errors = validate_response(response, episode_catalog)
    if errors:
        return {
            "status": "REJECTED",
            "attempts": 0,
            "response": None,
            "validation_errors": [
                f"Ranker determinista D2.9: {error}" for error in errors
            ],
        }
    emit(
        "    Ranker: modo determinista D2.9 (product policy); "
        "sin llamada LLM."
    )
    return {
        "status": "VALID",
        "attempts": 0,
        "response": response,
        "validation_errors": [],
        "deterministic": True,
        "deterministic_first": True,
        "ranker_source": "D2_9_PRODUCT_POLICY",
    }


def build_summary_response(
    episode_assessments,
    episode_catalog,
    *,
    build_summary: Callable,
    emit: Callable[[str], None] = print,
):
    response = build_summary(episode_assessments, episode_catalog)
    if response is None:
        return {
            "status": "REJECTED",
            "attempts": 0,
            "response": None,
            "validation_errors": [
                "deterministic-first: no hay resumen determinista disponible"
            ],
        }
    emit("    Resumen: modo deterministic-first (default); sin llamada LLM.")
    return {
        "status": "VALID",
        "attempts": 0,
        "response": response,
        "validation_errors": [],
        "deterministic": True,
        "deterministic_first": True,
    }
