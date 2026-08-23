# H5.3 action review round 4 — whole-lap current_faster

Date: 2026-08-22

## Purpose

Review the real `current_faster` anti-regression branch after correcting the source
of its sign, without changing production coaching authority.

## Correct contract

The sign used by the action policy describes the complete current lap relative to
the historical lap. It must come from validated H5.3a `total_delta`, not from each
zone's local delta. A globally faster lap can still contain locally slower zones.

The two pieces of evidence therefore have different jobs:

- positive local `delta_change_s > 0.08 s` determines whether a loss zone is eligible;
- whole-lap `delta_sign` controls the conservative anti-regression policy.

The policy currently retains every selected zone when the whole lap is
`current_faster`. Local time gains remain ineligible; no absolute-value ranking is
used.

## Deterministic replay

All seven available real H5.3 artifacts were replayed with the corrected contract.
No LLM was called. The key reproduction was Interlagos:

```text
Whole-lap current minus historical: -0.180 s
Whole-lap sign: current_faster
Selected local-loss zones: 3
Generated actions: 0
Withheld: 3
Reason: current_lap_faster_no_actions
```

Fuji also contributed real `current_faster` withheld evidence. One Monza session
correctly returned `SKIPPED_NOT_APPLICABLE` because it had no eligible local loss.

## Safe migration and review

Queue v4 was rebuilt from the seven validated artifacts. Migration compared both
`review_id` and the complete item snapshot:

```text
Review items: 20
Source occurrences: 21
Preserved labels: 11
Dropped changed labels: 7
New pending items: 9
```

The reviewer completed all nine new cases:

| Human label | Count |
|---|---:|
| `ACTION_USEFUL` | 12 |
| `CORRECTLY_WITHHELD` | 3 |
| `WITHHELD_BUT_ACTIONABLE` | 1 |
| `AMBIGUOUS` | 4 |

The actionable-withheld label records an important product distinction: a lap being
globally faster does not mean it is best in every zone. A clear local loss may still
deserve coaching. The four ambiguous labels also showed that observation codes alone
were insufficient for confident human review.

## Review-tool improvement

Future queues preserve the Python-owned local delta and available mean channel
deltas for every occurrence, including withheld cases. The interactive labeler shows
those values as `current - historical`. This improves human judgment only; it does
not change action policy, thresholds, validators or debrief rendering.

## H5.3f v0.2 verdict

```text
Verdict: EVIDENCE_INCOMPLETE
Non-affirmative labels: 5
Missing isolated actions: increase_brake, reduce_brake
Authority: SHADOW ONLY
```

The global-sign correctness defect is closed, but promotion is not ready. The next
policy experiment should determine when locally actionable losses can safely pass a
whole-lap-faster guard, using richer physical evidence and separate shadow review.
Historical actions remain unauthorized.

## Verification

```text
Focused review/pipeline tests: 104 passed
Full pytest: 1012 passed
git diff --check: PASS
Real deterministic replays: PASS / expected Monza skip preserved
Review-label validator: PASS
H5.3f v0.2 assessment: PASS / EVIDENCE_INCOMPLETE
```
