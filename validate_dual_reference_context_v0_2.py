from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA_VERSION = "1.0"
EXPECTED_DUAL_VERSION = "0.2"


def safe_float(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def safe_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida H5.1 dual-reference context.")
    ap.add_argument("dual_reference_json")
    args = ap.parse_args()

    path = Path(args.dual_reference_json)
    doc = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []

    meta = doc.get("metadata") or {}
    if meta.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        errors.append("schema_version inválida")
    if meta.get("dual_reference_version") != EXPECTED_DUAL_VERSION:
        errors.append("dual_reference_version inválida")

    analysis_path = Path(str(meta.get("source_analysis_json") or ""))
    h4_path = Path(str(meta.get("source_h4_selection_json") or ""))

    if not analysis_path.exists():
        errors.append("source_analysis_json no existe")
    elif sha256_file(analysis_path) != meta.get("source_analysis_sha256"):
        errors.append("source_analysis_sha256 mismatch")

    if not h4_path.exists():
        errors.append("source_h4_selection_json no existe")
    elif sha256_file(h4_path) != meta.get("source_h4_selection_sha256"):
        errors.append("source_h4_selection_sha256 mismatch")

    session = doc.get("session_reference")
    if not isinstance(session, dict):
        errors.append("session_reference ausente")
        session = {}
    s_lap = safe_int(session.get("lap"))
    s_time = safe_float(session.get("duration_s"))
    if s_lap is None or s_time is None or s_time <= 0:
        errors.append("session_reference inválida")
    if session.get("role") != "operational_coaching_reference":
        errors.append("session_reference role inválido")

    hist = doc.get("historical_reference")
    progress = doc.get("long_term_progress") or {}
    authority = doc.get("coaching_authority") or {}
    status = doc.get("status")

    if authority.get("active_reference") != "session_reference":
        errors.append("coaching active_reference debe seguir siendo session_reference")
    if authority.get("historical_reference_can_change_driver_cues") is not False:
        errors.append("historical reference no puede cambiar driver cues en H5.1")
    if authority.get("historical_reference_can_change_global_ABC_plan") is not False:
        errors.append("historical reference no puede cambiar ABC plan en H5.1")

    if hist is None:
        if status != "SESSION_REFERENCE_ONLY":
            errors.append("sin historical_reference, status debe ser SESSION_REFERENCE_ONLY")
        if progress.get("historical_reference_available") is not False:
            errors.append("availability histórica inconsistente")
        for k in ("current_minus_historical_s", "historical_minus_current_s", "status"):
            if progress.get(k) is not None:
                errors.append(f"sin histórico, progress.{k} debe ser null")
    else:
        if not isinstance(hist, dict):
            errors.append("historical_reference inválida")
        else:
            if status != "DUAL_REFERENCE_AVAILABLE":
                errors.append("con histórico, status debe ser DUAL_REFERENCE_AVAILABLE")
            h_session = safe_int(hist.get("session_id"))
            h_lap = safe_int(hist.get("lap"))
            h_time = safe_float(hist.get("duration_s"))
            if h_session is None or h_lap is None or h_time is None or h_time <= 0:
                errors.append("historical_reference identity/time inválida")
            if hist.get("role") != "long_term_benchmark":
                errors.append("historical_reference role inválido")
            if progress.get("historical_reference_available") is not True:
                errors.append("availability histórica inconsistente")
            delta = safe_float(progress.get("current_minus_historical_s"))
            reverse = safe_float(progress.get("historical_minus_current_s"))
            if s_time is not None and h_time is not None:
                expected = s_time - h_time
                if delta is None or abs(delta - expected) > 1e-9:
                    errors.append("current_minus_historical_s incorrecto")
                if reverse is None or abs(reverse + expected) > 1e-9:
                    errors.append("historical_minus_current_s incorrecto")

    print("=" * 88)
    print("RACE ENGINEER - H5.1 DUAL REFERENCE VALIDATION v0.2")
    print("=" * 88)
    print(f"Status:       {status}")
    print(f"Historical:   {'YES' if hist is not None else 'NO'}")
    print(f"Errors:       {len(errors)}")
    for e in errors:
        print(f"  - {e}")

    if errors:
        print("RESULT: FAIL")
        return 2
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
