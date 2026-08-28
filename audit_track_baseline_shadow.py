from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from track_baseline_shadow import match_only_calibration, resolve_track_baseline
import episode_pair_matcher as matcher


AUDIT_VERSION = "0.3"


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return payload


def _human_expected(label: str) -> str | None:
    value = str(label or "").strip().upper()
    if value == "SAME":
        return "MATCH"
    if value == "DIFFERENT":
        return "REJECT"
    if value == "AMBIGUOUS":
        return "AMBIGUOUS"
    return None


def audit_batch(batch_dir: Path) -> dict[str, Any]:
    status_path = batch_dir / "BATCH_STATUS.json"
    labels_path = batch_dir / "pair_labels.json"
    if not status_path.is_file() or not labels_path.is_file():
        raise FileNotFoundError("BATCH_STATUS.json or pair_labels.json missing")

    status = _load_object(status_path)
    labels_payload = _load_object(labels_path)

    track = str(status.get("track") or "").strip()
    layout = str(status.get("track_layout") or "").strip()
    variant = str(status.get("vehicle_variant") or "").strip()
    batch_id = str(status.get("batch_id") or batch_dir.name)

    baseline = resolve_track_baseline(
        track=track,
        track_layout=layout,
        vehicle_variant=variant,
    )
    baseline_public = {
        key: value
        for key, value in baseline.items()
        if key != "calibration"
    }

    rows = []
    human_counts: Counter[str] = Counter()
    shadow_counts: Counter[str] = Counter()
    automatic_counts: Counter[str] = Counter()
    contradictions = []
    ambiguous_automatic = []

    labels = labels_payload.get("labels")
    if not isinstance(labels, list):
        labels = []

    calibration = baseline.get("calibration")
    can_shadow = (
        baseline.get("status") == "TRACK_MATCH_BASELINE_SHADOW"
        and isinstance(calibration, dict)
    )

    for item in labels:
        if not isinstance(item, dict):
            continue
        human_label = str(item.get("human_label") or "").strip().upper()
        expected = _human_expected(human_label)
        snapshot = item.get("feature_snapshot")
        if expected is None or not isinstance(snapshot, dict):
            continue

        pair = dict(snapshot)
        pair["track"] = track
        pair["track_layout"] = layout
        pair["vehicle_variant"] = variant

        human_counts[human_label] += 1

        if not can_shadow:
            rows.append(
                {
                    "pair_id": item.get("pair_id"),
                    "human_label": human_label,
                    "shadow_decision": None,
                    "automatic": False,
                }
            )
            continue

        decision = matcher.classify_pair(
            pair,
            calibration_override=match_only_calibration(calibration),
        )
        shadow_decision = str(decision.get("decision") or "AMBIGUOUS")
        automatic = bool(decision.get("automatic") is True)
        shadow_counts[shadow_decision] += 1
        if automatic:
            automatic_counts[shadow_decision] += 1

        contradiction = False
        if automatic and expected in {"MATCH", "REJECT"}:
            contradiction = shadow_decision != expected
        elif automatic and expected == "AMBIGUOUS":
            ambiguous_automatic.append(
                {
                    "pair_id": item.get("pair_id"),
                    "human_label": human_label,
                    "shadow_decision": shadow_decision,
                    "rule_id": decision.get("rule_id"),
                }
            )

        if contradiction:
            contradictions.append(
                {
                    "pair_id": item.get("pair_id"),
                    "human_label": human_label,
                    "expected": expected,
                    "shadow_decision": shadow_decision,
                    "rule_id": decision.get("rule_id"),
                }
            )

        rows.append(
            {
                "pair_id": item.get("pair_id"),
                "human_label": human_label,
                "shadow_decision": shadow_decision,
                "automatic": automatic,
                "rule_id": decision.get("rule_id"),
            }
        )

    decisive_labels = human_counts["SAME"] + human_counts["DIFFERENT"]
    automatic_decisive = sum(
        1
        for row in rows
        if row.get("automatic")
        and row.get("human_label") in {"SAME", "DIFFERENT"}
    )
    correct_automatic_decisive = sum(
        1
        for row in rows
        if row.get("automatic")
        and (
            (row.get("human_label") == "SAME" and row.get("shadow_decision") == "MATCH")
            or (
                row.get("human_label") == "DIFFERENT"
                and row.get("shadow_decision") == "REJECT"
            )
        )
    )

    precision = (
        correct_automatic_decisive / automatic_decisive
        if automatic_decisive
        else None
    )
    coverage = (
        automatic_decisive / decisive_labels
        if decisive_labels
        else None
    )

    if not can_shadow:
        observed_status = baseline.get("status") or "NO_SHADOW_BASELINE"
    elif contradictions:
        observed_status = "DRIFT_SIGNAL"
    elif not rows:
        observed_status = "NO_HUMAN_LABELS"
    elif automatic_decisive == 0:
        observed_status = "NO_AUTOMATIC_COVERAGE"
    else:
        observed_status = "NO_CONTRADICTIONS_OBSERVED"

    return {
        "audit_version": AUDIT_VERSION,
        "batch_id": batch_id,
        "batch_dir": str(batch_dir.resolve()),
        "track": track,
        "track_layout": layout,
        "vehicle_variant": variant,
        "baseline": baseline_public,
        "observed_status": observed_status,
        "production_authorized": False,
        "human_labels": dict(sorted(human_counts.items())),
        "shadow_decisions": dict(sorted(shadow_counts.items())),
        "automatic_decisions": dict(sorted(automatic_counts.items())),
        "decisive_human_labels": decisive_labels,
        "automatic_decisive_labels": automatic_decisive,
        "correct_automatic_decisive_labels": correct_automatic_decisive,
        "automatic_precision_on_decisive_labels": precision,
        "automatic_coverage_on_decisive_labels": coverage,
        "contradictions": contradictions,
        "automatic_on_human_ambiguous": ambiguous_automatic,
        "pairs": rows,
    }


def discover_shadow_batches(root: Path) -> tuple[list[Path], list[dict[str, Any]]]:
    result: list[Path] = []
    skipped: list[dict[str, Any]] = []
    if not root.is_dir():
        return result, skipped
    for status_path in sorted(root.glob("*/BATCH_STATUS.json")):
        try:
            status = _load_object(status_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            skipped.append({
                "batch_dir": str(status_path.parent.resolve()),
                "status": "SKIPPED_INVALID_STATUS",
                "reason": str(exc),
            })
            continue
        resolution = resolve_track_baseline(
            track=str(status.get("track") or "").strip(),
            track_layout=str(status.get("track_layout") or "").strip(),
            vehicle_variant=str(status.get("vehicle_variant") or "").strip(),
        )
        if resolution.get("status") != "TRACK_MATCH_BASELINE_SHADOW":
            continue
        labels_path = status_path.parent / "pair_labels.json"
        if not labels_path.is_file():
            skipped.append({
                "batch_id": str(status.get("batch_id") or status_path.parent.name),
                "track": str(status.get("track") or "").strip(),
                "vehicle_variant": str(status.get("vehicle_variant") or "").strip(),
                "batch_dir": str(status_path.parent.resolve()),
                "status": "SKIPPED_NO_LABELS",
                "reason": "pair_labels.json missing",
            })
            continue
        result.append(status_path.parent)
    return result, skipped


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit inherited H2 MATCH cores against existing human labels; REJECT remains variant-specific."
    )
    parser.add_argument(
        "--batches-root",
        type=Path,
        default=Path(__file__).resolve().parent / "calibration_batches",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    batches, skipped = discover_shadow_batches(args.batches_root)
    reports = []
    errors = []
    for batch_dir in batches:
        try:
            reports.append(audit_batch(batch_dir))
        except Exception as exc:
            errors.append(f"{batch_dir}: {exc}")

    payload = {
        "audit_version": AUDIT_VERSION,
        "production_authorized": False,
        "reports": reports,
        "skipped": skipped,
        "errors": errors,
    }

    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if not reports:
        print("No TRACK_BASELINE_SHADOW batches with existing artifacts were found.")
    else:
        print("Track MATCH-baseline shadow audit (observational only)")
        print("Production authorized: False")
        print()
        for report in reports:
            sources = ",".join(
                (report["baseline"].get("match") or {}).get("source_variants") or []
            ) or "—"
            print(
                f"{report['track']} | {report['vehicle_variant']} | "
                f"baseline={sources} | labels={sum(report['human_labels'].values())} | "
                f"status={report['observed_status']}"
            )
            print(
                f"  automatic precision decisive={_pct(report['automatic_precision_on_decisive_labels'])} | "
                f"coverage decisive={_pct(report['automatic_coverage_on_decisive_labels'])} | "
                f"contradictions={len(report['contradictions'])} | "
                f"auto-on-human-ambiguous={len(report['automatic_on_human_ambiguous'])}"
            )
            print(
                f"  human={report['human_labels']} | "
                f"shadow={report['shadow_decisions']}"
            )
            if report["contradictions"]:
                for item in report["contradictions"][:5]:
                    print(
                        f"    CONTRADICTION {item['pair_id']}: "
                        f"human={item['human_label']} shadow={item['shadow_decision']} "
                        f"rule={item['rule_id']}"
                    )
            if report["automatic_on_human_ambiguous"]:
                for item in report["automatic_on_human_ambiguous"][:5]:
                    print(
                        f"    AUTO_ON_AMBIGUOUS {item['pair_id']}: "
                        f"shadow={item['shadow_decision']} rule={item['rule_id']}"
                    )
            print()

    if skipped:
        print("Skipped shadow batches:")
        for item in skipped:
            print(
                f"  - {item.get('track', '—')} | "
                f"{item.get('vehicle_variant', '—')} | "
                f"{item.get('status')} | {item.get('reason')}"
            )
        print()

    if errors:
        print("Errors:")
        for error in errors:
            print(f"  - {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
