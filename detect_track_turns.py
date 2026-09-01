#!/usr/bin/env python3
"""
detect_track_turns.py

Detecta candidatos de curva a partir del CSV producido por extract_lmu_track_gps.py.

Entrada esperada:
    lap_distance_m, x_east_m, y_north_m, ...

Método:
1) ordena y limpia por distancia de vuelta
2) remuestrea la trayectoria a paso fijo
3) calcula heading local usando una ventana espacial
4) calcula curvatura firmada (rad/m)
5) suaviza |curvatura|
6) encuentra máximos locales con separación mínima
7) selecciona N candidatos si --turn-count está definido
8) estima start/end de cada región alrededor del pico

No asigna nombres. Esa capa debe validarse posteriormente con una referencia oficial.

Uso Spa WEC:
    python detect_track_turns.py session_track_gps.csv --turn-count 20

Uso genérico:
    python detect_track_turns.py session_track_gps.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any


def finite(v):
    try:
        return math.isfinite(float(v))
    except Exception:
        return False


def load_points(path: Path):
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        needed = {"lap_distance_m", "x_east_m", "y_north_m"}
        missing = needed - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Faltan columnas: {sorted(missing)}")
        for r in reader:
            if not (
                finite(r.get("lap_distance_m"))
                and finite(r.get("x_east_m"))
                and finite(r.get("y_north_m"))
            ):
                continue
            rows.append(
                (
                    float(r["lap_distance_m"]),
                    float(r["x_east_m"]),
                    float(r["y_north_m"]),
                )
            )

    rows.sort(key=lambda p: p[0])

    # Deduplicar distancia conservando el último punto.
    dedup = []
    for p in rows:
        if dedup and abs(p[0] - dedup[-1][0]) < 1e-9:
            dedup[-1] = p
        elif not dedup or p[0] > dedup[-1][0]:
            dedup.append(p)

    return dedup


def interp(points, d):
    """
    Interpolación lineal en distancia.
    """
    if d <= points[0][0]:
        return points[0][1], points[0][2]
    if d >= points[-1][0]:
        return points[-1][1], points[-1][2]

    lo = 0
    hi = len(points) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if points[mid][0] <= d:
            lo = mid
        else:
            hi = mid

    d0, x0, y0 = points[lo]
    d1, x1, y1 = points[hi]
    if d1 <= d0:
        return x0, y0
    a = (d - d0) / (d1 - d0)
    return x0 + a * (x1 - x0), y0 + a * (y1 - y0)


def resample(points, step_m):
    start = points[0][0]
    end = points[-1][0]
    n = int(math.floor((end - start) / step_m)) + 1
    out = []
    for i in range(n):
        d = start + i * step_m
        x, y = interp(points, d)
        out.append({"d": d, "x": x, "y": y})
    if out[-1]["d"] < end:
        x, y = interp(points, end)
        out.append({"d": end, "x": x, "y": y})
    return out


def wrap_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def heading_at(samples, i, half_window_pts):
    a = max(0, i - half_window_pts)
    b = min(len(samples) - 1, i + half_window_pts)
    if b <= a:
        return 0.0
    dx = samples[b]["x"] - samples[a]["x"]
    dy = samples[b]["y"] - samples[a]["y"]
    return math.atan2(dy, dx)


def moving_average(values, radius):
    if radius <= 0:
        return list(values)
    prefix = [0.0]
    for v in values:
        prefix.append(prefix[-1] + v)
    out = []
    n = len(values)
    for i in range(n):
        a = max(0, i - radius)
        b = min(n, i + radius + 1)
        out.append((prefix[b] - prefix[a]) / (b - a))
    return out


def compute_curvature(samples, step_m, heading_window_m, smooth_window_m):
    hw = max(1, int(round((heading_window_m / step_m) / 2.0)))
    headings = [heading_at(samples, i, hw) for i in range(len(samples))]

    curv = [0.0] * len(samples)
    for i in range(1, len(samples) - 1):
        dh = wrap_angle(headings[i + 1] - headings[i - 1])
        dd = samples[i + 1]["d"] - samples[i - 1]["d"]
        curv[i] = dh / dd if dd > 0 else 0.0

    abs_curv = [abs(v) for v in curv]
    radius = max(0, int(round((smooth_window_m / step_m) / 2.0)))
    smooth_abs = moving_average(abs_curv, radius)

    return headings, curv, smooth_abs


def percentile(values, pct):
    vals = sorted(values)
    if not vals:
        return 0.0
    if len(vals) == 1:
        return vals[0]
    x = (len(vals) - 1) * pct
    lo = int(math.floor(x))
    hi = int(math.ceil(x))
    if lo == hi:
        return vals[lo]
    a = x - lo
    return vals[lo] * (1 - a) + vals[hi] * a


def local_peak_indices(signal):
    peaks = []
    for i in range(1, len(signal) - 1):
        if signal[i] >= signal[i - 1] and signal[i] > signal[i + 1]:
            peaks.append(i)
    return peaks


def select_peaks(
    samples,
    signal,
    min_separation_m,
    turn_count=None,
    min_strength=None,
):
    peaks = local_peak_indices(signal)

    if min_strength is not None:
        peaks = [i for i in peaks if signal[i] >= min_strength]

    # Selección por fuerza con non-max suppression espacial.
    ranked = sorted(peaks, key=lambda i: signal[i], reverse=True)
    selected = []

    for i in ranked:
        d = samples[i]["d"]
        if any(abs(d - samples[j]["d"]) < min_separation_m for j in selected):
            continue
        selected.append(i)
        if turn_count and len(selected) >= turn_count:
            break

    selected.sort(key=lambda i: samples[i]["d"])
    return selected


def estimate_region(samples, signal, peak_i, global_threshold, fraction_of_peak=0.30):
    peak = signal[peak_i]
    threshold = max(global_threshold * 0.65, peak * fraction_of_peak)

    a = peak_i
    while a > 0 and signal[a - 1] >= threshold:
        a -= 1

    b = peak_i
    while b + 1 < len(signal) and signal[b + 1] >= threshold:
        b += 1

    return a, b, threshold


def signed_turn_direction(curvature, a, b):
    signed = sum(curvature[a:b + 1])
    if signed > 0:
        return "left"
    if signed < 0:
        return "right"
    return "unknown"


def write_candidates_csv(path, candidates):
    fields = [
        "candidate_number",
        "start_distance_m",
        "center_distance_m",
        "end_distance_m",
        "direction",
        "peak_abs_curvature_rad_per_m",
        "mean_abs_curvature_rad_per_m",
        "estimated_heading_change_deg",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(candidates)


def main():
    parser = argparse.ArgumentParser(
        description="Detecta candidatos de curva desde una trayectoria GPS LMU."
    )
    parser.add_argument("track_csv")
    parser.add_argument(
        "--turn-count",
        type=int,
        default=None,
        help="Cantidad objetivo de candidatos. Para Spa FIA WEC: 20.",
    )
    parser.add_argument("--step-m", type=float, default=2.0)
    parser.add_argument("--heading-window-m", type=float, default=20.0)
    parser.add_argument("--smooth-window-m", type=float, default=14.0)
    parser.add_argument("--min-separation-m", type=float, default=45.0)
    parser.add_argument(
        "--threshold-percentile",
        type=float,
        default=0.70,
        help="Percentil de |curvatura| suavizada usado como piso (0-1).",
    )
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    path = Path(args.track_csv).expanduser().resolve()
    if not path.exists():
        print(f"ERROR: no existe {path}")
        return 2

    if args.turn_count is not None and args.turn_count <= 0:
        print("ERROR: --turn-count debe ser > 0")
        return 2

    points = load_points(path)
    if len(points) < 30:
        print("ERROR: muy pocos puntos válidos.")
        return 3

    samples = resample(points, args.step_m)
    headings, curvature, smooth_abs = compute_curvature(
        samples,
        args.step_m,
        args.heading_window_m,
        args.smooth_window_m,
    )

    pct = min(0.99, max(0.01, args.threshold_percentile))
    global_threshold = percentile(smooth_abs, pct)

    # Si se exige turn_count, no filtramos tan agresivamente por threshold:
    # el NMS espacial + ranking de fuerza se encarga.
    min_strength = None if args.turn_count else global_threshold

    selected = select_peaks(
        samples,
        smooth_abs,
        args.min_separation_m,
        turn_count=args.turn_count,
        min_strength=min_strength,
    )

    candidates = []
    for n, i in enumerate(selected, 1):
        a, b, threshold = estimate_region(
            samples,
            smooth_abs,
            i,
            global_threshold,
        )

        d0 = samples[a]["d"]
        dc = samples[i]["d"]
        d1 = samples[b]["d"]

        peak = max(smooth_abs[a:b + 1])
        mean_abs = statistics.mean(smooth_abs[a:b + 1])

        heading_change = 0.0
        for j in range(a + 1, b + 1):
            heading_change += wrap_angle(headings[j] - headings[j - 1])

        candidates.append({
            "candidate_number": n,
            "start_distance_m": round(d0, 3),
            "center_distance_m": round(dc, 3),
            "end_distance_m": round(d1, 3),
            "direction": signed_turn_direction(curvature, a, b),
            "peak_abs_curvature_rad_per_m": peak,
            "mean_abs_curvature_rad_per_m": mean_abs,
            "estimated_heading_change_deg": math.degrees(heading_change),
        })

    out_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else path.parent
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = path.stem.replace("_track_gps", "")
    csv_out = out_dir / f"{stem}_turn_candidates.csv"
    json_out = out_dir / f"{stem}_turn_candidates.json"

    write_candidates_csv(csv_out, candidates)

    payload = {
        "source_csv": str(path),
        "algorithm": {
            "step_m": args.step_m,
            "heading_window_m": args.heading_window_m,
            "smooth_window_m": args.smooth_window_m,
            "min_separation_m": args.min_separation_m,
            "threshold_percentile": pct,
            "global_abs_curvature_threshold_rad_per_m": global_threshold,
            "requested_turn_count": args.turn_count,
        },
        "track_distance_range_m": [points[0][0], points[-1][0]],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "warning": (
            "Estos son candidatos geométricos. No son nombres/números oficiales "
            "hasta completar la calibración contra una referencia verificada."
        ),
    }
    json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 76)
    print("TRACK TURN CANDIDATE DETECTOR")
    print("=" * 76)
    print(f"Fuente: {path}")
    print(f"Distancia: {points[0][0]:.1f} -> {points[-1][0]:.1f} m")
    print(f"Samples remuestreados: {len(samples)}")
    print(f"Candidatos: {len(candidates)}")
    print()

    print(
        f"{'#':>3} {'start':>9} {'center':>9} {'end':>9} "
        f"{'dir':>7} {'heading_d':>10} {'peak_kappa':>11}"
    )
    for c in candidates:
        print(
            f"{c['candidate_number']:>3d} "
            f"{c['start_distance_m']:>9.1f} "
            f"{c['center_distance_m']:>9.1f} "
            f"{c['end_distance_m']:>9.1f} "
            f"{c['direction']:>7} "
            f"{c['estimated_heading_change_deg']:>9.1f}deg "
            f"{c['peak_abs_curvature_rad_per_m']:>11.6f}"
        )

    print("\nSalidas:")
    print(f"  CSV:  {csv_out}")
    print(f"  JSON: {json_out}")
    print()
    print(
        "IMPORTANTE: todavía no asignar nombres automáticamente. "
        "Primero hay que validar la secuencia contra el mapa oficial del layout."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
