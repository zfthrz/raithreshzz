"""Neutral standalone entry point for the deterministic product debrief.

Extracted from llm_analysis_deepseek.py so that the product debrief
(deterministic_debrief.py) can run without importing any historical LLM
backend.  The legacy module delegates to these same functions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def find_json_file():
    """Return the analysis JSON to process.

    Usage:
        python deterministic_debrief.py "archivo.json"

    If no argument and exactly one JSON candidate exists, use it automatically.
    """
    if len(sys.argv) > 1:
        path = sys.argv[1]

        if not os.path.isabs(path):
            path = os.path.join(
                BASE_DIR,
                path,
            )

        path = os.path.abspath(path)

        if not os.path.exists(path):
            raise FileNotFoundError(
                f"No existe el JSON:\n{path}"
            )

        if not path.lower().endswith(".json"):
            raise ValueError(
                "El archivo indicado no es un JSON."
            )

        return path

    files = sorted(
        [
            filename
            for filename in os.listdir(BASE_DIR)
            if filename.lower().endswith(".json")
            and not filename.lower().endswith("_llm_analysis.json")
        ]
    )

    if not files:
        raise RuntimeError(
            "No se encontró ningún archivo JSON."
        )

    if len(files) == 1:
        return os.path.join(
            BASE_DIR,
            files[0],
        )

    raise RuntimeError(
        "Hay múltiples archivos JSON.\n\n"
        "Indicá cuál utilizar:\n\n"
        'python deterministic_debrief.py "archivo.json"\n\n'
        "Archivos disponibles:\n"
        + "\n".join(f"  {filename}" for filename in files)
    )


def reset_deepseek_usage():
    """Clear legacy usage counters. No-op when legacy module is not loaded."""


def build_debrief_runtime(*, output_dir: str, base_dir: str):
    """Build the product runtime while preserving the legacy artifact schema."""
    from deterministic_debrief_app import build_neutral_debrief_runtime
    from deterministic_debrief_compatibility import LegacyArtifactMetadata
    from deterministic_debrief_output import save_compatible_debrief

    # Neutral usage record and presentation — no backend tokens needed.
    def usage_record():
        return {}

    def usage_presentation():
        pass

    return build_neutral_debrief_runtime(
        output_dir=output_dir,
        base_dir=base_dir,
        artifact_metadata=LegacyArtifactMetadata(
            model_name="deterministic_debrief",
            context_size=0,
            temperature=0.0,
            anomaly_gate_config={},
        ),
        usage_record=usage_record,
        usage_presentation=usage_presentation,
        save_output=save_compatible_debrief,
    )


def _resolve_output_dir(input_path: str) -> str:
    """Resolve the same output_dir path as the historical llm_analysis_deepseek main."""
    from runtime_paths import llm_debug_dir

    return str(llm_debug_dir(input_path, backend="deepseek"))


def main():
    """Product debrief entry point — no LLM backend imports."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    reset_deepseek_usage()

    input_path = find_json_file()

    output_dir = _resolve_output_dir(input_path)

    stages, presentation = build_debrief_runtime(
        output_dir=output_dir,
        base_dir=BASE_DIR,
    )
    run_deterministic_debrief(
        stages=stages,
        presentation=presentation,
        input_path=input_path,
    )


def run_deterministic_debrief(stages, presentation, input_path):
    """Run the deterministic debrief pipeline using the provided stages."""
    from deterministic_debrief_runtime import run_deterministic_debrief as _run

    return _run(
        stages=stages,
        presentation=presentation,
        input_path=input_path,
    )


if __name__ == "__main__":
    main()
