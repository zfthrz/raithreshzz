# H5.3 production-readiness review — 2026-08-22

## Decision

```text
Production historical actions: KEEP SHADOW
historical_actions_authorized: false
session_reference_remains_authority: true
```

The H5.3 pipeline is technically mature enough to continue controlled shadow
evaluation. It is not yet supported by enough human-reviewed action evidence to
show historical instructions to the driver as production coaching.

## Evidence checked

- H5.3f structural gate: `PROMOTION_READY`.
- Coverage represented by that gate: four required tracks and both delta signs.
- Deterministic historical sections: 7/7 passed
  `validate_historical_debrief.py`.
- Runtime shadow action artifacts: 6/6 passed
  `validate_historical_actions.py` after aligning the validator with the existing
  `insufficient_action_context` policy reason.
- Runtime shadow output sample: 16 action candidates and 2 withheld candidates;
  both withheld cases use `insufficient_action_context`.
- Deduplicated action-review queue: 15 review items from 18 source occurrences
  (13 authorized shadow-action shapes and 2 withheld shapes). These cover Imola,
  Fuji and Interlagos; the current runtime action artifacts do not cover Monza.
- Full repository suite after the review-queue slice: 990 passed.
- Authority in every inspected action artifact remained false.

No generated artifact was changed or regenerated during this review.

## Defect corrected during the review

The deterministic producer already emitted the documented reason
`insufficient_action_context`, but the validator maintained a separate older list
that omitted it. This caused two valid real artifacts to fail validation.

The closed reason vocabulary now lives beside the producer and is imported by the
validator. A regression test validates an actual producer output containing that
reason. This is contract alignment only; it does not authorize an action or relax
any evidence rule.

## Why `PROMOTION_READY` is not production authorization

The v0.1 promotion gate checks required tracks, delta signs, special scenarios and
boolean validation flags recorded in a manifest. It does not measure whether the
closed actions are consistently useful to a driver, nor does it require independent
human review of each action direction and context.

The documented human review contains nine candidates from one Imola session:
eight accepted and one rejected. That rejection supports the specific rule that
isolated `current_throttle_higher` is insufficient context. It does not support a
general rule for every isolated throttle/brake direction. Documentation claiming
the broader rule was corrected to match the implemented and reviewed contract.

## Remaining blockers

1. Review the existing real action candidates from Fuji and Interlagos, not only
   Imola, and obtain a valid Monza runtime action artifact before claiming four-track
   action-review coverage.
2. Cover each isolated action direction and representative mixed-channel cases.
3. Record whether the proposed instruction is useful, merely observational,
   ambiguous or unsafe in its exact historical context.
4. Upgrade the promotion assessment so it consumes current validated artifacts and
   explicit review-coverage counts rather than trusting manifest booleans alone.
5. Define the additive user-facing presentation and fallback before any authority
   flag changes. The current-session H5.1 debrief must remain visible and primary.

## Recommended next slice

The first part is now implemented by `prepare_h5_3_action_review_queue.py`: it builds
a read-only queue from the existing validated shadow outputs, groups semantically
equivalent candidates and preserves every source occurrence. Human labels remain a
separate future artifact. Do not alter action policy thresholds or production
rendering in this slice.

Only after that review passes should the project revisit a narrowly scoped,
explicit production integration decision.
