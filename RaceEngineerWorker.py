"""Closed deterministic worker for the packaged public pipeline."""

from __future__ import annotations

import runpy
import sys


PUBLIC_WORKER_MODULES = frozenset(
    {
        "analyze_telemetry",
        "build_cross_session_comparison",
        "build_dual_reference_context",
        "build_historical_coaching_candidates",
        "build_historical_telemetry_evidence",
        "deterministic_debrief",
        "render_historical_debrief",
        "select_historical_reference",
        "select_session_persistent_patterns",
        "session_history",
        "validate_cross_session_comparison",
        "validate_historical_debrief",
        "validate_historical_telemetry_evidence",
        "validate_llm_analysis_output",
    }
)


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if not values:
        print("Usage: RaceEngineerWorker.exe MODULE [ARGS...]", file=sys.stderr)
        return 2
    module = values.pop(0)
    if module not in PUBLIC_WORKER_MODULES:
        print(f"BLOCKED: unsupported packaged worker module: {module}", file=sys.stderr)
        return 2
    original_argv = sys.argv
    sys.argv = [f"{module}.py", *values]
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=False)
    finally:
        sys.argv = original_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
