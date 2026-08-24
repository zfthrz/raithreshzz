from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


AUDIT_VERSION = "0.1"
AUDIT_STATUS = "SHADOW_OBSERVATIONAL_ONLY"

STALE_RENDER_ERROR = (
    "global_analysis no coincide exactamente con el renderizador determinista de Python."
)


def sha256_file(path: Path) -> str:
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


def _validator_error_lines(output: str) -> list[str]:
    return [
        line[2:].strip()
        for line in str(output or "").splitlines()
        if line.startswith("- ")
    ]


def validate_artifact(
    path: Path, *, allow_stale_render_only: bool = False
) -> str:
    validator = Path(__file__).with_name("validate_llm_analysis_output.py")
    completed = subprocess.run(
        [sys.executable, str(validator), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode == 0:
        return "PASS"
    detail = (completed.stdout or completed.stderr).strip()
    errors = _validator_error_lines(detail)
    if allow_stale_render_only and errors == [STALE_RENDER_ERROR]:
        return "STALE_RENDER_ONLY"
    raise ValueError(f"{path}: validator LLM FAIL\n{detail}")


def _profile_steps(cue: dict[str, Any]) -> int:
    profile = cue.get("reference_action_profile")
    if not isinstance(profile, dict):
        return 0
    steps = profile.get("steps") or []
    return len([step for step in steps if isinstance(step, dict)])


def _physical_point_count(item: dict[str, Any], channel: str) -> int:
    fields = {
        "brake": ("braking_point_patterns", "brake_release_patterns"),
        "throttle": ("throttle_onset_patterns", "throttle_release_patterns"),
    }.get(channel, ())
    return sum(
        1
        for field in fields
        for pattern in (item.get(field, []) or [])
        if isinstance(pattern, dict)
    )


def classify_cue(item: dict[str, Any], cue: dict[str, Any]) -> dict[str, Any]:
    channel = str(cue.get("channel") or "unknown")
    kind = str(cue.get("kind") or "unknown")
    point_count = _physical_point_count(item, channel)
    profile_step_count = _profile_steps(cue)
    sequence = cue.get("coaching_sequence") or {}
    sequence_event_count = len(
        [
            event
            for event in (sequence.get("events") or [])
            if isinstance(event, dict)
        ]
    )
    qualitative_channel_count = len(
        [value for value in (cue.get("channels") or []) if value]
    )

    if kind == "spatial_points" and profile_step_count:
        directness_class = "physical_point_with_reference_sequence"
    elif kind == "spatial_points" and point_count == 1:
        directness_class = "single_physical_point"
    elif kind == "spatial_points" and point_count > 1:
        directness_class = "multiple_physical_points"
    elif kind == "reference_action_profile":
        directness_class = "reference_sequence_only"
    elif kind == "qualitative_reference_level":
        directness_class = "qualitative_alignment"
    elif kind == "validated_llm_steering":
        directness_class = "validated_steering"
    elif kind == "combined_spatial_sequence":
        directness_class = "combined_spatial_sequence"
    else:
        directness_class = "other"

    component_count = point_count + profile_step_count
    if kind == "qualitative_reference_level":
        component_count = max(1, qualitative_channel_count)
    elif kind == "combined_spatial_sequence":
        component_count = max(1, sequence_event_count)
    elif component_count == 0:
        component_count = 1

    return {
        "channel": channel,
        "kind": kind,
        "directness_class": directness_class,
        "physical_point_count": point_count,
        "reference_profile_step_count": profile_step_count,
        "sequence_event_count": sequence_event_count,
        "instruction_component_count": component_count,
        "point_comparison_count": cue.get("point_comparison_count"),
        "region_comparison_count": cue.get("region_comparison_count"),
        "source": cue.get("source"),
    }


def audit_document(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    facts = document.get("session_coaching_facts")
    if not isinstance(facts, dict):
        raise ValueError(f"{path}: session_coaching_facts ausente")
    plan = facts.get("next_stint_plan")
    if not isinstance(plan, list):
        raise ValueError(f"{path}: next_stint_plan ausente o inválido")
    policy = facts.get("session_priority_policy") or {}
    if not policy.get("version"):
        raise ValueError(f"{path}: session_priority_policy.version ausente")

    zones: list[dict[str, Any]] = []
    for position, item in enumerate(plan, 1):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: next_stint_plan[{position - 1}] inválido")
        cues = item.get("driver_cues") or []
        if not isinstance(cues, list) or not cues:
            raise ValueError(f"{path}: zona {position} sin driver_cues")
        if item.get("actionable_cue_count") != len(cues):
            raise ValueError(
                f"{path}: zona {position} actionable_cue_count no coincide"
            )
        cue_audits = [
            classify_cue(item, cue)
            for cue in cues
            if isinstance(cue, dict)
        ]
        if len(cue_audits) != len(cues):
            raise ValueError(f"{path}: zona {position} contiene un cue inválido")
        location = item.get("track_location") or {}
        zones.append(
            {
                "position": position,
                "plan_label": item.get("plan_label"),
                "location": location.get("label"),
                "region_comparison_count": item.get("comparison_count"),
                "primary_cue": cue_audits[0],
                "secondary_cues": cue_audits[1:],
                "cue_count": len(cue_audits),
            }
        )

    metadata = document.get("metadata") or {}
    return {
        "source_path": str(path.resolve()),
        "source_sha256": sha256_file(path),
        "track": metadata.get("track") or facts.get("track"),
        "session_priority_policy_version": policy.get("version"),
        "actionability_policy_version": policy.get(
            "actionability_policy_version"
        ),
        "zone_count": len(zones),
        "zones": zones,
    }


def build_audit(results: list[dict[str, Any]]) -> dict[str, Any]:
    channel_counts: Counter[str] = Counter()
    directness_counts: Counter[str] = Counter()
    for result in results:
        for zone in result["zones"]:
            primary = zone["primary_cue"]
            channel_counts[primary["channel"]] += 1
            directness_counts[primary["directness_class"]] += 1

    return {
        "metadata": {
            "audit_version": AUDIT_VERSION,
            "status": AUDIT_STATUS,
        },
        "contract": {
            "production_priority_changed": False,
            "channel_preference_authorized": False,
            "complexity_score_authorized": False,
            "coaching_authority_changed": False,
            "purpose": "measure_cue_structure_without_changing_priority",
        },
        "summary": {
            "artifact_count": len(results),
            "zone_count": sum(result["zone_count"] for result in results),
            "primary_channel_counts": dict(sorted(channel_counts.items())),
            "primary_directness_counts": dict(sorted(directness_counts.items())),
        },
        "artifacts": results,
    }


def audit_paths(
    paths: list[Path],
    *,
    run_validator: bool = True,
    allow_stale_render_only: bool = False,
) -> dict[str, Any]:
    results = []
    for path in paths:
        validation_status = "NOT_RUN"
        if run_validator:
            validation_status = validate_artifact(
                path,
                allow_stale_render_only=allow_stale_render_only,
            )
        result = audit_document(path, load_json(path))
        result["input_validation_status"] = validation_status
        results.append(result)
    return build_audit(results)


def print_summary(audit: dict[str, Any]) -> None:
    summary = audit["summary"]
    print("=" * 88)
    print("RACE ENGINEER - SESSION PLAN ACTIONABILITY SHADOW AUDIT v0.1")
    print("=" * 88)
    print(f"Artifacts: {summary['artifact_count']}")
    print(f"Priority zones: {summary['zone_count']}")
    print("Primary channels:")
    for channel, count in summary["primary_channel_counts"].items():
        print(f"  {channel}: {count}")
    print("Primary directness classes:")
    for directness, count in summary["primary_directness_counts"].items():
        print(f"  {directness}: {count}")
    print("Authority: SHADOW ONLY — no channel preference or priority changed")
    print("RESULT: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita en shadow la estructura de cues del plan de sesión"
    )
    parser.add_argument("llm_analysis_json", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-stale-render-only",
        action="store_true",
        help="Acepta exclusivamente deriva del render global en artifacts históricos",
    )
    args = parser.parse_args()
    try:
        audit = audit_paths(
            args.llm_analysis_json,
            allow_stale_render_only=args.allow_stale_render_only,
        )
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
