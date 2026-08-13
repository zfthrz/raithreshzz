import math

import numpy as np
import pandas as pd


THROTTLE_POINT_VERSION = "1.1"
THROTTLE_POINT_SCHEMA_VERSION = "1.1"


# ============================================================
# THROTTLE POINT v1.1 - DETERMINISTIC
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
        "partial_lift_detection": False,
    }


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

        events.append({
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
        })

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

    objective_analysis["throttle_point_detection"] = {
        "version": THROTTLE_POINT_VERSION,
        "schema_version": THROTTLE_POINT_SCHEMA_VERSION,
        "features": [
            "throttle_onset",
            "throttle_release",
        ],
        "reference_event_count": len(reference_events),
        "comparison_event_count": len(comparison_events),
        "paired_event_count": len(paired_events),
        "config": throttle_point_config_summary(),
        "onset_deduplication_rule":
            "one_physical_throttle_pair_per_onset_coaching_assignment",
        "release_deduplication_rule":
            "one_physical_throttle_pair_per_release_coaching_assignment",
    }

    return objective_analysis
