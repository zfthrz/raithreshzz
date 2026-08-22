# Race Engineer desktop GUI v0.7

GUI v0.7 completes the read-only historical inspection path with a dedicated
**Comparación histórica** tab.

## Available comparison

When the orchestrator has produced H5.2, the tab shows:

- H5.2 status and exact track/vehicle context;
- historical History session, lap and time;
- current History session, reference lap and time;
- deterministic `current - historical` lap delta;
- track-profile localization mode and validation status;
- the validated H5.2 LLM observation and backend/model, when available.

If H5.2 LLM was not run, raw profile-localized zones are shown in track order.
They are not ranked or promoted to recommendations by the GUI.

## Non-applicable sessions

When no raw H5.2 artifact exists, the tab displays the exact orchestrator stage
status and directs the user to **Referencia histórica** to inspect the H4 result.
It does not guess a historical lap or search filenames for substitute artifacts.

## Authority

The tab is strictly observational and read-only. It does not:

- modify History or any generated artifact;
- authorize historical coaching or causal claims;
- replace the current-session reference;
- call an LLM;
- rerun any pipeline stage.

Full analysis still invokes only `analyze_telemetry_file.py`. All v0.6 safety
gates and the explicit stability-wait override contract remain unchanged.
