"""Backend-independent deterministic priority shadow diagnostics."""

from deterministic_coaching import safe_int
from deterministic_priority_contract import (
    derive_priority_classifications,
    validate_priority_ranker_response as validate_comparison_ranker_response,
)
from session_coaching_intervals import _finite_number


PRIORITY_COVERAGE_TARGET = 0.55
NO_ACTIONABLE_WEAK_SHARE_MAX = 0.05
NO_ACTIONABLE_MODERATE_SHARE_MAX = 0.04
NO_ACTIONABLE_STRONG_SHARE_MAX = 0.01



def build_deterministic_comparison_ranker_response(episode_catalog):
    """
    D2.1 shadow — ranker comparativo 100 % determinista.

    Devuelve exactamente el mismo contrato que el ranker LLM actual, pero no
    reemplaza todavía ninguna llamada de producción.

    Autoridades:
    - si global_rank es válido para todo el catálogo, conserva ese orden;
    - de lo contrario reconstruye el mismo orden objetivo desde hechos Python;
    - evidence_strength sólo define los cortes de tier, no reinterpreta
      telemetría ni introduce causalidad.
    """
    if not isinstance(episode_catalog, list) or not episode_catalog:
        raise ValueError(
            "El ranker determinista requiere al menos un episodio."
        )

    episodes = []
    seen_ids = set()

    for episode in episode_catalog:
        if not isinstance(episode, dict):
            raise ValueError(
                "Cada episodio del ranker determinista debe ser objeto."
            )

        episode_id = safe_int(episode.get("episode_id"))
        if episode_id is None:
            raise ValueError(
                "Cada episodio del ranker determinista requiere episode_id."
            )
        if episode_id in seen_ids:
            raise ValueError(
                f"episode_id duplicado en ranker determinista: {episode_id}"
            )

        seen_ids.add(episode_id)
        episodes.append(episode)

    global_ranks = [
        safe_int(episode.get("global_rank"))
        for episode in episodes
    ]
    usable_global_rank = (
        all(
            rank is not None and rank >= 1
            for rank in global_ranks
        )
        and len(set(global_ranks)) == len(global_ranks)
    )

    if usable_global_rank:
        ordered = sorted(
            episodes,
            key=lambda episode: (
                safe_int(episode.get("global_rank")),
                safe_int(episode.get("episode_id")),
            ),
        )
    else:
        evidence_priority = {
            "strong": 2,
            "moderate": 1,
            "weak": 0,
        }

        ordered = sorted(
            episodes,
            key=lambda episode: (
                -(
                    _finite_number(
                        episode.get("action_time_loss_s")
                    )
                    or 0.0
                ),
                -evidence_priority.get(
                    episode.get("evidence_strength"),
                    0,
                ),
                -(
                    safe_int(
                        episode.get("action_channel_count")
                    )
                    or 0
                ),
                -(
                    _finite_number(
                        episode.get("length_m")
                    )
                    or 0.0
                ),
                safe_int(episode.get("episode_id")),
            ),
        )

    ordered_episode_ids = [
        safe_int(episode.get("episode_id"))
        for episode in ordered
    ]

    n = len(ordered)

    # PRIORITARIO:
    # - siempre existe al menos uno;
    # - si el líder es strong, conserva el bloque strong inicial;
    # - con N > 1 nunca todos quedan PRIORITARIO, igual que el contrato LLM.
    if n == 1:
        priority_cut_rank = 1
    elif ordered[0].get("evidence_strength") == "strong":
        strong_prefix = 0
        for episode in ordered:
            if episode.get("evidence_strength") != "strong":
                break
            strong_prefix += 1

        priority_cut_rank = max(
            1,
            min(strong_prefix, n - 1),
        )
    else:
        priority_cut_rank = 1

    # NO_ACCIONABLE:
    # sólo el sufijo final consecutivo de evidencia weak.
    # Un weak intercalado no puede crear un corte que arrastre evidencia mejor.
    weak_suffix_start = n + 1

    for rank in range(n, 0, -1):
        episode = ordered[rank - 1]
        if episode.get("evidence_strength") != "weak":
            break
        weak_suffix_start = rank

    # El contrato exige que NO_ACCIONABLE empiece después del último
    # PRIORITARIO. Si todos son weak, el líder sigue siendo la mejor
    # oportunidad relativa de la comparación.
    no_actionable_start_rank = max(
        weak_suffix_start,
        priority_cut_rank + 1,
    )

    return {
        "ordered_episode_ids": ordered_episode_ids,
        "priority_cut_rank": priority_cut_rank,
        "no_actionable_start_rank": no_actionable_start_rank,
    }


def build_calibrated_priority_cut_rank(
    episode_catalog,
    ordered_episode_ids,
    *,
    coverage_target=PRIORITY_COVERAGE_TARGET,
):
    # D2.3 shadow: smallest deterministic loss-coverage prefix.
    ordered_episode_ids = [
        safe_int(value)
        for value in ordered_episode_ids
    ]
    if not ordered_episode_ids or any(
        value is None for value in ordered_episode_ids
    ):
        raise ValueError(
            "El corte calibrado requiere IDs de episodio válidos."
        )
    if not 0.0 < coverage_target <= 1.0:
        raise ValueError(
            "coverage_target debe estar en el intervalo (0, 1]."
        )

    by_id = {
        safe_int(episode.get("episode_id")): episode
        for episode in episode_catalog
        if isinstance(episode, dict)
    }
    if set(ordered_episode_ids) != set(by_id):
        raise ValueError(
            "El orden calibrado no coincide con episode_catalog."
        )

    losses = []
    for episode_id in ordered_episode_ids:
        loss = _finite_number(
            by_id[episode_id].get("action_time_loss_s")
        )
        losses.append(
            max(0.0, loss) if loss is not None else 0.0
        )

    n = len(ordered_episode_ids)
    if n == 1:
        return 1

    total = sum(losses)
    if total <= 0.0:
        return 1

    cumulative = 0.0
    cut = 1
    for rank, loss in enumerate(losses, start=1):
        cumulative += loss
        cut = rank
        if cumulative / total >= coverage_target:
            break

    return max(1, min(cut, n - 1))


def build_calibrated_comparison_ranker_response(
    episode_catalog,
    *,
    deterministic_response=None,
    coverage_target=PRIORITY_COVERAGE_TARGET,
):
    # D2.3 shadow candidate: keep deterministic order/NO_ACCIONABLE policy,
    # replace only priority_cut_rank with the calibrated loss-coverage cut.
    if deterministic_response is None:
        deterministic_response = (
            build_deterministic_comparison_ranker_response(
                episode_catalog
            )
        )

    ordered_episode_ids = list(
        deterministic_response["ordered_episode_ids"]
    )
    priority_cut_rank = build_calibrated_priority_cut_rank(
        episode_catalog,
        ordered_episode_ids,
        coverage_target=coverage_target,
    )
    no_actionable_start_rank = max(
        deterministic_response["no_actionable_start_rank"],
        priority_cut_rank + 1,
    )

    response = {
        "ordered_episode_ids": ordered_episode_ids,
        "priority_cut_rank": priority_cut_rank,
        "no_actionable_start_rank": no_actionable_start_rank,
    }
    errors = validate_comparison_ranker_response(
        response,
        episode_catalog,
    )
    if errors:
        raise ValueError(
            "El ranker calibrado shadow no cumple el contrato: "
            + "; ".join(errors)
        )
    return response


def build_calibrated_no_actionable_start_rank(
    episode_catalog,
    ordered_episode_ids,
    *,
    priority_cut_rank,
    weak_share_max=NO_ACTIONABLE_WEAK_SHARE_MAX,
    moderate_share_max=NO_ACTIONABLE_MODERATE_SHARE_MAX,
    strong_share_max=NO_ACTIONABLE_STRONG_SHARE_MAX,
):
    # D2.4 shadow: evidence-conditioned negligible-loss tail.
    ordered_episode_ids = [
        safe_int(value)
        for value in ordered_episode_ids
    ]
    if not ordered_episode_ids or any(
        value is None for value in ordered_episode_ids
    ):
        raise ValueError(
            "El corte NO_ACCIONABLE calibrado requiere IDs válidos."
        )

    thresholds = {
        "weak": weak_share_max,
        "moderate": moderate_share_max,
        "strong": strong_share_max,
    }
    if any(
        not 0.0 <= value <= 1.0
        for value in thresholds.values()
    ):
        raise ValueError(
            "Los thresholds NO_ACCIONABLE deben estar en [0, 1]."
        )

    n = len(ordered_episode_ids)
    if not 1 <= priority_cut_rank <= n:
        raise ValueError("priority_cut_rank fuera de rango.")

    by_id = {
        safe_int(episode.get("episode_id")): episode
        for episode in episode_catalog
        if isinstance(episode, dict)
    }
    if set(ordered_episode_ids) != set(by_id):
        raise ValueError(
            "El orden calibrado no coincide con episode_catalog."
        )

    losses = []
    for episode_id in ordered_episode_ids:
        loss = _finite_number(
            by_id[episode_id].get("action_time_loss_s")
        )
        losses.append(
            max(0.0, loss) if loss is not None else 0.0
        )

    total_loss = sum(losses)
    if total_loss <= 0.0:
        return n + 1

    no_actionable_start_rank = n + 1
    for rank in range(n, priority_cut_rank, -1):
        episode = by_id[ordered_episode_ids[rank - 1]]
        evidence = str(
            episode.get("evidence_strength") or ""
        ).strip().lower()
        threshold = thresholds.get(evidence, 0.0)
        share = losses[rank - 1] / total_loss

        if share > threshold:
            break
        no_actionable_start_rank = rank

    return max(
        no_actionable_start_rank,
        priority_cut_rank + 1,
    )


def build_calibrated_no_actionable_comparison_ranker_response(
    episode_catalog,
    *,
    calibrated_priority_response=None,
):
    # D2.4 shadow candidate: keep D2.3 order/priority cut and calibrate
    # only the NO_ACCIONABLE boundary.
    if calibrated_priority_response is None:
        calibrated_priority_response = (
            build_calibrated_comparison_ranker_response(
                episode_catalog
            )
        )

    ordered_episode_ids = list(
        calibrated_priority_response["ordered_episode_ids"]
    )
    priority_cut_rank = calibrated_priority_response[
        "priority_cut_rank"
    ]
    no_actionable_start_rank = (
        build_calibrated_no_actionable_start_rank(
            episode_catalog,
            ordered_episode_ids,
            priority_cut_rank=priority_cut_rank,
        )
    )

    response = {
        "ordered_episode_ids": ordered_episode_ids,
        "priority_cut_rank": priority_cut_rank,
        "no_actionable_start_rank": no_actionable_start_rank,
    }
    errors = validate_comparison_ranker_response(
        response,
        episode_catalog,
    )
    if errors:
        raise ValueError(
            "El ranker NO_ACCIONABLE calibrado no cumple el contrato: "
            + "; ".join(errors)
        )
    return response


def build_deterministic_ranker_shadow_audit(
    episode_catalog,
    llm_ranker_response,
):
    """
    D2.2 shadow — compara el ranker LLM autoritativo con el ranker
    determinista sin alterar ninguna clasificación de producción.

    El audit conserva ambas clasificaciones completas para poder diagnosticar
    divergencias por episodio cuando haya sesiones reales disponibles.
    """
    llm_errors = validate_comparison_ranker_response(
        llm_ranker_response,
        episode_catalog,
    )
    if llm_errors:
        raise ValueError(
            "El ranker LLM recibido por el shadow no cumple el contrato: "
            + "; ".join(llm_errors)
        )

    deterministic_response = (
        build_deterministic_comparison_ranker_response(
            episode_catalog
        )
    )
    deterministic_errors = validate_comparison_ranker_response(
        deterministic_response,
        episode_catalog,
    )
    if deterministic_errors:
        raise ValueError(
            "El ranker determinista shadow no cumple el contrato: "
            + "; ".join(deterministic_errors)
        )

    llm_classifications = derive_priority_classifications(
        llm_ranker_response,
        episode_catalog,
    )
    deterministic_classifications = derive_priority_classifications(
        deterministic_response,
        episode_catalog,
    )

    calibrated_response = build_calibrated_comparison_ranker_response(
        episode_catalog,
        deterministic_response=deterministic_response,
    )
    calibrated_classifications = derive_priority_classifications(
        calibrated_response,
        episode_catalog,
    )
    calibrated_agreement = {
        "ordered_episode_ids": (
            calibrated_response["ordered_episode_ids"]
            == llm_ranker_response["ordered_episode_ids"]
        ),
        "priority_cut_rank": (
            calibrated_response["priority_cut_rank"]
            == llm_ranker_response["priority_cut_rank"]
        ),
        "no_actionable_start_rank": (
            calibrated_response["no_actionable_start_rank"]
            == llm_ranker_response["no_actionable_start_rank"]
        ),
        "classifications": (
            calibrated_classifications == llm_classifications
        ),
    }
    calibrated_agreement["full"] = all(
        calibrated_agreement.values()
    )

    calibrated_no_actionable_response = (
        build_calibrated_no_actionable_comparison_ranker_response(
            episode_catalog,
            calibrated_priority_response=calibrated_response,
        )
    )
    calibrated_no_actionable_classifications = (
        derive_priority_classifications(
            calibrated_no_actionable_response,
            episode_catalog,
        )
    )
    calibrated_no_actionable_agreement = {
        "ordered_episode_ids": (
            calibrated_no_actionable_response["ordered_episode_ids"]
            == llm_ranker_response["ordered_episode_ids"]
        ),
        "priority_cut_rank": (
            calibrated_no_actionable_response["priority_cut_rank"]
            == llm_ranker_response["priority_cut_rank"]
        ),
        "no_actionable_start_rank": (
            calibrated_no_actionable_response[
                "no_actionable_start_rank"
            ]
            == llm_ranker_response["no_actionable_start_rank"]
        ),
        "classifications": (
            calibrated_no_actionable_classifications
            == llm_classifications
        ),
    }
    calibrated_no_actionable_agreement["full"] = all(
        calibrated_no_actionable_agreement.values()
    )

    agreement = {
        "ordered_episode_ids": (
            deterministic_response["ordered_episode_ids"]
            == llm_ranker_response["ordered_episode_ids"]
        ),
        "priority_cut_rank": (
            deterministic_response["priority_cut_rank"]
            == llm_ranker_response["priority_cut_rank"]
        ),
        "no_actionable_start_rank": (
            deterministic_response["no_actionable_start_rank"]
            == llm_ranker_response["no_actionable_start_rank"]
        ),
        "classifications": (
            deterministic_classifications == llm_classifications
        ),
    }
    agreement["full"] = all(agreement.values())

    return {
        "status": "VALID",
        "response": deterministic_response,
        "agreement": agreement,
        "llm_classifications": llm_classifications,
        "deterministic_classifications": deterministic_classifications,
        "calibrated_candidate": {
            "coverage_target": PRIORITY_COVERAGE_TARGET,
            "response": calibrated_response,
            "agreement": calibrated_agreement,
            "classifications": calibrated_classifications,
        },
        "calibrated_no_actionable_candidate": {
            "weak_share_max": NO_ACTIONABLE_WEAK_SHARE_MAX,
            "moderate_share_max": NO_ACTIONABLE_MODERATE_SHARE_MAX,
            "strong_share_max": NO_ACTIONABLE_STRONG_SHARE_MAX,
            "response": calibrated_no_actionable_response,
            "agreement": calibrated_no_actionable_agreement,
            "classifications": (
                calibrated_no_actionable_classifications
            ),
        },
    }
