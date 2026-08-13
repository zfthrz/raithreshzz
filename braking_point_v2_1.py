import math

import numpy as np
import pandas as pd


BRAKING_POINT_VERSION = "2.1"
BRAKING_POINT_SCHEMA_VERSION = "2.1"


# ============================================================
# BRAKING POINT v2.1 - DETERMINISTIC
# ============================================================
#
# Objetivo:
# - detectar el inicio REAL de una frenada en cada vuelta a partir de
#   brake_a / brake_b, no a partir de sustained_brake_difference;
# - asociar la frenada al driver_action_episode que contiene freno;
# - comparar referencia vs vuelta comparada;
# - autorizar objetivos cuantitativos independientes para:
#     * inicio de frenada (onset)
#     * liberación de freno (release)
#   sólo cuando la diferencia espacial supera una zona muerta conservadora.
#
# No diagnostica causa, trail braking, técnica ni geometría de trayectoria.
# ============================================================

BRAKE_ONSET_THRESHOLD_PERCENT = 5.0
BRAKE_CONFIRM_THRESHOLD_PERCENT = 15.0
BRAKE_RELEASE_THRESHOLD_PERCENT = 2.0

# El candidato debe alcanzar el umbral de confirmación relativamente pronto.
# Evita tomar como onset un roce leve del pedal mucho antes de la frenada real.
BRAKE_CONFIRM_MAX_DISTANCE_M = 40.0

# Una caída breve del pedal por debajo del umbral de release no divide la
# frenada inmediatamente. Debe permanecer liberado durante esta distancia.
BRAKE_RELEASE_CONFIRM_DISTANCE_M = 3.0

# Eventos demasiado cortos se descartan incluso si llegaron al umbral alto.
MIN_CONFIRMED_BRAKING_EVENT_DISTANCE_M = 5.0

# El evento de freno debe tocar el episodio de acción. Permitimos una pequeña
# tolerancia para diferencias de alineación/interpolación espacial.
EPISODE_ASSOCIATION_TOLERANCE_M = 8.0

# Diferencias menores se consideran equivalentes para coaching.
BRAKING_POINT_MIN_COACHING_DELTA_M = 8.0
BRAKE_RELEASE_POINT_MIN_COACHING_DELTA_M = 8.0

# Guardias adicionales: si los puntos emparejados están exageradamente
# separados, no se asume que correspondan a la misma maniobra.
BRAKING_POINT_MAX_PAIRED_ONSET_DELTA_M = 120.0
BRAKE_RELEASE_POINT_MAX_PAIRED_DELTA_M = 120.0


def _safe_float(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def braking_point_config_summary():
    return {
        "enabled": True,
        "version": BRAKING_POINT_VERSION,
        "schema_version": BRAKING_POINT_SCHEMA_VERSION,
        "onset_threshold_percent": BRAKE_ONSET_THRESHOLD_PERCENT,
        "confirm_threshold_percent": BRAKE_CONFIRM_THRESHOLD_PERCENT,
        "release_threshold_percent": BRAKE_RELEASE_THRESHOLD_PERCENT,
        "confirm_max_distance_m": BRAKE_CONFIRM_MAX_DISTANCE_M,
        "release_confirm_distance_m": BRAKE_RELEASE_CONFIRM_DISTANCE_M,
        "min_confirmed_event_distance_m": MIN_CONFIRMED_BRAKING_EVENT_DISTANCE_M,
        "episode_association_tolerance_m": EPISODE_ASSOCIATION_TOLERANCE_M,
        "onset_min_coaching_delta_m": BRAKING_POINT_MIN_COACHING_DELTA_M,
        "release_min_coaching_delta_m": BRAKE_RELEASE_POINT_MIN_COACHING_DELTA_M,
        "max_paired_onset_delta_m": BRAKING_POINT_MAX_PAIRED_ONSET_DELTA_M,
        "max_paired_release_delta_m": BRAKE_RELEASE_POINT_MAX_PAIRED_DELTA_M,
        "onset_source": "first_crossing_after_release",
        "release_source": "first_release_threshold_crossing_confirmed_by_distance",
        "confirmation_rule": "must_reach_confirm_threshold_before_max_distance",
        "onset_difference_source": "comparison_onset_minus_reference_onset",
        "release_difference_source": "comparison_release_minus_reference_release",
    }


def detect_braking_events(comparison, brake_column):
    """
    Detecta eventos de frenada en una señal individual ya alineada por
    distancia. El onset se fija en el PRIMER cruce del umbral bajo, pero el
    evento sólo se acepta si luego alcanza el umbral de confirmación.

    Devuelve eventos independientes de cualquier diferencia entre vueltas.
    """
    if not isinstance(comparison, pd.DataFrame):
        return []

    if "distance" not in comparison.columns or brake_column not in comparison.columns:
        return []

    distance = pd.to_numeric(
        comparison["distance"],
        errors="coerce",
    ).to_numpy(dtype=float)

    brake = pd.to_numeric(
        comparison[brake_column],
        errors="coerce",
    ).to_numpy(dtype=float)

    valid = np.isfinite(distance) & np.isfinite(brake)
    if not np.any(valid):
        return []

    distance = distance[valid]
    brake = brake[valid]

    if len(distance) < 2:
        return []

    events = []

    state = "idle"
    candidate_index = None
    confirmation_index = None
    release_candidate_index = None
    peak_index = None

    def reset():
        nonlocal state, candidate_index, confirmation_index
        nonlocal release_candidate_index, peak_index
        state = "idle"
        candidate_index = None
        confirmation_index = None
        release_candidate_index = None
        peak_index = None

    def close_event(end_index, release_confirmed):
        nonlocal events

        if candidate_index is None or confirmation_index is None:
            reset()
            return

        onset_m = float(distance[candidate_index])
        confirm_m = float(distance[confirmation_index])
        release_m = float(distance[end_index])
        length_m = release_m - onset_m

        if length_m < MIN_CONFIRMED_BRAKING_EVENT_DISTANCE_M:
            reset()
            return

        if peak_index is None:
            local = brake[candidate_index:end_index + 1]
            if len(local) == 0:
                reset()
                return
            local_peak = int(np.nanargmax(local))
            chosen_peak_index = candidate_index + local_peak
        else:
            chosen_peak_index = peak_index

        events.append({
            "braking_event_id": f"{brake_column}:{len(events) + 1:02d}",
            "onset_distance_m": _safe_float(onset_m),
            "confirmation_distance_m": _safe_float(confirm_m),
            "release_distance_m": _safe_float(release_m),
            "release_confirmed": bool(release_confirmed),
            "length_m": _safe_float(length_m),
            "peak_brake_percent": _safe_float(brake[chosen_peak_index]),
            "peak_distance_m": _safe_float(distance[chosen_peak_index]),
            "confirmed": True,
        })

        reset()

    for index in range(len(distance)):
        d = float(distance[index])
        b = float(brake[index])

        if state == "idle":
            if b >= BRAKE_ONSET_THRESHOLD_PERCENT:
                candidate_index = index
                peak_index = index
                state = "candidate"

                if b >= BRAKE_CONFIRM_THRESHOLD_PERCENT:
                    confirmation_index = index
                    state = "active"
            continue

        if peak_index is None or b > brake[peak_index]:
            peak_index = index

        if state == "candidate":
            onset_m = float(distance[candidate_index])

            if b <= BRAKE_RELEASE_THRESHOLD_PERCENT:
                reset()
                continue

            if d - onset_m > BRAKE_CONFIRM_MAX_DISTANCE_M:
                # El roce inicial no confirmó una frenada real.
                reset()
                # Si justo este punto ya es fuerte, se permite iniciar un
                # candidato nuevo aquí en vez de perder la frenada completa.
                if b >= BRAKE_ONSET_THRESHOLD_PERCENT:
                    candidate_index = index
                    peak_index = index
                    state = "candidate"
                    if b >= BRAKE_CONFIRM_THRESHOLD_PERCENT:
                        confirmation_index = index
                        state = "active"
                continue

            if b >= BRAKE_CONFIRM_THRESHOLD_PERCENT:
                confirmation_index = index
                state = "active"
            continue

        # state == active
        if b <= BRAKE_RELEASE_THRESHOLD_PERCENT:
            if release_candidate_index is None:
                release_candidate_index = index
            else:
                release_distance = (
                    float(distance[index])
                    - float(distance[release_candidate_index])
                )
                if release_distance >= BRAKE_RELEASE_CONFIRM_DISTANCE_M:
                    close_event(release_candidate_index, True)
            continue

        # Volvió a aplicar freno antes de confirmar release: mismo evento.
        release_candidate_index = None

    if state == "active":
        end_index = (
            release_candidate_index
            if release_candidate_index is not None
            else len(distance) - 1
        )
        close_event(end_index, False)

    return events


def _interval_overlap(start_a, end_a, start_b, end_b):
    return max(
        0.0,
        min(float(end_a), float(end_b))
        - max(float(start_a), float(start_b)),
    )


def _event_for_episode(events, episode):
    if not events or not isinstance(episode, dict):
        return None

    start_m = _safe_float(episode.get("start_distance_m"))
    end_m = _safe_float(episode.get("end_distance_m"))

    if start_m is None or end_m is None or end_m <= start_m:
        return None

    expanded_start = start_m - EPISODE_ASSOCIATION_TOLERANCE_M
    expanded_end = end_m + EPISODE_ASSOCIATION_TOLERANCE_M

    candidates = []

    for event in events:
        onset = _safe_float(event.get("onset_distance_m"))
        release = _safe_float(event.get("release_distance_m"))

        if onset is None or release is None or release <= onset:
            continue

        overlap = _interval_overlap(
            expanded_start,
            expanded_end,
            onset,
            release,
        )

        if overlap <= 0.0:
            continue

        # Prioriza el evento que más coincide con el episodio; ante empate,
        # el onset más próximo al comienzo del episodio.
        candidates.append((
            overlap,
            -abs(onset - start_m),
            event,
        ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )

    return candidates[0][2]


def build_braking_point_comparison(episode, reference_events, comparison_events):
    """
    Construye la comparación sólo para episodios cuyo canal de acción incluye
    brake. El episodio existente funciona como ancla espacial conservadora.
    """
    channels = set(episode.get("action_channels", []) or [])

    if "brake" not in channels:
        return None

    reference_event = _event_for_episode(reference_events, episode)
    comparison_event = _event_for_episode(comparison_events, episode)

    if reference_event is None or comparison_event is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "paired_braking_event_not_found",
            "authorized_numeric_coaching": False,
        }

    reference_onset = _safe_float(reference_event.get("onset_distance_m"))
    comparison_onset = _safe_float(comparison_event.get("onset_distance_m"))

    if reference_onset is None or comparison_onset is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "invalid_onset_distance",
            "authorized_numeric_coaching": False,
        }

    delta_m = comparison_onset - reference_onset

    if abs(delta_m) > BRAKING_POINT_MAX_PAIRED_ONSET_DELTA_M:
        return {
            "status": "UNAVAILABLE",
            "reason": "paired_onset_delta_exceeds_guard",
            "reference_onset_m": _safe_float(reference_onset),
            "comparison_onset_m": _safe_float(comparison_onset),
            "comparison_minus_reference_m": _safe_float(delta_m),
            "authorized_numeric_coaching": False,
        }

    if delta_m <= -BRAKING_POINT_MIN_COACHING_DELTA_M:
        relative_direction = "earlier_in_comparison_lap"
        coaching_direction = "later"
        authorized = True
    elif delta_m >= BRAKING_POINT_MIN_COACHING_DELTA_M:
        relative_direction = "later_in_comparison_lap"
        coaching_direction = "earlier"
        authorized = True
    else:
        relative_direction = "similar_to_reference"
        coaching_direction = None
        authorized = False

    reference_event_id = reference_event.get("braking_event_id")
    comparison_event_id = comparison_event.get("braking_event_id")
    pair_id = (
        f"{reference_event_id}|{comparison_event_id}"
        if reference_event_id and comparison_event_id
        else None
    )

    return {
        "status": "VALID",
        "braking_pair_id": pair_id,
        "reference_event_id": reference_event_id,
        "comparison_event_id": comparison_event_id,
        "reference_onset_m": _safe_float(reference_onset),
        "comparison_onset_m": _safe_float(comparison_onset),
        "comparison_minus_reference_m": _safe_float(delta_m),
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        # Redondeo a metro entero para el objetivo de coaching; el delta bruto
        # se conserva arriba para diagnóstico.
        "coaching_magnitude_m": (
            int(round(abs(delta_m)))
            if authorized
            else None
        ),
        "authorized_numeric_coaching": bool(authorized),
        "reference_event": {
            "confirmation_distance_m": reference_event.get("confirmation_distance_m"),
            "release_distance_m": reference_event.get("release_distance_m"),
            "release_confirmed": bool(reference_event.get("release_confirmed")),
            "peak_brake_percent": reference_event.get("peak_brake_percent"),
        },
        "comparison_event": {
            "confirmation_distance_m": comparison_event.get("confirmation_distance_m"),
            "release_distance_m": comparison_event.get("release_distance_m"),
            "release_confirmed": bool(comparison_event.get("release_confirmed")),
            "peak_brake_percent": comparison_event.get("peak_brake_percent"),
        },
    }



def build_brake_release_point_comparison(
    episode,
    reference_events,
    comparison_events,
):
    """
    Compara el punto físico de liberación del freno del mismo evento emparejado.

    Semántica espacial (distancia de vuelta creciente):
    - delta < 0: la vuelta comparada liberó antes -> target later;
    - delta > 0: la vuelta comparada liberó después -> target earlier.

    Sólo se autoriza coaching si ambas liberaciones fueron confirmadas por la
    histéresis del detector. No interpreta trail braking ni calidad técnica.
    """
    channels = set(episode.get("action_channels", []) or [])
    if "brake" not in channels:
        return None

    reference_event = _event_for_episode(reference_events, episode)
    comparison_event = _event_for_episode(comparison_events, episode)

    if reference_event is None or comparison_event is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "paired_braking_event_not_found",
            "authorized_numeric_coaching": False,
        }

    reference_event_id = reference_event.get("braking_event_id")
    comparison_event_id = comparison_event.get("braking_event_id")
    pair_id = (
        f"{reference_event_id}|{comparison_event_id}"
        if reference_event_id and comparison_event_id
        else None
    )

    reference_release = _safe_float(reference_event.get("release_distance_m"))
    comparison_release = _safe_float(comparison_event.get("release_distance_m"))

    if reference_release is None or comparison_release is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "invalid_release_distance",
            "braking_pair_id": pair_id,
            "reference_event_id": reference_event_id,
            "comparison_event_id": comparison_event_id,
            "authorized_numeric_coaching": False,
        }

    release_confirmed = (
        bool(reference_event.get("release_confirmed"))
        and bool(comparison_event.get("release_confirmed"))
    )

    delta_m = comparison_release - reference_release

    if abs(delta_m) > BRAKE_RELEASE_POINT_MAX_PAIRED_DELTA_M:
        return {
            "status": "UNAVAILABLE",
            "reason": "paired_release_delta_exceeds_guard",
            "braking_pair_id": pair_id,
            "reference_event_id": reference_event_id,
            "comparison_event_id": comparison_event_id,
            "reference_release_m": _safe_float(reference_release),
            "comparison_release_m": _safe_float(comparison_release),
            "comparison_minus_reference_m": _safe_float(delta_m),
            "authorized_numeric_coaching": False,
        }

    if not release_confirmed:
        return {
            "status": "UNAVAILABLE",
            "reason": "release_not_confirmed_in_both_laps",
            "braking_pair_id": pair_id,
            "reference_event_id": reference_event_id,
            "comparison_event_id": comparison_event_id,
            "reference_release_m": _safe_float(reference_release),
            "comparison_release_m": _safe_float(comparison_release),
            "comparison_minus_reference_m": _safe_float(delta_m),
            "authorized_numeric_coaching": False,
        }

    if delta_m <= -BRAKE_RELEASE_POINT_MIN_COACHING_DELTA_M:
        relative_direction = "earlier_in_comparison_lap"
        coaching_direction = "later"
        authorized = True
    elif delta_m >= BRAKE_RELEASE_POINT_MIN_COACHING_DELTA_M:
        relative_direction = "later_in_comparison_lap"
        coaching_direction = "earlier"
        authorized = True
    else:
        relative_direction = "similar_to_reference"
        coaching_direction = None
        authorized = False

    return {
        "status": "VALID",
        "braking_pair_id": pair_id,
        "reference_event_id": reference_event_id,
        "comparison_event_id": comparison_event_id,
        "reference_release_m": _safe_float(reference_release),
        "comparison_release_m": _safe_float(comparison_release),
        "comparison_minus_reference_m": _safe_float(delta_m),
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": (
            int(round(abs(delta_m)))
            if authorized
            else None
        ),
        "authorized_numeric_coaching": bool(authorized),
        "reference_event": {
            "onset_distance_m": reference_event.get("onset_distance_m"),
            "confirmation_distance_m": reference_event.get("confirmation_distance_m"),
            "release_confirmed": bool(reference_event.get("release_confirmed")),
            "peak_brake_percent": reference_event.get("peak_brake_percent"),
        },
        "comparison_event": {
            "onset_distance_m": comparison_event.get("onset_distance_m"),
            "confirmation_distance_m": comparison_event.get("confirmation_distance_m"),
            "release_confirmed": bool(comparison_event.get("release_confirmed")),
            "peak_brake_percent": comparison_event.get("peak_brake_percent"),
        },
    }


def _release_assignment_score(episode, result):
    """
    Decide qué episodio recibe coaching individual de release cuando la misma
    frenada toca más de un episodio.

    Prioriza:
    1) que los puntos de release caigan dentro/tocando el episodio;
    2) cercanía espacial del episodio al final de la frenada;
    3) |action_time_loss_s|.
    """
    if not isinstance(episode, dict) or not isinstance(result, dict):
        return (-1, -1e9, -1.0)

    start_m = _safe_float(episode.get("start_distance_m"))
    end_m = _safe_float(episode.get("end_distance_m"))
    if start_m is None or end_m is None or end_m <= start_m:
        return (-1, -1e9, -1.0)

    ref_release = _safe_float(result.get("reference_release_m"))
    cmp_release = _safe_float(result.get("comparison_release_m"))
    releases = [v for v in (ref_release, cmp_release) if v is not None]
    if not releases:
        return (-1, -1e9, -1.0)

    expanded_start = start_m - EPISODE_ASSOCIATION_TOLERANCE_M
    expanded_end = end_m + EPISODE_ASSOCIATION_TOLERANCE_M
    inside_count = sum(
        1 for value in releases
        if expanded_start <= value <= expanded_end
    )

    def distance_to_interval(value):
        if start_m <= value <= end_m:
            return 0.0
        if value < start_m:
            return start_m - value
        return value - end_m

    proximity = -max(distance_to_interval(value) for value in releases)
    action_loss = abs(_safe_float(episode.get("action_time_loss_s")) or 0.0)

    return (inside_count, proximity, action_loss)


def _deduplicate_release_pair_assignments(candidates):
    """
    Un par físico ref/comparison puede autorizar un objetivo de release en un
    solo episodio. Esto es independiente de la asignación del onset.
    """
    groups = {}

    for episode, result in candidates:
        if not isinstance(result, dict) or result.get("status") != "VALID":
            continue
        pair_id = result.get("braking_pair_id")
        if not pair_id:
            continue
        groups.setdefault(str(pair_id), []).append((episode, result))

    for pair_id, rows in groups.items():
        if len(rows) <= 1:
            continue

        winner_episode, winner_result = max(
            rows,
            key=lambda row: _release_assignment_score(row[0], row[1]),
        )

        winner_key = {
            "zone_id": winner_episode.get("zone_id"),
            "start_distance_m": _safe_float(winner_episode.get("start_distance_m")),
            "end_distance_m": _safe_float(winner_episode.get("end_distance_m")),
        }

        for episode, result in rows:
            if episode is winner_episode and result is winner_result:
                result["deduplication_status"] = "PRIMARY_ASSIGNMENT"
                continue

            result["status"] = "DUPLICATE"
            result["reason"] = "same_brake_release_assigned_to_another_episode"
            result["authorized_numeric_coaching"] = False
            result["coaching_direction"] = None
            result["coaching_magnitude_m"] = None
            result["deduplication_status"] = "SUPPRESSED_DUPLICATE"
            result["primary_assignment"] = dict(winner_key)


def _episode_assignment_score(episode, result):
    """
    Puntaje determinista para decidir qué episodio recibe un evento físico
    cuando la misma frenada toca más de un driver_action_episode.

    Prioridad:
    1) mayor solapamiento del episodio con la fase de frenada de ambas vueltas;
    2) comienzo del episodio más próximo al onset comparado/referencia;
    3) mayor |action_time_loss_s|.
    """
    if not isinstance(episode, dict) or not isinstance(result, dict):
        return (-1.0, -1.0, -1.0)

    start_m = _safe_float(episode.get("start_distance_m"))
    end_m = _safe_float(episode.get("end_distance_m"))
    if start_m is None or end_m is None or end_m <= start_m:
        return (-1.0, -1.0, -1.0)

    ref_onset = _safe_float(result.get("reference_onset_m"))
    cmp_onset = _safe_float(result.get("comparison_onset_m"))

    ref_event = result.get("reference_event", {}) or {}
    cmp_event = result.get("comparison_event", {}) or {}
    ref_release = _safe_float(ref_event.get("release_distance_m"))
    cmp_release = _safe_float(cmp_event.get("release_distance_m"))

    overlaps = []
    if ref_onset is not None and ref_release is not None and ref_release > ref_onset:
        overlaps.append(_interval_overlap(start_m, end_m, ref_onset, ref_release))
    if cmp_onset is not None and cmp_release is not None and cmp_release > cmp_onset:
        overlaps.append(_interval_overlap(start_m, end_m, cmp_onset, cmp_release))

    overlap_score = min(overlaps) if overlaps else 0.0

    onset_distances = []
    if ref_onset is not None:
        onset_distances.append(abs(start_m - ref_onset))
    if cmp_onset is not None:
        onset_distances.append(abs(start_m - cmp_onset))
    onset_proximity = -min(onset_distances) if onset_distances else -1e9

    action_loss = abs(_safe_float(episode.get("action_time_loss_s")) or 0.0)

    return (overlap_score, onset_proximity, action_loss)


def _deduplicate_braking_pair_assignments(candidates):
    """
    Un par de eventos físicos ref/comparison puede autorizar coaching numérico
    en un solo episodio. Los demás conservan diagnóstico, pero quedan marcados
    como DUPLICATE y sin autorización de coaching.
    """
    groups = {}

    for episode, result in candidates:
        if not isinstance(result, dict) or result.get("status") != "VALID":
            continue
        pair_id = result.get("braking_pair_id")
        if not pair_id:
            continue
        groups.setdefault(str(pair_id), []).append((episode, result))

    for pair_id, rows in groups.items():
        if len(rows) <= 1:
            continue

        winner_episode, winner_result = max(
            rows,
            key=lambda row: _episode_assignment_score(row[0], row[1]),
        )

        winner_key = {
            "zone_id": winner_episode.get("zone_id"),
            "start_distance_m": _safe_float(winner_episode.get("start_distance_m")),
            "end_distance_m": _safe_float(winner_episode.get("end_distance_m")),
        }

        for episode, result in rows:
            if episode is winner_episode and result is winner_result:
                result["deduplication_status"] = "PRIMARY_ASSIGNMENT"
                continue

            result["status"] = "DUPLICATE"
            result["reason"] = "same_braking_event_assigned_to_another_episode"
            result["authorized_numeric_coaching"] = False
            result["coaching_direction"] = None
            result["coaching_magnitude_m"] = None
            result["deduplication_status"] = "SUPPRESSED_DUPLICATE"
            result["primary_assignment"] = dict(winner_key)


def enrich_objective_with_braking_points(comparison, objective_analysis):
    """
    Enriquece in-place el objective_analysis existente.

    Agrega dos hechos independientes:
    - braking_point_comparison: inicio de frenada;
    - brake_release_point_comparison: liberación de freno.

    No cambia ranking, zonas, deltas, episodios, evidencia ni clasificación.
    Cada hecho físico sólo puede autorizar coaching cuantitativo en un episodio
    por comparación, pero onset y release pueden pertenecer a episodios
    distintos.
    """
    if not isinstance(objective_analysis, dict):
        return objective_analysis

    reference_events = detect_braking_events(comparison, "brake_a")
    comparison_events = detect_braking_events(comparison, "brake_b")

    ranking = objective_analysis.get("driver_action_episode_ranking", [])

    onset_by_key = {}
    release_by_key = {}
    onset_candidate_rows = []
    release_candidate_rows = []

    if isinstance(ranking, list):
        for episode in ranking:
            if not isinstance(episode, dict):
                continue

            onset_result = build_braking_point_comparison(
                episode,
                reference_events,
                comparison_events,
            )
            release_result = build_brake_release_point_comparison(
                episode,
                reference_events,
                comparison_events,
            )

            if onset_result is not None:
                episode["braking_point_comparison"] = onset_result
                onset_candidate_rows.append((episode, onset_result))

            if release_result is not None:
                episode["brake_release_point_comparison"] = release_result
                release_candidate_rows.append((episode, release_result))

        _deduplicate_braking_pair_assignments(onset_candidate_rows)
        _deduplicate_release_pair_assignments(release_candidate_rows)

        for episode, result in onset_candidate_rows:
            key = (
                episode.get("zone_id"),
                _safe_float(episode.get("start_distance_m")),
                _safe_float(episode.get("end_distance_m")),
            )
            onset_by_key[key] = result

        for episode, result in release_candidate_rows:
            key = (
                episode.get("zone_id"),
                _safe_float(episode.get("start_distance_m")),
                _safe_float(episode.get("end_distance_m")),
            )
            release_by_key[key] = result

    # Mantiene coherencia con las copias locales guardadas dentro de cada zona.
    loss_ranking = objective_analysis.get("loss_ranking", [])

    if isinstance(loss_ranking, list):
        for zone in loss_ranking:
            if not isinstance(zone, dict):
                continue
            for episode in zone.get("driver_action_episodes", []) or []:
                if not isinstance(episode, dict):
                    continue
                key = (
                    episode.get("zone_id"),
                    _safe_float(episode.get("start_distance_m")),
                    _safe_float(episode.get("end_distance_m")),
                )
                if key in onset_by_key:
                    episode["braking_point_comparison"] = dict(onset_by_key[key])
                if key in release_by_key:
                    episode["brake_release_point_comparison"] = dict(release_by_key[key])

    objective_analysis["braking_point_detection"] = {
        "version": BRAKING_POINT_VERSION,
        "schema_version": BRAKING_POINT_SCHEMA_VERSION,
        "features": [
            "brake_onset",
            "brake_release",
        ],
        "reference_event_count": len(reference_events),
        "comparison_event_count": len(comparison_events),
        "config": braking_point_config_summary(),
        "onset_deduplication_rule": "one_physical_braking_pair_per_onset_coaching_assignment",
        "release_deduplication_rule": "one_physical_braking_pair_per_release_coaching_assignment",
    }

    return objective_analysis
