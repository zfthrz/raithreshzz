"""Deterministic track-location helpers for session coaching."""

from deterministic_coaching import safe_float

def resolve_track_location(
    context,
    start_distance_m,
    end_distance_m,
):
    if (
        not isinstance(
            context,
            dict,
        )
        or
        context.get("status")
        !=
        "ACTIVE"
    ):
        return None

    start_m = safe_float(
        start_distance_m
    )

    end_m = safe_float(
        end_distance_m
    )

    if (
        start_m is None
        or
        end_m is None
    ):
        return None

    resolver = context.get(
        "resolver"
    )

    profile = context.get(
        "profile"
    )

    if (
        not callable(
            resolver
        )
        or
        not isinstance(
            profile,
            dict,
        )
    ):
        return None

    try:
        result = resolver(
            profile,
            start_m,
            end_m,
        )
    except Exception as exc:
        return {
            "status": "RESOLUTION_ERROR",
            "error": str(exc),
            "start_m": start_m,
            "end_m": end_m,
        }

    if not isinstance(
        result,
        dict,
    ):
        return None

    return {
        **result,
        "status": "RESOLVED",
    }

def track_location_label(
    item,
):
    if not isinstance(
        item,
        dict,
    ):
        return None

    location = item.get(
        "track_location"
    )

    if not isinstance(
        location,
        dict,
    ):
        return None

    if (
        location.get("status")
        !=
        "RESOLVED"
    ):
        return None

    label = location.get(
        "label"
    )

    if not isinstance(
        label,
        str,
    ):
        return None

    label = label.strip()

    return (
        label
        if label
        else None
    )

def track_location_context_summary(
    context,
):
    if not isinstance(
        context,
        dict,
    ):
        return {
            "status": "UNAVAILABLE",
        }

    return {
        "status":
            context.get(
                "status"
            ),
        "track":
            context.get(
                "track"
            ),
        "profile_id":
            context.get(
                "profile_id"
            ),
        "profile_status":
            context.get(
                "profile_status"
            ),
        "profile_path":
            context.get(
                "profile_path"
            ),
        "numbering_scheme":
            context.get(
                "numbering_scheme"
            ),
    }

def enrich_items_with_track_location(
    items,
    context,
):
    if not isinstance(
        items,
        list,
    ):
        return items

    for item in items:
        if not isinstance(
            item,
            dict,
        ):
            continue

        start_m = safe_float(
            item.get(
                "start_distance_m"
            )
        )
        end_m = safe_float(
            item.get(
                "end_distance_m"
            )
        )

        # Los patrones puntuales repetidos pueden no pertenecer todavía a una
        # priority_region. En ese caso conservan la coordenada física de la
        # referencia (onset/release), pero no un intervalo start/end. Resolver
        # un micro-intervalo alrededor de ese punto permite nombrar la curva
        # sin inventar una región de coaching ni alterar las distancias fuente.
        if (
            start_m is None
            or
            end_m is None
        ):
            point_m = None

            for field in (
                "reference_onset_m",
                "reference_release_m",
            ):
                point_m = safe_float(
                    item.get(field)
                )
                if point_m is not None:
                    break

            if point_m is not None:
                start_m = point_m - 10.0
                end_m = point_m + 10.0

        item["track_location"] = (
            resolve_track_location(
                context,
                start_m,
                end_m,
            )
        )

    return items
