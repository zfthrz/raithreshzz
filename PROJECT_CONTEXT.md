# Race Engineer — PROJECT_CONTEXT v1.0

> Canonical end-to-end onboarding context for coding agents and LLMs working on the Race Engineer repository.
> Baseline represented here: GUI v1.21, automatic H2 review queues, H5.4 P1–P11 and historical-shadow checkpoint 2026-08-26.
> Project name: **Threshzz's Telemetry Analysis LMU** (= Race Engineer).
>
> This is the detailed mental model of the project. `AGENTS.md` should instruct coding agents to read this file before non-trivial work.

---

## 0. How an agent must use this file

Before making changes:

1. Read this file completely.
2. Treat the generic runtime files and current tests as the operational source of truth.
3. Read `PROJECT_STATUS.md` for the latest short status and `README.md` for detailed usage when needed.
4. Inspect the exact code involved before changing behavior; do not reconstruct current behavior from old versioned files.
5. Preserve deterministic/LLM responsibility boundaries described below.
6. Run the relevant tests after modifications.
7. If a change alters architecture, contracts, runtime paths, version aliases, or project invariants, update this file in the same change.

Do **not** assume that an older design note is still current merely because it is detailed. The repository intentionally preserves provenance and superseded releases.

---

# 1. Project identity and objective

**Race Engineer** is a telemetry-analysis and coaching pipeline for **Le Mans Ultimate (LMU)**.

The project is not intended to be a generic chat assistant that looks at racing data. Its architecture deliberately separates:

- deterministic telemetry facts produced by Python;
- interpretation/prioritization/narrative produced by an LLM;
- persistent cross-session history;
- calibrated episode matching and pattern extraction;
- historical benchmarking;
- future raw cross-session comparison.

The user-facing goal is a concise race-engineer debrief that identifies the highest-value, evidence-backed driving changes for the next stint without inventing telemetry facts.

The intended normal command is:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

The default path is backend-free: `deterministic_debrief.py` produces the
full debrief without calling any LLM transport. Opt-in LLM backends are
available only for reproduction, benchmarks, or legacy workflows; they are
never invoked automatically by the product runtime.

`telemetria/` is the standard local location for LMU DuckDB recordings and is ignored by Git.

---

# 2. Non-negotiable architecture

## 2.1 Python owns facts

Python is authoritative for:

- lap identity and validity;
- reference lap selection;
- lap deltas;
- deterministic events;
- physical brake/throttle point detection;
- recurrence calculations;
- track location and track context;
- comparison quality gates;
- eligibility gates;
- persistent History facts;
- cross-session pair features;
- H2 matcher rules;
- H3/H4/H5 structural logic;
- validators and safety constraints.

The LLM must **not** silently recompute these facts from prose or raw-looking values.

## 2.2 The LLM owns interpretation, prioritization and wording

The LLM may:

- rank valid evidence;
- choose which authorized observations are useful coaching;
- synthesize an A/B/C plan;
- write a human-readable debrief;
- express qualitative changes toward the reference when authorized.

The LLM must **not**:

- invent braking/throttle distances;
- invent percentages;
- invent turns or track positions;
- add event counts that Python did not provide;
- infer understeer/oversteer, balance, grip, trajectory, stability or vehicle dynamics without explicit deterministic evidence;
- turn an observation into a driving target unless a deterministic detector/policy authorizes that transformation.

## 2.3 Speed is context, not a driving input

Speed may be propagated as context/evidence, but it is not itself treated as the controllable coaching input or target.

## 2.4 Validators are safety boundaries

Never weaken a validator merely to make a new output pass.

If a narrative is invalid but deterministic coaching is valid, prefer deterministic repair/fallback logic rather than relaxing the contract.

---

# 3. Critical domain semantics

## 3.1 Vehicle contexts must remain distinct

Never normalize these as equivalent:

```text
LMP2_ELMS
LMP2
```

`LMP2_ELMS` is the ELMS variant/context and must remain historically separate from the restricted WEC-style `LMP2` context.

This distinction matters for History, H2 calibration, matcher applicability, historical reference and future cross-session learning.

## 3.2 Track layout is part of hard context

`lmu_track_layout` is not decorative metadata. It participates in context isolation.

Do not match or pool sessions across incompatible track layouts merely because the circuit name is similar.

## 3.3 Prefer ambiguity over unsupported certainty

For H2 and similar learned/calibrated decisions:

```text
AMBIGUOUS > unsupported MATCH/REJECT
```

Human labels remain the strongest ground truth.

DeepSeek pseudo-labels/reviews are assistance and must never be silently mixed with human labels as though they had identical authority.

---

# 4. Current operational baseline

Checkpoint: **2026-08-26 GUI v1.21, H5.4 presentation and historical shadow** +
D3.x deterministic-first default and D2.9 production ranker (2026-08-25).

| Component | Current operational baseline |
|---|---|
| `race_engineer.py` | orchestrator v0.4 — estados nuevos usan `debrief`/`debrief_validator`; lectura legacy compatible |
| `race_engineer_gui.py` | v1.54 / discoverable shortcuts and persistent workspace |
| `analyze_telemetry.py` | v3.8 + Objective Python v6 |
| Brake point | 2.1 / schema 2.1 |
| Throttle point | 1.2.1 / schema 1.2 |
| Throttle episode sequence | 1.0 |
| Sustained throttle modulation | 1.0 |
| Full-throttle recurrence | 1.0 |
| Throttle modulation recurrence | 1.0 |
| Throttle physical point profile | 1.0 |
| Throttle coaching evidence gate | 1.0 / SHADOW |
| `llm_analysis.py` | 3.10.8.5.4 / Ollama `ingenierov3` |
| `llm_analysis_deepseek.py` | 3.10.8.5.4 / DeepSeek provisional v2 |
| `llm_analysis_llamacpp.py` | 3.10.8.5.4 / llama.cpp local (default `qwen3-14b`) |
| LLM output validator | v1.2 |
| `session_history.py` | v1.4 / History schema 4 |
| H2 matcher | v0.3 / provisional calibrated single context |
| H3 persistent patterns | v0.1 / derived + explicit idempotent History import |
| H4 historical reference | v0.2 |
| H5.1 dual reference | v0.2 |
| H5.2 | v0.2 profile-localized raw comparison + v0.1 validated observational LLM narrative |
| H5.2 interval telemetry evidence | v0.6 / corner-scoped normalized steering trace facts |
| H5.3 historical coaching debrief | roadmap only / shadow complete (H5.3a-f) + Nivel 2 action policy / production gated |
| H5.4 coaching precision | P1–P11 implemented / P10–P11 presentation-only |

Historical telemetry evidence v0.6 exposes normalized steering trace facts only
for intervals whose structured `location_type` is `corner`. Total variation is
normalized per 100 metres of actually observed comparable samples, while the
sign-change comparison is stored as an exact descriptive relation. This evidence
does not define a steering centre deadband, infer driver corrections, authorize
coaching, or alter ranking.
H5.3d renderer v0.2 may present those validated corner facts in the historical
section. It requires exact H5.2 interval bounds, stores the evidence source hash,
and renders only measurements (variation per 100 m and sign-change counts), never
an inferred correction or steering instruction.

Validated checkpoints relevant to the current working tree:

```text
full pytest (current working tree):  1359 PASS / 0 FAIL / 0 SKIP
Objective Python regressions:         55 PASS / 0 FAIL / 0 SKIP
Objective recovery check:             READY
```

The hidden scheduled-task action also completed a real manual execution with
`exit_code=0`, 68 source files scanned, no imports/errors and the backfill cooldown
preserved.

---

# 5. Source-of-truth hierarchy

When documents disagree, use this order:

1. **Current generic runtime code** (`race_engineer.py`, `analyze_telemetry.py`, `llm_analysis*.py`, `session_history.py`, etc.).
2. **Current automated tests and validators.**
3. `PROJECT_STATUS.md`.
4. `README.md`.
5. Current versioned notes for the relevant subsystem.
6. `legacy/` and historical notes only as provenance.

Do not promote a legacy file back to active status without understanding why it was superseded.

---

# 6. Repository conventions

## 6.1 Generic names for normal execution

Commands shown to the user should use generic script names without version suffixes, for example:

```powershell
python llm_analysis_deepseek.py analysis.json
python session_history.py ...
python race_engineer.py analyze "telemetria\archivo.duckdb"
```

Do not tell the user to execute `*_v3_10_8_5_4.py` when a generic operational alias exists.

## 6.2 Versioned release artifacts are still desirable

When producing a new release file for delivery/provenance, preserve an explicit version in the artifact name when appropriate.

Operational generic aliases should then be synchronized to the intended current release.

The project therefore distinguishes:

- **versioned artifact/release names** for provenance;
- **generic runtime aliases** for actual commands.

## 6.3 Generic aliases must not drift

At the current baseline:

```text
llm_analysis.py
    == llm_analysis_v3_10_8_5_4_ingenierov3.py

llm_analysis_ingenierov3.py
    == llm_analysis_v3_10_8_5_4_ingenierov3.py

llm_analysis_deepseek.py
    == llm_analysis_v3_10_8_5_4_deepseek_v2.py
```

Byte identity is an intentional project contract for these aliases at this checkpoint.

Do not update only the versioned release and leave the generic entry point stale.

---

# 7. Repository layout

Important paths:

```text
repo-root/
├─ telemetria/                      # local raw LMU DuckDB; ignored by Git
├─ data/
│  ├─ calibration_spa_lmp2_elms/    # known calibration/reference material
│  ├─ reference_sessions/           # deterministic historical session JSONs
│  ├─ generated/                    # regenerable runtime outputs; ignored
│  │  ├─ analysis/
│  │  ├─ llm_results/
│  │  ├─ llm_debug/
│  │  ├─ h4/
│  │  ├─ h5_1/
│  │  ├─ h5_2/
│  │  └─ runs/
│  ├─ local/                        # persistent local state; ignored
│  │  └─ race_engineer_history.duckdb
│  └─ raw/                          # optional raw imported material; ignored by default
├─ calibration_batches/             # reproducible H2 calibration runs/artifacts
├─ track_exports/                   # GPS / geometry exports
├─ track_profiles/                  # validated track profiles
├─ tests/
├─ legacy/                          # superseded code/docs retained for provenance
├─ scripts/
│  └─ repo_hygiene.py
├─ race_engineer.py
├─ runtime_paths.py
├─ analyze_telemetry.py
├─ llm_analysis.py
├─ llm_analysis_deepseek.py
├─ llm_analysis_ingenierov3.py
├─ validate_llm_analysis_output.py
├─ session_history.py
├─ episode_pair_features.py
├─ episode_pair_matcher.py
├─ build_persistent_patterns.py
├─ select_historical_reference.py
├─ build_dual_reference_context.py
└─ README.md
```

---

# 8. Runtime artifact policy / Git hygiene

Historically the repository mixed generated prompts, rejected attempts, final LLM output and source files inside `*_llm/` directories. Normal executions therefore modified dozens or hundreds of tracked files.

This is considered a repository hygiene bug, not desired behavior.

Current runtime paths are centralized in `runtime_paths.py`.

New runs should use:

```text
data/generated/analysis/
data/generated/llm_results/
data/generated/llm_debug/
data/generated/h4/
data/generated/h5_1/
data/generated/h5_2/
data/generated/runs/
data/local/race_engineer_history.duckdb
```

These are not source artifacts and must not normally be committed.

The repository ignores:

```text
telemetria/
data/generated/*
data/local/
*_llm/
*_llm_analysis*.json
race_engineer_history.duckdb
race_engineer_history_backup.duckdb
```

One-time cleanup of an old real Git checkout is performed by:

```powershell
python scripts\repo_hygiene.py
python scripts\repo_hygiene.py --apply-all `
  --verified-bundle "C:\ruta\backup.bundle" `
  --approved-head "SHA_COMPLETO_DE_HEAD"
```

The cleanup is intended to preserve useful local files while removing runtime garbage from Git tracking and moving superseded material to the correct locations.

The command without apply flags is audit-only. Every apply mode must verify an
external Git bundle containing the exact current `HEAD`, require explicit approval
of that full commit SHA, reject tracked working-tree changes and destination
collisions, and verify afterward that no protected SHA-256 content disappeared.

Do not reintroduce generated prompt/debug files into tracked source directories.

---

# 9. End-to-end normal pipeline

The intended current user flow is:

```text
LMU DuckDB
   ↓
analyze_telemetry.py --validate
   ↓
deterministic analysis JSON
   ↓
deterministic_debrief.py (default — 0 LLM calls)
   ↓
validate_llm_analysis_output.py
   ↓
History schema 4 idempotent import
   ↓
H3: normally SKIPPED_NOT_APPLICABLE in per-session flow
   ↓
H4 historical reference when target is eligible
   ↓
H5.1 dual-reference context
   ↓
H5.2 raw cross-session comparison when both DuckDBs resolve; otherwise SKIPPED_NOT_APPLICABLE
   ↓
H5.2 LLM observational narrative when LLM is explicitly enabled; historical actions remain disabled
   ↓
H5.3 deterministic historical section (observational) when H4/H5.1/H5.2 are valid
```

The orchestration entry point is:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

Useful switches:

```text
--history-db PATH
--force
--force-analyze
--force-debrief
--no-debrief
--no-history
--no-historical-context
--dry-run
```

Stage statuses are intentionally explicit:

```text
RUN
REUSED
SKIPPED_NOT_APPLICABLE
FAILED
```

A rerun should reuse valid stages rather than paying for an LLM call or regenerating every artifact unnecessarily.

Existing official H3 materializations can be reviewed together with:

```powershell
python maintain_h3_imports.py
```

This default is read-only. `python maintain_h3_imports.py --apply` is an explicit
operator action that imports only bundles already classified
`H3_READY_TO_IMPORT` by the production validator. It does not build H2/H3,
process conflicts or authorize coaching. The hidden scheduler runs only the
read-only form and publishes `data/local/h3_import_maintenance.json`; it never
passes `--apply`. A cheap History/official-bundle fingerprint reuses the existing
snapshot when inputs are unchanged.

After both H3 audits, the hidden scheduler atomically publishes the unified
read-only projection `data/local/h3_automation_status.json`. It records each
audit execution result, freshness, source fingerprints and the next safe operator
action per exact context (`MATERIALIZE_EXPLICIT`, `IMPORT_EXPLICIT`, `NONE` or
`REFRESH_AUDITS`). A failed or game-deferred audit marks the projection stale and
withholds every mutation action. This status never runs `--apply`, mutates History
or authorizes coaching.

Before creating missing official bundles, the in-memory gate can be audited with:

```powershell
python audit_h3_materialization_readiness.py
```

It executes the current authorized H2 classifier, H2→H3 gate and H3 builder without
writing their outputs. `MATERIALIZATION_READY` means the existing production logic
found at least one authorized MATCH and no H3 conflict; it is evidence for an
explicit later pipeline run, not permission for scheduler mutation.

`materialize_h3_context.py` automates that explicit pipeline run for exactly one
track/layout/vehicle context. It is read-only without `--apply`; apply mode accepts
only a fresh `MATERIALIZATION_READY` row, writes the normal three-file official
bundle without passing a History database, and verifies the resulting state is
`H3_READY_TO_IMPORT`. Import remains a separate explicit action.

`import_h3_context.py` implements that separate action for one exact context. It
requires fresh `H3_READY_TO_IMPORT`, checkpoints History, creates a physical
backup whose SHA-256 is verified against an unchanged source, invokes the
official transactional importer and requires `H3_IMPORTED` afterwards. GUI
v1.45 exposes it as `Importar H3`; no bulk-ready import is used by the GUI.

Completed isolated H3.2 projection labels can be summarized with
`audit_h3_projection_review.py`. It validates the exact queue hash and authority
contract, then reports human agreement by existing matcher rule/pattern plus raw
metric distributions. The queue is positive-only, so this evidence cannot estimate
recall or false negatives, define thresholds, calibrate H2, persist H3 membership
or authorize coaching.

The first explicit multi-context apply imported six validated bundles after a
checkpointed, SHA-256-verified physical History backup. Imola HYPER, Interlagos
LMP2_ELMS, Spa LMP2_ELMS, Spa LMP2_WEC, Fuji GT3 and Fuji LMP2_ELMS all returned
`RUN`; the post-import audit reports 7 imported exact contexts and 4 not applicable.
The full History validator passed and the hidden scheduler was re-enabled afterward.

State/signatures are stored under:

```text
data/generated/runs/<duckdb-stem>/state.json
```

Reusability is based on input/script/output signatures, not merely filename existence.

---

# 10. Deterministic analysis layer

`analyze_telemetry.py` is the deterministic telemetry-analysis core.

Current public version remains `3.8`, while a substantial Objective Python evolution has been integrated behind that interface through v6-era deterministic evidence layers.

Important conceptual outputs include:

- valid/invalid lap gate;
- reference lap;
- comparable laps;
- objective temporal validation;
- zone-level evidence;
- physical braking points;
- physical throttle points;
- throttle episode sequences;
- sustained throttle modulation;
- recurrence signals;
- action profiles;
- comparison-quality gating;
- next-stint deterministic plan material consumed by the LLM.

The deterministic layer must remain independently testable.

Regression infrastructure includes:

```powershell
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
python apply_objective_python_recovery_2026_08_13.py --check analyze_telemetry.py
```

Do not collapse deterministic analysis into the LLM prompt merely because the LLM could theoretically infer similar information.

---

# 11. Coaching behavior and evidence hierarchy

Current debrief behavior aims for a small number of high-actionability cues.

A zone normally presents at most:

1. the main `Qué cambiar` action;
2. a second cue only when another input is sufficiently authorized.

Current conceptual cue priority:

```text
physical onset/release point with authority
    > reference_action_profile
        > qualitative brake/throttle adjustment toward reference
            > validated steering cue
```

Within the repeated physical-point tier, the number of comparisons supporting
the point itself is evaluated before the broader recurrence count of its enclosing
region. This rule is channel-neutral: stronger point support wins whether the cue
belongs to brake or throttle.

Examples of qualitative transformations that can be valid when the underlying relationship is deterministic:

```text
more brake than reference     -> reduce brake
less brake than reference     -> increase brake
more throttle than reference  -> reduce throttle
less throttle than reference  -> increase throttle
```

However, an observed temporal relationship such as:

```text
brake happened first and throttle later, approximately 11 m apart
```

must remain an **observation** unless a deterministic detector explicitly authorizes a corresponding target.

Speed also remains observational context. When a repeated region contains both
lower and higher speed directions across different comparisons, the session render
must describe speed as variable between comparisons instead of presenting the two
directions as a single contradictory conclusion.

---

# 12. Important empirical coaching finding: brake vs throttle cues

A key current development issue is an observed asymmetry in user usefulness between physical brake cues and physical throttle cues.

During Fuji testing, release **3.10.8.1** often produced a more directly actionable debrief when the selected primary action was a braking-point/release-point change.

Later 3.10.8.5.x work added substantially richer throttle recurrence/profile/evidence logic and sometimes shifted priority toward throttle cues. The resulting cues can be objectively supported but may be less directly actionable when expressed as a simple spatial instruction such as “reapply throttle X metres earlier/later”.

Reason: a brake point is often a relatively unambiguous discrete event, while throttle reapplication may depend on the full sequence from turn-in through mid-corner and exit.

Therefore:

- do not assume brake and throttle point cues are equally interpretable just because both have spatial detectors;
- preserve the richer throttle context when selecting or wording throttle coaching;
- prefer strong, simple braking-point guidance when its evidence/actionability dominates;
- do not regress deterministic throttle evidence, but continue improving how it is prioritized and narrated.

Actionability policy `1.7` renders the closed vocabulary of known throttle reference
profiles as direct ordered actions (apply, release, reapply/sustain). When an authorized
physical onset/release point is also present, the point remains the concise primary cue
and the reference sequence becomes a separate secondary cue when the two-cue limit
allows it. Unknown future shape labels
retain the conservative descriptive fallback instead of being guessed.

The session-plan actionability shadow audit `0.1` validated four real DeepSeek Pro
artifacts and 12 priority zones. Seven primary cues were brake and five throttle.
Brake primary cues were five single-point and two multi-point instructions; throttle
primary cues were three point-plus-sequence, one qualitative alignment and one
sequence-only instruction in the pre-1.7 artifacts. This establishes structural
complexity asymmetry without showing systematic brake displacement. It does not
authorize a channel preference or complexity score. The v1.7 Monza deterministic
rerender preserved A/B/C order and moved the supported throttle sequence in zone B
from the physical-point sentence into `Segundo cue`.

H5.4 P10/P11 are deterministic presentation projections over the already authorized
plan. P11 exposes at most two focus items from the P10 presentation order and never
mutates, filters or re-authorizes `next_stint_plan`. GUI v1.5 presents that focus only
when its count, unique labels and complete-plan subset are consistent; otherwise it
falls back to the original three-zone plan. The complete validated plan always remains
visible for traceability.

This is an active product-quality topic, not a settled algorithmic rule.

The read-only mixed-cue presentation audit v0.2 compares the production combined
sequence against two alternatives without changing the plan. Across 53 current
validated debriefs it found 31 combined brake+throttle zones. Splitting both channels
into the two available cue slots would displace a structured reference action profile
in every case. A channel-neutral, threshold-free comparison based on the strongest
explicit physical-point `comparison_count` keeps the combined sequence when support
ties or no profile is available; it identifies 9/31 cases with one uniquely stronger
channel and preserves the profile there, while 22/31 fail closed to the production
sequence. These counts do not authorize promotion or a global brake/throttle
preference.

The subsequent exact-queue human review completed 9/9 cases: 5 favored focused
channel + profile, 3 favored the combined sequence and 1 was ambiguous. Support
margin alone did not explain the decisions. The only unanimous structural subgroup
was a uniquely dominant channel with at least two physical events: 4/4 favored the
focused presentation. In the current corpus all four are brake onset+release cases;
there is no reviewed multi-event throttle case, so this is not evidence for a
general channel rule. `build_mixed_cue_presentation_ab.py` reconstructs these cases
from exact source/queue/label hashes and emits a separate A/B artifact while keeping
production and `next_stint_plan` unchanged.

`maintain_mixed_cue_review.py` accumulates future evidence in numbered local
revisions. It creates a revision only when the exact review-item set changes and
migrates a human decision only when both `review_id` and the complete item snapshot
remain identical. New or changed cases stay pending; labels are never inferred. The
hidden History runner invokes this after a successful primary cycle as a non-blocking
shadow maintenance step, so a review-maintenance failure cannot invalidate History.
The first real revision migrated all 9 reviewed labels and an immediate rerun was
idempotent (`UP_TO_DATE`, 0 pending).

---

# 13. LLM layer

Current baseline:

```text
3.10.8.5.4
```

Operational files:

```text
llm_analysis.py                 # Ollama / ingenierov3
llm_analysis_ingenierov3.py     # explicit generic local backend alias
llm_analysis_deepseek.py        # DeepSeek provisional v2
llm_analysis_llamacpp.py        # llama.cpp local (OpenAI-compatible), default qwen3-14b
```

DeepSeek is the primary iteration backend; Ollama/`ingenierov3` is the local parity/checkpoint path.

The LLM stage should write:

- final result under `data/generated/llm_results/...`;
- prompts, retries, rejected content and debug under `data/generated/llm_debug/...`.

Never restore the old behavior of mixing final outputs and debug prompts in tracked `*_llm/` directories.

The output must pass `validate_llm_analysis_output.py` before downstream use.

### 13.1 Deterministic-first default (D3.x, 2026-08-25)

The LLM stage is **deterministic-first by default**:

The ongoing backend-relegation refactor keeps the historical artifact schema and
filename compatible while moving product-owned behavior into neutral modules.
`deterministic_comparison_decision.py` owns fail-closed quality/anomaly routes;
`deterministic_comparison_preparation.py` owns catalog construction order,
track localization, anomaly splitting and the mandatory-episode fail-closed check;
`deterministic_comparison_execution.py` owns route resolution, structured-response
validation, comparison rendering dispatch and final comparison-record construction;
`deterministic_debrief_input.py` owns the ordered load/validation/dataset/context
preparation contract;
`deterministic_global_fallback.py` owns the validated default global closure;
`deterministic_debrief_finalize.py` owns final audit/render composition; and
`deterministic_debrief_document.py` owns comparison/document construction,
serialization and the centralized compatible output path. These extractions do
not change coaching, gates, ranking, validators or artifact contents. The product
entrypoint is now fully backend-independent: normal execution calls the neutral
deterministic closure directly with zero LLM transport calls.
The runtime global-response stage calls the neutral deterministic closure directly;
the legacy global provider and its transport branch are no longer reachable from
the normal product stage, but remain temporarily available for explicit rollback.
The comparison stage likewise assembles the neutral response pipeline with direct
deterministic episode, D2.9 ranker and summary providers. Its legacy comparison
provider and transport-capable branches are no longer reachable from normal runtime.
`deterministic_debrief_wiring.py` now binds stage providers without selecting or
importing a backend, and `deterministic_debrief_presentation.py` owns the normal
console surface. The historical module still supplies several deterministic policy
callbacks, so the wiring layer uses the historical module as a compatibility surface
without introducing an LLM dependency.
`deterministic_input_contract.py` owns JSON loading, model validation, legacy lap
identity compatibility and temporal lap-time verification.
`deterministic_debrief_dataset.py` owns the bounded, schema-compatible cleanup of
comparison and episode evidence before debrief execution. `deterministic_track_context.py`
owns fail-closed validated-profile discovery and resolver loading. The normal input
stage no longer depends on historical-module callbacks.
`deterministic_comparison_stage.py` likewise owns the normal quality lookup,
episode-catalog construction, track localization and coaching-eligibility assembly;
the historical module no longer wires those deterministic preparation callbacks.
`deterministic_priority_contract.py` owns validation of ranker order/cuts, tier
derivation and immutable application to episode assessments. Normal comparison
execution injects this neutral contract rather than the historical implementations.
`deterministic_comparison_summary.py` owns ordering and selection of validated
episode text plus the established mixed-steering neutral fallback.
`deterministic_summary_validation.py` owns the corresponding backend-independent
grounding, numeric-content, steering-direction and reference-target contract. Normal
comparison execution now injects that neutral validator directly; the historical
validator remains only as a compatibility surface and no transport is reachable.
`deterministic_debrief_output.py` owns compatible artifact construction, timestamping
and persistence, while comparison execution calls the neutral renderer directly.
Neither filesystem output nor comparison presentation requires a backend provider.
`deterministic_episode_response.py` owns the factual channel-direction contract and
grounded episode fallback used by normal execution. The historical fallback remains
only for legacy retry/repair compatibility and is not reached by the product stage.
`deterministic_episode_validation.py` owns the matching per-episode grounding,
direction, steering and reference-target validation contract. Normal execution
injects it directly and no longer calls the historical episode validator.
`deterministic_comparison_validation.py` owns final validation of the assembled
comparison document, including episode identity, classification, grounding and
aggregate text. The normal comparison pipeline no longer calls its historical
backend counterpart.
Global validation is backend-independent in `deterministic_global_validation.py`.
The normal global contract consumes the complete neutral validator, including its
fail-closed temporal-action, zone-anchored steering, per-zone list consistency and
global direction-consistency guards. The historical backend name remains a
compatibility alias only.
`deterministic_global_render.py` owns the byte-compatible global debrief renderer
and its three strictly required presentation helpers. Normal finalization injects
this neutral renderer directly; the historical renderer remains available only for
compatibility and rollback.
`deterministic_priority_shadow.py` owns the unchanged D2.2–D2.4 ranker shadow
diagnostics consumed by normal comparison assembly. These audits remain
observational and do not alter production ordering, cuts or classifications; the
historical implementations remain compatibility surfaces only.
`deterministic_debrief_app.py` is the audited neutral composition root for all ten
`StageProviders` callables. It classifies direct neutral providers, the input
binding wrapper and the schema-compatibility persistence wrapper explicitly. The
historical runtime builder now delegates to this assembler and injects only legacy
artifact metadata plus usage presentation callbacks; historical `_stage_*`
wrappers are no longer reachable from normal assembly.
`deterministic_debrief_compatibility.py` names the five historical persistence
fields explicitly and maps them unchanged into the established filename/JSON
schema. The model, `deepseek_usage`, context, temperature and anomaly config fields
are compatibility data only: they select no provider and carry no coaching
authority. A future rename requires a separately versioned schema migration.
Runtime binding now injects `session_coaching.build_session_coaching_facts` and the
neutral output provider directly. Their historical wrapper functions remain only as
compatibility surfaces and are unreachable from the normal coordinator.

```text
RACE_ENGINEER_DETERMINISTIC_FIRST   default "1"
    -> episode interpretation, comparison summary and global prose are built
       by Python without calling the LLM transport

RACE_ENGINEER_EPISODE_DETERMINISTIC =0  opt-out per mode
RACE_ENGINEER_SUMMARY_DETERMINISTIC =0
RACE_ENGINEER_GLOBAL_DETERMINISTIC  =0

RACE_ENGINEER_DETERMINISTIC_FIRST=0     disables the default globally;
                                        a specific flag =1 still forces it
```

The priority ranker (`get_validated_comparison_ranker_response`) is now also
deterministic by default: D2.9 product policy
(`product_priority_ranker.build_product_priority_ranker_response`) owns the
PRIORITARIO / SECUNDARIO / NO_ACCIONABLE classifications that feed the render
and the deterministic summary ordering. The default pipeline is therefore
100% deterministic; set `RACE_ENGINEER_LLM_RANKER=1` to restore the LLM ranker
as rollback. Episode fallback
(`build_deterministic_grounded_episode_fallback`) reconstructs the contract for
901/901 real corpus episodes; genuinely interpretive episodes fail closed
(REJECTED) instead of degrading silently.

The H5.2 observational narrative (D3-L5) is non-blocking: a backend failure
marks `h5_2_llm = SKIPPED_NOT_APPLICABLE` and the completed analysis still
passes. Details: `docs/D3_LLM_RUNTIME_DEPENDENCY_AUDIT_V0_1.md`.

---

# 14. H1 — persistent History

Primary implementation:

```text
session_history.py
version: 1.4
schema: 4
```

Default DB:

```text
data/local/race_engineer_history.duckdb
```

History import is intended to be idempotent.

History is a structured evidence store, not a license to use prior sessions as coaching truth.

Cross-session historical evidence remains constrained by context and eligibility gates.

History schema assumptions in calibration/orchestration code must remain aligned with schema 4. Calibration batch orchestrator 1.5 declares this dependency explicitly and the project-contract suite verifies it, preventing the stale schema-3 gate from returning silently.

---

# 15. H2 — cross-session episode matching/calibration

H2 asks whether driving episodes from different sessions represent the same underlying repeated behavior/pattern strongly enough to be considered related.

Current matcher:

```text
episode_pair_matcher.py
MATCHER_VERSION = 0.3
```

The matcher is **not yet a universally calibrated multi-track/multi-vehicle model**.

Current thresholds are provisional and calibrated for limited known context. Do not copy them to unrelated circuit/layout/vehicle contexts without calibration evidence.

Hard context isolation is fundamental. Relevant context includes at least vehicle variant and track/layout identity.

Main ecosystem:

```text
episode_pair_features.py
pair_review_queue.py
label_episode_pairs.py
build_calibration_dataset.py
calibration_feature_report.py
episode_pair_matcher.py
validate_episode_pair_matcher.py
audit_episode_pair_matches.py
prepare_calibration_batch.py
```

The calibration system intentionally preserves reproducible batch artifacts under `calibration_batches/`.

Human labels remain stronger than model-assisted labels.

`auto_calibrate_matcher.py` aggregates those human labels only as a shadow audit.
Its diagnostic contexts always use `authorized: false`; production matchers never
read its generated report. Promotion remains an explicit reviewed source change.

Queue maintenance does not create a new full batch while the newest batch for the
same exact context still has a pending human queue. The read-only retention audit
classifies old unlabeled batches without deleting or moving evidence.

---

# 16. H2.2 — DeepSeek-assisted review

H2.2 uses DeepSeek as a pre-reviewer/assisted reviewer for ambiguous episode pairs.

It is designed to accelerate human calibration work, not replace ground truth.

Important rule:

```text
DeepSeek pseudo-label != human label
```

Never silently merge them as equivalent training truth.

Relevant files include DeepSeek review queues, benchmark queues, review outputs, validators and selection audits under the calibration batch directories.

A blind benchmark path exists to measure whether assisted review is trustworthy enough for a specific use before adopting it broadly.

---

# 17. H3 — persistent patterns

Current implementation:

```text
build_persistent_patterns.py
H3_VERSION = 0.1
expected matcher = 0.3
```

H3 is derived from a calibrated H2 matcher run. It is **not** forced on every new telemetry session.

`run_h3_pipeline.py` is the official materialization path:

```text
episode_pair_features.json
    -> authorized H2 decisions
    -> H2 authority gate
    -> persistent_patterns.json
    -> optional explicit validated History import
```

Omitting `--history-db` remains read-only. Supplying it adds an auditable History
stage with `RUN / REUSED / SKIPPED_NOT_APPLICABLE / FAILED`. The import reuses the
existing schema-4 pattern tables and preserves source hashes, H3/matcher versions,
authorized matcher and baseline/promotion policy versions, authority scopes, exact
track/layout/vehicle context, members and pair evidence. Its stable identity excludes
volatile timestamps, so rematerializing the same authorized evidence is idempotent.

State semantics are strict: two-session `cross_session_repeat` rows are derived
observational evidence and are not promoted to `persistent_pattern`; the latter still
requires the configured minimum of three independent sessions. Any
`conflict_review_required` run is withheld. Track-baseline authority may contribute
MATCH only; inherited REJECT blocks import. History validation rechecks those
provenance constraints. None of these states changes `session_reference`, ranking,
H4/H5 authority or `next_stint_plan`.

Real Imola HYPER validation on a temporary copy of History produced 26 MATCH,
298 AMBIGUOUS, 0 REJECT and 14 `cross_session_repeat` classes with zero conflicts.
Exactly one compatible run and 14 derived rows were stored; a full rerun returned
`REUSED`, inherited REJECT remained zero and the History validator passed. The real
History database was not modified during this checkpoint.

`h3_import_readiness.py` adds a read-only operational bridge before scheduler
automation. It discovers only already-materialized official H3 bundles, validates
them through the same History import contract and reports exact-context states:
`H3_NOT_APPLICABLE`, `H3_READY_TO_IMPORT`, `H3_IMPORTED`, `H3_CONFLICT` or
`H3_FAILED`. It never runs H2/H3, writes History or changes coaching authority.
Track Readiness v0.8 and GUI v1.39 expose this state independently from calibration
readiness; a ready bundle still requires explicit import.

H3.1 adds a per-session observational materialization step through
`select_session_persistent_patterns.py`. For an exact calibrated
track/layout/vehicle context with an imported pattern run, it selects only the
current session's stored `session_id + episode_pk` memberships from the latest
compatible snapshot. It does not spatially rematch new episodes, add
tolerances, authorize historical actions, alter `next_stint_plan`, or affect
ranking. Exact membership is never inferred for a newer session absent from
that snapshot.

H3.2 extends that fail-closed path for sessions absent from the snapshot. It
builds the existing neutral H2 pair features against each recurrent pattern's
stored representative episode and calls the unchanged matcher `0.3`. Only an
automatic `MATCH` is emitted as a projected observational edge; `AMBIGUOUS`,
`REJECT`, missing representatives and non-automatic results remain withheld.
The projection is not persisted as pattern membership and has no coaching or
ranking authority.

`audit_h3_runtime_utility.py` adds a separate read-only corpus-observability layer.
It consumes only generated H3.1, H4 and H5.2 JSON artifacts, keeps exact stored
membership distinct from calibrated H3.2 projection, and measures runtime coverage,
same-context pattern recurrence and complementarity with H5. It never opens History,
calls H2/LLM, changes a selection, applies a threshold or labels a false positive.
Its review signals are counts requiring later human interpretation, not promotion
evidence. The first real audit covered 49 sessions: 33 had recurrent or projected H3,
22 combined H3 with H5, 11 had H3 without H5 and 16 had neither; authority,
duplicate-identity and cross-context-collision checks were all zero.

`audit_h3_projection_stability.py` drills into the generated H3.2 subset without
rerunning the matcher. It groups only valid automatic MATCH edges by exact
track/layout/vehicle/pattern identity and reports independent projected sessions,
matcher rule IDs and whether the pattern also appears as exact runtime membership.
No repeated count is interpreted as a threshold. The first corpus audit found 102
edges across 27 patterns and 13 sessions: all 21 Spa LMP2_ELMS patterns appeared in
2–8 projected sessions, while six Interlagos patterns appeared in one projected
session and also existed as exact runtime membership. This supports human review of
Spa projection edges, not automatic persistence or promotion.

`prepare_h3_projection_review.py` reconstructs those generated projection pairs from
History in read-only mode using the neutral H2 feature builder. It includes every
valid edge for an operator-selected exact context, applies no threshold or sampling,
deduplicates only identical physical episode pairs, and writes an ignored local queue.
`label_h3_projection_pairs.py` reuses the existing human semantics
`SAME / DIFFERENT / AMBIGUOUS / SKIP` while enforcing the isolated scope
`H3_2_PROJECTION_VALIDATION_ONLY` in both queue and labels. These labels do not enter
normal H2 calibration, persist H3 membership or authorize coaching. The initial Spa
LMP2_ELMS queue contains all 96 projected edges as 96 unique review pairs.

Normal `race_engineer.py analyze` reports `H3 = RUN` only when H3.1 can
materialize the latest compatible snapshot. Contexts without an imported run
remain:

```text
H3 = SKIPPED_NOT_APPLICABLE
```

unless/until a suitable calibrated matcher run for that context can be identified and integrated safely.

Known real Spa batch result at the integration checkpoint:

```text
116 episodes
51 pattern classes
12 persistent_pattern
9 cross_session_repeat
30 single_observation
0 conflict_review_required
```

This demonstrates the layer works on real data, but it does not imply general calibration across all tracks/vehicles.

A separate Monza Hypercar calibration batch now provides initial human evidence from
4 independent Toyota sessions. Its 24 reviewed pairs contain 9 `SAME`, 13
`DIFFERENT` and 2 `AMBIGUOUS` labels. The session-level leakage-safe split retains
13 calibration pairs but no internal evaluation pairs, so its status is
`READY_FOR_MORE_REAL_DATA`. It does not authorize Monza matcher thresholds, automatic
matching or H3 patterns. See `docs/H2_MONZA_HYPER_CALIBRATION_V0_1.md`.

A separate Monza `LMP2_ELMS` batch contains 3 independent IDEC Sport #18 sessions
and 24 human-reviewed pairs: 11 `SAME`, 12 `DIFFERENT` and 1 `AMBIGUOUS`. Its
leakage-safe split retains 5 calibration pairs and no internal evaluation pairs,
with 19 cross-partition pairs excluded. Its status is also
`READY_FOR_MORE_REAL_DATA`; it does not authorize matcher thresholds, automatic
matching or H3. See `docs/H2_MONZA_LMP2_ELMS_CALIBRATION_V0_1.md`.

---

# 18. H4 — historical reference selection

Current selector:

```text
select_historical_reference.py
version = 0.2
requires History schema 4
```

H4 selects an eligible historical benchmark under strict context/safety gates.

Its output is observational historical context, not automatically the authority for current-session coaching.

Example from Spa integration testing:

```text
current race reference:
R lap 3 = 125.460 s

historical benchmark:
Q lap 4 = 124.320 s

gap:
+1.140 s to historical benchmark
```

The value of H4 is to answer “what stronger historical performance exists in compatible context?” without corrupting the current session’s deterministic coaching reference.

---

# 19. H5.1 — dual reference context

Current builder:

```text
build_dual_reference_context.py
version = 0.2
schema = 1.0
```

H5.1 explicitly separates two references:

```text
session_reference
    = authority for current coaching

historical_reference
    = observational benchmark/context
```

This separation is a **hard architectural invariant**.

Never make `historical_reference` silently replace `session_reference` as the coaching truth.

Historical performance may be faster, but without raw validated cross-session comparison it does not automatically explain what the driver should change in the current session.

---

# 20. H5.2 — raw cross-session comparison

Current implementation:

```text
build_cross_session_comparison.py
version = 0.2
schema = 1.1
validator = validate_cross_session_comparison.py
```

H5.2 resolves the current and selected historical raw DuckDBs through History,
requires exact track/layout/vehicle/car context, opens two independent
`Telemetry`/`LapAnalyzer` instances, and reuses `DeltaComparison` plus
`SectorAnalysis` on a common spatial grid.

`DeltaComparison` remains backward compatible with its one-session constructor and
accepts an optional second `LapAnalyzer` for the current/comparison lap.

The output contains deterministic temporal validation and preserves the original
delta-trend zones for audit. When an exact track/layout profile with validated status
exists, H5.2 splits those trends at profile turn boundaries and exposes only the
localized summaries to the historical LLM. The profile identity, status, source hash
and localization mode are validated. Without an exact profile, H5.2 keeps an explicit
unlocalized fallback rather than guessing circuit boundaries.

After a valid H5.2 raw comparison, the orchestrator may also build
`h5_2_telemetry_evidence` v0.5. It aligns the current and historical reference laps
on their common `Lap Dist` coverage and emits deterministic interval samples for
speed, throttle, brake, discrete gear, accumulated delta, and separate signed versus
magnitude steering facts. The steering evidence is observational and cannot authorize
steering coaching or relax its existing gate. The artifact is written
under `data/generated/h5_2_telemetry_evidence/<session>/`, has its own validator and
reuse signature, and fails non-blocking so H5.3 and the normal debrief can continue.
It is strictly observational: it does not modify the H5.2 zone summaries, authorize
historical actions, change ranking or replace `session_reference`.
Version 0.4 also records total steering variation and exact sign-change counts
for both traces. These are unclassified morphology facts: no threshold labels a
trace as intentional or corrective and they do not affect coaching authority.

Session coaching also exposes `steering_coaching_shadow` v0.1. It derives only
from Python priority findings that already contain a `steering_magnitude`
channel, an unambiguous Python direction and a valid physical interval. It
records the corresponding adjustment toward the reference, but remains
observational: it does not call an LLM, mutate `next_stint_plan`, affect ranking
or authorize a steering instruction. Mixed directions and missing/invalid
intervals fail closed with explicit reason codes.
Repeated candidates reuse the existing recurrence-region ordering and exact
direction agreement. The shadow exposes at most one selected secondary
candidate per session; this selection still has no driver-facing authority.
The separate deterministic steering policy v1.0 may promote that single
candidate as a secondary cue only when it overlaps an existing plan zone with
exactly one stronger cue. It never creates a steering-only plan item,
displaces brake/throttle/profile cues, changes ranking or makes a causal claim.
This is the only path that can turn the shadow selection into visible coaching.

At v0.2 it deliberately keeps:

```text
session_reference_remains_authority = true
historical_actions_authorized = false
```

The real Fuji validation checkpoint compared historical session 7 lap 8 against
current session 8 lap 5, reproduced `current - historical = +1.280 s`, passed temporal
validation, emitted 7 spatial zone summaries, and then reused the H5.2 stage on rerun.

When either raw DuckDB cannot be resolved, the orchestrator reports:

```text
H5.2 = SKIPPED_NOT_APPLICABLE
```

The dedicated H5.2 LLM v0.1 contract consumes only the compact evidence subset built
by Python and selects at most three localized zone IDs plus observation/limitation
codes already authorized for each zone. LLM free text is disabled.
`validate_historical_llm_analysis.py` rejects unknown zones, extra keys, unauthorized
codes, tampered deterministic evidence or any change in coaching authority. Python
owns every statement, exact distance and delta in the final Spanish rendering.

This authorization is for observational narrative only. It does not authorize
historical coaching actions and does not let `historical_reference` replace
`session_reference`.

`audit_h5_2_zone_selection.py` provides an offline shadow comparison of validated
H5.2 model selections. It ranks the same Python-owned zones independently by absolute
delta impact, absolute delta per 100 m and corner-only impact, then reports overlap
without changing the prompt, production selection or coaching authority. On Monza,
Pro and Qwen 27B matched the absolute-impact top three, while no tested model matched
the intensity top three; short segments dominated that intensity ranking. On Imola,
Pro matched both rankings 3/3. This confirms that neither raw impact nor raw intensity
is sufficiently general to become a deterministic relevance formula from the current
two-track audit. The audit must remain `SHADOW_OBSERVATIONAL_ONLY` until broader real
data supports a production rule.

Do not fake H5.2 by comparing only derived History rows or LLM prose and calling it raw telemetry comparison.

---

## 20.1 H5.3 — future historical coaching debrief

H5.3 is an explicit future objective, not a current production capability. Its goal
is to add a separate debrief comparing the current session reference against the
fastest compatible historical reference, while preserving the normal session debrief
unchanged.

Current authority remains:

```text
H5.3 status = ROADMAP_ONLY
session_reference_remains_authority = true
historical_actions_authorized = false
```

The implementation must be additive and consume validated H4/H5.1/H5.2 artifacts.
It must not reinterpret raw telemetry inside the LLM, change H4 selection, replace
the current-session A/B/C plan, or weaken any existing validator. The detailed staged
contract and acceptance criteria are in
`docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md`.

The first authorized development slice H5.3a is implemented as the standalone shadow
builder `build_historical_coaching_candidates.py`. It consumes validated H5.1/H5.2
JSON, emits deterministic `SHADOW_OBSERVATIONAL_ONLY` candidate records from
localized H5.2 zones, and calls no LLM and renders no driver instructions. It is
integrated into the normal orchestrator only as an observational stage. H5.3b adds the reproducible audit dataset
and human-review tooling (`prepare_h5_3_audit_dataset.py`,
`label_h5_3_audit_candidates.py`, `validate_h5_3_audit_labels.py`) with the closed
vocabulary `ACTIONABLE / OBSERVATIONAL_ONLY / NOT_COMPARABLE / AMBIGUOUS`. H5.3c
adds controlled LLM selection over the Python-authorized ACTIONABLE candidates
(`historical_candidate_selection.py`, `validate_historical_candidate_selection.py`)
with a closed response schema, no free text and no historical actions. Later
promotion still requires multitrack validation and a dedicated validator.
On the real Imola/Monza dataset, DeepSeek `deepseek-v4-pro` selected three of the
six ACTIONABLE candidates and the dedicated H5.3c validator passed.
H5.3d adds the deterministic separate renderer (`render_historical_debrief.py`):
Python labels the current/historical lap times, total delta, comparable zones,
limitations and authority without calling an LLM; the real Imola section rendered
`+0.600 s` with 11 localized zones. H5.3e adds the dedicated validator and safe
fallback (`validate_historical_debrief.py`): it rejects tampered sections, missing
or invented zones, source-hash mismatches and authority changes, and regenerates the
deterministic section from validated sources when the artifact is invalid. The real
Imola section passed validation with zero errors. H5.3f adds the multitrack promotion
gate (`assess_h5_3_promotion.py`); the real manifest verdict is
`PROMOTION_READY` with all four tracks, both delta signs, a validated H5.3c
selection and the documented human review
(`docs/H5_3_AUDIT_REVIEW_2026_08_17.md`). The roadmap is fully implemented in shadow;
the orchestrator now runs an observational `h5_3` stage (candidates + deterministic
section + validator) that returns `SKIPPED_NOT_APPLICABLE` when prerequisites are
absent. The additional H5.3 runtime shadow pipeline evaluates eligibility, selects
up to three candidates and validates closed-vocabulary action candidates. It uses a
single selection contract for deterministic and LLM backends, defaults to the
deterministic backend, and calls an LLM only when `H5_3_BACKEND` explicitly requests
one. It writes `candidate_eligibility.json`, `candidate_selection.json`,
`historical_actions.json` and `shadow_pipeline.json` under
`data/generated/h5_3_shadow/<session>/`. Nivel 2
(`historical_action_policy.py` + `validate_historical_actions.py`) constructs shadow
action candidates for current-slower comparisons only; speed and time codes never
become actions, faster-lap candidates are withheld, `session_reference` remains the
coaching authority and `historical_actions_authorized` remains false.

H5.3f v0.2 (`assess_h5_3_promotion_v0_2.py`) adds a reviewed-action evidence gate
without replacing the v0.1 structural gate. After the whole-lap sign correction,
all seven real shadow artifacts were replayed deterministically and their review
queue was rebuilt. Exact-snapshot migration preserved only 11 unchanged labels and
correctly required nine new reviews. Queue v4 contains 20/20 reviewed items
representing 21 occurrences across all four required tracks: 12 `ACTION_USEFUL`,
3 `CORRECTLY_WITHHELD`, 1 `WITHHELD_BUT_ACTIONABLE` and 4 `AMBIGUOUS`. The real gate
remains `EVIDENCE_INCOMPLETE` because five labels are non-affirmative and isolated
`increase_brake`/`reduce_brake` coverage is absent. The review shows that whole-lap
anti-regression is safe but potentially over-broad for locally actionable losses;
it must be revised separately rather than weakened automatically.

H5.3 runtime eligibility v0.2 preserves the whole-lap `total_delta.sign` separately
from each zone's local `delta_change_s`. Local losses remain eligible for shadow
selection, but the action-policy anti-regression guard uses only the validated
whole-lap sign. A real Interlagos replay (`-0.180 s` current minus historical)
therefore yields zero actions and three `current_lap_faster_no_actions` withheld
candidates. The orchestrator reuse signature includes every imported H5.3 shadow
policy/validator module, preventing stale pre-fix action artifacts from being reused.
This runtime evidence has now received explicit human review. It closes structural
coverage of `current_faster`, but the `WITHHELD_BUT_ACTIONABLE` and `AMBIGUOUS`
results prevent production promotion and motivate richer quantitative review output.

H5.3g adds that richer output without changing policy. The deterministic auditor
`audit_h5_3_faster_lap_withholding.py` reconstructs every reviewed
`current_faster + WITHHELD` occurrence from its hashed action and selection sources;
`validate_h5_3_faster_lap_withholding.py` rebuilds the complete document and rejects
tampering or an authority change. On queue v4 it found six reviewed cases with full
quantitative evidence: 1 `CORRECTLY_WITHHELD`, 1 `WITHHELD_BUT_ACTIONABLE` and 4
`AMBIGUOUS`. The actionable exception was Interlagos T12 Junção with a local
`+0.294 s` loss despite a globally faster lap. This is evidence that the whole-lap
guard may be over-broad, not permission to remove it: the next policy experiment
must remain shadow, local, independently reviewed and fail closed.

H5.3h (`evaluate_h5_3_local_loss_policy.py`) evaluates the first deliberately
conservative local-policy hypothesis without modifying `historical_action_policy.py`.
A case becomes `LOCAL_POLICY_CANDIDATE` only when its human label is
`WITHHELD_BUT_ACTIONABLE`, every occurrence has spatial and throttle/brake evidence,
and every local loss is at least `0.20 s`. Candidates remain explicitly unauthorized
and no action wording or channel direction is generated. The real v0.1 evaluation
produced one candidate (Interlagos T12 Junção) and retained the other five cases.
Its exact-reconstruction validator passed; independent confirming cases are required
before testing any action mapping.

Two additional Interlagos LMP2_ELMS sessions expanded the exact review queue to v5:
23/23 items representing 24 source occurrences. The three new globally faster-lap
cases were reviewed as 2 `WITHHELD_BUT_ACTIONABLE` and 1 `AMBIGUOUS`. H5.3h now
retains three unauthorized local-policy candidates and withholds six cases.
H5.3i (`audit_h5_3_local_loss_recurrence.py`) groups those candidates by validated
track/layout/vehicle context, exact location and numeric channel direction. Its first
real audit found zero exact-zone recurrence and one cross-zone pattern: Interlagos
T8 Pinheirinho and T12 Junção both showed lower speed, lower throttle and higher
brake across two independent sources. Cross-zone repetition is context only and must
not be treated as confirmation of either corner or as action authority.

`maintain_h5_3_action_review.py` now automates the mechanical review preparation.
It validates every generated `historical_actions.json`, compares the deterministic
queue with the latest numbered queue/labels pair, and creates the next revision only
when the reviewed snapshot changed. Unchanged labels migrate only by exact
`review_id + item_snapshot`; no label is invented. `hidden_history_ingest.py` runs
this maintenance after successful History maintenance without opening a console.
Failures are logged as non-blocking H5.3 warnings, while state and pending count are
written to `data/local/h5_3_review_maintenance.json`. The first real run detected all
8 artifacts and correctly returned `UP_TO_DATE`, revision v5, pending 0.
When pending reaches zero, the same maintenance now reconstructs and validates H5.3g,
H5.3h and H5.3i in sequence. Any pending human case stops this chain at
`WAITING_FOR_HUMAN_REVIEW`; no inference is attempted. The real v5 automatic chain
returned `AUDITS_CURRENT` with 9 faster-lap withheld cases, 3 unauthorized local
policy candidates, 0 exact-zone recurrences and 1 cross-zone pattern.

---

# 21. Track profiles and nomenclature

The project has tools and data for track geometry/location and human-readable turn naming, including validated profiles for Fuji, Imola, Interlagos, Monza, Spa and Circuit de la Sarthe.

Typical tooling includes:

```text
extract_lmu_track_gps.py
detect_track_turns.py
track_location.py
track_profiles/
track_exports/
*_nomenclature*.json
```

Track naming should be grounded in validated profile/nomenclature data rather than guessed from approximate telemetry position.

Be careful with circuit variants/layouts.

The Circuit de la Sarthe v0.1 profile is validated on five complete GPS laps from
three independent LMU sessions. It uses the exact track/layout identity
`Circuit de la Sarthe` and ACO 2026 corner names. Its 19 segment numbers are
project-local localization identifiers, not the FIA WEC 33-turn numbering. This is
intentional: long complexes generate multiple line-dependent curvature maxima, so
the named interval is authoritative. See
`docs/LA_SARTHE_TRACK_PROFILE_V0_1.md`.

The authoritative operational workflow for creating and promoting LMU track
profiles is `docs/TRACK_PROFILE_CREATION_AND_VALIDATION.md`. It requires exact
track/layout identity, a fail-closed `VALIDATED_SINGLE_SESSION` phase, a stable
independent session, per-lap deterministic geometry audits and explicit reviewed
promotion. LLM output is never geometry or nomenclature authority.

### Schema v2 — CLOSED SHADOW_ONLY

Schema v2 adds explicit `segments` array (straight/transition types) on top of
the v1 `turns` array. All 6 golden profiles have v2 shadow counterparts in
`track_profiles/shadow_v2/`.

Real A/B comparison: `docs/TRACK_PROFILE_V2_REAL_AB_V0_1.md`

- **H5.2 A/B classification:** SEMANTICALLY_EQUIVALENT (all 6 tracks)
- **H5.3 invariants:** IDENTICAL (all 6 tracks)
- **Coaching impact:** IDENTICAL (all 6 tracks)
- **v2 segments assessed:** 32
- **Verdict:** A) NO_MEASURABLE_BENEFIT
- **Promotion gate:** BLOCKED_BY_NO_MEASURABLE_BENEFIT

v1 remains production authority. v2 shadow infrastructure preserved in
`track_profiles/shadow_v2/` as experimental. No production code was modified.
v2 may be re-opened only if a real-world case demonstrates v1 localization is
insufficient or segments contribute measurable functional evidence.

See `docs/TRACK_PROFILE_SCHEMA_V2_PROMOTION_GATE_V0_1.md` and
`docs/TRACK_PROFILE_SCHEMA_V2_FINAL_REVIEW_V0_1.md`.

---

# 22. Comparison Quality Gate

An extremely non-representative lap can be excluded from the coaching aggregate while still remaining present in the deterministic JSON as ground truth.

When excluded before the LLM call:

- the lap is not erased;
- it does not participate in recurrence/coaching A/B/C;
- unnecessary LLM work is avoided.

The output validator recognizes this path only when the deterministic quality
status, `session_plan_eligible=false`, zero-attempt audit fallback, exact structured
fallback and exact excluded-comparison render all agree. Eligible episode IDs keep
their original identity and may therefore contain a gap where an anomalous episode
was separated for audit; they must remain positive, unique and ordered.

Do not confuse “excluded from coaching aggregation” with “deleted/invalid telemetry”.

---

# 23. Fallback and repair philosophy

The project prefers preserving deterministic truth and repairing presentation rather than losing a valid session because the LLM made a narrative mistake.

Current behavior can include:

- deterministic-first default for episode interpretation, comparison summary and
  global prose (D3.2–D3.4) with per-mode opt-out via `RACE_ENGINEER_*_DETERMINISTIC=0`;
- deterministic repair of badly anchored steering conclusions;
- revalidation after repair;
- deterministic global fallback derived from `next_stint_plan` if narrative output remains invalid.

Again: validators should not be weakened for convenience.

The H5.2 observational narrative is non-blocking (D3.1): it can be skipped
without failing an otherwise complete analysis.

---

# 24. Testing and validation contract

Minimum useful project checks after integration-sensitive changes:

```powershell
python -m pytest -q
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
python apply_objective_python_recovery_2026_08_13.py --check analyze_telemetry.py
```

For a real local environment with telemetry available, also exercise:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

A coding agent must not claim success merely because code imports. Report actual test output and distinguish:

- passed;
- failed;
- skipped due to environment/data;
- not run.

When a test fails, first determine whether code, fixture or contract is stale. Do not automatically “fix” production behavior to satisfy an outdated fixture.

---

# 25. Dependencies and environment

Core Python requirements:

```text
numpy>=1.26
pandas>=2.2
duckdb>=1.0
```

Development:

```text
pytest>=8
ruff>=0.6
```

The primary user environment is Windows/PowerShell. Commands intended for the user should therefore be Windows-friendly unless explicitly discussing Codespaces/Linux.

There is also GitHub Codespaces support for calibration/review workflows.

DeepSeek credentials/configuration must remain local/environment-based; do not commit secrets.

---

# 26. `race_engineer.py` orchestration behavior

Current orchestrator version: `0.3`.

It validates that the input is a `.duckdb` file, resolves it relative to the repo when necessary, and executes reusable stages.

Important reuse behavior:

- deterministic analysis signature includes telemetry file stat + analyzer hash;
- LLM signature includes analysis SHA + backend/model + script hash;
- validator signature includes LLM SHA + validator hash;
- History reuse verifies the imported analysis and the current History DB state;
- H4/H5.1 use their own signatures and expected output files.

The design intent is **idempotent/reusable operation**, not a shell wrapper that blindly reruns everything.

When extending the orchestrator, preserve explicit applicability and reuse semantics.

---

# 27. What must NOT be prematurely integrated

Do not:

- force H3 into every session without a calibrated applicable matcher run;
- promote H2 v0.3 thresholds to universal truth;
- treat DeepSeek pre-review as human ground truth;
- use historical reference as the current-session coaching authority;
- claim H5.2 coaching authority without both raw DuckDBs, validated comparison and a dedicated LLM authorization contract;
- normalize `LMP2_ELMS` and `LMP2`;
- move deterministic telemetry logic into the LLM because it seems easier;
- re-track runtime/generated outputs;
- delete `legacy/` merely to make the repo look smaller without checking provenance needs;
- change many architecture layers at once when a focused patch can isolate risk.

---

# 28. Legacy/provenance policy

`legacy/` exists intentionally.

It contains superseded versions of analyzers, LLM scripts, History tools and calibration utilities that are useful for:

- regression archaeology;
- comparing behavior across versions;
- recovering a known implementation;
- understanding why current policies exist.

Normal runtime should not execute legacy files.

Do not clutter the repo root with every historical release; place superseded releases under appropriate `legacy/` subdirectories.

---

# 29. Current known debt / roadmap

Completed after the integration checkpoint:

1. The H5.2 observational narrative passed on the real Fuji pair with DeepSeek and its dedicated validator.
2. The same raw and narrative contracts passed on Imola, Interlagos and Monza, including both positive and negative current-minus-historical lap deltas.
3. Monza confirmed that exact vehicle/context isolation rejects Hypercar-to-LMP2_ELMS history while accepting two compatible Toyota Hypercar sessions.
4. A first Monza Hypercar H2 batch completed human review and feature reporting, but its leakage-safe evaluation partition is empty; more independent sessions are required before matcher evaluation.
5. A separate Monza `LMP2_ELMS` H2 batch completed 24 human reviews across 3 sessions; its independent evaluation partition is also empty and remains blocked by real data.
6. D2.9 — product-principled deterministic ranker policy — is the **production
   ranker by default** (cutover 2026-08-25), evaluated over 127 comparisons
   (0 policy violations, 0 ranker-contract violations). Rollback:
   `RACE_ENGINEER_LLM_RANKER=1`. No more DeepSeek calibration. The narrative
   diff on Imola/Spa/Fuji showed the visible changes are classification labels,
   the secondary/priority lists and, when the cut extends, a full "Qué probar"
   entry; the closing focus and the deterministic summary did not change in
   those sessions.
7. D3.x is closed: the LLM stage is deterministic-first by default
   (`RACE_ENGINEER_DETERMINISTIC_FIRST`, default "1"), the H5.2 narrative is
   non-blocking, and **the default runtime path has no LLM dependency**;
   the LLM ranker is available only as explicit rollback
   (`RACE_ENGINEER_LLM_RANKER=1`).

Current priority order:

1. D3.x and D2.9 cutover are committed; the default pipeline is 100%
   deterministic (rollback: `RACE_ENGINEER_LLM_RANKER=1`).
2. Continue debrief refinement, especially brake-vs-throttle actionability.
3. Integrate H3 only when calibrated matcher provenance/applicability can be resolved for the current context.
4. Expand H2 calibration beyond the current limited context before calling it general.
5. Continue adding real H5.2 contexts without relaxing the track/layout/vehicle/car gates.

Episode prompt changes are isolated through `run_llm_prompt_shadow.py`.
`assess_llm_prompt_shadow_promotion.py` accepts only exact A/B pairs with the
same deterministic source, backend and model; cross-model results are backend
observations, not proof of prompt improvement. The current verdict is
`PROMOTION_BLOCKED_INSUFFICIENT_PAIRED_EVIDENCE`: the only exact pair (Imola,
DeepSeek V4 Pro) tied production at 4/43 repaired episodes and zero fallbacks.
Monza Flash and Fuji llama.cpp/Qwen3.6 35B passed validation but are unpaired.
Production remains unchanged. See
`docs/LLM_PROMPT_SHADOW_PROMOTION_GATE_V0_1.md`.

Do not skip directly to “learning from all history” before context isolation and raw-validation gates are trustworthy.

---

# 29. Automatic telemetry ingestion and Explorer launcher

`auto_ingest_telemetry.py` owns local Windows automation. The preferred telemetry
source is LMU's `UserData/Telemetry` directory; raw DuckDBs are opened read-only and
do not need to be copied into the repository.

The desktop entry point is `RaceEngineer.pyw` (implementation:
`race_engineer_gui.py`). Its catalogue is owned by `race_engineer_ui_model.py` and
uses orchestrator `state.json` rather than scanning result filenames heuristically.
GUI v1.11 can search/filter sessions and inspect deterministic lap times, validated debriefs,
next-stint plans, pipeline statuses, schema-4 History and the exact H4
historical-reference selection, plus the raw and validated observational H5.2
historical comparison. It also reconstructs a read-only GPS circuit map from the
selected session DuckDB in a background thread, preserving each point's LMU Lap Dist
for future zone overlays. Analysis lap numbers are aligned to zero-based GPS groups
by reference duration, and incomplete/short groups are rejected before rendering.
Deterministic H5.2 distance zones are overlaid on the GPS polyline (loss/gain)
and can be inspected by clicking without granting them coaching authority.
Validated `next_stint_plan` intervals are a separate blue GPS layer; clicking a
priority displays its driver cues. Native `Ground Speed`, `Brake Pos` and
`Throttle Pos` are aligned to that same complete GPS lap. Clicking any trace point
shows its instantaneous values, while an H5.2 zone or validated priority also shows
descriptive channel summaries for the exact distance interval. Missing optional
channels remain explicitly unavailable and never block the map. The white point
marker is a drag control snapped to the closest rendered GPS sample, so values update
continuously while it moves along the circuit. A full-lap chart below the map renders
speed, throttle and brake in three independently scaled lanes on the same `Lap Dist`
axis. Its white cursor follows the map marker, and the selected H5.2/priority interval
is shaded without changing the source evidence. The visual alignment runs at 10 Hz;
the chart supports pointer-anchored wheel zoom, `Shift + wheel` pan, full-lap reset
and automatic window following when the map marker leaves the visible span. All
windows remain clamped to the selected complete lap. This inspection is
read-only and cannot create or reprioritize coaching. The next-stint tab and GPS map
also distinguish a consistent H5.4 P11 two-item driver focus from the preserved
complete plan; inconsistent/legacy P11 data fails back to the complete plan. A valid debrief remains available when a later
historical pipeline stage fails, as proven by `debrief_validator` RUN/REUSED
(with legacy `llm_validator` states still readable).
History, telemetry and generated artifacts are opened
read-only. Legacy provider settings remain outside the product GUI. The GUI invokes
the deterministic `analyze_telemetry_file.py` path while streaming progress. A
per-run, opt-in override can omit only the 10-minute
file-age wait; LMU-running, authorized-root, telemetry type, 5 MiB and two-valid-lap
gates remain mandatory. The scheduled automatic ingest never uses this override.
The launcher remains the sole safety authority and the GUI never offers
cancellation. GUI v1.5 adds presentation-only H6.5 control chrome: flat dark entries
and comboboxes, thin scrollbars, modernized Treeview selection/headings, cleaner tabs
and a compact progress bar. See `docs/RACE_ENGINEER_GUI_V1_5.md`.

GUI v1.6 adds a read-only `H5.3 shadow` indicator beside the session count. It reads
only `data/local/h5_3_review_maintenance.json` on refresh and renders `al día`, the
pending review count, missing state or invalid/failed state with distinct dark-theme
colors. Clicking it copies its diagnostic detail into the footer. It never opens the
labeler, changes a label or exposes a shadow candidate as driver coaching. See
`docs/RACE_ENGINEER_GUI_V1_6.md`.

GUI v1.7 adds pointer-anchored wheel zoom directly to the GPS circuit map. The same
view transform applies to the track, H5.2 zones, H5.4 priorities, start marker and
draggable telemetry point, preserving selection alignment. Zoom is clamped to
`1x..8x`, resets explicitly or on session change, and remains independent from the
telemetry-chart distance zoom. It changes no GPS samples or coaching evidence. See
`docs/RACE_ENGINEER_GUI_V1_7.md`.

GUI v1.8 adds right-button drag panning while the GPS map is zoomed. The circuit,
H5.2 zones, H5.4 priorities, start marker and telemetry point move under the same
clamped canvas transform, so selections remain aligned and part of the circuit always
stays visible. Left-button dragging remains reserved for the telemetry point. This is
read-only presentation and changes no samples, distances or coaching authority. See
`docs/RACE_ENGINEER_GUI_V1_8.md`.

GUI v1.9 resolves the selected white GPS point against the highest-version exact
validated production track profile. It displays the calibrated turn or transition
outside H5.2 overlays and fails closed to distance-only output when no exact profile
exists. Map status and telemetry labels wrap dynamically with the available panel
width. No track name is inferred by the GUI and no coaching authority changes. See
`docs/RACE_ENGINEER_GUI_V1_9.md`.

GUI v1.10 adds an opt-in `Curvas` overlay derived from that same exact validated
profile. It draws calibrated turn intervals, apex markers and profile-owned names;
H5.2 zones and validated priorities remain visually above it. The complete layer
shares zoom/pan transforms and starts disabled to avoid clutter. It is read-only and
does not create spatial evidence or coaching. See `docs/RACE_ENGINEER_GUI_V1_10.md`.

GUI v1.11 adds an exact-profile turn selector. Choosing a turn enables its contextual
layer, highlights the calibrated interval, moves the white point to the profile apex,
fits the whole interval on the GPS canvas and focuses the lower telemetry chart on
the same entry/exit bounds. Map and chart remain independently adjustable afterward.
Turn navigation uses a separate control row so normal window widths remain legible.
See `docs/RACE_ENGINEER_GUI_V1_11.md`.

GUI v1.12 reorganiza la navegación principal en Resumen / Telemetría / Historial /
Diagnóstico con sub-vistas, agrega tarjetas compactas de sesión (referencia, vueltas
válidas, historial y estado) y coloca el mapa y los canales en un `Panedwindow`
vertical con separador arrastrable. El gráfico de canales usa tres carriles, se
expande con el panel y no dibuja líneas ficticias por debajo de 180×120 px. See
`docs/RACE_ENGINEER_GUI_V1_12.md`.

GUI v1.13 agrega badges de estado con color y tooltip en el catálogo de sesiones y
convierte `Historial → Comparación` en una vista lado a lado: línea de delta,
paneles histórico/actual y detalle con zonas de mayor impacto (top 3 por
`|delta_change|`) más la lectura H5.2 validada con backend/modelo. La vista se
calcula en `race_engineer_ui_model.py` desde artefactos H5.2 autorizados; la GUI
sólo la presenta y no altera ninguna autoridad. See
`docs/RACE_ENGINEER_GUI_V1_13.md`.

GUI v1.14 agrega `Diagnóstico → Calibración`: tabla read-only con el estado H2
por contexto (sesiones, labels, partición de evaluación y status del matcher
resuelto), coloreado por estado. Se calcula en `race_engineer_ui_model.py`
(`load_calibration_summary`) desde los `BATCH_STATUS.json`; presentación
únicamente. See `docs/RACE_ENGINEER_GUI_V1_14.md`.

GUI v1.15 agrega la sincronización plan ↔ mapa ↔ telemetría: selector de zonas
del `next_stint_plan` validado (foco P11 con prefijo `FOCO`) que resalta la
prioridad en el mapa GPS, hace fit al intervalo y enfoca el gráfico de canales
en el tramo inicio-fin. Presentación únicamente. See
`docs/RACE_ENGINEER_GUI_V1_15.md`.

GUI v1.16 agrega playback de telemetría: `▶ Play / ⏸ Pausa` y `⏮ Inicio`
avanzan el punto blanco a 10 Hz por la vuelta (mapa + gráfico + lecturas),
con auto-stop al final y al arrastrar/elegir curva o zona. Presentación
únicamente. See `docs/RACE_ENGINEER_GUI_V1_16.md`.

GUI v1.17 mejora la resolución: alineación a 20 Hz por default (la nativa es
~100 Hz) con selector 10/20/50 Hz en la fila de playback; el paso del playback
se ajusta para mantener velocidad 1×. Presentación read-only. See
`docs/RACE_ENGINEER_GUI_V1_17.md`.

GUI v1.40 corrects the 50 Hz telemetry render without changing source evidence.
Continuous channels are reduced to temporal extrema per canvas pixel, while the
gear lane stores only actual step transitions. Gear is aligned as a discrete
previous-value state instead of linearly interpolated; LMU zero transition sentinels
between positive gears and short same-gear bounces are removed only from the displayed
lap. Dense canvas lines are segmented and the previous chart remains visible during
an asynchronous resolution refresh. A stale previous-lap prefix before the LMU
`Lap Dist` reset is excluded by selecting the segment with greatest physical
distance coverage, fixing files that appeared loaded but blank at 50 Hz.
Leading/trailing sustained neutral remains visible. See
`docs/RACE_ENGINEER_GUI_V1_40.md`.

GUI v1.41 reads the scheduler-owned `data/local/h3_import_maintenance.json` snapshot
and shows its read-only H3 status/counts in `Circuitos → Readiness`. The existing
cheap scheduler fingerprint detects snapshot changes without rebuilding sessions,
maps or telemetry. Missing, malformed or non-read-only snapshots fail closed in the
label; the GUI never imports H3 or writes either History or maintenance state. See
`docs/RACE_ENGINEER_GUI_V1_41.md`.

GUI v1.42 / track-map v0.9 makes playback speed independent from render resolution.
The marker advances from `perf_counter()` wall time and snaps to the nearest existing
lap-relative telemetry sample, so 50 Hz affects visual update density rather than
making playback run slow. Native `Lap.ts` boundaries (or the exact selected analysis
duration for a reference match) own the displayed lap duration, preserving
millisecond precision instead of the final resampled grid interval. No synthetic
high-frequency telemetry is created. See `docs/RACE_ENGINEER_GUI_V1_42.md`.

GUI v1.43 adds a separate read-only line for H3 materialization readiness. The
hidden scheduler evaluates the authorized H2→H3 path in memory only when feature,
label, official-bundle or authority-code inputs change; ordinary History imports do
not trigger the multi-minute audit, and LMU running defers it. The local snapshot is
`data/local/h3_materialization_readiness.json`. `MATERIALIZATION_READY` remains an
explicit operator action and the GUI exposes no apply control. See
`docs/RACE_ENGINEER_GUI_V1_43.md`.

GUI v1.48 adds a lazy `Estadísticas` workspace over History schema 4. General and
monthly totals count only valid laps and sum their stored `lap_distance_m`; favorites
are descriptive usage counts, not coaching evidence. Exact `LMP2_WEC` and
`LMP2_ELMS` categories remain separate while their explicit car display is unified
as `Oreca 07`. Other classes fail closed to the LMU-recorded entry because History
does not yet own a canonical model field. DuckDB opens read-only in a background
worker and an mtime/size fingerprint avoids repeat work. See
`docs/RACE_ENGINEER_GUI_V1_48.md`.

GUI v1.49 enriches H5.2 map zones with H5.3d v0.2 steering morphology when their
physical bounds match exactly. Selecting a comparable corner shows current/reference
variation per 100 m and exact sign-change counts below the telemetry map. Invalid or
missing H5.3 context is ignored without hiding the base H5.2 zones.

GUI v1.50 makes the visible session headers sortable in memory. `Fecha` defaults
to newest first; `Circuito` and `Estado` default ascending, and a second click
reverses direction. Filtering, searching and the current selection are preserved,
and sorting does not reread session artifacts.

GUI v1.51 persists only the selected catalogue sort column and direction in the
ignored local file `data/local/gui_preferences.json`. Missing, corrupt, or unknown
values fail closed to `Fecha` descending; no session or pipeline state is modified.

GUI v1.52 consumes `data/local/h3_automation_status.json` in
`Circuitos → Readiness`. It presents one prominent current/stale workflow summary
and enables Materializar/Importar only when both the unified next action and the
operation-specific snapshot agree on the exact context. Successful explicit actions
rebuild the unified projection immediately; failed actions mark it stale. This is an
additional presentation/safety gate and never schedules `--apply` automatically.

GUI v1.53 adds application-wide keyboard navigation: `Ctrl+1..7` selects the
primary workspaces, `Ctrl+F` focuses and selects the session search, `Ctrl+R`
refreshes the current workspace with its appropriate loader, and `Esc` dismisses
the plan inspector and row tooltip. These shortcuts change presentation/focus only.

GUI v1.54 makes those section shortcuts visible in the sidebar and remembers the
last primary workspace in the ignored local GUI preferences. Preference writes are
atomic and preserve the existing catalogue sort keys; missing, corrupt or unknown
workspace values fail closed to `Resumen`.

GUI v1.18 integra el scheduler con el catálogo abierto mediante un fingerprint
read-only de los `state.json`. Cada cinco segundos comprueba ruta, `mtime_ns` y
tamaño, pero sólo llama `refresh()` cuando el conjunto cambió. Conserva la sesión
seleccionada, omite la recarga durante un análisis iniciado desde la GUI y cancela
el callback al cerrar. No escribe estado ni reconstruye mapa/telemetría cuando no
hay cambios. See `docs/RACE_ENGINEER_GUI_V1_18.md`.

GUI v1.19 añade un watchdog read-only. El runner oculto publica de forma
atómica `telemetry_scheduler_runtime.json` con RUNNING/PASS/FAILED, timestamps,
PID y exit code. La GUI distingue un ciclo normal, uno RUNNING por más de 15
minutos, heartbeat ausente por más de 5 minutos, último ciclo fallido y bloqueo
FIFO por tres fallos del mismo debrief. No salta ni reordena la cola. See
`docs/RACE_ENGINEER_GUI_V1_19.md`.

Al pulsar el indicador se abre el panel B3 con diagnóstico completo, sesión
bloqueante, intentos, último error, timestamps del ciclo, último éxito y accesos
para copiar el reporte o abrir el log local. El panel sigue siendo read-only.

GUI v1.20 añade B4 manual y reversible: una sesión con tres fallos confirmados
puede pasar a `DEBRIEF_DEFERRED` para liberar la cola y luego reactivarse al final.
History, intentos y último error se conservan. La acción exige confirmación,
rechaza un scheduler RUNNING y aborta si el JSON cambia concurrentemente. See
`docs/RACE_ENGINEER_GUI_V1_20.md`.

GUI v1.21 elimina la confirmación obsoleta de modelo/costo al iniciar análisis:
el doble clic comienza directamente el pipeline Python determinista, conservando
validaciones y override explícito de estabilidad. El scheduler ejecuta además
`maintain_calibration_queues.py`: compara los session IDs por contexto con batches
existentes, prepara como máximo una `pair_review_queue.json` cambiada por ciclo
mediante `--skip-import` y nunca genera labels ni llama un LLM. La tabla de
Calibración observa cambios en `BATCH_STATUS.json` y `pair_labels.json`. See
`docs/RACE_ENGINEER_GUI_V1_21.md`.

The scheduled task must execute `hidden_history_ingest.py` through `pythonw.exe`.
That wrapper preserves the same maintenance arguments, creates no console window and
redirects stdout/stderr to the ignored rotating local log
`data/local/telemetry_auto_ingest_task.log`. `install_history_ingest_task.ps1`
installs or updates that task action without changing the Python-owned ingest logic.

The scheduled `maintenance` contract is History-first:

- if `Le Mans Ultimate.exe` is running, return `SKIPPED_GAME_RUNNING` before scan;
- wait 10 minutes after the last game observation (`POST_GAME_SETTLE`);
- give new stable telemetry priority over backlog;
- run deterministic analysis, History import and applicable H3/H4/H5 Python
  context with `--no-debrief`;
- after successful History maintenance, audit existing official H3 import
  readiness read-only and atomically publish `data/local/h3_import_maintenance.json`;
  unchanged inputs reuse the prior snapshot and H3 audit failures remain
  non-blocking warnings;
- after ingest/backfill, generate the deterministic race debrief (one session
  per run) forcing `RACE_ENGINEER_DETERMINISTIC_FIRST=1` and
  `RACE_ENGINEER_LLM_RANKER=0` in the subprocess plus
  `--force-deterministic-debrief`; the explicit mode preserves deterministic
  historical context, skips the H5.2 LLM narrative, removes `DEEPSEEK_API_KEY`,
  rejects incompatible invocation and rebuilds stale renders without model
  access (failures keep `HISTORY_READY` for retry);
- process at most one backfill candidate per cooldown;
- retain an unchanged `FAILED` entry without retrying it every minute, so an old
  unusable recording cannot block pending deterministic debriefs; a signature
  change returns that file to `PENDING_STABILITY`;
- never use the 5 MiB threshold as proof that a recording is complete;
- scope scan/backfill/debrief selection to the configured source directory.

The real Monza file `Autodromo Nazionale Monza_P_2026-08-17T18_55_39Z.duckdb`
completed the unattended transition `PENDING_STABILITY -> HISTORY_READY`, passed
deterministic analysis and was imported as History `session_id=23`; LLM remained
disabled for that automatic stage.

`analyze_telemetry_file.py` is the explicit user-authorized LLM path used by the
Windows Explorer context menu and desktop GUI. It accepts only DuckDBs inside authorized
telemetry roots, blocks History databases, LMU-running state and files below 5 MiB.
By default it also blocks files younger than 10 minutes; GUI v0.6 or the explicit
`--skip-stability-wait` flag may omit only that age check. It first runs
deterministic analysis + History without an LLM, requires at least two
Python-confirmed valid laps, and only then runs the full
selected backend. The Windows context menu exposes three verbs: DeepSeek,
`ingenierov3` (Ollama) and `llama.cpp` (default model `qwen3-14b`).
`race_engineer.py` reuse remains responsible for preventing
duplicate valid model calls.

Real historical-reference confirmation for the latest unattended Monza session:

- target History session: `session_id=23`, current reference lap 3, `99.280 s`;
- selected historical session: `session_id=19`, lap 10, `97.500 s` (`1:37.500`);
- context: Monza / exact Monza layout / `LMP2_ELMS` / IDEC Sport #18 / dry-compatible;
- historical advantage: `1.780 s`;
- H4 status: `HISTORICAL_REFERENCE_SELECTED`.

This confirms that automatic History ingestion feeds the existing H4/H5 path. H5.1
continues to keep the current-session reference as coaching authority.

Two legacy backfill candidates are recorded as
`BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS` because each has only one usable lap after
incomplete laps are discarded. This is non-applicable data, not corruption.
`validate_global_output` remains unchanged; the ingest layer classifies the expected
single-valid-lap outcome without weakening the analyzer validator.

# 30. Recommended workflow for an agent making a change

For any non-trivial task:

1. Identify which layer owns the requested behavior.
2. Inspect the current generic file and its tests.
3. Check whether a versioned current release must remain synchronized.
4. Avoid editing legacy files unless the task explicitly concerns provenance/recovery.
5. Make the smallest coherent change.
6. Add/update tests for the actual contract.
7. Run targeted tests first.
8. Run full `pytest` if the change can affect shared contracts.
9. Run Objective Python regressions for deterministic-analysis changes.
10. If runtime/output behavior changed, verify Git hygiene paths.
11. Update `PROJECT_STATUS.md`, relevant README sections, and this `AGENTS.md` when the architectural truth changed.
12. Summarize what changed, what was validated, and what remains untested because of unavailable raw telemetry/credentials/environment.

---

# 31. How to reason about a new coaching idea

Before implementing a new recommendation, ask:

```text
Is this a deterministic fact?
    -> Python/detector/schema/test owns it.

Is this a transformation from deterministic evidence to an authorized target?
    -> deterministic policy/gate should authorize it.

Is this only prioritization or wording among already-authorized facts?
    -> LLM layer may own it.

Does it use historical data?
    -> identify whether it is observational H4/H5.1 or validated raw H5.2.

Does it cross session/track/vehicle boundaries?
    -> enforce context gates before comparing.
```

---

# 33. Fast orientation: files to inspect by task

Use this routing map instead of reading the whole repository blindly:

| Task | Start with |
|---|---|
| End-to-end/runtime | `race_engineer.py`, `runtime_paths.py`, `PROJECT_STATUS.md` |
| Deterministic telemetry | `analyze_telemetry.py`, regression/recovery scripts |
| LLM debrief | `llm_analysis.py`, `llm_analysis_deepseek.py`, `validate_llm_analysis_output.py` |
| History | `session_history.py`, `validate_history_db.py` |
| H2 calibration | `prepare_calibration_batch.py`, `episode_pair_features.py`, matcher/review/label tools |
| H2.2 | DeepSeek ambiguous-pool/reviewer tools + calibration batch artifacts |
| H3 | `build_persistent_patterns.py` |
| H4 | `select_historical_reference.py` |
| H5.1 | `build_dual_reference_context.py` |
| Track geometry | GPS/turn detection tools, `track_profiles/`, nomenclature JSONs |
| Repo cleanup | `scripts/repo_hygiene.py`, `.gitignore` |

---

# 34. Context that portable copies usually do NOT include

A repository ZIP may intentionally omit:

- `telemetria/*.duckdb` because raw recordings are large/local;
- `data/local/race_engineer_history.duckdb` because it is local persistent state;
- generated prompts/results under `data/generated/`;
- API keys/secrets;
- `.git/` metadata.

An agent inspecting such a ZIP must not conclude those systems do not exist merely because their local data is absent.

In particular, lack of `telemetria/` prevents true end-to-end raw telemetry tests and H5.2 validation.

---

# 35. Maintaining this context file

This file is intended to eliminate repeated re-onboarding of ChatGPT/Codex/other LLMs.

Update it whenever any of these change materially:

- current operational versions;
- architecture ownership boundaries;
- History schema;
- H2/H3/H4/H5 status;
- normal entry point;
- runtime output layout;
- Git hygiene policy;
- vehicle/layout context semantics;
- required validation commands;
- major empirical coaching conclusions;
- the roadmap or a previously forbidden integration becomes valid.

Do not turn this file into a changelog of every tiny patch. Keep it a current mental model plus durable invariants.

Historical details belong in versioned notes or `legacy/`.

---

# 36. One-paragraph mental model

Race Engineer takes an LMU DuckDB, extracts and validates deterministic lap/zone/action evidence in Python, asks an LLM only to prioritize and explain authorized evidence, validates that narrative, stores the deterministic session in a schema-4 History DB, optionally selects a context-compatible historical benchmark through H4, preserves current-session coaching authority through H5.1 dual reference, and compares both compatible raw reference laps deterministically through H5.2. A separate validated H5.2 LLM contract may select only Python-authorized zone and observation codes; Python renders every historical statement and number, while causal claims and driving recommendations remain impossible. H2/H3 are the calibrated cross-session pattern-learning path and remain context-limited rather than universal. The repo must stay clean: source/provenance is tracked, runtime telemetry/debug/results stay under ignored `telemetria/`, `data/generated/` and `data/local/` paths.

Since 2026-08-25 the LLM layer is fully deterministic by default: episode
interpretation, comparison summary, global prose and the priority ranker
(D2.9 product policy) are built by Python. The LLM ranker remains available
only as explicit rollback (`RACE_ENGINEER_LLM_RANKER=1`).
