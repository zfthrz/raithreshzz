#!/usr/bin/env python3
"""Blind, isolated DeepSeek pair reviewer for Race Engineer H2.2.

One independent request per pair. The model never receives human labels, matcher
outputs, current matcher rules, or calibration thresholds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REVIEWER_VERSION = "1.0"
PROMPT_VERSION = "1.0"
OUTPUT_SCHEMA_VERSION = "1.0"
DEEPSEEK_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
MODEL_NAME = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TRANSPORT_ATTEMPTS = 2
MAX_CLASSIFICATION_ATTEMPTS = 2

PRICING_USD_PER_MILLION = {
    "deepseek-v4-flash": {"input_cache_hit": 0.0028, "input_cache_miss": 0.14, "output": 0.28},
    "deepseek-v4-pro": {"input_cache_hit": 0.003625, "input_cache_miss": 0.435, "output": 0.87},
}

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

USAGE = Counter()

SYSTEM_PROMPT = r"""
You are a blind calibration reviewer for a racing telemetry episode matcher.
Your task is to classify whether two cross-session driver-action episodes represent the same general historical pattern.

SEMANTICS
- SAME: the episodes represent the same general physical track location/region AND the same general driving-difference type. SAME does NOT mean identical samples, identical event boundaries, identical channels, or proven identical causality. Secondary channels may appear/disappear and shapes may differ somewhat.
- DIFFERENT: the evidence supports that they belong to materially different physical regions or materially different driving-difference patterns, so they should not be treated as the same historical pattern.
- AMBIGUOUS: the available evidence does not safely justify SAME or DIFFERENT. Use this when spatial and channel/shape evidence conflict, the pair sits on a plausible boundary, or both interpretations remain credible.

EVIDENCE POLICY
1. Spatial identity is the primary anchor: start/end/center positions, center separation, overlap over union, and overlap over the shorter episode.
2. Channel identity and per-channel shape are supporting evidence, not sufficient by themselves to make spatially distinct episodes SAME.
3. Action-time-loss similarity is secondary context only. Never let it override clear spatial evidence.
4. Direction consistency may support or weaken channel-shape similarity but is not a causal claim.
5. Do not infer corner names, driving causality, vehicle dynamics, grip, balance, understeer, oversteer, or setup effects.
6. Do NOT use or invent fixed matcher thresholds. Judge the supplied pair holistically from the evidence. You are not being told the current matcher rules.
7. Prefer AMBIGUOUS over an unsupported forced decision.

CONFIDENCE
- HIGH: evidence strongly supports the label and a credible alternative is hard to defend.
- MEDIUM: one label is better supported, but meaningful counter-evidence remains.
- LOW: weak or incomplete support; classification is mostly a cautious lean.

Return one JSON object only, with exactly these fields:
{
  "label": "SAME|DIFFERENT|AMBIGUOUS",
  "confidence": "HIGH|MEDIUM|LOW",
  "reason_codes": ["ONE_OR_MORE_ALLOWED_CODES"],
  "decisive_evidence": ["short factual evidence statement", "..."],
  "reason": "brief explanation grounded only in supplied features"
}

Allowed reason_codes:
SPATIAL_PROXIMITY_SUPPORTS_SAME
SPATIAL_SEPARATION_SUPPORTS_DIFFERENT
OVERLAP_SUPPORTS_SAME
LOW_OR_ZERO_OVERLAP_SUPPORTS_DIFFERENT
CHANNEL_SET_SUPPORTS_SAME
CHANNEL_SET_CONFLICT
CHANNEL_SHAPE_SUPPORTS_SAME
CHANNEL_SHAPE_CONFLICT
DIRECTION_CONSISTENCY_SUPPORTS_SAME
DIRECTION_CONSISTENCY_CONFLICT
ACTION_TIME_SUPPORTS_SAME
ACTION_TIME_CONFLICT
EVIDENCE_MIXED_OR_INSUFFICIENT
""".strip()


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def usage_int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def record_usage(result):
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(usage, dict):
        return
    USAGE["usage_responses"] += 1
    prompt = usage_int(usage.get("prompt_tokens"))
    completion = usage_int(usage.get("completion_tokens"))
    total = usage_int(usage.get("total_tokens")) or prompt + completion
    details = usage.get("prompt_tokens_details") or {}
    cache_hit = usage_int(usage.get("prompt_cache_hit_tokens")) or usage_int(details.get("cached_tokens"))
    cache_miss = usage_int(usage.get("prompt_cache_miss_tokens"))
    if not cache_miss and prompt >= cache_hit:
        cache_miss = prompt - cache_hit
    USAGE["prompt_tokens"] += prompt
    USAGE["cache_hit"] += cache_hit
    USAGE["cache_miss"] += cache_miss
    USAGE["completion_tokens"] += completion
    USAGE["total_tokens"] += total


def estimated_cost():
    p = PRICING_USD_PER_MILLION.get(MODEL_NAME)
    if not p:
        return None
    return (
        USAGE["cache_hit"] * p["input_cache_hit"]
        + USAGE["cache_miss"] * p["input_cache_miss"]
        + USAGE["completion_tokens"] * p["output"]
    ) / 1_000_000.0


def deepseek_json(system_prompt, user_prompt, temperature, timeout_seconds):
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY no está configurada. En Codespaces agregala como secret/export de entorno."
        )
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "max_tokens": 1200,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
        req = urllib.request.Request(
            DEEPSEEK_URL,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            USAGE["http_requests"] += 1
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                raw = response.read()
            result = json.loads(raw.decode("utf-8"))
            record_usage(result)
            choices = result.get("choices") or []
            content = ((choices[0].get("message") or {}).get("content")) if choices else None
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("DeepSeek devolvió content vacío.")
            return json.loads(content)
        except urllib.error.HTTPError as exc:
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body_text = ""
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            if retryable and attempt < MAX_TRANSPORT_ATTEMPTS:
                time.sleep(2)
                continue
            raise RuntimeError(f"DEEPSEEK_HTTP_ERROR HTTP {exc.code}: {body_text[:1200]}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt < MAX_TRANSPORT_ATTEMPTS:
                time.sleep(2)
                continue
            raise RuntimeError(f"DEEPSEEK_REQUEST_FAILED: {exc}") from exc
    raise RuntimeError(f"DEEPSEEK_REQUEST_FAILED: {last_error}")


def validate_review(value):
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


def build_user_prompt(pair, validation_errors=None):
    feature_snapshot = pair.get("feature_snapshot")
    payload = {
        "pair_id_for_operator_trace_only": pair.get("pair_id"),
        "feature_snapshot": feature_snapshot,
    }
    prefix = "Review this pair independently. Do not assume anything from other pairs."
    if validation_errors:
        prefix += "\nYour previous JSON failed schema validation: " + "; ".join(validation_errors)
    return prefix + "\n\nPAIR FEATURES:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def load_queue(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pairs = data.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("Queue inválida: falta lista 'pairs'.")
    blindness = ((data.get("metadata") or {}).get("blindness_contract") or {})
    if blindness and not all(blindness.get(k) is False for k in (
        "human_labels_in_queue", "matcher_decisions_in_queue", "matcher_thresholds_in_queue", "selection_lenses_in_queue"
    )):
        raise ValueError("Queue no declara blindness contract válido.")
    return data, pairs


def save_output(path, output):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("queue")
    parser.add_argument("--output", required=True)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-pair-id", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    queue, pairs = load_queue(args.queue)
    queue_hash = sha256_json(pairs)
    selected_ids = set(args.only_pair_id)
    work = [p for p in pairs if not selected_ids or p.get("pair_id") in selected_ids]
    if args.limit is not None:
        work = work[:max(0, args.limit)]

    out_path = Path(args.output)
    existing = {}
    output = {
        "metadata": {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "reviewer_version": REVIEWER_VERSION,
            "prompt_version": PROMPT_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": MODEL_NAME,
            "temperature": args.temperature,
            "source_queue": str(args.queue),
            "source_pair_count": len(pairs),
            "source_pairs_sha256": queue_hash,
            "blindness_contract": (queue.get("metadata") or {}).get("blindness_contract"),
            "review_policy": "one_isolated_request_per_pair",
        },
        "reviews": [],
    }

    if out_path.exists() and not args.overwrite:
        old = json.loads(out_path.read_text(encoding="utf-8"))
        old_meta = old.get("metadata") or {}
        if old_meta.get("source_pairs_sha256") != queue_hash:
            raise RuntimeError("Existing output belongs to a different queue; use --overwrite or another output path.")
        for row in old.get("reviews") or []:
            if isinstance(row, dict) and isinstance(row.get("pair_id"), str):
                existing[row["pair_id"]] = row
        output = old

    if args.dry_run:
        print("=" * 78)
        print("H2.2 - DEEPSEEK PAIR REVIEWER v1.0 DRY RUN")
        print("=" * 78)
        print(f"Queue pairs: {len(pairs)}")
        print(f"Selected: {len(work)}")
        print(f"Model: {MODEL_NAME}")
        print(f"Queue hash: {queue_hash}")
        if work:
            print("First pair:", work[0].get("pair_id"))
            print("Feature keys:", sorted((work[0].get("feature_snapshot") or {}).keys()))
        print("No API request sent.")
        return

    print("=" * 78)
    print("H2.2 - DEEPSEEK PAIR REVIEWER v1.0")
    print("=" * 78)
    print(f"Model: {MODEL_NAME}")
    print(f"Pairs selected: {len(work)}")
    print(f"Already reviewed: {sum(1 for p in work if p.get('pair_id') in existing)}")

    reviews_by_id = {r.get("pair_id"): r for r in output.get("reviews") or [] if isinstance(r, dict)}

    for index, pair in enumerate(work, 1):
        pair_id = pair.get("pair_id")
        if not isinstance(pair_id, str) or not pair_id:
            raise ValueError("Pair sin pair_id válido.")
        if pair_id in existing and existing[pair_id].get("status") == "VALID":
            print(f"[{index:>3}/{len(work)}] {pair_id} REUSED")
            continue

        last_errors = None
        parsed = None
        attempts = 0
        for attempt in range(1, MAX_CLASSIFICATION_ATTEMPTS + 1):
            attempts = attempt
            user_prompt = build_user_prompt(pair, last_errors)
            parsed = deepseek_json(SYSTEM_PROMPT, user_prompt, args.temperature, args.timeout)
            last_errors = validate_review(parsed)
            if not last_errors:
                break

        if last_errors:
            review = {
                "pair_id": pair_id,
                "status": "INVALID",
                "attempts": attempts,
                "validation_errors": last_errors,
                "raw_parsed_response": parsed,
            }
            print(f"[{index:>3}/{len(work)}] {pair_id} INVALID: {'; '.join(last_errors)}")
        else:
            review = {
                "pair_id": pair_id,
                "status": "VALID",
                "attempts": attempts,
                "label": parsed["label"],
                "confidence": parsed["confidence"],
                "reason_codes": parsed["reason_codes"],
                "decisive_evidence": parsed["decisive_evidence"],
                "reason": parsed["reason"],
            }
            print(f"[{index:>3}/{len(work)}] {pair_id} {review['label']:<9} {review['confidence']}")

        reviews_by_id[pair_id] = review
        output["reviews"] = [reviews_by_id[k] for k in sorted(reviews_by_id)]
        output["metadata"]["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        output["metadata"]["review_count"] = len(output["reviews"])
        save_output(out_path, output)

    valid_reviews = [r for r in output["reviews"] if r.get("status") == "VALID"]
    print("\n" + "=" * 78)
    print("REVIEW SUMMARY")
    print("=" * 78)
    print(f"Valid: {len(valid_reviews)} / {len(output['reviews'])}")
    for label in ("SAME", "DIFFERENT", "AMBIGUOUS"):
        print(f"{label:<9}: {sum(1 for r in valid_reviews if r.get('label') == label)}")
    for confidence in ("HIGH", "MEDIUM", "LOW"):
        print(f"confidence {confidence:<6}: {sum(1 for r in valid_reviews if r.get('confidence') == confidence)}")
    print("\nDeepSeek usage:")
    print(f"  HTTP requests:   {USAGE['http_requests']}")
    print(f"  Input tokens:    {USAGE['prompt_tokens']}")
    print(f"    cache hit:     {USAGE['cache_hit']}")
    print(f"    cache miss:    {USAGE['cache_miss']}")
    print(f"  Output tokens:   {USAGE['completion_tokens']}")
    print(f"  Total tokens:    {USAGE['total_tokens']}")
    cost = estimated_cost()
    if cost is not None:
        print(f"  Estimated cost:  ${cost:.6f}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
