# Race Engineer GUI v1.40 — 50 Hz and discrete gear rendering

The telemetry model still aligns the selected lap at 10, 20 or 50 Hz, but the Tk
canvas no longer receives every redundant high-density vertex. Continuous speed,
throttle and brake traces retain the first, last and temporal extrema for each x
pixel. Gear emits only horizontal segments and real state transitions.
Dense traces are sent to Tk in overlapping chunks of at most 750 points, avoiding
platform-specific single-polyline limits. Changing resolution keeps the previous
chart visible while the 50 Hz lap loads in the background; a failed refresh reports
the error and preserves that chart instead of leaving an empty panel. The internal
startup resolution now matches the visible `20 Hz` selector.

Some LMU files retain multiple samples from the previous lap immediately before
the `Lap Dist` reset (for example `6975, 6975, 0, 1, 2...`). At 50 Hz that prefix
previously caused the renderer to stop after one point and show an apparently
loaded but empty chart. The chart now splits only at the existing physical reset
threshold and renders the segment with the greatest distance coverage. This is a
display-only selection; no sample or analysis artifact is rewritten.

Gear is a discrete LMU event channel. It now uses previous-value hold rather than
linear interpolation, which cannot invent intermediate gears. LMU zero sentinels
bracketed by positive gears and short same-gear bounces are removed from the display
trace; genuine leading/trailing neutral remains visible. The source DuckDB and all
deterministic analysis evidence remain untouched.

Real validation used the Fuji reference lap at 50 Hz:

- 5125 aligned lap points;
- visible speed, throttle, brake and gear series;
- gears 1 through 6;
- impossible mid-lap neutral samples: 12 before, 0 after.

The boundary fix was also validated read-only on the ten most recent Spa DuckDBs
available locally. All ten produced visible speed, throttle, brake and gear series
at 50 Hz; affected files changed from 1-2 points per lane to roughly 2900-3135.
