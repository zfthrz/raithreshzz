# Project Status

## Current integration checkpoint

Checkpoint: **2026-08-22** / published `main` commit `b9b75a5` plus the integrated
llama.cpp recovery and H5.3 review work described below.

Validated baseline:

- full pytest: `1012 PASS / 0 FAIL / 0 SKIP`;
- Objective Python regressions: `55 PASS / 0 FAIL / 0 SKIP` (last analyzer-affecting checkpoint);
- GUI: v1.5, H6.5 visual polish + deterministic H5.4 P11 focus over the preserved complete plan;
- H5.3: shadow implementation complete, production historical actions still disabled.

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

### H5.4 coaching precision and presentation

Current: deterministic P1–P11 implemented in the canonical LLM backends.

- precision evidence and locality/track-reference guards remain Python-owned;
- P8 orders driver-facing cues without inventing evidence;
- P9 adds deterministic cross-zone diversity metadata;
- P10 creates a presentation-only plan projection;
- P11 takes at most two items from that projection as driver focus;
- P10/P11 never mutate or re-authorize `next_stint_plan`;
- GUI v1.5 shows a consistent P11 focus first and preserves the complete plan below;
- five recent real debriefs exposed `ACTIVE / 2` focus, while older artifacts safely
  fall back to the complete plan.

The controlled production-readiness review concluded **KEEP SHADOW**. The existing
`PROMOTION_READY` manifest proves structural multitrack coverage, not enough reviewed
action quality for driver-facing production. The current six action artifacts and
seven historical sections validate. Do not enable `historical_actions_authorized`.
See `docs/H5_3_PRODUCTION_READINESS_REVIEW_2026_08_22.md`.
The 15-item runtime action-review queue now has a resumable interactive labeler and
dedicated validator. Review round 2 completed all 15 items representing 18 source
occurrences: 13 `ACTION_USEFUL`, 2 `CORRECTLY_WITHHELD`, zero unsafe/ambiguous and
zero pending across Imola, Interlagos and Fuji. Monza action-review coverage is still
absent, so production authority remains disabled. See
`docs/H5_3_ACTION_REVIEW_ROUND_2_2026_08_22.md`.
H5.3f v0.2 consumes that real review and returns `EVIDENCE_INCOMPLETE`. The
subsequent Monza HYPER llama.cpp run completed H5.2/H5.3 and added three shadow
action items. Queue v2 represents 21 source occurrences, preserved all 15 prior
labels by exact snapshot migration and completed the three new Monza items. Final
review: 18/18, 16 `ACTION_USEFUL`, 2 `CORRECTLY_WITHHELD`, zero non-affirmative.
The subsequent whole-lap sign correction invalidated candidate snapshots whose
anti-regression context had previously been derived from local zone deltas. All seven
real artifacts were replayed deterministically. Queue v4 contains 20/20 reviewed
items representing 21 occurrences; exact-snapshot migration preserved 11 labels and
required nine new decisions. Final labels: 12 `ACTION_USEFUL`, 3
`CORRECTLY_WITHHELD`, 1 `WITHHELD_BUT_ACTIONABLE` and 4 `AMBIGUOUS`. H5.3f v0.2
remains `EVIDENCE_INCOMPLETE` due to five non-affirmative labels plus missing isolated
`increase_brake` and `reduce_brake`. Historical action authority remains false. See
`docs/H5_3_ACTION_REVIEW_ROUND_4_CURRENT_FASTER_2026_08_22.md`.

### llama.cpp orchestration recovery

`race_engineer.py` now resolves the canonical llama.cpp artifact name including the
`_llamacpp_` backend segment and can recover an already completed artifact only when
source analysis, version, model and internal validation statuses match exactly.
`historical_llm_analysis.py` exposes its already implemented llama.cpp backend in the
CLI parser. The recovered Monza main debrief passed validation with zero warnings,
and the historical H5.2 llama.cpp output also passed its dedicated validator.

H5.3 runtime eligibility v0.2 now keeps whole-lap delta authority separate from
zone-local losses. The real Interlagos `-0.180 s` current-faster replay validates
with zero actions and three `current_lap_faster_no_actions` withheld candidates.
The runtime artifact is ready for human review but does not yet satisfy the H5.3f
reviewed-evidence requirement. Shadow authority remains false.

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
size and deterministic valid-lap count before authorizing an LLM. Its context-menu
registration is per-user and reversible and exposes two verbs: DeepSeek (remote) and
`ingenierov3` (local Ollama).

Explorer registration validation:
- `Analizar con Race Engineer (DeepSeek)` appears in the `.duckdb` context menu;
- `Analizar con Race Engineer (ingenierov3)` uses the same launcher with
  `--backend ollama` and the local `ingenierov3` model;
- `Analizar con Race Engineer (llama.cpp)` uses the same launcher with
  `--backend llamacpp` and the local `qwen3-14b` model (OpenAI-compatible server);
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
  `BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS` because each contains only one usable
  lap after the initial and incomplete laps are excluded;
- the analyzer correctly produces no comparisons and `--validate` returns failure;
- `auto_ingest_telemetry.py` classifies that expected outcome as skipped without
  weakening `validate_global_output`;
- neither case called an LLM, corrupted History or affects ready sessions.

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

Implemented H5.3 slice:
- H5.3a Python-owned shadow candidate builder
  `build_historical_coaching_candidates.py`;
- emits `SHADOW_OBSERVATIONAL_ONLY`, calls no LLM and renders no driver actions;
- H5.3b reproducible audit dataset and human review
  (`prepare_h5_3_audit_dataset.py`, `label_h5_3_audit_candidates.py`,
  `validate_h5_3_audit_labels.py`) with the closed review vocabulary
  `ACTIONABLE / OBSERVATIONAL_ONLY / NOT_COMPARABLE / AMBIGUOUS`;
- H5.3c controlled LLM selection over Python-authorized ACTIONABLE candidates
  (`historical_candidate_selection.py`, `validate_historical_candidate_selection.py`)
  with a closed response schema, no free text and no historical actions;
- real H5.3c checkpoint: DeepSeek `deepseek-v4-pro` selected three of six ACTIONABLE
  candidates (T6 Villeneuve primary, T15 Gresini secondary, T2 Tamburello context)
  and the dedicated validator passed;
- H5.3d deterministic separate renderer (`render_historical_debrief.py`) that labels
  current/historical lap times, total delta, comparable zones, limitations and
  authority without calling an LLM; real Imola section rendered `+0.600 s` / 11 zones;
- H5.3e dedicated validator and safe fallback
  (`validate_historical_debrief.py`) that rejects tampered sections and regenerates
  the deterministic section from validated sources when the artifact is invalid;
  the real Imola section passed validation with zero errors;
- H5.3f multitrack promotion gate (`assess_h5_3_promotion.py`); the real manifest
  verdict is `PROMOTION_READY` with the four tracks, both delta signs, a validated
  H5.3c selection and documented human review;
- the orchestrator `h5_3` stage is integrated as observational-only (candidates +
  deterministic section + validator) and returns `SKIPPED_NOT_APPLICABLE` when
  H4/H5.1/H5.2 prerequisites are absent; H5.3c LLM selection remains a separate
  manual tool.
- H5.3 Nivel 2 action policy (`historical_action_policy.py`,
  `validate_historical_actions.py`) constructs closed throttle/brake shadow action
  candidates for selected current-slower comparisons; speed/time never become
  actions and faster-lap candidates are withheld. The validator reconstructs the
  deterministic result from its hashed selection source. Production authority stays
  false (`historical_actions_authorized=false`).
- H5.3 runtime eligibility `0.2` carries the validated whole-lap delta sign through
  selection/action policy while retaining zone-local delta only as ranking evidence;
  imported policy and validator hashes now participate in orchestrator reuse.
- the additional runtime shadow pipeline uses one selection contract for its
  deterministic and optional LLM backends. Deterministic is the default, so normal
  orchestration performs no hidden API/local-model call. Stable artifacts are written
  under `data/generated/h5_3_shadow/<session>/` and never modify the visible debrief.
- Debrief refinement shadow audit
  (`audit_historical_actions_actionability.py`) classifies authorized historical
  actions as brake/throttle/mixed; the real artifact showed 2 mixed-cue candidates
  and promotes no channel preference or ranking formula.

Promotion status: all H5.3 slices are implemented in shadow; production promotion
gate verdict is `PROMOTION_READY`, but production historical coaching remains
`historical_actions_authorized=false` and is not integrated into the orchestrator.

See `docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md`. H5.3 must remain additive:
the current-session debrief and H5.1 coaching authority cannot change merely because
the roadmap exists.

H5.2 resolves both raw DuckDBs through History, applies exact context gates, compares
independent historical/current `LapAnalyzer` sources, validates the temporal delta and
emits observational spatial zone summaries.

H5.2 v0.2 preserves broad delta trends for audit and, when an exact validated
track/layout profile exists, splits them deterministically at profile boundaries
before LLM selection. Missing profiles use an explicit unlocalized fallback.

Circuit de la Sarthe track-profile checkpoint:
- exact identity: `Circuit de la Sarthe` / `Circuit de la Sarthe`;
- five complete GPS laps across three independent LMU Practice sessions;
- independent-session median reference-point offsets: 4 m and 8 m;
- independent-session maximum offsets: 22 m and 24 m;
- status: `VALIDATED_MULTI_SESSION`;
- ACO names are authoritative; the 19 profile segment numbers are not represented as
  the official FIA WEC 33-turn numbering.

See `docs/LA_SARTHE_TRACK_PROFILE_V0_1.md`.

### Track profile schema v2 — CLOSED SHADOW_ONLY

Schema v2 adds explicit `segments` array (straight/transition types) on top of
existing v1 `turns` array. All 6 golden profiles have v2 shadow counterparts
in `track_profiles/shadow_v2/`.

**Real A/B comparison:** `docs/TRACK_PROFILE_V2_REAL_AB_V0_1.md`

| Metric | Value |
|--------|-------|
| Tracks compared | 6 |
| v2 shadow profiles | 6 / 6 |
| H5.2 A/B classification | SEMANTICALLY_EQUIVALENT (all) |
| H5.3 invariants | IDENTICAL (all) |
| Coaching impact | IDENTICAL (all) |
| v2 segments assessed | 32 |
| Verdict | A) NO_MEASURABLE_BENEFIT |
| Promotion gate | BLOCKED_BY_NO_MEASURABLE_BENEFIT |
| pytest | 728 / 728 passed |
| Regressions | 55 / 55 passed |

**Status:** v2 stays SHADOW_ONLY. No production code modified.
v1 remains production authority. v2 may be re-opened only if a real-world
case demonstrates v1 localization is insufficient or segments contribute
measurable functional evidence.

See `docs/TRACK_PROFILE_SCHEMA_V2_PROMOTION_GATE_V0_1.md` and
`docs/TRACK_PROFILE_SCHEMA_V2_FINAL_REVIEW_V0_1.md`.

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

LLM episode-prompt shadow checkpoint:
- `run_llm_prompt_shadow.py` isolates experimental artifacts and records the
  prompt policy/hash without replacing production results;
- llama.cpp explicitly disables Qwen thinking, preventing hidden reasoning from
  exhausting the 8192-token output budget;
- the exact Imola DeepSeek V4 Pro A/B is tied at 4/43 repaired episodes (9.3%)
  with zero fallbacks on both production and shadow;
- Monza Flash (6/49 repairs) and Fuji Qwen3.6 35B A3B IQ2_M (1/18 repairs) are
  valid unpaired observations, not isolated prompt comparisons;
- `assess_llm_prompt_shadow_promotion.py` returns
  `PROMOTION_BLOCKED_INSUFFICIENT_PAIRED_EVIDENCE`: 1/3 exact pairs and 1/2
  tracks, with no regression and no measurable benefit;
- production prompt, ranking and coaching remain unchanged.

See `docs/LLM_PROMPT_SHADOW_PROMOTION_GATE_V0_1.md`.

Validation:
- pytest: `987 PASS / 0 FAIL / 0 SKIP`
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

Desktop interface v0.1 is available as `RaceEngineer.pyw` /
`race_engineer_gui.py`. It is a read-only session hub backed by orchestrator
`state.json` files. It lists recent runs, distinguishes History-only sessions from
validated debriefs, renders the next-stint plan and exposes pipeline status without
calling an LLM or changing History. The first real catalogue smoke test loaded 46
sessions successfully. See `docs/RACE_ENGINEER_GUI_V0_1.md`.

GUI v0.2 adds explicit telemetry selection, DeepSeek/llama.cpp/Ollama backend
selection and a live execution log. It invokes only `analyze_telemetry_file.py`,
so LMU-running, authorized-root, 5 MiB, 10-minute stability and two-valid-lap
gates remain authoritative. One process is allowed at a time, there is no cancel
button and the window refuses to close while analysis is active. See
`docs/RACE_ENGINEER_GUI_V0_2.md`.

GUI v0.3 adds a schema-4, strictly read-only History browser with search and lap
detail, plus a per-session H4 reference tab. It shows the selected historical lap
or the exact non-applicable result without changing coaching authority. The analysis
button uses a dedicated dark-red style. See `docs/RACE_ENGINEER_GUI_V0_3.md`.

GUI v0.4 adds a deterministic `Vueltas` tab, non-secret DeepSeek/llama.cpp model
settings and a black/neutral-grey theme. Settings preserve existing compatible
environment variables until saved, never store API keys and restrict llama.cpp URLs
to localhost. See `docs/RACE_ENGINEER_GUI_V0_4.md`.

GUI v0.5 adds local multi-term search and `Todas / Con debrief / Sólo History /
Fallidas` filters to the main session catalogue. Filtering never changes the exact
session/DuckDB mapping used by detail views or double-click analysis. See
`docs/RACE_ENGINEER_GUI_V0_5.md`.

GUI v0.6 adds the opt-in **Omitir espera 10 min** control for a finished telemetry
file the user explicitly wants to analyze immediately. The flag skips only file
age: LMU-running, authorized root, DuckDB/History, 5 MiB, History-first and two
valid lap gates remain mandatory. Automatic ingest is unchanged. See
`docs/RACE_ENGINEER_GUI_V0_6.md`.

GUI v0.7 adds a read-only **Comparación histórica** tab. It renders the H5.2 raw
lap identities, times, current-minus-historical delta and localization, then shows
the validated H5.2 LLM observation when available. Missing/non-applicable sessions
retain their exact stage status. The tab never authorizes historical actions or
replaces the current-session reference. See `docs/RACE_ENGINEER_GUI_V0_7.md`.

GUI v0.8 adds a read-only **Mapa** tab reconstructed from the selected session's
native LMU GPS channels. Extraction runs in a background thread, prefers the current
reference lap, caches by DuckDB mtime/lap and preserves local XY plus LMU Lap Dist
per point for later H5.2/track-profile zone overlays. Analysis reference laps are
matched to native GPS groups by duration; incomplete tails fail the completeness
gate instead of being drawn as a circuit. No CSV/GeoJSON is written.
See `docs/RACE_ENGINEER_GUI_V0_8.md`.

GUI v0.9 overlays deterministic H5.2 `zone_summaries` on the GPS map by aligned
LMU Lap Dist. Loss segments are red, gain segments green and the remaining circuit
grey. Clicking within 18 px selects a zone and shows its localized label, zone ID,
distance interval and deterministic delta change. This is read-only observational
inspection and does not promote zones to coaching. See `docs/RACE_ENGINEER_GUI_V0_9.md`.

GUI v1.0 adds validated `next_stint_plan` intervals as an independent blue map
layer. Priority clicks take precedence over overlapping H5.2 zones and show the
plan label, localized track name, distance interval and existing driver cues. The
layer requires an existing debrief plus `llm_validator = RUN/REUSED`; a failure in
a later H5 stage does not hide that valid artifact. See `docs/RACE_ENGINEER_GUI_V1_0.md`.

GUI v1.1 aligns native `Ground Speed`, `Brake Pos` and `Throttle Pos` to the same
complete GPS lap. Clicking any circuit point shows its distance and instantaneous
values; H5.2 zones and validated priorities additionally show descriptive min/mean/
max channel summaries for their exact distance interval. Missing optional channels
render as unavailable and never block the map. The white point marker can be dragged
continuously along the circuit and remains snapped to the closest rendered GPS
sample. The feature is read-only and changes
no coaching authority, selection or pipeline artifact. See
`docs/RACE_ENGINEER_GUI_V1_1.md`.

GUI v1.2 adds a full-lap chart below the GPS map with independent speed, throttle
and brake lanes on one `Lap Dist` axis. The draggable white map marker controls a
shared vertical chart cursor; selecting an H5.2 zone or validated priority shades
its exact interval behind the traces. The chart consumes only the already aligned
complete-lap native channels, remains read-only and changes no coaching or historical
authority. See `docs/RACE_ENGINEER_GUI_V1_2.md`.

GUI v1.3 raises the complete-lap visual alignment from 5 to 10 Hz and adds a bounded
distance-window controller to the telemetry chart. Mouse wheel zooms around the
pointer, `Shift + wheel` pans, **Restablecer gráfico** returns to the full lap and the
window follows the draggable map marker when it exits the visible span. Zoom never
changes source samples, zones, priorities or coaching authority. The real Imola
smoke test rendered 967 points and retained 194 samples per channel in a 20% window.
See `docs/RACE_ENGINEER_GUI_V1_3.md`.

GUI v1.4 surfaces the deterministic H5.4 P11 driver focus before the complete
validated next-stint plan. It accepts only an `ACTIVE` one/two-item focus whose count,
unique labels and plan subset are consistent; older or inconsistent artifacts fall
back to the original plan. Focus intervals use bright heavy blue on the GPS map and
non-focus plan intervals remain muted blue. Five recent real debriefs expose valid
two-item focus; the latest Imola view rendered A/C focus over the preserved A/C/B
plan. No ranking, cue or coaching authority changes. See
`docs/RACE_ENGINEER_GUI_V1_4.md`.

GUI v1.5 implements the H6.5 presentation-only polish while retaining Tkinter/ttk:
flat dark entries and comboboxes, 10 px scrollbars, consistent button states,
modernized Treeview headings/selection, cleaner notebook tabs and a compact flat
progress bar. No session logic, map/telemetry interaction, ranking or coaching
authority changed. See `docs/RACE_ENGINEER_GUI_V1_5.md`.

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
