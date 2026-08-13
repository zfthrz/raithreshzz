# Race Engineer — Objective Python v6 (2026-08-13)

## Baseline

- Brake Point 2.1 / schema 2.1
- Throttle Point 1.2.1 / schema 1.2
- Throttle Episode Sequence 1.0
- Throttle Sustained Modulation 1.0
- Full Throttle Attainment Recurrence 1.0
- Throttle Modulation Recurrence 1.0
- Throttle Physical Point Profile 1.0
- Throttle Coaching Evidence Gate 1.0 (SHADOW MODE)

LLM Analysis is not modified.

## Throttle Coaching Evidence Gate 1.0

Deterministic session-level shadow gate.

It does NOT:
- change ranking;
- change next_session_priorities;
- change existing per-comparison coaching;
- activate new coaching;
- reinterpret or redetect telemetry.

Existing throttle onset/release can become
`SHADOW_AUTHORIZED_EXISTING_POINT_COACHING` only when:

1. Throttle Point 1.2.1 already produced `authorized_numeric_coaching=True`;
2. the same coaching direction is supported by at least 2 distinct comparison laps;
3. no opposite source-authorized direction is present;
4. no duplicate physical assignment conflict exists;
5. the reference event snapshot is not contradictory.

Neutral/unavailable evidence does not count as support and is not, by itself,
a contradiction.

The shadow magnitude is the median of already-authorized source magnitudes.

The following remain held out even if recurrent:
- full_throttle_attainment
- partial_lift
- sustained_throttle_modulation

Repeated evidence is marked:
`HELD_OUT_PENDING_MULTITRACK_VALIDATION`

These still have:
- shadow_authorized = false
- activates_coaching = false
- affects_ranking = false
- affects_session_priority = false

## Install from Objective Python v5

```bash
unzip -o race_engineer_throttle_coaching_evidence_gate_v1_0_hotfix.zip
python ./apply_objective_python_recovery_2026_08_13.py ./analyze_telemetry.py
python ./run_race_engineer_regressions.py --analyzer ./analyze_telemetry.py
```

Expected:

```text
Throttle Coaching Evidence Gate: 1.0 / SHADOW
RACE ENGINEER PYTHON REGRESSION SUITE v1.5
RESULT: 55 PASS / 0 FAIL / 0 SKIP
```

## Validation performed

- Objective Python v5 -> v6: 55 PASS / 0 FAIL / 0 SKIP
- clean analyze_telemetry v3.8 -> v6: 55 PASS / 0 FAIL / 0 SKIP
- second recovery application: already expected state
