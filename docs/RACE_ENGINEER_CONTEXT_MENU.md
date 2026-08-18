# Race Engineer Windows context menu

## Purpose

Add reversible per-user Windows Explorer actions for explicitly requesting a full
analysis of one telemetry DuckDB with either backend:

```text
Analizar con Race Engineer (DeepSeek)
Analizar con Race Engineer (ingenierov3)
Analizar con Race Engineer (llama.cpp)
```

The DeepSeek action runs the default remote backend; the `ingenierov3` action runs
the local Ollama backend; the `llama.cpp` action runs the OpenAI-compatible local
server (default `http://localhost:8080/v1/chat/completions`, model
`qwen3-14b`). Neither replaces the global `.duckdb` default application.

Before using the `ingenierov3` action, Ollama must be running locally with the
`ingenierov3` model available:

```powershell
ollama pull ingenierov3
```

The local backend defaults to `http://localhost:11434/api/chat`.

## Install

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_race_engineer_context_menu.ps1
```

The installer writes only below:

```text
HKCU\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyze
HKCU\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyzeOllama
HKCU\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyzeLlamacpp
```

Administrator privileges are not required.

## Use

1. Close Le Mans Ultimate.
2. Wait at least 10 minutes after telemetry stopped changing.
3. Right-click the telemetry `.duckdb`.
4. Select `Analizar con Race Engineer (DeepSeek)`.
5. Keep the console open until it displays `RESULT: PASS` or a blocking reason.

For the local backends, select `Analizar con Race Engineer (ingenierov3)` or
`Analizar con Race Engineer (llama.cpp)` instead. All verbs run the same safety
gates; only the LLM backend differs.

The launcher accepts only files under:

```text
C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry
<repository>\telemetria
```

## Execution contract

The launcher performs these gates in order:

1. refuse while `Le Mans Ultimate.exe` is running;
2. require an authorized `.duckdb` path;
3. reject any filename containing `race_engineer_history`;
4. require at least 5 MiB;
5. require file mtime to be at least 10 minutes old;
6. run deterministic analysis and History import without LLM;
7. read Python's `metadata.valid_laps` result;
8. require at least two valid laps;
9. run the full selected backend pipeline (DeepSeek, Ollama/`ingenierov3` or
   llama.cpp).

The first stage can safely remain in History if the LLM gate is withheld. Existing
valid stage outputs are reused by `race_engineer.py`; the launcher does not use
`--force` and therefore does not intentionally duplicate model calls.

## Validation status

The per-user registration was installed successfully and the action
`Analizar con Race Engineer (DeepSeek)` appeared in Windows Explorer. The focused
launcher/automation checkpoint passed 22 tests. The first complete Explorer-triggered
DeepSeek run remains the final manual validation step.

Temporarily disable the scheduled ingest task during that first run and re-enable it
afterward to avoid concurrent History writers.

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File .\install_race_engineer_context_menu.ps1 -Uninstall
```

This removes only the Race Engineer verb created under HKCU. It does not alter
DuckDB files, History, generated results or another program's default association.
