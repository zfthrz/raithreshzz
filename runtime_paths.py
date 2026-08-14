from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def generated_root() -> Path:
    """Return the local runtime-artifact root.

    Can be overridden with RACE_ENGINEER_GENERATED_DIR. Relative overrides are
    resolved from the repository root so Windows/PowerShell usage stays stable.
    """
    configured = os.environ.get("RACE_ENGINEER_GENERATED_DIR")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()
    return (PROJECT_ROOT / "data" / "generated").resolve()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_root() -> Path:
    """Local persistent state that must never be tracked by Git."""
    return ensure_dir(PROJECT_ROOT / "data" / "local")


def history_db_default_path() -> Path:
    return local_root() / "race_engineer_history.duckdb"


def analysis_output_path(database_path: str | os.PathLike[str]) -> Path:
    stem = Path(database_path).stem
    return ensure_dir(generated_root() / "analysis") / f"{stem}.json"


def llm_debug_dir(
    analysis_json_path: str | os.PathLike[str],
    *,
    backend: str,
) -> Path:
    stem = Path(analysis_json_path).stem
    return ensure_dir(generated_root() / "llm_debug" / stem / backend)


def llm_result_dir(
    analysis_json_path: str | os.PathLike[str],
) -> Path:
    stem = Path(analysis_json_path).stem
    return ensure_dir(generated_root() / "llm_results" / stem)


def run_state_dir(database_path: str | os.PathLike[str]) -> Path:
    return ensure_dir(generated_root() / "runs" / Path(database_path).stem)


def run_state_path(database_path: str | os.PathLike[str]) -> Path:
    return run_state_dir(database_path) / "state.json"


def stage_output_dir(
    database_path: str | os.PathLike[str],
    stage: str,
) -> Path:
    return ensure_dir(generated_root() / stage / Path(database_path).stem)


def historical_reference_output_path(
    database_path: str | os.PathLike[str],
) -> Path:
    return stage_output_dir(database_path, "h4") / "historical_reference_selection.json"


def dual_reference_output_path(
    database_path: str | os.PathLike[str],
) -> Path:
    return stage_output_dir(database_path, "h5_1") / "dual_reference_context.json"


def cross_session_output_path(
    database_path: str | os.PathLike[str],
) -> Path:
    return stage_output_dir(database_path, "h5_2") / "cross_session_comparison.json"
