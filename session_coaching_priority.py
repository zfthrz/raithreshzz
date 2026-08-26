"""Deterministic session coaching priority-region construction."""

from deterministic_coaching import (
    _aggregate_channel_quantitative_facts,
    _aggregate_region_brake_throttle_relation,
    _coaching_target_for_channel_direction,
    safe_float,
)

def _alpha_label(index):
    index = int(index)
    letters = ""

    while True:
        index, remainder = divmod(index, 26)
        letters = chr(ord("A") + remainder) + letters

        if index == 0:
            return letters

        index -= 1

def _finding_interval(finding):
    start = safe_float(
        finding.get("start_distance_m")
    )
    end = safe_float(
        finding.get("end_distance_m")
    )

    if start is None or end is None:
        return None

    if end < start:
        start, end = end, start

    return start, end

def _findings_share_spatial_region(
    first,
    second,
):
    """
    Agrupación descriptiva intra-sesión, NO matcher persistente.

    Dos episodios se consideran de la misma región sólo si tienen una
    superposición espacial material. Esto evita declarar un patrón global
    simplemente porque el mismo canal apareció en curvas distintas.

    No se usa distancia de centro ni un umbral de similitud aprendido.
    """
    interval_a = _finding_interval(first)
    interval_b = _finding_interval(second)

    if interval_a is None or interval_b is None:
        return False

    a0, a1 = interval_a
    b0, b1 = interval_b

    overlap = max(
        0.0,
        min(a1, b1) - max(a0, b0),
    )

    if overlap <= 0.0:
        return False

    len_a = max(a1 - a0, 1.0)
    len_b = max(b1 - b0, 1.0)

    # Exige al menos 20 % del episodio más corto, con tope de 20 m.
    # Es una regla conservadora de reporte; no se persiste como matcher.
    required_overlap = min(
        20.0,
        0.20 * min(len_a, len_b),
    )

    return overlap >= required_overlap

def _build_priority_regions(
    priority_findings,
):
    findings = [
        item
        for item in priority_findings
        if _finding_interval(item) is not None
    ]

    count = len(findings)

    adjacency = {
        index: set()
        for index in range(count)
    }

    for left in range(count):
        for right in range(left + 1, count):
            if _findings_share_spatial_region(
                findings[left],
                findings[right],
            ):
                adjacency[left].add(right)
                adjacency[right].add(left)

    components = []
    visited = set()

    for root in range(count):
        if root in visited:
            continue

        stack = [root]
        component = []
        visited.add(root)

        while stack:
            current = stack.pop()
            component.append(
                findings[current]
            )

            for neighbour in sorted(
                adjacency[current]
            ):
                if neighbour in visited:
                    continue

                visited.add(neighbour)
                stack.append(neighbour)

        components.append(component)

    regions = []

    for component in components:
        starts = []
        ends = []
        comparisons = set()

        for finding in component:
            interval = _finding_interval(
                finding
            )

            if interval is not None:
                starts.append(interval[0])
                ends.append(interval[1])

            comparison = finding.get(
                "comparison"
            )

            if comparison:
                comparisons.add(
                    str(comparison)
                )

        channel_rows = {}

        for finding in component:
            comparison = str(
                finding.get("comparison")
            )

            for channel_fact in (
                finding.get("channels", [])
                or []
            ):
                channel = channel_fact.get(
                    "channel"
                )
                direction = (
                    channel_fact.get("direction")
                    or "unknown"
                )

                if not channel:
                    continue

                key = (
                    str(channel),
                    str(direction),
                )

                row = channel_rows.setdefault(
                    key,
                    {
                        "channel":
                            str(channel),
                        "direction":
                            str(direction),
                        "description":
                            channel_fact.get(
                                "description"
                            ),
                        "comparisons":
                            set(),
                        "episode_count":
                            0,
                        "priority_episode_count":
                            0,
                        "quantitative_facts":
                            [],
                    },
                )

                row["comparisons"].add(
                    comparison
                )
                row["episode_count"] += 1
                if finding.get("classification") == "PRIORITARIO":
                    row["priority_episode_count"] += 1

                quantitative = channel_fact.get(
                    "quantitative"
                )
                if isinstance(quantitative, dict):
                    row["quantitative_facts"].append(
                        quantitative
                    )

        repeated_differences = []

        channels_with_directional_repeat = set()

        # Si el mismo canal repite AMBAS direcciones en la misma región a
        # través de múltiples comparaciones, no generamos dos targets
        # contradictorios. Se degrada a patrón mixto/replicar secuencia.
        repeated_direction_count_by_channel = {}
        for (channel, _direction), row in channel_rows.items():
            if len(row.get("comparisons", set())) < 2:
                continue
            repeated_direction_count_by_channel[channel] = (
                repeated_direction_count_by_channel.get(channel, 0) + 1
            )

        for (
            channel,
            direction,
        ), row in channel_rows.items():
            comparison_count = len(
                row["comparisons"]
            )

            if comparison_count < 2:
                continue

            if repeated_direction_count_by_channel.get(channel, 0) > 1:
                continue

            channels_with_directional_repeat.add(
                channel
            )

            qualitative_target = _coaching_target_for_channel_direction(
                channel,
                direction,
            )

            repeated_differences.append({
                "channel":
                    channel,
                "direction":
                    direction,
                "description":
                    row.get(
                        "description"
                    ),
                "comparison_count":
                    comparison_count,
                "recurrence_episode_count":
                    row[
                        "episode_count"
                    ],
                "priority_episode_count":
                    row.get(
                        "priority_episode_count",
                        0,
                    ),
                "target":
                    qualitative_target,
                "actionability": (
                    "qualitative_reference_alignment"
                    if qualitative_target
                    else "observation_only"
                ),
                "target_source": (
                    "deterministic_observed_level_to_reference"
                    if qualitative_target
                    else "observation_only_channel_difference"
                ),
                "quantitative":
                    _aggregate_channel_quantitative_facts(
                        row.get(
                            "quantitative_facts",
                            [],
                        )
                    ),
            })

        channel_presence = {}

        for (
            channel,
            _direction,
        ), row in channel_rows.items():
            entry = channel_presence.setdefault(
                channel,
                {
                    "comparisons": set(),
                    "episode_count": 0,
                    "priority_episode_count": 0,
                    "quantitative_facts": [],
                },
            )

            entry["comparisons"].update(
                row["comparisons"]
            )
            entry["episode_count"] += (
                row["episode_count"]
            )
            entry["priority_episode_count"] += (
                row.get("priority_episode_count", 0)
            )
            entry["quantitative_facts"].extend(
                row.get(
                    "quantitative_facts",
                    [],
                )
            )

        for channel, row in channel_presence.items():
            if channel in channels_with_directional_repeat:
                continue

            comparison_count = len(
                row["comparisons"]
            )

            if comparison_count < 2:
                continue

            description = {
                "throttle":
                    "modulación distinta del acelerador",
                "brake":
                    "aplicación distinta del freno",
                "steering_magnitude":
                    "magnitud distinta de dirección/volante",
            }.get(
                channel,
                str(channel),
            )

            repeated_differences.append({
                "channel":
                    channel,
                "direction":
                    "mixed_across_comparisons",
                "description":
                    description,
                "comparison_count":
                    comparison_count,
                "recurrence_episode_count":
                    row[
                        "episode_count"
                    ],
                "priority_episode_count":
                    row.get(
                        "priority_episode_count",
                        0,
                    ),
                "target":
                    _coaching_target_for_channel_direction(
                        channel,
                        "mixed",
                    ),
                "actionability": "observation_only",
                "target_source": "observation_only_channel_difference",
                "quantitative":
                    _aggregate_channel_quantitative_facts(
                        row.get(
                            "quantitative_facts",
                            [],
                        )
                    ),
            })

        repeated_differences.sort(
            key=lambda item: (
                -item[
                    "comparison_count"
                ],
                -item.get(
                    "recurrence_episode_count",
                    0,
                ),
                item[
                    "description"
                ]
                or "",
            )
        )

        best_comparison_rank = min(
            (
                item.get(
                    "comparison_priority_rank"
                )
                if item.get(
                    "comparison_priority_rank"
                ) is not None
                else 999999
            )
            for item in component
        )

        best_episode_rank = min(
            (
                item.get(
                    "relative_priority_rank"
                )
                if item.get(
                    "relative_priority_rank"
                ) is not None
                else 999999
            )
            for item in component
        )

        max_action_loss = max(
            abs(
                safe_float(
                    item.get(
                        "action_time_loss_s"
                    )
                )
                or 0.0
            )
            for item in component
        )

        speed_directions = sorted({
            direction
            for item in component
            for direction in (
                item.get(
                    "speed_directions",
                    [],
                )
                or []
            )
        })

        propagation_statuses = sorted({
            status
            for item in component
            for status in (
                item.get(
                    "propagation_statuses",
                    [],
                )
                or []
            )
        })

        region_brake_throttle_relation = (
            _aggregate_region_brake_throttle_relation(
                component
            )
        )

        regions.append({
            "start_distance_m":
                min(starts)
                if starts
                else None,
            "end_distance_m":
                max(ends)
                if ends
                else None,
            "comparison_count":
                len(comparisons),
            "comparisons":
                sorted(comparisons),
            "recurrence_episode_count":
                len(component),
            "priority_episode_count":
                sum(
                    1
                    for item in component
                    if item.get("classification") == "PRIORITARIO"
                ),
            "best_comparison_priority_rank":
                best_comparison_rank,
            "best_episode_priority_rank":
                best_episode_rank,
            "max_action_time_loss_s":
                max_action_loss,
            "repeated_differences":
                repeated_differences,
            "brake_throttle_relation":
                region_brake_throttle_relation,
            "speed_directions":
                speed_directions,
            "propagation_statuses":
                propagation_statuses,
            "findings":
                sorted(
                    component,
                    key=lambda item: (
                        item.get(
                            "comparison_priority_rank"
                        )
                        if item.get(
                            "comparison_priority_rank"
                        ) is not None
                        else 999999,
                        item.get(
                            "relative_priority_rank"
                        )
                        if item.get(
                            "relative_priority_rank"
                        ) is not None
                        else 999999,
                    ),
                ),
        })

    regions.sort(
        key=lambda item: (
            -(
                1
                if (
                    item["comparison_count"] >= 2
                    and
                    item["repeated_differences"]
                )
                else 0
            ),
            -item[
                "comparison_count"
            ],
            -len(
                item.get(
                    "repeated_differences",
                    [],
                )
            ),
            -item.get(
                "recurrence_episode_count",
                0,
            ),
            -item[
                "max_action_time_loss_s"
            ],
            item[
                "start_distance_m"
            ]
            if item[
                "start_distance_m"
            ] is not None
            else 999999.0,
        )
    )

    for index, region in enumerate(
        regions
    ):
        region["region_label"] = (
            _alpha_label(index)
        )

    return regions
