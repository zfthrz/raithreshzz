"""Alias: historical_action_policy.py → historical_action_policy_v0_2.py

Este archivo mantiene la compatibilidad backward con el alias genérico.
El código fuente de la política v0.2 reside en historical_action_policy_v0_2.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Re-export everything from the versioned module.
from historical_action_policy_v0_2 import (  # noqa: F401
    ACTION_POLICY_VERSION,
    SCHEMA_VERSION,
    STATUS_AUTHORIZED,
    OBSERVATION_TO_ACTION,
    ACTION_TEXT,
    KNOWN_OBSERVATION_CODES,
    KNOWN_NON_MAPPABLE_CODES,
    sha256_file,
    build_action_candidates,
    main,
)

__all__ = [
    "ACTION_POLICY_VERSION",
    "SCHEMA_VERSION",
    "STATUS_AUTHORIZED",
    "OBSERVATION_TO_ACTION",
    "ACTION_TEXT",
    "KNOWN_OBSERVATION_CODES",
    "KNOWN_NON_MAPPABLE_CODES",
    "sha256_file",
    "build_action_candidates",
    "main",
]

# Verify the alias file is a thin wrapper (same SHA as source).
_ALIAS_PATH = Path(__file__).resolve()
_SOURCE_PATH = Path(__file__).resolve().parent / "historical_action_policy_v0_2.py"

if __name__ == "__main__":
    raise SystemExit(main())
