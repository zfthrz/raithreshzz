# Race Engineer GUI v1.39 — H3 import readiness

`Circuitos → Readiness` exposes the state of existing official H3 bundles without
materializing them or writing History.

The read-only detector selects the largest/newest batch for each exact
`track + track_layout + vehicle_variant` context and reports:

- `H3_NOT_APPLICABLE`: no official H3 materialization exists;
- `H3_READY_TO_IMPORT`: the bundle passes the production import validator and its
  exact stable identity is not present in the selected History DB;
- `H3_IMPORTED`: that exact bundle identity is already present;
- `H3_CONFLICT`: H3 declared `conflict_review_required` and import is blocked;
- `H3_FAILED`: the materialization is incomplete, History is unavailable, or the
  production provenance/context validator rejected it.

The detector does not run H2, build H3 outputs, create labels, write History or
authorize historical coaching. Calibration readiness and H3 import readiness remain
separate fields. Automatic scheduler import is intentionally still disabled.
