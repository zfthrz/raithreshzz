#!/usr/bin/env python3
"""Golden-set semantic regression for Race Engineer debriefs (Phase J).

NO compara prosa exacta. Compara expectativas semánticas deterministas:
- región esperada (etiquetas de curva T-n en el plan);
- familias de acción esperadas (canales de driver_cues);
- estructura P10/P11 (foco <= 2 items, subset del plan);
- acciones prohibidas (speed/time como acción);
- evidencia autorizada (sources conocidos).

El golden set v0.1 es un SEED derivado de debriefs ya validados; no autoriza
cambios de ranking ni de producción.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GOLDEN_VERSION = "0.1"
FORBIDDEN_CUE_TOKENS = ("velocidad", "segundo", "km/h", "tiempo de vuelta")
AUTHORIZED_SOURCES = (
    "authorized_brake_onset_release",
    "authorized_throttle_onset_release",
    "deterministic_observed_level_to_reference",
    "reference_action_profile",
    "deterministic_coaching_sequence",
    "deterministic_coaching_sequence_shadow_split",
    "validated_llm_recommendation+python_direction",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: la raíz JSON debe ser un objeto")
    return payload


def _plan_labels(plan: list[dict]) -> set[str]:
    labels: set[str] = set()
    for item in plan:
        if not isinstance(item, dict):
            continue
        location = item.get("track_location")
        label = ""
        if isinstance(location, dict):
            label = str(location.get("label") or "")
        if not label:
            label = str(item.get("location_label") or "")
        if label:
            labels.add(label)
    return labels


def _turns(label: str) -> set[str]:
    return set(re.findall(r"T\d+", label))


def _cue_families(plan: list[dict]) -> set[str]:
    families: set[str] = set()
    for item in plan:
        for cue in item.get("driver_cues") or []:
            if not isinstance(cue, dict):
                continue
            channel = str(cue.get("channel") or "")
            if "brake" in channel:
                families.add("brake")
            if "throttle" in channel:
                families.add("throttle")
            if "steering" in channel:
                families.add("steering")
    return families


def _cue_sources(plan: list[dict]) -> set[str]:
    sources: set[str] = set()
    for item in plan:
        for cue in item.get("driver_cues") or []:
            if isinstance(cue, dict) and cue.get("source"):
                sources.add(str(cue["source"]))
    return sources


def _forbidden_hits(plan: list[dict]) -> list[str]:
    hits: list[str] = []
    for item in plan:
        for cue in item.get("driver_cues") or []:
            if not isinstance(cue, dict):
                continue
            text = str(cue.get("text") or "").lower()
            for token in FORBIDDEN_CUE_TOKENS:
                if token in text:
                    hits.append(f"{item.get('plan_label')}:{token}")
    return hits


def build_golden_record(
    session_key: str,
    track: str,
    variant: str,
    debrief: dict[str, Any],
) -> dict[str, Any]:
    facts = debrief.get("session_coaching_facts") or {}
    plan = facts.get("next_stint_plan") or []
    focus = facts.get("next_stint_focus") or {}
    labels = sorted(_plan_labels(plan))
    return {
        "golden_id": f"{session_key[:42]}",
        "track": track,
        "vehicle_variant": variant,
        "session_key": session_key,
        "status": "SEED",
        "derived_from": f"debrief {utc_now_iso()}",
        "expected_regions": labels,
        "expected_action_families": sorted(_cue_families(plan)),
        "expected_cue_sources": sorted(_cue_sources(plan)),
        "expected_p11": {
            "status": str(focus.get("status") or "INACTIVE"),
            "max_items": 2,
        },
        "forbidden_cue_tokens": list(FORBIDDEN_CUE_TOKENS),
        "usefulness_score": None,
        "notes": "Seed derivado de un debrief validado; refinar con revisión humana.",
    }


def evaluate_record(record: dict[str, Any], debrief: dict[str, Any]) -> dict[str, Any]:
    facts = debrief.get("session_coaching_facts") or {}
    plan = facts.get("next_stint_plan") or []
    focus = facts.get("next_stint_focus") or {}
    plan_labels = _plan_labels(plan)
    plan_turns = set().union(*(_turns(label) for label in plan_labels)) if plan_labels else set()

    checks: dict[str, Any] = {}

    expected_turns = set().union(
        *(_turns(label) for label in (record.get("expected_regions") or []))
    ) if record.get("expected_regions") else set()
    checks["region_coverage"] = bool(expected_turns and expected_turns <= plan_turns)

    families = _cue_families(plan)
    expected_families = set(record.get("expected_action_families") or [])
    checks["action_families_present"] = bool(
        expected_families and expected_families <= families
    )

    forbidden = _forbidden_hits(plan)
    checks["no_forbidden_actions"] = not forbidden
    if forbidden:
        checks["forbidden_hits"] = forbidden

    sources = _cue_sources(plan)
    unauthorized = sorted(sources - set(AUTHORIZED_SOURCES))
    checks["evidence_authorized"] = not unauthorized
    if unauthorized:
        checks["unauthorized_sources"] = unauthorized

    p11_status = str(focus.get("status") or "INACTIVE")
    focus_items = focus.get("items") or []
    expected_p11 = record.get("expected_p11") or {}
    checks["p11_status"] = p11_status == expected_p11.get("status")
    checks["p11_max_items"] = len(focus_items) <= int(expected_p11.get("max_items", 2))
    focus_labels = {
        str(item.get("plan_label")) for item in focus_items if isinstance(item, dict)
    }
    plan_labels_set = {
        str(item.get("plan_label")) for item in plan if isinstance(item, dict)
    }
    checks["p11_subset_of_plan"] = bool(focus_labels <= plan_labels_set)

    return {
        "golden_id": record.get("golden_id"),
        "pass": all(checks.values()),
        "checks": checks,
        "usefulness_score": record.get("usefulness_score"),
    }


def evaluate_set(
    golden_path: Path,
    debrief_root: Path,
) -> dict[str, Any]:
    golden = load_json(golden_path)
    records = golden.get("records") or []
    results: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for record in records:
        session_key = str(record.get("session_key") or "")
        debrief_path = _resolve_debrief(debrief_root, session_key)
        if debrief_path is None:
            unavailable.append(session_key)
            continue
        try:
            debrief = load_json(debrief_path)
        except (OSError, ValueError, json.JSONDecodeError):
            unavailable.append(session_key)
            continue
        result = evaluate_record(record, debrief)
        result["debrief_path"] = str(debrief_path)
        results.append(result)
    passed = sum(1 for r in results if r["pass"])
    return {
        "golden_version": golden.get("version"),
        "record_count": len(records),
        "evaluated": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "unavailable": unavailable,
        "results": results,
    }


def _resolve_debrief(debrief_root: Path, session_key: str) -> Path | None:
    run_state = debrief_root / "runs" / session_key / "state.json"
    if run_state.is_file():
        try:
            state = load_json(run_state)
            output = str((state.get("stages") or {}).get("llm", {}).get("output") or "")
            if output and Path(output).is_file():
                return Path(output)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    candidates = sorted((debrief_root / "llm_results" / session_key).glob("*.json"))
    return candidates[0] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Golden-set semantic regression (Phase J)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Construir golden set seed desde debriefs.")
    build.add_argument("--sessions", nargs="+", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--debrief-root", default="data/generated")

    evaluate = sub.add_parser("evaluate", help="Evaluar debriefs contra golden set.")
    evaluate.add_argument("golden_json")
    evaluate.add_argument("--debrief-root", default="data/generated")
    args = parser.parse_args()

    if args.command == "build":
        root = Path(args.debrief_root)
        records = []
        for session_key in args.sessions:
            debrief_path = _resolve_debrief(root, session_key)
            if debrief_path is None:
                print(f"WARN: sin debrief para {session_key}")
                continue
            debrief = load_json(debrief_path)
            metadata = (debrief.get("metadata") or {})
            identity = metadata.get("vehicle_identity") or {}
            record = build_golden_record(
                session_key,
                str(metadata.get("track") or "UNKNOWN"),
                str(
                    metadata.get("vehicle_variant")
                    or identity.get("variant")
                    or "UNKNOWN"
                ),
                debrief,
            )
            records.append(record)
        payload = {
            "version": GOLDEN_VERSION,
            "generated_at_utc": utc_now_iso(),
            "policy": {
                "semantic_not_prose": True,
                "no_ranking_change_authorized": True,
                "human_review_required_before_promotion": True,
            },
            "records": records,
        }
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Golden set escrito: {output} ({len(records)} records)")
        return 0

    result = evaluate_set(Path(args.golden_json), Path(args.debrief_root))
    print("=" * 88)
    print(f"GOLDEN SET SEMANTIC REGRESSION v{GOLDEN_VERSION}")
    print("=" * 88)
    print(
        f"Records: {result['record_count']} · Evaluados: {result['evaluated']} · "
        f"PASS: {result['passed']} · FAIL: {result['failed']}"
    )
    if result["unavailable"]:
        print("Sin debrief:", result["unavailable"])
    for item in result["results"]:
        print(f"  {item['golden_id'][:48]:48} {'PASS' if item['pass'] else 'FAIL'}")
    print("RESULT:", "PASS" if result["failed"] == 0 else "FAIL")
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
