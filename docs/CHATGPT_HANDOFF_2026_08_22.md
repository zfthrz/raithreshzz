# Race Engineer — ChatGPT handoff — 2026-08-22

This document is the current portable continuation checkpoint. It supplements, but
does not replace, `AGENTS.md`, `PROJECT_CONTEXT.md`, `PROJECT_STATUS.md` and the exact
current code/tests.

## Repository checkpoint

```text
repository: zfthrz/raithreshzz
branch: main
published commit: fb91b12 surface deterministic driver focus in desktop GUI
main: synchronized with origin/main at handoff preparation
full pytest: 987 passed
Objective Python regressions: 55 passed (last analyzer-affecting checkpoint)
GUI: 1.4
```

Normal execution remains:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

The desktop entry point is `RaceEngineer.pyw`.

## Mandatory reading order

1. `AGENTS.md` — hard instructions and baseline.
2. `PROJECT_CONTEXT.md` — complete architecture and authority model.
3. `PROJECT_STATUS.md` — current concise checkpoint.
4. `README.md` — operational workflows.
5. this handoff.
6. exact generic runtime code and tests for the chosen task.

Current generic runtime code and automated tests outrank older design notes and
`legacy/`. Do not infer current behavior from filenames alone.

## User collaboration context

The repository owner is not a software specialist but can reliably follow explicit
PowerShell steps. Explain decisions in Spanish, provide commands ready to paste and
prefer one small verified commit at a time. The user normally runs `git add`,
`git commit` and `git push`; do not assume permission to stage unrelated files.

## Non-negotiable architecture

- Python owns deterministic telemetry facts, laps, deltas, physical points, gates,
  History, matching, historical context and validators.
- The LLM may interpret, prioritize and word only authorized evidence.
- Never weaken a validator to make an output pass.
- Speed is context, not a controllable target.
- `LMP2_ELMS` is distinct from `LMP2`.
- Exact LMU track layout is a hard context gate.
- H5.1 `session_reference` remains current-session coaching authority.
- H5.2 and the current H5.3 runtime are observational/shadow.
- `historical_actions_authorized` remains `false`.
- H5.4 P10/P11 are presentation-only and never mutate or re-authorize the complete
  `next_stint_plan`.
- Generated/local artifacts belong under ignored `data/generated/`, `data/local/`
  or `telemetria/` paths.

## Current functional state

### Automatic telemetry and History

`auto_ingest_telemetry.py` monitors LMU telemetry through a hidden scheduled task,
waits for LMU shutdown/stability, runs deterministic analysis and imports History
without an LLM. Explicit LLM analysis is launched from the desktop GUI or Explorer
context menu after the existing safety gates.

### H1–H5 historical stack

- H1 History: schema 4, idempotent import.
- H2 matcher 0.3: provisional/context-limited; Monza Hyper and LMP2_ELMS batches
  still need more independent real sessions for leakage-safe evaluation.
- H3: derived from calibrated H2 and not forced per session.
- H4: selects the fastest compatible historical reference under strict gates.
- H5.1: keeps session and historical references separate.
- H5.2: validated raw cross-session comparison and controlled observational LLM
  selection; no historical action authority.
- H5.3a–f: fully implemented in shadow, including deterministic renderer, validator,
  fallback and multitrack promotion manifest.
- H5.3 Nivel 2: closed brake/throttle action candidates for current-slower cases;
  speed/time never become actions and faster cases are withheld.
- Production historical coaching is still disabled even though the existing manifest
  reports `PROMOTION_READY`.

### H5.4 and GUI

H5.4 P1–P11 are implemented in the canonical backends. P10 projects the complete
plan for presentation and P11 exposes at most two driver-focus items without changing
the plan.

GUI v1.4 provides:

- safe explicit DeepSeek/llama.cpp/Ollama analysis;
- read-only History and H4 reference inspection;
- deterministic lap-time and pipeline tabs;
- validated current-session debrief and complete next-stint plan;
- P11 focus shown before the preserved complete plan;
- H5.2 historical comparison;
- GPS circuit map with H5.2 loss/gain zones and validated plan/focus layers;
- draggable GPS point with speed/brake/throttle inspection;
- synchronized 10 Hz full-lap telemetry chart with wheel zoom, `Shift + wheel` pan
  and graph reset.

Map zoom was consciously deferred because it is lower priority than historical
product validation.

## Real evidence immediately before handoff

- Five recent debriefs had consistent `next_stint_focus = ACTIVE / 2`.
- Latest Imola rendered focus A/C while retaining complete plan A/C/B.
- Latest real Imola GPS smoke test: 967 aligned points at 10 Hz; a representative
  20% chart window retained 194 speed/throttle/brake samples.
- GUI/H5.4 focused checkpoint: 110 tests passed.
- Full suite: 987 tests passed.

## Working-tree exclusions

At handoff preparation the source branch was synchronized, but these local/untracked
items existed and must not be staged automatically:

```text
.qwen/
APPLY_UPDATE_2026_08_21.md
H5_4_P9_DEEPSEEK_NAMEERROR_FIX_v0_1.patch
Modelfile
UPDATE_MANIFEST_2026_08_21.json
fix_h5_4_p9_deepseek.ps1
fix_h5_4_p9_deepseek_v0_2.ps1
fix_h5_4_p9_deepseek_v0_3.py
p11_diff.txt
tests/test_coaching_precision_p10.py
track_exports/Circuit de la Sarthe_*
track_exports/sarthe_*/
```

Always inspect `git status --short --branch` and stage explicit paths. Never use a
blanket `git add .` in this checkout.

## Recommended next objective

Perform a **read-only H5.3 production-readiness review** before changing authority.

The first slice should:

1. inventory current real H5.3 artifacts across available tracks/contexts;
2. rerun the dedicated validators without calling an LLM where reuse is possible;
3. compare shadow historical action candidates against the current-session P11 focus
   and identify conflicts, duplication or excessive cognitive load;
4. generate a review report under `docs/` or ignored `data/generated/` as appropriate;
5. keep `historical_actions_authorized=false` and make no production integration;
6. present the evidence to the user before proposing any feature flag or promotion.

Do not interpret `PROMOTION_READY` as automatic permission to enable coaching. The
manifest proves the existing shadow gate conditions, not product usefulness or safe
coexistence with the current-session focus.

## Validation commands

After a focused code change, run relevant tests first. For integration-sensitive
changes run:

```powershell
python -m pytest -q
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
python apply_objective_python_recovery_2026_08_13.py --check analyze_telemetry.py
git diff --check
```

Only claim checks that actually ran. A documentation/GUI-only change does not need a
new real LLM call.

## Ready-to-paste continuation prompt

```text
You are taking over development of the repository zfthrz/raithreshzz (Race Engineer
for Le Mans Ultimate). Work as a careful coding collaborator and answer me in Spanish.
I am not a software specialist, but I can follow exact PowerShell commands. Make one
small, verifiable change at a time and let me run Git commits/pushes unless I explicitly
ask otherwise.

First read these files completely, in this order:
1. AGENTS.md
2. PROJECT_CONTEXT.md
3. PROJECT_STATUS.md
4. README.md
5. docs/CHATGPT_HANDOFF_2026_08_22.md

Then inspect the exact current generic code and tests involved. Current runtime code
and tests are the source of truth; do not reconstruct behavior from legacy files or
old notes.

Current published checkpoint:
- branch main, commit fb91b12
- pytest: 987 passed
- Objective Python regressions: 55 passed at the last analyzer checkpoint
- GUI v1.4
- H5.4 P1-P11 implemented; P10/P11 are presentation-only
- H5.3a-f and Nivel 2 actions are complete in shadow
- historical_actions_authorized remains false

Preserve these invariants:
- Python owns telemetry facts, gates, History and validators.
- Never weaken a validator to make output pass.
- Speed is context, not a driving target.
- LMP2_ELMS and LMP2 are different contexts.
- Track layout is a hard gate.
- H5.1 session_reference remains coaching authority.
- H5.2/H5.3 historical evidence remains observational/shadow until explicit review.
- P11 focus never replaces or mutates the complete next_stint_plan.

Before editing, run git status --short --branch. Do not stage or delete the existing
local .qwen/, Modelfile, patch/update files, tests/test_coaching_precision_p10.py or
track_exports/ artifacts. Never use git add .

Next objective: perform a read-only H5.3 production-readiness review. Inventory real
H5.3 artifacts, run their dedicated validators, and compare shadow historical action
candidates against the current-session P11 focus for conflicts, duplication and
cognitive load. Produce evidence and a clear recommendation, but do not enable
historical_actions_authorized, integrate historical actions into production or call
an LLM unnecessarily. Stop for my review before proposing a promotion patch.

Report what you inspected, what actually passed, what remains unavailable, and give
me exact PowerShell commands when I need to do something.
```

