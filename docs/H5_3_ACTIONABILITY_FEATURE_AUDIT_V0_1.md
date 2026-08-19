# H5.3 Actionability Feature Audit v0.1

## Status

```text
Objective: H5.3b actionability feature audit (shadow)
Tool: audit_h5_3_actionability_features.py
Version: 0.1
Status: SHADOW_AUDIT_ONLY
Production authority: NONE
historical_actions_authorized: false
```

## Purpose

`audit_h5_3_actionability_features.py` is a **shadow/offline** tool that analyses the
H5.3b human-reviewed audit dataset (candidates + validated human labels) to describe
what **observational feature distributions** differentiate each `human_label`:

- `ACTIONABLE`
- `OBSERVATIONAL_ONLY`
- `NOT_COMPARABLE`
- `AMBIGUOUS`

The tool **does not**:

- produce an actionability score;
- recommend thresholds;
- promote a production rule;
- rank candidates globally;
- infer causality from correlations;
- assume brake is superior to throttle;
- convert speed into an action (speed remains context);
- merge `LMP2_ELMS` with `LMP2`.

Human labels remain ground truth for this audit.

## Inputs

The tool consumes two JSON files:

1. **H5.3b audit dataset** (`prepare_h5_3_audit_dataset.py` output):
   - `candidates[]` — one record per candidate from validated H5.3a shadow artifacts;
   - `metadata`, `sources`, `coverage` (read-only informational).

2. **Validated human labels** (`label_h5_3_audit_candidates.py` output):
   - `labels[]` — one record per reviewed candidate with `human_label`.

Before producing statistics, the tool **reuses** `validate_h5_3_audit_labels.py`
internally to confirm the label file is compatible with the dataset. If the label
validation fails (e.g. tampered `source_dataset_sha256`, unknown audit IDs, invalid
`human_label` values), the tool raises an error and stops.

## Features extracted

For each candidate with a valid human label, the tool extracts:

| Feature | Source |
|---|---|
| `audit_id` | Dataset `audit_id` |
| `human_label` | Labels `human_label` |
| `candidate_id` | Dataset `candidate_id` |
| `track` | Dataset `context.track` |
| `track_layout` | Dataset `context.track_layout` |
| `vehicle_variant` | Dataset `context.vehicle_variant` |
| `car_name_raw` | Dataset `context.car_name_raw` |
| `delta_sign` | Dataset `delta_sign` |
| `delta_change_s` | Dataset `evidence.delta_change_s` |
| `start_distance_m` | Dataset `evidence.start_distance_m` |
| `end_distance_m` | Dataset `evidence.end_distance_m` |
| `zone_length_m` | Derived: `end_distance_m - start_distance_m` |
| `speed_delta_avg` | Dataset `observational_channel_evidence.speed_delta_avg` |
| `throttle_delta_avg` | Dataset `observational_channel_evidence.throttle_delta_avg` |
| `brake_delta_avg` | Dataset `observational_channel_evidence.brake_delta_avg` |
| `channel_presence` | Derived: which `observational_channel_evidence` keys have numeric values |
| `channel_count` | Derived: count of present channels |
| `location_label` | Dataset `location_label` |
| `profile_localization` | Shadow: `"not_available"` (not exposed by H5.3a v0.1) |

If a feature the audit considers useful is **not available** from the dataset
schema, it is recorded in `missing_feature_inventory` rather than guessed.

## Output schema

```json
{
  "metadata": {
    "audit_version": "0.1",
    "generated_at_utc": "<ISO-8601>",
    "dataset_path": "<absolute>",
    "labels_path": "<absolute>",
    "policy": {
      "production_policy_changed": false,
      "historical_actions_authorized": false,
      "thresholds_promoted": false,
      "human_labels_are_ground_truth": true
    }
  },
  "status": "SHADOW_AUDIT_ONLY",
  "summary": {
    "total_labeled_candidates": <int>,
    "total_candidates_in_dataset": <int>,
    "label_records": <int>,
    "count_by_label": { "ACTIONABLE": n, "OBSERVATIONAL_ONLY": n, ... }
  },
  "distributions": {
    "count_by_track_and_label": { "TrackName": { "ACTIONABLE": n, ... }, ... },
    "count_by_delta_sign_and_label": { "current_slower": { ... }, ... },
    "delta_change_s_by_label": { "ACTIONABLE": { "count", "min", "max", "median", "mean", "p10", "p25", "p50", "p75", "p90" }, ... },
    "zone_length_m_by_label": { "ACTIONABLE": { "count", "min", "max", ... }, ... },
    "channel_availability_by_label": { "ACTIONABLE": { "speed_delta_avg": n, ... }, ... },
    "channel_sign_distribution_by_label": { "ACTIONABLE": { "speed_delta_avg": { "positive", "negative", "zero_or_none" }, ... }, ... },
    "channel_combinations_by_label": { "ACTIONABLE": { "brake|throttle|speed|steering": n, ... }, ... }
  },
  "labeled_items": [{ ... }],
  "missing_feature_inventory": ["feature1", "feature2", ...]
}
```

The `generated_at_utc` field is the only non-deterministic field; all other output
is deterministic for the same inputs.

## Aggregated statistics

For each `human_label` the tool produces:

1. **count_by_label**: total candidates per label.
2. **count_by_track_and_label**: candidates per `(track, label)` pair.
3. **count_by_delta_sign_and_label**: candidates per `(delta_sign, label)` pair.
4. **delta_change_s_by_label**: descriptive statistics (`count`, `min`, `max`,
   `median`, `mean`, `p10`, `p25`, `p50`, `p75`, `p90`) for `delta_change_s` per label.
5. **zone_length_m_by_label**: same descriptive statistics for `zone_length_m` per label.
6. **channel_availability_by_label**: count of candidates per label with each
   channel (`speed_delta_avg`, `throttle_delta_avg`, `brake_delta_avg`,
   `steering_delta_avg`) present.
7. **channel_sign_distribution_by_label**: for each channel, count of
   `positive` / `negative` / `zero_or_none` values per label.
8. **channel_combinations_by_label**: count of distinct channel-presence patterns
   (e.g. `brake|throttle|speed|steering`) per label.

Numeric fields use only descriptive statistics (no clustering, classification, or
threshold inference).

## What the tool does NOT produce

The tool explicitly does **not** produce:

- an actionability score;
- a classifier or model;
- recommended thresholds;
- a production rule;
- a global ranking;
- causal inferences.

## Usage

```bash
python audit_h5_3_actionability_features.py \
  h5_3_audit_dataset.json \
  h5_3_audit_labels.json \
  --output h5_3_actionability_feature_audit.json
```

## Test coverage

`tests/test_h5_3_actionability_feature_audit.py` includes:

- valid labels;
- ACTIONABLE label;
- OBSERVATIONAL_ONLY label;
- AMBIGUOUS label;
- missing numerical channels;
- zero delta;
- invalid/tampered labels rejected;
- deterministic output for same input;
- contract fields (`production_policy_changed`, `historical_actions_authorized`,
  `thresholds_promoted`, `human_labels_are_ground_truth`);
- channel availability distribution;
- delta sign by label;
- missing feature inventory;
- no-score/no-threshold/no-ranking invariant.

## See also

- `docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md` — H5.3 roadmap
- `docs/H5_3_AUDIT_REVIEW_2026_08_17.md` — H5.3b human review evidence
- `prepare_h5_3_audit_dataset.py` — H5.3b dataset builder
- `label_h5_3_audit_candidates.py` — H5.3b human reviewer
- `validate_h5_3_audit_labels.py` — H5.3b label validator
