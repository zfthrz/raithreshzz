# H3 Persistent Pattern Types v0.1

## Semantics frozen for this phase

`MATCH` is an equivalence relation for pattern identity.

Therefore:

- A MATCH B
- B MATCH C
- implies A, B and C belong to the same pattern class.

A direct A-C `AMBIGUOUS` does not break the class; it is counted as
`transitively_resolved_ambiguous_pair_count`.

A direct `REJECT` whose endpoints fall inside the same MATCH-connected class is a
contradiction. The class becomes `conflict_review_required`; the source pairwise
decision is not silently rewritten.

## State policy

Current H2 evidence is cross-session only.

- `single_observation`: isolated episode, no MATCH edge.
- `cross_session_repeat`: equivalence class observed in 2 independent sessions.
- `persistent_pattern`: equivalence class observed in at least 3 independent sessions.
- `conflict_review_required`: an internal REJECT or missing internal cross-session pair evidence exists.

The 3-session threshold is a semantic cardinality policy, not a geometric matcher threshold.
It is configurable with `--persistent-min-sessions` but v0.1 rejects values below 3.

`within_session_repeat` is not inferred yet because H2 pair features deliberately contain
cross-session pairs only.

## Safety boundaries

H3 v0.1:
- does not change matcher v0.3;
- does not mutate History DuckDB;
- does not select historical_reference;
- does not change llm_analysis or coaching;
- does not use DeepSeek/Ollama;
- keeps observation_count separate from independent_session_count;
- records source matcher version and transitive evidence.

## Next checkpoint

Run builder + validator + audit on the real Spa/LMP2_ELMS 5506-pair batch.
If no internal REJECT contradiction appears and the pattern-size distribution is sane,
then persist the derived pattern layer into History as a later H3 schema migration.
