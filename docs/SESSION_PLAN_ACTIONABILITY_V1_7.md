# Session-plan actionability v1.7

## Problem

A physical throttle onset/release can be fully authorized while its reference profile
contains several additional actions. Rendering both in one sentence made a valid cue
harder to execute than a comparable brake point.

The issue concerns presentation complexity, not evidence validity and not an inherent
preference for brake over throttle.

## Shadow checkpoint

`audit_session_plan_actionability.py` inspected four real DeepSeek Pro artifacts:
one Imola session and three Monza sessions. Three passed the current validator; one
older artifact was accepted only as `STALE_RENDER_ONLY` because its sole error was
global-render drift.

Across 12 priority zones:

| Primary channel | Count |
|---|---:|
| Brake | 7 |
| Throttle | 5 |

Primary directness classes:

| Class | Count |
|---|---:|
| Single physical point | 5 |
| Multiple physical points | 2 |
| Physical point with reference sequence | 3 |
| Qualitative alignment | 1 |
| Reference sequence only | 1 |

The sample shows that throttle cues were structurally more varied. It does not show
systematic displacement of brake cues and does not authorize a channel preference or
a numeric complexity score.

## Policy 1.7

When a throttle item contains an authorized physical point plus a known reference
profile:

1. the physical point becomes the concise primary cue;
2. the reference sequence becomes a separate secondary cue when the two-cue limit
   permits it;
3. profile-only items still render their ordered driver-facing sequence;
4. unknown shape labels retain the conservative descriptive fallback;
5. session ranking and evidence gates remain unchanged.

## Real deterministic rerender

The current Monza LMP2_ELMS Pro result was rerendered without an LLM call. The A/B/C
order was preserved:

- A, Lesmo 1: brake point primary; throttle release secondary;
- B, Variante Ascari: throttle reapplication point primary; sustained reference
  sequence secondary;
- C, Curva Alboreto: brake release primary; ordered throttle sequence secondary.

The preview reported `llm_called=false`, validator errors `0` and `RESULT: PASS`.

## Deterministic rerender utility

`rerender_llm_analysis_output.py` rebuilds only presentation-owned deterministic
fields from a saved valid result. It does not call a model, does not modify the source
by default, records the source SHA-256 and validates the new output completely.

Generated previews and actionability audit JSONs remain under `data/generated/` and
are not repository artifacts.
