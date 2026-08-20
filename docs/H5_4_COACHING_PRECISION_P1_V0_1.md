# H5.4 Coaching Precision — P1 v0.1

## Status

`IMPLEMENTED — PRESENTATION_ENRICHMENT_ONLY`

This change improves driver-facing precision without changing telemetry detectors,
comparison eligibility, ranking, coaching authority, or H5.3 production status.

## Objective

Replace opaque lap-distance-only mental references with deterministic coaching
provenance that answers:

- Which lap is the reference?
- Which compared laps support the cue?
- What range of point differences was observed?
- Where is the reference physical point relative to the named corner?

Absolute LMU lap distance remains the source coordinate and is retained in JSON.
The relative coordinate is derived presentation evidence only.

## Implemented deterministic contract

New shared module: `coaching_precision.py`.

For repeated physical-point patterns it derives:

```text
precision_evidence.version
precision_evidence.event_kind
precision_evidence.reference_lap
precision_evidence.supporting_laps[]
precision_evidence.support_count
precision_evidence.observed_delta_min_m
precision_evidence.observed_delta_max_m
precision_evidence.representative_delta_m
precision_evidence.corner_relative_reference
```

`corner_relative_reference` preserves the source event coordinate and adds:

```text
event_distance_m
anchor_turn
anchor_name
anchor_type
anchor_distance_m
relative_offset_m
relative_magnitude_m
relation
driver_label
```

## Anchor policy v0.1

The policy is deliberately narrow and deterministic:

- braking onset -> `turn_start`
- brake release -> `apex`
- throttle onset -> `apex`
- throttle release -> `apex`

If no validated track profile is active, corner-relative reference is `null` and
existing coaching behavior remains available.

Example:

```text
absolute reference brake onset: 4500 m
T1 start:                       4620 m

derived driver label:
~120 m antes de T1 — Hairpin
```

The helper never overwrites `reference_onset_m`, `reference_release_m`, or any
source detector coordinate.

## Debrief presentation

For the primary spatial cue of a plan zone, the deterministic render can now add:

```text
Referencia del cue: vuelta 1; punto de referencia ~120 m antes de T1 — Hairpin.
Evidencia entre vueltas: el mismo desvío apareció en las vueltas 2 y 3;
rango observado 31–35 m; valor representativo 33 m.
```

This complements rather than replaces the existing coaching instruction, e.g.:

```text
Qué cambiar: frená aproximadamente 33 m más temprano.
```

The first physical point in a compound cue is the primary displayed precision
anchor. Full onset/release precision evidence remains available in JSON.

## Responsibility boundary

Python owns all new fields and wording inputs. The LLM does not:

- choose the reference lap;
- choose supporting laps;
- calculate ranges;
- calculate relative corner distance;
- select the corner anchor;
- perform lap-distance arithmetic.

The LLM remains responsible only for the narrative fields already authorized by
the existing architecture.

## Files changed

- `coaching_precision.py` — new deterministic shared helper.
- `llm_analysis.py` — enrich repeated physical patterns and render precision evidence.
- `llm_analysis_ingenierov3.py` — synchronized operational alias.
- `llm_analysis_v3_10_8_5_4_ingenierov3.py` — synchronized release alias.
- `llm_analysis_llamacpp.py` — same precision integration; llama.cpp naming/header fix retained.
- `llm_analysis_v3_10_8_5_4_llamacpp.py` — synchronized release alias.
- `llm_analysis_deepseek.py` — same precision integration.
- `llm_analysis_v3_10_8_5_4_deepseek_v2.py` — synchronized release alias.
- `tests/test_coaching_precision.py` — deterministic unit/render tests.

## Verification in the supplied ZIP environment

Targeted tests:

```text
tests/test_coaching_precision.py
+ tests/test_llm_analysis_llamacpp.py
+ tests/test_deterministic_llm_rerender.py
PASS
```

Full pytest in the Linux sandbox reached:

```text
770 passed
2 skipped
3 failed
5 errors
```

The 3 failures are environment/platform-sensitive existing tests (Windows
`tasklist` behavior and Windows path separator expectation). The 5 errors require
`data/generated/h5_3/audit_dataset_full.json`, a runtime artifact absent from the
uploaded ZIP. None are in the H5.4 precision files or targeted tests.

## Next step (P2)

Run a real llama.cpp session on a track with a validated profile and at least one
repeated physical point. Review the resulting driver-facing lines for:

1. correct reference lap;
2. correct supporting laps;
3. correct relative corner anchor;
4. useful anchor choice for brake vs throttle;
5. no duplicated or overly technical wording.

Do not change anchor policy based on a synthetic example alone. Use real-session
human review before P2/P3 expansion.
