# Public release roadmap v0.1

## Goal

Ship a Windows desktop build for drivers who want to analyze LMU sessions, without
exposing calibration, matcher review, H3 maintenance or development diagnostics.
The public build must preserve the current deterministic coaching and validation
contracts. It must make no automatic LLM call.

Track profiles remain versioned data. A later profile or exact layout variant is
added to the production catalog and shipped in a subsequent application or profile
bundle; it does not require redesigning the executable.

## Current audit

The source tree is not yet a distributable product:

- `RaceEngineer.pyw` opens the complete development interface.
- `Circuitos`, `Diagnóstico` and `Calibración` expose operator workflows that do
  not belong in the public interface.
- The frozen public processes still need packaging configuration and end-to-end
  validation.
- The exact release dependencies are pinned, but the complete license files from
  the built runtime and wheels must be collected into the final artifact.
- `INSTALL.txt`, `MANIFEST.txt` and `PATCH_MANIFEST.txt` describe old internal
  deliveries and are not public installation material.

`python public_release_contract.py` records these conditions deterministically.
It is read-only and exits with status 1 while a blocker remains. Its profile catalog
selects the highest validated top-level profile for each exact track/layout identity;
`track_profiles/shadow_v2` is never a public candidate.

## Release gates

### R0 — Contract and inventory

- Keep public sections limited to Resumen, Telemetría, Historial and Estadísticas.
- Exclude Circuitos, Diagnóstico and Calibración from the public entrypoint.
- Define the production profile catalog by exact track/layout and highest validated
  version.
- Maintain a machine-readable, read-only readiness audit.

Exit: `public_release_contract.py` reports only the blockers belonging to later gates.

### R1 — Public runtime mode

- [x] Add `RaceEngineerPublic.pyw` as a separate entrypoint.
- [x] Do not initialize operator-only views, scheduler maintenance controls or
  calibration modules in public mode.
- [x] Keep the source/developer entrypoint unchanged for profile work.
- [x] Store generated state and History under `%LOCALAPPDATA%\RaceEngineer` rather
  than beside the executable, while preserving source-checkout paths for developers.

Exit reached structurally: the public process exposes four navigation targets,
cannot navigate to an absent operator frame and does not import the eight operator
modules during GUI import. Native visual QA remains part of R4.

### R2 — Reproducible Windows package

- [x] Pin the tested analysis/runtime libraries and PyInstaller build tool in
  `requirements-release.txt`.
- [x] Define separate GUI, safe-launcher and deterministic-CLI entrypoints so a
  frozen GUI never masquerades as `python.exe` when spawning pipeline stages.
- [x] Configure the packager and measure the first functional onedir build: about
  123.6 MiB before final size optimization.
- [x] Bundle the Python interpreter and native runtime dependencies. Public users must
  not install Python or run `pip`; Python remains a development/calibration tool.
- [x] Produce an exact direct/transitive runtime and build dependency lock from the
  tested environment.
- Include only runtime Python modules, production profiles and user documentation.
- Exclude tests, calibration batches, raw/reference sessions, LLM backends, audit
  tools, local state, telemetry and generated artifacts.
- [x] Generate SHA-256 checksums and a machine-readable build manifest containing
  the source commit, dependency lock and exact profile catalog.
- [x] Fix `PYTHONHASHSEED` and derive `SOURCE_DATE_EPOCH` from the source commit in
  `build_public_release.ps1`; refuse pre-existing work/output directories.

Exit: two clean builds from the same commit have the same declared contents and
pass the portable smoke test.

### R3 — Installation and first run

- Provide a clear first-run choice for telemetry location and debrief language.
- Verify that paths containing spaces and non-ASCII characters work.
- Explain unsupported track/layout states without exposing calibration internals.
- Define update and uninstall behavior without deleting user telemetry or History.

Exit: a clean Windows account can install, analyze a supplied fixture, reopen the
session and uninstall while its explicitly retained user data stays intact.

### R4 — Release candidate QA

- Run the full pytest and deterministic regression suites.
- Validate every shipped production profile and exact identity.
- Exercise short/long debriefs, no-debrief, History-only and load-error states.
- Test window resize, DPI scaling, clipboard, English/Spanish new reports and LMU
  coexistence on the supported Windows versions.
- Confirm zero writes to bundled profiles and zero automatic LLM calls.

Exit: signed QA report with every required check and no unresolved release blocker.

### R5 — Publication

- [x] Choose the initial license: free personal, non-commercial use under the
  proprietary Race Engineer Personal Use License 1.0. Source visibility does not
  make the first-party application open source.
- [x] Record third-party license families and require their complete notices in the
  final package.
- Choose public product name, semantic version and support channel.
- Write the user installation guide, privacy/data statement and known limitations.
- Create the versioned artifact, checksums and release notes from a tagged commit.
- Publishing or pushing remains an explicit owner action.

Exit: immutable public artifact traceable to its source commit and profile catalog.

## Later personalization stage

Personalized recommendations can use a driver's own History to distinguish repeated,
resolved and newly observed patterns. Any such policy must keep current-session
telemetry as factual authority, remain isolated per user and pass a separate
longitudinal promotion gate. Existing H3/H4/H5 historical evidence is a foundation,
but its current observational status is unchanged for the first public release.

## Adding the remaining profiles

Each new circuit or layout follows the existing internal calibration and validation
process. Promotion adds one validated, versioned JSON to the top-level
`track_profiles` catalog. The release audit then selects it automatically by its
exact identity. Shadow candidates and raw calibration material remain internal.

For the initial public stage, profiles ship inside each application version. This
keeps the executable, tests and exact profile catalog traceable as one release and
lets data coverage improve with each update. If profiles are closed after the first
public release, they are delivered in the next application build.

A separately installable profile bundle is deferred until the catalog is stable.
Before enabling it, the application must validate bundle schema, compatible app
versions, exact track/layout identity, file checksums and publisher signature, and
must install atomically without replacing a newer profile. This avoids committing
the first release to an update protocol before the data format is mature.
