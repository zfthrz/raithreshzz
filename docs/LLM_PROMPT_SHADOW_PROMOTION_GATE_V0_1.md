# LLM prompt shadow promotion gate v0.1

## Outcome

`episode-grounding-shadow-v0.1` remains `SHADOW_OBSERVATIONAL_ONLY`.

Current verdict:

```text
PROMOTION_BLOCKED_INSUFFICIENT_PAIRED_EVIDENCE
```

No production prompt, ranking, P9/P10/P11 policy or coaching output was changed.

## Why cross-model results are not prompt A/B evidence

An exact prompt pair must keep all of these fixed:

- deterministic source JSON;
- backend;
- model;
- comparison and episode counts.

The only intended difference is `production` versus
`episode-grounding-shadow-v0.1`. A result from a different model is useful for
backend evaluation, but it cannot isolate the effect of the prompt appendix.

## Real evidence checkpoint

| Track | Backend/model | Comparison | Episodes repaired | Fallbacks | Role |
|---|---|---|---:|---:|---|
| Imola | DeepSeek / `deepseek-v4-pro` | production | 4 / 43 (9.3%) | 0 | exact A/B baseline |
| Imola | DeepSeek / `deepseek-v4-pro` | shadow v0.1 | 4 / 43 (9.3%) | 0 | exact A/B candidate |
| Monza | DeepSeek / `deepseek-v4-flash` | shadow v0.1 | 6 / 49 (12.2%) | 2 | unpaired observation |
| Fuji | llama.cpp / `qwen3.6-35b-a3b-iq2_m` | shadow v0.1 | 1 / 18 (5.6%) | 2 | unpaired observation |

All completed shadow artifacts passed the strict LLM output validator. Fuji
passed with zero warnings. The llama.cpp non-thinking fix prevented hidden
reasoning from exhausting the 8192-token output budget.

The exact Imola pair shows no regression in aggregate repair burden, but also
no measurable reduction: both variants required 4 repairs in 43 episodes.
Monza and Fuji demonstrate portability across tracks and backends; they do not
increase the exact-pair count because their production artifacts use different
models.

## Automated gate

`assess_llm_prompt_shadow_promotion.py` accepts result files or directories and
uses the read-only repair diagnostics. Promotion requires:

1. at least 3 exact A/B source pairs;
2. exact pairs covering at least 2 tracks;
3. consistent comparison and episode counts inside every pair;
4. no increase in repair rate, critical grounding errors or fallbacks;
5. at least one measurable decrease in those metrics.

Possible verdicts:

- `PROMOTION_READY`;
- `PROMOTION_BLOCKED_INSUFFICIENT_PAIRED_EVIDENCE`;
- `PROMOTION_BLOCKED_REGRESSION`;
- `PROMOTION_BLOCKED_NO_MEASURABLE_BENEFIT`.

The gate is diagnostic. Even `PROMOTION_READY` is evidence for a later explicit
production change; the assessor itself never rewrites prompts or authorizes
coaching.

## Next evidence needed

Run production and shadow with the same model for at least two additional
sources, covering another track. The cheapest useful continuation is an exact
same-model pair on Fuji and one additional exact pair on Monza or Imola. Do not
spend more calls merely to create cross-model comparisons for this gate.
