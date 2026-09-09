# Public release R4 QA — 2026-09-09

Status: **CANDIDATE / MANUAL SESSION COVERAGE PENDING**

This report records reproducible evidence for the Windows public release candidate.
It does not approve publication while the pending checks below remain open.

## Candidate identity

- Source branch: `main`
- Source commit: `4c78ebb5092d05d103ec0570b5469de14562f1e4`
- Product version: GUI v1.74
- Build directory: `data/local/public_builds/rc-4c78ebb/RaceEngineer`
- Package form: Windows onedir with embedded Python 3.12.10
- Manifest: `BUILD_MANIFEST_OK`
- Manifest entries: 1843, plus `BUILD_MANIFEST.json`
- Package bytes including manifest: 130,089,460
- Production profiles: 12 exact track/layout identities

## Automated evidence

| Check | Result |
|---|---|
| Complete pytest suite | 2059 passed in 57.12 s |
| Objective Python regressions | 55 passed, 0 failed, 0 skipped |
| Focused public locale/runtime tests | 60 passed |
| Production-profile and validator tests | 335 passed |
| Source profile hashes before/after profile validation | 0 changes |
| Public release contract v0.3 | READY, 0 blockers |
| Build manifest verification | PASS |
| Packaged CLI top-level and `analyze` help | PASS, exit 0, English |
| Packaged safe-launcher help | PASS, exit 0, English |
| Packaged worker invoked with `llm_analysis` | BLOCKED, exit 2 |
| `git diff --check` before source commit | PASS |

No LLM was called during QA. The candidate contains the closed deterministic worker;
the worker rejected the unsupported `llm_analysis` module. Profile validation did
not change any source profile. Tests and build checks did not modify source telemetry,
History, generated reports or coaching authority.

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

## Pending checks

These checks require a suitable real telemetry fixture, controllable native UI or LMU:

- reconfirm the sidebar open/close Summary layout and `Ctrl+Space` help in v1.74;
- exercise short and long real-session debriefs in Spanish and English;
- open FOCUS and confirm Summary remains populated;
- navigate from Detail to the corresponding Telemetry zone;
- verify Actions only, Copy checklist and clipboard contents;
- verify full-debrief jumps for Start, Focus, Plan and Evidence;
- switch between short-text and long-text sessions;
- exercise no-debrief, History-only and real load-error states;
- complete one packaged analysis from a supplied `.duckdb`, reopen it and verify the
  isolated per-user History/statistics lifecycle;
- test a clean-account install and retained-data uninstall;
- test LMU coexistence and scheduler impact while LMU is running;
- test another supported Windows DPI scaling value.

## Publication decision

R4 remains open. Sign-off and R5 publication require the pending checks to pass with
no unresolved release blocker. Publishing, tagging and pushing remain owner actions.
