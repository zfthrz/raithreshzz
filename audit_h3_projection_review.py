"""Summarize isolated human review of existing H3.2 projection matches.

This audit is positive-only and observational. It evaluates the generated
projection queue; it does not call the matcher, search for missing pairs, infer
thresholds, or authorize H3 membership.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import validate_pair_labels


AUDIT_VERSION = "0.1"
REVIEW_SCOPE = "H3_2_PROJECTION_VALIDATION_ONLY"
AUTHORITY_FALSE_FIELDS = (
    "labels_authorize_matcher_calibration",
    "labels_authorize_h3_membership",
    "affects_next_stint_plan",
    "historical_actions_authorized",
)
METRIC_FIELDS = (
    "center_distance_abs_diff_m",
    "overlap_over_union",
    "overlap_over_shorter",
    "channel_jaccard",
)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: la raíz no es un objeto.")
    return value


def _require_isolated_metadata(
    document: dict[str, Any], *, label: str
) -> dict[str, Any]:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError(f"{label}.metadata no es un objeto.")
    if metadata.get("review_scope") != REVIEW_SCOPE:
        raise ValueError(f"{label} no pertenece al scope aislado H3.2.")
    for field in AUTHORITY_FALSE_FIELDS:
        if metadata.get(field) is not False:
            raise ValueError(f"{label}.metadata.{field} debe ser false.")
    return metadata


def _distribution(values: Iterable[Any]) -> dict[str, float | int | None]:
    numeric = sorted(
        float(value)
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    if not numeric:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {
        "count": len(numeric),
        "min": numeric[0],
        "median": statistics.median(numeric),
        "max": numeric[-1],
    }


def _label_summary(labels: Iterable[str]) -> dict[str, Any]:
    counts = Counter(labels)
    total = sum(counts.values())
    order = ("SAME", "DIFFERENT", "AMBIGUOUS", "SKIP")
    return {
        "total": total,
        "counts": {label: counts.get(label, 0) for label in order},
        "percentages": {
            label: round(counts.get(label, 0) * 100.0 / total, 3)
            if total
            else 0.0
            for label in order
        },
    }


def audit_projection_review(
    queue_path: Path,
    labels_path: Path,
) -> dict[str, Any]:
    errors, warnings, validation = validate_pair_labels.validate(
        queue_path, labels_path
    )
    if errors:
        raise ValueError("Etiquetas inválidas: " + "; ".join(errors))

    queue_document = _load_object(queue_path)
    labels_document = _load_object(labels_path)
    queue_metadata = _require_isolated_metadata(queue_document, label="queue")
    _require_isolated_metadata(labels_document, label="labels")

    queue = queue_document.get("queue")
    labels = labels_document.get("labels")
    if not isinstance(queue, list) or not isinstance(labels, list):
        raise ValueError("Queue o labels no es lista.")
    if validation.get("unreviewed") != 0:
        raise ValueError("La revisión humana todavía tiene pares sin etiquetar.")

    labels_by_id = {
        item["pair_id"]: item["human_label"]
        for item in labels
        if isinstance(item, dict)
        and isinstance(item.get("pair_id"), str)
        and isinstance(item.get("human_label"), str)
    }

    pair_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    for index, item in enumerate(queue):
        if not isinstance(item, dict):
            raise ValueError(f"queue[{index}] no es objeto.")
        if item.get("review_scope") != REVIEW_SCOPE:
            raise ValueError(f"queue[{index}] tiene scope inválido.")
        pair_id = item.get("pair_id")
        if pair_id not in labels_by_id:
            raise ValueError(f"{pair_id}: no tiene etiqueta humana válida.")
        features = item.get("features")
        evidence = item.get("h3_projection_evidence")
        if not isinstance(features, dict) or not isinstance(evidence, list) or not evidence:
            raise ValueError(f"{pair_id}: evidencia H3.2 inválida.")
        label = labels_by_id[pair_id]
        pair_rows.append({"label": label, "features": features})
        for edge_index, edge in enumerate(evidence):
            if not isinstance(edge, dict):
                raise ValueError(f"{pair_id}: evidence[{edge_index}] inválida.")
            decision = edge.get("matcher_decision")
            if not isinstance(decision, dict):
                raise ValueError(f"{pair_id}: matcher_decision ausente.")
            if decision.get("decision") != "MATCH" or decision.get("automatic") is not True:
                raise ValueError(f"{pair_id}: la evidencia no es un MATCH automático.")
            rule_id = decision.get("rule_id")
            pattern_id = edge.get("pattern_id")
            if not isinstance(rule_id, str) or not isinstance(pattern_id, str):
                raise ValueError(f"{pair_id}: identidad de proyección incompleta.")
            edge_rows.append({
                "pair_id": pair_id,
                "label": label,
                "rule_id": rule_id,
                "pattern_id": pattern_id,
                "pattern_state": edge.get("pattern_state"),
                "current_session_id": edge.get("current_session_id"),
                "features": features,
            })

    by_rule: dict[str, list[str]] = defaultdict(list)
    by_state: dict[str, list[str]] = defaultdict(list)
    by_pattern: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in edge_rows:
        by_rule[row["rule_id"]].append(row["label"])
        by_state[str(row["pattern_state"])].append(row["label"])
        by_pattern[row["pattern_id"]].append(row)

    patterns = []
    for pattern_id, rows in sorted(by_pattern.items()):
        patterns.append({
            "pattern_id": pattern_id,
            "pattern_state": rows[0]["pattern_state"],
            "projection_edge_count": len(rows),
            "projected_session_ids": sorted({
                row["current_session_id"]
                for row in rows
                if isinstance(row["current_session_id"], int)
            }),
            "human_labels": _label_summary(row["label"] for row in rows),
        })

    metrics_by_label: dict[str, dict[str, Any]] = {}
    for label in ("SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"):
        matching = [row["features"] for row in pair_rows if row["label"] == label]
        metrics_by_label[label] = {
            field: _distribution(features.get(field) for features in matching)
            for field in METRIC_FIELDS
        }

    return {
        "metadata": {
            "audit_version": AUDIT_VERSION,
            "status": "POSITIVE_ONLY_HUMAN_REVIEW_EVIDENCE",
            "review_scope": REVIEW_SCOPE,
            "queue_path": str(queue_path.resolve()),
            "queue_sha256": validate_pair_labels.file_sha256(queue_path),
            "labels_path": str(labels_path.resolve()),
            "labels_sha256": validate_pair_labels.file_sha256(labels_path),
            "selection_policy": queue_metadata.get("selection_policy"),
            "matcher_called": False,
            "llm_called": False,
            "threshold_inferred": False,
            "observational_only": True,
            "labels_authorize_matcher_calibration": False,
            "labels_authorize_h3_membership": False,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
        },
        "summary": {
            "reviewed_pair_count": len(pair_rows),
            "projection_edge_count": len(edge_rows),
            "human_labels_by_pair": _label_summary(row["label"] for row in pair_rows),
            "human_labels_by_projection_edge": _label_summary(
                row["label"] for row in edge_rows
            ),
            "pattern_count": len(patterns),
        },
        "by_matcher_rule": {
            key: _label_summary(value) for key, value in sorted(by_rule.items())
        },
        "by_pattern_state": {
            key: _label_summary(value) for key, value in sorted(by_state.items())
        },
        "metrics_by_human_label": metrics_by_label,
        "patterns": patterns,
        "validation_warnings": warnings,
        "limitations": [
            "La cola contiene sólo proyecciones que el matcher ya clasificó MATCH.",
            "El resultado estima acuerdo humano dentro de positivos seleccionados; no estima recall ni falsos negativos.",
            "Las distribuciones métricas son descriptivas y no definen thresholds.",
            "Las etiquetas no autorizan calibración, membresía H3, coaching ni cambios de runtime.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita etiquetas humanas de proyecciones H3.2 sin promoción."
    )
    parser.add_argument("queue_json", type=Path)
    parser.add_argument("labels_json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_projection_review(
        args.queue_json.resolve(), args.labels_json.resolve()
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    summary = report["summary"]
    pair_labels = summary["human_labels_by_pair"]
    print("=" * 76)
    print(f"RACE ENGINEER - H3.2 PROJECTION REVIEW AUDIT v{AUDIT_VERSION}")
    print("=" * 76)
    print(f"Reviewed pairs:   {summary['reviewed_pair_count']}")
    print(f"Projection edges: {summary['projection_edge_count']}")
    print(f"Patterns:         {summary['pattern_count']}")
    for label, count in pair_labels["counts"].items():
        print(f"{label:10} {count:4} ({pair_labels['percentages'][label]:6.2f}%)")
    print("By matcher rule:")
    for rule, values in report["by_matcher_rule"].items():
        counts = values["counts"]
        print(
            f"  {rule}: SAME={counts['SAME']} DIFFERENT={counts['DIFFERENT']} "
            f"AMBIGUOUS={counts['AMBIGUOUS']} SKIP={counts['SKIP']}"
        )
    print("Authority: HUMAN REVIEW EVIDENCE ONLY / NO AUTOMATIC PROMOTION")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
