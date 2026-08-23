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

## Usar directamente la carpeta de LMU

La fuente recomendada en Windows es:

```text
C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry
```

Race Engineer abre esos DuckDB en modo `read_only=True`. Para cambiar desde una
copia dentro del repo sin que todos los archivos parezcan nuevos:

```powershell
python auto_ingest_telemetry.py `
  --telemetry-dir "C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry" `
  migrate-source
```

La migración exige coincidencia exacta de nombre, tamaño y fecha de modificación.
Preserva los estados coincidentes y registra como `PENDING_STABILITY` únicamente
los archivos exclusivos de la fuente nueva. No abre DuckDB, no analiza y no llama
al LLM. Si encuentra una identidad ambigua se bloquea sin adivinar.

Los comandos `backfill-next`, `maintenance`, `debrief-next` y `debrief-latest`
respetan `--telemetry-dir`; no recorren entradas pertenecientes a una fuente
anterior.

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

Antes de cualquier operación, `maintenance` comprueba el proceso de Windows
`Le Mans Ultimate.exe`. Mientras el juego está abierto termina con
`SKIPPED_GAME_RUNNING`: no escanea, no analiza, no abre DuckDB, no ejecuta LLM y
no lanza procesos secundarios. La comprobación usa `CREATE_NO_WINDOW` para no
mostrar una consola. El archivo nuevo se detecta después de cerrar el juego y a
partir de entonces cumple la espera normal de estabilidad.

Además se registra `last_game_seen_at`. Tras cerrar LMU, el mantenimiento entra
en `POST_GAME_SETTLE` durante 10 minutos antes de abrir o analizar cualquier
DuckDB, incluso si un estado anterior consideraba estable al archivo. El umbral
de 5 MiB nunca sustituye esta barrera: sólo filtra candidatos de backfill o LLM.

## Administrar la tarea programada

La tarea instalada se llama:

```text
RaceEngineer-History-Ingest
```

Instalar o actualizar la acción oculta:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_history_ingest_task.ps1
```

El instalador resuelve el Python real, usa su `pythonw.exe` y conserva una tarea
existente actualizando únicamente su acción. Si la tarea no existe, la crea con
repetición cada minuto y evita instancias simultáneas.

La acción ejecuta `hidden_history_ingest.py`. No aparece ninguna consola. Toda la
salida normal y los errores quedan en:

```text
data\local\telemetry_auto_ingest_task.log
data\local\telemetry_auto_ingest_task.log.1
```

Después de un mantenimiento de History exitoso, el mismo runner oculto ejecuta
`maintain_h5_3_action_review.py`. Esta segunda etapa busca nuevos
`historical_actions.json` ya producidos por análisis completos, pero no ejecuta el
LLM. Si la cola cambió, crea el siguiente par numerado `action_review_queue_vN.json`
y `action_review_labels_vN.json`, migrando solo labels con identidad y snapshot
exactamente iguales. Nunca sobrescribe una revisión existente ni decide labels.

El estado se consulta en:

```powershell
Get-Content .\data\local\h5_3_review_maintenance.json
```

`NEW_REVIEW_REQUIRED` indica que `pending_review_count` contiene casos nuevos para
revisión manual. Un fallo H5.3 queda en el log y en ese estado, pero no bloquea la
ingestión de History.

Cuando `pending_review_count` llega a cero, el mantenimiento reconstruye y valida en
orden H5.3g, H5.3h y H5.3i. Los paths y conteos quedan en el mismo estado local bajo
`downstream_status: AUDITS_CURRENT`. Con casos pendientes devuelve
`WAITING_FOR_HUMAN_REVIEW` y no intenta inferir labels.

El log rota al alcanzar 2 MiB y conserva una copia anterior. Ambos archivos están
dentro de `data/local/` y no se versionan.

Reactivar después de una prueba manual:

```powershell
Enable-ScheduledTask -TaskName "RaceEngineer-History-Ingest"
```

Verificar estado, acción y próxima ejecución:

```powershell
Get-ScheduledTask -TaskName "RaceEngineer-History-Ingest" |
  Select-Object TaskName, State, Actions

Get-ScheduledTaskInfo -TaskName "RaceEngineer-History-Ingest" |
  Select-Object LastRunTime, LastTaskResult, NextRunTime
```

El estado esperado después de reactivarla es `Ready`; `LastTaskResult = 0` confirma
la última ejecución terminada correctamente. La acción debe conservar como fuente
`pythonw.exe`, con `hidden_history_ingest.py` como argumento. Desactivar temporalmente
durante una prueba manual evita que dos procesos intenten escribir History al mismo
tiempo.

Para inspeccionar un error sin depender de una consola fugaz:

```powershell
Get-Content .\data\local\telemetry_auto_ingest_task.log -Tail 100
```

## Backfill con una sola vuelta válida

Un DuckDB puede superar 5 MiB y abrir correctamente, pero no contener dos vueltas
utilizables. El analizador necesita al menos una referencia y otra vuelta para formar
una comparación validable. Si sólo queda una vuelta, escribe el JSON determinista con
`comparisons=[]` y `--validate` termina con código 1.

`auto_ingest_telemetry.py` reconoce ese caso y lo registra como
`BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS`, no como `BACKFILL_FAILED`.

Casos reales conocidos:

```text
Monza 2026-08-15T05_01_19Z: lap 1 válida; lap 2 incompleta
Spa   2026-08-12T07_32_09Z: lap 1 válida; lap 2 incompleta
```

Es un resultado no aplicable, no evidencia de corrupción. No llama al LLM, no se
importa como una comparación válida en History y no debilita
`validate_global_output`.

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
- `BACKFILL_SKIPPED_INSUFFICIENT_VALID_LAPS`: histórico sin una comparación
  validable por vueltas válidas insuficientes.
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
