# Guía de comandos — `race_engineer.py`

`race_engineer.py` es el punto de entrada recomendado para procesar una sesión completa de Race Engineer.

Desde PowerShell, ubicado en la raíz del repositorio, el comando normal es:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

No es solamente un alias de `llm_analysis.py`. Es el **orquestador** que coordina las etapas aplicables, reutiliza resultados válidos y deja un estado trazable de la ejecución.

---

## 1. Qué ejecuta

El flujo completo puede incluir:

```text
DuckDB de telemetría
    ↓
analyze          análisis determinista y validación
    ↓
llm              debrief con DeepSeek u Ollama
    ↓
llm_validator    validación del resultado LLM
    ↓
history          importación idempotente en History
    ↓
h3               patrones persistentes, solo si existe calibración aplicable
    ↓
h4               selección de referencia histórica compatible
    ↓
h5_1             contexto de doble referencia
    ↓
h5_2             comparación determinista entre telemetrías compatibles
    ↓
h5_2_llm         narrativa histórica observacional controlada
```

No todas las etapas tienen que ejecutarse en todas las sesiones. Por ejemplo, H5.2 necesita una referencia histórica compatible y acceso a ambas telemetrías originales.

### Estados que muestra

| Estado | Significado |
|---|---|
| `RUN` | La etapa se ejecutó en esta ocasión. |
| `REUSED` | El resultado existente sigue siendo válido y fue reutilizado. |
| `SKIPPED_NOT_APPLICABLE` | La etapa no corresponde con las opciones o datos disponibles. |
| `FAILED` | La etapa falló; hay que revisar el mensaje anterior. |

Un `SKIPPED_NOT_APPLICABLE` no es necesariamente un error.

---

## 2. Comando recomendado

### Ejecución normal con DeepSeek

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

DeepSeek es el backend predeterminado. Para usarlo debe estar configurada la API key en el entorno.

Ejemplo con un archivo real:

```powershell
python race_engineer.py analyze "telemetria\Autodromo Nazionale Monza_P_2026-08-15T20_03_24Z.duckdb"
```

El programa reutiliza automáticamente las etapas que siguen siendo válidas. Repetir el comando normal no debería volver a pagar una llamada LLM si nada relevante cambió.

---

## 3. Opciones disponibles

| Opción | Para qué sirve |
|---|---|
| `--backend deepseek` | Usa DeepSeek. Es el valor predeterminado. |
| `--backend ollama` | Usa el modelo local configurado mediante Ollama. |
| `--history-db RUTA` | Usa una base History diferente de la predeterminada. |
| `--force` | Fuerza todas las etapas aplicables. Puede repetir llamadas con costo. |
| `--force-analyze` | Fuerza solamente el análisis determinista. |
| `--force-llm` | Fuerza una nueva ejecución del LLM y su validación. |
| `--no-llm` | No llama a DeepSeek ni a Ollama. |
| `--no-history` | No importa History y omite el contexto histórico posterior. |
| `--no-historical-context` | Mantiene el análisis/LLM/History, pero omite H3, H4 y H5. |
| `--dry-run` | Solo evita ejecutar el analizador cuando esa etapa necesita regenerarse; no simula de forma global todo el pipeline. |

Para ver la ayuda incorporada:

```powershell
python race_engineer.py --help
python race_engineer.py analyze --help
```

---

## 4. Recetas habituales

### Primera comprobación sin gastar API

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --no-llm
```

Sirve para verificar la telemetría, generar el análisis determinista e incorporar History sin llamar a un modelo. Las etapas LLM y la narrativa histórica LLM aparecerán como omitidas.

### Flujo completo después de la comprobación

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
```

El análisis ya válido normalmente se reutilizará y se ejecutarán las etapas pendientes.

### Usar Ollama local

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --backend ollama
```

El backend local normal usa el alias `ingenierov3`. El entry point experimental
del Qwen3.8 27B ejecuta solamente la etapa LLM sobre un análisis determinista ya
generado y conserva un output separado:

```powershell
python llm_analysis_qwen3_8_27b_iq3m.py "data\generated\analysis\SESSION.json"
```

Ver [`LLM_BACKEND_BENCHMARK_MONZA_V0_1.md`](LLM_BACKEND_BENCHMARK_MONZA_V0_1.md).

### Regenerar solamente el debrief LLM

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --force-llm
```

Puede generar una nueva llamada a la API y, por lo tanto, costo.

### Regenerar el análisis determinista sin usar LLM

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --force-analyze --no-llm
```

Es útil después de modificar `analyze_telemetry.py` o sus contratos.

### Forzar todo el pipeline aplicable

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --force
```

Usar solamente cuando realmente se necesita regenerar todo. Puede repetir llamadas LLM con costo aunque ya exista un resultado válido.

### Analizar sin guardar en History

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --no-history
```

Al no disponer de la etapa History en ese run, también se omite el contexto histórico H3/H4/H5.

### Guardar en History pero omitir comparaciones históricas

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --no-historical-context
```

La sesión puede analizarse, pasar por LLM e importarse en History, pero no se ejecutan H3, H4, H5.1 ni H5.2.

### Usar otra base History

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --history-db "data\local\otra_history.duckdb"
```

Conviene usar esta opción solamente si se quiere aislar una prueba o mantener historiales deliberadamente separados.

---

## 5. Flujo seguro para una telemetría nueva

Para una sesión recién grabada, el orden recomendado es:

1. Guardar el `.duckdb` dentro de `telemetria\`.
2. Ejecutar primero sin LLM:

   ```powershell
   python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --no-llm
   ```

3. Confirmar que el resumen termina en `RESULT: PASS`.
4. Ejecutar el flujo normal:

   ```powershell
   python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
   ```

5. Si se repite el comando, comprobar que las etapas válidas aparezcan como `REUSED`.

Este flujo permite detectar primero problemas de telemetría o validación sin consumir una llamada LLM.

---

## 6. Advertencias importantes

### `--force` puede tener costo

`--force` invalida la reutilización de todas las etapas aplicables. Si DeepSeek está habilitado, puede volver a llamar a la API aunque el resultado anterior sea válido.

Para regenerar únicamente lo necesario, preferir `--force-analyze` o `--force-llm`.

### `--dry-run` no es una simulación global

En la versión actual, `--dry-run` intercepta la ejecución del analizador solamente cuando el análisis necesita volver a generarse. Si existe un análisis reutilizable, el orquestador puede continuar con etapas posteriores.

Por eso, para garantizar que no se llame a ningún modelo, usar:

```powershell
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --no-llm
```

### Una referencia histórica puede no existir

H4 exige compatibilidad de circuito, layout, variante de vehículo y automóvil. Si no hay una sesión compatible, el resultado esperado es:
