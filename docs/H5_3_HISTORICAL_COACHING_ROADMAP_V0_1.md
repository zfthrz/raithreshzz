# H5.3 historical coaching debrief roadmap v0.1

## Status

```text
Objective: H5.3 historical coaching debrief
Status: ROADMAP_ONLY
Implementation: H5_3F_PROMOTION_GATE / EVIDENCE_READY
Production authority: NONE
historical_actions_authorized: false
session_reference_remains_authority: true
```

This document defines a future compatible implementation path. Its presence does not
authorize historical coaching or change any current output.

## Product goal

Produce a separate debrief-style comparison between:

- the fastest valid reference lap of the current session; and
- the fastest H4-selected compatible historical reference lap.

The output should help the driver understand the gap to a previously demonstrated
personal performance level. It must not replace the normal current-session debrief,
which remains the primary next-stint coaching authority.

Conceptual presentation:

```text
CURRENT-SESSION DEBRIEF
Reference: fastest valid lap in this session
Authority: primary coaching

HISTORICAL COMPARISON DEBRIEF
Current reference:    1:39.280
Historical reference: 1:37.500
Observed gap:          +1.780 s
Authority: secondary and conditional
```

## Existing foundation

H5.3 must reuse, not duplicate:

- H4 exact historical-reference selection and eligibility gates;
- H5.1 dual-reference identity and authority separation;
- H5.2 raw two-DuckDB comparison, temporal validation and profile localization;
- deterministic brake/throttle physical points and reference action profiles;
- current validators and explicit orchestrator stage statuses.

The LLM must never open raw DuckDBs, recalculate telemetry facts or infer an action
from prose.

## Compatibility contract

H5.3 must be additive:

1. Keep all current H4/H5.1/H5.2 schemas valid.
2. Do not mutate the normal LLM debrief or its A/B/C priority order.
3. Store new runtime artifacts below `data/generated/h5_3/`.
4. Use a new explicit schema/version and dedicated validator.
5. Return `SKIPPED_NOT_APPLICABLE` when prerequisites are absent.
6. Preserve `historical_actions_authorized=false` until an explicit later promotion.
7. Never use setup, fuel, tyres, grip, balance or weather details that Python has not
   modeled and authorized.
8. Treat a current lap faster than the historical reference as valid evidence; never
   turn it into an instruction to become slower or copy the historical lap.

## Staged implementation

### H5.3a — deterministic shadow candidates

Build a new Python-owned artifact from validated H4/H5.1/H5.2 inputs. Candidate
records may contain only existing authorized evidence, for example:

- exact localized zone identity;
- current-minus-historical time contribution;
- physical brake/throttle onset or release relationships;
- reference action-profile relationships;
- evidence availability and comparability limitations;
- source artifact paths, hashes and versions.

Output status remains `SHADOW_OBSERVATIONAL_ONLY`. Do not render driver instructions,
call an LLM or change production selection.

### H5.3b — offline audit and human review

Create a reproducible audit dataset across multiple tracks and both signs of lap-time
delta. Review whether each candidate is:

```text
ACTIONABLE
OBSERVATIONAL_ONLY
NOT_COMPARABLE
AMBIGUOUS
```

Human review is stronger ground truth than model opinion. No threshold becomes a
production rule from a single track, vehicle or session pair.

### H5.3c — controlled LLM selection

Only after H5.3a/b evidence is adequate, allow the LLM to select from Python-issued
candidate IDs and closed observation/action codes. Initially keep free text disabled.
The model may prioritize authorized candidates but may not create measurements,
causes, targets or new actions.

Real H5.3c checkpoint (2026-08-17): on the real Imola/Monza audit dataset (26
candidates, 6 ACTIONABLE), DeepSeek `deepseek-v4-pro` selected three candidates
(T6 Villeneuve primary, T15 Gresini secondary, T2 Tamburello context). The dedicated
validator passed with zero errors; the render is Python-owned and no historical
action was authorized.
A later full-dataset run (55 candidates, 16 ACTIONABLE across the four tracks)
selected T6 Villeneuve, the pre-T1 segment at Fuji and T1 do Senna at Interlagos,
and also passed the dedicated validator with zero errors.

### H5.3d — deterministic separate renderer

Python renders a distinct historical section. It must clearly label:

- current and historical lap times;
- total observed delta;
- comparable zones;
- evidence limitations;
- whether each item is observational or action-authorized.

The normal session debrief remains present and unchanged.

### H5.3e — validator and safe fallback

A dedicated validator must reject:

- altered H4/H5.1 identities;
- invented or missing source zones;
- unauthorized measurements or codes;
- actions without a Python authorization record;
- causal setup/tyre/grip/balance claims without modeled evidence;
- replacement or mutation of current-session coaching authority;
- unknown keys or evidence-hash mismatches.

When validation fails, retain the valid normal debrief and either fall back to a
deterministic observational historical summary or mark H5.3 `FAILED`. Never weaken
the validator.

### H5.3f — multitrack promotion gate

Before any production action authorization, validate independent real pairs on at
least the existing Fuji, Imola, Interlagos and Monza contexts, including:

- current slower than historical;
- current faster than historical;
- unavailable raw telemetry;
- missing or invalid track profile;
- incompatible vehicle/layout/weather rejected by H4;
- different setups recorded as observations rather than assumed causes.

Promotion requires documented human review and zero unsafe authority changes.

Real H5.3f checkpoint (2026-08-17): with regenerated H5.2 v0.2 for Fuji and
Interlagos, a 55-candidate audit across the four tracks (16 ACTIONABLE), a validated
DeepSeek `deepseek-v4-pro` selection (3 of 16) and documented human review, the gate
returned `PROMOTION_READY` with zero unmet requirements. Production authority
remains `NONE` and `historical_actions_authorized=false`; enabling production
historical coaching still requires an explicit decision and orchestrator integration.

## Initial hard prerequisites

H5.3 processing is applicable only when:

```text
H4 = HISTORICAL_REFERENCE_SELECTED
H5.1 = dual reference valid
H5.2 raw validator = PASS
exact track/layout/vehicle/car gate = PASS
current and historical raw laps = resolvable
temporal validation = PASS
```

For the first H5.3a slice, lack of an exact validated track profile should withhold
localized action candidates. It may produce an explicit limitation, but must not
guess a corner or action location.

## First real development fixture

Use the confirmed Monza `LMP2_ELMS` pair as an initial fixture, not as sufficient
promotion evidence:

```text
target History session:      23
current reference:           lap 3 / 99.280 s
historical History session:  19
historical reference:        lap 10 / 97.500 s
historical advantage:        1.780 s
vehicle:                     IDEC Sport #18:ELMS25
H4 status:                   HISTORICAL_REFERENCE_SELECTED
```

The implementation must also test a pair where the current lap is faster than the
historical reference before interpreting ranking or wording as general.

## Acceptance criteria for H5.3a

- New artifact is deterministic and byte-stable for the same inputs.
- Every candidate traces to validated source evidence and hashes.
- No LLM is called.
- No driver action or coaching sentence is produced.
- Existing H4/H5.1/H5.2 outputs remain unchanged.
- Existing normal debrief output remains unchanged.
- Incompatible or incomplete context yields an explicit skip/limitation.
- Unit tests cover positive, negative, missing-data and tampered-input cases.
- Full pytest, Objective Python regressions and relevant validators pass.
- Documentation records actual evidence rather than anticipated results.

## Explicit non-goals for the first slice

- no production historical coaching;
- no replacement of the current-session reference;
- no LLM free text;
- no universal zone-ranking formula;
- no setup/tyre/fuel causal attribution;
- no matcher/H3 redesign;
- no change to current H5.2 model benchmark conclusions.

## Recommended first coding task

Implement and test only a proposed function or script such as:

```text
build_historical_coaching_candidates.py
```

It should consume validated H5.1 and H5.2 JSON, emit a versioned shadow artifact and
stop. Do not integrate it into the normal orchestrator until its standalone contract,
tests and validator expectations are reviewed.
