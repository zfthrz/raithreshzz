# Automatic telemetry ingest v0.1

## Objetivo

Detectar archivos `.duckdb` nuevos y guardarlos en History sin iniciar varios
debriefs LLM juntos.

El flujo separa dos responsabilidades:

1. `scan` ejecuta el análisis determinista y la importación a History con
   `--no-llm --no-historical-context`.
2. `debrief-next` completa el LLM y el contexto histórico para una sola sesión.

Un fallo del LLM no elimina ni revierte la sesión ya importada.

## Primera activación

Registrar los DuckDB que ya existen sin analizarlos:

```powershell
python auto_ingest_telemetry.py baseline
```

Este paso evita interpretar todo el archivo histórico como telemetría nueva.

## Detectar e importar sesiones nuevas

```powershell
python auto_ingest_telemetry.py scan
```

Un archivo debe permanecer 10 minutos sin cambiar antes de procesarse. Además,
se comprueba que DuckDB pueda abrirlo en modo de sólo lectura.

Repetir `scan` es seguro: un archivo sin cambios que ya fue importado no vuelve a
procesarse. Si cambia después de la importación queda en
`CHANGED_REVIEW_REQUIRED` y no se modifica automáticamente.

## Incorporar gradualmente el archivo histórico

El baseline no analiza archivos preexistentes. Para importar uno por ejecución,
empezando por el más reciente:

```powershell
python auto_ingest_telemetry.py backfill-next --min-size-mb 5
```

Cada ejecución procesa como máximo un DuckDB y nunca llama al LLM. Los archivos
menores de 5 MiB quedan como `BASELINE_SKIPPED_SMALL` y no vuelven a evaluarse en
cada escaneo. Si un archivo falla queda como `BACKFILL_FAILED`; tampoco provoca
que el escaneo programado intente procesar todo el backlog.

Antes de elegir un archivo, el comando revisa los estados de ejecución existentes.
Si la sesión ya tiene un `session_id` de History o un debrief validado, reconcilia
el estado local sin repetir el análisis ni llamar al modelo.

El backfill prioriza llenar History. El filtro mínimo de dos vueltas válidas se
aplica después al elegir una sesión para el debrief LLM.

### Mantenimiento unificado

Para una tarea programada se recomienda usar:

```powershell
python auto_ingest_telemetry.py maintenance `
  --min-size-mb 5 `
  --backfill-minutes 30
```

Cada ejecución escanea primero las sesiones nuevas. Si encuentra una esperando
estabilidad, recién importada o fallida, omite el backfill. Sólo cuando el escaneo
está inactivo incorpora como máximo un histórico, respetando 30 minutos entre
intentos. Esto evita dos procesos simultáneos sobre History.

## Generar debriefs de a uno

### Procesar solamente la última sesión válida

Este es el comando recomendado para automatización:

```powershell
python auto_ingest_telemetry.py debrief-latest `
  --backend deepseek `
  --min-size-mb 5 `
  --min-valid-laps 2
```

El tamaño se mide en MiB y funciona como prefiltro. La cantidad de vueltas se
obtiene del campo determinista `metadata.valid_laps`, no se estima a partir del
tamaño.

Si existen varias sesiones pendientes elegibles, se procesa únicamente el
DuckDB más reciente según su fecha de modificación. Las anteriores se conservan
en History con estado `HISTORY_ONLY_SUPERSEDED`. Las ejecuciones posteriores no
recorren hacia atrás la cola ni generan debriefs antiguos.

### Procesar manualmente la siguiente sesión pendiente

DeepSeek:

```powershell
python auto_ingest_telemetry.py debrief-next --backend deepseek
```

Qwen local mediante Ollama:

```powershell
python auto_ingest_telemetry.py debrief-next --backend ollama
```

Cada ejecución procesa como máximo una sesión, comenzando por la más antigua.
Si el modelo falla, esa sesión continúa en `HISTORY_READY` para reintentar más
adelante.

## Consultar la cola

```powershell
python auto_ingest_telemetry.py status
```

Estados principales:

- `BASELINED`: existía al activar la herramienta y no se tocó.
- `BASELINE_SKIPPED_SMALL`: histórico excluido por el filtro de tamaño.
- `BACKFILL_FAILED`: falló su incorporación histórica y requiere revisión.
- `PENDING_STABILITY`: nuevo, todavía puede estar siendo escrito.
- `HISTORY_READY`: ya está en History; falta el debrief.
- `DEBRIEF_READY`: flujo completo terminado.
- `HISTORY_ONLY_INELIGIBLE`: está en History pero no cumple los filtros del debrief.
- `HISTORY_ONLY_SUPERSEDED`: está en History y otra sesión más reciente recibió el debrief.
- `FAILED`: falló análisis/importación y puede reintentarse con `scan`.
- `CHANGED_REVIEW_REQUIRED`: cambió después de procesarse; requiere revisión.

El estado operativo se guarda en:

```text
data/local/telemetry_auto_ingest.json
```

No se versiona en Git.

## Automatización de Windows

Primero se debe validar manualmente `baseline`, dos ejecuciones de `scan` y
`status`. Después puede programarse `scan` cada cinco minutos con el Programador
de tareas de Windows.

La activación automática de `debrief-latest` se hace únicamente después de
validar el flujo manual. El comando procesa como máximo una sesión y no recorre
sesiones anteriores, por lo que una detección masiva no dispara varias llamadas
pagas ni varias cargas consecutivas de la GPU local.
