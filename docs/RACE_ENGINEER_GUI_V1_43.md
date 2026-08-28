# Race Engineer GUI v1.43 — H3 materialization readiness

`Circuitos → Readiness` now displays two independent H3 snapshots:

- import readiness for existing official bundles;
- in-memory materialization readiness for the newest feature batch per exact context.

The second line reads `data/local/h3_materialization_readiness.json` and reports
ready, already-materialized, no-authorized-MATCH and blocked/failed counts. This
distinction matters when History contains an older official bundle but a newer batch
has since become eligible for explicit rematerialization.

The hidden scheduler runs the expensive H2→H3 audit only after relevant feature,
label, official-bundle or authority-code changes. Ordinary History ingestion does
not invalidate it, unchanged inputs reuse the snapshot, and LMU running defers the
audit. Failures are warnings and do not invalidate History maintenance.

The GUI and scheduler remain read-only: no match/pattern bundle is generated, no H3
run is imported and no coaching authority changes. `MATERIALIZATION_READY` requires
an explicit operator pipeline run.
