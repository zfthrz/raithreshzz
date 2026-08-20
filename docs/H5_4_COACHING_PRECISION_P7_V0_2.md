# H5.4 Coaching Precision — P7 v0.2

## Backend parity fix

P7 v0.1 implemented deterministic `coaching_sequence` generation and generic
driver-cue consolidation, but production DeepSeek was not wired to call it.

P7 v0.2 adds integration parity to:

- `llm_analysis_deepseek.py`
- `llm_analysis_llamacpp.py`

Each active backend now:

1. imports `enrich_plan_items_with_coaching_sequence`;
2. calls it after `enrich_plan_items_with_precision`;
3. converts eligible brake + throttle spatial cues to
   `combined_spatial_sequence`.

No detector, threshold, ranking, coaching direction/magnitude, P4/P5/P6
policy, authority, or historical coaching behavior changes.

A regression test checks active-backend parity so this wiring cannot silently
diverge again.
