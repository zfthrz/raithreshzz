# H5.2 historical telemetry evidence v0.1

## Purpose

This stage preserves deterministic pointwise evidence behind an applicable H5.2
cross-session comparison. It exists for inspection and future validated analysis;
it is not a historical coaching policy.

## Inputs and alignment

The builder consumes the current and historical raw LMU DuckDB paths, their selected
reference laps, the H5.2 zone summaries and an output path. Both laps are aligned by
`Lap Dist` over their common physical coverage. No sample is extrapolated beyond that
coverage.

Continuous channels are interpolated on the shared distance grid:

- speed;
- throttle;
- brake.

Gear remains discrete. The artifact also records pointwise channel differences and
the accumulated time delta. A leading LMU boundary sample belonging to the previous
lap is normalized conservatively before coverage is calculated.

## Runtime contract

The orchestrator stage is named `h5_2_telemetry_evidence` and runs after validated
H5.2 raw comparison. Its artifact lives at:

```text
data/generated/h5_2_telemetry_evidence/<session>/interval_evidence_v0_1.json
```

Reuse depends on the H5.2 artifact hash, both raw file signatures and the builder,
validator, telemetry model and track-map implementation signatures. Builder or
validator failure is recorded as `FAILED` but does not stop the normal pipeline.

## Authority boundary

The output is always observational:

```text
observational_only = true
affects_next_stint_plan = false
historical_actions_authorized = false
```

It cannot:

- modify H5.2 zone identity or temporal truth;
- create or authorize a driver action;
- affect next-stint ranking;
- replace the current-session reference;
- grant H5.3 production authority.

## Validation checkpoint

The real Spa pipeline completed the stage and its validator successfully. The shared
coverage represented 96.38% of the current lap and 100% of the historical lap, with
27 fully covered H5.2 zones and one partial zone. The complete orchestrator continued
through H5.3 with `RESULT: PASS`.
