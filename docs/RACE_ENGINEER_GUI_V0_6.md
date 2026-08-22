# Race Engineer desktop GUI v0.6

GUI v0.6 adds an explicit, per-run override for the 10-minute telemetry
stability wait. It is intended for a session the user knows has finished writing
and wants to analyze immediately.

## Use

1. Close Le Mans Ultimate.
2. Select **Omitir espera 10 min** in the GUI header.
3. Select or double-click the telemetry session and confirm the warning.

The option starts disabled every time the GUI opens. It applies only to the next
analysis while selected; it does not modify the scheduled automatic ingest.

The equivalent command-line invocation is:

```powershell
python analyze_telemetry_file.py "TELEMETRIA.duckdb" --backend BACKEND --skip-stability-wait
```

## Safety boundary

The override skips only the file-age check in `analyze_telemetry_file.py`. It
does not bypass any of these requirements:

- Le Mans Ultimate must be closed;
- the path must be inside an authorized telemetry directory;
- the input must be a telemetry DuckDB, not the History database;
- the file must be at least 5 MiB;
- deterministic analysis and History import run before the LLM;
- Python must confirm at least two valid laps;
- the selected output validators must pass.

The confirmation dialog and execution log state when the override is active.
The launcher remains the sole authority for every retained gate.

All v0.5 search/filter behavior and the earlier lap, settings, History, H4 and
safe-launcher contracts remain unchanged.
