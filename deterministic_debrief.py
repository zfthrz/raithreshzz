"""Fail-closed entrypoint for the product debrief.

The deterministic renderer still lives in the historical DeepSeek module while
it is extracted incrementally. This adapter makes that implementation detail
explicit and prevents the product path from reaching its transport function.
"""

from __future__ import annotations

import os
from types import ModuleType


DETERMINISTIC_ENVIRONMENT = {
    "RACE_ENGINEER_DETERMINISTIC_FIRST": "1",
    "RACE_ENGINEER_EPISODE_DETERMINISTIC": "1",
    "RACE_ENGINEER_SUMMARY_DETERMINISTIC": "1",
    "RACE_ENGINEER_GLOBAL_DETERMINISTIC": "1",
    "RACE_ENGINEER_LLM_RANKER": "0",
}


def configure_deterministic_environment() -> None:
    os.environ.update(DETERMINISTIC_ENVIRONMENT)
    os.environ.pop("DEEPSEEK_API_KEY", None)


def blocked_llm_transport(*args, **kwargs):
    raise RuntimeError("LLM transport is disabled in deterministic debrief mode")


def run(renderer: ModuleType | None = None) -> int:
    configure_deterministic_environment()
    if renderer is None:
        import llm_analysis_deepseek as renderer

    # Defence in depth: even a future regression in an environment gate cannot
    # turn the product debrief into a network call.
    renderer.deepseek_chat = blocked_llm_transport
    renderer.main()
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
