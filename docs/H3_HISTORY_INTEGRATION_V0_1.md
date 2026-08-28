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
