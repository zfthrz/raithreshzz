"""Deterministic repeated physical coaching pattern detection."""

import statistics

from deterministic_coaching import (
    BRAKE_RELEASE_SESSION_MIN_DELTA_M,
    BRAKING_POINT_SESSION_MIN_DELTA_M,
    safe_float,
    safe_int,
)

BRAKING_POINT_PATTERN_ONSET_TOLERANCE_M = 8.0
BRAKE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M = 8.0


def _build_repeated_braking_point_patterns(
    braking_point_findings,
    priority_regions,
):
    """
    Agrupa el mismo evento físico entre comparaciones usando el onset de la
    vuelta de referencia. La agregación es independiente del episodio que
    terminó siendo dueño del coaching numérico en cada comparación.

    Un patrón sólo existe con >=2 comparaciones distintas, misma dirección de
    coaching y delta >= zona muerta. La magnitud de coaching es la MEDIANA de
    los deltas firmados para resistir outliers.
    """
    rows = []

    for finding in braking_point_findings or []:
        if not isinstance(finding, dict):
            continue
        bp = finding.get("braking_point")
        if not isinstance(bp, dict):
            continue
        onset = safe_float(bp.get("reference_onset_m"))
        delta = safe_float(bp.get("comparison_minus_reference_m"))
        direction = bp.get("coaching_direction")
        comparison = finding.get("comparison")
        if (
            onset is None
            or delta is None
            or not comparison
            or direction not in {"later", "earlier"}
            or abs(delta) < BRAKING_POINT_SESSION_MIN_DELTA_M
        ):
            continue
        rows.append(finding)

    rows.sort(
        key=lambda item: safe_float(
            (item.get("braking_point") or {}).get("reference_onset_m")
        ) or 0.0
    )

    clusters = []
    for row in rows:
        onset = safe_float(
            (row.get("braking_point") or {}).get("reference_onset_m")
        )
        placed = False
        for cluster in clusters:
            anchor_onset = cluster["anchor_onset_m"]
            if abs(onset - anchor_onset) <= BRAKING_POINT_PATTERN_ONSET_TOLERANCE_M:
                cluster["rows"].append(row)
                placed = True
                break
        if not placed:
            clusters.append({
                "anchor_onset_m": onset,
                "rows": [row],
            })

    region_members = []
    for region in priority_regions or []:
        if not isinstance(region, dict):
            continue
        keys = {
            (item.get("comparison"), safe_int(item.get("episode_id")))
            for item in (region.get("findings", []) or [])
            if isinstance(item, dict)
        }
        region.setdefault("braking_point_patterns", [])
        region_members.append((region, keys))

    patterns = []

    for cluster in clusters:
        by_direction = {}
        for row in cluster["rows"]:
            direction = (row.get("braking_point") or {}).get("coaching_direction")
            by_direction.setdefault(direction, []).append(row)

        for direction, direction_rows in by_direction.items():
            # Defensa adicional contra outputs v3.8.23 previos a la deduplicación:
            # una comparación sólo aporta una observación al mismo evento físico.
            best_by_comparison = {}
            for row in direction_rows:
                comparison = str(row.get("comparison"))
                action_loss = abs(
                    safe_float(row.get("action_time_loss_s")) or 0.0
                )
                episode_id = safe_int(row.get("episode_id"))
                score = (
                    action_loss,
                    -(episode_id if episode_id is not None else 999999),
                )
                previous = best_by_comparison.get(comparison)
                if previous is None or score > previous[0]:
                    best_by_comparison[comparison] = (score, row)

            selected = [item[1] for item in best_by_comparison.values()]
            if len(selected) < 2:
                continue

            signed_deltas = [
                safe_float((row.get("braking_point") or {}).get("comparison_minus_reference_m"))
                for row in selected
            ]
            signed_deltas = [value for value in signed_deltas if value is not None]
            if len(signed_deltas) < 2:
                continue

            median_delta = float(statistics.median(signed_deltas))
            magnitude = int(round(abs(median_delta)))
            if magnitude < BRAKING_POINT_SESSION_MIN_DELTA_M:
                continue

            comparisons = sorted(str(row.get("comparison")) for row in selected)
            reference_onsets = [
                safe_float((row.get("braking_point") or {}).get("reference_onset_m"))
                for row in selected
            ]
            reference_onsets = [value for value in reference_onsets if value is not None]

            pattern = {
                "status": "REPEATED",
                "comparison_count": len(comparisons),
                "comparisons": comparisons,
                "coaching_direction": direction,
                "coaching_magnitude_m": magnitude,
                "median_delta_m": median_delta,
                "deltas_m": sorted(signed_deltas),
                "reference_onset_m": (
                    float(statistics.median(reference_onsets))
                    if reference_onsets
                    else None
                ),
                "aggregation": "median_comparison_minus_reference_m",
                "source_findings": [
                    {
                        "comparison": row.get("comparison"),
                        "episode_id": safe_int(row.get("episode_id")),
                    }
                    for row in selected
                ],
            }

            # Asignar el evento físico a UNA sola región del plan. Gana la
            # región que contiene más de sus episodios fuente; luego la región
            # con mayor soporte comparativo y finalmente la de mayor pérdida.
            candidates = []
            selected_keys = {
                (row.get("comparison"), safe_int(row.get("episode_id")))
                for row in selected
            }
            for region, keys in region_members:
                votes = len(selected_keys & keys)
                if votes <= 0:
                    continue
                candidates.append((
                    votes,
                    safe_int(region.get("comparison_count")) or 0,
                    abs(safe_float(region.get("max_action_time_loss_s")) or 0.0),
                    region,
                ))

            if candidates:
                candidates.sort(key=lambda item: item[:3], reverse=True)
                chosen_region = candidates[0][3]
                pattern["region_label"] = chosen_region.get("region_label")
                pattern["start_distance_m"] = chosen_region.get("start_distance_m")
                pattern["end_distance_m"] = chosen_region.get("end_distance_m")
                pattern["track_location"] = chosen_region.get("track_location")
                chosen_region.setdefault("braking_point_patterns", []).append(pattern)
            else:
                pattern["region_label"] = None

            patterns.append(pattern)

    patterns.sort(
        key=lambda item: (
            -safe_int(item.get("comparison_count")) if safe_int(item.get("comparison_count")) is not None else 0,
            -abs(safe_float(item.get("median_delta_m")) or 0.0),
            safe_float(item.get("reference_onset_m")) or 999999.0,
        )
    )

    for region in priority_regions or []:
        values = region.get("braking_point_patterns", []) or []
        values.sort(
            key=lambda item: (
                -safe_int(item.get("comparison_count")) if safe_int(item.get("comparison_count")) is not None else 0,
                -abs(safe_float(item.get("median_delta_m")) or 0.0),
            )
        )

    return patterns

def _build_repeated_brake_release_patterns(
    brake_release_findings,
    priority_regions,
):
    """
    Agrupa liberaciones del mismo evento físico usando la distancia de release
    de la vuelta de referencia. Requiere >=2 comparaciones distintas, misma
    dirección, magnitud >= zona muerta y AUSENCIA de una diferencia accionable
    en dirección opuesta. La magnitud es la mediana firmada.

    DUPLICATE puede aportar evidencia física a la agregación, pero cada
    comparación aporta como máximo una muestra por evento.
    """
    rows = []

    for finding in brake_release_findings or []:
        if not isinstance(finding, dict):
            continue
        release = finding.get("brake_release")
        if not isinstance(release, dict):
            continue
        reference_release = safe_float(
            release.get("reference_release_m")
        )
        delta = safe_float(
            release.get("comparison_minus_reference_m")
        )
        direction = release.get("coaching_direction")
        comparison = finding.get("comparison")
        if (
            reference_release is None
            or delta is None
            or not comparison
            or direction not in {"later", "earlier"}
            or abs(delta) < BRAKE_RELEASE_SESSION_MIN_DELTA_M
        ):
            continue
        rows.append(finding)

    rows.sort(
        key=lambda item: safe_float(
            (item.get("brake_release") or {}).get("reference_release_m")
        ) or 0.0
    )

    clusters = []
    for row in rows:
        reference_release = safe_float(
            (row.get("brake_release") or {}).get("reference_release_m")
        )
        placed = False
        for cluster in clusters:
            anchor_release = cluster["anchor_release_m"]
            if (
                abs(reference_release - anchor_release)
                <= BRAKE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M
            ):
                cluster["rows"].append(row)
                placed = True
                break
        if not placed:
            clusters.append({
                "anchor_release_m": reference_release,
                "rows": [row],
            })

    region_members = []
    for region in priority_regions or []:
        if not isinstance(region, dict):
            continue
        keys = {
            (item.get("comparison"), safe_int(item.get("episode_id")))
            for item in (region.get("findings", []) or [])
            if isinstance(item, dict)
        }
        region.setdefault("brake_release_patterns", [])
        region_members.append((region, keys))

    patterns = []

    for cluster in clusters:
        by_direction = {}
        for row in cluster["rows"]:
            direction = (
                (row.get("brake_release") or {}).get("coaching_direction")
            )
            by_direction.setdefault(direction, []).append(row)

        # Release es más sensible que onset. Si el mismo evento físico tiene
        # diferencias accionables en sentidos opuestos entre comparaciones,
        # no se promueve ningún coaching regional de release.
        actionable_directions = {
            direction
            for direction, rows_for_direction in by_direction.items()
            if (
                direction in {"later", "earlier"}
                and rows_for_direction
            )
        }
        if len(actionable_directions) > 1:
            continue

        for direction, direction_rows in by_direction.items():
            best_by_comparison = {}
            for row in direction_rows:
                comparison = str(row.get("comparison"))
                action_loss = abs(
                    safe_float(row.get("action_time_loss_s")) or 0.0
                )
                episode_id = safe_int(row.get("episode_id"))
                score = (
                    action_loss,
                    -(episode_id if episode_id is not None else 999999),
                )
                previous = best_by_comparison.get(comparison)
                if previous is None or score > previous[0]:
                    best_by_comparison[comparison] = (score, row)

            selected = [item[1] for item in best_by_comparison.values()]
            if len(selected) < 2:
                continue

            signed_deltas = [
                safe_float(
                    (row.get("brake_release") or {}).get(
                        "comparison_minus_reference_m"
                    )
                )
                for row in selected
            ]
            signed_deltas = [
                value for value in signed_deltas
                if value is not None
            ]
            if len(signed_deltas) < 2:
                continue

            median_delta = float(statistics.median(signed_deltas))
            magnitude = int(round(abs(median_delta)))
            if magnitude < BRAKE_RELEASE_SESSION_MIN_DELTA_M:
                continue

            comparisons = sorted(
                str(row.get("comparison"))
                for row in selected
            )
            reference_releases = [
                safe_float(
                    (row.get("brake_release") or {}).get(
                        "reference_release_m"
                    )
                )
                for row in selected
            ]
            reference_releases = [
                value for value in reference_releases
                if value is not None
            ]

            pattern = {
                "status": "REPEATED",
                "comparison_count": len(comparisons),
                "comparisons": comparisons,
                "coaching_direction": direction,
                "coaching_magnitude_m": magnitude,
                "median_delta_m": median_delta,
                "deltas_m": sorted(signed_deltas),
                "reference_release_m": (
                    float(statistics.median(reference_releases))
                    if reference_releases
                    else None
                ),
                "aggregation": "median_comparison_minus_reference_m",
                "source_findings": [
                    {
                        "comparison": row.get("comparison"),
                        "episode_id": safe_int(row.get("episode_id")),
                    }
                    for row in selected
                ],
            }

            candidates = []
            selected_keys = {
                (row.get("comparison"), safe_int(row.get("episode_id")))
                for row in selected
            }
            for region, keys in region_members:
                votes = len(selected_keys & keys)
                if votes <= 0:
                    continue
                candidates.append((
                    votes,
                    safe_int(region.get("comparison_count")) or 0,
                    abs(
                        safe_float(region.get("max_action_time_loss_s"))
                        or 0.0
                    ),
                    region,
                ))

            if candidates:
                candidates.sort(
                    key=lambda item: item[:3],
                    reverse=True,
                )
                chosen_region = candidates[0][3]
                pattern["region_label"] = chosen_region.get("region_label")
                pattern["start_distance_m"] = chosen_region.get(
                    "start_distance_m"
                )
                pattern["end_distance_m"] = chosen_region.get(
                    "end_distance_m"
                )
                pattern["track_location"] = chosen_region.get(
                    "track_location"
                )
                chosen_region.setdefault(
                    "brake_release_patterns",
                    [],
                ).append(pattern)
            else:
                pattern["region_label"] = None

            patterns.append(pattern)

    patterns.sort(
        key=lambda item: (
            -safe_int(item.get("comparison_count"))
            if safe_int(item.get("comparison_count")) is not None
            else 0,
            -abs(safe_float(item.get("median_delta_m")) or 0.0),
            safe_float(item.get("reference_release_m")) or 999999.0,
        )
    )

    for region in priority_regions or []:
        values = region.get("brake_release_patterns", []) or []
        values.sort(
            key=lambda item: (
                -safe_int(item.get("comparison_count"))
                if safe_int(item.get("comparison_count")) is not None
                else 0,
                -abs(safe_float(item.get("median_delta_m")) or 0.0),
            )
        )

    return patterns

def _build_repeated_throttle_patterns(
    findings,
    priority_regions,
    *,
    fact_key,
    point_key,
    min_delta_m,
    tolerance_m,
    region_field,
):
    """
    Agrega onset/release de acelerador por punto físico de referencia.

    Reglas conservadoras:
    - >=2 comparaciones distintas;
    - una muestra por comparación;
    - misma dirección de coaching;
    - si existe evidencia accionable en dirección opuesta para el mismo punto,
      no se promueve ningún patrón;
    - magnitud = mediana firmada.
    """
    rows = []
    delta_key = "comparison_minus_reference_m"

    for finding in findings or []:
        if not isinstance(finding, dict):
            continue
        fact = finding.get(fact_key)
        if not isinstance(fact, dict):
            continue
        reference_point = safe_float(fact.get(point_key))
        delta = safe_float(fact.get(delta_key))
        direction = fact.get("coaching_direction")
        comparison = finding.get("comparison")
        if (
            reference_point is None
            or delta is None
            or not comparison
            or direction not in {"later", "earlier"}
            or abs(delta) < min_delta_m
        ):
            continue
        rows.append(finding)

    rows.sort(
        key=lambda item: safe_float(
            (item.get(fact_key) or {}).get(point_key)
        ) or 0.0
    )

    clusters = []
    for row in rows:
        reference_point = safe_float(
            (row.get(fact_key) or {}).get(point_key)
        )
        placed = False
        for cluster in clusters:
            if abs(reference_point - cluster["anchor_m"]) <= tolerance_m:
                cluster["rows"].append(row)
                placed = True
                break
        if not placed:
            clusters.append({
                "anchor_m": reference_point,
                "rows": [row],
            })

    region_members = []
    for region in priority_regions or []:
        if not isinstance(region, dict):
            continue
        keys = {
            (item.get("comparison"), safe_int(item.get("episode_id")))
            for item in (region.get("findings", []) or [])
            if isinstance(item, dict)
        }
        region.setdefault(region_field, [])
        region_members.append((region, keys))

    patterns = []

    for cluster in clusters:
        by_direction = {}
        for row in cluster["rows"]:
            direction = (row.get(fact_key) or {}).get("coaching_direction")
            by_direction.setdefault(direction, []).append(row)

        actionable_directions = {
            direction
            for direction, direction_rows in by_direction.items()
            if direction in {"later", "earlier"} and direction_rows
        }
        if len(actionable_directions) > 1:
            continue

        for direction, direction_rows in by_direction.items():
            best_by_comparison = {}
            for row in direction_rows:
                comparison = str(row.get("comparison"))
                action_loss = abs(
                    safe_float(row.get("action_time_loss_s")) or 0.0
                )
                episode_id = safe_int(row.get("episode_id"))
                score = (
                    action_loss,
                    -(episode_id if episode_id is not None else 999999),
                )
                previous = best_by_comparison.get(comparison)
                if previous is None or score > previous[0]:
                    best_by_comparison[comparison] = (score, row)

            selected = [item[1] for item in best_by_comparison.values()]
            if len(selected) < 2:
                continue

            signed_deltas = [
                safe_float((row.get(fact_key) or {}).get(delta_key))
                for row in selected
            ]
            signed_deltas = [value for value in signed_deltas if value is not None]
            if len(signed_deltas) < 2:
                continue

            median_delta = float(statistics.median(signed_deltas))
            magnitude = int(round(abs(median_delta)))
            if magnitude < min_delta_m:
                continue

            comparisons = sorted(str(row.get("comparison")) for row in selected)
            reference_points = [
                safe_float((row.get(fact_key) or {}).get(point_key))
                for row in selected
            ]
            reference_points = [v for v in reference_points if v is not None]

            reference_event_ids = sorted({
                str((row.get(fact_key) or {}).get("reference_event_id") or "").strip()
                for row in selected
                if str((row.get(fact_key) or {}).get("reference_event_id") or "").strip()
            })

            pattern = {
                "status": "REPEATED",
                "comparison_count": len(comparisons),
                "comparisons": comparisons,
                "coaching_direction": direction,
                "coaching_magnitude_m": magnitude,
                "median_delta_m": median_delta,
                "deltas_m": sorted(signed_deltas),
                point_key: (
                    float(statistics.median(reference_points))
                    if reference_points else None
                ),
                "aggregation": "median_comparison_minus_reference_m",
                "reference_event_id": (
                    reference_event_ids[0]
                    if len(reference_event_ids) == 1
                    else None
                ),
                "reference_event_ids": reference_event_ids,
                "source_findings": [
                    {
                        "comparison": row.get("comparison"),
                        "episode_id": safe_int(row.get("episode_id")),
                    }
                    for row in selected
                ],
            }

            selected_keys = {
                (row.get("comparison"), safe_int(row.get("episode_id")))
                for row in selected
            }
            candidates = []
            for region, keys in region_members:
                votes = len(selected_keys & keys)
                if votes <= 0:
                    continue
                candidates.append((
                    votes,
                    safe_int(region.get("comparison_count")) or 0,
                    abs(safe_float(region.get("max_action_time_loss_s")) or 0.0),
                    region,
                ))

            if candidates:
                candidates.sort(key=lambda item: item[:3], reverse=True)
                chosen_region = candidates[0][3]
                pattern["region_label"] = chosen_region.get("region_label")
                pattern["start_distance_m"] = chosen_region.get("start_distance_m")
                pattern["end_distance_m"] = chosen_region.get("end_distance_m")
                pattern["track_location"] = chosen_region.get("track_location")
                chosen_region.setdefault(region_field, []).append(pattern)
            else:
                # El patrón físico puede ser válido aunque sus episodios no
                # formen una priority_region. Conservar igualmente ubicación
                # de pista si las muestras coinciden en el mismo lugar.
                pattern["region_label"] = None

                locations = [
                    row.get("track_location")
                    for row in selected
                    if isinstance(row.get("track_location"), dict)
                    and row.get("track_location", {}).get("status") == "RESOLVED"
                ]

                labels = {
                    str(location.get("label"))
                    for location in locations
                    if location.get("label")
                }

                if len(labels) == 1 and locations:
                    pattern["track_location"] = dict(locations[0])

                starts = [
                    safe_float(row.get("start_distance_m"))
                    for row in selected
                ]
                starts = [value for value in starts if value is not None]

                ends = [
                    safe_float(row.get("end_distance_m"))
                    for row in selected
                ]
                ends = [value for value in ends if value is not None]

                if starts:
                    pattern["start_distance_m"] = min(starts)
                if ends:
                    pattern["end_distance_m"] = max(ends)

            patterns.append(pattern)

    patterns.sort(
        key=lambda item: (
            -(safe_int(item.get("comparison_count")) or 0),
            -abs(safe_float(item.get("median_delta_m")) or 0.0),
            safe_float(item.get(point_key)) or 999999.0,
        )
    )

    for region in priority_regions or []:
        values = region.get(region_field, []) or []
        values.sort(
            key=lambda item: (
                -(safe_int(item.get("comparison_count")) or 0),
                -abs(safe_float(item.get("median_delta_m")) or 0.0),
            )
        )

    return patterns
