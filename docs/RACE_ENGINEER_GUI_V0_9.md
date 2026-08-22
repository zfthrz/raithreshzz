# Race Engineer desktop GUI v0.9

GUI v0.9 adds deterministic H5.2 zones to the read-only GPS circuit map.

## Overlay source

Zones come only from the exact H5.2 `cross_session_comparison.json` path registered
in the selected orchestrator `state.json`. The GUI does not discover substitutes by
filename and does not calculate new comparison zones.

Each valid `zone_summary` supplies:

- start/end LMU Lap Dist;
- loss/gain observation type;
- deterministic delta change;
- localized track-profile label when available.

Invalid or reversed intervals are ignored rather than drawn.

## Display

- grey: circuit outside H5.2 comparative zones;
- red: deterministic time-loss zone;
- green: deterministic time-gain zone;
- yellow: zone currently selected by the user.

The legend and summary report zone/loss/gain counts. Clicking within 18 pixels of
the trace selects the corresponding Lap Dist point and displays its label, zone ID,
distance interval and delta change. Clicking away from the trace clears selection.

## Authority

The overlay is observational and read-only. It does not rank zones, authorize an
action, infer causality, change the current-session reference, call an LLM or modify
History/artifacts. Sessions without H5.2 retain the neutral circuit map from v0.8.

Full analysis still invokes only `analyze_telemetry_file.py` and all launcher safety
gates remain unchanged.
