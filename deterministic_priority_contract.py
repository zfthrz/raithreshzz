"""Validation and application of deterministic comparison priority tiers."""

from __future__ import annotations

from deterministic_coaching import safe_int


def validate_priority_ranker_response(response, episode_catalog):
    errors = []
    expected_keys = {
        "ordered_episode_ids",
        "priority_cut_rank",
        "no_actionable_start_rank",
    }
    actual_keys = set(response.keys()) if isinstance(response, dict) else set()
    if actual_keys != expected_keys:
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        if missing:
            errors.append("Faltan claves del ranker: " + ", ".join(sorted(missing)))
        if extra:
            errors.append("Sobran claves del ranker: " + ", ".join(sorted(extra)))
    if not isinstance(response, dict):
        return errors or ["La respuesta del ranker debe ser objeto."]

    ordered = response.get("ordered_episode_ids")
    expected_ids = [safe_int(ep.get("episode_id")) for ep in episode_catalog]
    count = len(expected_ids)
    if not isinstance(ordered, list):
        errors.append("ordered_episode_ids debe ser lista.")
        ordered_ids = []
    else:
        ordered_ids = [safe_int(value) for value in ordered]
        if any(value is None for value in ordered_ids):
            errors.append("ordered_episode_ids debe contener sólo IDs enteros.")
    if len(ordered_ids) != count:
        errors.append(
            "Cantidad de IDs ordenados incorrecta: "
            f"esperados={count} recibidos={len(ordered_ids)}"
        )
    if sorted(x for x in ordered_ids if x is not None) != sorted(
        x for x in expected_ids if x is not None
    ):
        errors.append(
            "ordered_episode_ids no coincide con los episode_id esperados."
        )
    if len(ordered_ids) != len(set(ordered_ids)):
        errors.append("ordered_episode_ids contiene IDs duplicados.")

    priority_cut = safe_int(response.get("priority_cut_rank"))
    no_actionable_start = safe_int(response.get("no_actionable_start_rank"))
    if count <= 0:
        errors.append("El ranker requiere al menos un episodio.")
        return errors
    if priority_cut is None:
        errors.append("priority_cut_rank debe ser entero.")
    else:
        max_priority_cut = 1 if count == 1 else count - 1
        if not (1 <= priority_cut <= max_priority_cut):
            errors.append(
                "priority_cut_rank fuera de rango: "
                f"debe estar entre 1 y {max_priority_cut}."
            )
    if no_actionable_start is None:
        errors.append("no_actionable_start_rank debe ser entero.")
    elif not (1 <= no_actionable_start <= count + 1):
        errors.append(
            "no_actionable_start_rank fuera de rango: "
            f"debe estar entre 1 y {count + 1}."
        )
    if (
        priority_cut is not None
        and no_actionable_start is not None
        and no_actionable_start <= priority_cut
    ):
        errors.append(
            "no_actionable_start_rank debe ser posterior a priority_cut_rank."
        )
    return errors


def derive_priority_classifications(ranker_response, episode_catalog):
    ordered = [
        safe_int(value)
        for value in ranker_response.get("ordered_episode_ids", [])
    ]
    priority_cut = safe_int(ranker_response.get("priority_cut_rank"))
    no_actionable_start = safe_int(
        ranker_response.get("no_actionable_start_rank")
    )
    position_by_id = {
        episode_id: rank for rank, episode_id in enumerate(ordered, start=1)
    }
    classifications = []
    for episode in episode_catalog:
        episode_id = safe_int(episode.get("episode_id"))
        rank = position_by_id[episode_id]
        if rank <= priority_cut:
            classification = "PRIORITARIO"
        elif rank >= no_actionable_start:
            classification = "NO_ACCIONABLE"
        else:
            classification = "SECUNDARIO"
        classifications.append(
            {
                "episode_id": episode_id,
                "relative_priority_rank": rank,
                "classification": classification,
            }
        )
    return classifications


def apply_priority_classifications(
    episode_assessments,
    episode_catalog,
    ranker_response,
):
    derived = derive_priority_classifications(ranker_response, episode_catalog)
    by_id = {safe_int(item.get("episode_id")): item for item in derived}
    merged = []
    for assessment in episode_assessments:
        item = dict(assessment)
        episode_id = safe_int(item.get("episode_id"))
        item["classification"] = by_id[episode_id]["classification"]
        merged.append(item)
    return merged
