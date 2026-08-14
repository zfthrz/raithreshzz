#!/usr/bin/env python3
"""
track_location.py

Resuelve un intervalo LMU Lap Dist contra un perfil de circuito calibrado.

Uso:
    python track_location.py spa_francorchamps_profile_v0_1.json 2853 2951

Salida:
    JSON determinista con:
      - label
      - overlaps
      - fase geométrica aproximada
      - transición si el episodio cae mayormente entre curvas

No usa LLM y no inventa nombres.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def overlap_m(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def turn_label(turn: dict[str, Any]) -> str:
    return f"T{turn['turn']} — {turn['name']}"


def geometric_phase(turn: dict[str, Any], start_m: float, end_m: float) -> str:
    """
    Fase derivada sólo de geometría:
    - entry: el solapamiento queda antes del ápice geométrico
    - apex: cruza/rodea el ápice
    - exit: queda después del ápice
    """
    s = max(start_m, float(turn["start_m"]))
    e = min(end_m, float(turn["end_m"]))
    apex = float(turn["apex_m"])

    if e <= apex:
        return "entry"
    if s >= apex:
        return "exit"
    return "apex"


def load_profile(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if "turns" not in data or not isinstance(data["turns"], list):
        raise ValueError("Perfil inválido: falta turns[]")
    return data


def nearest_before_after(turns: list[dict[str, Any]], start_m: float, end_m: float):
    before = None
    after = None

    for t in turns:
        if float(t["end_m"]) <= start_m:
            if before is None or float(t["end_m"]) > float(before["end_m"]):
                before = t
        if float(t["start_m"]) >= end_m:
            if after is None or float(t["start_m"]) < float(after["start_m"]):
                after = t

    return before, after


def resolve_interval(profile: dict[str, Any], start_m: float, end_m: float) -> dict[str, Any]:
    if end_m < start_m:
        start_m, end_m = end_m, start_m

    span = max(end_m - start_m, 1e-9)
    turns = sorted(profile["turns"], key=lambda t: float(t["start_m"]))

    overlaps = []
    for t in turns:
        ov = overlap_m(start_m, end_m, float(t["start_m"]), float(t["end_m"]))
        if ov <= 0:
            continue
        overlaps.append({
            "turn": int(t["turn"]),
            "name": t["name"],
            "group": t.get("group", t["name"]),
            "direction": t.get("direction"),
            "overlap_m": round(ov, 3),
            "overlap_share": round(ov / span, 4),
            "phase": geometric_phase(t, start_m, end_m),
            "turn_start_m": t["start_m"],
            "apex_m": t["apex_m"],
            "turn_end_m": t["end_m"],
        })

    significant = [x for x in overlaps if x["overlap_m"] >= 8.0]
    total_overlap = sum(x["overlap_m"] for x in overlaps)
    coverage = total_overlap / span

    label = None
    location_type = None

    if significant:
        dominant = max(significant, key=lambda x: x["overlap_m"])

        # Un complejo de varias curvas puede dominar el intervalo aunque
        # ninguna curva individual supere 50% del span. Agrupar primero por
        # `group` evita etiquetar como transición un intervalo que pertenece
        # materialmente al mismo complejo (p. ej. Villeneuve T5–T6).
        group_rows = {}
        for row in significant:
            if row["overlap_share"] < 0.10:
                continue
            group_rows.setdefault(row["group"], []).append(row)

        if group_rows:
            dominant_group, dominant_group_rows = max(
                group_rows.items(),
                key=lambda item: sum(row["overlap_m"] for row in item[1]),
            )
            dominant_group_overlap = sum(
                row["overlap_m"] for row in dominant_group_rows
            )
            dominant_group_share = dominant_group_overlap / span
        else:
            dominant_group = None
            dominant_group_rows = []
            dominant_group_share = 0.0

        if len(dominant_group_rows) > 1 and dominant_group_share >= 0.50:
            nums = sorted(row["turn"] for row in dominant_group_rows)
            label = f"T{nums[0]}–T{nums[-1]} — {dominant_group}"
            location_type = "corner_complex"

        # Un episodio claramente contenido en una curva.
        elif dominant["overlap_share"] >= 0.50:
            same_group = [
                x for x in significant
                if x["group"] == dominant["group"] and x["overlap_share"] >= 0.10
            ]
            if len(same_group) > 1:
                nums = sorted(x["turn"] for x in same_group)
                label = f"T{nums[0]}–T{nums[-1]} — {dominant['group']}"
                location_type = "corner_complex"
            else:
                label = f"T{dominant['turn']} — {dominant['name']}"
                location_type = "corner"
        else:
            # Hay contacto con una curva, pero la mayor parte del intervalo
            # está entre curvas. Si el episodio toca la parte final de la
            # curva dominante, esa curva es el origen de la transición.
            dominant_turn = next(
                t for t in turns if int(t["turn"]) == int(dominant["turn"])
            )
            dominant_end = float(dominant_turn["end_m"])
            dominant_start = float(dominant_turn["start_m"])

            if end_m > dominant_end and start_m < dominant_end:
                after_candidates = [
                    t for t in turns
                    if int(t["turn"]) > int(dominant_turn["turn"])
                    and float(t["start_m"]) >= dominant_end
                ]
                after = after_candidates[0] if after_candidates else None
                if after:
                    label = (
                        f"salida de {turn_label(dominant_turn)} "
                        f"→ {turn_label(after)}"
                    )
                    location_type = "transition"
                else:
                    label = f"salida de {turn_label(dominant_turn)}"
                    location_type = "corner_exit"
            elif start_m < dominant_start and end_m > dominant_start:
                before_candidates = [
                    t for t in turns
                    if int(t["turn"]) < int(dominant_turn["turn"])
                    and float(t["end_m"]) <= dominant_start
                ]
                before = before_candidates[-1] if before_candidates else None
                if before:
                    label = (
                        f"{turn_label(before)} "
                        f"→ entrada de {turn_label(dominant_turn)}"
                    )
                    location_type = "transition"
                else:
                    label = f"entrada de {turn_label(dominant_turn)}"
                    location_type = "corner_entry"
            else:
                label = f"T{dominant['turn']} — {dominant['name']}"
                location_type = "corner_edge"

    else:
        before, after = nearest_before_after(turns, start_m, end_m)
        if before and after:
            label = f"{turn_label(before)} → {turn_label(after)}"
            location_type = "between_corners"
        elif before:
            label = f"después de {turn_label(before)}"
            location_type = "after_corner"
        elif after:
            label = f"antes de {turn_label(after)}"
            location_type = "before_corner"
        else:
            label = f"{start_m:.0f}–{end_m:.0f} m"
            location_type = "distance_only"

    return {
        "track": profile.get("track"),
        "profile_id": profile.get("profile_id"),
        "profile_status": profile.get("status"),
        "numbering_scheme": profile.get("calibration", {}).get("numbering_scheme"),
        "start_m": round(start_m, 3),
        "end_m": round(end_m, 3),
        "span_m": round(span, 3),
        "label": label,
        "location_type": location_type,
        "turn_coverage_share": round(coverage, 4),
        "overlaps": overlaps,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("start_m", type=float)
    ap.add_argument("end_m", type=float)
    args = ap.parse_args()

    profile = load_profile(args.profile)
    result = resolve_interval(profile, args.start_m, args.end_m)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
