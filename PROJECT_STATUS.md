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

H5.2 resolves both raw DuckDBs through History, applies exact context gates, compares
independent historical/current `LapAnalyzer` sources, validates the temporal delta and
emits observational spatial zone summaries.

Real checkpoint:
- Fuji historical session 7 lap 8: `90.980 s`
- Fuji current session 8 lap 5: `92.260 s`
- current minus historical: `+1.280 s`
- temporal validation: `PASS`
- spatial zone summaries: `7`
- second orchestrator run: H5.2 `REUSED`

H5.2 historical actions remain disabled. LLM prompt/output/validator integration is the
next development block; `session_reference` remains coaching authority.

Validation:
- pytest: `58 PASS / 0 FAIL / 0 SKIP`
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
Define a dedicated LLM authorization contract before historical evidence can alter wording or coaching.

Do not let `historical_reference` silently replace the current session reference.
