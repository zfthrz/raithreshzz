# H2 Monza Hypercar calibration checkpoint v0.1

## Scope

This checkpoint is restricted to the exact History context:

```text
track:           Autodromo Nazionale Monza
track layout:    Autodromo Nazionale Monza
vehicle family:  HYPERCAR
vehicle variant: HYPER
car observed:    Toyota Racing 2026 #7:LM
```

It must not be transferred to `LMP2_ELMS`, another circuit or another layout.

## Reproducible batch

```text
batch id:          636633bd5e
independent sessions: 4
session ids:       13, 14, 16, 17
candidate pairs:   587
review queue:      24
```

The batch lives under:

```text
calibration_batches/autodromo-nazionale-monza--hyper-636633bd5e/
```

## Human labels

```text
SAME:       9
DIFFERENT: 13
AMBIGUOUS:  2
SKIP:       0
```

`AMBIGUOUS` remains first-class evidence. It is not converted to `SAME` or
`DIFFERENT` to increase sample counts.

## Leakage-safe split

The dataset assigns complete sessions to only one partition. Pairs crossing the
calibration/evaluation boundary are excluded from both partitions.

```text
calibration sessions:       3
evaluation sessions:        1
calibration pairs:          13
  SAME:                      3
  DIFFERENT:                 8
  AMBIGUOUS:                 2
evaluation pairs:            0
cross-split pairs excluded: 11
```

The evaluation session has no reviewed pair whose other endpoint is also in the
evaluation partition. Changing the seed or allowing session leakage merely to obtain
evaluation rows would invalidate the intended independence of the measurement.

## Result and authorization boundary

```text
overall status: READY_FOR_MORE_REAL_DATA
matcher status: BLOCKED_BY_REAL_DATA
```

The batch authorizes only these conclusions:

- the Monza Hypercar feature pipeline works on four compatible sessions;
- the human review and label validator completed;
- calibration dataset and descriptive feature report completed;
- more independent Monza Hypercar sessions are required for internal evaluation.

It does not authorize:

- Monza matcher thresholds or weights;
- automatic `MATCH`/`REJECT` decisions;
- importing Monza persistent patterns into History;
- enabling H3 in the normal per-session pipeline;
- using impact/time-loss similarity as the dominant matching feature.

## Next evidence requirement

Collect and import additional independent Monza Hypercar sessions in the same exact
track/layout/vehicle context. Regenerate a new deterministic batch signature, review
its queue and require a non-empty, session-independent evaluation partition before
evaluating a Monza matcher.
