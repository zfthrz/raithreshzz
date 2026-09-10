# Race Engineer product perfection roadmap v1.0

For independent execution by a future local coding LLM, use
`docs/LOCAL_LLM_DEVELOPMENT_ROADMAP_V1_0.md` together with this product sequence.

## Purpose

This roadmap starts from the current public candidate instead of reopening completed
interface work. Its goal is to turn the existing deterministic application into a
maintainable public product, expand circuit coverage and then evaluate driver-specific
recommendations without weakening telemetry authority.

The first public release remains deliberately small: a Windows package with embedded
Python, an English/Spanish interface, deterministic debriefs and a fixed validated
profile catalog. Calibration, matcher review, diagnostics and maintenance tools remain
in the development application.

## Invariants

- Current-session Python evidence remains factual and coaching authority.
- History may describe recurrence and change only through validated contracts.
- Personalization cannot invent facts, replace the current-session reference or turn
  observational H3/H4/H5 data into coaching without a separate promotion gate.
- A public install starts with empty History and statistics.
- Existing Spanish reports remain unchanged; language affects the interface and newly
  generated reports only.
- Public builds never call an LLM automatically.
- Profiles, telemetry, History and generated reports are never rewritten by an update.
- Publication, tags and pushes remain explicit owner actions.

## Stage P0 — Close the first release candidate

Objective: complete R4 with evidence from the actual packaged application.

- [x] Reproducible Windows package with embedded Python.
- [x] Public-only navigation and isolated per-user state.
- [x] Complete English/Spanish public interface and deterministic new-report language.
- [x] Full automated suite, deterministic regressions and 13-profile validation.
- [x] Package manifest, dependency lock, licenses and installation lifecycle.
- [x] Run one packaged end-to-end analysis from a retained QA `.duckdb` fixture.
- [x] Verify functional short/long, no-debrief, History-only and load-error states.
- [ ] Complete clipboard, debrief navigation, Detail-to-Telemetry and FOCUS checks.
- [ ] Complete clean-account install/reopen/retained-data uninstall.
- [ ] Test another supported DPI scale.
- [ ] Measure scheduler coexistence with LMU when LMU becomes available.

Exit: the R4 QA report contains every result, has no unresolved blocker and is marked
approved for publication.

Current result (2026-09-09): functional packaged QA passes after three reproduced
packaging fixes. Native session UI, alternate DPI and LMU coexistence remain the only
sign-off gate because the current automation environment cannot control native apps.

## Stage P1 — Complete initial circuit coverage

Objective: maintain exact circuit/layout coverage for the owner's target catalog.

The first-release scope was frozen at the 13 identities already validated when R4
functional QA passed. The three still unnamed targets move to later application
versions; no identity or profile is inferred merely to enlarge version 0.1.0.

### P1a — Exact inventory

- Confirm the exact LMU track and layout strings for all four targets.
- Record category, car, available independent sessions and source-file fingerprints.
- Do not infer the three unnamed targets from old documents or unrelated local data.
- Keep Barcelona as the only currently identified target; it already has registered
  telemetry files but still requires normal inspection and validation.

### P1b — Barcelona

- [x] Recover the existing source sessions without copying or modifying them.
- [x] Validate lap coverage, geometry, direction, start/finish continuity and turn bounds.
- [x] Build the smallest profile version supported by the available independent evidence.
- [x] Run profile and localization validation against independent real-session GPS.
- [x] Promote only after the existing profile gate passes.

Completed as `barcelona-lmu-fia14-v0.1`: source plus three independent
`LMP2_ELMS` validations, each 14/14 PASS with no warnings. Representative complete
pipeline analysis remains part of P0 packaged end-to-end QA rather than profile
geometry authority.

### P1c — Other three profiles after 0.1.0

- Wait for real source sessions and confirmed identities.
- Apply the same calibration and independent-validation workflow to each profile.
- Never lower the gate to complete the catalog sooner.

### P1d — 0.1.0 catalog freeze

- Publish the exact track/layout/profile-version matrix selected by the release audit.
- Rebuild the candidate from the frozen source commit.
- Re-run profile hashes, full tests, deterministic regressions and the packaged smoke.

Exit for 0.1.0: the release manifest includes the 13-profile frozen catalog with no
shadow or calibration data. Later targets enter only through the same gate.

## Stage P2 — Publish version 0.1

Objective: produce the first immutable public artifact after P0 and P1 pass.

- [x] Choose `Race Engineer`, semantic version `0.1.0` and public GitHub Issues support.
- [x] Add a concise privacy/data statement: processing is local, telemetry location is
  user-selected, and no automatic LLM or telemetry upload occurs.
- [x] Freeze known limitations, validated Windows platform and supported LMU layouts.
- Build from the final tagged commit in a new empty directory.
- [x] Prepare release notes and the exact profile catalog; final checksums follow the tag.
- Verify installation on a clean account before signing the QA report.
- Publish only after explicit owner approval.

Exit: one immutable downloadable artifact is traceable to its tag, source commit,
dependency lock and profile manifest.

Current result (2026-09-09): R5 content is prepared as `0.1.0-rc.1`. The immutable
tag, final artifact and publication remain gated by the pending native R4 checks.

## Stage P3 — Make releases maintainable

Objective: let coverage and fixes improve without risking user data.

### P3a — Application updates

- [x] Keep and exercise the current new-folder update model for early versions.
- [x] Add an in-app read-only version/about surface to identify the exact build and
  public support channel without consulting user data or the network.
- Define compatibility and migration tests before any persistent-state schema change.
- [x] Keep rollback possible by retaining the prior application folder. The packaged
  previous → current → previous sequence preserved the exact isolated-state hash.

### P3b — Profile delivery decision

- Continue bundling profiles with application versions until the catalog format is
  stable across multiple releases.
- Measure whether full application updates are creating a real operational burden.
- Introduce profile-only packages only when that burden is demonstrated.

If profile packages become justified, the required contract is:

- signed publisher identity and manifest;
- SHA-256 for every file;
- exact schema and compatible application-version range;
- exact track/layout identity and monotonically newer profile version;
- validation in a temporary location before an atomic install;
- no downgrade, partial install or mutation of bundled/user data;
- recovery to the last valid catalog after interruption.

Exit: at least one update path has passed install, rollback and retained-data tests.

Current result (2026-09-10): the portable new-folder path passed packaged update,
rollback and retained-state checks. Clean-account visual installation and application-
folder removal remain part of the pending native R4 lifecycle sign-off.

## Stage P4 — Personalization foundation, observational only

Objective: determine whether a driver's own History contains stable, useful signals
before changing any recommendation.

### P4a — Baseline and consent

- Keep personalization off by default during the experiment.
- Explain which local History fields are used and provide a reset that affects only
  derived personalization state.
- Define a minimum amount of independent same-context history before any pattern is
  eligible for evaluation.

### P4b — Longitudinal model

For each authorized action identity, derive only deterministic states such as:

- newly observed;
- repeated in compatible sessions;
- improving, unchanged or worsening;
- absent after previously recurring;
- unavailable because context or evidence is insufficient.

The model must distinguish exact track/layout, category, vehicle and car context. It
must not treat frequency alone as severity, and absence in one session must not mean
that a problem is resolved.

### P4c — Shadow evaluation

- Compute a personalized ordering beside the unchanged production ordering.
- Record agreement, useful differences, instability and withheld cases.
- Review real longitudinal examples across multiple circuits and session lengths.
- Reject policies that over-focus on old habits or hide a higher-value current issue.

Exit: a versioned shadow dataset shows that personalization improves prioritization
without factual, context or authority violations. Production output is unchanged.

## Stage P5 — Gated adaptive recommendations

Objective: expose personalization only after P4 evidence supports a narrow policy.

- Start with explanatory annotations such as repeated or improving, rather than
  silently changing the primary action.
- Allow reordering only among actions already authorized in the current session.
- Never generate a historical action absent from current authorized evidence.
- Show why History affected presentation and allow the user to disable it.
- Preserve the complete non-personalized plan as a deterministic fallback.
- Add longitudinal rollback, reset, migration and corrupted-History tests.

Exit: a separately approved policy and validator permit the smallest useful adaptive
behavior, with a feature flag and deterministic rollback.

## Stage P6 — Ongoing product quality

Objective: improve reliability and clarity using evidence from actual users.

- Track crashes, load failures and unsupported layouts locally with opt-in export.
- Prioritize reproducible defects over speculative interface changes.
- Measure startup, session switching, telemetry rendering and scheduler cost on the
  supported hardware range.
- Expand accessibility and DPI coverage.
- Review documentation and known limitations with every release.
- Add circuits through the P1 profile gate and never through runtime guesswork.

## Immediate execution order

1. Finish the remaining P0 native checks when native control and LMU are available.
2. Publish version 0.1 from the frozen 13-profile catalog after owner sign-off.
3. Validate the early-release new-folder update and retained-data rollback workflow.
4. Add later circuit profiles only from identified real sessions through the P1 gate.
5. Gather real longitudinal evidence before implementing P4 personalization logic.

P3 profile packages and P5 adaptive coaching are deliberately conditional. They are
implemented only when release operations or shadow evidence demonstrate a concrete
need; neither is required to ship the first public version.
