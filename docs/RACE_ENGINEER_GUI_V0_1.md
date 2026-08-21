# Race Engineer desktop interface v0.1

## Scope

The first desktop slice is a read-only session hub. It does not run analysis,
call an LLM, edit History or change coaching authority.

It reads the orchestrator-owned `data/generated/runs/*/state.json` files and
shows:

- recent sessions;
- circuit, vehicle, valid-lap count and reference time;
- whether the session is only analyzed, stored in History or has a validated
  LLM debrief;
- the final deterministic debrief render;
- the concise next-stint plan;
- every orchestrator stage and its output paths.

Using `state.json` as the index avoids guessing which artifact is current and
preserves the existing `RUN`, `REUSED`, `SKIPPED_NOT_APPLICABLE` and `FAILED`
semantics.

## Start the interface

Double-click:

```text
RaceEngineer.pyw
```

or:

```text
launch_race_engineer_gui.cmd
```

From PowerShell:

```powershell
python race_engineer_gui.py
```

The `.pyw` and `.cmd` launchers avoid leaving a console window open with the
current Python installation.

## Read-only CLI probe

The same catalogue can be inspected without opening a window:

```powershell
python race_engineer_gui.py --list
```

This is useful for troubleshooting session discovery. A custom state root can
be supplied with `--runs-root`.

## Failure behavior

- A malformed `state.json` is reported but does not hide valid sessions.
- Missing output artifacts leave the session visible with the strongest status
  that can be proven.
- A session is labelled `Debrief validado` only when the orchestrator records
  `llm_validator` as `RUN` or `REUSED`.
- History-only sessions never appear as though they already have LLM coaching.
- Opening a folder is the only external action available in v0.1.

## Next slices

### v0.2 — explicit analysis launch

Add a telemetry picker, backend selection and visible progress by invoking the
existing safe launcher/orchestrator. Reuse its LMU-running, file-age, size and
valid-lap gates rather than duplicating them in GUI code.

### v0.3 — History and historical comparison

Expose compatible historical-reference status and the existing H4/H5.1/H5.2
artifacts while continuing to identify the current-session reference as coaching
authority.

### v0.4 — packaging and convenience

Add a Start Menu/desktop shortcut installer and consider packaging only after
the workflow stabilizes. The Python source remains the development authority.
