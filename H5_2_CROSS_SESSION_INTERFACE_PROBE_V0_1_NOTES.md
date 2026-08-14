# H5.2 Cross-session interface probe v0.1

## Purpose

Before modifying the deterministic telemetry core, inspect the actual runtime interfaces
of:

- `telemetry.Telemetry`
- `laps.LapAnalyzer`
- `delta_comparison.DeltaComparison`
- `sector_analysis.SectorAnalysis`

The current intra-session analyzer constructs a single `Telemetry`, a single
`LapAnalyzer`, and `DeltaComparison(lap_analyzer)`. H5.2 needs two independent raw
sessions, so the correct extension point must be verified from the real repository code,
not guessed.

## What the probe verifies

Using `dual_reference_context.json` + History schema 4, it:

1. resolves current and historical session IDs/laps;
2. reads each session's `source_database_path` / `source_json_path` from History;
3. resolves both raw DuckDB files inside `telemetria/`;
4. confirms exact same track/layout/vehicle_variant/car;
5. opens both DuckDBs through the existing `Telemetry` class;
6. constructs two existing `LapAnalyzer` instances;
7. confirms the selected laps exist in raw telemetry;
8. records public method signatures, module paths and safe source snippets for
   `LapAnalyzer` and `DeltaComparison`.

It does not modify telemetry, History, matcher, H4, H5.1 or coaching.

## Why this is a checkpoint rather than a workaround

The goal is to make the smallest reusable core change, likely one of:

- expose a deterministic `lap_trace(lap)` primitive from `LapAnalyzer`, then compare two
  traces;
- generalize `DeltaComparison` to accept independent reference/comparison lap sources;
- introduce a small adapter consumed by the existing comparison/event pipeline.

Which one is correct depends on the actual core implementation returned by this probe.
We do not duplicate the v3.8 event logic.
