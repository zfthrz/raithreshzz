# H2 Monza LMP2 ELMS calibration checkpoint v0.1

## Scope

This checkpoint is restricted to the exact History context:

```text
track:           Autodromo Nazionale Monza
track layout:    Autodromo Nazionale Monza
vehicle family:  LMP2
vehicle variant: LMP2_ELMS
car observed:    IDEC Sport #18:ELMS25
```

It must not be transferred to `HYPER`, WEC-style `LMP2`, another circuit or
another layout.

## Reproducible batch

```text
batch id:             d4379744c6
independent sessions: 3
session ids:          15, 18, 19
candidate pairs:      455
review queue:          24
```

The batch lives under:

```text
calibration_batches/autodromo-nazionale-monza--lmp2-elms-d4379744c6/
```

## Human labels

```text
SAME:       11
DIFFERENT:  12
AMBIGUOUS:   1
SKIP:        0
```

`AMBIGUOUS` remains first-class evidence. It is not converted to `SAME` or
`DIFFERENT` to increase sample counts.

## Leakage-safe split

Complete sessions belong to only one partition. Pairs crossing the partition
boundary are excluded from both partitions.

```text
calibration sessions:        2 (18, 19)
evaluation sessions:         1 (15)
calibration pairs:           5
  SAME:                      1
  DIFFERENT:                 4
  AMBIGUOUS:                 0
evaluation pairs:            0
cross-split pairs excluded: 19
```

The evaluation session has no reviewed pair whose other endpoint is also in its
partition. Changing the seed or allowing session leakage merely to obtain rows
would invalidate the intended independence of the measurement.

## Result and authorization boundary

```text
overall status: READY_FOR_MORE_REAL_DATA
matcher status: BLOCKED_BY_REAL_DATA
```

The batch confirms that feature extraction, human review, label validation,
dataset construction and descriptive feature reporting work in the exact Monza
`LMP2_ELMS` context.

It does not authorize:

- Monza `LMP2_ELMS` matcher thresholds or weights;
- automatic `MATCH`/`REJECT` decisions;
- importing Monza persistent patterns into History;
- enabling H3 in the normal per-session pipeline;
- combining this evidence with the separate Monza Hypercar batch.

## Next evidence requirement

Collect and import at least one additional independent Monza `LMP2_ELMS` session
with the same exact track/layout/vehicle context. Generate the new deterministic
batch, review its queue and require a non-empty, session-independent evaluation
partition before evaluating or authorizing a matcher.
