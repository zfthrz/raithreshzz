# H5.3b — Historical Candidate Eligibility (Shadow Gate)

**Version:** 0.1
**Status:** `SHADOW_ELIGIBILITY_ONLY`
**Date:** 2026-08-18

## Objective

H5.3b evaluates H5.3a deterministically-generated candidates to determine if they are sufficiently significant to merit selection by the H5.3c shadow LLM selector.

## Implementation

- **Module:** `historical_candidate_eligibility.py`
- **Validator:** `validate_historical_candidate_eligibility.py`
- **Tests:** `tests/test_historical_candidate_eligibility.py`

## Eligibility States

| State | Meaning |
|---|---|
| `ELIGIBLE_FOR_SELECTION` | `delta_change_s > MIN_SIGNIFICANT_DELTA_S`, context complete, geometry valid, evidence comparable |
| `WITHHELD` | `delta_change_s <= MIN_SIGNIFICANT_DELTA_S`, invalid context/geometry, non-comparable, or no evidence |
| `AMBIGUOUS` | Evidence and localization truly ambiguous — cannot determine significance |

## Significance Policy

```
MIN_SIGNIFICANT_DELTA_S = 0.08  (explicit constant, not learned)
delta > 0.08 → ELIGIBLE (significant zone loss)
delta < 0.00 → ELIGIBLE (current_faster has independent significance)
0 <= delta <= 0.08 → WITHHELD (insignificant or no zone loss)
```

**No `abs()` is used.** A negative delta (faster lap) has independent significance and is eligible.

## Evaluation Pipeline

1. **Context** — `track`, `track_layout`, `vehicle_variant` all present.
2. **Geometry** — finite values, `end > start`, `zone_length > 0`.
3. **Significance** — delta checked against threshold.
4. **Comparability** — `human_label = NOT_COMPARABLE → WITHHELD`.
5. **Evidence** — missing individual channels do NOT reject automatically.
6. **Localization** — `ambiguous → AMBIGUOUS`; `not_available` does NOT auto-reject.

## Contract

- `contract.status = SHADOW_ELIGIBILITY_ONLY`
- `policy.historical_actions_authorized = false`
- `policy.historical_coaching_authorized = false`
- `policy.session_reference_remains_authority = true`

## Prohibited Outputs

- No `score`, `probability`, `rank` fields
- No `actions`, `coaching`, `causal`, `recommendation` fields

## Test Results

```
pytest:  34 PASS / 0 FAIL / 0 SKIP (targeted module)
Full suite:  244 PASS / 0 FAIL / 2 SKIP
Objective Python regressions:  55 PASS / 0 FAIL / 0 SKIP
```

## Retrospective Replay

Replay on 55 real candidates across 4 tracks (Fuji, Imola, Interlagos, Monza) validates the pipeline against real audit dataset.

## References

- [`historical_candidate_eligibility.py`](../historical_candidate_eligibility.py)
- [`validate_historical_candidate_eligibility.py`](../validate_historical_candidate_eligibility.py)
- [`tests/test_historical_candidate_eligibility.py`](../tests/test_historical_candidate_eligibility.py)
- [`H5.3a shadow: candidates deterministas`](docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md)
- [`H5.3c shadow: selección LLM controlada`](docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md)
