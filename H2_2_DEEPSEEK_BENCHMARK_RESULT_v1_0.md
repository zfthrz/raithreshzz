# H2.2 DeepSeek benchmark result v1.0

## Input
- 40 blind pairs
- Human ground truth: 13 SAME, 19 DIFFERENT, 8 AMBIGUOUS
- Model: deepseek-v4-pro, temperature 0

## Reviewer schema issue
Original run produced 33 VALID and 7 INVALID. All seven INVALID rows failed only because `decisive_evidence` contained more than four items. Their label/confidence/reason content was otherwise structurally usable.

A deterministic schema-only repair truncates `decisive_evidence` to the first four items. It does not change label, confidence, reason codes (unless over schema maximum), or semantic reasoning.

## Repaired benchmark metrics
- Evaluated: 40/40
- Exact agreement: 32/40 = 80.0%
- HIGH-confidence coverage: 28/40 = 70.0%
- HIGH-confidence exact agreement: 26/28 = 92.9%
- Direct SAME<->DIFFERENT flips: 1
- HIGH-confidence direct SAME<->DIFFERENT flips: 0
- Safety gate: PASS

### Confusion matrix
| Human | DeepSeek SAME | DeepSeek DIFFERENT | DeepSeek AMBIGUOUS |
|---|---:|---:|---:|
| SAME | 9 | 1 | 3 |
| DIFFERENT | 0 | 19 | 0 |
| AMBIGUOUS | 2 | 2 | 4 |

## Interpretation
DeepSeek is acceptable as an assisted pre-reviewer, not as automatic ground truth. It is especially strong on clear DIFFERENT cases (19/19). The remaining errors concentrate around human boundary semantics. Two human AMBIGUOUS cases were called HIGH DIFFERENT, so HIGH confidence must not be promoted directly to human labels.

Recommended next stage: run blind review over the current matcher AMBIGUOUS pool, then use DeepSeek labels/confidence only to stratify a smaller human-review queue. Preserve human and model provenance separately.
