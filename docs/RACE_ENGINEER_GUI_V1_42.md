# Race Engineer GUI v1.42 — time-based playback and exact lap timing

Telemetry playback now advances from monotonic wall time rather than incrementing
one rendered point per callback. The selected 10/20/50 Hz resolution controls only
visual update density; rendering overhead cannot make a 50 Hz lap play slowly.

Every displayed track point preserves its lap-relative timestamp. The playback
marker snaps to the nearest existing/resampled telemetry point for the current wall
time, and stops at the authoritative lap duration. This does not invent telemetry
between samples.

Lap-list duration prefers native `Lap.ts` boundaries. When a loaded reference lap
was selected by an exact analysis duration, that duration remains authoritative.
The GUI formats lap and playback time to milliseconds, avoiding the previous
`.x00`/`.x50` appearance caused by using the last point of a resampled grid.

All changes are presentation-only and read the source DuckDB without modifying it.
