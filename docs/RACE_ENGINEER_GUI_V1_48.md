# Race Engineer GUI v1.48 — History statistics

GUI v1.48 adds a read-only `Estadísticas` workspace backed exclusively by History
schema 4.

The general summary reports imported sessions, valid laps, total distance from
valid `laps.lap_distance_m` values and favorite track, exact vehicle category and
recorded car/entry by valid-lap use. The monthly history repeats those metrics for
each calendar month with a valid `sessions.timestamp_utc` value. Double-clicking a
month opens its complete session detail with date, track, category, car/entry,
valid laps and kilometers. Invalid and discarded laps never contribute to lap or
distance totals.

Three native Tk donut charts summarize the general distribution of valid laps by
track, exact category and car/entry. Each chart shows the five largest groups and
combines the remainder as `Otros`; it does not add a plotting dependency or change
the underlying totals.

LMU stores team/entry names rather than a canonical model in `car_name_raw`.
Therefore GT3 and Hypercar fail closed to that recorded identity. The explicit
domain normalization is LMP2: `LMP2_WEC` and `LMP2_ELMS` retain separate category
statistics, but their car display is unified as `Oreca 07`; teams do not create
different cars.

Statistics load lazily when the workspace opens, run on a daemon worker and open
DuckDB read-only. An mtime/size fingerprint prevents repeated queries while History
is unchanged. No telemetry, History row, coaching, calibration or pipeline artifact
is modified.

Real local smoke checkpoint (2026-08-30):

```text
sessions:           120
valid laps:         452
distance:           2711.3 km
favorite track:     Circuit de Spa-Francorchamps
favorite category:  LMP2_ELMS
favorite car:       Oreca 07
```
