# H5.4 Coaching Precision — P9 v0.1

## Deterministic cross-zone driver-plan diversity

P9 v0.1 implements **deterministic presentation-order diversity** for the
`next_stint_plan` cross-zone driver plan.  It improves the presentation so that
repeated cue families do not dominate, without changing H5.2 ranking/selection
authority.

## Scope

- `coaching_precision.py` only (action-family derivation, presentation ordering,
  metadata enrichment).
- No changes to detectors, thresholds, H5.2 episode/zone ranking, LLM authority,
  action authorization, or P1–P8 behavior.
- Backends inherit via the existing `enrich_plan_with_p9_presentation_metadata`
  call at the end of `analyze_session_coaching_facts`.

## Closed action families

| Family | Description |
|--------|-------------|
| `BRAKE_THROTTLE_SEQUENCE` | Combined spatial sequence (onset + release) |
| `BRAKE_TIMING` | Spatial point brake |
| `BRAKE_PROFILE` | Reference action profile brake |
| `THROTTLE_TIMING` | Spatial point throttle |
| `THROTTLE_PROFILE` | Reference action profile throttle |
| `STEERING` | Steering cue (P8-authorized) |
| `OTHER_AUTHORIZED` | Catch-all for unrecognized, no-authorized-cue, or mixed-channel cues |

## Cue-kind-to-family mapping

| Kind | Channel | Family |
|------|---------|--------|
| `combined_spatial_sequence` | brake+throttle | BRAKE_THROTTLE_SEQUENCE |
| `spatial_points` | brake | BRAKE_TIMING |
| `spatial_points` | throttle | THROTTLE_TIMING |
| `reference_action_profile` | brake | BRAKE_PROFILE |
| `reference_action_profile` | throttle | THROTTLE_PROFILE |
| `qualitative_reference_level` | brake | BRAKE_PROFILE |
| `qualitative_reference_level` | throttle | THROTTLE_PROFILE |
| `qualitative_reference_level` | mixed | OTHER_AUTHORIZED |
| `validated_llm_steering` | steering_magnitude | STEERING |
| (any) | (any) | OTHER_AUTHORIZED |

Rules:
- Speed is context only and never creates an action family.
- Steering only if already authorized by P8.

## Presentation ordering

For each plan item:
1. Derive `primary_action_family` from P8 `driver_cues[0]`.
2. Fail closed (OTHER_AUTHORIZED) if no authorized cue.
3. Preserve original H5.2 order for the **first occurrence** of each family.
4. Place repeated families afterward, preserving their relative order.
5. No-authorized-cue items must not displace authorized items.

### Example

Input plan order (families):
```
[THROTTLE_TIMING, THROTTLE_TIMING, BRAKE_TIMING]
```
Presentation order:
```
[THROTTLE_TIMING, BRAKE_TIMING, THROTTLE_TIMING]
```

Metadata added to each item:
```json
{
  "primary_action_family": "THROTTLE_TIMING",
  "original_plan_rank": 0,
  "presentation_rank": 0,
  "redundancy_status": "FIRST_OCCURRENCE"
}
```

## Rules

### Rule R1 — Closed action families

The seven closed action families are exhaustive.  No time_loss, magnitude, or LLM
score may affect presentation order.

### Rule R2 — Deterministic presentation order

First occurrence of each family preserves original H5.2 order; repeated families
come afterward.  Order is deterministic and stable across repeated calls.

### Rule R3 — No-displace rule

Items with no authorized cue (OTHER_AUTHORIZED) must not displace authorized
items in the presentation order.

### Rule R4 — Fail-closed

Missing or empty driver_cues fail closed to OTHER_AUTHORIZED.  No cue in the
plan should cause P9 to invent a family.

### Rule R5 — Speed remains context

Speed is never a cue kind in P8, so it never creates an action family.

### Rule R6 — Steering only if authorized

Steering only if already authorized by P8 as `validated_llm_steering`.

### Rule R7 — Preserve H5.2 ranks

P9 adds metadata without overwriting H5.2 ranks.  The authoritative plan
ordering is unchanged; P9 provides a derived presentation-order view.

### Rule R8 — Backend parity

All active backends (`llm_analysis.py`, `llm_analysis_deepseek.py`,
`llm_analysis_ingenierov3.py`, `llm_analysis_llamacpp.py`) must import
`enrich_plan_with_p9_presentation_metadata` and call it on
`next_stint_plan`.

## Integration

P9 is wired into the active backends as a call to
`enrich_plan_with_p9_presentation_metadata(next_stint_plan)` immediately after
the P8 enrichment.

## No-change guarantees

- **H5.2**: episode ranking, zone selection, and selection authority are
  unchanged.
- **P1–P8**: coaching sequence generation, precision anchors, track reference,
  steering validation, and cue priority are unchanged.
- **max_cues=2**: P9 applies after the cue list is built, so the two-cue limit
  is preserved.
- **Validators**: P9 is additive; it adds `_p9_presentation_metadata` to each
  plan item.  It never modifies existing fields.
- **Action authorization**: P9 never alters `historical_actions_authorized`.

## Tests

Regression tests in `tests/test_coaching_precision.py` cover:

| Test | Rule |
|------|------|
| A) repeated throttle + brake diversity | R2 |
| B) all unique unchanged | R2 |
| C) all same unchanged | R2 |
| D) combined sequence classification | R1 |
| E) profile vs timing classification | R1 |
| F) no-cue fail closed | R4 |
| G) speed cannot create family | R5 |
| H) H5.2 ranks unchanged | R7 |
| I) deterministic repeated result | R2 |
| J) backend parity | R8 |

## Added schema

Each plan item receives a `_p9_presentation_metadata` dict:

```json
{
  "primary_action_family": "THROTTLE_TIMING",
  "original_plan_rank": 0,
  "presentation_rank": 0,
  "redundancy_status": "FIRST_OCCURRENCE"
}
```

Where:
- `primary_action_family`: the closed action family derived from P8 driver_cues[0]
- `original_plan_rank`: the original H5.2 index of this plan item
- `presentation_rank`: the presentation-order index after diversity ordering
- `redundancy_status`: FIRST_OCCURRENCE or REPEATED_FAMILY
