from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from validate_cross_session_comparison import validate as validate_raw_h5_2
from validate_historical_llm_analysis import validate as validate_historical_llm


AUDIT_VERSION = "0.1"
AUDIT_STATUS = "SHADOW_OBSERVATIONAL_ONLY"


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: la raíz JSON debe ser un objeto")
    return document


def _rank(
    rows: list[dict[str, Any]],
    *,
    key: str,
    secondary: str,
) -> dict[str, int]:
    ordered = sorted(
        rows,
        key=lambda row: (
            -float(row[key]),
            -float(row[secondary]),
            row["zone_id"],
        ),
    )
    return {row["zone_id"]: index for index, row in enumerate(ordered, 1)}


def build_zone_metrics(source: dict[str, Any]) -> list[dict[str, Any]]:
    zones = source["spatial_comparison"]["zone_summaries"]
    rows: list[dict[str, Any]] = []
    for index, zone in enumerate(zones, 1):
        start_m = float(zone["start_distance"])
        end_m = float(zone["end_distance"])
        span_m = float(zone.get("distance", end_m - start_m))
        if span_m <= 0:
            raise ValueError(f"zone_{index:03d}: distancia no positiva")
        delta_change_s = float(zone["delta_change"])
        abs_delta_s = abs(delta_change_s)
        location = zone.get("location") or {}
        rows.append(
            {
                "zone_id": f"zone_{index:03d}",
                "label": location.get("label") or f"{start_m:.1f}-{end_m:.1f} m",
                "location_type": location.get("location_type") or "unlocalized",
                "start_m": start_m,
                "end_m": end_m,
                "span_m": span_m,
                "delta_change_s": delta_change_s,
                "abs_delta_change_s": abs_delta_s,
                "abs_delta_per_100m_s": abs_delta_s * 100.0 / span_m,
            }
        )

    impact_ranks = _rank(
        rows,
        key="abs_delta_change_s",
        secondary="abs_delta_per_100m_s",
    )
    intensity_ranks = _rank(
        rows,
        key="abs_delta_per_100m_s",
        secondary="abs_delta_change_s",
    )
    corner_rows = [row for row in rows if row["location_type"] == "corner"]
    corner_ranks = _rank(
        corner_rows,
        key="abs_delta_change_s",
        secondary="abs_delta_per_100m_s",
    )
    for row in rows:
        zone_id = row["zone_id"]
        row["impact_rank"] = impact_ranks[zone_id]
        row["intensity_rank"] = intensity_ranks[zone_id]
        row["corner_impact_rank"] = corner_ranks.get(zone_id)
    return rows


def build_audit(
    source_path: Path,
    source: dict[str, Any],
    selections: list[tuple[Path, dict[str, Any]]],
) -> dict[str, Any]:
    source_sha256 = sha256_file(source_path)
    zone_metrics = build_zone_metrics(source)
    by_id = {row["zone_id"]: row for row in zone_metrics}
    top_count = min(3, len(zone_metrics))
    top_impact = {
        row["zone_id"]
        for row in sorted(zone_metrics, key=lambda row: row["impact_rank"])[
            :top_count
        ]
    }
    top_intensity = {
        row["zone_id"]
        for row in sorted(zone_metrics, key=lambda row: row["intensity_rank"])[
            :top_count
        ]
    }

    model_selections: list[dict[str, Any]] = []
    for selection_path, document in selections:
        metadata = document["metadata"]
        if metadata.get("source_h5_2_sha256") != source_sha256:
            raise ValueError(
                f"{selection_path}: no referencia el H5.2 suministrado"
            )
        selected = document["llm_selection"]["selected_zones"]
        selected_ids = [item["zone_id"] for item in selected]
        selected_metrics = []
        for position, item in enumerate(selected, 1):
            metric = by_id[item["zone_id"]]
            selected_metrics.append(
                {
                    "position": position,
                    "zone_id": item["zone_id"],
                    "significance": item["significance"],
                    "impact_rank": metric["impact_rank"],
                    "intensity_rank": metric["intensity_rank"],
                    "corner_impact_rank": metric["corner_impact_rank"],
                    "location_type": metric["location_type"],
                    "abs_delta_change_s": metric["abs_delta_change_s"],
                    "abs_delta_per_100m_s": metric["abs_delta_per_100m_s"],
                }
            )
        model_selections.append(
            {
                "selection_path": str(selection_path.resolve()),
                "backend": metadata.get("backend"),
                "model": metadata.get("model"),
                "selected_zone_ids": selected_ids,
                "selected_zone_metrics": selected_metrics,
                "top_3_impact_overlap": len(set(selected_ids) & top_impact),
                "top_3_intensity_overlap": len(set(selected_ids) & top_intensity),
                "selected_corner_count": sum(
                    by_id[zone_id]["location_type"] == "corner"
                    for zone_id in selected_ids
                ),
            }
        )

    return {
        "metadata": {
            "audit_version": AUDIT_VERSION,
            "status": AUDIT_STATUS,
            "source_h5_2_json": str(source_path.resolve()),
            "source_h5_2_sha256": source_sha256,
        },
        "contract": {
            "production_selection_changed": False,
            "coaching_authority_changed": False,
            "ranking_formula_authorized": False,
            "purpose": "compare_selection_behavior_without_authorizing_coaching",
        },
        "context": source.get("context"),
        "localization": source["spatial_comparison"].get("localization"),
        "zone_metrics": zone_metrics,
        "model_selections": model_selections,
    }


def audit_paths(
    source_path: Path,
    selection_paths: list[Path],
) -> dict[str, Any]:
    source = load_json(source_path)
    raw_errors = validate_raw_h5_2(source)
    if raw_errors:
        raise ValueError("H5.2 fuente inválido: " + "; ".join(raw_errors))

    selections: list[tuple[Path, dict[str, Any]]] = []
    for path in selection_paths:
        document = load_json(path)
        errors = validate_historical_llm(document)
        if errors:
            raise ValueError(f"{path}: " + "; ".join(errors))
        selections.append((path, document))
    return build_audit(source_path, source, selections)


def print_summary(audit: dict[str, Any]) -> None:
    print("=" * 88)
    print("RACE ENGINEER - H5.2 ZONE SELECTION SHADOW AUDIT v0.1")
    print("=" * 88)
    print(f"Zones: {len(audit['zone_metrics'])}")
    for selection in audit["model_selections"]:
        selected = ", ".join(selection["selected_zone_ids"])
        print(
            f"{selection['backend']} / {selection['model']}: {selected} | "
            f"impact top3={selection['top_3_impact_overlap']}/3 | "
            f"intensity top3={selection['top_3_intensity_overlap']}/3 | "
            f"corners={selection['selected_corner_count']}"
        )
    print("Authority: SHADOW ONLY — no production ranking or coaching changed")
    print("RESULT: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita en shadow la selección de zonas H5.2 entre modelos"
    )
    parser.add_argument("comparison_json", type=Path)
    parser.add_argument("historical_llm_json", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        audit = audit_paths(args.comparison_json, args.historical_llm_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RESULT: FAIL — {exc}")
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Output: {args.output.resolve()}")
    print_summary(audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
