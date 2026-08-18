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

The Windows task invokes `hidden_history_ingest.py` with `pythonw.exe`. It creates no
console and redirects stdout/stderr to the rotating ignored log
`data/local/telemetry_auto_ingest_task.log`.

The Windows Explorer action `Analizar con Race Engineer (DeepSeek)` is the explicit
LLM path. It checks authorized path, LMU shutdown, age, size and at least two valid
laps before running the full DeepSeek pipeline. It does not use `--force`, so valid
stages can be reused. A second verb, `Analizar con Race Engineer (ingenierov3)`,
runs the same launcher with `--backend ollama` and the local `ingenierov3` model.

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
full pytest (current H5.3 milestone): 146 passed
full pytest after La Sarthe profile: 123 passed
focused La Sarthe/profile contracts:  15 passed
Objective Python regressions:         55 passed (last analyzer-affecting checkpoint)
git diff --check:                      PASS
```

The hidden task also completed a real manual run: 68 files scanned, zero scan errors,
the backfill cooldown preserved and `exit_code=0` recorded in the local log.

## Scheduled task

Task name:

```text
RaceEngineer-History-Ingest
```

The task was re-enabled after the first context-menu test and its hidden action was
verified with `exit_code=0`. It should normally remain in state `Ready`. Inspect it
with:

```powershell
Get-ScheduledTask -TaskName "RaceEngineer-History-Ingest" |
  Select-Object TaskName, State, Actions

Get-ScheduledTaskInfo -TaskName "RaceEngineer-History-Ingest" |
  Select-Object LastRunTime, LastTaskResult, NextRunTime
```

The action must still point to the LMU `UserData\Telemetry`
workflow through `pythonw.exe` plus `hidden_history_ingest.py`, with the repository as
working directory. Install or update it with:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_history_ingest_task.ps1
```

Known non-blocking state entries:

```text
BACKFILL_FAILED: Monza 2026-08-15T05_01_19Z
BACKFILL_FAILED: Spa   2026-08-12T07_32_09Z
```

Both contain one usable lap, so strict comparison validation correctly exits
non-zero. Do not weaken the validator. A later cosmetic change may classify them as
`BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS`.

## Circuit de la Sarthe profile checkpoint

`track_profiles/la_sarthe_profile_v0_1.json` is now
`VALIDATED_MULTI_SESSION` for the exact identity
`Circuit de la Sarthe` / `Circuit de la Sarthe`.

Evidence consists of five complete GPS laps across three independent LMU Practice
sessions. The two independent sessions produced median representative-point offsets
of 4 m and 8 m and maxima of 22 m and 24 m. ACO 2026 names are authoritative. The 19
profile segment numbers are project-local localization identifiers and must not be
presented as the official FIA WEC 33-turn numbering.

Read `docs/LA_SARTHE_TRACK_PROFILE_V0_1.md` before changing its boundaries or names.
The profile activates deterministic H5.2 localization only; it does not authorize
historical coaching or change H5.1 authority.

## Current repository checkpoint

Published milestones on `main`:

```text
7287931 complete telemetry automation and project handoff
41315ff run History ingest task without console
9353c41 add validated Circuit de la Sarthe track profile
```

At handoff preparation, `main` matched `origin/main`. Local untracked
`track_exports/` files are calibration evidence and must not be included in source
commits. Continue staging explicit paths rather than using a blanket `git add .`.

## Immediate next actions

There is no pending automation or La Sarthe closeout change.

1. Start every new task by checking `git status --short --branch` and reading the
   exact current code/tests involved.
2. Prefer minor isolated maintenance while the temporary backend handoff is active.
3. The one-valid-lap backfill outcome is now
   `BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS`; keep the strict analyzer validator
   unchanged.
4. H5.3a/b/c are implemented shadow-only; continue with H5.3d/e/f only when
   explicitly chosen.

## Future objective after automation closeout

H5.3 is the historical-product objective: a separate full-style debrief comparing
the current reference lap against the fastest compatible historical lap. It remains
`ROADMAP_ONLY`; H5.3a (shadow candidates), H5.3b (audit dataset + human review) and
H5.3c (controlled LLM selection) are implemented in shadow with real Imola/Monza
evidence, and historical coaching stays disabled. Remaining slices: H5.3d
deterministic separate renderer, H5.3e safe fallback, H5.3f multitrack promotion
gate. Read `docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md` before extending. Preserve
the existing H4/H5.1/H5.2 schemas and the current-session A/B/C output.

## Safe continuation rule

Do not redesign the History/H4/H5 authority boundary while closing this milestone.
If a run fails, diagnose the owning stage and preserve the explicit
`RUN / REUSED / SKIPPED_NOT_APPLICABLE / FAILED` semantics.
