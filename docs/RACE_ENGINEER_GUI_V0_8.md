# Race Engineer desktop GUI v0.8

GUI v0.8 introduces the base circuit map needed for later GPS-by-zone overlays.

## Map source

The **Mapa** tab reconstructs one lap directly from the selected LMU telemetry
DuckDB using the existing GPS extraction contract:

- `GPS Latitude` and `GPS Longitude` provide geometry;
- `GPS Time` aligns the native column channels;
- `Lap` boundaries are preferred, with `Lap Dist` reset as fallback;
- the session reference is matched to GPS groups by lap duration because analysis
  laps are one-based while native GPS boundary groups can be zero-based;
- coordinates are projected to local east/north metres.

The DuckDB is opened with `read_only=True`. The GUI does not create CSV, GeoJSON
or any other generated file.

## Interface behavior

GPS extraction runs in a daemon background thread so selecting a session does not
freeze the desktop interface. Results are cached in memory by exact database path,
mtime and reference lap. Switching sessions invalidates stale asynchronous results.

Before drawing, candidate groups must have at least 70% GPS coverage, 30 seconds,
1 km of Lap Dist, 90% of the session's maximum lap distance and 85% of its maximum
GPS path. This rejects short tails and incomplete reference groups. If the analysis
lap number points at such a group, the complete group whose duration matches the
reference time is used and the internal GPS group is reported in the status line.

The canvas:

- preserves the circuit aspect ratio;
- keeps north pointing upward;
- marks the lap start;
- rescales when the window changes size;
- reports missing files/channels without affecting the remaining tabs.

## Zone-ready contract

Every rendered GPS point retains its aligned LMU `Lap Dist` value. A later version
can therefore color exact H5.2 or track-profile distance intervals on the same
polyline without changing GPS extraction or introducing heuristic screen-space
matching.

The map is informational only. It does not call an LLM, alter coaching authority,
modify History or run the analysis pipeline. Full analysis still invokes only
`analyze_telemetry_file.py`.
