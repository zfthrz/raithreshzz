# H4 Historical Benchmark Selector v0.1

## Goal

Select one historical benchmark lap for a target session without changing intra-session coaching.

## Candidate unit

H4 does **not** scan every historical lap and independently invent a new best-lap policy.
Each historical session contributes only its existing `sessions.reference_lap`, already chosen by `analyze_telemetry`.

## Hard gate v0.1

A candidate session reference is eligible only if:

1. it is a different session;
2. its timestamp is strictly earlier than the target session;
3. exact same `track`;
4. exact same `lmu_track_layout`;
5. exact same `vehicle_variant`;
6. exact same `car_name_raw`;
7. `vehicle_supported_domain = true`;
8. session temporal validation is `OK`;
9. session objective validation is `OK`;
10. at least 3 valid laps by default (`--min-valid-laps` configurable);
11. reference-lap row exists and is valid, not discarded, not initial/ignored, has the reference flag, positive duration, positive samples and positive lap distance;
12. when target `weather_conditions` is known, candidate raw weather must be known and exactly equal.

Weather v0.1 deliberately does not infer equivalence between differently encoded conditions.

## Recorded but non-gating in v0.1

- `session_type`;
- `lmu_session_type`;
- `setup_sha256`.

Their equality is recorded for later empirical study. They do not yet accept/reject candidates.

## Ranking

Among eligible session-reference laps:

1. shortest `duration_s` wins;
2. timestamp breaks exact ties;
3. session_id is the final deterministic tie-breaker.

## Data sufficiency

Default `min_valid_laps = 3` reflects the operational rule that very short telemetry recordings (often below roughly 5 MB) tend to contain no more than about two useful valid laps. The file-size heuristic itself is for the future telemetry watcher; History currently stores the stronger post-analysis signal: actual valid-lap count.

## Safety boundaries

H4 v0.1:

- requires History schema 4;
- never modifies History;
- does not use DeepSeek/Ollama;
- does not use H3 patterns to rank lap speed;
- does not replace the current session reference;
- produces a separate JSON for validation/audit;
- historical candidates after the target timestamp are rejected to avoid offline future leakage;
- `LMP2_ELMS` and other vehicle variants remain distinct.

## Next checkpoint

Run selector, validator and audit against a real Spa session that has earlier compatible sessions.
Inspect candidate rejection reasons before persisting H4 decisions or wiring H5 dual-reference analysis.
