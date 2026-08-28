# H3 → History integration v0.1

## Scope

`run_h3_pipeline.py` owns the official batch path from authorized H2 decisions to
derived H3 evidence. History persistence is an explicit optional stage selected with
`--history-db`; it is not a side effect of `build_patterns()`.

## State contract

- `cross_session_repeat`: evidence repeated across two independent sessions. It is
  stored with that exact state and remains observational.
- `persistent_pattern`: requires the configured minimum, currently three independent
  sessions.
- `conflict_review_required`: never imported. The run remains review-required.

Importing any state does not change `session_reference`, `next_stint_plan`, ranking,
H4/H5 authority or historical coaching authorization.

## Provenance and safety

Official imports validate and preserve:

- H3, matcher and authorized-matcher versions;
- track-baseline and MATCH-promotion policy versions;
- H2 authority gate and calibration-scope counts;
- exact track, track layout and vehicle variant;
- source feature, match and pattern hashes;
- member session IDs and episode PKs;
- raw pattern and pair-evidence structures;
- persistent-session threshold and run timestamps.

Promoted track baselines are MATCH-only. An inherited REJECT, an unauthorized MATCH,
inconsistent member context, missing History episode or conflict blocks persistence.
The schema-4 validator rechecks durable official provenance and baseline REJECT policy.

Official idempotency uses a stable materialization hash over deterministic evidence
and authority provenance while excluding volatile timestamps and paths. Rebuilding
the same source evidence therefore returns `REUSED` instead of creating another run.

## Explicit multi-context maintenance v0.2

`maintain_h3_imports.py` consolidates the existing readiness inspection without
changing its authority boundary:

```powershell
python maintain_h3_imports.py
```

The default mode is read-only. `--apply` is an explicit operator action and imports
only existing bundles classified `H3_READY_TO_IMPORT` by the production inspection.
It skips imported, incomplete, conflicting and legacy-invalid bundles. It does not
run H2/H3, repair provenance or authorize coaching.

The hidden scheduler executes only this read-only audit after successful History
maintenance and atomically publishes:

```text
data/local/h3_import_maintenance.json
```

It never passes `--apply`. A cheap fingerprint over History and the official H3
bundle files allows unchanged scheduler cycles to reuse the existing snapshot.
Audit failures are non-blocking warnings: History remains successful and no import
is attempted. Real validation reduced an unchanged rerun from 19.69 seconds to
0.14 seconds while retaining `history_mutated=false`.

The first real audit found 11 exact contexts: one already imported Imola LMP2_ELMS
bundle, one legacy Imola HYPER bundle failing closed because it lacks a valid
`source_features_sha256`, nine contexts without an official materialization, and no
bundle ready to import. History remained unchanged.

`audit_h3_materialization_readiness.py` diagnoses the preceding stage. It runs the
current authorized H2 classifier, H2→H3 gate and H3 builder in memory, requiring at
least one authorized MATCH and no conflict for `MATERIALIZATION_READY`. It writes no
matches, patterns or reports and never mutates History.

The first real materialization audit classified six contexts ready (Imola HYPER,
Interlagos LMP2_ELMS, Spa LMP2_ELMS, Spa LMP2_WEC, Fuji GT3 and Fuji LMP2_ELMS),
four with no authorized MATCH (Monza HYPER, Monza LMP2_ELMS, Sarthe LMP2_WEC and
Daytona LMP2_ELMS), plus the already-materialized Imola LMP2_ELMS context.

## First multi-context apply

Before applying, the scheduler was disabled, DuckDB was checkpointed and a physical
backup was verified byte-for-byte with SHA-256. Six bundles then returned `RUN`:
Imola HYPER, Interlagos LMP2_ELMS, Spa LMP2_ELMS, Spa LMP2_WEC, Fuji GT3 and Fuji
LMP2_ELMS. The post-import audit reports seven `H3_IMPORTED` exact contexts and four
`H3_NOT_APPLICABLE`, with no ready, failed or conflicting bundle. The History schema
validator passed; its only warning was the pre-existing filename/context difference
for session 98. The hidden scheduler was restored to enabled/ready.

## Real checkpoint

The Imola HYPER batch `c75b788fa4` was executed against a temporary copy of History:

```text
pairs:                 324
MATCH:                  26
AMBIGUOUS:             298
REJECT:                  0
authority scope:        COVERED_BY_TRACK_MATCH_BASELINE
H3 classes:             14
cross_session_repeat:   14
persistent_pattern:      0
conflicts:               0
inherited REJECT:        0
first import:           RUN
second import:          REUSED
History validator:      PASS
```

The production History database was not modified for this validation.
