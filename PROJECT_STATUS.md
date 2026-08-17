# Project Status

## Current integration checkpoint

### analyze_telemetry
Current: `3.8`

Primary objective unit:
`driver_action_episode`

Speed does not merge driver actions.

### llm_analysis
Current: `3.10.8.5.4`

Contract:
- structured JSON only
- all episode IDs required
- qualitative text cannot contain numbers
- Python owns ground truth and final rendering
- invalid LLM response is rejected

### history
Current: `session_history v1.4 / schema 4`

Implemented:
- DuckDB schema
- idempotent SHA-256 imports
- session/comparison/episode/channel storage
- normalized lap fractions
- batch import
- stats

### automatic telemetry ingest

Current: `auto_ingest_telemetry v0.1`

Implemented and validated on Windows:
- reads LMU DuckDBs directly from `UserData/Telemetry` in read-only mode;
- preserves source state by exact name/size/mtime migration;
- skips every operation while `Le Mans Ultimate.exe` is running;
- waits 10 minutes after the game was last observed before opening telemetry;
- imports deterministic analysis into History before any LLM work;
- serializes backlog processing and gives new telemetry priority;
- keeps files below 5 MiB out of automatic backfill;
- scopes maintenance and debrief selection to the active telemetry source.
- runs scheduled maintenance through `pythonw.exe` with no visible console;
- redirects scheduled stdout/stderr to a 2 MiB rotating local log with one backup.

Real unattended validation:
- source: `Autodromo Nazionale Monza_P_2026-08-17T18_55_39Z.duckdb`;
- deterministic analyzer: `RUN`;
- History: `IMPORTED`, `session_id=23`;
- LLM: `SKIPPED_NOT_APPLICABLE` as required by the History-first stage;
- state transition: `PENDING_STABILITY -> HISTORY_READY` without manual analysis.

The optional Windows Explorer launcher validates source, LMU shutdown, file age,
size and deterministic valid-lap count before authorizing DeepSeek. Its context-menu
registration is per-user and reversible.

Explorer registration validation:
- `Analizar con Race Engineer (DeepSeek)` appears in the `.duckdb` context menu;
- the launcher and registration tests passed in the focused 22-test checkpoint;
- an end-to-end Explorer-triggered DeepSeek run should be recorded before calling
  this milestone fully closed.

Latest real H4 validation:
- target: History `session_id=23`, Monza `LMP2_ELMS`, IDEC Sport #18;
- current session reference: lap 3, `99.280 s`;
- selected history: `session_id=19`, lap 10, `97.500 s` (`1:37.500`);
- selected delta: historical lap `1.780 s` faster;
- status: `HISTORICAL_REFERENCE_SELECTED`;
- H5 remains observational and the current-session reference retains coaching authority.

Known non-blocking backfill outcome:
- Monza `2026-08-15T05_01_19Z` and Spa `2026-08-12T07_32_09Z` are recorded as
  `BACKFILL_FAILED` because each contains only one usable lap after the initial and
  incomplete laps are excluded;
- neither case called an LLM, corrupted History or affects ready sessions;
- a future cosmetic improvement may use
  `BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS`, but validators must not be weakened.

Known non-blocking backfill outcome:
- Monza `2026-08-15T05_01_19Z` and Spa `2026-08-12T07_32_09Z` are recorded as
  `BACKFILL_FAILED` because each contains only one usable lap after the initial and
  incomplete laps are excluded;
- the analyzer correctly produces no comparisons and `--validate` returns failure;
- neither case called an LLM, corrupted History or affects ready sessions;
- a future cosmetic improvement may classify this as
  `BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS`, but validators must not be weakened.

Hidden-task closeout evidence:
- `RaceEngineer-History-Ingest` was updated to `pythonw.exe` plus
  `hidden_history_ingest.py`;
- real manual task execution scanned 68 source files, preserved the backfill cooldown
  and ended with `exit_code=0`;
- full pytest: `119 PASS / 0 FAIL / 0 SKIP`;
- `git diff --check`: `PASS`;
- final source commit remains the only closeout action.

### historical layers

Implemented:
- H2 matcher `0.3`, provisional and context-limited
- H3 persistent pattern builder `0.1`, calibration-derived
- H4 historical reference selector `0.2`
- H5.1 dual reference context `0.2`
- H5.2 profile-localized raw cross-session comparison `0.2` / schema `1.1`
- H5.2 validated observational LLM narrative `0.1`

Planned, not implemented:
- H5.3 separate historical coaching debrief;
- current state: `ROADMAP_ONLY`, `historical_actions_authorized=false`;
- first future slice: H5.3a Python-owned shadow candidate builder;
- promotion requires dedicated gates, validator, human audit and multitrack evidence.

See `docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md`. H5.3 must remain additive:
the current-session debrief and H5.1 coaching authority cannot change merely because
the roadmap exists.

H5.2 resolves both raw DuckDBs through History, applies exact context gates, compares
independent historical/current `LapAnalyzer` sources, validates the temporal delta and
emits observational spatial zone summaries.

H5.2 v0.2 preserves broad delta trends for audit and, when an exact validated
track/layout profile exists, splits them deterministically at profile boundaries
before LLM selection. Missing profiles use an explicit unlocalized fallback.

Real multitrack checkpoint:

| Track | Historical reference | Current reference | Current - historical | Raw zones | LLM-selected zones | Validators |
|---|---:|---:|---:|---:|---:|---:|
| Fuji | session 7 lap 8, `90.980 s` | session 8 lap 5, `92.260 s` | `+1.280 s` | 7 | 3 | `PASS` |
| Imola | session 9 lap 4, `93.660 s` | session 10 lap 4, `94.260 s` | `+0.600 s` | 3 | 3 | `PASS` |
| Interlagos | session 11 lap 7, `87.320 s` | session 12 lap 13, `87.140 s` | `-0.180 s` | 4 | 3 | `PASS` |
| Monza | session 14 lap 1, `99.140 s` | session 16 lap 8, `98.020 s` | `-1.120 s` | 5 | 3 | `PASS` |

Fuji also completed an orchestrator reuse check with H5.2 `REUSED`. The four
historical narratives use DeepSeek `deepseek-v4-pro`, disable free text and keep
historical coaching disabled. See `docs/H5_2_MULTITRACK_VALIDATION_V0_1.md`.

The H5.2 LLM contract can select up to three validated spatial zones and only the
observation codes authorized by Python for each zone. LLM free text is disabled;
Python owns the complete rendering. The validator rejects invented zones, extra
fields, unauthorized codes and evidence tampering.
Historical actions remain disabled and `session_reference` remains coaching authority.

H5.2 zone-selection shadow audit `0.1`:
- compares validated model outputs offline against absolute-impact, intensity-per-100-m
  and corner-only ranks;
- Monza: Pro and Qwen 27B matched impact top 3, Qwen 14B overlapped 2/3 and Flash 1/3;
- Imola: Pro matched impact and intensity top 3, while Flash overlapped 2/3;
- intensity alone overweights short Monza segments and impact alone can favor a broad
  cumulative interval;
- no production ranking or coaching authority was changed. See
  `docs/H5_2_ZONE_SELECTION_SHADOW_AUDIT_V0_1.md`.

Debrief actionability:
- session priority policy `1.9` ranks repeated physical points by their own
  cross-comparison support before the broader recurrence of the enclosing region;
- the rule is channel-neutral and does not hard-code brake over throttle;
- on the real Imola audit, the brake point supported in 3 comparisons ranks ahead
  of the throttle point supported in 2, despite the throttle region appearing in 5.
- actionability policy `1.7` keeps an authorized throttle onset/release point as the
  concise primary cue and moves its known reference sequence to a separate secondary
  cue when capacity allows; profile-only zones still render ordered driver actions,
  and unknown shapes retain a descriptive fallback.
- actionability shadow audit `0.1` inspected 4 validated/stale-render-only Pro
  artifacts and 12 priority zones: 7 brake primary cues and 5 throttle primary cues;
  brake cues were structurally simpler in this sample, but no channel preference or
  complexity score was promoted;
- deterministic rerender `0.1` rebuilds cues, deterministic priority text and the
  final render from an existing result without calling an LLM; the real Monza v1.7
  preview passed the complete output validator and preserved A/B/C ordering.
- mixed lower/higher speed directions across comparisons render as variable speed
  context instead of two apparently contradictory conclusions; speed remains
  observational and never becomes a driving target.

LLM backend benchmark on the real 10-comparison Monza `LMP2_ELMS` session:
- DeepSeek `deepseek-v4-pro`: approximately 4 minutes, 3 deterministic summary
  fallbacks, 7 episode repairs and final validator `PASS`;
- local Qwen 14B `ingenierov3`: 8.0 minutes, 6 fallbacks, 17 repairs and
  final validator `PASS`;
- local Qwen3.8 27B IQ3_M: 33.7 minutes, 3 fallbacks, 7 repairs and final
  validator `PASS`; observed as 13 GB / 100% GPU;
- all three produced the same final authorized A/B/C plan;
- operational recommendation: Pro remains the general default, 14B is the
  recommended local/offline backend and 27B remains experimental.

See `docs/LLM_BACKEND_BENCHMARK_MONZA_V0_1.md`.

Validation:
- pytest: `83 PASS / 0 FAIL / 0 SKIP`
- Objective Python regressions: `55 PASS / 0 FAIL / 0 SKIP`
- Objective recovery check: `READY`

H2 Monza Hypercar calibration checkpoint:
- exact context: `Autodromo Nazionale Monza` / `HYPER`;
- 4 independent sessions, 587 candidate pairs and a 24-pair human queue;
- human labels: 9 `SAME`, 13 `DIFFERENT`, 2 `AMBIGUOUS`, 0 `SKIP`;
- leakage-safe split: 13 calibration pairs, 0 evaluation pairs and 11 cross-split exclusions;
- status: `READY_FOR_MORE_REAL_DATA`; no Monza matcher or H3 patterns are authorized.

See `docs/H2_MONZA_HYPER_CALIBRATION_V0_1.md`.

H2 Monza `LMP2_ELMS` calibration checkpoint:
- exact context: `Autodromo Nazionale Monza` / `LMP2_ELMS` / `IDEC Sport #18:ELMS25`;
- 3 independent sessions, 455 candidate pairs and a 24-pair human queue;
- human labels: 11 `SAME`, 12 `DIFFERENT`, 1 `AMBIGUOUS`, 0 `SKIP`;
- leakage-safe split: 5 calibration pairs, 0 evaluation pairs and 19 cross-split exclusions;
- status: `READY_FOR_MORE_REAL_DATA`; no Monza matcher or H3 patterns are authorized.

See `docs/H2_MONZA_LMP2_ELMS_CALIBRATION_V0_1.md`.

LLM output validator `1.2` recognizes the exact deterministic fallback for a
comparison excluded by the global quality gate before the LLM call. It requires
all exclusion markers and exact fallback content, while preserving the original
non-contiguous episode IDs left after an anomalous episode is separated for audit.

Calibration batch orchestrator `1.5` requires the current History schema 4 contract,
reports its runtime version consistently and has a regression test against schema drift.

## Mandatory gates

### Gate A
Keep both raw DuckDBs and exact track/layout/vehicle/car compatibility.

### Gate B
Require H4 selection plus H5.1 dual-reference context.

### Gate C
Require H5.2 temporal validation and its structural validator.

### Gate D
Require the dedicated H5.2 LLM validator before historical evidence can alter observational wording. Historical evidence cannot authorize coaching actions.

Do not let `historical_reference` silently replace the current session reference.
