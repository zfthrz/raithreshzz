# Race Engineer handoff — 2026-08-17

This is the short operational handoff for continuing development with DeepSeek or
another coding agent. It supplements, but does not replace, `AGENTS.md` and
`PROJECT_CONTEXT.md`.

## Mandatory reading order

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `PROJECT_STATUS.md`
4. this handoff
5. the exact current code and tests involved in the next change

Generic runtime files and current tests are the operational source of truth. Do not
reconstruct current behavior from `legacy/` or superseded versioned notes.

## Non-negotiable contracts

- Python owns deterministic telemetry facts, gates, History and validators.
- The LLM may only prioritize and narrate authorized evidence.
- Never weaken a validator to make output pass.
- Speed is context, not a controllable driving target.
- `LMP2_ELMS` remains distinct from `LMP2`.
- Track layout is a hard context gate.
- H5.1 session reference remains coaching authority.
- H5.2 historical output remains observational; historical coaching is disabled.
- Runtime artifacts belong under ignored `data/generated/`, `data/local/` or
  `telemetria/` paths.

## Current operational flow

The scheduled History-first path reads LMU telemetry directly from:

```text
C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry
```

`auto_ingest_telemetry.py maintenance`:

1. exits before scanning while `Le Mans Ultimate.exe` is running;
2. waits 10 minutes after the game was last observed;
3. gives newly completed telemetry priority;
4. runs deterministic analysis and idempotent History import without LLM;
5. processes at most one eligible backlog file per cooldown;
6. never treats the 5 MiB threshold as proof that recording finished.

The Windows Explorer action `Analizar con Race Engineer (DeepSeek)` is the explicit
LLM path. It checks authorized path, LMU shutdown, age, size and at least two valid
laps before running the full DeepSeek pipeline. It does not use `--force`, so valid
stages can be reused.

## Real validation checkpoint

New unattended file:

```text
Autodromo Nazionale Monza_P_2026-08-17T18_55_39Z.duckdb
```

Observed result:

```text
PENDING_STABILITY -> HISTORY_READY
deterministic analyzer: RUN
History: IMPORTED / session_id=23
LLM: SKIPPED_NOT_APPLICABLE
```

H4 then confirmed that historical selection is working:

```text
target session:            23
current reference:         lap 3 / 99.280 s
historical session:        19
historical reference:      lap 10 / 97.500 s (1:37.500)
historical advantage:      1.780 s
selection status:          HISTORICAL_REFERENCE_SELECTED
context:                   Monza / LMP2_ELMS / IDEC Sport #18 / dry compatible
```

The current-session reference remains the coaching authority. The 1:37.500 is an
observational historical benchmark used by H4/H5, not a replacement for the normal
intra-session debrief reference.

Known non-blocking state entries:

```text
BACKFILL_FAILED: Monza 2026-08-15T05_01_19Z
BACKFILL_FAILED: Spa   2026-08-12T07_32_09Z
```

Both have exactly one usable lap after incomplete laps are discarded. The analyzer
therefore has no comparison, and strict `--validate` correctly exits non-zero. Do not
weaken the analyzer validator. A later minor change may rename these outcomes to
`BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS` and suppress the expected traceback.

## Test evidence

Most recent recorded checkpoints:

```text
full pytest before Explorer launcher: 100 passed
focused automation/launcher tests:    22 passed
Objective Python regressions:         55 passed
```

Run a fresh full suite before committing the pending milestone:

```powershell
python -m pytest -q
git diff --check
```

The deterministic analyzer itself was not changed by the Explorer launcher, but the
full suite is still the required closeout check.

## Scheduled task

Task name:

```text
RaceEngineer-History-Ingest
```

It was temporarily disabled for the first context-menu test. Reactivate and verify:

```powershell
Enable-ScheduledTask -TaskName "RaceEngineer-History-Ingest"

Get-ScheduledTask -TaskName "RaceEngineer-History-Ingest" |
  Select-Object TaskName, State, Actions

Get-ScheduledTaskInfo -TaskName "RaceEngineer-History-Ingest" |
  Select-Object LastRunTime, LastTaskResult, NextRunTime
```

Expected state: `Ready`. The action must still point to the LMU `UserData\Telemetry`
directory and the repository working directory.

## Current uncommitted milestone

The working tree contains one coherent automation/menu/documentation milestone:

```text
auto_ingest_telemetry.py
analyze_telemetry_file.py
race_engineer_context_menu.cmd
install_race_engineer_context_menu.ps1
tests/test_auto_ingest_telemetry.py
tests/test_analyze_telemetry_file.py
README.md
PROJECT_CONTEXT.md
PROJECT_STATUS.md
docs/AUTOMATIC_TELEMETRY_INGEST_V0_1.md
docs/RACE_ENGINEER_COMMAND_GUIDE.md
docs/RACE_ENGINEER_CONTEXT_MENU.md
docs/DEEPSEEK_HANDOFF_2026_08_17.md
```

Local untracked files that must not be included accidentally:

```text
Modelfile
Modelfile-qwen38
```

After the full tests pass, stage only the explicit milestone paths. Do not use a
blanket `git add .` while the local Modelfiles remain untracked.

## Immediate next actions

1. Re-enable and verify the scheduled task.
2. Complete one full DeepSeek run from the Explorer menu and record `RESULT: PASS`.
3. Run full pytest and `git diff --check`.
4. Update this handoff if the real result differs from the expected flow.
5. Commit the coherent milestone once, rather than making per-file commits.
6. Resume product development only after the automation baseline is reproducible.

## Future objective after automation closeout

H5.3 is the next historical-product objective: a separate full-style debrief comparing
the current reference lap against the fastest compatible historical lap. It is
`ROADMAP_ONLY`; do not enable historical coaching as part of automation closeout.

Read `docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md` before proposing or implementing
H5.3. Begin only with H5.3a, a Python-owned shadow candidate artifact. Preserve the
existing H4/H5.1/H5.2 schemas and the current-session A/B/C output. Do not add LLM
free text, actions or production ranking in the first slice.

## Safe continuation rule

Do not redesign the History/H4/H5 authority boundary while closing this milestone.
If a run fails, diagnose the owning stage and preserve the explicit
`RUN / REUSED / SKIPPED_NOT_APPLICABLE / FAILED` semantics.
