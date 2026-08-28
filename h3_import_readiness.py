"""Read-only discovery of official H3 bundles eligible for History import."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


H3_IMPORT_READINESS_VERSION = "0.1"
H3_NOT_APPLICABLE = "H3_NOT_APPLICABLE"
H3_READY_TO_IMPORT = "H3_READY_TO_IMPORT"
H3_IMPORTED = "H3_IMPORTED"
H3_CONFLICT = "H3_CONFLICT"
H3_FAILED = "H3_FAILED"
_CACHE_KEY: tuple[Any, ...] | None = None
_CACHE_VALUE: dict[H3Context, dict[str, Any]] | None = None


@dataclass(frozen=True)
class H3Context:
    track: str
    track_layout: str
    vehicle_variant: str


def clear_h3_import_readiness_cache() -> None:
    global _CACHE_KEY, _CACHE_VALUE
    _CACHE_KEY = None
    _CACHE_VALUE = None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _feature_context(features_path: Path) -> tuple[H3Context, int]:
    rows = _load_json(features_path)
    if not isinstance(rows, list) or not rows:
        raise ValueError("episode_pair_features vacío o inválido")
    contexts: set[H3Context] = set()
    sessions: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("episode_pair_features contiene una fila inválida")
        context = H3Context(
            str(row.get("track") or "").strip(),
            str(row.get("track_layout") or "").strip(),
            str(row.get("vehicle_variant") or "").strip(),
        )
        if not all((context.track, context.track_layout, context.vehicle_variant)):
            raise ValueError("episode_pair_features contiene contexto incompleto")
        contexts.add(context)
        for key in ("session_a", "session_b"):
            if row.get(key) is not None:
                sessions.add(int(row[key]))
    if len(contexts) != 1:
        raise ValueError("episode_pair_features mezcla contextos H3")
    return next(iter(contexts)), len(sessions)


def _conflict_count(patterns_path: Path) -> int:
    document = _load_json(patterns_path)
    if not isinstance(document, dict):
        raise ValueError("persistent_patterns inválido")
    summary = document.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("persistent_patterns sin summary")
    return int(summary.get("conflict_review_required_count") or 0)


def discover_h3_import_readiness(
    *,
    batches_root: Path,
    history_db: Path,
) -> dict[H3Context, dict[str, Any]]:
    """Inspect the newest/largest H3 materialization for each exact context.

    Discovery never runs H2/H3, creates outputs or mutates History.  Existing
    bundles are validated through the same import contract used by production.
    """

    batches_root = Path(batches_root)
    history_db = Path(history_db)
    candidates: dict[H3Context, list[dict[str, Any]]] = {}
    if not batches_root.is_dir():
        return {}

    for features_path in batches_root.glob("*/episode_pair_features.json"):
        try:
            context, session_count = _feature_context(features_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            # An unreadable features file cannot be assigned safely to a context.
            continue
        batch_dir = features_path.parent
        matches_path = batch_dir / "episode_pair_matches.json"
        patterns_path = batch_dir / "persistent_patterns.json"
        candidates.setdefault(context, []).append({
            "batch_id": batch_dir.name,
            "features_path": features_path,
            "matches_path": matches_path,
            "patterns_path": patterns_path,
            "session_count": session_count,
            "mtime_ns": features_path.stat().st_mtime_ns,
        })

    selected = {
        context: max(
            rows,
            key=lambda row: (row["session_count"], row["mtime_ns"], row["batch_id"]),
        )
        for context, rows in candidates.items()
    }

    fingerprint_rows = []
    for context, candidate in sorted(
        selected.items(),
        key=lambda item: (item[0].track, item[0].track_layout, item[0].vehicle_variant),
    ):
        file_fingerprints = []
        for key in ("features_path", "matches_path", "patterns_path"):
            path = candidate[key]
            stat = path.stat() if path.is_file() else None
            file_fingerprints.append(
                (str(path), stat.st_mtime_ns if stat else None, stat.st_size if stat else None)
            )
        fingerprint_rows.append((context, tuple(file_fingerprints)))
    history_stat = history_db.stat() if history_db.is_file() else None
    cache_key = (
        tuple(fingerprint_rows),
        str(history_db),
        history_stat.st_mtime_ns if history_stat else None,
        history_stat.st_size if history_stat else None,
    )
    global _CACHE_KEY, _CACHE_VALUE
    if cache_key == _CACHE_KEY and _CACHE_VALUE is not None:
        return deepcopy(_CACHE_VALUE)

    connection = None
    history_error = ""
    if history_db.is_file():
        import duckdb
        try:
            connection = duckdb.connect(str(history_db), read_only=True)
        except Exception as exc:
            history_error = f"{type(exc).__name__}: {exc}"

    result: dict[H3Context, dict[str, Any]] = {}
    try:
        for context, candidate in selected.items():
            matches_path = candidate["matches_path"]
            patterns_path = candidate["patterns_path"]
            base = {
                "version": H3_IMPORT_READINESS_VERSION,
                "batch_id": candidate["batch_id"],
                "session_count": candidate["session_count"],
                "features_path": str(candidate["features_path"]),
                "matches_path": str(matches_path),
                "patterns_path": str(patterns_path),
                "read_only": True,
                "historical_actions_authorized": False,
            }
            if not matches_path.exists() and not patterns_path.exists():
                result[context] = {**base, "status": H3_NOT_APPLICABLE}
                continue
            if not matches_path.is_file() or not patterns_path.is_file():
                result[context] = {
                    **base,
                    "status": H3_FAILED,
                    "reason": "materialización H3 incompleta",
                }
                continue
            try:
                conflicts = _conflict_count(patterns_path)
                if conflicts:
                    result[context] = {
                        **base,
                        "status": H3_CONFLICT,
                        "conflict_count": conflicts,
                    }
                    continue
                if connection is None:
                    result[context] = {
                        **base,
                        "status": H3_FAILED,
                        "reason": (
                            "History DB no disponible para validar membresías"
                            + (f": {history_error}" if history_error else "")
                        ),
                    }
                    continue

                from session_history import inspect_pattern_run_import

                inspection = inspect_pattern_run_import(
                    connection,
                    patterns_path,
                    matches_path,
                )
                status = (
                    H3_IMPORTED
                    if inspection["status"] == "IMPORTED"
                    else H3_READY_TO_IMPORT
                )
                result[context] = {**base, **inspection, "status": status}
            except Exception as exc:
                result[context] = {
                    **base,
                    "status": H3_FAILED,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
    finally:
        if connection is not None:
            connection.close()
    _CACHE_KEY = cache_key
    _CACHE_VALUE = deepcopy(result)
    return result
