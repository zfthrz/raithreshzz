#!/usr/bin/env python3
"""Compare blind DeepSeek pair reviews against human labels for H2.2."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

VALID_LABELS = ("SAME", "DIFFERENT", "AMBIGUOUS")
CONFIDENCES = ("HIGH", "MEDIUM", "LOW")


def load_human(paths):
    out = {}
    source = {}
    for raw in paths:
        path = Path(raw)
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("labels") or []:
            pair_id = row.get("pair_id")
            label = row.get("human_label")
            if label not in VALID_LABELS:
                raise ValueError(f"{path}: invalid human label {label!r} for {pair_id}")
            if pair_id in out and out[pair_id] != label:
                raise ValueError(f"Conflicting human labels for {pair_id}")
            out[pair_id] = label
            source[pair_id] = str(path)
    return out, source


def pct(n, d):
    return 100.0 * n / d if d else 0.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("reviews")
    p.add_argument("human_label_files", nargs="+")
    p.add_argument("--json-output")
    args = p.parse_args()

    human, human_source = load_human(args.human_label_files)
    review_data = json.loads(Path(args.reviews).read_text(encoding="utf-8"))
    review_rows = review_data.get("reviews") or []
    reviews = {}
    duplicates = []
    for row in review_rows:
        pair_id = row.get("pair_id")
        if pair_id in reviews:
            duplicates.append(pair_id)
        reviews[pair_id] = row

    confusion = {h: {d: 0 for d in VALID_LABELS} for h in VALID_LABELS}
    confidence_confusion = {c: {h: {d: 0 for d in VALID_LABELS} for h in VALID_LABELS} for c in CONFIDENCES}
    mismatches = []
    missing = []
    invalid = []
    evaluated = 0
    exact = 0
    high_evaluated = 0
    high_exact = 0
    direct_opposite = []
    high_direct_opposite = []

    for pair_id, hlabel in human.items():
        row = reviews.get(pair_id)
        if row is None:
            missing.append(pair_id)
            continue
        if row.get("status") != "VALID" or row.get("label") not in VALID_LABELS or row.get("confidence") not in CONFIDENCES:
            invalid.append(pair_id)
            continue
        dlabel = row["label"]
        confidence = row["confidence"]
        evaluated += 1
        confusion[hlabel][dlabel] += 1
        confidence_confusion[confidence][hlabel][dlabel] += 1
        if hlabel == dlabel:
            exact += 1
        else:
            mismatches.append({
                "pair_id": pair_id,
                "human_label": hlabel,
                "deepseek_label": dlabel,
                "confidence": confidence,
                "reason": row.get("reason"),
                "source": human_source[pair_id],
            })
        if confidence == "HIGH":
            high_evaluated += 1
            if hlabel == dlabel:
                high_exact += 1
        is_direct = (hlabel == "SAME" and dlabel == "DIFFERENT") or (hlabel == "DIFFERENT" and dlabel == "SAME")
        if is_direct:
            direct_opposite.append(pair_id)
            if confidence == "HIGH":
                high_direct_opposite.append(pair_id)

    predicted_conf = Counter()
    predicted = Counter()
    for pair_id, row in reviews.items():
        if pair_id in human and row.get("status") == "VALID":
            predicted[row.get("label")] += 1
            predicted_conf[row.get("confidence")] += 1

    high_coverage = pct(high_evaluated, evaluated)
    report = {
        "status": "BENCHMARK_COMPLETE" if evaluated == len(human) and not invalid and not duplicates else "BENCHMARK_INCOMPLETE",
        "human_pair_count": len(human),
        "evaluated_pair_count": evaluated,
        "missing_pair_count": len(missing),
        "invalid_pair_count": len(invalid),
        "duplicate_review_count": len(duplicates),
        "exact_agreement_count": exact,
        "exact_agreement_rate": exact / evaluated if evaluated else None,
        "high_confidence_pair_count": high_evaluated,
        "high_confidence_coverage": high_evaluated / evaluated if evaluated else None,
        "high_confidence_exact_agreement_count": high_exact,
        "high_confidence_exact_agreement_rate": high_exact / high_evaluated if high_evaluated else None,
        "direct_same_different_flip_count": len(direct_opposite),
        "high_confidence_direct_same_different_flip_count": len(high_direct_opposite),
        "safety_gate": "PASS" if not high_direct_opposite and evaluated == len(human) and not invalid else "FAIL",
        "confusion_matrix": confusion,
        "confidence_distribution": dict(predicted_conf),
        "mismatches": mismatches,
        "missing_pair_ids": missing,
        "invalid_pair_ids": invalid,
        "duplicate_pair_ids": duplicates,
    }

    print("=" * 78)
    print("H2.2 - DEEPSEEK PAIR REVIEWER BENCHMARK v1.0")
    print("=" * 78)
    print(f"Human pairs:              {len(human)}")
    print(f"Evaluated:                {evaluated}")
    print(f"Exact agreement:          {exact}/{evaluated} ({pct(exact, evaluated):.1f}%)")
    print(f"HIGH-confidence coverage: {high_evaluated}/{evaluated} ({high_coverage:.1f}%)")
    print(f"HIGH exact agreement:     {high_exact}/{high_evaluated} ({pct(high_exact, high_evaluated):.1f}%)")
    print(f"Direct SAME<->DIFFERENT:  {len(direct_opposite)}")
    print(f"HIGH direct flips:        {len(high_direct_opposite)}")
    print(f"Safety gate:              {report['safety_gate']}")
    print(f"Benchmark status:         {report['status']}")

    print("\nCONFUSION MATRIX (rows=human, columns=DeepSeek)")
    print(f"{'human':<12}{'SAME':>10}{'DIFFERENT':>12}{'AMBIGUOUS':>12}")
    for h in VALID_LABELS:
        print(f"{h:<12}{confusion[h]['SAME']:>10}{confusion[h]['DIFFERENT']:>12}{confusion[h]['AMBIGUOUS']:>12}")

    print("\nDEEPSEEK CONFIDENCE")
    for c in CONFIDENCES:
        print(f"  {c:<6}: {predicted_conf[c]}")

    if mismatches:
        print("\nMISMATCHES")
        for row in mismatches:
            print(
                f"  {row['pair_id']} human={row['human_label']:<9} "
                f"deepseek={row['deepseek_label']:<9} conf={row['confidence']:<6} "
                f"reason={row.get('reason') or ''}"
            )

    print("\nINTERPRETATION")
    print("- Safety gate only checks the most dangerous assisted-review failure: a HIGH-confidence direct SAME<->DIFFERENT flip.")
    print("- It deliberately does NOT create an arbitrary minimum agreement threshold.")
    print("- Exact agreement and HIGH-confidence coverage determine usefulness; inspect mismatches before reviewing the 699-pair pool.")

    if args.json_output:
        out = Path(args.json_output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nJSON report: {out}")


if __name__ == "__main__":
    main()
