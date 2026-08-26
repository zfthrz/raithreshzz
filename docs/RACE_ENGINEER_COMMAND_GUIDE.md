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

### Rerenderizar un resultado existente sin llamar al LLM

```powershell
python rerender_llm_analysis_output.py "data\generated\llm_results\SESSION\RESULTADO.json" --output "data\generated\rerender_tests\preview.json"
```

Reconstruye cues, prioridades deterministas y el render final con el código actual,
luego ejecuta el validator completo. El source no se modifica y el output debe ser una
ruta diferente. Si el destino ya existe, solo puede reemplazarse explícitamente con
`--overwrite`.

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

### Auditar selecciones históricas H5.2 sin usar un modelo

```powershell
python audit_h5_2_zone_selection.py `
  "data\generated\h5_2\SESSION\cross_session_comparison.json" `
  "data\generated\h5_2_llm\SESSION\MODELO_A.json" `
  "data\generated\h5_2_llm\SESSION\MODELO_B.json" `
  --output "data\generated\h5_2_audits\selection_audit.json"
```

Este comando reutiliza resultados existentes, valida sus SHA-256 y compara rankings
de impacto, intensidad y curvas. No hace llamadas API, no carga Ollama y no altera el
pipeline. Su resultado es exclusivamente shadow y no autoriza una fórmula de ranking
ni recomendaciones históricas.

### H5.3 runtime shadow

Cuando existen los prerequisitos H4/H5.1/H5.2, `race_engineer.py analyze` ejecuta
también el pipeline H5.3 runtime en modo shadow. La selección es determinista por
defecto: no consume API ni carga un modelo local. Escribe estos artefactos:

```text
data/generated/h5_3_shadow/SESSION/candidate_eligibility.json
data/generated/h5_3_shadow/SESSION/candidate_selection.json
data/generated/h5_3_shadow/SESSION/historical_actions.json
data/generated/h5_3_shadow/SESSION/shadow_pipeline.json
```

Para una prueba explícita con un modelo se puede definir temporalmente el backend:

```powershell
$env:H5_3_BACKEND = "deepseek"  # también ollama o llamacpp
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --force
Remove-Item Env:\H5_3_BACKEND
```

Esta opción puede tener costo o tiempo de carga. No cambia el debrief visible y
`historical_actions_authorized` continúa siendo `false`. Para desactivar solamente
este pipeline shadow:

```powershell
$env:H5_3_SHADOW_ENABLED = "0"
python race_engineer.py analyze "telemetria\ARCHIVO.duckdb"
Remove-Item Env:\H5_3_SHADOW_ENABLED
```

### Revisar acciones H5.3 en shadow

Este flujo no llama a ningún LLM ni cambia el debrief. Primero prepara una cola
deduplicada desde todos los `historical_actions.json` válidos:

```powershell
python prepare_h5_3_action_review_queue.py `
  --input-root "data\generated\h5_3_shadow" `
  --output "data\generated\h5_3\action_review_queue.json"
```

Después abre la revisión interactiva. Cada respuesta se guarda inmediatamente y el
comando puede cerrarse con `q` y retomarse más adelante:

```powershell
python label_h5_3_action_review_queue.py `
  "data\generated\h5_3\action_review_queue.json" `
  --labels "data\generated\h5_3\action_review_labels.json" `
  --reviewer "thres"
```

Al terminar —o para comprobar un avance parcial— validar los labels:

```powershell
python validate_h5_3_action_review_labels.py `
  "data\generated\h5_3\action_review_queue.json" `
  "data\generated\h5_3\action_review_labels.json"
```

Un `PASS` con advertencia de pendientes significa que el archivo es consistente,
pero la revisión todavía no terminó. Estos labels siguen siendo evidencia humana
shadow y nunca activan `historical_actions_authorized`.

Si aparecen nuevos artifacts, generar una cola con otro nombre y migrar únicamente
los labels cuya identidad y snapshot continúan exactamente iguales:

```powershell
python migrate_h5_3_action_review_labels.py `
  "data\generated\h5_3\action_review_queue.json" `
  "data\generated\h5_3\action_review_labels.json" `
  "data\generated\h5_3\action_review_queue_v2.json" `
  --output "data\generated\h5_3\action_review_labels_v2.json"
```

La migración nunca copia un label si cambió el caso revisado; ese caso vuelve a
quedar pendiente.

Desde eligibility v0.2, el delta positivo local de zona decide significancia, pero
`delta_sign` proviene exclusivamente del delta validado de la vuelta completa. Una
vuelta globalmente `current_faster` puede contener pérdidas locales seleccionables;
la política actual las deja en `WITHHELD` para que la protección anti-regresión pueda
revisarse con evidencia real.

Las colas nuevas conservan por ocurrencia el delta temporal local y los promedios
disponibles de velocidad, acelerador y freno. El labeler los muestra también para
casos `WITHHELD`. Son diferencias `current - historical`; aportan contexto humano,
pero no constituyen por sí solas una acción ni modifican la política.

Para reconstruir exclusivamente los casos revisados donde la vuelta actual era
globalmente más rápida pero existía pérdida local, ejecutar el auditor H5.3g:

```powershell
python audit_h5_3_faster_lap_withholding.py `
  "data\generated\h5_3\action_review_queue_v4.json" `
  "data\generated\h5_3\action_review_labels_v4.json" `
  --output "data\generated\h5_3\faster_lap_withholding_audit_v0_1.json"

python validate_h5_3_faster_lap_withholding.py `
  "data\generated\h5_3\faster_lap_withholding_audit_v0_1.json"
```

El validator reconstruye todo desde la cola, los labels y las selecciones con hash.
El resultado es diagnóstico shadow: no cambia la política, no autoriza acciones y no
activa `historical_actions_authorized`.

Para evaluar la primera hipótesis de política local H5.3h, todavía sin producir
acciones:

```powershell
python evaluate_h5_3_local_loss_policy.py `
  "data\generated\h5_3\faster_lap_withholding_audit_v0_1.json" `
  --output "data\generated\h5_3\local_loss_policy_experiment_v0_1.json"

python validate_h5_3_local_loss_policy.py `
  "data\generated\h5_3\local_loss_policy_experiment_v0_1.json"
```

`LOCAL_POLICY_CANDIDATE` significa solamente que el caso merece evidencia
independiente adicional. Su bloque `authorization.authorized` continúa en `false`.

Para distinguir recurrencia de la misma curva de patrones repetidos en curvas
distintas:

```powershell
python audit_h5_3_local_loss_recurrence.py `
  "data\generated\h5_3\local_loss_policy_experiment_v0_1_v5.json" `
  --output "data\generated\h5_3\local_loss_recurrence_audit_v0_1_v5.json"

python validate_h5_3_local_loss_recurrence.py `
  "data\generated\h5_3\local_loss_recurrence_audit_v0_1_v5.json"
```

Solo `EXACT_ZONE_RECURRENCE_OBSERVED` representa repetición independiente de la
misma zona y patrón. `CROSS_ZONE_PATTERN_ONLY` es contexto general y nunca confirma
una curva ni autoriza coaching.

### Mantenimiento automático de la revisión H5.3

La tarea oculta de History ejecuta automáticamente este comando después de un ciclo
exitoso:

```powershell
python maintain_h5_3_action_review.py
```

También puede ejecutarse manualmente. Si no aparecieron artifacts nuevos devuelve
`UP_TO_DATE` y no crea archivos. Si cambió la evidencia, crea la siguiente revisión
numerada, conserva únicamente labels exactos y registra cuántos quedaron pendientes:

```powershell
Get-Content .\data\local\h5_3_review_maintenance.json
```

La automatización prepara la revisión, pero no abre el labeler, no contesta casos,
no llama al LLM y mantiene `historical_actions_authorized=false`.

Después de completar todos los labels, el siguiente ciclo reconstruye automáticamente
los auditores H5.3g/h/i. El estado `AUDITS_CURRENT` incluye sus paths y los conteos de
casos, candidatos y recurrencias. Mientras haya pendientes, informa
`WAITING_FOR_HUMAN_REVIEW` y no ejecuta esa cadena.

La GUI v1.6 muestra este mismo estado junto al contador de sesiones. Verde indica
`UP_TO_DATE`; ámbar muestra la cantidad de casos pendientes; rojo indica un estado
inválido o fallido. Al pulsar el indicador, el detalle o path de labels aparece en
el pie de la ventana. Es una proyección de solo lectura.

GUI v1.7 permite ampliar directamente el mapa GPS con la rueda cuando el cursor está
sobre el circuito. Conserva el punto bajo el cursor, mantiene alineadas todas las
capas y llega hasta `8x`. `Restablecer mapa` vuelve a la vista completa. Esta
interacción es independiente del zoom del gráfico inferior.

GUI v1.8 permite desplazar ese mapa ampliado manteniendo presionado el botón derecho.
El trazado, las zonas, las prioridades y el punto blanco se mueven juntos. El botón
izquierdo continúa reservado para seleccionar el punto de telemetría y el circuito
no puede desplazarse por completo fuera del área visible.

GUI v1.9 identifica la posición del punto blanco mediante el perfil de circuito
validado que coincida exactamente con circuito y layout. Fuera de una zona H5.2
muestra la curva o transición calibrada junto con la distancia. Si no existe ese
perfil, conserva únicamente la distancia y no inventa nombres. Los textos largos del
mapa se ajustan automáticamente en varias filas según el ancho de la ventana.

GUI v1.10 agrega la casilla `Curvas`. Al activarla, el mapa dibuja los intervalos
calibrados, marca cada ápice y muestra el nombre conservado por el perfil validado.
La capa comienza desactivada para mantener legible el mapa y se desplaza/amplía con
él. Las zonas H5.2 y las prioridades permanecen por encima.

GUI v1.11 agrega `Navegación por curva`. Elegir una curva activa su capa, centra y
amplía el intervalo completo en el mapa, coloca el punto blanco en el ápice y enfoca
el gráfico inferior entre la entrada y la salida calibradas. Luego ambos zooms pueden
ajustarse de forma independiente o restablecerse. Los controles usan una fila propia
para conservar la legibilidad en ventanas normales.

El gate H5.3f v0.2 combina el gate estructural anterior con la cola y los labels
reales. Su mejor resultado exige igualmente una decisión explícita y no activa
producción:

```powershell
python assess_h5_3_promotion_v0_2.py `
  "data\generated\h5_3\promotion_manifest.json" `
  "data\generated\h5_3\action_review_queue.json" `
  "data\generated\h5_3\action_review_labels.json" `
  --output "data\generated\h5_3\promotion_report_v0_2.json"
```

### Auditar estructura de cues del plan sin cambiar prioridades

```powershell
python audit_session_plan_actionability.py "RESULTADO_A.json" "RESULTADO_B.json" --output "data\generated\actionability_audits\audit.json"
```

Valida cada resultado y cuenta canal, tipo, puntos físicos y pasos de perfil de los
cues primarios/secundarios. `--allow-stale-render-only` permite auditar artifacts
históricos únicamente cuando su único error es la deriva exacta del render global.
El auditor no crea puntajes ni autoriza preferencia entre freno y acelerador.

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

```text
NO_COMPATIBLE_HISTORICAL_REFERENCE
```

---

## 7. Automatización local de History

La tarea programada recomendada usa directamente la carpeta de LMU:

```powershell
python auto_ingest_telemetry.py `
  --telemetry-dir "C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Telemetry" `
  maintenance --min-size-mb 5 --backfill-minutes 30
```

`maintenance` no hace nada mientras LMU está abierto y espera otros 10 minutos
después de verlo cerrado. Las sesiones nuevas se analizan e importan a History sin
LLM antes de cualquier backfill. Ver
[`AUTOMATIC_TELEMETRY_INGEST_V0_1.md`](AUTOMATIC_TELEMETRY_INGEST_V0_1.md).

Instalar o actualizar la tarea sin consola visible:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_history_ingest_task.ps1
```

La salida se consulta en lugar de una ventana interactiva:

```powershell
Get-Content .\data\local\telemetry_auto_ingest_task.log -Tail 100
```

Reactivar y comprobar la tarea después de una prueba manual:

```powershell
Enable-ScheduledTask -TaskName "RaceEngineer-History-Ingest"

Get-ScheduledTask -TaskName "RaceEngineer-History-Ingest" |
  Select-Object TaskName, State, Actions

Get-ScheduledTaskInfo -TaskName "RaceEngineer-History-Ingest" |
  Select-Object LastRunTime, LastTaskResult, NextRunTime
```

`Ready` significa que está habilitada y esperando su siguiente ejecución. En
`Actions`, `Execute` debe terminar en `pythonw.exe` y los argumentos deben mencionar
`hidden_history_ingest.py`.

## 8. Analizar desde Windows Explorer

Instalar para el usuario actual:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_race_engineer_context_menu.ps1
```

Después, sobre un `.duckdb` autorizado:

```text
Clic derecho -> Analizar con Race Engineer (DeepSeek)
```

Desinstalar:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_race_engineer_context_menu.ps1 -Uninstall
```

El launcher bloquea LMU abierto, History, rutas externas, archivos menores de
5 MiB o recientes. Ejecuta primero Python + History sin LLM y exige dos vueltas
válidas antes de autorizar DeepSeek. Ver
[`RACE_ENGINEER_CONTEXT_MENU.md`](RACE_ENGINEER_CONTEXT_MENU.md).

## 9. Preparar automáticamente colas de calibración

El scheduler lo ejecuta automáticamente, pero puede comprobarse manualmente:

```powershell
python maintain_calibration_queues.py
```

Procesa como máximo un contexto nuevo o modificado, reutiliza batches exactos y
genera solamente la cola para labeling humano. No importa nuevamente History, no
llama un LLM y no genera labels automáticos.

Mientras la cola más reciente del contexto esté pendiente, no se crea otro batch.
Para inspeccionar espacio y evidencia sin eliminar nada:

```powershell
python audit_calibration_batch_retention.py
```
