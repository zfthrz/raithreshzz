# H5.4 P11 — Deterministic Driver Focus Slots

## Version

v0.1 — 2026-08-21

## Objective

Derive a **presentation-only** driver-facing focus view from the P10 projection
(`next_stint_plan_presentation`). P11 takes at most the first 2 items from P10
presentation, deep-copies them, and returns them in a compact `next_stint_focus`
field. No ranking, eligibility, action-authority, or P1–P10 changes are made.

## Output Shape

```json
{
  "next_stint_focus": {
    "status": "ACTIVE",
    "policy_version": "0.1",
    "focus_count": 2,
    "items": [
      { /* deep-copied plan item 0 */ },
      { /* deep-copied plan item 1 */ }
    ]
  }
}
```

## Policy

- **Presentation-only.** Never mutates `next_stint_plan` or `next_stint_plan_presentation`.
- **Uses only P10 presentation.** No time_loss, magnitude, speed, or LLM score.
- **Takes at most the first 2 items** from P10 presentation (already sorted by `presentation_rank`).
- **Preserves all structured fields** and `driver_cues` exactly.
- **Never re-orders, re-ranks, or re-selects.** P11 consumes P10 only.
- **Fail closed** if P10 status is not `ACTIVE` or presentation is not a list:
  `status = "UNAVAILABLE"`, `focus_count = 0`, `items = []`.

## Contract

| Field | Type | Description |
|---|---|---|
| `status` | `"ACTIVE"` or `"UNAVAILABLE"` | Whether focus slots were derived |
| `policy_version` | `"0.1"` | Deterministic policy identifier |
| `focus_count` | `int` | Number of items in `items` (0, 1, or 2) |
| `items` | `list` | Deep-copied plan items, at most 2 |

## Integration

P11 is integrated into the canonical backends:

- `llm_analysis.py`
- `llm_analysis_deepseek.py`
- `llm_analysis_ingenierov3.py`
- `llm_analysis_llamacpp.py`

Each backend:

1. Builds `next_stint_plan` (authoritative).
2. Builds `next_stint_plan_presentation` via `build_p10_plan_presentation()`.
3. Builds `next_stint_focus` via `build_p11_plan_focus()`.
4. Returns all three in the output JSON.

## Deterministic Driver Focus Example

```json
{
  "next_stint_focus": {
    "status": "ACTIVE",
    "policy_version": "0.1",
    "focus_count": 2,
    "items": [
      {
        "_p9_presentation_metadata": { "presentation_rank": 0 },
        "driver_cues": [
          {
            "kind": "spatial_points",
            "channel": "brake",
            "text": "reduced onset in left-knee sector",
            "location": { "zone": "sector_2", "start_m": 3420.0, "end_m": 3850.0 }
          }
        ],
        "actionable_cue_count": 1,
        "speed_m_s": 24.5,
        "time_loss_s": 0.12,
        "magnitude": 0.8
      },
      {
        "_p9_presentation_metadata": { "presentation_rank": 1 },
        "driver_cues": [
          {
            "kind": "spatial_points",
            "channel": "throttle",
            "text": "earlier throttle than reference",
            "location": { "zone": "sector_3", "start_m": 4100.0, "end_m": 4600.0 }
          }
        ],
        "actionable_cue_count": 1,
        "speed_m_s": 22.1,
        "time_loss_s": 0.08,
        "magnitude": 0.6
      }
    ]
  }
}
```

## Tests

- **A**: 3-item presentation → first 2 items returned
- **B**: 2 items → both returned
- **C**: 1 item → one returned
- **D**: empty presentation → focus_count=0, items=[]
- **E**: fallback P10 → UNAVAILABLE
- **F**: invalid P10 presentation → UNAVAILABLE
- **F**: original next_stint_plan not mutated
- **G**: P10 presentation not mutated
- **H**: P8/P9 metadata preserved
- **I**: repeated calls deterministic
- **J**: speed/time_loss/magnitude cannot affect focus
- **K**: canonical backend integration

All tests pass: 67 total (55 existing + 12 new P11 tests).
