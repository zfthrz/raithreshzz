from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("episode_pair_matcher", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_labels(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    labels = raw.get("labels") if isinstance(raw, dict) else None
    if not isinstance(labels, list):
        raise ValueError(f"{path} no contiene labels[].")
    return [r for r in labels if isinstance(r, dict)]


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida matcher H2 v0.3 contra labels humanos.")
    ap.add_argument("matcher_py")
    ap.add_argument("label_files", nargs="+")
    args = ap.parse_args()

    matcher_path = Path(args.matcher_py).resolve()
    matcher = load_module(matcher_path)

    records: list[dict[str, Any]] = []
    for raw_path in args.label_files:
        records.extend(load_labels(Path(raw_path).resolve()))

    human_counts = Counter()
    decision_counts = Counter()
    matrix = Counter()
    violations: list[dict[str, Any]] = []

    for record in records:
        human = str(record.get("human_label"))
        features = record.get("feature_snapshot")
        if not isinstance(features, dict):
            continue
        # label_episode_pairs stores a reduced feature_snapshot that omits some context
        # fields. The source batch was already hard-gated to the calibration context, so
        # restore only those omitted context fields for offline validation.
        features = dict(features)
        cal_ctx = getattr(matcher, "CALIBRATION_CONTEXT", {})
        features.setdefault("track_layout", cal_ctx.get("track_layout"))
        features.setdefault("vehicle_variant", cal_ctx.get("vehicle_variant"))
        result = matcher.classify_pair(features)
        decision = str(result["decision"])
        human_counts[human] += 1
        decision_counts[decision] += 1
        matrix[(human, decision)] += 1

        unsafe = (
            (human == "AMBIGUOUS" and decision in {"MATCH", "REJECT"})
            or (human == "DIFFERENT" and decision == "MATCH")
            or (human == "SAME" and decision == "REJECT")
        )
        if unsafe:
            violations.append({
                "pair_id": record.get("pair_id"),
                "human_label": human,
                "decision": decision,
                "rule_id": result.get("rule_id"),
            })

    automatic = decision_counts["MATCH"] + decision_counts["REJECT"]
    total = sum(human_counts.values())
    exact = (
        matrix[("SAME", "MATCH")]
        + matrix[("DIFFERENT", "REJECT")]
        + matrix[("AMBIGUOUS", "AMBIGUOUS")]
    )

    auto_correct = matrix[("SAME", "MATCH")] + matrix[("DIFFERENT", "REJECT")]
    auto_precision = (auto_correct / automatic) if automatic else None
    auto_coverage = (automatic / total) if total else None
    exact_rate = (exact / total) if total else None

    print("=" * 72)
    print("RACE ENGINEER - MATCHER CALIBRATION VALIDATION v0.3")
    print("=" * 72)
    print(f"Human labels: {dict(human_counts)}")
    print(f"Matcher decisions: {dict(decision_counts)}")
    print("Matrix:")
    for human in ("SAME", "AMBIGUOUS", "DIFFERENT"):
        print(
            f"  {human:10s} -> "
            f"MATCH={matrix[(human, 'MATCH')]} "
            f"AMBIGUOUS={matrix[(human, 'AMBIGUOUS')]} "
            f"REJECT={matrix[(human, 'REJECT')]}"
        )
    print(f"Automatic precision on observed labels: {auto_precision:.3f}" if auto_precision is not None else "Automatic precision: n/a")
    print(f"Automatic coverage: {auto_coverage:.3f}" if auto_coverage is not None else "Automatic coverage: n/a")
    print(f"Exact tri-state agreement: {exact_rate:.3f}" if exact_rate is not None else "Exact tri-state agreement: n/a")
    print(f"Safety violations: {len(violations)}")
    if violations:
        for v in violations:
            print("  ", v)
        return 2

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
