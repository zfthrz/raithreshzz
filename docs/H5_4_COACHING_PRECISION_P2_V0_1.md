# H5.4 Coaching Precision — P2 v0.1

## Goal
Extend deterministic `precision_evidence` from repeated physical-point patterns to authorized single-comparison physical-point cues that reach `next_stint_plan`.

## Contract
- Absolute LMU lap distance remains source truth.
- No detector, threshold, ranking, magnitude, direction, or actionability policy changes.
- A SINGLE pattern receives lap provenance only from its explicit parent comparison (for example `4->3`) and its already-measured signed `comparison_minus_reference_m`.
- Corner-relative labels are derived only from an active validated track profile.
- Missing/ambiguous comparison, delta, point, or profile fails safe: existing coaching remains, precision lines are omitted.
- LLM performs no arithmetic and chooses no anchor.

## Implementation
1. SINGLE plan patterns now preserve `comparisons`, `deltas_m`, and `median_delta_m` from deterministic source facts.
2. The final selected `next_stint_plan` is passed through the shared precision helper for braking onset, brake release, throttle onset, and throttle release patterns.
3. Existing P1 rendering is reused unchanged.

## Expected visible effect
A/B-style single priority cues can now expose:
- reference lap;
- supporting lap;
- one-observation range/representative magnitude;
- corner-relative reference point;
while repeated C-style cues keep their existing multi-lap evidence.

## Validation
Run:

```bash
python -m pytest tests/test_coaching_precision.py -q
python -m pytest tests/test_llm_analysis_llamacpp.py -q
python -m pytest -q
```

Then rerun a known real session and verify that previously single-only priority zones receive precision lines when deterministic anchors exist.
