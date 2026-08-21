#!/usr/bin/env python3
"""Read-only diagnostics for validated Race Engineer LLM output artifacts.

This tool measures validation and deterministic-repair burden.  It never rewrites
the source artifacts and has no production authority over ranking or coaching.
"""

from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


DIAGNOSTIC_VERSION = "0.1"
ERROR_CATEGORIES = (
    "FACTUAL_DIRECTION_INVERSION",
    "UNAUTHORIZED_CHANNEL",
    "WRONG_REFERENCE_TARGET",
    "UNOBSERVED_DOMAIN",
    "OTHER",
)
NON_REPAIR_FALLBACKS = {
    "ALL_EPISODES_EXCLUDED_BY_ANOMALY_GATE",
    "COMPARISON_QUALITY_GATE_EXCLUDED_BEFORE_LLM",
}


@dataclass(frozen=True)
class SessionDiagnostic:
    path: str
    backend: str
    model: str
    track: str
    comparison_count: int
    episode_count: int
    clean_episode_count: int
    episodes_requiring_repair_count: int
    replaced_interpretation_count: int
    replaced_recommendation_count: int
    pruned_hypothesis_count: int
    target_reference_repair_count: int
    episode_retry_count: int
    ranking_attempts_gt_one_count: int
    summary_attempts_gt_one_count: int
    global_attempts_gt_one_count: int
    fallback_count: int
    repair_rate: float
    clean_output: bool
    validation_error_categories: dict[str, int]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalized(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def classify_validation_error(error: str) -> str:
    """Classify a stored original validator error without changing its meaning."""

    value = _normalized(str(error))
    if (
        "vuelta comparada como objetivo" in value
        or "comparison lap as" in value
        or "wrong_reference_target" in value
        or "wrong reference target" in value
    ):
        return "WRONG_REFERENCE_TARGET"
    if (
        "no esta autorizado por action_channels" in value
        or "canal no esta autorizado" in value
        or "channel is not authorized" in value
        or "solo puede convertirse en accion" in value
    ):
        return "UNAUTHORIZED_CHANNEL"
    if "dominio no observado" in value or "unobserved domain" in value:
        return "UNOBSERVED_DOMAIN"
    if (
        "direccion factual invertida" in value
        or "direccion de coaching invertida" in value
        or "factual direction inversion" in value
        or "coaching direction inversion" in value
    ):
        return "FACTUAL_DIRECTION_INVERSION"
    return "OTHER"


def _infer_backend(metadata: dict[str, Any], model: str, path: str) -> str:
    for key in ("backend", "llm_backend", "provider"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    evidence = f"{model} {path}".casefold()
    if "deepseek" in evidence:
        return "deepseek"
    if "qwen38-27b" in evidence or "qwen3.8-27b" in evidence:
        return "ollama"
    if "ingenierov3" in evidence or "ollama" in evidence:
        return "ollama"
    if "qwen3-14b" in evidence or "llamacpp" in evidence or "llama.cpp" in evidence:
        return "llamacpp"
    return "UNKNOWN"


def _repair_fallback(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value not in NON_REPAIR_FALLBACKS


def _pruned_indexes(episode_audit: dict[str, Any], repairs: dict[str, Any]) -> set[Any]:
    indexes: set[Any] = set()
    for source in (
        episode_audit.get("pruned_hypothesis_indexes"),
        repairs.get("pruned_hypothesis_indexes"),
    ):
        for value in _list(source):
            try:
                indexes.add((type(value).__name__, json.dumps(value, sort_keys=True)))
            except TypeError:
                indexes.add((type(value).__name__, repr(value)))
    return indexes


def _stored_errors(payload: dict[str, Any]) -> Iterable[str]:
    for comparison in _list(payload.get("comparisons")):
        audit = _dict(_dict(comparison).get("llm_validation_audit"))
        for episode in _list(audit.get("episodes")):
            for error in _list(_dict(episode).get("original_validation_errors")):
                if isinstance(error, str) and error:
                    yield error
    global_audit = _dict(payload.get("global_validation_audit"))
    for error in _list(global_audit.get("llm_validation_errors")):
        if isinstance(error, str) and error:
            yield error


def diagnose_payload(payload: dict[str, Any], *, path: str = "<memory>") -> SessionDiagnostic:
    """Build metrics from one LLM result payload without mutating it."""

    if not isinstance(payload, dict) or not isinstance(payload.get("comparisons"), list):
        raise ValueError("not a Race Engineer LLM output: comparisons list is missing")

    metadata = _dict(payload.get("metadata"))
    model = str(metadata.get("model") or "UNKNOWN")
    track = str(metadata.get("track") or "UNKNOWN")
    backend = _infer_backend(metadata, model, path)

    episode_count = 0
    clean_episode_count = 0
    repaired_episode_count = 0
    replaced_interpretation_count = 0
    replaced_recommendation_count = 0
    pruned_hypothesis_count = 0
    target_reference_repair_count = 0
    episode_retry_count = 0
    ranking_attempts_gt_one_count = 0
    summary_attempts_gt_one_count = 0
    fallback_count = 0

    for comparison_value in payload["comparisons"]:
        comparison = _dict(comparison_value)
        audit = _dict(comparison.get("llm_validation_audit"))

        ranking = _dict(audit.get("priority_ranking"))
        if _integer(ranking.get("attempts")) > 1:
            ranking_attempts_gt_one_count += 1

        summary = _dict(audit.get("summary"))
        if _integer(summary.get("attempts")) > 1:
            summary_attempts_gt_one_count += 1
        if _repair_fallback(summary.get("fallback")):
            fallback_count += 1

        for episode_value in _list(audit.get("episodes")):
            episode = _dict(episode_value)
            repairs = _dict(episode.get("deterministic_repairs"))
            episode_count += 1

            attempts = _integer(episode.get("attempts"))
            if attempts > 1:
                episode_retry_count += 1

            replaced_fields = [
                value for value in _list(repairs.get("replaced_fields")) if isinstance(value, str)
            ]
            replaced_interpretation_count += sum(
                value == "interpretation" for value in replaced_fields
            )
            replaced_recommendation_count += sum(
                value == "recommendation" for value in replaced_fields
            )

            pruned = _pruned_indexes(episode, repairs)
            pruned_hypothesis_count += len(pruned)
            target_repairs = _list(repairs.get("target_reference_repairs"))
            target_reference_repair_count += len(target_repairs)
            has_fallback = _repair_fallback(episode.get("fallback"))
            if has_fallback:
                fallback_count += 1

            has_deterministic_repair = bool(
                replaced_fields or pruned or target_repairs or has_fallback
            )
            if has_deterministic_repair:
                repaired_episode_count += 1

            original_errors = _list(episode.get("original_validation_errors"))
            if attempts <= 1 and not has_deterministic_repair and not original_errors:
                clean_episode_count += 1

    global_audit = _dict(payload.get("global_validation_audit"))
    global_attempts_gt_one_count = int(_integer(global_audit.get("attempts")) > 1)
    if _repair_fallback(global_audit.get("fallback")):
        fallback_count += 1

    categories = Counter({category: 0 for category in ERROR_CATEGORIES})
    for error in _stored_errors(payload):
        categories[classify_validation_error(error)] += 1

    has_global_repairs = bool(
        _dict(global_audit.get("deterministic_repairs"))
        or _list(global_audit.get("pruned_global_items"))
    )
    clean_output = bool(
        clean_episode_count == episode_count
        and repaired_episode_count == 0
        and episode_retry_count == 0
        and ranking_attempts_gt_one_count == 0
        and summary_attempts_gt_one_count == 0
        and global_attempts_gt_one_count == 0
        and fallback_count == 0
        and not has_global_repairs
        and sum(categories.values()) == 0
    )

    return SessionDiagnostic(
        path=path,
        backend=backend,
        model=model,
        track=track,
        comparison_count=len(payload["comparisons"]),
        episode_count=episode_count,
        clean_episode_count=clean_episode_count,
        episodes_requiring_repair_count=repaired_episode_count,
        replaced_interpretation_count=replaced_interpretation_count,
        replaced_recommendation_count=replaced_recommendation_count,
        pruned_hypothesis_count=pruned_hypothesis_count,
        target_reference_repair_count=target_reference_repair_count,
        episode_retry_count=episode_retry_count,
        ranking_attempts_gt_one_count=ranking_attempts_gt_one_count,
        summary_attempts_gt_one_count=summary_attempts_gt_one_count,
        global_attempts_gt_one_count=global_attempts_gt_one_count,
        fallback_count=fallback_count,
        repair_rate=(repaired_episode_count / episode_count if episode_count else 0.0),
        clean_output=clean_output,
        validation_error_categories=dict(categories),
    )


def diagnose_file(path: Path) -> SessionDiagnostic:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return diagnose_payload(payload, path=str(path.resolve()))


def _totals(sessions: list[SessionDiagnostic]) -> dict[str, Any]:
    sum_fields = (
        "comparison_count",
        "episode_count",
        "clean_episode_count",
        "episodes_requiring_repair_count",
        "replaced_interpretation_count",
        "replaced_recommendation_count",
        "pruned_hypothesis_count",
        "target_reference_repair_count",
        "episode_retry_count",
        "ranking_attempts_gt_one_count",
        "summary_attempts_gt_one_count",
        "global_attempts_gt_one_count",
        "fallback_count",
    )
    result = {field: sum(getattr(session, field) for session in sessions) for field in sum_fields}
    result["output_count"] = len(sessions)
    result["clean_output_count"] = sum(session.clean_output for session in sessions)
    result["repair_rate"] = (
        result["episodes_requiring_repair_count"] / result["episode_count"]
        if result["episode_count"]
        else 0.0
    )
    result["clean_output_rate"] = (
        result["clean_output_count"] / result["output_count"] if result["output_count"] else 0.0
    )
    category_totals = Counter({category: 0 for category in ERROR_CATEGORIES})
    for session in sessions:
        category_totals.update(session.validation_error_categories)
    result["validation_error_categories"] = dict(category_totals)
    return result


def aggregate_sessions(sessions: list[SessionDiagnostic]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[SessionDiagnostic]] = {}
    for session in sessions:
        grouped.setdefault((session.backend, session.model, session.track), []).append(session)

    groups = []
    for (backend, model, track), members in sorted(grouped.items()):
        groups.append(
            {
                "backend": backend,
                "model": model,
                "track": track,
                **_totals(members),
            }
        )
    return {**_totals(sessions), "groups": groups}


def _expand_paths(inputs: list[str]) -> list[Path]:
    paths: dict[str, Path] = {}
    for raw in inputs:
        candidate = Path(raw)
        discovered = candidate.rglob("*.json") if candidate.is_dir() else [candidate]
        for path in discovered:
            if path.is_file():
                paths[str(path.resolve()).casefold()] = path
    return sorted(paths.values(), key=lambda value: str(value).casefold())


def _human_report(sessions: list[SessionDiagnostic], aggregate: dict[str, Any]) -> str:
    lines = [
        "=" * 88,
        f"RACE ENGINEER - LLM REPAIR DIAGNOSTICS v{DIAGNOSTIC_VERSION}",
        "=" * 88,
        f"Outputs: {aggregate['output_count']}",
        f"Episodes: {aggregate['episode_count']}",
        f"Episodes requiring deterministic repair: {aggregate['episodes_requiring_repair_count']}",
        f"Repair rate: {aggregate['repair_rate']:.1%}",
        f"Clean outputs: {aggregate['clean_output_count']} / {aggregate['output_count']} "
        f"({aggregate['clean_output_rate']:.1%})",
        f"Clean episodes: {aggregate['clean_episode_count']}",
        f"Replaced interpretations: {aggregate['replaced_interpretation_count']}",
        f"Replaced recommendations: {aggregate['replaced_recommendation_count']}",
        f"Pruned hypotheses: {aggregate['pruned_hypothesis_count']}",
        f"Target-reference repairs: {aggregate['target_reference_repair_count']}",
        f"Episode retries: {aggregate['episode_retry_count']}",
        f"Ranking attempts > 1: {aggregate['ranking_attempts_gt_one_count']}",
        f"Summary attempts > 1: {aggregate['summary_attempts_gt_one_count']}",
        f"Global attempts > 1: {aggregate['global_attempts_gt_one_count']}",
        f"Fallbacks: {aggregate['fallback_count']}",
        "",
        "VALIDATION ERROR CATEGORIES",
    ]
    for category in ERROR_CATEGORIES:
        lines.append(f"  {category}: {aggregate['validation_error_categories'][category]}")
    lines.extend(["", "BY BACKEND / MODEL / TRACK"])
    for group in aggregate["groups"]:
        lines.append(
            f"  {group['backend']} / {group['model']} / {group['track']}: "
            f"outputs={group['output_count']}, episodes={group['episode_count']}, "
            f"repairs={group['episodes_requiring_repair_count']} "
            f"({group['repair_rate']:.1%}), clean={group['clean_output_rate']:.1%}"
        )
    lines.extend(["", "OUTPUT DETAILS"])
    for session in sessions:
        lines.append(
            f"  {session.track} | {session.backend}/{session.model} | "
            f"comparisons={session.comparison_count}, episodes={session.episode_count}, "
            f"repairs={session.episodes_requiring_repair_count}, retries={session.episode_retry_count}, "
            f"fallbacks={session.fallback_count}, clean={'YES' if session.clean_output else 'NO'}"
        )
    lines.extend(
        [
            "",
            "Authority: DIAGNOSTIC ONLY - no artifact, ranking, P9/P10/P11 or coaching changed",
            "RESULT: PASS",
        ]
    )
    return "\n".join(lines)


def _write_json(path: Path, sessions: list[SessionDiagnostic], aggregate: dict[str, Any]) -> None:
    payload = {
        "metadata": {
            "diagnostic_version": DIAGNOSTIC_VERSION,
            "authority": "DIAGNOSTIC_ONLY",
            "source_artifacts_modified": False,
        },
        "aggregate": aggregate,
        "sessions": [asdict(session) for session in sessions],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, sessions: list[SessionDiagnostic]) -> None:
    rows = []
    for session in sessions:
        row = asdict(session)
        categories = row.pop("validation_error_categories")
        row.update({f"errors_{key.lower()}": value for key, value in categories.items()})
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="LLM result JSON files or directories")
    parser.add_argument("--json-report", type=Path, help="optional aggregate JSON report")
    parser.add_argument("--csv-report", type=Path, help="optional per-output CSV report")
    args = parser.parse_args(argv)

    paths = _expand_paths(args.inputs)
    if not paths:
        parser.error("no JSON files found")

    sessions: list[SessionDiagnostic] = []
    errors: list[str] = []
    for path in paths:
        try:
            sessions.append(diagnose_file(path))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
    if not sessions:
        return 2

    aggregate = aggregate_sessions(sessions)
    print(_human_report(sessions, aggregate))
    if args.json_report:
        _write_json(args.json_report, sessions, aggregate)
        print(f"JSON: {args.json_report}")
    if args.csv_report:
        _write_csv(args.csv_report, sessions)
        print(f"CSV: {args.csv_report}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
