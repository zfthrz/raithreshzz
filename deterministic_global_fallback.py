"""Deterministic global fallback extracted from llm_analysis_deepseek.

Backend-independent deterministic closure for the global response.
"""

from deterministic_coaching import (
    _direct_coaching_target_text,
    build_deterministic_repeated_observations,
)
from deterministic_text_validation import (
    text_contains_forbidden_numeric_content,
)


def build_deterministic_global_fallback(
    session_coaching_facts,
):
    """
    Fallback global v3.10.8.5.4.

    La síntesis narrativa del LLM nunca debe ser un punto único de fallo.
    Si el backend no logra entregar un JSON global válido, Python construye
    un cierre mínimo únicamente desde next_stint_plan y los hechos recurrentes
    ya validados. No inventa causas, dominios ni objetivos nuevos.
    """
    plan = (
        session_coaching_facts.get("next_stint_plan", [])
        if isinstance(session_coaching_facts, dict)
        else []
    ) or []

    opportunities = []
    qualitative_by_label = {}

    for item in plan[:3]:
        if not isinstance(item, dict):
            continue

        label = str(item.get("plan_label") or "").strip().upper()
        if not label:
            continue

        parts = []
        for target in item.get("targets", []) or []:
            direct = _direct_coaching_target_text(target)
            if not direct:
                continue

            # opportunities/conclusion no admiten cifras. Los targets de punto
            # espacial permanecen exclusivamente en next_session_priorities.
            if text_contains_forbidden_numeric_content(direct):
                continue

            if direct not in parts:
                parts.append(direct)

        if not parts:
            continue

        qualitative_by_label[label] = parts
        opportunities.append(
            f"Zona {label}: " + "; ".join(parts) + "."
        )

    if not opportunities:
        opportunities = [
            "Concentrá la próxima tanda en los inputs repetidos de las zonas prioritarias."
        ]

    repeated_observations = build_deterministic_repeated_observations(
        session_coaching_facts
    )

    primary_label = None
    primary_parts = None
    for item in plan[:3]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("plan_label") or "").strip().upper()
        parts = qualitative_by_label.get(label)
        if label and parts:
            primary_label = label
            primary_parts = parts
            break

    if primary_label and primary_parts:
        conclusion = (
            f"Empezá la próxima tanda por la zona {primary_label}: "
            + "; ".join(primary_parts)
            + ". Después continuá con las demás zonas prioritarias."
        )
    else:
        conclusion = (
            "En la próxima tanda, concentrá la ejecución en los inputs repetidos "
            "de las zonas prioritarias."
        )

    return {
        "opportunities": opportunities[:4],
        "repeated_observations": repeated_observations[:4],
        "hypotheses": [],
        "limitations": [],
        "conclusion": conclusion,
    }
