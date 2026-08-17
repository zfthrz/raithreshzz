# H5.2 zone-selection shadow audit v0.1

## Purpose

`audit_h5_2_zone_selection.py` compares already validated H5.2 LLM selections
without calling a model and without changing production behavior. The audit is
strictly observational:

```text
status = SHADOW_OBSERVATIONAL_ONLY
production_selection_changed = false
coaching_authority_changed = false
ranking_formula_authorized = false
```

Both the raw H5.2 artifact and every historical LLM result must pass their current
validators. Each model result must also reference the exact supplied raw artifact by
SHA-256.

## Metrics

The auditor preserves three separate views instead of collapsing them into an
unvalidated score:

- absolute delta change: total temporal impact within the zone;
- absolute delta change per 100 m: local intensity;
- corner-only absolute impact: specificity among profile-localized corners.

A high rank is evidence for inspection, not proof that a zone is a better coaching
target. Speed remains context only, and historical observations cannot authorize a
driver action.

## Real checkpoint

| Track | Model | Selected zones | Impact top-3 overlap | Intensity top-3 overlap | Selected corners |
|---|---|---|---:|---:|---:|
| Monza | DeepSeek Pro | 14, 11, 8 | 3/3 | 0/3 | 1 |
| Monza | DeepSeek Flash | 12, 14, 13 | 1/3 | 0/3 | 2 |
| Monza | Qwen 14B | 9, 8, 14 | 2/3 | 0/3 | 2 |
| Monza | Qwen 27B | 14, 11, 8 | 3/3 | 0/3 | 1 |
| Imola | DeepSeek Pro | 2, 8, 10 | 3/3 | 3/3 | 3 |
| Imola | DeepSeek Flash | 2, 1, 10 | 2/3 | 2/3 | 3 |

Monza exposes the important ambiguity. Absolute impact ranks a 940 m cumulative
interval between Lesmo 2 and Ascari second, while intensity ranks short T1/T2
segments first. Imola has cleaner localized zones and the top three absolute-impact
and intensity rankings coincide.

These results do not justify an arbitrary weighted score. A formula fitted now would
overfit two circuits and could silently prefer very short segments or very broad
cumulative intervals.

## Current decision

Keep the validated controlled-code LLM selection in production and keep this auditor
in shadow mode. Do not promote impact, intensity, corner count or a weighted
combination to coaching authority until independent tracks demonstrate stable
behavior and the policy has explicit tests.

The tool may be used to accumulate those future observations at zero model cost.

## Command

```powershell
python audit_h5_2_zone_selection.py `
  "data\generated\h5_2\SESSION\cross_session_comparison.json" `
  "data\generated\h5_2_llm\SESSION\MODEL_A.json" `
  "data\generated\h5_2_llm\SESSION\MODEL_B.json" `
  --output "data\generated\h5_2_audits\selection_audit.json"
```

The output directory is runtime-generated data and remains untracked.
