# Project Status

## Current integration checkpoint

### analyze_telemetry
Current: `3.8`

Primary objective unit:
`driver_action_episode`

Speed does not merge driver actions.

### llm_analysis
Current: `3.10.8.5.4`

Contract:
- structured JSON only
- all episode IDs required
- qualitative text cannot contain numbers
- Python owns ground truth and final rendering
- invalid LLM response is rejected

### history
Current: `session_history v1.4 / schema 4`

Implemented:
- DuckDB schema
- idempotent SHA-256 imports
- session/comparison/episode/channel storage
- normalized lap fractions
- batch import
- stats

### historical layers

Implemented:
- H2 matcher `0.3`, provisional and context-limited
- H3 persistent pattern builder `0.1`, calibration-derived
- H4 historical reference selector `0.2`
- H5.1 dual reference context `0.2`
- H5.2 raw cross-session comparison `0.1`
- H5.2 validated observational LLM narrative `0.1`

H5.2 resolves both raw DuckDBs through History, applies exact context gates, compares
independent historical/current `LapAnalyzer` sources, validates the temporal delta and
emits observational spatial zone summaries.

Real multitrack checkpoint:

| Track | Historical reference | Current reference | Current - historical | Raw zones | LLM-selected zones | Validators |
|---|---:|---:|---:|---:|---:|---:|
| Fuji | session 7 lap 8, `90.980 s` | session 8 lap 5, `92.260 s` | `+1.280 s` | 7 | 3 | `PASS` |
| Imola | session 9 lap 4, `93.660 s` | session 10 lap 4, `94.260 s` | `+0.600 s` | 3 | 3 | `PASS` |
| Interlagos | session 11 lap 7, `87.320 s` | session 12 lap 13, `87.140 s` | `-0.180 s` | 4 | 3 | `PASS` |
| Monza | session 14 lap 1, `99.140 s` | session 16 lap 8, `98.020 s` | `-1.120 s` | 5 | 3 | `PASS` |

Fuji also completed an orchestrator reuse check with H5.2 `REUSED`. The four
historical narratives use DeepSeek `deepseek-v4-pro`, disable free text and keep
historical coaching disabled. See `docs/H5_2_MULTITRACK_VALIDATION_V0_1.md`.

The H5.2 LLM contract can select up to three validated spatial zones and only the
observation codes authorized by Python for each zone. LLM free text is disabled;
Python owns the complete rendering. The validator rejects invented zones, extra
fields, unauthorized codes and evidence tampering.
Historical actions remain disabled and `session_reference` remains coaching authority.

Debrief actionability:
- session priority policy `1.9` ranks repeated physical points by their own
  cross-comparison support before the broader recurrence of the enclosing region;
- the rule is channel-neutral and does not hard-code brake over throttle;
- on the real Imola audit, the brake point supported in 3 comparisons ranks ahead
  of the throttle point supported in 2, despite the throttle region appearing in 5.
- actionability policy `1.5` converts only known throttle profile shapes into clear,
  ordered driver actions and preserves a descriptive fallback for unknown shapes.

Validation:
- pytest: `72 PASS / 0 FAIL / 0 SKIP`
- Objective Python regressions: `55 PASS / 0 FAIL / 0 SKIP`
- Objective recovery check: `READY`

## Mandatory gates

### Gate A
Keep both raw DuckDBs and exact track/layout/vehicle/car compatibility.

### Gate B
Require H4 selection plus H5.1 dual-reference context.

### Gate C
Require H5.2 temporal validation and its structural validator.

### Gate D
Require the dedicated H5.2 LLM validator before historical evidence can alter observational wording. Historical evidence cannot authorize coaching actions.

Do not let `historical_reference` silently replace the current session reference.
