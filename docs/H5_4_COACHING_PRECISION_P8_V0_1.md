# H5.4 Coaching Precision — P8 v0.1

## Deterministic driver-facing cue priority

P8 v0.1 implements **deterministic priority ordering** for the driver-facing cues
produced by `build_driver_cues_for_plan_item`.  This prevents the LLM backend from
accidentally placing a steering observation above a brake/throttle physical cue or
duplicating evidence that a combined_spatial_sequence already represents.

## Scope

- `coaching_precision.py` only (helper logic for priority classes, suppression,
  deduplication, and enrichment).
- No changes to detectors, thresholds, H5.2 episode/zone ranking, LLM authority,
  action authorization, or `max_cues=2`.
- Backends inherit via the existing `enrich_cues_with_deterministic_priority` call
  at the end of `build_driver_cues_for_plan_item`.

## Rules

### Rule R1 — Priority classes

| Rank | Kind                           |
|------|--------------------------------|
| 1    | combined_spatial_sequence      |
| 2    | spatial_points                 |
| 3    | reference_action_profile       |
| 4    | qualitative_reference_level    |
| 5    | validated_llm_steering         |

Unrecognized kinds sink to the bottom (rank 999).

### Rule R2 — Combined sequence suppresses component spatial cues

When `combined_spatial_sequence` exists, component `spatial_points` cues that share
a brake or throttle channel are suppressed and must not appear alongside it.

### Rule R3 — Independent spatial cues ordered by event_distance_m

Independent spatial cues (rank 2) are sorted by their physical
`event_distance_m`, not by hard-coded brake-before-throttle channel order.

### Rule R4 — Steering cannot displace physical evidence

Rank-5 steering is sorted after rank-2 spatial and rank-3 reference profiles, so it
can never displace physical brake/throttle evidence.

### Rule R5 — Deduplication

Beyond the first occurrence, duplicate cue kinds are suppressed.  This is applied
after R2 suppression and before priority sorting.

### Rule R6 — Fail-closed

Missing or invalid priority metadata must not invent distance, phase, action,
magnitude, or causal meaning.

### Rule R7 — Speed remains context

Speed is never emitted as a cue kind by `build_driver_cues_for_plan_item`, so it
never enters the priority sort.

### Rule R8 — Distinct reference_action_profile

A `reference_action_profile` may fill a remaining slot only when it adds distinct
driver-facing information beyond what a spatial cue already covers.

### Rule R9 — No duplication of combined-sequence evidence

A second cue must not duplicate physical point evidence already represented by
`combined_spatial_sequence`.

## Integration

P8 is already wired into the active backends (llvm_analysis.py,
llm_analysis_deepseek.py, llm_analysis_ingenierov3.py,
llm_analysis_llamacpp.py) as a call to
`enrich_cues_with_deterministic_priority` immediately after
`build_driver_cues_for_plan_item`.

## Tests

Regression tests in `tests/test_coaching_precision.py` cover:

| Test | Rule |
|------|------|
| A) combined sequence gets slot 1 | R1 |
| B) component spatial cue is not duplicated | R2 |
| C) two independent spatial cues ordered by event_distance_m | R3 |
| D) physical cue beats reference profile | R1 |
| E) reference profile can fill slot 2 when distinct | R1 |
| F) steering cannot displace physical brake/throttle | R4 |
| G) single-cue legacy behavior unchanged | R1 |
| H) backend parity | Integration |

## No-change guarantees

- **P1–P7**: coaching sequence generation, precision anchors, track reference,
  steering validation, and qualitative reference-level cues are unchanged.
- **max_cues=2**: P8 applies after the cue list is built, so the two-cue limit
  is preserved.
- **H5.2 episode ranking**: P8 never inspects H5.2 zones.
- **Action authorization**: P8 never alters `historical_actions_authorized`.
- **Validators**: P8 is additive; it enriches the cue list and adds `_p8_priority_rank`
  metadata.  It never weakens existing validator rules.
