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

Normal entry point (backend-free):

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

Opt-in LLM backend (DeepSeek):

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --backend deepseek
```

Opt-in local backend (Ollama / llama.cpp):

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
- `maintain_h3_imports.py` preserves that read-only default. Its `--apply` mode is
  an explicit operator action that may import only bundles already classified
  `H3_READY_TO_IMPORT`. The hidden scheduler may run only its read-only audit and
  publish local readiness state; it must never pass `--apply`.
- `audit_h3_materialization_readiness.py` may run the authorized H2 gate and H3
  builder in memory to report readiness, but it must write no bundle and mutate no
  History state. The hidden scheduler may publish only its read-only snapshot and
  must defer the expensive audit while LMU is running. `MATERIALIZATION_READY`
  still requires an explicit pipeline run.
- `materialize_h3_context.py` is the explicit bridge from one exact
  `MATERIALIZATION_READY` row to the official H3 bundle. Its default is read-only;
  `--apply` may write only the three H3 bundle files, must pass `history_db=None`,
  and must finish as `H3_READY_TO_IMPORT`. It never imports History or authorizes
  coaching.
- `import_h3_context.py` is the separate exact-context History mutation. It
  requires `H3_READY_TO_IMPORT`, creates and SHA-256-verifies a checkpointed
  DuckDB backup first, then post-validates `H3_IMPORTED`. It remains
  observational and never authorizes coaching.
- GUI telemetry gain/loss shading must derive only from adjacent changes in the
  existing deterministic accumulated-delta comparison. Visual aggregation may
  bound canvas objects for 50 Hz performance, but must not rewrite telemetry,
  alter stored delta or become coaching authority.
- GUI `Steering Pos` is a signed, optional observational lane. It may help inspect
  an already-authorized steering recommendation, but its display, sign or visual
  similarity must never create new steering coaching or relax the existing gate.
- `audit_h3_runtime_utility.py` is corpus observability only. It may compare
  generated H3.1 availability with generated H4/H5.2 artifacts and report exact
  membership separately from H3.2 projection, but it must not label false positives,
  call the matcher/LLM, open History, change thresholds or authorize coaching.
- `audit_h3_projection_stability.py` may group already-generated automatic H3.2
  projection edges by exact context and pattern identity. Repetition counts and
  coexistence with exact runtime membership are review signals only: they are not
  thresholds, labels, persisted membership or promotion authority.
- H3.2 projection review queues must remain under ignored local state and declare
  `H3_2_PROJECTION_VALIDATION_ONLY`. Their SAME/DIFFERENT/AMBIGUOUS/SKIP labels
  reuse H2 review semantics but must never be consumed as matcher calibration,
  persisted membership or coaching authority without a separate approved gate.
- The H3.2 projection human-review audit may summarize completed isolated labels
  by existing matcher rule, pattern and raw feature distributions. Its queue is
  positive-only, so it cannot estimate recall or false negatives, infer thresholds,
  calibrate the matcher, persist membership or authorize coaching.
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
race_engineer_gui.py         desktop session hub 1.43 / automatic H3 audit status
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
