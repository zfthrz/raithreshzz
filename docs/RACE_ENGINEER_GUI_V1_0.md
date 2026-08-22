# Race Engineer desktop GUI v1.0

GUI v1.0 links the validated next-stint plan to the GPS circuit map.

## Priority source

The layer reads only `session_coaching_facts.next_stint_plan` from the exact debrief
path registered in orchestrator state. It is enabled only when:

- the debrief artifact exists; and
- `llm_validator` is `RUN` or `REUSED`.

A later H5 pipeline failure does not hide an already validated session debrief.
Unvalidated LLM output is never used for the priority layer.

Every priority must contain a finite, increasing `start_distance_m` /
`end_distance_m` interval. The GUI reuses the existing localized `track_location`
and `driver_cues`; it does not generate or reinterpret coaching text.

## Map layers

- grey: circuit outside active overlays;
- red/green: observational H5.2 loss/gain zones;
- blue: validated next-stint priority;
- white: selected next-stint priority;
- yellow: selected H5.2 observation.

When overlays overlap, a click resolves the validated next-stint priority first.
Its plan label, localized name, distance interval and driver cues are displayed
below the map. Clicking away clears selection.

## Authority

The blue layer visualizes coaching that was already authorized and validated by the
existing deterministic/LLM pipeline. The GUI does not create priorities, change
their order, authorize new numerical claims, call an LLM or modify any artifact.

Full analysis continues to invoke only `analyze_telemetry_file.py`; all launcher
safety gates remain unchanged.
