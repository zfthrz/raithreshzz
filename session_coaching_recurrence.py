"""Deterministic recurrence and point-pattern coaching logic."""

import re

from deterministic_coaching import (
    _single_event_direction,
    safe_float,
    safe_int,
)
from session_coaching_intervals import (
    _interval_intersection_length,
    _interval_total_length,
    _merge_distance_intervals,
    _minimum_interval_gap,
    _plan_overlap_m,
    _same_plan_region,
)
from session_coaching_location import track_location_label
from session_coaching_plan import (
    _brake_release_target_text,
    _braking_point_target_text,
    _throttle_onset_target_text,
    _throttle_release_target_text,
)
from session_coaching_priority import _alpha_label
from session_coaching_reference import (
    _reference_brake_event_catalog,
    _reference_brake_profile_for_region,
    _reference_throttle_event_catalog,
    _reference_throttle_profile_for_region,
)

SESSION_PRIORITY_POLICY_VERSION = "1.9"

def _apply_recurrence_aware_session_priority(
    plan,
    repeated_braking_point_patterns,
    repeated_brake_release_patterns,
    repeated_throttle_onset_patterns,
    repeated_throttle_release_patterns,
    max_items=3,
):
    """
    v3.10.8

    Reordena únicamente el plan GLOBAL de próxima tanda.

    No cambia:
      - detección de episodios;
      - clasificación/ranking dentro de cada comparación;
      - detectores de freno/acelerador;
      - hechos objetivos.

    Un patrón físico repetido puede desplazar a un hallazgo individual si
    reaparece en múltiples comparaciones.
    """
    base_plan = [
        item
        for item in (
            plan
            or []
        )
        if isinstance(
            item,
            dict,
        )
    ]

    pattern_specs = [
        (
            repeated_braking_point_patterns,
            "braking_point_patterns",
            "braking_point_target",
            _braking_point_target_text,
        ),
        (
            repeated_brake_release_patterns,
            "brake_release_patterns",
            "brake_release_target",
            _brake_release_target_text,
        ),
        (
            repeated_throttle_onset_patterns,
            "throttle_onset_patterns",
            "throttle_onset_target",
            _throttle_onset_target_text,
        ),
        (
            repeated_throttle_release_patterns,
            "throttle_release_patterns",
            "throttle_release_target",
            _throttle_release_target_text,
        ),
    ]

    # Primero adjuntamos patrones repetidos a zonas ya presentes.
    for (
        patterns,
        field_name,
        target_name,
        target_builder,
    ) in pattern_specs:
        for pattern in (
            patterns
            or []
        ):
            if (
                not isinstance(
                    pattern,
                    dict,
                )
                or
                pattern.get(
                    "status"
                )
                != "REPEATED"
            ):
                continue

            matching = [
                item
                for item in base_plan
                if _same_plan_region(
                    item,
                    pattern,
                )
            ]

            if not matching:
                continue

            matching.sort(
                key=lambda item: (
                    _plan_overlap_m(
                        item,
                        pattern,
                    ),
                    int(
                        item.get(
                            "kind"
                        )
                        == "repeated_region"
                    ),
                ),
                reverse=True,
            )

            _attach_point_pattern_to_plan_item(
                matching[0],
                pattern,
                field_name,
                target_name,
                target_builder,
            )

    standalone = (
        _standalone_repeated_point_candidates(
            base_plan,
            pattern_specs,
        )
    )

    candidates = (
        base_plan
        +
        standalone
    )

    candidates.sort(
        key=_session_plan_sort_key
    )

    selected = candidates[
        :max_items
    ]

    for index, item in enumerate(
        selected
    ):
        item["plan_label"] = (
            _alpha_label(
                index
            )
        )

        basis = item.setdefault(
            "session_priority_basis",
            {},
        )
        basis["policy_version"] = (
            SESSION_PRIORITY_POLICY_VERSION
        )
        basis["kind"] = item.get(
            "kind"
        )
        basis["comparison_count"] = (
            safe_int(
                item.get(
                    "comparison_count"
                )
            )
            or 0
        )
        basis["repeated_evidence"] = (
            item.get(
                "kind"
            )
            in {
                "repeated_region",
                "repeated_point_pattern",
            }
        )

    return selected

def _attach_point_anchored_reference_profiles(plan, source_data):
    """Completa perfiles de forma para cues espaciales sin autorizar targets nuevos."""
    if not isinstance(plan, list):
        return plan

    for item in plan:
        if not isinstance(item, dict):
            continue

        profiles = [
            profile
            for profile in (item.get("reference_action_profiles", []) or [])
            if isinstance(profile, dict)
        ]
        channels = {
            str(profile.get("channel") or "")
            for profile in profiles
        }

        for channel in ("brake", "throttle"):
            if channel in channels:
                continue
            profile = _point_anchored_profile(item, source_data, channel)
            if profile is not None:
                profiles.append(profile)
                channels.add(channel)

        item["reference_action_profiles"] = profiles

    return plan

def _attach_point_pattern_to_plan_item(
    item,
    pattern,
    field_name,
    target_name,
    target_builder,
):
    if not isinstance(item, dict) or not isinstance(pattern, dict):
        return

    existing = item.setdefault(
        field_name,
        [],
    )

    if pattern not in existing:
        existing.append(
            pattern
        )

    if not item.get(
        target_name
    ):
        item[target_name] = target_builder(
            pattern
        )

    comparisons = {
        str(value)
        for value in (
            item.get(
                "comparisons",
                [],
            )
            or []
        )
        if value
    }

    comparisons.update(
        str(value)
        for value in (
            pattern.get(
                "comparisons",
                [],
            )
            or []
        )
        if value
    )

    item["comparisons"] = sorted(
        comparisons
    )
    item["comparison_count"] = max(
        safe_int(
            item.get(
                "comparison_count"
            )
        )
        or 0,
        safe_int(
            pattern.get(
                "comparison_count"
            )
        )
        or 0,
        len(comparisons),
    )

    starts = [
        safe_float(
            item.get(
                "start_distance_m"
            )
        ),
        safe_float(
            pattern.get(
                "start_distance_m"
            )
        ),
    ]
    starts = [
        value
        for value in starts
        if value is not None
    ]

    ends = [
        safe_float(
            item.get(
                "end_distance_m"
            )
        ),
        safe_float(
            pattern.get(
                "end_distance_m"
            )
        ),
    ]
    ends = [
        value
        for value in ends
        if value is not None
    ]

    if starts:
        item["start_distance_m"] = min(
            starts
        )

    if ends:
        item["end_distance_m"] = max(
            ends
        )

    basis = item.setdefault(
        "session_priority_basis",
        {},
    )
    basis["repeated_evidence"] = True
    basis["point_pattern_count"] = (
        safe_int(
            basis.get(
                "point_pattern_count"
            )
        )
        or 0
    ) + 1
    basis["comparison_count"] = max(
        safe_int(
            basis.get(
                "comparison_count"
            )
        )
        or 0,
        item.get(
            "comparison_count",
            0,
        ),
    )

def _attach_repeated_throttle_patterns_to_plan(
    plan,
    onset_patterns,
    release_patterns,
):
    """
    Un patrón repetido de throttle puede aparecer en una zona elegida para el
    plan aunque esa zona haya entrado como single_priority_finding.

    v3.8.30 sólo adjuntaba patrones que ya vivían dentro de priority_regions;
    eso dejaba, por ejemplo, un onset repetido de Bus Stop en el respaldo
    técnico pero fuera del coaching de Zona C.
    """
    if not isinstance(plan, list):
        return plan

    def overlap_m(a_start, a_end, b_start, b_end):
        values = [
            safe_float(a_start),
            safe_float(a_end),
            safe_float(b_start),
            safe_float(b_end),
        ]
        if any(value is None for value in values):
            return 0.0

        a0, a1, b0, b1 = values
        return max(0.0, min(a1, b1) - max(a0, b0))

    def attach(patterns, field_name, target_name, target_builder):
        for pattern in patterns or []:
            if (
                not isinstance(pattern, dict)
                or pattern.get("status") != "REPEATED"
            ):
                continue

            candidates = []
            for item in plan:
                overlap = overlap_m(
                    item.get("start_distance_m"),
                    item.get("end_distance_m"),
                    pattern.get("start_distance_m"),
                    pattern.get("end_distance_m"),
                )
                if overlap <= 0.0:
                    continue

                item_location = track_location_label(item)
                pattern_location = track_location_label(pattern)
                same_location = int(
                    bool(item_location)
                    and bool(pattern_location)
                    and item_location == pattern_location
                )

                candidates.append(
                    (same_location, overlap, item)
                )

            if not candidates:
                continue

            candidates.sort(
                key=lambda row: (row[0], row[1]),
                reverse=True,
            )
            item = candidates[0][2]

            existing = item.setdefault(field_name, [])
            signature = (
                pattern.get("reference_onset_m"),
                pattern.get("reference_release_m"),
                pattern.get("coaching_direction"),
                pattern.get("coaching_magnitude_m"),
            )
            existing_signatures = {
                (
                    value.get("reference_onset_m"),
                    value.get("reference_release_m"),
                    value.get("coaching_direction"),
                    value.get("coaching_magnitude_m"),
                )
                for value in existing
                if isinstance(value, dict)
            }

            if signature not in existing_signatures:
                existing.append(pattern)

            if not item.get(target_name):
                item[target_name] = target_builder(pattern)

    attach(
        onset_patterns,
        "throttle_onset_patterns",
        "throttle_onset_target",
        _throttle_onset_target_text,
    )
    attach(
        release_patterns,
        "throttle_release_patterns",
        "throttle_release_target",
        _throttle_release_target_text,
    )

    return plan

def _brake_throttle_relation_from_channels(
    channels,
):
    by_channel = {
        str(item.get("channel")):
            item
        for item in (
            channels
            or []
        )
        if (
            isinstance(item, dict)
            and
            item.get("channel")
        )
    }

    brake = by_channel.get(
        "brake"
    )
    throttle = by_channel.get(
        "throttle"
    )

    if not brake or not throttle:
        return None

    brake_intervals = (
        _merge_distance_intervals(
            brake.get(
                "event_intervals_m",
                [],
            )
        )
    )
    throttle_intervals = (
        _merge_distance_intervals(
            throttle.get(
                "event_intervals_m",
                [],
            )
        )
    )

    if (
        not brake_intervals
        or
        not throttle_intervals
    ):
        return None

    overlap_m = (
        _interval_intersection_length(
            brake_intervals,
            throttle_intervals,
        )
    )

    brake_length_m = (
        _interval_total_length(
            brake_intervals
        )
    )
    throttle_length_m = (
        _interval_total_length(
            throttle_intervals
        )
    )

    relation = {
        "kind":
            None,
        "overlap_m":
            overlap_m,
        "gap_m":
            None,
        "brake_event_length_m":
            brake_length_m,
        "throttle_event_length_m":
            throttle_length_m,
        "brake_intervals_m":
            [
                [start, end]
                for start, end in brake_intervals
            ],
        "throttle_intervals_m":
            [
                [start, end]
                for start, end in throttle_intervals
            ],
    }

    if overlap_m > 1e-9:
        shorter_length = min(
            brake_length_m,
            throttle_length_m,
        )

        if (
            shorter_length > 0.0
            and
            overlap_m >= (
                0.95
                * shorter_length
            )
        ):
            relation["kind"] = (
                "substantial_overlap"
            )
        else:
            relation["kind"] = (
                "partial_overlap"
            )

        relation["gap_m"] = 0.0
        return relation

    brake_first_start = (
        brake_intervals[0][0]
    )
    brake_last_end = (
        brake_intervals[-1][1]
    )
    throttle_first_start = (
        throttle_intervals[0][0]
    )
    throttle_last_end = (
        throttle_intervals[-1][1]
    )

    if (
        brake_last_end
        <= throttle_first_start
    ):
        relation["kind"] = (
            "brake_then_throttle"
        )
        relation["gap_m"] = (
            throttle_first_start
            - brake_last_end
        )
        return relation

    if (
        throttle_last_end
        <= brake_first_start
    ):
        relation["kind"] = (
            "throttle_then_brake"
        )
        relation["gap_m"] = (
            brake_first_start
            - throttle_last_end
        )
        return relation

    relation["kind"] = (
        "interleaved_without_overlap"
    )
    relation["gap_m"] = (
        _minimum_interval_gap(
            brake_intervals,
            throttle_intervals,
        )
    )
    return relation

def _channel_direction_coaching_label(
    channel,
    evidence,
):
    direction = _single_event_direction(
        evidence
    )

    labels = {
        ("throttle", "higher_in_comparison_lap"):
            "más acelerador",
        ("throttle", "lower_in_comparison_lap"):
            "menos acelerador",
        ("brake", "higher_in_comparison_lap"):
            "más freno",
        ("brake", "lower_in_comparison_lap"):
            "menos freno",
        ("steering_magnitude", "higher_in_comparison_lap"):
            "mayor magnitud de dirección/volante",
        ("steering_magnitude", "lower_in_comparison_lap"):
            "menor magnitud de dirección/volante",
    }

    if (channel, direction) in labels:
        return labels[
            (channel, direction)
        ]

    fallback = {
        "throttle":
            "modulación distinta del acelerador",
        "brake":
            "aplicación distinta del freno",
        "steering_magnitude":
            "magnitud distinta de dirección/volante",
    }

    return fallback.get(
        channel,
        str(channel),
    )

def _channel_quantitative_fact(
    channel,
    evidence,
):
    """
    Resume magnitudes observadas sin inferir causalidad.

    Para freno/acelerador las diferencias se expresan en puntos porcentuales
    porque los canales de origen están en percent. Para steering_magnitude se
    conservan las unidades nativas del input de volante; no se asumen grados.
    """
    if not isinstance(evidence, dict):
        evidence = {}

    events = [
        item
        for item in (evidence.get("events", []) or [])
        if isinstance(item, dict)
    ]

    event_mean_differences = [
        value
        for value in (
            safe_float(item.get("mean_difference"))
            for item in events
        )
        if value is not None
    ]

    event_peak_differences = [
        value
        for value in (
            safe_float(item.get("peak_difference"))
            for item in events
        )
        if value is not None
    ]

    mean_difference = safe_float(
        evidence.get("mean_of_event_mean_differences")
    )
    peak_difference = safe_float(
        evidence.get("largest_abs_peak_difference")
    )

    if peak_difference is None and event_peak_differences:
        peak_difference = max(
            event_peak_differences,
            key=lambda value: abs(value),
        )

    unit = None

    if channel in ("throttle", "brake"):
        unit = "percentage_points"
    elif channel == "steering_magnitude":
        unit = "steering_input_units"
    else:
        for event in events:
            raw_unit = event.get("unit")
            if raw_unit:
                unit = str(raw_unit)
                break

    return {
        "mean_difference": mean_difference,
        "peak_difference": peak_difference,
        "event_mean_min": (
            min(event_mean_differences)
            if event_mean_differences
            else None
        ),
        "event_mean_max": (
            max(event_mean_differences)
            if event_mean_differences
            else None
        ),
        "event_count": len(events),
        "unit": unit,
    }

def _comparison_quality_map(quality_gate):
    return {
        str(row.get("comparison")): row
        for row in (quality_gate.get("comparisons", []) or [])
        if isinstance(row, dict) and row.get("comparison")
    }

def _empty_repeated_point_plan_item(
    pattern,
):
    return {
        "plan_label": None,
        "kind": "repeated_point_pattern",
        "start_distance_m": pattern.get(
            "start_distance_m"
        ),
        "end_distance_m": pattern.get(
            "end_distance_m"
        ),
        "track_location": pattern.get(
            "track_location"
        ),
        "comparisons": [],
        "comparison_count": 0,
        "observed_differences": [],
        "targets": [],
        "quantitative_observations": [],
        "temporal_relationships": [],
        "temporal_target": None,
        "braking_point_patterns": [],
        "braking_point_target": None,
        "brake_release_patterns": [],
        "brake_release_target": None,
        "throttle_onset_patterns": [],
        "throttle_onset_target": None,
        "throttle_release_patterns": [],
        "throttle_release_target": None,
        "speed_directions": [],
        "propagation_statuses": [],
        "session_priority_basis": {
            "repeated_evidence": True,
            "point_pattern_count": 0,
            "comparison_count": 0,
        },
    }

def _point_anchored_profile(item, source_data, channel):
    """
    v3.10.8.5.4: un onset/release autorizado arrastra la forma del MISMO evento
    de referencia por reference_event_id.

    Esto evita perder el perfil cuando el punto de referencia queda apenas
    fuera del intervalo agregado de la región. La forma sigue siendo
    descriptiva; sólo onset/release conserva autoridad numérica de coaching.
    """
    if channel == "throttle":
        fields = ("throttle_onset_patterns", "throttle_release_patterns")
        catalog_builder = _reference_throttle_event_catalog
        profile_builder = _reference_throttle_profile_for_region
    elif channel == "brake":
        fields = ("braking_point_patterns", "brake_release_patterns")
        catalog_builder = _reference_brake_event_catalog
        profile_builder = _reference_brake_profile_for_region
    else:
        return None

    wanted_ids = _point_pattern_reference_event_ids(item, fields)
    if not wanted_ids:
        return None

    reference_lap = _reference_lap_for_plan_item(item)
    catalog = catalog_builder(source_data, reference_lap=reference_lap)
    wanted = set(wanted_ids)
    matched = [
        event for event in catalog
        if str(event.get("event_id") or "").strip() in wanted
    ]
    if not matched:
        return None

    event = sorted(
        matched,
        key=lambda row: (
            safe_float(row.get("onset_distance_m"))
            if safe_float(row.get("onset_distance_m")) is not None
            else 999999.0,
            str(row.get("event_id") or ""),
        ),
    )[0]
    anchor = safe_float(event.get("onset_distance_m"))
    if anchor is None:
        return None

    synthetic_region = {
        "start_distance_m": anchor - 1.0,
        "end_distance_m": anchor + 1.0,
        "findings": (
            [{"reference_lap": reference_lap}]
            if reference_lap is not None
            else []
        ),
    }
    profile = profile_builder(synthetic_region, source_data)
    if not isinstance(profile, dict):
        return None

    profile = dict(profile)

    # La ventana sintética de 2 m sólo sirve para identificar el evento.
    # No debe contaminar el wording driver-facing con "dentro de la zona".
    if channel == "throttle":
        verbose = "reaplicación sostenida sin volver a soltar dentro de la zona"
        concise = "reaplicación sostenida"
        if profile.get("shape_summary") == verbose:
            profile["shape_summary"] = concise
        sequence = [
            concise if value == verbose else value
            for value in (profile.get("shape_sequence", []) or [])
        ]
        profile["shape_sequence"] = sequence
        for step in (profile.get("steps", []) or []):
            if isinstance(step, dict) and step.get("shape") == verbose:
                step["shape"] = concise

    profile["attachment"] = "point_reference_event_id"
    profile["reference_event_ids"] = wanted_ids
    profile["plan_region_start_m"] = item.get("start_distance_m")
    profile["plan_region_end_m"] = item.get("end_distance_m")
    return profile

def _point_pattern_reference_event_ids(item, fields):
    event_ids = []
    for field in fields:
        for pattern in (item.get(field, []) or []):
            if not isinstance(pattern, dict):
                continue
            event_id = str(pattern.get("reference_event_id") or "").strip()
            if event_id and event_id not in event_ids:
                event_ids.append(event_id)
            for plural_id in (pattern.get("reference_event_ids", []) or []):
                plural_id = str(plural_id or "").strip()
                if plural_id and plural_id not in event_ids:
                    event_ids.append(plural_id)
    return event_ids

def _priority_ranking_map(
    comparison_result,
):
    audit = comparison_result.get(
        "llm_validation_audit",
        {},
    )

    ranking = (
        audit.get(
            "priority_ranking",
            {},
        )
        if isinstance(audit, dict)
        else {}
    )

    rows = (
        ranking.get(
            "classifications",
            [],
        )
        if isinstance(ranking, dict)
        else []
    )

    result = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        episode_id = safe_int(
            row.get(
                "episode_id"
            )
        )

        if episode_id is None:
            continue

        result[episode_id] = {
            "classification":
                row.get(
                    "classification"
                ),

            "relative_priority_rank":
                safe_int(
                    row.get(
                        "relative_priority_rank"
                    )
                ),
        }

    return result

def _reference_lap_for_plan_item(item):
    """Infere la vuelta de referencia desde labels `ref->cmp` del plan."""
    if not isinstance(item, dict):
        return None

    laps = set()
    for label in (item.get("comparisons", []) or []):
        match = re.match(r"^\s*(\d+)\s*->", str(label))
        if match:
            laps.add(int(match.group(1)))

    return next(iter(laps)) if len(laps) == 1 else None

def _sanitize_recurrence_regions(regions):
    """
    Elimina metadata dependiente del ranker de la capa física de recurrencia.

    v3.10.8.5.4: NO muta los dicts originales. priority_findings y
    recurrence_findings pueden compartir objetos durante la construcción;
    sanear in-place borraba relative_priority_rank/classification también de
    la capa prioritaria y terminaba degradando el desempate del plan.
    """
    if not isinstance(regions, list):
        return []

    cleaned_regions = []

    for region in regions:
        if not isinstance(region, dict):
            continue

        cleaned = dict(region)
        cleaned.pop("priority_episode_count", None)
        cleaned.pop("best_episode_priority_rank", None)
        cleaned.pop("best_comparison_priority_rank", None)

        cleaned_repeated = []
        for repeated in (region.get("repeated_differences", []) or []):
            if not isinstance(repeated, dict):
                continue
            repeated_copy = dict(repeated)
            repeated_copy.pop("priority_episode_count", None)
            cleaned_repeated.append(repeated_copy)
        cleaned["repeated_differences"] = cleaned_repeated

        findings = []
        for finding in (region.get("findings", []) or []):
            if not isinstance(finding, dict):
                continue
            finding_copy = dict(finding)
            finding_copy.pop("relative_priority_rank", None)
            finding_copy.pop("classification", None)
            findings.append(finding_copy)

        findings.sort(
            key=lambda item: (
                str(item.get("comparison") or ""),
                item.get("start_distance_m")
                if item.get("start_distance_m") is not None
                else 999999.0,
                item.get("end_distance_m")
                if item.get("end_distance_m") is not None
                else 999999.0,
                item.get("episode_id")
                if item.get("episode_id") is not None
                else 999999,
            )
        )
        cleaned["findings"] = findings
        cleaned_regions.append(cleaned)

    return cleaned_regions

def _session_plan_sort_key(
    item,
):
    """
    v3.10.8.5.4: prioridad por especificidad + calidad del hallazgo.

    Jerarquía:
      1) punto físico REPETIDO (Braking Point 2.1 / Throttle Point 1.2.1);
      2) punto físico VALID individual autorizado;
      3) reference_action_profile concreto;
      4) resto de evidencia accionable.

    Dentro del tier de puntos repetidos, el soporte del propio punto físico
    precede a la recurrencia más amplia de la zona. Esto evita que una zona
    frecuente con un punto observado pocas veces desplace a un punto físico
    mejor repetido.

    Dentro del tier individual, el orden es:
      comparison_priority_rank -> episode_priority_rank -> pérdida local.
    La posición en pista es únicamente el último desempate absoluto.
    """
    kind = item.get("kind")

    point_fields = (
        "braking_point_patterns",
        "brake_release_patterns",
        "throttle_onset_patterns",
        "throttle_release_patterns",
    )
    point_patterns = [
        pattern
        for field in point_fields
        for pattern in (item.get(field, []) or [])
        if isinstance(pattern, dict)
    ]

    repeated_point_count = sum(
        1 for pattern in point_patterns
        if (
            pattern.get("status") == "REPEATED"
            and bool(pattern.get("authorized_numeric_coaching"))
        )
    )
    repeated_point_support_count = max(
        [
            safe_int(pattern.get("comparison_count")) or 1
            for pattern in point_patterns
            if (
                pattern.get("status") == "REPEATED"
                and bool(pattern.get("authorized_numeric_coaching"))
            )
        ],
        default=0,
    )
    single_authorized_point_count = sum(
        1 for pattern in point_patterns
        if (
            pattern.get("status") == "SINGLE"
            and bool(pattern.get("authorized_numeric_coaching"))
        )
    )
    point_pattern_count = len(point_patterns)

    profile_count = len([
        profile
        for profile in (item.get("reference_action_profiles", []) or [])
        if isinstance(profile, dict) and str(profile.get("shape_summary") or "").strip()
    ])

    if repeated_point_count:
        evidence_tier = 0
    elif single_authorized_point_count:
        evidence_tier = 1
    elif profile_count:
        evidence_tier = 2
    else:
        evidence_tier = 3

    repeated = int(
        kind in {"repeated_region", "repeated_point_pattern"}
    )
    comparison_count = safe_int(item.get("comparison_count")) or 0
    comparison_rank = (
        safe_int(item.get("comparison_priority_rank"))
        or safe_int((item.get("source_priority") or {}).get("comparison_priority_rank"))
        or 999999
    )
    episode_rank = (
        safe_int(item.get("best_episode_priority_rank"))
        or safe_int(item.get("episode_priority_rank"))
        or safe_int((item.get("source_priority") or {}).get("episode_priority_rank"))
        or 999999
    )
    max_loss = abs(
        safe_float(item.get("max_action_time_loss_s"))
        or safe_float(item.get("action_time_loss_s"))
        or 0.0
    )
    start = safe_float(item.get("start_distance_m"))
    start_key = start if start is not None else 999999.0

    if evidence_tier == 0:
        return (
            0,
            -repeated_point_support_count,
            -repeated_point_count,
            -comparison_count,
            comparison_rank,
            episode_rank,
            -max_loss,
            -point_pattern_count,
            start_key,
        )

    if evidence_tier == 1:
        return (
            1,
            comparison_rank,
            episode_rank,
            -max_loss,
            -single_authorized_point_count,
            -point_pattern_count,
            start_key,
            0,
        )

    if evidence_tier == 2:
        return (
            2,
            -repeated,
            -comparison_count,
            comparison_rank,
            episode_rank,
            -max_loss,
            -profile_count,
            start_key,
        )

    return (
        3,
        -repeated,
        -comparison_count,
        comparison_rank,
        episode_rank,
        -max_loss,
        -point_pattern_count,
        start_key,
    )

def _standalone_repeated_point_candidates(
    existing_plan,
    pattern_specs,
):
    """
    Crea candidatos sólo para patrones físicos repetidos que todavía no
    están representados por una zona del plan.

    Ejemplo Spa:
      Les Combes reaplicación repetida -> candidato de sesión propio.
    """
    candidates = []

    for (
        patterns,
        field_name,
        target_name,
        target_builder,
    ) in pattern_specs:
        for pattern in (
            patterns
            or []
        ):
            if (
                not isinstance(
                    pattern,
                    dict,
                )
                or
                pattern.get(
                    "status"
                )
                != "REPEATED"
                or (
                    safe_int(
                        pattern.get(
                            "comparison_count"
                        )
                    )
                    or 0
                )
                < 2
            ):
                continue

            represented = any(
                _same_plan_region(
                    item,
                    pattern,
                )
                for item in (
                    existing_plan
                    or []
                )
                if isinstance(
                    item,
                    dict,
                )
            )

            if represented:
                continue

            candidate = next(
                (
                    item
                    for item in candidates
                    if _same_plan_region(
                        item,
                        pattern,
                    )
                ),
                None,
            )

            if candidate is None:
                candidate = (
                    _empty_repeated_point_plan_item(
                        pattern
                    )
                )
                candidates.append(
                    candidate
                )

            _attach_point_pattern_to_plan_item(
                candidate,
                pattern,
                field_name,
                target_name,
                target_builder,
            )

    return candidates
