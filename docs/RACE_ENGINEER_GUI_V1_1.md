# Race Engineer desktop GUI v1.1

GUI v1.1 adds read-only native telemetry inspection to the GPS circuit map.

## User workflow

1. Select a session in the catalogue.
2. Open the **Mapa** tab.
3. Click within 18 pixels of the circuit trace.
4. Keep the left button pressed and drag the white marker along the circuit.
5. Inspect the continuously updated telemetry line below the map.

Every point can show:

- aligned LMU `Lap Dist`;
- `Ground Speed` in km/h (with `GPS Speed` as a source fallback);
- `Brake Pos` in percent;
- `Throttle Pos` in percent.

When the point belongs to an H5.2 zone or a validated next-stint priority, the GUI
also summarizes the samples inside that exact distance interval:

- minimum, mean and maximum speed;
- mean and maximum brake;
- mean and maximum throttle;
- the instantaneous values at the selected point.

The drag starts only from the circuit hit area. Once captured, the white marker
remains snapped to the nearest rendered GPS point while the cursor moves. Releasing
the button leaves it at the final point. Clicking outside the trace clears the
marker and selection.

## Alignment and safety contract

The additional channels are read from the same DuckDB, aligned to the same master
timeline and restricted to the same geometrically complete GPS lap already selected
by the v0.8 map contract. No second lap is inferred and no derived telemetry file is
written.

The DuckDB remains open with `read_only=True`. Missing optional channels render as
`—`; they do not prevent GPS geometry, H5.2 zones or validated priorities from being
shown. The summaries are descriptive inspection only. They do not create coaching,
change priority order, alter H5.2 authority or authorize historical actions.

## Validation checkpoint

- targeted track-map tests: `9 passed`;
- full pytest: `981 passed`;
- real read-only smoke test: latest Imola telemetry, complete GPS lap selected,
  native speed/brake/throttle values aligned and one 1000–1500 m interval summarized;
- no LLM call and no source DuckDB modification.
