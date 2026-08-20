# H5.3 Human Review Round 1 — v0.1

## Status

```text
Review: H5.3 Human Review Round 1
Reviewed candidates: 9
Accepted: 8
Rejected: 1
Policy correction: v0.2 (insufficient_action_context rule)
Replay: CLEAN_AUTHORIZED=8, CLEAN_WITHHELD=1, selector_invalid=0, policy_invalid=0
Production authority: NONE
historical_actions_authorized: false
session_reference_remains_authority: true
```

## Human review result

**ACCEPTED: 8**
**REJECTED: 1**

| # | Circuit | Candidate | Observation codes | v0.1 action | Human verdict |
|---|---------|-----------|-------------------|-------------|---------------|
| 1 | Imola | T5 Villeneuve | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_lower` | `reduce_throttle`, `increase_brake` | ACCEPTED |
| 2 | Imola | T12 Acque Minerali | `time_loss`, `current_speed_lower`, `current_throttle_lower`, `current_brake_higher` | `increase_throttle`, `reducir freno` | ACCEPTED |
| 3 | Imola | T13 Acque Minerali | `time_loss`, `current_speed_lower`, `current_throttle_higher` | `reduce_throttle` | **REJECTED** |
| 4 | Imola | T18 Rivazza 2 | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_higher` | (not selected) | ACCEPTED |
| 5 | Imola | T14 Gresini | `time_loss`, `current_speed_lower`, `current_throttle_lower` | (not selected) | ACCEPTED |
| 6 | Imola | T17 Rivazza 1 | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_higher` | (not selected) | ACCEPTED |
| 7 | Imola | T15 Gresini | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_lower` | (not selected) | ACCEPTED |
| 8 | Imola | T1 Turn 1 | `time_loss`, `current_speed_lower`, `current_throttle_lower`, `current_brake_lower` | (not selected) | ACCEPTED |
| 9 | Imola | T2 Tamburello | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_lower` | (not selected) | ACCEPTED |

## Rejected case

**Candidate:** Imola T13 — Acque Minerali

**Observation codes:**
```text
- time_loss
- current_speed_lower
- current_throttle_higher
```

**v0.1 action:**
```text
reduce_throttle
```

**Human verdict:** REJECTED

**Reason:** `current_throttle_higher` alone is insufficient action context.
The human reviewer recognized that an isolated throttle signal (no brake code,
no combined context) does not justify a coaching instruction to "reducir acelerador".

**Human notes:** "Throttle higher alone is not actionable. Need brake context
or combined case to authorize reduce_throttle."

## Policy v0.2 correction

The human rejection was codified into `historical_action_policy.py` v0.2:

```text
Vocabulary closed: brake/throttle adjustments only (no speed, no time)
Anti-regression: only current_slower generates actions
Anti-regression: current_faster → WITHHELD (reason: "current_lap_faster_no_actions")
New rule (Point 6): isolated current_throttle_higher → WITHHELD (reason: "insufficient_action_context")
New rule (Point 6): isolated current_brake_lower → WITHHELD (reason: "insufficient_action_context")
Observation classification: mappable / non_mappable / unknown
Unknown observation codes → validation failure
Duplicate candidate_id detection → validation failure
```

**Isolated throttle/brake codes are not sufficient action context without
a complementary code from the other channel.**

### Observation-to-action mapping (v0.2)

```text
current_throttle_higher → reduce_throttle
current_throttle_lower  → increase_throttle
current_brake_higher    → reduce_brake
current_brake_lower     → increase_brake
```

### Insufficient context rule

```text
Mappable codes = {"current_throttle_higher"} → WITHHELD (insufficient_action_context)
Mappable codes = {"current_throttle_lower"}  → WITHHELD (insufficient_action_context)
Mappable codes = {"current_brake_higher"}    → WITHHELD (insufficient_action_context)
Mappable codes = {"current_brake_lower"}     → WITHHELD (insufficient_action_context)
```

These are insufficient alone. Combined cases (e.g. `current_throttle_higher + current_brake_lower`) remain authorized.

### Code classification

```text
mappable:       codes present in OBSERVATION_TO_ACTION
non_mappable:   KNOWN_NON_MAPPABLE_CODES (speed/time)
unknown:        not in any known set → validation failure
```

## v0.2 replay

Replayed v0.2 on all 3 real sessions (Imola, Interlagos, Fuji):

```text
CLEAN_AUTHORIZED:    8
CLEAN_WITHHELD:      1
selector_invalid:     0
policy_invalid:       0
validator_failures:   0
```

**Accepted cases changed: 0** — the v0.2 replay confirmed that 8 cases
remain authorized and 1 case (Imola T13) is now correctly withheld.

## Production promotion status

```text
STILL BLOCKED pending additional real human-review evidence.
```

**Rationale:**

1. **Sample size:** Only 9 candidates reviewed (1 circuit, 1 session).
2. **No multitrack evidence:** The human review round 1 was on Imola only.
   H5.3f promotion requires independent evidence across at least 4 circuits.
3. **No LLM selection:** Human review was done against Python-issued candidates,
   not via H5.3c LLM selection.
4. **No eligibility change:** The eligibility gate was not modified.
5. **Policy v0.2 is shadow:** The v0.2 policy correction is implemented and tested,
   but the historical coaching debrief remains ROADMAP_ONLY.

## Run

```powershell
python -m pytest tests/test_historical_action_policy.py -q --tb=short
python -m pytest tests/test_h5_3_real_session_audit.py -q --tb=short
python -m pytest -q
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
```

### Results

```text
tests/test_historical_action_policy.py:   36 passed
tests/test_h5_3_real_session_audit.py:    38 passed
pytest:                                  ALL PASSED
regressions:                             ALL PASSED
```

## Preservation

```text
historical_actions_authorized = false
session_reference_remains_authority = true
scope = authorized_action_candidates_only
```

These invariants remain unchanged. The human review round 1 documents a
rejection and a policy correction. It does not authorize historical coaching,
nor does it change the production authority of the current-session debrief.

## Files changed

- `docs/H5_3_HUMAN_REVIEW_ROUND_1_V0_1.md` — this document
- `docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md` — updated roadmap section

## Next steps

1. Collect more real human review evidence across additional circuits.
2. When eligibility for production is revisited, re-run the full pipeline
   (H4 → H5.3f) and report results.
3. Consider whether the v0.2 `insufficient_action_context` rule applies to
   isolated brake codes (the human review only covered throttle).
4. The roadmap remains: ROADMAP_ONLY.
