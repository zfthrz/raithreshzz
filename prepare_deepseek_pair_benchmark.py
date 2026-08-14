#!/usr/bin/env python3
"""Build a blind DeepSeek benchmark queue from human pair-label files.

H2.2 calibration support. Human labels are deliberately stripped from the queue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
ALLOWED_HUMAN_LABELS = {"SAME", "DIFFERENT", "AMBIGUOUS"}
FORBIDDEN_KEYS = {
    "human_label",
    "review_notes",
    "reviewed_at_utc",
    "selected_by",
    "matcher_decision",
    "matcher_rule",
    "decision",
    "rule",
}


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def find_forbidden(value, path="$"):
    hits = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                hits.append(f"{path}.{key}")
            hits.extend(find_forbidden(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            hits.extend(find_forbidden(child, f"{path}[{i}]"))
    return hits


def load_labels(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    labels = data.get("labels")
    if not isinstance(labels, list):
        raise ValueError(f"{path}: falta lista 'labels'.")
    return data, labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("label_files", nargs="+", help="Human label JSON files")
    parser.add_argument("--output", required=True, help="Blind benchmark queue JSON")
    args = parser.parse_args()

    pairs = []
    seen = {}
    source_files = []
    hidden_distribution = {k: 0 for k in sorted(ALLOWED_HUMAN_LABELS)}

    for raw_path in args.label_files:
        path = Path(raw_path)
        data, labels = load_labels(path)
        source_files.append({
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "label_schema_version": (data.get("metadata") or {}).get("label_schema_version"),
            "pair_count": len(labels),
        })

        for row in labels:
            if not isinstance(row, dict):
                raise ValueError(f"{path}: label row no es objeto.")
            pair_id = row.get("pair_id")
            human_label = row.get("human_label")
            features = row.get("feature_snapshot")
            if not isinstance(pair_id, str) or not pair_id:
                raise ValueError(f"{path}: pair_id inválido.")
            if human_label not in ALLOWED_HUMAN_LABELS:
                raise ValueError(f"{path}: human_label inválido para {pair_id}: {human_label!r}")
            if not isinstance(features, dict):
                raise ValueError(f"{path}: feature_snapshot inválido para {pair_id}.")

            feature_hash = sha256_json(features)
            if pair_id in seen:
                if seen[pair_id] != feature_hash:
                    raise ValueError(f"pair_id duplicado con features distintas: {pair_id}")
                continue
            seen[pair_id] = feature_hash
            hidden_distribution[human_label] += 1

            pairs.append({
                "pair_id": pair_id,
                "feature_snapshot": features,
            })

    # Keep deterministic ordering independent of input-file ordering.
    pairs.sort(key=lambda row: row["pair_id"])

    queue = {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "blind_deepseek_pair_reviewer_benchmark",
            "pair_count": len(pairs),
            "source_files": source_files,
            "blindness_contract": {
                "human_labels_in_queue": False,
                "matcher_decisions_in_queue": False,
                "matcher_thresholds_in_queue": False,
                "selection_lenses_in_queue": False,
            },
        },
        "pairs": pairs,
    }

    forbidden = find_forbidden(queue)
    if forbidden:
        raise RuntimeError("Blindness contract violated: " + ", ".join(forbidden[:20]))

    queue["metadata"]["content_sha256"] = sha256_json(pairs)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 78)
    print("H2.2 - BLIND DEEPSEEK PAIR BENCHMARK QUEUE v1.0")
    print("=" * 78)
    print(f"Pairs: {len(pairs)}")
    print(f"Output: {out}")
    print("Blindness: PASS")
    # Distribution is shown only to the human/operator, never written into the blind queue.
    print("Human distribution (operator audit only):")
    for label in ("SAME", "DIFFERENT", "AMBIGUOUS"):
        print(f"  {label:<9}: {hidden_distribution[label]}")


if __name__ == "__main__":
    main()
