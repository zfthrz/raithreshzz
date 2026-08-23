# H5.3 action review — round 3 Monza — 2026-08-22

> Historical checkpoint: some labels from this round were later invalidated by the
> whole-lap sign correction. Current evidence is documented in round 4 and queue v4.

## Pipeline recovery

The Monza HYPER llama.cpp run initially exposed two orchestration contract defects:

1. `race_engineer.py` expected the main artifact without the canonical `_llamacpp_`
   filename segment, although the backend had completed and saved a valid result.
2. `historical_llm_analysis.py` implemented `call_backend("llamacpp")` but omitted
   llama.cpp from its CLI parser choices.

The artifact resolver now uses the canonical filename and can recover a completed
artifact only when source analysis, LLM version, model and internal validation
statuses match. The existing Monza qwen3-14b artifact passed the full LLM validator
with zero warnings and was reused without repeating its 26 model requests. The H5.2
historical llama.cpp output then ran and passed its dedicated validator.

## Monza historical result

```text
H4: HISTORICAL_REFERENCE_SELECTED
Current reference: session 41, lap 4, 98.080 s
Historical reference: session 16, lap 8, 98.020 s
Current - historical: +0.060 s
H5.2 temporal validation: PASS
H5.2 localized zones: 11
H5.2 historical LLM: PASS
H5.3 deterministic section: PASS
H5.3 runtime shadow: PASS
Historical coaching authority: DISABLED
```

The runtime shadow policy produced three Monza action items, all current-slower and
all combined-channel:

- before T1: `increase_throttle + increase_brake`;
- T1: `reduce_throttle + increase_brake`;
- T4: `reduce_throttle + increase_brake`.

## Safe queue expansion

The original 15 labels were not copied blindly. A new queue was generated and
`migrate_h5_3_action_review_labels.py` preserved a label only when both `review_id`
and the complete item snapshot were identical.

```text
Validated source artifacts: 7
Queue v2 unique items: 18
Source occurrences represented: 21
Prior labels preserved: 15
Prior labels dropped: 0
New Monza items reviewed: 3
Final reviewed: 18/18
```

Final labels:

| Human label | Count |
|---|---:|
| `ACTION_USEFUL` | 16 |
| `CORRECTLY_WITHHELD` | 2 |
| all non-affirmative labels | 0 |

Track coverage now includes Imola, Interlagos, Fuji and Monza.

## H5.3f v0.2 result

```text
Verdict: EVIDENCE_INCOMPLETE
Missing reviewed delta sign: current_faster
Missing authorized single-action branches: increase_brake, reduce_brake
Authority: SHADOW ONLY
```

Monza is no longer a missing requirement. The remaining gaps are real evidence gaps,
not implementation failures. Production historical actions remain disabled.
