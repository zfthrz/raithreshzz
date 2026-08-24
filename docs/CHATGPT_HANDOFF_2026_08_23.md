# Race Engineer — ChatGPT handoff — 2026-08-23

This document is the current portable continuation checkpoint. It supplements, but
does not replace, `AGENTS.md`, `PROJECT_CONTEXT.md`, `PROJECT_STATUS.md` and the exact
current code/tests.

## Repository checkpoint

```text
repository: zfthrz/raithreshzz
branch: main
latest commit: 264fd1c algo
main: synchronized with origin/main at handoff preparation
full pytest: 1052 passed
Objective Python regressions: 55 passed (last analyzer-affecting checkpoint)
GUI: 1.13 — status badges + side-by-side historical comparison (staged, NOT committed)
```

Normal execution remains:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

The desktop entry point is `RaceEngineer.pyw` (implementation `race_engineer_gui.py`).

## Mandatory reading order

1. `AGENTS.md` — hard instructions and baseline.
2. `PROJECT_CONTEXT.md` — complete architecture and authority model.
3. `PROJECT_STATUS.md` — current concise checkpoint.
4. `README.md` — operational workflows.
5. `docs/DEEPSEEK_HANDOFF_2026_08_17.md` — historical stack state.
6. this handoff.
7. exact generic runtime code and tests for the chosen task.

Current generic runtime code and automated tests outrank older design notes and
`legacy/`. Do not infer current behavior from filenames alone.

## User collaboration context

The repository owner is not a software specialist but can reliably follow explicit
PowerShell steps. Explain decisions in Spanish, provide commands ready to paste and
prefer one small verified change at a time. The user normally runs `git commit` and
`git push`; the assistant may prepare `git add` with explicit paths only. Never use
`git add .`.

## Non-negotiable architecture

- Python owns deterministic telemetry facts, laps, deltas, physical points, gates,
  History, matching, historical context and validators.
- The LLM may interpret, prioritize and word only authorized evidence.
- Never weaken a validator to make an output pass.
- Speed is context, not a controllable target.
- `LMP2_ELMS` is distinct from `LMP2`/WEC.
- Exact LMU track layout is a hard context gate.
- H5.1 `session_reference` remains current-session coaching authority.
- H5.2 and the whole H5.3 stack are observational/shadow.
- `historical_actions_authorized` remains `false`; H5.3 is `ROADMAP_ONLY`.
- H5.4 P10/P11 are presentation-only and never mutate or re-authorize the complete
  `next_stint_plan`; an inconsistent P11 focus falls back to the complete plan.
- Shadow audit metrics (actionability, zone selection, local loss) are evidence,
  not production ranking formulas.
- Generated/local artifacts belong under ignored `data/generated/`, `data/local/`
  or `telemetria/` paths.

## Current functional state

### Automatic telemetry and History

`auto_ingest_telemetry.py` monitors LMU telemetry through a hidden scheduled task,
waits for LMU shutdown/stability, runs deterministic analysis and imports History
without an LLM. Explicit LLM analysis is launched from the desktop GUI or Explorer
context menu after the existing safety gates. `hidden_history_ingest.py` uses
`pythonw.exe` and shows no console.

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
- H5.3g/h/i: faster-lap withholding audit, conservative local-loss hypothesis and
  exact-zone recurrence audit; all diagnostic, policy unchanged.
- `maintain_h5_3_action_review.py` automatically expands the exact-label review
  queue without making decisions; current real checkpoint `UP_TO_DATE`, 8 artifacts.
- Production historical coaching is still disabled even though the existing manifest
  reports `PROMOTION_READY`. The manifest proves shadow gate conditions, not product
  usefulness or safe coexistence with the current-session focus.

### H5.4 and GUI

H5.4 P1–P11 are implemented in the canonical backends. P10 projects the complete
plan for presentation and P11 exposes at most two driver-focus items without changing
the plan.

GUI v1.13 provides:

- safe explicit DeepSeek/llama.cpp/Ollama analysis (llama.cpp restricted to
  localhost; non-secret settings under `data/local/`);
- section navigation (Resumen / Telemetría / Historial / Diagnóstico) with compact
  session cards;
- **status badges**: the catalogue colors each session state and shows an explanatory
  tooltip on hover;
- **side-by-side historical comparison**: delta summary, historical/current panels
  and detail with top-3 deterministic zones plus the validated H5.2 LLM reading;
- read-only History, H4 reference and deterministic lap-time/pipeline tabs;
- validated current-session debrief and complete next-stint plan;
- P11 focus shown before the preserved complete plan;
- H5.3 shadow-maintenance review status indicator;
- GPS circuit map with H5.2 loss/gain zones, validated plan/focus layers, exact
  profile turn selector and curve overlay;
- draggable GPS point with speed/brake/throttle inspection;
- synchronized full-lap telemetry chart with turn navigation, wheel zoom,
  `Shift + wheel` pan and graph reset.

## Real evidence immediately before handoff

- Full pytest suite: 1052 passed / 0 failed / 0 skip.
- B/C focused tests: 26 passed (`test_race_engineer_gui_style.py` +
  `test_race_engineer_ui_model.py`).
- Latest Imola/debrief consistency checks remain valid; `next_stint_focus` P11
  presentation keeps the complete plan intact.

## Working-tree exclusions

At handoff preparation the GUI v1.13 B/C changes are staged with explicit paths only.
These local/untracked items exist and must not be staged automatically:

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

1. Commit the staged GUI v1.13 B/C milestone (the user runs commit/push) after a
   visual check of the badges/tooltips and the side-by-side comparison tab.
2. Then continue with the current priority order:
   - debrief refinement, especially brake-vs-throttle actionability (shadow audits
     only; production prompt changes need exact A/B paired evidence);
   - read-only H5.3 production-readiness review (inventory real artifacts, rerun
     validators, compare shadow actions vs P11 focus for conflicts/duplication;
     keep `historical_actions_authorized=false`);
   - integrate H3 only when calibrated matcher provenance/applicability resolves;
   - expand H2 calibration beyond the current context and add real H5.2 sessions
     without relaxing track/layout/vehicle/car gates.

Do not interpret `PROMOTION_READY` as automatic permission to enable coaching, and
do not activate H5.3 historical coaching without an explicit user request plus its
gates.

## Validation commands

After a focused code change, run relevant tests first. For integration-sensitive
changes run:

```powershell
python -m pytest -q
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
python apply_objective_python_recovery_2026_08_13.py --check analyze_telemetry.py
git diff --check
```

On Windows, if pytest fails cleaning a reused `--basetemp` directory
(`PermissionError` from a stale open handle), use a fresh basetemp name:

```powershell
python -m pytest -q -p no:cacheprovider --basetemp=data\generated\pytest_tmp_<nuevo> tests
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
5. docs/DEEPSEEK_HANDOFF_2026_08_17.md
6. docs/CHATGPT_HANDOFF_2026_08_23.md

Then inspect the exact current generic code and tests involved. Current runtime code
and tests are the source of truth; do not reconstruct behavior from legacy files or
old notes.

Current published checkpoint:
- branch main, latest commit 264fd1c, synchronized with origin/main
- pytest: 1052 passed / 0 failed
- Objective Python regressions: 55 passed at the last analyzer checkpoint
- GUI v1.13: status badges and side-by-side historical comparison are implemented
  and staged but NOT committed yet
- H5.4 P1-P11 implemented; P10/P11 are presentation-only
- H5.3a-i and Nivel 2 actions are complete in shadow; H5.3 remains ROADMAP_ONLY
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
track_exports/ artifacts. Never use git add .; stage explicit paths only.

Next objective: commit the staged GUI v1.13 B/C milestone (I run the commit/push)
and then propose the next priority from the current list (debrief refinement,
read-only H5.3 production-readiness review, H3 integration gate, or H2/H5.2 real-data
expansion). If you propose the H5.3 review: inventory real artifacts, run their
dedicated validators, and compare shadow historical action candidates against the
current-session P11 focus for conflicts, duplication and cognitive load. Produce
evidence and a clear recommendation, but do not enable historical_actions_authorized,
integrate historical actions into production or call an LLM unnecessarily. Stop for
my review before proposing a promotion patch.

Report what you inspected, what actually passed, what remains unavailable, and give
me exact PowerShell commands when I need to do something.
```
