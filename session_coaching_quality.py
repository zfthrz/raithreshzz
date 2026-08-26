"""Deterministic session comparison quality and anomaly gating."""

import statistics

from deterministic_coaching import safe_float, safe_int

ANOMALY_GATE_CONFIG = {
    "max_episode_length_m": 500.0,
    "min_local_loss_s": 5.0,
    "lap_delta_exceed_margin_s": 1.0,
    "extreme_local_loss_s": 8.0,
    "lap_delta_fraction": 0.75,
}

SESSION_COMPARISON_LOCAL_SEVERITY_MIN_MARGIN_S = 1.0

SESSION_COMPARISON_LOCAL_SEVERITY_SIGMA_MULTIPLIER = 8.0

SESSION_COMPARISON_QUALITY_GATE_VERSION = "1.1"

SESSION_COMPARISON_QUALITY_MAD_SIGMA_MULTIPLIER = 6.0

SESSION_COMPARISON_QUALITY_MIN_COUNT = 3

SESSION_COMPARISON_QUALITY_MIN_MARGIN_S = 1.0

SESSION_COMPARISON_QUALITY_RATIO_MULTIPLIER = 3.0

def _comparison_quality_diagnostics(comparison):
    """
    v3.10.8.5.4 — diagnóstico determinista para confirmar o rechazar un
    candidato estadístico del quality gate.

    Puede trabajar sobre una comparación cruda de analyze_telemetry,
    construyendo el catálogo de episodios sin LLM, o reutilizar
    episode_ground_truth si la comparación ya fue analizada.
    """
    if not isinstance(comparison, dict):
        return None

    episodes = comparison.get("episode_ground_truth")
    excluded_count = safe_int(comparison.get("excluded_anomaly_count")) or 0

    if not isinstance(episodes, list):
        try:
            detected = build_episode_catalog(comparison)
            episodes, excluded = split_episode_catalog_for_coaching(
                comparison,
                detected,
            )
            excluded_count = len(excluded or [])
        except Exception:
            return None

    episodes = [
        item for item in (episodes or [])
        if isinstance(item, dict)
    ]

    losses = [
        abs(safe_float(item.get("action_time_loss_s")) or 0.0)
        for item in episodes
    ]
    lengths = [
        max(0.0, safe_float(item.get("length_m")) or 0.0)
        for item in episodes
    ]
    abs_delta_edges = []
    for item in episodes:
        for key in ("delta_start_s", "delta_end_s"):
            value = safe_float(item.get(key))
            if value is not None:
                abs_delta_edges.append(abs(value))

    return {
        "available": True,
        "coaching_episode_count": len(episodes),
        "excluded_anomaly_count": excluded_count,
        "max_action_time_loss_s": max(losses, default=0.0),
        "median_action_time_loss_s": (
            float(statistics.median(losses))
            if losses else 0.0
        ),
        "sum_action_time_loss_s": sum(losses),
        "max_episode_length_m": max(lengths, default=0.0),
        "max_abs_episode_delta_s": max(abs_delta_edges, default=0.0),
    }

def _confirm_statistical_comparison_outlier(candidate_row, baseline_rows):
    """
    Segunda etapa del gate 1.1.

    Un delta de vuelta atípico NO alcanza para excluir coaching. El candidato
    debe mostrar además severidad local extraordinaria respecto de las demás
    comparaciones de la propia sesión, o contener una anomalía determinista
    ya excluida por el anomaly gate.
    """
    diagnostic = candidate_row.get("diagnostics")
    if not isinstance(diagnostic, dict) or not diagnostic.get("available"):
        return {
            "confirmed": False,
            "reason": "insufficient_local_diagnostics",
            "local_severity_threshold_s": None,
            "baseline_local_loss_median_s": None,
            "baseline_local_loss_mad_s": None,
        }

    if (safe_int(diagnostic.get("excluded_anomaly_count")) or 0) > 0:
        return {
            "confirmed": True,
            "reason": "deterministic_local_anomaly_present",
            "local_severity_threshold_s": None,
            "baseline_local_loss_median_s": None,
            "baseline_local_loss_mad_s": None,
        }

    baseline_values = []
    for row in baseline_rows or []:
        other = row.get("diagnostics")
        if not isinstance(other, dict) or not other.get("available"):
            continue
        value = safe_float(other.get("max_action_time_loss_s"))
        if value is not None:
            baseline_values.append(max(0.0, value))

    if len(baseline_values) < 2:
        return {
            "confirmed": False,
            "reason": "insufficient_baseline_local_diagnostics",
            "local_severity_threshold_s": None,
            "baseline_local_loss_median_s": (
                float(statistics.median(baseline_values))
                if baseline_values else None
            ),
            "baseline_local_loss_mad_s": None,
        }

    baseline_median = float(statistics.median(baseline_values))
    baseline_deviations = [
        abs(value - baseline_median)
        for value in baseline_values
    ]
    baseline_mad = float(statistics.median(baseline_deviations))
    baseline_sigma = 1.4826 * baseline_mad

    threshold = baseline_median + max(
        SESSION_COMPARISON_LOCAL_SEVERITY_MIN_MARGIN_S,
        SESSION_COMPARISON_LOCAL_SEVERITY_SIGMA_MULTIPLIER * baseline_sigma,
    )

    candidate_local_loss = (
        safe_float(diagnostic.get("max_action_time_loss_s"))
        or 0.0
    )
    confirmed = candidate_local_loss > threshold

    return {
        "confirmed": confirmed,
        "reason": (
            "statistical_outlier_plus_extreme_local_loss"
            if confirmed
            else "statistical_outlier_without_extreme_local_loss"
        ),
        "candidate_max_local_loss_s": candidate_local_loss,
        "local_severity_threshold_s": threshold,
        "baseline_local_loss_median_s": baseline_median,
        "baseline_local_loss_mad_s": baseline_mad,
        "baseline_local_loss_robust_sigma_s": baseline_sigma,
    }

def _session_comparison_key(comparison):
    if not isinstance(comparison, dict):
        return "comparison"
    reference_lap = safe_int(comparison.get("reference_lap"))
    comparison_lap = safe_int(comparison.get("comparison_lap"))
    if reference_lap is not None and comparison_lap is not None:
        return f"{reference_lap}->{comparison_lap}"
    return "comparison"

def build_episode_catalog(comparison):
    """
    Crea IDs secuenciales deterministas para el contrato LLM.

    El LLM nunca decide IDs ni ranking.
    """

    episodes = (
        comparison[
            "objective_analysis"
        ][
            "driver_action_episode_ranking"
        ]
    )

    catalog = []

    for episode_id, episode in enumerate(
        episodes,
        start=1,
    ):
        record = dict(episode)

        record["episode_id"] = episode_id

        catalog.append(record)

    return catalog

def build_session_comparison_quality_gate(valid_comparison_results):
    """
    Comparison Quality Gate v1.1.

    Etapa 1: mediana + MAD + criterio relativo -> candidato estadístico.
    Etapa 2: confirmación determinista de severidad local extraordinaria.

    Ser una vuelta más lenta no alcanza para excluirla del coaching.
    """
    rows = []
    for comparison in valid_comparison_results or []:
        if not isinstance(comparison, dict):
            continue
        if comparison.get("status") not in {None, "VALID"}:
            continue
        delta = safe_float(comparison.get("comparison_minus_reference_s"))
        if delta is None:
            continue
        rows.append({
            "comparison": _session_comparison_key(comparison),
            "reference_lap": safe_int(comparison.get("reference_lap")),
            "comparison_lap": safe_int(comparison.get("comparison_lap")),
            "comparison_minus_reference_s": delta,
            "abs_delta_s": abs(delta),
            "diagnostics": _comparison_quality_diagnostics(comparison),
        })

    if not rows:
        return {
            "version": SESSION_COMPARISON_QUALITY_GATE_VERSION,
            "status": "NO_VALID_COMPARISONS",
            "method": "median_mad_candidate_plus_local_severity_confirmation",
            "comparison_count": 0,
            "included_count": 0,
            "excluded_count": 0,
            "statistical_candidate_count": 0,
            "retained_statistical_outlier_count": 0,
            "comparisons": [],
        }

    values = [row["abs_delta_s"] for row in rows]
    median_delta = float(statistics.median(values))
    deviations = [abs(value - median_delta) for value in values]
    mad = float(statistics.median(deviations))
    robust_sigma = 1.4826 * mad

    enough = len(values) >= SESSION_COMPARISON_QUALITY_MIN_COUNT
    if enough:
        robust_threshold = median_delta + max(
            SESSION_COMPARISON_QUALITY_MIN_MARGIN_S,
            SESSION_COMPARISON_QUALITY_MAD_SIGMA_MULTIPLIER * robust_sigma,
        )
        relative_threshold = max(
            median_delta * SESSION_COMPARISON_QUALITY_RATIO_MULTIPLIER,
            median_delta + SESSION_COMPARISON_QUALITY_MIN_MARGIN_S,
        )
        candidate_threshold = max(robust_threshold, relative_threshold)
    else:
        robust_threshold = None
        relative_threshold = None
        candidate_threshold = None

    candidate_rows = []
    baseline_rows = []
    for row in rows:
        is_candidate = bool(
            enough
            and candidate_threshold is not None
            and row["abs_delta_s"] > candidate_threshold
        )
        row["statistical_outlier_candidate"] = is_candidate
        if is_candidate:
            candidate_rows.append(row)
        else:
            baseline_rows.append(row)

    excluded = []
    retained_candidates = []

    for row in rows:
        if not row["statistical_outlier_candidate"]:
            row["session_plan_eligible"] = True
            row["quality_status"] = "SESSION_PLAN_ELIGIBLE"
            row["reason"] = None
            row["confirmation"] = None
            continue

        confirmation = _confirm_statistical_comparison_outlier(
            row,
            baseline_rows,
        )
        row["confirmation"] = confirmation

        if confirmation.get("confirmed"):
            row["session_plan_eligible"] = False
            row["quality_status"] = "COACHING_EXCLUDED_NON_REPRESENTATIVE_LAP"
            row["reason"] = confirmation.get("reason")
            excluded.append(row["comparison"])
        else:
            row["session_plan_eligible"] = True
            row["quality_status"] = "STATISTICAL_OUTLIER_RETAINED_FOR_COACHING"
            row["reason"] = confirmation.get("reason")
            retained_candidates.append(row["comparison"])

    return {
        "version": SESSION_COMPARISON_QUALITY_GATE_VERSION,
        "status": "ACTIVE" if enough else "INSUFFICIENT_COMPARISONS_FOR_ROBUST_GATE",
        "method": "median_mad_candidate_plus_local_severity_confirmation",
        "comparison_count": len(rows),
        "included_count": sum(1 for row in rows if row["session_plan_eligible"]),
        "excluded_count": len(excluded),
        "statistical_candidate_count": len(candidate_rows),
        "retained_statistical_outlier_count": len(retained_candidates),
        "median_abs_delta_s": median_delta,
        "mad_abs_delta_s": mad,
        "robust_sigma_s": robust_sigma,
        "robust_threshold_s": robust_threshold,
        "relative_threshold_s": relative_threshold,
        "candidate_threshold_s": candidate_threshold,
        "exclusion_threshold_s": candidate_threshold,
        "excluded_comparisons": excluded,
        "retained_statistical_outliers": retained_candidates,
        "comparisons": rows,
        "policy": (
            "statistical pace outlier is only a candidate; exclusion from "
            "session coaching requires deterministic local-severity confirmation"
        ),
    }

def classify_non_representative_time_loss(
    episode,
    comparison,
):
    """
    Devuelve metadata de anomalía si el episodio concentra una pérdida
    temporal demasiado grande para tratarla como coaching técnico normal.

    La función sólo clasifica la forma temporal de la anomalía. Nunca
    intenta identificar su causa física o deportiva.
    """
    if not isinstance(episode, dict):
        return None

    if not isinstance(comparison, dict):
        return None

    length_m = safe_float(
        episode.get("length_m")
    )
    local_loss_s = safe_float(
        episode.get("action_time_loss_s")
    )
    lap_delta_s = safe_float(
        comparison.get("comparison_minus_reference_s")
    )

    if (
        length_m is None
        or local_loss_s is None
        or lap_delta_s is None
    ):
        return None

    # Sólo aplica a comparaciones donde la vuelta comparada pierde tiempo.
    if lap_delta_s <= 0.0:
        return None

    if local_loss_s <= 0.0:
        return None

    if (
        length_m
        > ANOMALY_GATE_CONFIG["max_episode_length_m"]
    ):
        return None

    if (
        local_loss_s
        < ANOMALY_GATE_CONFIG["min_local_loss_s"]
    ):
        return None

    reasons = []

    if (
        local_loss_s
        >= lap_delta_s
        + ANOMALY_GATE_CONFIG[
            "lap_delta_exceed_margin_s"
        ]
    ):
        reasons.append(
            "LOCAL_LOSS_EXCEEDS_LAP_DELTA"
        )

    if (
        local_loss_s
        >= ANOMALY_GATE_CONFIG[
            "extreme_local_loss_s"
        ]
        and
        local_loss_s
        >= lap_delta_s
        * ANOMALY_GATE_CONFIG[
            "lap_delta_fraction"
        ]
    ):
        reasons.append(
            "EXTREME_LOCAL_LOSS_CONCENTRATION"
        )

    if not reasons:
        return None

    return {
        "anomaly_status":
            "NON_REPRESENTATIVE_TIME_LOSS",
        "recommended_for_driver_analysis":
            False,
        "excluded_from_coaching":
            True,
        "anomaly_reason":
            "+".join(reasons),
        "anomaly_reasons":
            reasons,
        "local_loss_s":
            local_loss_s,
        "lap_delta_s":
            lap_delta_s,
        "local_loss_to_lap_delta_ratio":
            (
                local_loss_s / lap_delta_s
                if lap_delta_s > 0.0
                else None
            ),
        "detection_basis":
            "DETERMINISTIC_TIME_LOSS_GATE",
        "cause_inferred":
            False,
        "driver_message":
            (
                "Se detectó una pérdida anómala de gran magnitud. "
                "No se utiliza para recomendaciones de técnica."
            ),
    }

def split_episode_catalog_for_coaching(
    comparison,
    episode_catalog,
):
    """
    Mantiene los episode_id originales. Los episodios anómalos se
    conservan aparte para auditoría y no llegan al LLM/ranker/coaching.
    """
    eligible = []
    excluded = []

    for episode in episode_catalog:
        anomaly = (
            classify_non_representative_time_loss(
                episode,
                comparison,
            )
        )

        if anomaly is None:
            eligible.append(episode)
            continue

        record = dict(episode)
        record.update(anomaly)
        excluded.append(record)

    return eligible, excluded
