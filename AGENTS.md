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
- H2 matcher v0.3 is provisional/context-limited, not a universal multi-track matcher.
- H3 is calibration-derived and is not forced on every per-session run.

## Current baseline

Checkpoint: 2026-08-14 integration v0.2.

```text
race_engineer.py             orchestrator 0.2
analyze_telemetry.py         3.8 + Objective Python v6
llm_analysis*.py             3.10.8.5.4
session_history.py           1.4 / schema 4
episode_pair_matcher.py      H2 0.3
build_persistent_patterns.py H3 0.1
select_historical_reference.py H4 0.2
build_dual_reference_context.py H5.1 0.2
build_cross_session_comparison.py H5.2 0.2 / profile-localized raw comparison
historical_llm_analysis.py   H5.2 LLM 0.1 / validated observational narrative
```

Validated integration checkpoint:

```text
pytest:                         81 PASS / 0 FAIL / 0 SKIP
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
