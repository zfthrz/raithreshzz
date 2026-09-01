#!/usr/bin/env python3
"""D2.9 production ranker — product-principled deterministic priority policy.

Same fixed product rules as ``audit_d2_9_product_policy.py``, self-contained
for runtime use by the four LLM backends:

1. ORDER base = D2.1 (``global_rank`` determinista de Python).
2. PRIORITARIO = prefix de cobertura 55% de pérdida acumulada (constante de
   producto), EXTENDIDO sólo mientras el siguiente episodio sea ``strong`` y
   tenga un TARGET DIRECTO AUTORIZADO (brake/throttle con dirección), con tope
   de prioridad = 3 (foco del plan). NO usa canal-count (D2.8 refutado).
3. NO_ACCIONABLE = sólo cola de episodios OBSERVACIONALES (sin target directo)
   o ``weak`` con share negligible (<= 0.05). Los moderate/strong con target
   directo NUNCA se descartan por share.
4. TIE-BREAK de order: sólo entre pares adyacentes con diferencia relativa de
   pérdida <= 5% (near-tie); el de mayor ``parent_zone_delta_loss_s`` va
   primero. Fuera de near-ties el orden es D2.1.

No se ajustan thresholds: las constantes son decisiones de producto.
"""

from __future__ import annotations

from typing import Any, Iterable


PRODUCT_PRIORITY_COVERAGE_TARGET = 0.55
PRODUCT_PRIORITY_CAP = 3
PRODUCT_WEAK_SHARE_MAX = 0.05
PRODUCT_NEAR_TIE_RELATIVE = 0.05


def _safe_nonnegative_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result != result or result in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, result)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _evidence_key(episode: dict[str, Any]) -> str:
    return str(episode.get("evidence_strength") or "").strip().lower()


def calibrated_priority_cut_rank(
    ordered_episode_ids: Iterable[int],
    losses_by_episode_id: dict[int, float],
    *,
    coverage_target: float = PRODUCT_PRIORITY_COVERAGE_TARGET,
) -> int:
    """D2.3 rule: menor prefix cuya pérdida acumulada alcanza el target."""
    ordered = tuple(int(value) for value in ordered_episode_ids)
    if not ordered:
        raise ValueError("Se requiere al menos un episodio.")
    if not 0.0 < coverage_target <= 1.0:
        raise ValueError("coverage_target debe estar en (0, 1].")

    losses = [
        _safe_nonnegative_float(losses_by_episode_id.get(episode_id))
        for episode_id in ordered
    ]
    total = sum(losses)

    if len(ordered) == 1:
        return 1
    if total <= 0.0:
        return 1

    cumulative = 0.0
    cut = 1
    for rank, loss in enumerate(losses, start=1):
        cumulative += loss
        cut = rank
        if cumulative / total >= coverage_target:
            break

    # Convención de seguridad existente: con más de un episodio, al menos uno
    # queda fuera de PRIORITARIO.
    return max(1, min(cut, len(ordered) - 1))


def derive_d21_order(
    episodes: Iterable[dict[str, Any]],
) -> tuple[int, ...]:
    """Order D2.1 desde ground truth (misma lógica que el shadow)."""
    episodes = [episode for episode in episodes if isinstance(episode, dict)]
    usable_global_rank = all(
        isinstance(episode.get("global_rank"), int)
        and episode.get("global_rank") >= 1
        for episode in episodes
    ) and len({episode.get("global_rank") for episode in episodes}) == len(
        episodes
    )
    if usable_global_rank:
        ordered = sorted(
            episodes,
            key=lambda episode: (
                episode.get("global_rank"),
                episode.get("episode_id"),
            ),
        )
    else:
        evidence_priority = {"strong": 2, "moderate": 1, "weak": 0}
        ordered = sorted(
            episodes,
            key=lambda episode: (
                -(_finite(episode.get("action_time_loss_s")) or 0.0),
                -evidence_priority.get(
                    _evidence_key(episode),
                    0,
                ),
                -(int(episode.get("action_channel_count") or 0)),
                -(_finite(episode.get("length_m")) or 0.0),
                episode.get("episode_id"),
            ),
        )
    return tuple(int(episode.get("episode_id")) for episode in ordered)


def has_direct_authorized_target(episode: dict[str, Any]) -> bool:
    """¿El episodio tiene un target directo de coaching autorizado?

    Replica la regla de accionabilidad de Python (misma que usa
    ``build_deterministic_grounded_episode_fallback``): sólo canales
    brake/throttle con eventos direccionales generan recomendación de
    coaching; steering solo es observacional.
    """
    evidence_by_channel = episode.get("action_evidence_by_channel") or {}
    action_channels = episode.get("action_channels", []) or []
    if not isinstance(evidence_by_channel, dict) or not isinstance(
        action_channels, (list, tuple, set)
    ):
        return False
    for channel in action_channels:
        if channel not in {"brake", "throttle"}:
            continue
        info = evidence_by_channel.get(channel) or {}
        if not isinstance(info, dict):
            continue
        events = info.get("events") or []
        if not isinstance(events, (list, tuple)):
            continue
        directions = {
            str(event.get("direction"))
            for event in events
            if isinstance(event, dict)
            and event.get("persistent", True)
            and event.get("direction")
        }
        if len(directions) == 1 and directions <= {
            "higher_in_comparison_lap",
            "lower_in_comparison_lap",
        }:
            return True
    return False


def product_priority_cut_rank(
    order: Iterable[int],
    episodes_by_id: dict[int, dict[str, Any]],
    *,
    coverage_target: float = PRODUCT_PRIORITY_COVERAGE_TARGET,
    cap: int = PRODUCT_PRIORITY_CAP,
) -> int:
    """Prefix 55% + extensión por strong + target directo, con tope de foco."""
    ordered = tuple(int(value) for value in order)
    if not ordered:
        raise ValueError("Se requiere al menos un episodio.")
    if len(ordered) == 1:
        return 1

    losses = {
        episode_id: _safe_nonnegative_float(
            episodes_by_id[episode_id].get("action_time_loss_s")
        )
        for episode_id in ordered
    }
    cut = calibrated_priority_cut_rank(
        ordered,
        losses,
        coverage_target=coverage_target,
    )
    if cut >= len(ordered) - 1:
        return cut

    while cut < len(ordered) - 1 and cut < cap:
        next_episode = episodes_by_id.get(ordered[cut]) or {}
        if (
            _evidence_key(next_episode) == "strong"
            and has_direct_authorized_target(next_episode)
        ):
            cut += 1
        else:
            break
    # El tope de foco aplica al PRIORITARIO FINAL (base 55% + extensión).
    return max(1, min(cut, cap, len(ordered) - 1))


def product_no_actionable_start_rank(
    order: Iterable[int],
    episodes_by_id: dict[int, dict[str, Any]],
    *,
    priority_cut_rank: int,
    weak_share_max: float = PRODUCT_WEAK_SHARE_MAX,
) -> int:
    """Cola NO_ACCIONABLE: sólo observacional o weak con share negligible."""
    ordered = tuple(int(value) for value in order)
    if not ordered:
        raise ValueError("Se requiere al menos un episodio.")
    if not 1 <= priority_cut_rank <= len(ordered):
        raise ValueError("priority_cut_rank fuera de rango.")
    if not 0.0 <= weak_share_max <= 1.0:
        raise ValueError("weak_share_max debe estar en [0, 1].")

    losses = {
        episode_id: _safe_nonnegative_float(
            episodes_by_id[episode_id].get("action_time_loss_s")
        )
        for episode_id in ordered
    }
    total = sum(losses.values())
    start = len(ordered) + 1
    for rank in range(len(ordered), priority_cut_rank, -1):
        episode_id = ordered[rank - 1]
        episode = episodes_by_id.get(episode_id) or {}
        share = losses[episode_id] / total if total > 0.0 else 0.0
        is_observational = not has_direct_authorized_target(episode)
        if is_observational:
            start = rank
            continue
        if _evidence_key(episode) == "weak" and share <= weak_share_max:
            start = rank
            continue
        # moderate/strong con target directo: nunca NO_ACCIONABLE por share.
        break
    return start


def apply_tie_break(
    order: Iterable[int],
    episodes_by_id: dict[int, dict[str, Any]],
    *,
    near_tie_relative: float = PRODUCT_NEAR_TIE_RELATIVE,
) -> tuple[int, ...]:
    """Sólo en near-ties adyacentes: mayor parent_zone_delta_loss_s primero."""
    ordered = list(int(value) for value in order)
    if len(ordered) < 2:
        return tuple(ordered)

    losses = [
        _safe_nonnegative_float(
            episodes_by_id[episode_id].get("action_time_loss_s")
        )
        for episode_id in ordered
    ]

    def zone_delta(index: int) -> float:
        return _finite(
            (episodes_by_id.get(ordered[index]) or {}).get(
                "parent_zone_delta_loss_s"
            )
        ) or 0.0

    # Grupos de pares adyacentes near-tie.
    groups: list[list[int]] = []
    current: list[int] = []
    for index in range(len(ordered)):
        if not current:
            current = [index]
            continue
        previous = index - 1
        larger = max(losses[previous], losses[index])
        is_near_tie = (
            larger > 0.0
            and abs(losses[previous] - losses[index]) / larger
            <= near_tie_relative
        )
        if is_near_tie:
            current.append(index)
        else:
            groups.append(current)
            current = [index]
    if current:
        groups.append(current)

    result: list[int] = []
    for group in groups:
        if len(group) == 1:
            result.append(ordered[group[0]])
            continue
        members = sorted(
            group,
            key=lambda index: (-zone_delta(index), index),
        )
        result.extend(ordered[index] for index in members)
    return tuple(result)


def build_product_priority_ranker_response(
    episode_catalog: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """D2.9 candidate de producción: order + priority_cut + no_actionable."""
    episodes = [
        episode
        for episode in episode_catalog
        if isinstance(episode, dict)
    ]
    if not episodes:
        raise ValueError("El ranker determinista requiere al menos un episodio.")

    episodes_by_id: dict[int, dict[str, Any]] = {}
    for episode in episodes:
        episode_id = episode.get("episode_id")
        if not isinstance(episode_id, int):
            raise ValueError(
                "Cada episodio del ranker determinista requiere episode_id."
            )
        episodes_by_id[episode_id] = episode

    baseline_order = derive_d21_order(episodes)
    if set(baseline_order) != set(episodes_by_id):
        raise ValueError("No se pudo derivar un orden D2.1 completo.")

    order = apply_tie_break(baseline_order, episodes_by_id)
    priority_cut = product_priority_cut_rank(order, episodes_by_id)
    no_actionable_start = product_no_actionable_start_rank(
        order,
        episodes_by_id,
        priority_cut_rank=priority_cut,
    )
    return {
        "ordered_episode_ids": list(order),
        "priority_cut_rank": priority_cut,
        "no_actionable_start_rank": no_actionable_start,
    }
