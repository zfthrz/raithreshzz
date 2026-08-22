# H5.3 current-faster whole-lap sign correction — 2026-08-22

## Problem

The H5.3a raw-to-runtime normalizer derived `delta_sign` independently from each
zone's local `delta_change_s`. A whole lap that was faster than its historical
reference could therefore expose local-loss zones as `current_slower`, allowing the
shadow action policy to produce actions contrary to its anti-regression contract.

Real reproduction: Interlagos current lap `87.140 s` versus historical lap
`87.320 s`, total current-minus-historical delta `-0.180 s`. The pre-fix runtime
artifact incorrectly contained three actions.

## Correction

- runtime eligibility version is `0.2`;
- H5.3a `total_delta.current_minus_historical_s`, `sign` and tolerance are validated
  together and fail closed on disagreement;
- every normalized candidate carries the whole-lap sign;
- zone `delta_change_s` remains unchanged as local significance/ranking evidence;
- the action-policy anti-regression guard continues to accept actions only when the
  whole-lap sign is `current_slower`;
- the orchestrator H5.3 shadow reuse signature now hashes imported eligibility,
  selection, action-policy and validator modules.

## Real replay

```text
Total delta: -0.180 s
Whole-lap sign: current_faster
Selected local-loss candidates: 3
Authorized actions: 0
Withheld: 3
Reason: current_lap_faster_no_actions
validate_historical_actions: PASS
historical_actions_authorized: false
```

This produces reviewable shadow evidence only. The H5.3f `current_faster` gap remains
open until the new withheld artifact receives an explicit human label and the v0.2
evidence gate is rerun.
