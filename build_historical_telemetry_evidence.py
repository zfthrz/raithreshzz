"""Build read-only historical telemetry evidence from two selected laps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from historical_telemetry_evidence import (
    build_historical_interval_evidence_document,
    intervals_from_track_turns,
    intervals_from_track_zones,
)
from race_engineer_track_map import (
    TrackMapData,
    build_historical_telemetry_comparison,
    load_track_map,
    load_track_profile,
    load_track_zones,
    profile_turns,
)
from validate_historical_telemetry_evidence import validate_document


def build_artifact(
    current: TrackMapData,
    reference: TrackMapData,
    *,
    track_profiles_dir: Path,
    zones_path: Path | None = None,
) -> dict:
    if (current.track, current.layout) != (reference.track, reference.layout):
        raise ValueError("Las vueltas actual e histórica no pertenecen al mismo circuito/layout.")
    comparison = build_historical_telemetry_comparison(
        current.points,
        reference.points,
    )
    if zones_path is not None:
        intervals = intervals_from_track_zones(load_track_zones(zones_path))
        interval_basis = "h5_2_zones"
    else:
        profile = load_track_profile(
            track_profiles_dir,
            track=current.track,
            layout=current.layout,
        )
        intervals = intervals_from_track_turns(profile_turns(profile))
        interval_basis = "validated_track_profile_turns"
    if not intervals:
        raise ValueError("No hay intervalos validados disponibles para generar evidencia.")
    document = build_historical_interval_evidence_document(comparison, intervals)
    document["metadata"].update({
        "track": current.track,
        "layout": current.layout,
        "interval_basis": interval_basis,
        "current": {
            "database_path": str(current.database_path.resolve()),
            "lap": current.lap,
            "analysis_lap": current.requested_lap,
            "gps_lap": current.lap,
            "selection_reason": current.selection_reason,
            "duration_s": current.duration_s,
        },
        "historical_reference": {
            "database_path": str(reference.database_path.resolve()),
            "lap": reference.lap,
            "analysis_lap": reference.requested_lap,
            "gps_lap": reference.lap,
            "selection_reason": reference.selection_reason,
            "duration_s": reference.duration_s,
        },
    })
    errors = validate_document(document)
    if errors:
        raise ValueError("Artefacto histórico inválido: " + "; ".join(errors))
    return document


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current_database", type=Path)
    parser.add_argument("reference_database", type=Path)
    parser.add_argument("--current-lap", type=int, required=True)
    parser.add_argument("--reference-lap", type=int, required=True)
    parser.add_argument("--current-duration", type=float)
    parser.add_argument("--reference-duration", type=float)
    parser.add_argument("--track-profiles-dir", type=Path, default=Path("track_profiles"))
    parser.add_argument("--zones", type=Path)
    parser.add_argument("--target-hz", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    current = load_track_map(
        args.current_database,
        preferred_lap=args.current_lap,
        preferred_duration_s=args.current_duration,
        target_hz=args.target_hz,
    )
    reference = load_track_map(
        args.reference_database,
        preferred_lap=args.reference_lap,
        preferred_duration_s=args.reference_duration,
        target_hz=args.target_hz,
    )
    if (
        current.selection_reason == "AUTOMATIC_COMPLETE_LAP"
        or reference.selection_reason == "AUTOMATIC_COMPLETE_LAP"
    ):
        raise RuntimeError(
            "No se pudieron resolver las vueltas solicitadas por número o duración."
        )
    document = build_artifact(
        current,
        reference,
        track_profiles_dir=args.track_profiles_dir,
        zones_path=args.zones,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("RACE ENGINEER - HISTORICAL TELEMETRY EVIDENCE v0.5")
    print(f"Status: {document['metadata']['status']}")
    print(f"Intervals: {len(document['interval_evidence'])}")
    print(f"Output: {args.output.resolve()}")
    print("Authority: OBSERVATIONAL ONLY")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
