# Race Engineer desktop GUI v0.3

GUI v0.3 adds a read-only History browser and explicit H4 historical-reference
detail to the safe analysis workflow documented in `RACE_ENGINEER_GUI_V0_2.md`.

## History browser

Use the `History` button in the main header. The browser:

- opens `data/local/race_engineer_history.duckdb` with DuckDB `read_only=True`;
- requires History schema 4 and never initializes, migrates or imports data;
- lists sessions latest-first with circuit, vehicle, valid-lap count and reference time;
- filters locally by space-separated ID, date, circuit, layout, session, vehicle or weather terms;
- shows every stored lap and marks valid, discarded, ignored and reference flags;
- displays the exact source analysis and source DuckDB recorded by History.

If scheduled maintenance is writing History at that instant, the browser reports
the database error without retrying, mutating or bypassing the History contract.

## Historical reference tab

The main session detail includes `Referencia histórica`. It reads the exact H4
artifact recorded in orchestrator `state.json` and displays:

- current session reference lap and time;
- exact track/layout/vehicle/car context;
- considered, eligible and rejected candidate counts;
- selected History session, lap, time and delta when one exists;
- the explicit no-compatible-reference result otherwise.

This view is observational. It does not run H4, select a different candidate,
replace `session_reference`, authorize historical coaching or call an LLM.

## Analysis controls

`Elegir archivo…` now uses a dedicated dark-red style so the action that can
start a remote or local LLM analysis is visually distinct from read-only controls.
All v0.2 launcher gates, UTF-8 propagation, no-cancel behavior and validated-debrief
recovery remain unchanged. Full analysis still invokes only the existing safe
`analyze_telemetry_file.py` entry point.
