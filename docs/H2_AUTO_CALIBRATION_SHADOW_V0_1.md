# H2 automatic calibration shadow v0.1

`auto_calibrate_matcher.py` audits accumulated human labels and derives candidate
thresholds by exact track, layout and vehicle variant.

Its authority is strictly `SHADOW_ONLY`:

- it never creates human labels;
- every context is emitted with `authorized: false`;
- its default report lives under
  `data/generated/diagnostics/h2_auto_calibration_shadow.json`;
- neither `episode_pair_matcher.py` nor its v0.3 alias reads that report;
- production promotion requires an explicit, reviewed source change plus tests.

The tool deduplicates stable pair IDs across successive batches. A later human
review may supersede an older label only when both timestamps exist and establish
a strict order. Equal or missing timestamps with conflicting labels fail closed.

Run the audit without writing a report:

```powershell
python auto_calibrate_matcher.py --dry-run
```

Generate the ignored diagnostic report:

```powershell
python auto_calibrate_matcher.py
```
