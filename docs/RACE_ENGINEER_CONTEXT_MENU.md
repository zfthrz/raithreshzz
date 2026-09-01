# Race Engineer Windows context menu

## Purpose

Add one reversible, per-user Windows Explorer action:

```text
Analizar con Race Engineer
```

The action runs the product's deterministic telemetry and debrief pipeline. It
does not require an API key, Ollama, llama.cpp or model selection, and it does
not replace the global `.duckdb` default application.

## Install

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_race_engineer_context_menu.ps1
```

The installer writes only below:

```text
HKCU\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyze
```

Administrator privileges are not required. Reinstalling also removes the old
Ollama and llama.cpp provider-specific Race Engineer verbs, if present.

## Use

1. Right-click an authorized telemetry `.duckdb`.
2. Select `Analizar con Race Engineer`.
3. Keep the console open until it displays `RESULT: PASS` or a blocking reason.

The launcher accepts only files under the LMU telemetry directory or the
repository's `telemetria` directory. It applies the existing path, size,
stability and valid-lap gates before producing the deterministic debrief.

## Execution contract

The launcher:

1. validates the telemetry path and rejects History databases;
2. checks file size and stability;
3. runs deterministic analysis and imports the session into History;
4. reads Python's `metadata.valid_laps` result;
5. requires enough valid laps for a debrief;
6. generates and validates the debrief with Python in fail-closed mode;
7. continues with the applicable deterministic H3/H4/H5 stages.

Existing valid outputs are reused unless an explicit force option is used by a
developer workflow. The Explorer action never selects or calls an LLM backend.

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File .\install_race_engineer_context_menu.ps1 -Uninstall
```

This removes only Race Engineer's current and legacy verbs under HKCU. It does
not alter DuckDB files, History, generated results or another program's default
association.
