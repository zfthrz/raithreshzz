# Race Engineer desktop GUI v0.4

GUI v0.4 adds local backend settings, deterministic lap-time inspection and a
neutral black/grey theme to the History-aware v0.3 interface.

## Backend settings

Use `Configuración` in the main header. The dialog controls:

- DeepSeek model (`DEEPSEEK_MODEL`);
- llama.cpp model (`LLAMACPP_MODEL`);
- local llama.cpp chat endpoint (`LLAMACPP_API_URL`).

Ollama remains fixed to the existing `ingenierov3` runtime contract. API keys are
never displayed, accepted by the settings model or written to disk. The llama.cpp
URL is restricted to HTTP(S) on `localhost`, `127.0.0.1` or `::1`, with an explicit
port and endpoint path.

Before a settings file exists, the GUI preserves compatible environment variables.
After the user saves, non-secret values are stored locally under:

```text
data/local/race_engineer_gui_settings.json
```

This path is ignored by Git. The values are passed only to the existing safe
`analyze_telemetry_file.py` subprocess and its descendants. The confirmation dialog
and execution log show the exact selected model before work begins.

## Lap times

The main session detail now includes `Vueltas`. It reads the deterministic analysis
JSON and shows, in lap order:

- lap number and exact time;
- the selected session reference;
- valid, discarded/incomplete and ignored-initial status;
- delta to the reference for every other valid lap.

No lap validity or delta is inferred by the GUI.

## Visual theme

Window, panels, tables, text areas and selected rows use black/neutral-grey tones.
Turquoise remains an informational accent and the analysis button remains dark red
to distinguish the action that may call an LLM from read-only navigation.

All v0.3 History/H4 behavior and all v0.2 launcher, UTF-8, no-cancel and validated
debrief recovery contracts remain unchanged.
