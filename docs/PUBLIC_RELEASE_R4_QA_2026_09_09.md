# Public release R4 QA — 2026-09-09

Status: **FUNCTIONAL PASS / NATIVE VISUAL SIGN-OFF PENDING**

This report records reproducible evidence for the Windows public release candidate.
It does not approve publication while the pending checks below remain open.

## Candidate identity

- Source branch: `main`
- Functional candidate source commit: `880d3bfa3f038f376174ed148e523d6d449167aa`
- Product version: GUI v1.74
- Release version proposal: `0.1.0-rc.1`
- Build directory: `data/local/public_builds/rc-880d3bf/RaceEngineer`
- Package form: Windows onedir with embedded Python 3.12.10
- Manifest: `BUILD_MANIFEST_OK`
- Manifest entries: 1843, plus `BUILD_MANIFEST.json`
- Package bytes including manifest: 130,112,946
- Production profiles: 13 exact track/layout identities

## Automated evidence

| Check | Result |
|---|---|
| Complete pytest suite | 2069 passed in 50.96 s |
| Objective Python regressions | 55 passed, 0 failed, 0 skipped |
| Focused public locale/runtime tests | 60 passed |
| Production-profile and validator tests | 335 passed |
| Source profile hashes before/after profile validation | 0 changes |
| Public release contract v0.3 | READY, 0 blockers |
| Build manifest verification | PASS |
| Packaged real Le Mans analysis | PASS, 8 valid laps, Analysis → History → debrief → validator |
| Packaged isolated Paul Ricard analysis | PASS, 2 valid laps, English presentation stored |
| Packaged real load-error state | PASS, incomplete Imola session rejected with no usable laps |
| Source DuckDB SHA-256 before/after | IDENTICAL in all three packaged attempts |
| Isolated History validation | PASS, 1 session / 10 laps / 7 comparisons / 109 episodes |
| Packaged CLI top-level and `analyze` help | PASS, exit 0, English |
| Packaged safe-launcher help | PASS, exit 0, English |
| Packaged worker invoked with `llm_analysis` | BLOCKED, exit 2 |
| `git diff --check` before source commit | PASS |

No LLM was called during QA. The candidate contains the closed deterministic worker;
the worker rejected the unsupported `llm_analysis` module. Profile validation did
not change any source profile. Tests and build checks did not modify source telemetry,
History, generated reports or coaching authority.

The final functional run exposed and fixed three packaging defects: source-script
signatures assumed loose `.py` files, DuckDB's dynamic `uuid` dependency was absent
from the CLI and the validator imported the excluded legacy LLM module. Candidate
`880d3bf` completed the full packaged pipeline after those fixes.

## Native visual evidence

The public executable was exercised on the available Windows desktop at these window
sizes:

- maximized: 3840 x 2088;
- restored: 2402 x 1608;
- narrow restored: 1862 x 1608.

Observed coverage included Summary with the sidebar open and closed, maximize and
restore, empty History, empty Statistics and English keyboard help. QA reproduced and
fixed the empty-catalog Spanish footer, stale Summary layout after a sidebar geometry
change, clipped empty Statistics messages and the English `Ctrl+Espacio` label.
Statistics wrapping was visually reconfirmed in v1.73. The command-line localization
found during the final packaged checks was corrected and verified from the v1.74
executables.

## Pending native checks

These checks require a suitable real telemetry fixture, controllable native UI or LMU:

- reconfirm the sidebar open/close Summary layout and `Ctrl+Space` help in the final build;
- exercise short and long real-session debriefs in Spanish and English;
- open FOCUS and confirm Summary remains populated;
- navigate from Detail to the corresponding Telemetry zone;
- verify Actions only, Copy checklist and clipboard contents;
- verify full-debrief jumps for Start, Focus, Plan and Evidence;
- switch between short-text and long-text sessions;
- exercise no-debrief, History-only and real load-error states;
- reopen the real packaged sessions in the GUI and verify their History/statistics views;
- test a clean-account install and retained-data uninstall;
- test LMU coexistence and scheduler impact while LMU is running;
- test another supported Windows DPI scaling value.

## Publication decision

The functional portion of R4 passes. Final R4 sign-off remains open because this Codex
environment exposed no controllable native-application surface; the pending visual,
DPI and LMU coexistence results were not simulated. R5 assets may be prepared, but the
final tag/publication must wait for these checks to pass. Pushing remains an explicit
owner action.
