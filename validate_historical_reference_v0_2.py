from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def safe_float(v: Any) -> float | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida salida H4 historical reference selector v0.2.")
    ap.add_argument("selection_json")
    args = ap.parse_args()

    doc = json.loads(Path(args.selection_json).read_text(encoding="utf-8"))
    errors: list[str] = []
    metadata = doc.get("metadata") or {}
    target = doc.get("target_session") or {}
    candidates = doc.get("candidates")
    selected = doc.get("selected_historical_reference")
    status = doc.get("selection_status")

    if metadata.get("selector_version") != "0.2":
        errors.append("selector_version != 0.2")
    if metadata.get("history_schema_version") != 4:
        errors.append("history_schema_version != 4")
    if not isinstance(candidates, list):
        errors.append("candidates no es lista")
        candidates = []

    target_id = target.get("session_id")
    eligible = []
    rejected = []
    seen_sessions = set()
    for i, c in enumerate(candidates):
        sid = c.get("session_id")
        if sid in seen_sessions:
            errors.append(f"candidate session duplicada: {sid}")
        seen_sessions.add(sid)
        if sid == target_id:
            errors.append("target session aparece como candidate")
        e = c.get("eligibility")
        reasons = c.get("rejection_reasons")
        if not isinstance(reasons, list):
            errors.append(f"candidate[{i}] rejection_reasons inválido")
            reasons = []
        obs = c.get("compatibility_observations") or {}
        target_wc = obs.get("target_weather_class")
        cand_wc = obs.get("candidate_weather_class")
        weather_relation = obs.get("weather_compatibility")

        if e == "ELIGIBLE":
            eligible.append(c)
            if reasons:
                errors.append(f"eligible session {sid} tiene rejection_reasons")
            if target_wc == "DRY" and cand_wc != "DRY":
                errors.append(f"eligible session {sid}: target DRY pero candidate weather_class={cand_wc!r}")
            if target_wc == "WET" and weather_relation != "WET_EXACT_RAW_COMPATIBLE":
                errors.append(f"eligible session {sid}: WET sin exact-raw compatibility")
            d = safe_float(c.get("reference_lap_duration_s"))
            if d is None or d <= 0:
                errors.append(f"eligible session {sid} duration inválida")
        elif e == "REJECTED":
            rejected.append(c)
            if not reasons:
                errors.append(f"rejected session {sid} sin reason")
        else:
            errors.append(f"candidate[{i}] eligibility inválida: {e!r}")

    summary = doc.get("candidate_summary") or {}
    if summary.get("candidate_sessions_considered") != len(candidates):
        errors.append("candidate_summary considered mismatch")
    if summary.get("eligible") != len(eligible):
        errors.append("candidate_summary eligible mismatch")
    if summary.get("rejected") != len(rejected):
        errors.append("candidate_summary rejected mismatch")

    eligible_sorted = sorted(
        eligible,
        key=lambda c: (
            safe_float(c.get("reference_lap_duration_s")) if safe_float(c.get("reference_lap_duration_s")) is not None else float("inf"),
            c.get("timestamp_utc") or "",
            c.get("session_id") or 0,
        ),
    )

    if eligible_sorted:
        if status != "HISTORICAL_REFERENCE_SELECTED":
            errors.append("hay eligible pero status no selecciona reference")
        if not isinstance(selected, dict):
            errors.append("hay eligible pero selected_historical_reference ausente")
        else:
            best = eligible_sorted[0]
            if selected.get("session_id") != best.get("session_id"):
                errors.append("selected session no es fastest eligible")
            if selected.get("lap") != best.get("reference_lap"):
                errors.append("selected lap no coincide con candidate reference_lap")
            if safe_float(selected.get("duration_s")) != safe_float(best.get("reference_lap_duration_s")):
                errors.append("selected duration no coincide con best eligible")
    else:
        if status != "NO_COMPATIBLE_HISTORICAL_REFERENCE":
            errors.append("no hay eligible pero status incorrecto")
        if selected is not None:
            errors.append("no hay eligible pero selected no es null")

    print("=" * 84)
    print("RACE ENGINEER - H4 HISTORICAL REFERENCE VALIDATION v0.2")
    print("=" * 84)
    print(f"Candidates: {len(candidates)}")
    print(f"Eligible:   {len(eligible)}")
    print(f"Rejected:   {len(rejected)}")
    print(f"Status:     {status}")
    if isinstance(selected, dict):
        print(f"Selected:   session={selected.get('session_id')} lap={selected.get('lap')} duration={selected.get('duration_s')}")
    print(f"Errors:     {len(errors)}")
    for e in errors:
        print(f"  - {e}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
