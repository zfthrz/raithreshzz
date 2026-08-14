# H2.2 — DeepSeek Assisted Pair Review v1.0

## Goal
Use DeepSeek as a blind pre-reviewer for cross-session episode pairs, never as automatic human ground truth.

## Stage 1: blind benchmark
Human pool currently contains 40 unique labels:
- SAME: 13
- DIFFERENT: 19
- AMBIGUOUS: 8

`prepare_deepseek_pair_benchmark.py` strips every human label/review field and creates a blind queue containing only `pair_id` plus `feature_snapshot`.

DeepSeek never receives:
- human labels;
- review notes;
- queue selection lenses;
- matcher decision/rule;
- matcher thresholds.

## Reviewer policy
`deepseek_pair_reviewer.py` performs one isolated request per pair and returns:
- label: SAME / DIFFERENT / AMBIGUOUS;
- confidence: HIGH / MEDIUM / LOW;
- reason codes;
- decisive factual evidence;
- short explanation.

Spatial identity is the primary anchor. Channel identity/shape is supporting evidence. Action-time similarity is secondary. The prompt explicitly prohibits inventing or using fixed matcher thresholds.

The output is resumable and saved after every pair.

## Benchmark validator
`validate_deepseek_pair_reviewer.py` compares the blind reviews with the human files only after inference.

It reports:
- full confusion matrix;
- exact agreement;
- HIGH-confidence coverage;
- HIGH-confidence exact agreement;
- direct SAME<->DIFFERENT flips;
- full mismatch list.

### Safety gate
The gate deliberately avoids an arbitrary minimum agreement threshold.

PASS requires:
- all 40 human pairs evaluated and valid;
- zero HIGH-confidence direct SAME<->DIFFERENT flips.

Agreement and confidence coverage are then inspected as usefulness metrics before DeepSeek is allowed to pre-review the current 699 matcher-AMBIGUOUS pairs.

## Intended next stage
If the benchmark is acceptable, build the 699-pair blind review pool and use DeepSeek only to prioritize human review:
- HIGH SAME / HIGH DIFFERENT: candidate pseudo-labels, audited by sampling;
- MEDIUM: human review priority;
- LOW / AMBIGUOUS: human review priority or remain unresolved.

Human and DeepSeek provenance must remain separate permanently.
