# Race Engineer GUI v1.40 — 50 Hz and discrete gear rendering

The telemetry model still aligns the selected lap at 10, 20 or 50 Hz, but the Tk
canvas no longer receives every redundant high-density vertex. Continuous speed,
throttle and brake traces retain the first, last and temporal extrema for each x
pixel. Gear emits only horizontal segments and real state transitions.

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
