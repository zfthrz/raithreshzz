# Race Engineer — Repository Agent Instructions

## Mandatory onboarding

Before any non-trivial code change, architecture proposal, debugging session, refactor, calibration change, or review:

1. Read `PROJECT_CONTEXT.md` completely.
2. Treat current generic runtime code + tests as the operational source of truth.
3. Use `PROJECT_STATUS.md` for the short current checkpoint and `README.md` for detailed user workflows.
4. Inspect the exact current code before editing; do not infer current behavior from `legacy/` or an old versioned note.
5. If architecture/contracts/version baselines change, update `PROJECT_CONTEXT.md` in the same change.

If `PROJECT_CONTEXT.md` is missing, report that before making a broad project-level change.

## Project mental model

Race Engineer is an LMU telemetry coaching pipeline. Python owns deterministic telemetry facts and validation. The LLM interprets, prioritizes and writes coaching from authorized evidence; it must not invent telemetry facts or silently recalculate deterministic truth.

Normal entry point:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

DeepSeek is the default backend. Ollama/local:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --backend ollama
```

## Hard invariants

- Python owns laps, deltas, events, physical points, recurrence, gates, track/context facts, History, matcher logic and validators.
- The LLM may prioritize and narrate only authorized evidence.
- Never invent metres, percentages, turns, counts, grip/balance/stability/understeer/oversteer or trajectory claims without deterministic evidence.
- Speed is context, not a controllable driving target.
- Never weaken validators merely to make an output pass.
- Keep `LMP2_ELMS` distinct from `LMP2`/WEC context.
- Track layout (`lmu_track_layout`) is part of hard context.
- For H2, prefer `AMBIGUOUS` over an unsupported MATCH/REJECT.
- Human labels are stronger ground truth than DeepSeek pseudo-labels.
- H5.1 `session_reference` remains coaching authority; `historical_reference` is observational.
- H5.2 LLM output is a controlled-code selection only: Python authorizes and renders every observation; free text, historical actions, causal claims and replacement of `session_reference` are forbidden.
- H5.2 zone-selection audit metrics are shadow evidence only. Impact, intensity or
  corner specificity cannot become a production ranking formula without broader validation.
- H5.2 interval telemetry evidence is deterministic and observational only. Its
  speed/throttle/brake/gear samples and accumulated delta may support inspection,
  but cannot authorize historical coaching or replace `session_reference`.
- LLM prompt experiments must use `run_llm_prompt_shadow.py`. Promotion evidence
  requires exact same-source/backend/model A/B pairs assessed by
  `assess_llm_prompt_shadow_promotion.py`; cross-model comparisons are
  observational only and cannot authorize a production prompt change. The current
  verdict is `PROMOTION_BLOCKED_INSUFFICIENT_PAIRED_EVIDENCE`.
- A throttle physical point remains a concise cue; its reference sequence is a separate
  secondary cue when capacity allows. Actionability audit counts are shadow evidence and
  cannot authorize a brake/throttle channel preference or complexity score.
- H5.4 P10/P11 are presentation-only projections. They never mutate or re-authorize
  `next_stint_plan`; a consumer may expose P11 focus only when its count and plan-label
  subset are consistent, otherwise it must fall back to the complete validated plan.
- H2 matcher v0.3 is provisional/context-limited, not a universal multi-track matcher.
- Hierarchical H2 track/layout baselines may authorize MATCH only after explicit
  promotion. REJECT remains exact-variant-only and inherited REJECT is forbidden.
- H3 is calibration-derived and is not forced on every per-session run. Importing
  an official H3 run into History is explicit, idempotent and observational:
  `cross_session_repeat` is not a `persistent_pattern`, conflicts are never imported,
  and no imported row changes session-reference or historical coaching authority.
- H3 import readiness discovery is read-only. It may validate existing official
  bundles and report not-applicable/ready/imported/conflict/failed, but it must not
  run H2/H3, mutate History or treat readiness as coaching authority.
- H5.3 remains ROADMAP_ONLY; H5.3a/b/c are implemented shadow-only and never
  enable historical coaching. The orchestrator `h5_3` stage is observational-only
  and must return `SKIPPED_NOT_APPLICABLE` when H4/H5.1/H5.2 prerequisites are
  absent. `historical_action_policy.py` may construct shadow action candidates only
  (closed throttle/brake vocabulary, current-slower candidates only, speed and time
  never become actions); `historical_actions_authorized` remains false.
- H5.3g reconstructs reviewed `current_faster + WITHHELD` cases from hashed
  selection artifacts. Its local deltas are diagnostic evidence only: it must not
  weaken the whole-lap guard or authorize a local action without a separately
  reviewed shadow policy and broader independent evidence.

## Current baseline

Checkpoint: 2026-08-26 GUI v1.21 + automatic H2 review queues + H5.4 P1–P11.

```text
race_engineer.py             orchestrator 0.3
race_engineer_gui.py         desktop session hub 1.21 / automatic calibration queues
analyze_telemetry.py         3.8 + Objective Python v6
llm_analysis*.py             3.10.8.5.4
llm_analysis_llamacpp.py     3.10.8.5.4 / llama.cpp local (default qwen3-14b)
session_history.py           1.4 / schema 4
episode_pair_matcher.py      H2 0.3
build_persistent_patterns.py H3 0.1
run_h3_pipeline.py          authorized H2 -> H3 -> optional validated History import
select_historical_reference.py H4 0.2
build_dual_reference_context.py H5.1 0.2
build_cross_session_comparison.py H5.2 0.2 / profile-localized raw comparison
build_historical_telemetry_evidence.py H5.2 interval evidence 0.1 / observational
historical_llm_analysis.py   H5.2 LLM 0.1 / validated observational narrative
build_historical_coaching_candidates.py H5.3a 0.1 / shadow candidates
prepare_h5_3_audit_dataset.py + label/validate H5.3b 0.1 / audit + human review
historical_candidate_eligibility.py H5.3 runtime eligibility 0.2 / whole-lap delta authority
historical_candidate_selection.py    H5.3c 0.1 / controlled LLM selection
historical_candidate_selection_runtime.py H5.3 runtime 0.2 / deterministic default
historical_action_policy.py           H5.3 action candidates 0.2 / shadow only
audit_h5_3_faster_lap_withholding.py   H5.3g 0.1 / local-loss diagnostic audit
evaluate_h5_3_local_loss_policy.py     H5.3h 0.1 / unauthorized local-policy hypothesis
audit_h5_3_local_loss_recurrence.py    H5.3i 0.1 / exact-zone vs cross-zone recurrence
maintain_h5_3_action_review.py         automatic exact-label queue expansion / no decisions
audit_h5_3_real_sessions.py            H5.3 Point 6 audit 0.3 / real sessions + P11 comparison
```

Validated integration checkpoint:

```text
pytest:                         1052 PASS / 0 FAIL / 0 SKIP
Objective Python regressions:  55 PASS / 0 FAIL / 0 SKIP
```

## Runtime and Git hygiene

Do not write generated prompts/results into tracked source directories.

Runtime/local state belongs under:

```text
telemetria/
data/generated/
data/local/
```

Current generated subpaths are centralized by `runtime_paths.py`.

Do not reintroduce tracked `*_llm/` runtime directories. `legacy/` is provenance, not normal runtime.

## Versioning convention

Normal commands use generic filenames without version suffixes. Versioned release artifacts may be retained for provenance.

When a release changes, keep its generic operational alias synchronized. At this checkpoint the generic LLM aliases correspond to release 3.10.8.5.4.

## Testing

For integration-sensitive changes run, as applicable:

```powershell
python -m pytest -q
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
python apply_objective_python_recovery_2026_08_13.py --check analyze_telemetry.py
```

With local telemetry available also exercise:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

Report what actually ran, what passed, what failed and what was skipped because of unavailable telemetry, credentials or environment.

## Change discipline

- Make the smallest coherent change in the layer that owns the behavior.
- Read tests/contracts before changing behavior.
- Do not “fix” production code to satisfy an obviously stale fixture without checking the contract.
- Do not delete `legacy/` for cosmetic cleanup.
- Preserve stage reuse and explicit `RUN / REUSED / SKIPPED_NOT_APPLICABLE / FAILED` semantics in the orchestrator.
- Keep deterministic evidence independently testable.
- Update `PROJECT_CONTEXT.md` when the mental model changes.
