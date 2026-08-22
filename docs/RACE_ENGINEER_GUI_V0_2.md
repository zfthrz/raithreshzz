# Race Engineer desktop interface v0.2

## Outcome

GUI v0.2 adds an explicit full-analysis workflow to the read-only session hub.
The interface still does not implement telemetry rules itself: it invokes
`analyze_telemetry_file.py`, which remains the sole safety authority.

## Workflow

1. Select DeepSeek, llama.cpp or Ollama in the header.
2. Double-click an existing session to reuse its registered DuckDB, or press
   **Elegir archivo…** for telemetry that is not in the catalogue yet.
3. Confirm the selected file and backend.
5. Follow the complete console output in the **Ejecución** tab.
6. After `RESULT: PASS`, the catalogue refreshes and selects the resulting
   session automatically.

The confirmation explicitly warns that DeepSeek is remote and can incur API
cost. Local backends require their corresponding server/model to be running.

## Safety ownership

Every GUI launch is an unbuffered subprocess call equivalent to:

```powershell
python -u analyze_telemetry_file.py "TELEMETRIA.duckdb" --backend BACKEND
```

The existing launcher rechecks:

- LMU is closed;
- the path is inside an authorized telemetry root;
- the file is a telemetry DuckDB rather than the History database;
- minimum size is 5 MiB;
- minimum stability age is 10 minutes;
- deterministic analysis and History complete first;
- Python confirms at least two valid laps before any LLM call.

GUI code does not bypass or duplicate these decisions.

The double-click lookup uses the exact `database` path stored by the orchestrator
in that session's `state.json`. If the raw file was moved or removed, the GUI
reports that condition and does not guess another file with a similar name.

## Process behavior

- Only one analysis can run from the GUI at a time.
- There is intentionally no cancel button.
- Closing the window is rejected while an analysis is active, preventing an
  accidental interruption or loss of visible progress.
- Launcher exit `0` is shown as PASS, exit `2` as a safe BLOCKED result and any
  other exit as FAILED.
- A PASS refreshes the selected session and opens its Debrief tab automatically.
- If a process reports a late error after its debrief was already saved and
  validated, the GUI exposes it as `RECOVERED_VALID_DEBRIEF` and keeps any
  unfinished downstream pipeline stages visible for inspection.
- Standard output and errors are merged into the visible execution log.
- The GUI forces UTF-8 for the launcher and all descendant Python processes,
  preventing Windows CP1252 console errors on arrows and accented text after a
  valid LLM result has been generated.

## Start

Double-click `RaceEngineer.pyw` or run:

```powershell
python race_engineer_gui.py
```

The read-only session-list probe remains available:

```powershell
python race_engineer_gui.py --list
```

## Local backend configuration

v0.2 uses the same environment configuration as the existing command-line
backends. It does not maintain a second model registry. Start the desired Ollama
or llama.cpp server before selecting a local backend. Model/server configuration
will move into a dedicated settings screen only after runtime behavior has been
validated through the GUI.

## Deferred

- desktop/Start Menu shortcut installer;
- packaging into a standalone executable.

The History browser and historical-reference detail were completed in GUI v0.3.
The non-secret model/server settings screen was completed in GUI v0.4.

The v0.1 read-only contract remains documented in
`docs/RACE_ENGINEER_GUI_V0_1.md`.
