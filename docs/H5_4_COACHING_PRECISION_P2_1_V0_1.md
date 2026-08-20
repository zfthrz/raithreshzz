# H5.4 Coaching Precision — P2.1

## Purpose

Fail closed when a driver-facing relative anchor points to a different corner
than the validated `track_location` of the selected plan item.

## Contract

- Absolute LMU distance remains unchanged and authoritative.
- Reference/supporting laps and observed delta remain available even when an
  anchor is withheld.
- `track_location.overlaps[]` is the primary deterministic source for allowed
  turn ids; the existing validated label is only a fallback when overlaps do
  not identify a turn.
- If `anchor_turn` is outside the plan item's allowed turns,
  `corner_relative_reference` is suppressed.
- The reason is recorded in `anchor_coherence.status` as
  `WITHHELD_LOCATION_MISMATCH`.
- No detector, ranking, magnitude, threshold, historical action policy, or LLM
  authority changes.

## Regression case

Imola P 2026-08-13T23:25:02Z exposed a Zone A cue labeled
`T2–T3 — Variante Tamburello` whose P2 relative anchor resolved to T1. P2.1
must retain the lap-support/delta evidence for that cue but omit the T1 relative
reference. Zones with coherent anchors (for example Rivazza 1 / T17) remain
unchanged.
