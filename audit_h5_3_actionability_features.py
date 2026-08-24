from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUDIT_VERSION = "0.1"
VALID_HUMAN_LABELS = {"ACTIONABLE", "OBSERVATIONAL_ONLY", "NOT_COMPARABLE", "AMBIGUOUS"}
CHANNEL_DELTA_KEYS = (
    "speed_delta_avg",
    "throttle_delta_avg",
    "brake_delta_avg",
    "steering_delta_avg",
)


def _channel_sign(value: Any) -> str:
    """Signo determinista de un delta de canal (pos/neg/zero)."""
    if value is None:
        return "zero"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "zero"
    if number > 0:
        return "pos"
    if number < 0:
        return "neg"
    return "zero"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: la raíz JSON debe ser un objeto.")
    return payload


def run_audit(
    dataset_path: Path,
    labels_path: Path,
) -> dict[str, Any]:
    """
    Shadow audit: analiza características del dataset H5.3b y sus labels humanos
    para describir qué diferencias observacionales existen entre cada human_label.

    No produce scores, thresholds, ranking ni reglas de producción.
    """
    dataset_data = load_json(dataset_path)
    labels_data = load_json(labels_path)

    # ── Validar que el dataset y labels son compatibles ──
    candidates = dataset_data.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("dataset.candidates ausente/inválido.")
    labels = labels_data.get("labels")
    if not isinstance(labels, list):
        raise ValueError("labels no es lista.")

    # Construir lookup de labels por audit_id
    labels_by_id: dict[str, dict[str, Any]] = {}
    for label_record in labels:
        if isinstance(label_record, dict) and isinstance(
            label_record.get("human_label"), str
        ):
            labels_by_id[label_record["audit_id"]] = label_record

    # ── Ensamblar items labelados + missing features ──
    labeled_items: list[dict[str, Any]] = []
    missing_features: list[str] = []
    missing_set: set[str] = set()

    # Inventario base de features deseables
    EXPECTED_FEATURES = {
        "human_label",
        "candidate_id",
        "track",
        "track_layout",
        "vehicle_variant",
        "car_name_raw",
        "delta_sign",
        "delta_change_s",
        "start_distance_m",
        "end_distance_m",
        "zone_length_m",
        "speed_delta_avg",
        "throttle_delta_avg",
        "brake_delta_avg",
        "channel_count",
        "location_label",
        "profile_localization",
    }

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        audit_id = candidate.get("audit_id")
        if not isinstance(audit_id, str):
            continue

        label_record = labels_by_id.get(audit_id)
        if label_record is None:
            continue
        human_label = label_record.get("human_label")
        if human_label not in VALID_HUMAN_LABELS:
            continue

        context = candidate.get("context") or {}
        evidence = candidate.get("evidence") or {}
        channel_evidence = candidate.get("observational_channel_evidence") or {}
        delta_sign = candidate.get("delta_sign")
        current_minus_historical = candidate.get("current_minus_historical_s")

        # Extraer features del candidate
        start_dist = evidence.get("start_distance_m")
        end_dist = evidence.get("end_distance_m")
        zone_length = None if start_dist is None or end_dist is None else end_dist - start_dist

        has_channels: dict[str, bool] = {}
        for ch in CHANNEL_DELTA_KEYS:
            has_channels[ch] = isinstance(channel_evidence.get(ch), (int, float))

        channel_count = sum(1 for v in has_channels.values() if v)

        # Detectar features faltantes — NO marcar todos como ausentes
        # Solo marcar si al menos un feature no aparece en ningún labeled_item
        pass  # Feature detection happens after the loop

        # Detectar profile localization
        profile_localization = "not_available"
        # No tenemos access directo al H5.2 en este audit; registramos limitation

        item = {
            "audit_id": audit_id,
            "human_label": human_label,
            "review_notes": label_record.get("review_notes", ""),
            "candidate_id": candidate.get("candidate_id"),
            "context": {
                "track": context.get("track"),
                "track_layout": context.get("track_layout"),
                "vehicle_variant": context.get("vehicle_variant"),
                "car_name_raw": context.get("car_name_raw"),
            },
            "delta_sign": delta_sign,
            "delta_change_s": evidence.get("delta_change_s"),
            "start_distance_m": start_dist,
            "end_distance_m": end_dist,
            "zone_length_m": zone_length,
            "speed_delta_avg": channel_evidence.get("speed_delta_avg"),
            "throttle_delta_avg": channel_evidence.get("throttle_delta_avg"),
            "brake_delta_avg": channel_evidence.get("brake_delta_avg"),
            "channel_presence": {k: v for k, v in has_channels.items()},
            "channel_count": channel_count,
            "location_label": candidate.get("location_label"),
            "profile_localization": profile_localization,
        }
        labeled_items.append(item)

    # ── Detectar features faltantes ──
    # Un feature se considera ausente si NINGÚN labeled_item tiene su valor presente
    present_features: dict[str, bool] = {feat: False for feat in EXPECTED_FEATURES}
    for item in labeled_items:
        for feat in EXPECTED_FEATURES:
            if present_features[feat]:
                continue
            # Cada feature se verifica en el item correspondiente
            if feat == "human_label" and isinstance(item.get("human_label"), str):
                present_features[feat] = True
            elif feat == "candidate_id" and isinstance(item.get("candidate_id"), str):
                present_features[feat] = True
            elif feat == "track" and isinstance(item.get("context", {}).get("track"), str):
                present_features[feat] = True
            elif feat == "track_layout" and isinstance(item.get("context", {}).get("track_layout"), str):
                present_features[feat] = True
            elif feat == "vehicle_variant" and isinstance(item.get("context", {}).get("vehicle_variant"), str):
                present_features[feat] = True
            elif feat == "car_name_raw" and isinstance(item.get("context", {}).get("car_name_raw"), str):
                present_features[feat] = True
            elif feat == "delta_sign" and item.get("delta_sign") is not None:
                present_features[feat] = True
            elif feat == "delta_change_s" and item.get("delta_change_s") is not None:
                present_features[feat] = True
            elif feat == "start_distance_m" and item.get("start_distance_m") is not None:
                present_features[feat] = True
            elif feat == "end_distance_m" and item.get("end_distance_m") is not None:
                present_features[feat] = True
            elif feat == "zone_length_m" and isinstance(item.get("zone_length_m"), (int, float)):
                present_features[feat] = True
            elif feat == "speed_delta_avg" and item.get("speed_delta_avg") is not None:
                present_features[feat] = True
            elif feat == "throttle_delta_avg" and item.get("throttle_delta_avg") is not None:
                present_features[feat] = True
            elif feat == "brake_delta_avg" and item.get("brake_delta_avg") is not None:
                present_features[feat] = True
            elif feat == "channel_count" and isinstance(item.get("channel_count"), int):
                present_features[feat] = True
            elif feat == "location_label" and item.get("location_label") is not None:
                present_features[feat] = True
            elif feat == "profile_localization" and isinstance(item.get("profile_localization"), str):
                present_features[feat] = True

    missing_features = sorted(feat for feat in EXPECTED_FEATURES if not present_features[feat])

    # ── Estadísticas agregadas ──
    # Count por label
    count_by_label = Counter(item["human_label"] for item in labeled_items)

    # Count por track y label
    count_by_track_label: dict[str, dict[str, int]] = {}
    for item in labeled_items:
        track = item["context"]["track"] or "UNKNOWN"
        label = item["human_label"]
        if track not in count_by_track_label:
            count_by_track_label[track] = {}
        count_by_track_label[track][label] = (
            count_by_track_label[track].get(label, 0) + 1
        )

    # Count por delta_sign y label
    count_by_delta_label: dict[str, dict[str, int]] = {}
    for item in labeled_items:
        sign = item["delta_sign"] or "UNKNOWN"
        label = item["human_label"]
        if sign not in count_by_delta_label:
            count_by_delta_label[sign] = {}
        count_by_delta_label[sign][label] = (
            count_by_delta_label[sign].get(label, 0) + 1
        )

    # Distribuciones descriptivas por label
    def _describe(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0}
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        result = {
            "count": n,
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "median": statistics.median(sorted_vals),
        }
        if n > 1:
            result["mean"] = statistics.mean(sorted_vals)
            # Percentiles
            result["p10"] = sorted_vals[max(0, n * 10 // 100)]
            result["p25"] = sorted_vals[max(0, n * 25 // 100)]
            result["p50"] = result["median"]
            result["p75"] = sorted_vals[max(0, n * 75 // 100)]
            result["p90"] = sorted_vals[min(n - 1, n * 90 // 100)]
        return result

    delta_by_label: dict[str, dict[str, Any]] = {}
    for label in VALID_HUMAN_LABELS:
        vals = [
            item["delta_change_s"]
            for item in labeled_items
            if item["human_label"] == label
            and isinstance(item["delta_change_s"], (int, float))
        ]
        if vals:
            delta_by_label[label] = _describe([float(v) for v in vals])

    zone_length_by_label: dict[str, dict[str, Any]] = {}
    for label in VALID_HUMAN_LABELS:
        vals = [
            item["zone_length_m"]
            for item in labeled_items
            if item["human_label"] == label
            and isinstance(item["zone_length_m"], (int, float))
        ]
        if vals:
            zone_length_by_label[label] = _describe([float(v) for v in vals])

    # Disponibilidad de canales por label
    channel_availability: dict[str, dict[str, Any]] = {}
    for label in VALID_HUMAN_LABELS:
        items_for_label = [
            item for item in labeled_items if item["human_label"] == label
        ]
        ch_counts = {
            ch: sum(
                1 for item in items_for_label
                if item["channel_presence"].get(ch, False)
            )
            for ch in CHANNEL_DELTA_KEYS
        }
        channel_availability[label] = ch_counts

    # Signos de canales por label
    channel_sign_distribution: dict[str, dict[str, dict[str, int]]] = {}
    for label in VALID_HUMAN_LABELS:
        items_for_label = [
            item for item in labeled_items if item["human_label"] == label
        ]
        ch_dist: dict[str, dict[str, int]] = {}
        for ch in CHANNEL_DELTA_KEYS:
            signs: dict[str, int] = {"positive": 0, "negative": 0, "zero_or_none": 0}
            for item in items_for_label:
                val = item.get(ch)
                if val is None:
                    signs["zero_or_none"] += 1
                elif val > 0:
                    signs["positive"] += 1
                elif val < 0:
                    signs["negative"] += 1
                else:
                    signs["zero_or_none"] += 1
            ch_dist[ch] = signs
        channel_sign_distribution[label] = ch_dist

    # Combinaciones de canales por label
    channel_combinations: dict[str, dict[str, int]] = {}
    for label in VALID_HUMAN_LABELS:
        items_for_label = [
            item for item in labeled_items if item["human_label"] == label
        ]
        combo_counts: Counter = Counter()
        for item in items_for_label:
            present_ch = sorted(
                ch for ch in CHANNEL_DELTA_KEYS if item["channel_presence"].get(ch, False)
            )
            combo_key = "|".join(present_ch) if present_ch else "none"
            combo_counts[combo_key] += 1
        channel_combinations[label] = dict(combo_counts)

    # Brake vs throttle: presencia por label
    brake_throttle_presence: dict[str, dict[str, int]] = {}
    for label in VALID_HUMAN_LABELS:
        items_for_label = [
            item for item in labeled_items if item["human_label"] == label
        ]
        presence_counts: Counter = Counter()
        for item in items_for_label:
            has_brake = bool(item["channel_presence"].get("brake_delta_avg", False))
            has_throttle = bool(
                item["channel_presence"].get("throttle_delta_avg", False)
            )
            if has_brake and has_throttle:
                key = "both"
            elif has_brake:
                key = "brake_only"
            elif has_throttle:
                key = "throttle_only"
            else:
                key = "neither"
            presence_counts[key] += 1
        brake_throttle_presence[label] = dict(presence_counts)

    # Brake sign x throttle sign por label
    brake_throttle_sign: dict[str, dict[str, int]] = {}
    for label in VALID_HUMAN_LABELS:
        items_for_label = [
            item for item in labeled_items if item["human_label"] == label
        ]
        sign_counts: Counter = Counter()
        for item in items_for_label:
            brake_sign = _channel_sign(item.get("brake_delta_avg"))
            throttle_sign = _channel_sign(item.get("throttle_delta_avg"))
            sign_counts[f"brake_{brake_sign}_throttle_{throttle_sign}"] += 1
        brake_throttle_sign[label] = dict(sign_counts)

    # ── Construir output ──
    output = {
        "metadata": {
            "audit_version": AUDIT_VERSION,
            "generated_at_utc": utc_now_iso(),
            "dataset_path": str(dataset_path.resolve()),
            "labels_path": str(labels_path.resolve()),
            "policy": {
                "production_policy_changed": False,
                "historical_actions_authorized": False,
                "thresholds_promoted": False,
                "human_labels_are_ground_truth": True,
            },
        },
        "status": "SHADOW_AUDIT_ONLY",
        "summary": {
            "total_labeled_candidates": len(labeled_items),
            "total_candidates_in_dataset": len(candidates),
            "label_records": len(labels),
            "count_by_label": dict(sorted(count_by_label.items())),
        },
        "distributions": {
            "count_by_track_and_label": {
                track: dict(sorted(labels_by_track.items()))
                for track, labels_by_track in sorted(count_by_track_label.items())
            },
            "count_by_delta_sign_and_label": {
                sign: dict(sorted(labels_by_sign.items()))
                for sign, labels_by_sign in sorted(count_by_delta_label.items())
            },
            "delta_change_s_by_label": {
                label: delta_by_label[label]
                for label in sorted(VALID_HUMAN_LABELS)
                if label in delta_by_label
            },
            "zone_length_m_by_label": {
                label: zone_length_by_label[label]
                for label in sorted(VALID_HUMAN_LABELS)
                if label in zone_length_by_label
            },
            "channel_availability_by_label": {
                label: dict(sorted(channel_availability[label].items()))
                for label in sorted(VALID_HUMAN_LABELS)
                if label in channel_availability
            },
            "channel_sign_distribution_by_label": {
                label: {
                    ch: dict(sorted(channel_sign_distribution[label][ch].items()))
                    for ch in sorted(CHANNEL_DELTA_KEYS)
                }
                for label in sorted(VALID_HUMAN_LABELS)
                if label in channel_sign_distribution
            },
            "channel_combinations_by_label": {
                label: dict(sorted(channel_combinations[label].items()))
                for label in sorted(VALID_HUMAN_LABELS)
                if label in channel_combinations
            },
            "brake_throttle_presence_by_label": {
                label: dict(sorted(brake_throttle_presence[label].items()))
                for label in sorted(VALID_HUMAN_LABELS)
                if label in brake_throttle_presence
            },
            "brake_throttle_sign_by_label": {
                label: dict(sorted(brake_throttle_sign[label].items()))
                for label in sorted(VALID_HUMAN_LABELS)
                if label in brake_throttle_sign
            },
        },
        "labeled_items": [
            _serialize_item(item) for item in labeled_items
        ],
        "missing_feature_inventory": missing_features,
    }

    return output


def _serialize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Serializar item para JSON determinista."""
    return {
        "audit_id": item["audit_id"],
        "human_label": item["human_label"],
        "candidate_id": item["candidate_id"],
        "context": item["context"],
        "delta_sign": item["delta_sign"],
        "delta_change_s": item["delta_change_s"],
        "start_distance_m": item["start_distance_m"],
        "end_distance_m": item["end_distance_m"],
        "zone_length_m": item["zone_length_m"],
        "speed_delta_avg": item["speed_delta_avg"],
        "throttle_delta_avg": item["throttle_delta_avg"],
        "brake_delta_avg": item["brake_delta_avg"],
        "channel_presence": item["channel_presence"],
        "channel_count": item["channel_count"],
        "location_label": item["location_label"],
        "profile_localization": item["profile_localization"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3b: shadow audit de features que diferencian labels humanos."
    )
    parser.add_argument("dataset_json", help="Dataset H5.3b audit JSON.")
    parser.add_argument("labels_json", help="Labels humanos validados JSON.")
    parser.add_argument(
        "--output",
        default="h5_3_actionability_feature_audit.json",
        help="Salida JSON del audit de features.",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset_json).resolve()
    labels_path = Path(args.labels_json).resolve()
    output_path = Path(args.output).resolve()

    if not dataset_path.exists():
        print(f"ERROR: dataset no encontrado: {dataset_path}")
        return 1
    if not labels_path.exists():
        print(f"ERROR: labels no encontrado: {labels_path}")
        return 1

    try:
        result = run_audit(dataset_path, labels_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = result["summary"]
    print("=" * 88)
    print(f"RACE ENGINEER - H5.3b ACTIONABILITY FEATURE AUDIT v{AUDIT_VERSION}")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Labeled candidates: {summary['total_labeled_candidates']}")
    print(f"Dataset candidates: {summary['total_candidates_in_dataset']}")
    print(f"Label counts: {summary['count_by_label']}")
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
