# H5.2 multitrack validation v0.1

Date: 2026-08-15

## Scope

This checkpoint exercises the same H5.2 raw comparison and controlled historical
LLM narrative on four real track/session pairs. Runtime JSON, raw telemetry and LLM
debug attempts remain local under ignored paths; this note preserves the validation
result without tracking generated artifacts.

Contracts exercised:

- raw cross-session comparison `0.1`, schema `1.0`;
- historical LLM narrative `0.1`, schema `1.0`;
- backend/model: DeepSeek `deepseek-v4-pro`;
- maximum selected zones: 3;
- LLM free text: disabled;
- historical coaching: disabled.

## Results

| Track | Historical reference | Current reference | Current - historical | Raw zones | Selected zones | Raw validator | Narrative validator |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fuji Speedway | session 7 lap 8, `90.980 s` | session 8 lap 5, `92.260 s` | `+1.280 s` | 7 | 3 | `PASS` | `PASS` |
| Autodromo Enzo e Dino Ferrari | session 9 lap 4, `93.660 s` | session 10 lap 4, `94.260 s` | `+0.600 s` | 3 | 3 | `PASS` | `PASS` |
| Autódromo José Carlos Pace | session 11 lap 7, `87.320 s` | session 12 lap 13, `87.140 s` | `-0.180 s` | 4 | 3 | `PASS` | `PASS` |
| Autodromo Nazionale Monza | session 14 lap 1, `99.140 s` | session 16 lap 8, `98.020 s` | `-1.120 s` | 5 | 3 | `PASS` | `PASS` |

Fuji additionally passed the orchestrator reuse path with H5.2 reported as
`REUSED`.

## Coverage demonstrated

- four distinct real circuits;
- positive and negative `current_minus_historical` lap deltas;
- different raw zone counts;
- deterministic selection restricted to existing zone IDs;
- exact evidence copied from Python-owned H5.2 output;
- accented Windows paths accepted on Interlagos;
- exact vehicle/context isolation rejected a Monza Hypercar-to-LMP2_ELMS candidate and accepted two Toyota Hypercar sessions;
- no free-text observations, causal claims or driving instructions.

## Authority invariant

Every output preserved:

```text
session_reference_remains_authority = true
historical_actions_authorized = false
```

The result supports using H5.2 as validated observational context. It does not
authorize promotion of the historical reference to current-session coaching truth,
nor does it make the context gates less strict.

## Repository validation checkpoint

```text
pytest:                         71 PASS / 0 FAIL / 0 SKIP
Objective Python regressions:  55 PASS / 0 FAIL / 0 SKIP
Objective recovery check:      READY
```
