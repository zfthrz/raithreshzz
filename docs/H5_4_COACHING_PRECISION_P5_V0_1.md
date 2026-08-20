# H5.4 Coaching Precision — P5 v0.1

## Purpose

Prevent P4 constrained reselection from producing a technically authorized but
geometrically remote driver-facing anchor.

## Locality contract

P5 applies only after P4 would successfully reselect an anchor inside the
validated `track_location` turn set.

The candidate is accepted only when:

`abs(relative_offset_m) <= target_turn_span_m`

where `target_turn_span_m = turn_end_m - turn_start_m` comes directly from the
validated track profile.

This is deliberately geometry-derived rather than a fixed global metre
threshold.

## Outcomes

- `RESELECTED_WITHIN_LOCATION`: candidate is both turn-coherent and local.
- `WITHHELD_NONLOCAL_RESELECTION`: candidate is in an authorized turn but is
  farther from its anchor than the validated span of that turn.
- Existing P2.1 fail-closed behavior remains when no constrained candidate can
  be resolved.

## Non-goals

No changes to detectors, thresholds, ranking, action direction/magnitude,
session coaching authority, historical coaching, LLM prompts, or normal
unconstrained P1/P2 anchors.

## Regression target

The real Imola Tamburello cue (~89 m before T2, whose validated T2 span is about
90 m) remains accepted, while a synthetic ~500 m-before-T2 reselection against
a 120 m turn span is withheld.
