from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ASSESS_VERSION = "0.1"
SCHEMA_VERSION = "1.0"

VERDICT_NOT_AUTHORIZED = "PROMOTION_NOT_AUTHORIZED"
VERDICT_READY = "PROMOTION_READY"

REQUIRED_TRACKS = {
    "Fuji Speedway",
    "Autodromo Enzo e Dino Ferrari",
    "Autódromo José Carlos Pace",
    "Autodromo Nazionale Monza",
}
REQUIRED_SIGNS = {"current_slower", "current_faster"}

REQUIRED_FLAGS = (
    "raw_telemetry_resolved",
    "track_profile_localized",
    "h4_compatible",
    "h5_2_validated",
    "h5_3a_candidates_available",
    "h5_3b_labels_validated",
    "h5_3c_selection_validated",
    "h5_3d_render_validated",
    "h5_3e_validation_pass",
)
SCENARIOS = {
    "unavailable_raw_telemetry": "raw_telemetry_resolved",
    "missing_or_invalid_track_profile": "track_profile_localized",
    "incompatible_context_rejected": "h4_compatible",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("contexts"), list):
        raise ValueError("Manifest inválido: se espera metadata + contexts.")
    return payload


def _flags_ok(context: dict[str, Any], missing: list[str]) -> bool:
    ok = True
    for flag in REQUIRED_FLAGS:
        if context.get(flag) is not True:
            missing.append(flag)
            ok = False
    if context.get("human_review_documented") is not True:
        missing.append("human_review_documented")
        ok = False
    return ok


def assess(manifest_path: Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    manifest = _load_manifest(manifest_path)
    contexts = manifest["contexts"]

    normal: list[dict[str, Any]] = []
    scenario_flags: dict[str, bool] = {name: False for name in SCENARIOS}
    unmet: list[str] = []
    unsafe_authority = False

    for index, context in enumerate(contexts):
        if not isinstance(context, dict):
            raise ValueError(f"contexts[{index}] no es objeto")
        if context.get("historical_actions_authorized") is not False:
            unsafe_authority = True
            unmet.append(
                f"contexts[{index}] autoriza acciones históricas; no permitido"
            )
        scenario = context.get("scenario")
        if scenario is None:
            normal.append(context)
            continue
        if scenario not in SCENARIOS:
            raise ValueError(f"contexts[{index}] scenario desconocido: {scenario!r}")
        flag = SCENARIOS[scenario]
        if context.get(flag) is False:
            scenario_flags[scenario] = True
        else:
            unmet.append(f"contexts[{index}] no registra {scenario}")

    covered_tracks = {
        str(context.get("track"))
        for context in normal
        if context.get("track")
    }
    covered_signs = {
        str(context.get("delta_sign"))
        for context in normal
        if context.get("delta_sign")
    }
    missing_tracks = sorted(REQUIRED_TRACKS - covered_tracks)
    missing_signs = sorted(REQUIRED_SIGNS - covered_signs)

    all_normal_ok = True
    for context in normal:
        track = context.get("track")
        missing: list[str] = []
        ok = _flags_ok(context, missing)
        if not ok:
            all_normal_ok = False
            unmet.append(f"{track}: faltan {', '.join(missing)}")
        if context.get("delta_sign") not in REQUIRED_SIGNS:
            unmet.append(f"{track}: delta_sign inválido o ausente")

    if missing_tracks:
        unmet.append("faltan contextos requeridos: " + ", ".join(missing_tracks))
    if missing_signs:
        unmet.append("faltan signos de delta: " + ", ".join(missing_signs))
    for scenario, present in scenario_flags.items():
        if not present:
            unmet.append(f"falta escenario registrado: {scenario}")
    if not all_normal_ok:
        unmet.append("no todos los contextos requeridos están completamente validados")
    if unsafe_authority:
        unmet.append("cambio no autorizado de autoridad detectado")

    verdict = VERDICT_READY if not unmet else VERDICT_NOT_AUTHORIZED
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "assess_version": ASSESS_VERSION,
            "source_manifest_json": str(manifest_path),
            "source_manifest_sha256": sha256_file(manifest_path),
        },
        "verdict": verdict,
        "requirements": {
            "required_tracks_covered": not missing_tracks,
            "both_delta_signs_covered": not missing_signs,
            "all_contexts_fully_validated": all_normal_ok,
            "special_cases_present": {
                scenario: present for scenario, present in scenario_flags.items()
            },
            "human_review_documented": all(
                context.get("human_review_documented") is True
                for context in normal
            ),
            "zero_unsafe_authority_changes": not unsafe_authority,
        },
        "coverage": {
            "tracks_covered": sorted(covered_tracks),
            "missing_tracks": missing_tracks,
            "delta_signs_covered": sorted(covered_signs),
            "missing_delta_signs": missing_signs,
            "context_count": len(normal),
        },
        "unmet": sorted(set(unmet)),
        "authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3f: gate multitrack de promoción del debrief histórico."
    )
    parser.add_argument("manifest_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = assess(Path(args.manifest_json))
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 88)
    print(f"RACE ENGINEER - H5.3f MULTITRACK PROMOTION GATE v{ASSESS_VERSION}")
    print("=" * 88)
    print(f"Verdict: {report['verdict']}")
    print(f"Tracks: {report['coverage']['tracks_covered']}")
    print(f"Missing tracks: {report['coverage']['missing_tracks']}")
    print(f"Missing signs: {report['coverage']['missing_delta_signs']}")
    print(f"Unmet requirements: {len(report['unmet'])}")
    for item in report["unmet"]:
        print(f"  - {item}")
    print(f"Output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
