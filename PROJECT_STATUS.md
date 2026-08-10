# Project Status

## Frozen / current

### analyze_telemetry
Current: `3.8`

Primary objective unit:
`driver_action_episode`

Speed does not merge driver actions.

### llm_analysis
Current candidate: `3.8.2`

Contract:
- structured JSON only
- all episode IDs required
- qualitative text cannot contain numbers
- Python owns ground truth and final rendering
- invalid LLM response is rejected

### history
Current: `session_history v1.1`

Implemented:
- DuckDB schema
- idempotent SHA-256 imports
- session/comparison/episode/channel storage
- normalized lap fractions
- batch import
- stats

### historical matcher
Not implemented by design.

Available:
- neutral pair-feature extraction
- calibration specification

Blocked until real multi-session data exists.

## Mandatory gates

### Gate A
Run and validate `llm_analysis 3.8.2`.

### Gate B
Import multiple `analyze_telemetry 3.8` JSON files.

### Gate C
Validate history DB.

### Gate D
Generate cross-session pair features and manually inspect SAME / DIFFERENT / AMBIGUOUS examples.

Only then choose matching thresholds.
