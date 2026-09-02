"""Fail-closed entrypoint for the product debrief.

Uses the neutral deterministic main module. No LLM backend is imported
transitively from this file.
"""

from __future__ import annotations

import os


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


def run() -> int:
    """Run the neutral product debrief with fail-closed gates.

    No llm_analysis* module is imported transitively.
    """
    configure_deterministic_environment()
    from deterministic_debrief_main import main as _neutral_main

    _neutral_main()
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
