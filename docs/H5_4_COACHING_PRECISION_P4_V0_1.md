# H5.4 Coaching Precision — P4 v0.1

## Purpose

Recover a coherent deterministic corner-relative anchor when the unconstrained
P2/P2.1 selector points outside the validated `track_location`.

## Contract

- Absolute detector coordinate remains authoritative and unchanged.
- Existing unconstrained selection runs first.
- Reselection is attempted only after `WITHHELD_LOCATION_MISMATCH`.
- Candidate turns are restricted to `_location_turns(expected_location)`.
- The same event policy is preserved:
  - braking onset -> turn start;
  - brake/throttle release and throttle onset -> apex.
- If no allowed turn exists in the validated profile, retain P2.1 fail-closed
  behavior and suppress the relative anchor.
- Successful recovery records
  `anchor_coherence.status = RESELECTED_WITHIN_LOCATION`.
- No detector, threshold, ranking, direction, magnitude, historical action
  policy, coaching authority, or LLM prompt changes.

## Regression target

The Imola Tamburello case that previously produced a T1 anchor for a T2-T3
driver-facing region should be eligible for deterministic reselection inside the
authorized turn set instead of immediately suppressing the relative reference.
