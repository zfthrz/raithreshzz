from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_LABELS = {"SAME", "DIFFERENT", "AMBIGUOUS"}
ALLOWED_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
ALLOWED_REASON_CODES = {
    "SPATIAL_PROXIMITY_SUPPORTS_SAME",
    "SPATIAL_SEPARATION_SUPPORTS_DIFFERENT",
    "OVERLAP_SUPPORTS_SAME",
    "LOW_OR_ZERO_OVERLAP_SUPPORTS_DIFFERENT",
    "CHANNEL_SET_SUPPORTS_SAME",
    "CHANNEL_SET_CONFLICT",
    "CHANNEL_SHAPE_SUPPORTS_SAME",
    "CHANNEL_SHAPE_CONFLICT",
    "DIRECTION_CONSISTENCY_SUPPORTS_SAME",
    "DIRECTION_CONSISTENCY_CONFLICT",
    "ACTION_TIME_SUPPORTS_SAME",
    "ACTION_TIME_CONFLICT",
    "EVIDENCE_MIXED_OR_INSUFFICIENT",
}


def normalize(value):
    if not isinstance(value, dict):
        return value, []
    out = dict(value)
    repairs = []
    codes = out.get("reason_codes")
    if isinstance(codes, list) and len(codes) > 6:
        out["reason_codes"] = codes[:6]
        repairs.append("truncate_reason_codes_to_6")
    evidence = out.get("decisive_evidence")
    if isinstance(evidence, list) and len(evidence) > 4:
        out["decisive_evidence"] = evidence[:4]
        repairs.append("truncate_decisive_evidence_to_4")
    reason = out.get("reason")
    if isinstance(reason, str) and len(reason) > 900:
        out["reason"] = reason[:900].rstrip()
        repairs.append("truncate_reason_to_900_chars")
    return out, repairs


def validate(value):
    errors = []
    if not isinstance(value, dict):
        return ["response is not an object"]
    expected = {"label", "confidence", "reason_codes", "decisive_evidence", "reason"}
    extra = set(value) - expected
    missing = expected - set(value)
    if missing:
        errors.append("missing fields: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("unexpected fields: " + ", ".join(sorted(extra)))
    if value.get("label") not in ALLOWED_LABELS:
        errors.append("invalid label")
    if value.get("confidence") not in ALLOWED_CONFIDENCE:
        errors.append("invalid confidence")
    codes = value.get("reason_codes")
    if not isinstance(codes, list) or not codes:
        errors.append("reason_codes must be a non-empty list")
    else:
        bad = [c for c in codes if c not in ALLOWED_REASON_CODES]
        if bad:
            errors.append("invalid reason_codes: " + ", ".join(map(str, bad)))
        if len(codes) > 6:
            errors.append("too many reason_codes")
    evidence = value.get("decisive_evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("decisive_evidence must be a non-empty list")
    else:
        if len(evidence) > 4:
            errors.append("too many decisive_evidence items")
        if any(not isinstance(x, str) or not x.strip() for x in evidence):
            errors.append("invalid decisive_evidence item")
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append("reason must be a non-empty string")
    elif len(reason) > 900:
        errors.append("reason too long")
    return errors


def main():
    ap = argparse.ArgumentParser(description="Repair only schema-format overflow in DeepSeek pair reviews; never changes label/confidence.")
    ap.add_argument("input_json")
    ap.add_argument("--output", default="deepseek_pair_reviews_repaired.json")
    args = ap.parse_args()

    src = Path(args.input_json)
    out = Path(args.output)
    data = json.loads(src.read_text(encoding="utf-8"))
    repaired = 0
    still_invalid = 0

    data = json.loads(src.read_text(encoding="utf-8"))
    repaired = 0
    still_invalid = 0
    for i, row in enumerate(data.get("reviews") or []):
        if row.get("status") == "VALID":
            continue
        pair_id = row.get("pair_id")
        attempts = row.get("attempts")
        raw = row.get("raw_parsed_response")
        norm, repairs = normalize(raw)
        errors = validate(norm)
        if errors:
            still_invalid += 1
            continue
        data["reviews"][i] = {
            "pair_id": pair_id,
            "status": "VALID",
            "attempts": attempts,
            "label": norm["label"],
            "confidence": norm["confidence"],
            "reason_codes": norm["reason_codes"],
            "decisive_evidence": norm["decisive_evidence"],
            "reason": norm["reason"],
            "deterministic_repairs": repairs,
            "recovered_from_invalid_output": True,
        }
        repaired += 1

    meta = data.setdefault("metadata", {})
    meta["schema_repair_version"] = "1.0"
    meta["schema_repaired_at_utc"] = datetime.now(timezone.utc).isoformat()
    meta["schema_repaired_review_count"] = repaired
    meta["schema_still_invalid_review_count"] = still_invalid
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Repaired: {repaired}")
    print(f"Still invalid: {still_invalid}")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()
