"""Backend-independent validation for an assembled comparison response."""

from __future__ import annotations

from deterministic_coaching import safe_int
from deterministic_episode_validation import validate_episode_steering_contract
from deterministic_summary_validation import (
    grounding_context_from_episodes,
    validate_grounded_text,
    validate_grounded_text_list,
    validate_speed_not_action_target,
    validate_text_list,
)
from deterministic_text_validation import text_contains_forbidden_numeric_content


ALLOWED_CLASSIFICATIONS = {"PRIORITARIO", "SECUNDARIO", "NO_ACCIONABLE"}


def validate_comparison_response(response, episode_catalog):
    """Validate the stable assembled-comparison schema and grounding contract."""
    errors = []
    expected_root = {
        "episode_assessments",
        "comparison_observations",
        "limitations",
        "conclusion",
    }
    actual_root = set(response.keys())
    missing_root = expected_root - actual_root
    extra_root = actual_root - expected_root
    if missing_root:
        errors.append("Faltan claves raíz: " + ", ".join(sorted(missing_root)))
    if extra_root:
        errors.append("Claves raíz no permitidas: " + ", ".join(sorted(extra_root)))

    assessments = response.get("episode_assessments")
    if not isinstance(assessments, list):
        errors.append("episode_assessments debe ser lista.")
        assessments = []
    expected_ids = [episode["episode_id"] for episode in episode_catalog]
    episode_by_id = {
        safe_int(episode.get("episode_id")): episode
        for episode in episode_catalog
        if safe_int(episode.get("episode_id")) is not None
    }
    comparison_channels, comparison_speed_context = grounding_context_from_episodes(
        episode_catalog
    )
    actual_ids = []

    for index, assessment in enumerate(assessments):
        if not isinstance(assessment, dict):
            errors.append(f"episode_assessments[{index}] no es objeto.")
            continue
        expected = {
            "episode_id",
            "classification",
            "interpretation",
            "hypotheses",
            "recommendation",
        }
        actual = set(assessment.keys())
        if actual != expected:
            missing = expected - actual
            extra = actual - expected
            if missing:
                errors.append(
                    f"Episodio índice {index}: faltan claves "
                    + ", ".join(sorted(missing))
                )
            if extra:
                errors.append(
                    f"Episodio índice {index}: sobran claves "
                    + ", ".join(sorted(extra))
                )
        episode_id = safe_int(assessment.get("episode_id"))
        if episode_id is None:
            errors.append(f"Episodio índice {index}: episode_id inválido.")
        else:
            actual_ids.append(episode_id)
        episode = episode_by_id.get(episode_id)
        if isinstance(episode, dict):
            allowed_channels = set(episode.get("action_channels", []) or [])
            speed_context = bool(episode.get("concurrent_speed_events")) or bool(
                episode.get("speed_propagation")
            )
        else:
            allowed_channels = set()
            speed_context = False

        classification = assessment.get("classification")
        if classification not in ALLOWED_CLASSIFICATIONS:
            errors.append(
                f"Episodio {episode_id}: classification inválida: {classification}"
            )
        interpretation = assessment.get("interpretation")
        if not isinstance(interpretation, str):
            errors.append(f"Episodio {episode_id}: interpretation debe ser texto.")
        else:
            if text_contains_forbidden_numeric_content(interpretation):
                errors.append(f"Episodio {episode_id}: interpretation contiene cifras.")
            validate_grounded_text(
                interpretation,
                f"Episodio {episode_id}.interpretation",
                allowed_channels,
                speed_context,
                errors,
            )
        hypotheses = assessment.get("hypotheses")
        validate_text_list(hypotheses, f"Episodio {episode_id}.hypotheses", errors)
        validate_grounded_text_list(
            hypotheses,
            f"Episodio {episode_id}.hypotheses",
            allowed_channels,
            speed_context,
            errors,
        )
        recommendation = assessment.get("recommendation")
        if not isinstance(recommendation, str):
            errors.append(f"Episodio {episode_id}: recommendation debe ser texto.")
        else:
            if text_contains_forbidden_numeric_content(recommendation):
                errors.append(f"Episodio {episode_id}: recommendation contiene cifras.")
            field = f"Episodio {episode_id}.recommendation"
            validate_grounded_text(
                recommendation, field, allowed_channels, speed_context, errors
            )
            validate_speed_not_action_target(recommendation, field, errors)
            validate_episode_steering_contract(
                recommendation, episode, errors, field_name=field
            )

    if len(assessments) != len(episode_catalog):
        errors.append(
            f"Cantidad de episodios incorrecta: esperados={len(episode_catalog)} recibidos={len(assessments)}"
        )
    if len(actual_ids) != len(set(actual_ids)):
        errors.append("Hay episode_id duplicados.")
    if sorted(actual_ids) != sorted(expected_ids):
        errors.append(
            f"Los episode_id no coinciden con los esperados: esperados={expected_ids} recibidos={actual_ids}"
        )

    for key in ("comparison_observations", "limitations"):
        value = response.get(key)
        validate_text_list(value, key, errors)
        validate_grounded_text_list(
            value, key, comparison_channels, comparison_speed_context, errors
        )
    conclusion = response.get("conclusion")
    if not isinstance(conclusion, str):
        errors.append("conclusion debe ser texto.")
    else:
        if text_contains_forbidden_numeric_content(conclusion):
            errors.append("conclusion contiene cifras.")
        validate_grounded_text(
            conclusion,
            "conclusion",
            comparison_channels,
            comparison_speed_context,
            errors,
        )
    return errors
