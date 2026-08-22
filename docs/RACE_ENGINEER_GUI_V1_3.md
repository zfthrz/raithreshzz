# Race Engineer desktop GUI v1.3

GUI v1.3 improves the synchronized telemetry chart with higher visual sampling and
an explicit distance-window navigation contract.

## Controls

- Place the pointer over the telemetry chart and use the mouse wheel to zoom around
  that distance.
- Use **Shift + mouse wheel** to move the current window left or right without
  changing its span.
- Select **Restablecer gráfico** to return to the complete-lap chart.
- Continue dragging the white marker on the GPS map. If it leaves the visible chart
  window, that window follows automatically while preserving its current span.

The status line reports the exact visible start/end distances and span.

## Resolution

The read-only map loader now aligns the selected complete lap at 10 Hz instead of
5 Hz. This improves brake/throttle transition rendering while remaining light enough
for the Tk canvas and preserving the same native-channel interpolation contract.

The real Imola smoke test produced 967 complete-lap points (previously approximately
483 at 5 Hz). A representative 20% zoom window retained 194 samples for each of
speed, throttle and brake.

## Safety and boundaries

Zoom and pan only change the visible `Lap Dist` interval. They never alter the source
samples, chosen GPS lap, zone boundaries, priorities, summary calculations or any
pipeline artifact. Every window is clamped to the complete-lap distance range and
has a minimum 100 m span.

The feature remains descriptive and read-only. It grants no coaching or historical
authority and performs no LLM call.

## Validation checkpoint

- targeted GUI/map tests: `28 passed`;
- full pytest: `985 passed`;
- real read-only Imola resolution/zoom smoke test: PASS;
- `git diff --check`: PASS.
