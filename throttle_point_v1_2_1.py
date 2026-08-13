import math

import numpy as np
import pandas as pd


THROTTLE_POINT_VERSION = "1.2.1"
THROTTLE_POINT_SCHEMA_VERSION = "1.2"


# ============================================================
# THROTTLE POINT v1.2.1 - DETERMINISTIC
# ============================================================
#
# Objetivo:
# - detectar eventos físicos de acelerador en throttle_a / throttle_b;
# - comparar por separado:
#     * throttle onset: primera reaplicación real del acelerador;
#     * throttle release: liberación real del acelerador;
# - asociar cada punto físico al driver_action_episode de throttle más cercano;
# - deduplicar onset y release de forma independiente;
# - autorizar coaching numérico sólo fuera de una zona muerta conservadora.
#
# No diagnostica tracción, wheelspin, balance, línea, "mejor salida",
# lift-and-coast ni causa de la pérdida.
#
# v1.2 agrega DOS observaciones independientes sin modificar onset/release:
# - full_throttle_attainment:
#     primer punto >= 95 % confirmado por >= 90 % durante 12 m;
# - partial_lift:
#     excursión down-up recuperada dentro de un evento activo, con caída
#     >= 20 pp, piso >= 20 %, duración >= 8 m y recuperación cerca del nivel
#     previo. No se interpreta como lift-and-coast ni como error de técnica.
#
# En v1.2 estas métricas son OBSERVACIONALES:
# - no cambian ranking;
# - no autorizan coaching numérico;
# - no cambian el pairing físico v1.1.
# ============================================================

THROTTLE_ONSET_THRESHOLD_PERCENT = 5.0
THROTTLE_CONFIRM_THRESHOLD_PERCENT = 20.0
THROTTLE_RELEASE_THRESHOLD_PERCENT = 2.0

# Una reaplicación suave debe alcanzar 20 % dentro de una distancia razonable
# para considerarse un evento real y no un roce del pedal.
THROTTLE_CONFIRM_MAX_DISTANCE_M = 60.0

# La liberación debe sostenerse para evitar interpretar dips de señal o cortes
# muy breves como un lift real.
THROTTLE_RELEASE_CONFIRM_DISTANCE_M = 8.0

MIN_CONFIRMED_THROTTLE_EVENT_DISTANCE_M = 10.0

# Onset/release se asocian por proximidad física del punto al episodio.
THROTTLE_POINT_ASSOCIATION_TOLERANCE_M = 30.0

# Pairing global y monótono de eventos físicos. Permite eventos faltantes
# sin desplazar toda la secuencia de IDs.
THROTTLE_EVENT_PAIR_GAP_PENALTY = 60.0
THROTTLE_EVENT_PAIR_RELEASE_WEIGHT = 0.20

THROTTLE_ONSET_MIN_COACHING_DELTA_M = 8.0
THROTTLE_RELEASE_MIN_COACHING_DELTA_M = 8.0

THROTTLE_ONSET_MAX_PAIRED_DELTA_M = 150.0
THROTTLE_RELEASE_MAX_PAIRED_DELTA_M = 150.0


# Full-throttle attainment: casi pleno + confirmación sostenida.
FULL_THROTTLE_THRESHOLD_PERCENT = 95.0
FULL_THROTTLE_HOLD_FLOOR_PERCENT = 90.0
FULL_THROTTLE_CONFIRM_DISTANCE_M = 12.0
FULL_THROTTLE_ATTAINMENT_DEADBAND_M = 8.0

# Partial lift: excursión parcial recuperada, distinta de un release real.
PARTIAL_LIFT_MIN_PRE_LEVEL_PERCENT = 60.0
PARTIAL_LIFT_MIN_DROP_PP = 20.0
PARTIAL_LIFT_MIN_THROTTLE_PERCENT = 20.0
PARTIAL_LIFT_MIN_DISTANCE_M = 8.0
PARTIAL_LIFT_RECOVERY_TOLERANCE_PP = 8.0
PARTIAL_LIFT_MAX_EVENT_DISTANCE_M = 60.0



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


def throttle_point_config_summary():
    return {
        "enabled": True,
        "version": THROTTLE_POINT_VERSION,
        "schema_version": THROTTLE_POINT_SCHEMA_VERSION,
        "onset_threshold_percent": THROTTLE_ONSET_THRESHOLD_PERCENT,
        "confirm_threshold_percent": THROTTLE_CONFIRM_THRESHOLD_PERCENT,
        "release_threshold_percent": THROTTLE_RELEASE_THRESHOLD_PERCENT,
        "confirm_max_distance_m": THROTTLE_CONFIRM_MAX_DISTANCE_M,
        "release_confirm_distance_m": THROTTLE_RELEASE_CONFIRM_DISTANCE_M,
        "min_confirmed_event_distance_m": MIN_CONFIRMED_THROTTLE_EVENT_DISTANCE_M,
        "point_association_tolerance_m": THROTTLE_POINT_ASSOCIATION_TOLERANCE_M,
        "event_pairing": "monotonic_sequence_alignment",
        "event_pair_gap_penalty": THROTTLE_EVENT_PAIR_GAP_PENALTY,
        "event_pair_release_weight": THROTTLE_EVENT_PAIR_RELEASE_WEIGHT,
        "onset_min_coaching_delta_m": THROTTLE_ONSET_MIN_COACHING_DELTA_M,
        "release_min_coaching_delta_m": THROTTLE_RELEASE_MIN_COACHING_DELTA_M,
        "max_paired_onset_delta_m": THROTTLE_ONSET_MAX_PAIRED_DELTA_M,
        "max_paired_release_delta_m": THROTTLE_RELEASE_MAX_PAIRED_DELTA_M,
        "onset_source": "first_crossing_after_confirmed_release",
        "release_source": "first_release_threshold_crossing_confirmed_by_distance",
        "confirmation_rule": "must_reach_confirm_threshold_before_max_distance",
        "onset_difference_source": "comparison_onset_minus_reference_onset",
        "release_difference_source": "comparison_release_minus_reference_release",
        "partial_lift_detection": True,
        "partial_lift_min_pre_level_percent":
            PARTIAL_LIFT_MIN_PRE_LEVEL_PERCENT,
        "partial_lift_min_drop_pp":
            PARTIAL_LIFT_MIN_DROP_PP,
        "partial_lift_min_throttle_percent":
            PARTIAL_LIFT_MIN_THROTTLE_PERCENT,
        "partial_lift_min_distance_m":
            PARTIAL_LIFT_MIN_DISTANCE_M,
        "partial_lift_recovery_tolerance_pp":
            PARTIAL_LIFT_RECOVERY_TOLERANCE_PP,
        "partial_lift_max_event_distance_m":
            PARTIAL_LIFT_MAX_EVENT_DISTANCE_M,
        "full_throttle_attainment_detection": True,
        "full_throttle_threshold_percent":
            FULL_THROTTLE_THRESHOLD_PERCENT,
        "full_throttle_hold_floor_percent":
            FULL_THROTTLE_HOLD_FLOOR_PERCENT,
        "full_throttle_confirm_distance_m":
            FULL_THROTTLE_CONFIRM_DISTANCE_M,
        "full_throttle_attainment_deadband_m":
            FULL_THROTTLE_ATTAINMENT_DEADBAND_M,
    }



def _detect_full_throttle_attainment(
    distance,
    throttle,
    start_index,
    end_index,
):
    """
    Primer punto >=95 % que se sostiene >=90 % durante al menos 12 m.

    Devuelve None si sólo existe un pico transitorio o si el evento termina
    antes de completar la confirmación.
    """
    if (
        start_index is None
        or end_index is None
        or end_index <= start_index
    ):
        return None

    for index in range(start_index, end_index + 1):
        value = float(throttle[index])
        if value < FULL_THROTTLE_THRESHOLD_PERCENT:
            continue

        start_m = float(distance[index])
        confirmed = False

        for check in range(index, end_index + 1):
            if float(throttle[check]) < FULL_THROTTLE_HOLD_FLOOR_PERCENT:
                break

            if (
                float(distance[check]) - start_m
                >= FULL_THROTTLE_CONFIRM_DISTANCE_M
            ):
                confirmed = True
                break

        if confirmed:
            return {
                "distance_m":
                    _safe_float(start_m),
                "threshold_percent":
                    FULL_THROTTLE_THRESHOLD_PERCENT,
                "hold_floor_percent":
                    FULL_THROTTLE_HOLD_FLOOR_PERCENT,
                "confirm_distance_m":
                    FULL_THROTTLE_CONFIRM_DISTANCE_M,
                "confirmed":
                    True,
            }

    return None


def _detect_partial_lifts(
    distance,
    throttle,
    start_index,
    end_index,
):
    """
    Detecta excursiones parciales recuperadas dentro de un evento activo.

    Requisitos:
    - nivel previo >=60 %;
    - caída >=20 pp;
    - el mínimo permanece >=20 % (si cae más, la reducción es demasiado
      profunda para etiquetarla como partial lift en esta versión);
    - la excursión dura >=8 m;
    - recupera hasta <=8 pp del nivel previo;
    - longitud máxima 60 m.

    No intenta inferir intención ni técnica.
    """
    if (
        start_index is None
        or end_index is None
        or end_index <= start_index
    ):
        return []

    lifts = []

    running_peak_value = float(throttle[start_index])
    running_peak_index = start_index

    candidate = None

    for index in range(start_index + 1, end_index + 1):
        d = float(distance[index])
        value = float(throttle[index])

        if candidate is None:
            if value > running_peak_value:
                running_peak_value = value
                running_peak_index = index

            if (
                running_peak_value >= PARTIAL_LIFT_MIN_PRE_LEVEL_PERCENT
                and value >= PARTIAL_LIFT_MIN_THROTTLE_PERCENT
                and (
                    running_peak_value - value
                    >= PARTIAL_LIFT_MIN_DROP_PP
                )
            ):
                candidate = {
                    "baseline_percent":
                        running_peak_value,
                    "baseline_distance_m":
                        float(distance[running_peak_index]),
                    "start_index":
                        index,
                    "start_distance_m":
                        d,
                    "min_index":
                        index,
                    "min_percent":
                        value,
                }
            continue

        # Candidate active.
        if value < PARTIAL_LIFT_MIN_THROTTLE_PERCENT:
            # Se aproxima demasiado a release: no es partial lift recuperado.
            candidate = None
            running_peak_value = value
            running_peak_index = index
            continue

        if value < candidate["min_percent"]:
            candidate["min_percent"] = value
            candidate["min_index"] = index

        length_m = d - candidate["start_distance_m"]

        if length_m > PARTIAL_LIFT_MAX_EVENT_DISTANCE_M:
            candidate = None
            running_peak_value = value
            running_peak_index = index
            continue

        recovery_level = (
            candidate["baseline_percent"]
            - PARTIAL_LIFT_RECOVERY_TOLERANCE_PP
        )

        if value >= recovery_level:
            if length_m >= PARTIAL_LIFT_MIN_DISTANCE_M:
                min_index = candidate["min_index"]

                lifts.append({
                    "partial_lift_id":
                        f"partial_lift:{len(lifts) + 1:02d}",
                    "start_distance_m":
                        _safe_float(
                            candidate["start_distance_m"]
                        ),
                    "minimum_distance_m":
                        _safe_float(
                            distance[min_index]
                        ),
                    "recovery_distance_m":
                        _safe_float(d),
                    "length_m":
                        _safe_float(length_m),
                    "pre_lift_percent":
                        _safe_float(
                            candidate["baseline_percent"]
                        ),
                    "minimum_throttle_percent":
                        _safe_float(
                            candidate["min_percent"]
                        ),
                    "depth_pp":
                        _safe_float(
                            candidate["baseline_percent"]
                            - candidate["min_percent"]
                        ),
                    "recovered":
                        True,
                })

            candidate = None
            running_peak_value = value
            running_peak_index = index

    return lifts

def detect_throttle_events(comparison, throttle_column):
    """
    Detecta eventos físicos de acelerador en una señal individual alineada por
    distancia.

    Onset:
      primer cruce >= 5 %, confirmado si alcanza >= 20 % dentro de 60 m.

    Release:
      primer cruce <= 2 %, confirmado si permanece liberado >= 8 m.

    Un evento que llega al final de la traza sin release confirmado conserva
    onset válido pero release_confirmed=False.
    """
    if not isinstance(comparison, pd.DataFrame):
        return []

    if (
        "distance" not in comparison.columns
        or throttle_column not in comparison.columns
    ):
        return []

    distance = pd.to_numeric(
        comparison["distance"],
        errors="coerce",
    ).to_numpy(dtype=float)

    throttle = pd.to_numeric(
        comparison[throttle_column],
        errors="coerce",
    ).to_numpy(dtype=float)

    valid = np.isfinite(distance) & np.isfinite(throttle)
    if not np.any(valid):
        return []

    distance = distance[valid]
    throttle = throttle[valid]

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

        if length_m < MIN_CONFIRMED_THROTTLE_EVENT_DISTANCE_M:
            reset()
            return

        if peak_index is None:
            local = throttle[candidate_index:end_index + 1]
            if len(local) == 0:
                reset()
                return
            chosen_peak_index = candidate_index + int(np.nanargmax(local))
        else:
            chosen_peak_index = peak_index

        full_attainment = _detect_full_throttle_attainment(
            distance,
            throttle,
            confirmation_index,
            end_index,
        )

        partial_lifts = _detect_partial_lifts(
            distance,
            throttle,
            confirmation_index,
            end_index,
        )

        event = {
            "throttle_event_id":
                f"{throttle_column}:{len(events) + 1:02d}",
            "onset_distance_m": _safe_float(onset_m),
            "confirmation_distance_m": _safe_float(confirm_m),
            "release_distance_m": _safe_float(release_m),
            "release_confirmed": bool(release_confirmed),
            "length_m": _safe_float(length_m),
            "peak_throttle_percent":
                _safe_float(throttle[chosen_peak_index]),
            "peak_distance_m":
                _safe_float(distance[chosen_peak_index]),
            "confirmed": True,
            "full_throttle_attainment_confirmed":
                bool(full_attainment),
            "full_throttle_attainment_distance_m":
                (
                    full_attainment.get("distance_m")
                    if full_attainment
                    else None
                ),
            "distance_from_onset_to_full_throttle_m":
                (
                    _safe_float(
                        full_attainment["distance_m"] - onset_m
                    )
                    if full_attainment
                    else None
                ),
            "partial_lift_count":
                len(partial_lifts),
            "partial_lifts":
                partial_lifts,
        }

        events.append(event)

        reset()

    for index in range(len(distance)):
        d = float(distance[index])
        value = float(throttle[index])

        if state == "idle":
            if value >= THROTTLE_ONSET_THRESHOLD_PERCENT:
                candidate_index = index
                peak_index = index
                state = "candidate"

                if value >= THROTTLE_CONFIRM_THRESHOLD_PERCENT:
                    confirmation_index = index
                    state = "active"
            continue

        if peak_index is None or value > throttle[peak_index]:
            peak_index = index

        if state == "candidate":
            onset_m = float(distance[candidate_index])

            if value <= THROTTLE_RELEASE_THRESHOLD_PERCENT:
                reset()
                continue

            if d - onset_m > THROTTLE_CONFIRM_MAX_DISTANCE_M:
                reset()
                if value >= THROTTLE_ONSET_THRESHOLD_PERCENT:
                    candidate_index = index
                    peak_index = index
                    state = "candidate"
                    if value >= THROTTLE_CONFIRM_THRESHOLD_PERCENT:
                        confirmation_index = index
                        state = "active"
                continue

            if value >= THROTTLE_CONFIRM_THRESHOLD_PERCENT:
                confirmation_index = index
                state = "active"
            continue

        # state == active
        if value <= THROTTLE_RELEASE_THRESHOLD_PERCENT:
            if release_candidate_index is None:
                release_candidate_index = index
            else:
                released_distance = (
                    float(distance[index])
                    - float(distance[release_candidate_index])
                )
                if (
                    released_distance
                    >= THROTTLE_RELEASE_CONFIRM_DISTANCE_M
                ):
                    close_event(release_candidate_index, True)
            continue

        # Reaplicó antes de confirmar release: sigue siendo el mismo evento.
        release_candidate_index = None

    if state == "active":
        end_index = (
            release_candidate_index
            if release_candidate_index is not None
            else len(distance) - 1
        )
        close_event(end_index, False)

    return events


def _distance_to_interval(value, start_m, end_m):
    if start_m <= value <= end_m:
        return 0.0
    if value < start_m:
        return start_m - value
    return value - end_m


def _pair_id(reference_event, comparison_event):
    reference_event_id = (
        reference_event.get("throttle_event_id")
        if isinstance(reference_event, dict)
        else None
    )
    comparison_event_id = (
        comparison_event.get("throttle_event_id")
        if isinstance(comparison_event, dict)
        else None
    )
    pair_id = (
        f"{reference_event_id}|{comparison_event_id}"
        if reference_event_id and comparison_event_id
        else None
    )
    return pair_id, reference_event_id, comparison_event_id


def _pair_cost(reference_event, comparison_event):
    ref_onset = _safe_float(reference_event.get("onset_distance_m"))
    cmp_onset = _safe_float(comparison_event.get("onset_distance_m"))

    if ref_onset is None or cmp_onset is None:
        return None

    onset_delta = abs(cmp_onset - ref_onset)
    if onset_delta > THROTTLE_ONSET_MAX_PAIRED_DELTA_M:
        return None

    cost = onset_delta

    if (
        bool(reference_event.get("release_confirmed"))
        and bool(comparison_event.get("release_confirmed"))
    ):
        ref_release = _safe_float(reference_event.get("release_distance_m"))
        cmp_release = _safe_float(comparison_event.get("release_distance_m"))
        if ref_release is not None and cmp_release is not None:
            release_delta = abs(cmp_release - ref_release)
            cost += THROTTLE_EVENT_PAIR_RELEASE_WEIGHT * min(
                release_delta,
                THROTTLE_RELEASE_MAX_PAIRED_DELTA_M,
            )

    return float(cost)


def pair_throttle_events(reference_events, comparison_events):
    """
    Alineamiento monotónico uno-a-uno de eventos físicos.

    Puede saltar eventos faltantes en cualquiera de las dos vueltas, pero nunca
    cruza el orden de la secuencia. Esto evita emparejar un evento con el
    anterior/siguiente de la otra vuelta por mera proximidad al episodio.
    """
    refs = list(reference_events or [])
    cmps = list(comparison_events or [])

    n = len(refs)
    m = len(cmps)

    if n == 0 or m == 0:
        return []

    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    prev = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0

    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + THROTTLE_EVENT_PAIR_GAP_PENALTY
        prev[i][0] = ("skip_ref", i - 1, 0)

    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + THROTTLE_EVENT_PAIR_GAP_PENALTY
        prev[0][j] = ("skip_cmp", 0, j - 1)

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = []

            pair_cost = _pair_cost(refs[i - 1], cmps[j - 1])
            if pair_cost is not None:
                options.append((
                    dp[i - 1][j - 1] + pair_cost,
                    "pair",
                    i - 1,
                    j - 1,
                ))

            options.append((
                dp[i - 1][j] + THROTTLE_EVENT_PAIR_GAP_PENALTY,
                "skip_ref",
                i - 1,
                j,
            ))
            options.append((
                dp[i][j - 1] + THROTTLE_EVENT_PAIR_GAP_PENALTY,
                "skip_cmp",
                i,
                j - 1,
            ))

            best = min(
                options,
                key=lambda item: (
                    item[0],
                    0 if item[1] == "pair" else 1,
                ),
            )
            dp[i][j] = best[0]
            prev[i][j] = (best[1], best[2], best[3])

    pairs = []
    i, j = n, m

    while i > 0 or j > 0:
        step = prev[i][j]
        if step is None:
            break

        action, pi, pj = step

        if action == "pair":
            reference_event = refs[i - 1]
            comparison_event = cmps[j - 1]
            pair_id, ref_id, cmp_id = _pair_id(
                reference_event,
                comparison_event,
            )
            pairs.append({
                "throttle_pair_id": pair_id,
                "reference_event_id": ref_id,
                "comparison_event_id": cmp_id,
                "reference_event": reference_event,
                "comparison_event": comparison_event,
                "pair_cost": _pair_cost(
                    reference_event,
                    comparison_event,
                ),
            })

        i, j = pi, pj

    pairs.reverse()
    return pairs


def _paired_event_for_episode_by_point(pairs, episode, point_key):
    if not pairs or not isinstance(episode, dict):
        return None

    start_m = _safe_float(episode.get("start_distance_m"))
    end_m = _safe_float(episode.get("end_distance_m"))

    if start_m is None or end_m is None or end_m <= start_m:
        return None

    candidates = []

    for pair in pairs:
        reference_event = pair.get("reference_event") or {}
        comparison_event = pair.get("comparison_event") or {}

        if point_key == "release_distance_m":
            if (
                not bool(reference_event.get("release_confirmed"))
                or not bool(comparison_event.get("release_confirmed"))
            ):
                continue

        ref_point = _safe_float(reference_event.get(point_key))
        cmp_point = _safe_float(comparison_event.get(point_key))
        if ref_point is None or cmp_point is None:
            continue

        ref_distance = _distance_to_interval(
            ref_point,
            start_m,
            end_m,
        )
        cmp_distance = _distance_to_interval(
            cmp_point,
            start_m,
            end_m,
        )

        max_distance = max(ref_distance, cmp_distance)
        if max_distance > THROTTLE_POINT_ASSOCIATION_TOLERANCE_M:
            continue

        inside_count = (
            int(start_m <= ref_point <= end_m)
            + int(start_m <= cmp_point <= end_m)
        )

        anchor = start_m if point_key == "onset_distance_m" else end_m
        mean_anchor_distance = (
            abs(ref_point - anchor) + abs(cmp_point - anchor)
        ) / 2.0

        pair_cost = _safe_float(pair.get("pair_cost")) or 0.0

        candidates.append((
            inside_count,
            -max_distance,
            -mean_anchor_distance,
            -pair_cost,
            pair,
        ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item[:4],
        reverse=True,
    )
    return candidates[0][4]


def build_throttle_onset_comparison(
    episode,
    paired_events,
):
    channels = set(episode.get("action_channels", []) or [])
    if "throttle" not in channels:
        return None

    pair = _paired_event_for_episode_by_point(
        paired_events,
        episode,
        "onset_distance_m",
    )

    if pair is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "paired_throttle_onset_event_not_found",
            "authorized_numeric_coaching": False,
        }

    reference_event = pair["reference_event"]
    comparison_event = pair["comparison_event"]

    reference_onset = _safe_float(reference_event.get("onset_distance_m"))
    comparison_onset = _safe_float(comparison_event.get("onset_distance_m"))

    if reference_onset is None or comparison_onset is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "invalid_throttle_onset_distance",
            "authorized_numeric_coaching": False,
        }

    delta_m = comparison_onset - reference_onset

    if abs(delta_m) > THROTTLE_ONSET_MAX_PAIRED_DELTA_M:
        return {
            "status": "UNAVAILABLE",
            "reason": "paired_throttle_onset_delta_exceeds_guard",
            "reference_onset_m": reference_onset,
            "comparison_onset_m": comparison_onset,
            "comparison_minus_reference_m": delta_m,
            "authorized_numeric_coaching": False,
        }

    if delta_m <= -THROTTLE_ONSET_MIN_COACHING_DELTA_M:
        relative_direction = "earlier_in_comparison_lap"
        coaching_direction = "later"
        authorized = True
    elif delta_m >= THROTTLE_ONSET_MIN_COACHING_DELTA_M:
        relative_direction = "later_in_comparison_lap"
        coaching_direction = "earlier"
        authorized = True
    else:
        relative_direction = "similar_to_reference"
        coaching_direction = None
        authorized = False

    return {
        "status": "VALID",
        "throttle_pair_id": pair.get("throttle_pair_id"),
        "reference_event_id": pair.get("reference_event_id"),
        "comparison_event_id": pair.get("comparison_event_id"),
        "reference_onset_m": reference_onset,
        "comparison_onset_m": comparison_onset,
        "comparison_minus_reference_m": _safe_float(delta_m),
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))) if authorized else None,
        "authorized_numeric_coaching": bool(authorized),
        "event_pairing": "monotonic_sequence_alignment",
        "pair_cost": _safe_float(pair.get("pair_cost")),
        "reference_event": {
            "confirmation_distance_m": reference_event.get("confirmation_distance_m"),
            "release_distance_m": reference_event.get("release_distance_m"),
            "release_confirmed": bool(reference_event.get("release_confirmed")),
            "peak_throttle_percent": reference_event.get("peak_throttle_percent"),
        },
        "comparison_event": {
            "confirmation_distance_m": comparison_event.get("confirmation_distance_m"),
            "release_distance_m": comparison_event.get("release_distance_m"),
            "release_confirmed": bool(comparison_event.get("release_confirmed")),
            "peak_throttle_percent": comparison_event.get("peak_throttle_percent"),
        },
    }


def build_throttle_release_comparison(
    episode,
    paired_events,
):
    channels = set(episode.get("action_channels", []) or [])
    if "throttle" not in channels:
        return None

    pair = _paired_event_for_episode_by_point(
        paired_events,
        episode,
        "release_distance_m",
    )

    if pair is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "paired_throttle_release_event_not_found",
            "authorized_numeric_coaching": False,
        }

    reference_event = pair["reference_event"]
    comparison_event = pair["comparison_event"]

    reference_release = _safe_float(reference_event.get("release_distance_m"))
    comparison_release = _safe_float(comparison_event.get("release_distance_m"))

    if reference_release is None or comparison_release is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "invalid_throttle_release_distance",
            "authorized_numeric_coaching": False,
        }

    delta_m = comparison_release - reference_release

    if abs(delta_m) > THROTTLE_RELEASE_MAX_PAIRED_DELTA_M:
        return {
            "status": "UNAVAILABLE",
            "reason": "paired_throttle_release_delta_exceeds_guard",
            "reference_release_m": reference_release,
            "comparison_release_m": comparison_release,
            "comparison_minus_reference_m": delta_m,
            "authorized_numeric_coaching": False,
        }

    if delta_m <= -THROTTLE_RELEASE_MIN_COACHING_DELTA_M:
        relative_direction = "earlier_in_comparison_lap"
        coaching_direction = "later"
        authorized = True
    elif delta_m >= THROTTLE_RELEASE_MIN_COACHING_DELTA_M:
        relative_direction = "later_in_comparison_lap"
        coaching_direction = "earlier"
        authorized = True
    else:
        relative_direction = "similar_to_reference"
        coaching_direction = None
        authorized = False

    return {
        "status": "VALID",
        "throttle_pair_id": pair.get("throttle_pair_id"),
        "reference_event_id": pair.get("reference_event_id"),
        "comparison_event_id": pair.get("comparison_event_id"),
        "reference_release_m": reference_release,
        "comparison_release_m": comparison_release,
        "comparison_minus_reference_m": _safe_float(delta_m),
        "relative_direction": relative_direction,
        "coaching_direction": coaching_direction,
        "coaching_magnitude_m": int(round(abs(delta_m))) if authorized else None,
        "authorized_numeric_coaching": bool(authorized),
        "event_pairing": "monotonic_sequence_alignment",
        "pair_cost": _safe_float(pair.get("pair_cost")),
        "reference_event": {
            "onset_distance_m": reference_event.get("onset_distance_m"),
            "confirmation_distance_m": reference_event.get("confirmation_distance_m"),
            "peak_throttle_percent": reference_event.get("peak_throttle_percent"),
        },
        "comparison_event": {
            "onset_distance_m": comparison_event.get("onset_distance_m"),
            "confirmation_distance_m": comparison_event.get("confirmation_distance_m"),
            "peak_throttle_percent": comparison_event.get("peak_throttle_percent"),
        },
    }



def _paired_event_for_episode_by_overlap(
    pairs,
    episode,
):
    if not pairs or not isinstance(episode, dict):
        return None

    start_m = _safe_float(episode.get("start_distance_m"))
    end_m = _safe_float(episode.get("end_distance_m"))

    if start_m is None or end_m is None or end_m <= start_m:
        return None

    candidates = []

    for pair in pairs:
        ref = pair.get("reference_event") or {}
        cmp = pair.get("comparison_event") or {}

        ref_start = _safe_float(ref.get("onset_distance_m"))
        ref_end = _safe_float(ref.get("release_distance_m"))
        cmp_start = _safe_float(cmp.get("onset_distance_m"))
        cmp_end = _safe_float(cmp.get("release_distance_m"))

        if None in (ref_start, ref_end, cmp_start, cmp_end):
            continue

        def overlap(a0, a1, b0, b1):
            return max(0.0, min(a1, b1) - max(a0, b0))

        ref_overlap = overlap(start_m, end_m, ref_start, ref_end)
        cmp_overlap = overlap(start_m, end_m, cmp_start, cmp_end)
        total_overlap = ref_overlap + cmp_overlap

        ref_distance = min(
            abs(ref_start - end_m),
            abs(ref_end - start_m),
            0.0 if ref_overlap > 0 else float("inf"),
        )
        cmp_distance = min(
            abs(cmp_start - end_m),
            abs(cmp_end - start_m),
            0.0 if cmp_overlap > 0 else float("inf"),
        )

        if (
            total_overlap <= 0.0
            and min(ref_distance, cmp_distance)
            > THROTTLE_POINT_ASSOCIATION_TOLERANCE_M
        ):
            continue

        pair_cost = _safe_float(pair.get("pair_cost")) or 0.0

        candidates.append((
            total_overlap,
            -pair_cost,
            pair,
        ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda row: row[:2],
        reverse=True,
    )
    return candidates[0][2]


def build_full_throttle_attainment_comparison(
    episode,
    paired_events,
):
    """
    Observación v1.2.

    Usa el MISMO pair físico v1.1 asociado al onset del episodio.
    No autoriza coaching.
    """
    channels = set(episode.get("action_channels", []) or [])
    if "throttle" not in channels:
        return None

    pair = _paired_event_for_episode_by_point(
        paired_events,
        episode,
        "onset_distance_m",
    )

    if pair is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "paired_throttle_event_not_found",
            "authorized_numeric_coaching": False,
        }

    ref = pair.get("reference_event") or {}
    cmp = pair.get("comparison_event") or {}

    ref_ok = bool(ref.get("full_throttle_attainment_confirmed"))
    cmp_ok = bool(cmp.get("full_throttle_attainment_confirmed"))

    ref_m = _safe_float(
        ref.get("full_throttle_attainment_distance_m")
    )
    cmp_m = _safe_float(
        cmp.get("full_throttle_attainment_distance_m")
    )

    result = {
        "status": "VALID",
        "throttle_pair_id": pair.get("throttle_pair_id"),
        "reference_event_id": pair.get("reference_event_id"),
        "comparison_event_id": pair.get("comparison_event_id"),
        "reference_attainment_confirmed": ref_ok,
        "comparison_attainment_confirmed": cmp_ok,
        "reference_attainment_m": ref_m,
        "comparison_attainment_m": cmp_m,
        "reference_onset_to_full_throttle_m":
            _safe_float(
                ref.get(
                    "distance_from_onset_to_full_throttle_m"
                )
            ),
        "comparison_onset_to_full_throttle_m":
            _safe_float(
                cmp.get(
                    "distance_from_onset_to_full_throttle_m"
                )
            ),
        "comparison_minus_reference_m": None,
        "relative_direction": None,
        "authorized_numeric_coaching": False,
        "observational_only": True,
        "threshold_percent":
            FULL_THROTTLE_THRESHOLD_PERCENT,
        "hold_floor_percent":
            FULL_THROTTLE_HOLD_FLOOR_PERCENT,
        "confirm_distance_m":
            FULL_THROTTLE_CONFIRM_DISTANCE_M,
    }

    if ref_ok and cmp_ok and ref_m is not None and cmp_m is not None:
        delta_m = cmp_m - ref_m
        result["comparison_minus_reference_m"] = _safe_float(delta_m)

        if delta_m <= -FULL_THROTTLE_ATTAINMENT_DEADBAND_M:
            result["relative_direction"] = "earlier_in_comparison_lap"
        elif delta_m >= FULL_THROTTLE_ATTAINMENT_DEADBAND_M:
            result["relative_direction"] = "later_in_comparison_lap"
        else:
            result["relative_direction"] = "similar_to_reference"

    elif ref_ok and not cmp_ok:
        result["relative_direction"] = "reference_attained_comparison_not_confirmed"

    elif cmp_ok and not ref_ok:
        result["relative_direction"] = "comparison_attained_reference_not_confirmed"

    else:
        result["status"] = "UNAVAILABLE"
        result["reason"] = "full_throttle_not_confirmed_in_either_event"

    return result


def _partial_lifts_near_episode(
    event,
    episode,
):
    if not isinstance(event, dict) or not isinstance(episode, dict):
        return []

    start_m = _safe_float(episode.get("start_distance_m"))
    end_m = _safe_float(episode.get("end_distance_m"))

    if start_m is None or end_m is None:
        return []

    result = []

    for lift in event.get("partial_lifts", []) or []:
        if not isinstance(lift, dict):
            continue

        lift_start = _safe_float(lift.get("start_distance_m"))
        lift_end = _safe_float(lift.get("recovery_distance_m"))

        if lift_start is None or lift_end is None:
            continue

        distance_to_episode = min(
            _distance_to_interval(lift_start, start_m, end_m),
            _distance_to_interval(lift_end, start_m, end_m),
        )

        overlaps = (
            max(start_m, lift_start)
            <= min(end_m, lift_end)
        )

        if (
            overlaps
            or distance_to_episode
            <= THROTTLE_POINT_ASSOCIATION_TOLERANCE_M
        ):
            result.append(dict(lift))

    return result


def build_partial_lift_comparison(
    episode,
    paired_events,
):
    """
    Observación v1.2.

    No empareja lifts individuales ni genera coaching. Sólo informa cuántas
    excursiones parciales recuperadas aparecen en el pair físico asociado.
    """
    channels = set(episode.get("action_channels", []) or [])
    if "throttle" not in channels:
        return None

    pair = _paired_event_for_episode_by_overlap(
        paired_events,
        episode,
    )

    if pair is None:
        return None

    ref = pair.get("reference_event") or {}
    cmp = pair.get("comparison_event") or {}

    ref_lifts = _partial_lifts_near_episode(
        ref,
        episode,
    )
    cmp_lifts = _partial_lifts_near_episode(
        cmp,
        episode,
    )

    if not ref_lifts and not cmp_lifts:
        return None

    return {
        "status": "VALID",
        "throttle_pair_id": pair.get("throttle_pair_id"),
        "reference_event_id": pair.get("reference_event_id"),
        "comparison_event_id": pair.get("comparison_event_id"),
        "reference_partial_lift_count": len(ref_lifts),
        "comparison_partial_lift_count": len(cmp_lifts),
        "count_difference":
            len(cmp_lifts) - len(ref_lifts),
        "comparison_has_additional_partial_lift":
            len(cmp_lifts) > len(ref_lifts),
        "comparison_has_fewer_partial_lifts":
            len(cmp_lifts) < len(ref_lifts),
        "reference_partial_lifts": ref_lifts,
        "comparison_partial_lifts": cmp_lifts,
        "authorized_numeric_coaching": False,
        "observational_only": True,
    }

def _point_assignment_score(episode, result, point_name):
    if not isinstance(episode, dict) or not isinstance(result, dict):
        return (-1, -1e9, -1.0)

    start_m = _safe_float(episode.get("start_distance_m"))
    end_m = _safe_float(episode.get("end_distance_m"))
    if start_m is None or end_m is None or end_m <= start_m:
        return (-1, -1e9, -1.0)

    key = (
        "reference_onset_m"
        if point_name == "onset"
        else "reference_release_m"
    )
    key_cmp = (
        "comparison_onset_m"
        if point_name == "onset"
        else "comparison_release_m"
    )

    points = [
        value
        for value in (
            _safe_float(result.get(key)),
            _safe_float(result.get(key_cmp)),
        )
        if value is not None
    ]
    if not points:
        return (-1, -1e9, -1.0)

    inside_count = sum(
        1 for value in points
        if start_m <= value <= end_m
    )
    max_distance = max(
        _distance_to_interval(value, start_m, end_m)
        for value in points
    )
    action_loss = abs(
        _safe_float(episode.get("action_time_loss_s")) or 0.0
    )

    return (inside_count, -max_distance, action_loss)


def _deduplicate_assignments(candidates, point_name):
    groups = {}

    for episode, result in candidates:
        if (
            not isinstance(result, dict)
            or result.get("status") != "VALID"
        ):
            continue

        pair_id = result.get("throttle_pair_id")
        if not pair_id:
            continue

        groups.setdefault(str(pair_id), []).append(
            (episode, result)
        )

    for pair_id, rows in groups.items():
        if len(rows) <= 1:
            continue

        winner_episode, winner_result = max(
            rows,
            key=lambda row: _point_assignment_score(
                row[0],
                row[1],
                point_name,
            ),
        )

        winner_key = {
            "zone_id": winner_episode.get("zone_id"),
            "start_distance_m":
                _safe_float(winner_episode.get("start_distance_m")),
            "end_distance_m":
                _safe_float(winner_episode.get("end_distance_m")),
        }

        for episode, result in rows:
            if episode is winner_episode and result is winner_result:
                result["deduplication_status"] = "PRIMARY_ASSIGNMENT"
                continue

            result["status"] = "DUPLICATE"
            result["reason"] = (
                f"same_throttle_{point_name}_assigned_to_another_episode"
            )
            result["authorized_numeric_coaching"] = False
            result["coaching_direction"] = None
            result["coaching_magnitude_m"] = None
            result["deduplication_status"] = "SUPPRESSED_DUPLICATE"
            result["primary_assignment"] = dict(winner_key)


def enrich_objective_with_throttle_points(
    comparison,
    objective_analysis,
):
    """
    Enriquece in-place objective_analysis con:
      - throttle_onset_point_comparison
      - throttle_release_point_comparison
      - throttle_full_throttle_attainment_comparison (observacional)
      - throttle_partial_lift_comparison (observacional)

    No modifica ranking, zonas, deltas ni eventos de acción existentes.
    """
    if not isinstance(objective_analysis, dict):
        return objective_analysis

    reference_events = detect_throttle_events(
        comparison,
        "throttle_a",
    )
    comparison_events = detect_throttle_events(
        comparison,
        "throttle_b",
    )

    paired_events = pair_throttle_events(
        reference_events,
        comparison_events,
    )

    ranking = objective_analysis.get(
        "driver_action_episode_ranking",
        [],
    )

    onset_by_key = {}
    release_by_key = {}
    full_attainment_by_key = {}
    partial_lift_by_key = {}
    onset_candidates = []
    release_candidates = []

    if isinstance(ranking, list):
        for episode in ranking:
            if not isinstance(episode, dict):
                continue

            onset_result = build_throttle_onset_comparison(
                episode,
                paired_events,
            )
            release_result = build_throttle_release_comparison(
                episode,
                paired_events,
            )
            full_attainment_result = (
                build_full_throttle_attainment_comparison(
                    episode,
                    paired_events,
                )
            )
            partial_lift_result = (
                build_partial_lift_comparison(
                    episode,
                    paired_events,
                )
            )

            if onset_result is not None:
                episode[
                    "throttle_onset_point_comparison"
                ] = onset_result
                onset_candidates.append(
                    (episode, onset_result)
                )

            if release_result is not None:
                episode[
                    "throttle_release_point_comparison"
                ] = release_result
                release_candidates.append(
                    (episode, release_result)
                )

            if full_attainment_result is not None:
                episode[
                    "throttle_full_throttle_attainment_comparison"
                ] = full_attainment_result

            if partial_lift_result is not None:
                episode[
                    "throttle_partial_lift_comparison"
                ] = partial_lift_result

        _deduplicate_assignments(
            onset_candidates,
            "onset",
        )
        _deduplicate_assignments(
            release_candidates,
            "release",
        )

        for episode, result in onset_candidates:
            key = (
                episode.get("zone_id"),
                _safe_float(episode.get("start_distance_m")),
                _safe_float(episode.get("end_distance_m")),
            )
            onset_by_key[key] = result

        for episode, result in release_candidates:
            key = (
                episode.get("zone_id"),
                _safe_float(episode.get("start_distance_m")),
                _safe_float(episode.get("end_distance_m")),
            )
            release_by_key[key] = result

        for episode in ranking:
            if not isinstance(episode, dict):
                continue

            key = (
                episode.get("zone_id"),
                _safe_float(episode.get("start_distance_m")),
                _safe_float(episode.get("end_distance_m")),
            )

            if (
                "throttle_full_throttle_attainment_comparison"
                in episode
            ):
                full_attainment_by_key[key] = episode[
                    "throttle_full_throttle_attainment_comparison"
                ]

            if "throttle_partial_lift_comparison" in episode:
                partial_lift_by_key[key] = episode[
                    "throttle_partial_lift_comparison"
                ]

    loss_ranking = objective_analysis.get("loss_ranking", [])

    if isinstance(loss_ranking, list):
        for zone in loss_ranking:
            if not isinstance(zone, dict):
                continue
            for episode in (
                zone.get("driver_action_episodes", []) or []
            ):
                if not isinstance(episode, dict):
                    continue

                key = (
                    episode.get("zone_id"),
                    _safe_float(episode.get("start_distance_m")),
                    _safe_float(episode.get("end_distance_m")),
                )

                if key in onset_by_key:
                    episode[
                        "throttle_onset_point_comparison"
                    ] = dict(onset_by_key[key])

                if key in release_by_key:
                    episode[
                        "throttle_release_point_comparison"
                    ] = dict(release_by_key[key])

                if key in full_attainment_by_key:
                    episode[
                        "throttle_full_throttle_attainment_comparison"
                    ] = dict(full_attainment_by_key[key])

                if key in partial_lift_by_key:
                    episode[
                        "throttle_partial_lift_comparison"
                    ] = dict(partial_lift_by_key[key])

    objective_analysis["throttle_point_detection"] = {
        "version": THROTTLE_POINT_VERSION,
        "schema_version": THROTTLE_POINT_SCHEMA_VERSION,
        "features": [
            "throttle_onset",
            "throttle_release",
            "full_throttle_attainment",
            "partial_lift",
        ],
        "reference_event_count": len(reference_events),
        "comparison_event_count": len(comparison_events),
        "paired_event_count": len(paired_events),
        "config": throttle_point_config_summary(),
        "onset_deduplication_rule":
            "one_physical_throttle_pair_per_onset_coaching_assignment",
        "release_deduplication_rule":
            "one_physical_throttle_pair_per_release_coaching_assignment",
        "full_throttle_attainment_policy":
            "observational_only_no_numeric_coaching",
        "partial_lift_policy":
            "recovered_excursion_observational_only_no_numeric_coaching",
    }

    return objective_analysis
