# H5.1 Dual Reference Context v0.1

## Goal

Represent both references at the same time without letting the historical benchmark
silently replace the current session reference.

- `session_reference`: operational coaching reference.
- `historical_reference`: long-term progress benchmark.

This implements the first half of H5.

## Why H5 is split

History stores lap/session summaries and driver-action episodes, but not the full raw
telemetry trace of every historical lap. Therefore historical action differences must
not be reconstructed from History summaries.

H5 is split into:

1. H5.1 dual-reference context:
   - availability;
   - identities;
   - lap times;
   - current-vs-historical progress delta;
   - provenance;
   - coaching authority.

2. H5.2 cross-session telemetry comparison:
   - load both raw DuckDB files from `telemetria/`;
   - compare the selected historical lap against the current session lap;
   - run the same deterministic event/episode logic used by `analyze_telemetry.py`;
   - only after deterministic validation may historical action evidence reach the LLM.

## Safety policy

H5.1 explicitly states:

- historical reference does not replace session reference;
- historical reference cannot change driver cues;
- historical reference cannot change the global A/B/C plan;
- historical reference is observational only;
- when no compatible historical reference exists, normal session coaching continues;
- History episode summaries are insufficient for historical action coaching.

## Progress sign

`current_minus_historical_s = current_session_reference - historical_reference`

- positive: current session is slower than the historical benchmark;
- negative: current session is faster;
- approximately zero: equal within configured tolerance.

## Inputs

- deterministic `analyze_telemetry` JSON for the target session;
- H4 historical-reference selection JSON for the exact same target.

Both input SHA256 hashes are recorded.

## Next checkpoint

Run H5.1 against Spa target session 6, where H4 v0.2 should select session 5 as the
historical reference.

Expected:
- session reference ~= 125.460 s;
- historical reference ~= 124.320 s;
- current_minus_historical ~= +1.140 s;
- long-term status = BEHIND_HISTORICAL_BENCHMARK;
- coaching active reference remains session_reference.
