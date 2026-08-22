# Race Engineer desktop GUI v0.5

GUI v0.5 adds local search and status filters to the main session catalogue built
in v0.1-v0.4.

## Search

The `Buscar` field matches every space-separated term against the already-loaded
orchestrator records. Searchable values include:

- session key and UTC/local date;
- circuit and session type;
- vehicle;
- general status and its driver-facing description.

Every term must match the same session. Search does not scan generated filenames,
open History, modify state or call an LLM.

## Status filters

The adjacent selector offers:

- `Todas`;
- `Con debrief` (`DEBRIEF_READY`);
- `Sólo History` (`HISTORY_READY`);
- `Fallidas` (`FAILED`).

The count shows visible sessions versus the complete loaded catalogue. Search and
status filters combine. Selection, double-click analysis and detail tabs continue
to resolve the exact `SessionRecord`, so filtering cannot change the DuckDB target.

After a successful analysis the GUI clears active filters, refreshes the catalogue,
selects the analyzed DuckDB and opens its Debrief tab.

All v0.4 settings/lap/theme behavior and earlier History, H4 and safe-launcher
contracts remain unchanged. Full analysis continues to invoke only
`analyze_telemetry_file.py`.
