# Race Engineer desktop GUI v1.2

GUI v1.2 adds a full-lap telemetry chart synchronized with the draggable GPS-map
marker introduced in v1.1.

## Visual contract

The lower part of the **Mapa** tab contains three independent lanes sharing one LMU
`Lap Dist` axis:

- speed in blue, scaled from zero to the next 50 km/h boundary above the observed
  lap maximum;
- throttle in green, fixed to 0–100%;
- brake in red, fixed to 0–100%.

Dragging the white point marker on the map moves a white vertical cursor through all
three chart lanes. Selecting an H5.2 zone or a validated next-stint priority shades
its exact distance interval behind the traces. The existing numeric point and zone
summary remains visible above the chart.

## Data ownership and safety

The chart consumes only the native channels already aligned by
`race_engineer_track_map.py` for the geometrically complete selected GPS lap. It does
not query a different lap, interpolate a historical reference, derive a new coaching
fact or write an export.

Each lane has its own declared scale; speed is never visually compared as though it
were a brake/throttle percentage. Missing optional channels leave that lane empty
without blocking the map or the other channels.

The feature remains descriptive and read-only. It changes no H5.2 zone, debrief
priority, coaching authority, historical action gate or pipeline artifact.

## Validation checkpoint

- targeted GUI/map tests: `26 passed`;
- full pytest: `983 passed`;
- `git diff --check`: PASS;
- no LLM call and no source DuckDB modification.

