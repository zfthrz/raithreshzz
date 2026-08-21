# Race Engineer — PROJECT_CONTEXT v1.0

> Canonical end-to-end onboarding context for coding agents and LLMs working on the Race Engineer repository.
> Baseline represented here: integration and local automation checkpoint 2026-08-17.
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

Default LLM backend: DeepSeek.

Local/Ollama backend:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --backend ollama
```

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

Checkpoint: **2026-08-17 automation and historical-reference integration**.

| Component | Current operational baseline |
|---|---|
| `race_engineer.py` | orchestrator v0.3 |
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
| H3 persistent patterns | v0.1 / derived |
| H4 historical reference | v0.2 |
| H5.1 dual reference | v0.2 |
| H5.2 | v0.2 profile-localized raw comparison + v0.1 validated observational LLM narrative |
| H5.3 historical coaching debrief | roadmap only / shadow complete (H5.3a-f) + Nivel 2 action policy / production gated |

Validated checkpoints relevant to the current working tree:

```text
full pytest (current working tree):   408 PASS / 0 FAIL / 0 SKIP
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
LLM backend (DeepSeek default / Ollama optional)
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
H5.2 LLM observational narrative when LLM is enabled; historical actions remain disabled
   
H5.3 deterministic historical section (observational) when H4/H5.1/H5.2 are valid
```

The orchestration entry point is:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

Useful switches:

```text
--backend deepseek|ollama
--history-db PATH
--force
--force-analyze
--force-llm
--no-llm
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

This is an active product-quality topic, not a settled algorithmic rule.

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

Normal `race_engineer.py analyze` therefore currently reports:

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

- deterministic repair of badly anchored steering conclusions;
- revalidation after repair;
- deterministic global fallback derived from `next_stint_plan` if narrative output remains invalid.

Again: validators should not be weakened for convenience.

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

Current priority order:

1. Continue debrief refinement, especially brake-vs-throttle actionability.
2. Integrate H3 only when calibrated matcher provenance/applicability can be resolved for the current context.
3. Expand H2 calibration beyond the current limited context before calling it general.
4. Continue adding real H5.2 contexts without relaxing the track/layout/vehicle/car gates.

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

The scheduled task must execute `hidden_history_ingest.py` through `pythonw.exe`.
That wrapper preserves the same maintenance arguments, creates no console window and
redirects stdout/stderr to the ignored rotating local log
`data/local/telemetry_auto_ingest_task.log`. `install_history_ingest_task.ps1`
installs or updates that task action without changing the Python-owned ingest logic.

The scheduled `maintenance` contract is History-first:

- if `Le Mans Ultimate.exe` is running, return `SKIPPED_GAME_RUNNING` before scan;
- wait 10 minutes after the last game observation (`POST_GAME_SETTLE`);
- give new stable telemetry priority over backlog;
- run deterministic analysis and History import with `--no-llm --no-historical-context`;
- process at most one backfill candidate per cooldown;
- never use the 5 MiB threshold as proof that a recording is complete;
- scope scan/backfill/debrief selection to the configured source directory.

The real Monza file `Autodromo Nazionale Monza_P_2026-08-17T18_55_39Z.duckdb`
completed the unattended transition `PENDING_STABILITY -> HISTORY_READY`, passed
deterministic analysis and was imported as History `session_id=23`; LLM remained
disabled for that automatic stage.

`analyze_telemetry_file.py` is the explicit user-authorized LLM path used by the
Windows Explorer context menu. It accepts only DuckDBs inside authorized telemetry
roots, blocks History databases, LMU-running state, files below 5 MiB and files
younger than 10 minutes. It first runs deterministic analysis + History without an
LLM, requires at least two Python-confirmed valid laps, and only then runs the full
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
