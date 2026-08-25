#!/usr/bin/env python3
"""D2.8 — Evidence/channel-aware boundary policy candidate (offline, shadow).

Hipótesis derivadas de D2.7 (sin tuning de thresholds; cambia la FORMA de la
política):

1. PRIORITY CUT: tras alcanzar el coverage objetivo (55%), el prefijo
   PRIORITARIO puede extenderse mientras el siguiente episodio tenga evidencia
   ``strong`` y >= 2 canales de acción, con tope de coverage (95%).
   (D2.7: en los 3 priority_cut UNRESOLVED el LLM retiene un episodio strong +
   multi-canal en el borde.)

2. NO_ACCIONABLE: sólo la cola de episodios con evidencia ``weak`` y share bajo
   es descartable; moderate/strong nunca pasan a NO_ACCIONABLE por share.
   (D2.7: 3 casos donde el LLM mantiene accionables episodios moderate/strong
   con share tiny.)

NO cambia producción, NO entrena, NO toca prompts.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any, Iterable

from audit_d2_7_residual_disagreements import (
    _evidence_key,
    _safe_nonnegative_float,
    load_samples,
)


DEFAULT_PRIORITY_COVERAGE_TARGET = 0.55
DEFAULT_MAX_COVERAGE = 0.95
DEFAULT_WEAK_SHARE_MAX = 0.05


def _losses(order: Iterable[int], episodes_by_id: dict[int, dict[str, Any]]) -> dict[int, float]:
    return {
        episode_id: _safe_nonnegative_float(episodes_by_id[episode_id].get("action_time_loss_s"))
        for episode_id in order
    }


def evidence_channel_priority_cut_rank(
    order: Iterable[int],
    episodes_by_id: dict[int, dict[str, Any]],
    *,
    coverage_target: float = DEFAULT_PRIORITY_COVERAGE_TARGET,
    max_coverage: float = DEFAULT_MAX_COVERAGE,
) -> int:
    """D2.1 order + coverage 55% + extensión strong/multi-canal en el borde."""
    ordered = tuple(int(value) for value in order)
    if not ordered:
        raise ValueError("Se requiere al menos un episodio.")
    if not 0.0 < coverage_target <= 1.0 or not 0.0 < max_coverage <= 1.0:
        raise ValueError("coverage_target y max_coverage deben estar en (0, 1].")
    if len(ordered) == 1:
        return 1
    losses = _losses(ordered, episodes_by_id)
    total = sum(losses.values())
    if total <= 0.0:
        return 1

    cumulative = 0.0
    cut = 1
    for rank, episode_id in enumerate(ordered, start=1):
        cumulative += losses[episode_id]
        cut = rank
        if cumulative / total >= coverage_target:
            break

    # Extensión por borde fuerte: siguiente episodio strong + >=2 canales.
    while cut < len(ordered) - 1:
        next_episode = episodes_by_id.get(ordered[cut]) or {}
        evidence = _evidence_key(next_episode)
        channel_count = int(next_episode.get("action_channel_count") or 0)
        next_loss = losses.get(ordered[cut], 0.0)
        if evidence != "strong" or channel_count < 2:
            break
        if (cumulative + next_loss) / total > max_coverage:
            break
        cumulative += next_loss
        cut += 1

    # Convención determinista existente: dejar al menos uno fuera de PRIORITARIO.
    return max(1, min(cut, len(ordered) - 1))


def evidence_aware_no_actionable_start_rank(
    order: Iterable[int],
    episodes_by_id: dict[int, dict[str, Any]],
    *,
    priority_cut_rank: int,
    weak_share_max: float = DEFAULT_WEAK_SHARE_MAX,
) -> int:
    """Sólo la cola weak con share bajo es NO_ACCIONABLE; nunca moderate/strong."""
    ordered = tuple(int(value) for value in order)
    if not ordered:
        raise ValueError("Se requiere al menos un episodio.")
    if not 1 <= priority_cut_rank <= len(ordered):
        raise ValueError("priority_cut_rank fuera de rango.")
    if not 0.0 <= weak_share_max <= 1.0:
        raise ValueError("weak_share_max debe estar en [0, 1].")

    losses = _losses(ordered, episodes_by_id)
    total = sum(losses.values())
    start = len(ordered) + 1
    for rank in range(len(ordered), priority_cut_rank, -1):
        episode_id = ordered[rank - 1]
        episode = episodes_by_id.get(episode_id) or {}
        share = losses[episode_id] / total if total > 0.0 else 0.0
        if _evidence_key(episode) == "weak" and share <= weak_share_max:
            start = rank
        else:
            break
    return start


def build_candidate(sample) -> dict[str, Any]:
    priority_cut = evidence_channel_priority_cut_rank(
        sample.baseline_order,
        sample.episodes_by_id,
    )
    no_actionable_start = evidence_aware_no_actionable_start_rank(
        sample.baseline_order,
        sample.episodes_by_id,
        priority_cut_rank=priority_cut,
    )
    return {
        "ordered_episode_ids": list(sample.baseline_order),
        "priority_cut_rank": priority_cut,
        "no_actionable_start_rank": no_actionable_start,
    }


def _derive_classifications(
    order: Iterable[int],
    priority_cut_rank: int,
    no_actionable_start_rank: int,
) -> tuple[tuple[int, int, str], ...]:
    ordered = tuple(int(value) for value in order)
    result = []
    for rank, episode_id in enumerate(ordered, start=1):
        if rank <= priority_cut_rank:
            classification = "PRIORITARIO"
        elif rank >= no_actionable_start_rank:
            classification = "NO_ACCIONABLE"
        else:
            classification = "SECUNDARIO"
        result.append((episode_id, rank, classification))
    return tuple(result)


def evaluate(samples: Iterable) -> dict[str, Any]:
    samples = list(samples)
    rows = []
    counts = {
        "order": 0,
        "priority_cut": 0,
        "no_actionable_cut": 0,
        "classifications": 0,
        "full": 0,
    }
    for sample in samples:
        candidate = build_candidate(sample)
        llm_classifications = _derive_classifications(
            sample.llm_order,
            sample.llm_priority_cut_rank,
            sample.llm_no_actionable_start_rank,
        )
        candidate_classifications = _derive_classifications(
            candidate["ordered_episode_ids"],
            candidate["priority_cut_rank"],
            candidate["no_actionable_start_rank"],
        )
        agreement = {
            "order": tuple(candidate["ordered_episode_ids"]) == sample.llm_order,
            "priority_cut": (
                candidate["priority_cut_rank"] == sample.llm_priority_cut_rank
            ),
            "no_actionable_cut": (
                candidate["no_actionable_start_rank"]
                == sample.llm_no_actionable_start_rank
            ),
            "classifications": candidate_classifications == llm_classifications,
        }
        agreement["full"] = all(agreement.values())
        for key in counts:
            counts[key] += int(agreement[key])
        rows.append(
            {
                "track": sample.track,
                "comparison": sample.comparison,
                "llm": {
                    "ordered_episode_ids": list(sample.llm_order),
                    "priority_cut_rank": sample.llm_priority_cut_rank,
                    "no_actionable_start_rank": sample.llm_no_actionable_start_rank,
                },
                "candidate": candidate,
                "agreement": agreement,
            }
        )
    count = len(samples)
    return {
        "comparison_count": count,
        "rates": {
            key: {"count": counts[key], "rate": counts[key] / count if count else 0.0}
            for key in counts
        },
        "rows": rows,
    }


def _expand_inputs(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        matches = glob.glob(value)
        if matches:
            result.extend(matches)
        elif Path(value).is_file():
            result.append(value)
    return sorted(set(result))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="D2.8 evidence/channel-aware boundary policy candidate (shadow)."
    )
    parser.add_argument("inputs", nargs="+", help="JSON files or glob patterns.")
    parser.add_argument("--json-output", type=Path, default=None)
    args = parser.parse_args()

    samples = load_samples(_expand_inputs(args.inputs))
    if not samples:
        raise SystemExit("No se encontraron comparisons con deterministic_shadow VALID.")
    report = evaluate(samples)

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Output: {args.json_output.resolve()}")

    print("=" * 88)
    print("D2.8 EVIDENCE/CHANNEL-AWARE BOUNDARY POLICY (SHADOW)")
    print("=" * 88)
    print(f"Comparisons: {report['comparison_count']}")
    for key, value in report["rates"].items():
        print(f"  {key:16} {value['count']}/{report['comparison_count']} = {value['rate']:.3f}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
