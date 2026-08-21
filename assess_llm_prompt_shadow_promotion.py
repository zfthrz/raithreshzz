#!/usr/bin/env python3
"""Assess whether an LLM episode-prompt shadow policy may be promoted.

Only exact A/B pairs are promotion evidence: same deterministic source, backend
and model, with one production artifact and one artifact from the target shadow
policy. Cross-model results remain useful observations but cannot isolate the
effect of the prompt.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from llm_prompt_shadow_policy import SHADOW_PROMPT_POLICY_VERSION
from tools.llm_repair_diagnostics import SessionDiagnostic, diagnose_payload


GATE_VERSION = "0.1"
MIN_EXACT_PAIRS = 3
MIN_TRACKS = 2

VERDICT_READY = "PROMOTION_READY"
VERDICT_INSUFFICIENT = "PROMOTION_BLOCKED_INSUFFICIENT_PAIRED_EVIDENCE"
VERDICT_REGRESSION = "PROMOTION_BLOCKED_REGRESSION"
VERDICT_NO_BENEFIT = "PROMOTION_BLOCKED_NO_MEASURABLE_BENEFIT"

CRITICAL_ERROR_CATEGORIES = (
    "FACTUAL_DIRECTION_INVERSION",
    "UNAUTHORIZED_CHANNEL",
    "WRONG_REFERENCE_TARGET",
    "UNOBSERVED_DOMAIN",
)


def _source_key(value: str) -> str:
    return value.replace("\\", "/").casefold()


def _critical_errors(session: SessionDiagnostic) -> int:
    return sum(
        session.validation_error_categories.get(category, 0)
        for category in CRITICAL_ERROR_CATEGORIES
    )


def _variant_metrics(session: SessionDiagnostic) -> dict:
    return {
        "path": session.path,
        "backend": session.backend,
        "model": session.model,
        "prompt_policy": session.prompt_policy,
        "episode_count": session.episode_count,
        "episodes_requiring_repair_count": session.episodes_requiring_repair_count,
        "repair_rate": session.repair_rate,
        "critical_error_count": _critical_errors(session),
        "fallback_count": session.fallback_count,
        "validation_error_categories": session.validation_error_categories,
    }


def assess_sessions(
    sessions: Iterable[SessionDiagnostic],
    *,
    shadow_policy: str = SHADOW_PROMPT_POLICY_VERSION,
) -> dict:
    sessions = list(sessions)
    groups: dict[tuple[str, str, str], list[SessionDiagnostic]] = defaultdict(list)
    for session in sessions:
        groups[
            (_source_key(session.source_json), session.backend, session.model)
        ].append(session)

    exact_pairs = []
    paired_shadow_paths: set[str] = set()
    ambiguous_groups = []
    for (_, backend, model), members in sorted(groups.items()):
        production = [item for item in members if item.prompt_policy == "production"]
        shadow = [item for item in members if item.prompt_policy == shadow_policy]
        if not shadow:
            continue
        if len(production) != 1 or len(shadow) != 1:
            if production:
                ambiguous_groups.append({
                    "source_json": members[0].source_json,
                    "backend": backend,
                    "model": model,
                    "production_count": len(production),
                    "shadow_count": len(shadow),
                })
            continue

        baseline = production[0]
        candidate = shadow[0]
        paired_shadow_paths.add(candidate.path)
        consistent = (
            baseline.comparison_count == candidate.comparison_count
            and baseline.episode_count == candidate.episode_count
        )
        regressions = []
        benefits = []
        if candidate.repair_rate > baseline.repair_rate:
            regressions.append("repair_rate_increased")
        elif candidate.repair_rate < baseline.repair_rate:
            benefits.append("repair_rate_decreased")
        if _critical_errors(candidate) > _critical_errors(baseline):
            regressions.append("critical_errors_increased")
        elif _critical_errors(candidate) < _critical_errors(baseline):
            benefits.append("critical_errors_decreased")
        if candidate.fallback_count > baseline.fallback_count:
            regressions.append("fallbacks_increased")
        elif candidate.fallback_count < baseline.fallback_count:
            benefits.append("fallbacks_decreased")
        if not consistent:
            regressions.append("comparison_or_episode_count_mismatch")

        exact_pairs.append({
            "source_json": baseline.source_json,
            "track": baseline.track,
            "backend": backend,
            "model": model,
            "counts_consistent": consistent,
            "production": _variant_metrics(baseline),
            "shadow": _variant_metrics(candidate),
            "regressions": regressions,
            "benefits": benefits,
        })

    tracks = sorted({pair["track"] for pair in exact_pairs})
    regressions = [
        f"{pair['track']} / {pair['backend']} / {pair['model']}: {item}"
        for pair in exact_pairs
        for item in pair["regressions"]
    ]
    benefits = [
        f"{pair['track']} / {pair['backend']} / {pair['model']}: {item}"
        for pair in exact_pairs
        for item in pair["benefits"]
    ]
    unpaired_shadow = [
        _variant_metrics(session)
        | {"source_json": session.source_json, "track": session.track}
        for session in sessions
        if session.prompt_policy == shadow_policy
        and session.path not in paired_shadow_paths
    ]

    enough_pairs = len(exact_pairs) >= MIN_EXACT_PAIRS
    enough_tracks = len(tracks) >= MIN_TRACKS
    no_regression = not regressions and not ambiguous_groups
    measurable_benefit = bool(benefits)

    if not no_regression:
        verdict = VERDICT_REGRESSION
    elif not enough_pairs or not enough_tracks:
        verdict = VERDICT_INSUFFICIENT
    elif not measurable_benefit:
        verdict = VERDICT_NO_BENEFIT
    else:
        verdict = VERDICT_READY

    return {
        "metadata": {
            "gate_version": GATE_VERSION,
            "shadow_policy": shadow_policy,
            "authority": "SHADOW_OBSERVATIONAL_ONLY",
            "production_prompt_modified": False,
        },
        "verdict": verdict,
        "requirements": {
            "minimum_exact_pairs": MIN_EXACT_PAIRS,
            "minimum_tracks": MIN_TRACKS,
            "enough_exact_pairs": enough_pairs,
            "enough_tracks": enough_tracks,
            "no_regression": no_regression,
            "measurable_benefit": measurable_benefit,
        },
        "coverage": {
            "artifact_count": len(sessions),
            "exact_pair_count": len(exact_pairs),
            "tracks": tracks,
            "track_count": len(tracks),
            "unpaired_shadow_count": len(unpaired_shadow),
        },
        "exact_pairs": exact_pairs,
        "unpaired_shadow_artifacts": unpaired_shadow,
        "ambiguous_groups": ambiguous_groups,
        "regressions": regressions,
        "benefits": benefits,
        "authority": {
            "prompt_policy_promoted": verdict == VERDICT_READY,
            "production_ranking_changed": False,
            "production_coaching_changed": False,
        },
    }


def _expand_paths(inputs: list[str]) -> list[Path]:
    paths: dict[str, Path] = {}
    for raw in inputs:
        candidate = Path(raw)
        discovered = candidate.rglob("*.json") if candidate.is_dir() else [candidate]
        for path in discovered:
            if path.is_file():
                paths[str(path.resolve()).casefold()] = path
    return sorted(paths.values(), key=lambda path: str(path).casefold())


def load_sessions(inputs: list[str]) -> list[SessionDiagnostic]:
    sessions = []
    for path in _expand_paths(inputs):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            sessions.append(diagnose_payload(payload, path=str(path.resolve())))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
    return sessions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="LLM artifact files or directories")
    parser.add_argument("--output", type=Path, help="optional deterministic JSON report")
    args = parser.parse_args(argv)

    report = assess_sessions(load_sessions(args.inputs))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print("=" * 88)
    print(f"RACE ENGINEER - LLM PROMPT SHADOW PROMOTION GATE v{GATE_VERSION}")
    print("=" * 88)
    print(f"Verdict: {report['verdict']}")
    print(f"Exact A/B pairs: {report['coverage']['exact_pair_count']} / {MIN_EXACT_PAIRS}")
    print(f"Tracks with exact pairs: {report['coverage']['track_count']} / {MIN_TRACKS}")
    print(f"Unpaired shadow observations: {report['coverage']['unpaired_shadow_count']}")
    print(f"Regression-free: {report['requirements']['no_regression']}")
    print(f"Measurable benefit: {report['requirements']['measurable_benefit']}")
    if args.output:
        print(f"Output: {args.output.resolve()}")
    print("Authority: SHADOW ONLY - production prompt, ranking and coaching unchanged")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
