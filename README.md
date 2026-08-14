# Race Engineer

Proyecto de análisis de telemetría y coaching para **Le Mans Ultimate (LMU)**.

Este README documenta el flujo operativo actual del proyecto: análisis de una sesión, track profiles, historial persistente, calibración cross-session H2, matcher provisional y revisión asistida por DeepSeek.

> Para comandos de uso normal se usan nombres **genéricos sin sufijos de versión** (`llm_analysis.py`, `episode_pair_matcher.py`, etc.). Los archivos versionados se conservan como releases/historial, pero no hace falta escribir la versión en cada comando.

---

## 1. Estado actual del proyecto

Componentes principales:

| Componente | Estado actual |
|---|---|
| `analyze_telemetry.py` | v3.8 — análisis determinista intra-session |
| `llm_analysis.py` / `llm_analysis_deepseek.py` | baseline operativa 3.10.8.5.4 |
| `session_history.py` | v1.3 — History schema 3 |
| `validate_history_db.py` | v1.2 |
| `episode_pair_features.py` | v1.2 — hard context gate con layout |
| `pair_review_queue.py` | schema 1.1 — cola humana estratificada |
| `prepare_calibration_batch.py` | orchestrator 1.4 |
| `episode_pair_matcher.py` | H2 v0.2 — `CALIBRATED_PROVISIONAL_SINGLE_CONTEXT` |
| `audit_episode_pair_matches.py` | v0.2 |
| DeepSeek assisted pair review | H2.2 v1.0 — benchmark en curso |

Checkpoint de calibración H2 actual sobre **Spa + layout Spa + `LMP2_ELMS`**:

```text
candidate pairs: 5506
MATCH:             23
AMBIGUOUS:        699
REJECT:          4784
```

Pool humano actual:

```text
SAME:       13
DIFFERENT:  19
AMBIGUOUS:   8
TOTAL:      40
```

El matcher **todavía no es un matcher general multi-circuito/multi-vehículo**. Los thresholds actuales se consideran calibrados provisionalmente para un único contexto y no deben copiarse automáticamente a otros circuitos/layouts/vehículos.

---

## 2. Principio de arquitectura

La separación de responsabilidades es deliberada:

- **Python** posee los hechos deterministas: vueltas, deltas, eventos, validación, recurrencia intra-session, ubicación de pista, puntos físicos, contexto histórico y reglas del matcher.
- **El LLM** interpreta, prioriza y redacta. No debe recalcular ni inventar hechos de telemetría.
- **Velocidad** es contexto/propagación, nunca un input de conducción ni un target.
- No se permiten inferencias de estabilidad, balance, grip, trayectoria, understeer/oversteer o dinámica vehicular sin evidencia determinista explícita.
- El histórico cross-session permanece separado del coaching operativo hasta estar suficientemente calibrado.

### Variantes de vehículo

No normalizar como equivalentes:

```text
LMP2_ELMS
LMP2
```

`LMP2_ELMS` representa el contexto ELMS sin las mismas restricciones del LMP2 utilizado en WEC. Deben conservarse como contextos históricos separados.

---

## 3. Estructura recomendada

```text
raithreshzz/
├─ telemetria/                      # DuckDB crudos de LMU
├─ track_exports/                   # GPS / GeoJSON / candidatos geométricos
├─ track_profiles/                  # perfiles validados de circuitos
├─ calibration_batches/             # batches H2 reproducibles
├─ analyze_telemetry.py
├─ llm_analysis.py                  # backend local / Ollama
├─ llm_analysis_deepseek.py         # backend DeepSeek
├─ validate_llm_analysis_output.py
├─ extract_lmu_track_gps.py
├─ detect_track_turns.py
├─ track_location.py
├─ session_history.py
├─ validate_history_db.py
├─ episode_pair_features.py
├─ pair_review_queue.py
├─ label_episode_pairs.py
├─ validate_pair_labels.py
├─ build_calibration_dataset.py
├─ calibration_feature_report.py
├─ prepare_calibration_batch.py
├─ episode_pair_matcher.py
├─ validate_episode_pair_matcher.py
├─ audit_episode_pair_matches.py
├─ boundary_review_queue.py
├─ reject_boundary_review_queue.py
├─ prepare_deepseek_pair_benchmark.py
├─ deepseek_pair_reviewer.py
├─ validate_deepseek_pair_reviewer.py
└─ requirements.txt
```

Los DuckDB crudos se guardan en:

```text
telemetria/
```

---

# PARTE A — USO NORMAL DEL ANALIZADOR

## 4. Preparación local en Windows

Desde PowerShell en la raíz del repo:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Checks recomendados:

```powershell
python scripts\check_project.py
python -m compileall -q .
pytest -q
```

---

## 5. Flujo normal de una sesión

### 5.1 Grabar telemetría

Conservar el `.duckdb` original de LMU en:

```text
telemetria/
```

### 5.2 Generar análisis determinista

```powershell
python analyze_telemetry.py "telemetria\ARCHIVO.duckdb"
```

Con validación:

```powershell
python analyze_telemetry.py --validate "telemetria\ARCHIVO.duckdb"
```

El JSON generado por `analyze_telemetry.py` es el contrato determinista consumido por los backends LLM y por el historial.

### 5.3 Ejecutar DeepSeek

Configurar credenciales:

```powershell
$env:DEEPSEEK_API_KEY="TU_API_KEY"
$env:DEEPSEEK_MODEL="deepseek-v4-pro"
```

Ejecutar:

```powershell
python llm_analysis_deepseek.py "ARCHIVO.json"
```

DeepSeek es actualmente el backend preferido para desarrollo y pruebas frecuentes.

### 5.4 Ejecutar el modelo local

El backend local se mantiene para checkpoints de paridad:

```powershell
python llm_analysis.py "ARCHIVO.json"
```

La configuración local habitual usa Ollama y `ingenierov3`.

### 5.5 Validar salida LLM

```powershell
python validate_llm_analysis_output.py "ARCHIVO_LLM_GENERADO.json"
```

Un resultado estable debería terminar en:

```text
REGRESSION VALIDATION: PASS
```

---

## 6. Comportamiento actual del coaching 3.10.8.5.4

### Comparison Quality Gate

Una vuelta extremadamente no representativa puede quedar fuera del agregado de coaching sin ser borrada del JSON.

Cuando el gate decide la exclusión antes de llamar al LLM:

- se conserva el ground truth;
- no participa en recurrencia ni plan A/B/C;
- no se gasta una llamada LLM innecesaria.

### Cues por zona

El debrief intenta mostrar como máximo:

1. `Qué cambiar`;
2. `Segundo cue` si hay otro input suficientemente autorizado.

La prioridad conceptual actual es:

```text
punto físico onset/release autorizado
    > reference_action_profile
        > ajuste cualitativo brake/throttle hacia referencia
            > steering validado
```

Una diferencia unívoca de freno/acelerador puede transformarse en cue cualitativo hacia la referencia sin inventar metros ni porcentajes.

Ejemplo:

```text
más freno que referencia      -> reducí el freno
menos freno que referencia    -> aumentá el freno
más acelerador                -> reducí el acelerador
menos acelerador              -> aumentá el acelerador
```

Una relación temporal medida, por ejemplo:

```text
freno primero y acelerador después; separación aproximada 11 m
```

permanece como **observación** salvo que exista un detector determinista que autorice convertirla en target.

### Reparaciones/fallbacks globales

Una narrativa LLM inválida no debería destruir una sesión cuyo plan determinista es válido.

Las versiones actuales pueden:

- reparar determinísticamente conclusiones globales de steering mal ancladas;
- revalidar la respuesta;
- caer a un global determinista construido desde `next_stint_plan` si la narrativa sigue inválida.

No se relajan los validators para lograrlo.

---

# PARTE B — TRACK PROFILES

## 7. Track location

El mapping de metros LMU a nombres de curva es determinista.

Flujo resumido:

```text
DuckDB
  -> extract_lmu_track_gps.py
  -> *_track_gps.csv / GeoJSON / summary
  -> detect_track_turns.py
  -> candidatos geométricos
  -> asignación humana/verificada de T1..TN
  -> track profile DRAFT
  -> validación con >=2 sesiones del mismo layout
  -> VALIDATED_MULTI_SESSION
  -> track_location.py
```

### Extraer GPS

```powershell
python extract_lmu_track_gps.py "telemetria\ARCHIVO.duckdb" --output-dir track_exports
```

Si la vuelta elegida automáticamente no sirve:

```powershell
python extract_lmu_track_gps.py "telemetria\ARCHIVO.duckdb" --lap N --output-dir track_exports
```

### Detectar candidatos de curva

```powershell
python detect_track_turns.py "track_exports\ARCHIVO_track_gps.csv" --turn-count N --output-dir track_exports
```

`candidate_number` no es un número oficial de curva. El mapeo final requiere verificación humana/geométrica.

### Probar un profile

```powershell
python track_location.py "track_profiles\perfil.json" 1200 1280
```

Sólo perfiles `VALIDATED` o `VALIDATED_MULTI_SESSION` deben activarse automáticamente en el analizador.

Para el procedimiento detallado de construcción de perfiles, consultar `README_GUIA_USUARIO.md`.

---

# PARTE C — H1: HISTORIAL PERSISTENTE

## 8. History DB

El historial usa una DuckDB separada de los DuckDB crudos de LMU:

```text
race_engineer_history.duckdb
```

Estado actual:

```text
session_history v1.3
schema version 3
```

Schema 3 agrega contexto explícito de:

```text
lmu_track_layout
```

### Inicializar o migrar

```bash
python session_history.py init
```

Si la DB estaba en schema 2, `init` realiza la migración a schema 3 sin borrar los datos históricos.

### Importar un JSON

```bash
python session_history.py import "ARCHIVO.json"
```

### Importar una carpeta

```bash
python session_history.py import-dir . --recursive
```

El import por SHA es idempotente. Si una sesión legacy ya estaba importada pero tenía contexto NULL, un reimport puede completar el contexto faltante sin duplicar laps/comparaciones/episodios.

### Consultar

```bash
python session_history.py list
python session_history.py stats
python session_history.py inspect SESSION_ID
```

### Validar la DB

```bash
python validate_history_db.py
```

Una sesión legacy sin layout puede conservarse para auditoría, pero queda fuera del pairing H2.

---

# PARTE D — H2: CALIBRACIÓN CROSS-SESSION

## 9. Hard context gate

Antes de comparar dos episodios de sesiones distintas, H2 exige:

1. sesiones distintas;
2. mismo `track`;
3. layout conocido en ambas;
4. mismo `lmu_track_layout`;
5. mismo `vehicle_variant`;
6. dominio de vehículo soportado;
7. comparación fuente elegible para análisis del piloto.

La identidad del batch es:

```text
track + layout + vehicle_variant
```

Esto evita mezclar layouts o variantes que no son equivalentes.

---

## 10. Generar features de pares manualmente

Si se quiere trabajar sin orchestrator:

```bash
python episode_pair_features.py \
  --track "Circuit de Spa-Francorchamps" \
  --track-layout "Circuit de Spa-Francorchamps" \
  --vehicle-variant LMP2_ELMS \
  --output episode_pair_features.json
```

La salida contiene features neutrales. No decide `MATCH`, `SAME`, `DIFFERENT` ni `AMBIGUOUS`.

Entre las features importantes se encuentran:

- distancia entre centros;
- overlap sobre union;
- overlap sobre episodio más corto;
- Jaccard de canales;
- canales compartidos/exclusivos;
- similitud de shape por canal;
- offsets onset/end por canal;
- similitud de action-time-loss como evidencia secundaria.

---

## 11. Flujo recomendado: `prepare_calibration_batch.py`

Para calibración real conviene usar el orchestrator en lugar de ejecutar cada herramienta a mano.

Ejemplo desde Codespaces/Linux:

```bash
python prepare_calibration_batch.py . \
  --recursive \
  --track "Circuit de Spa-Francorchamps" \
  --track-layout "Circuit de Spa-Francorchamps" \
  --vehicle-variant LMP2_ELMS
```

El batch se guarda bajo:

```text
calibration_batches/<track-layout-vehicle-hash>/
```

Un batch puede contener:

```text
BATCH_STATUS.json
episode_pair_features.json
pair_review_queue.json
pair_labels.json
calibration_dataset.json
calibration_feature_report.json
episode_pair_matches.json
...colas/labels adicionales de boundary review
```

### Reutilización

El orchestrator intenta reutilizar artefactos compatibles (`REUSED`) y regenerar los que no coinciden con el contrato actual.

La cola humana se considera incompatible y debe regenerarse si cambian, entre otros:

- schema de cola;
- hash de features fuente;
- `per_lens`;
- máximo total;
- seed.

### Usar sólo una History DB ya importada

```bash
python prepare_calibration_batch.py . \
  --skip-import \
  --track "Circuit de Spa-Francorchamps" \
  --track-layout "Circuit de Spa-Francorchamps" \
  --vehicle-variant LMP2_ELMS
```

---

## 12. Cola de revisión humana inicial

`pair_review_queue.py` no clasifica pares. Sólo crea una muestra diversa para revisión.

Política actual por defecto:

```text
per_lens: 6
max_review_pairs: 24
selection: round_robin_stratified
7 lentes de selección
```

Ejemplo manual:

```bash
python pair_review_queue.py episode_pair_features.json \
  --output pair_review_queue.json \
  --per-lens 6 \
  --max-total 24
```

---

## 13. Etiquetado humano

### Semántica

```text
SAME
```

Misma ubicación/región general y mismo tipo general de diferencia de conducción. No implica muestras idénticas ni causalidad idéntica.

```text
DIFFERENT
```

La evidencia apoya que son regiones o patrones materialmente distintos.

```text
AMBIGUOUS
```

No hay evidencia suficiente para decidir de forma segura.

```text
SKIP
```

Caso no adjudicado; no debe contarse como etiqueta útil para calibración.

### Ejecutar review interactivo

```bash
python label_episode_pairs.py pair_review_queue.json \
  --labels pair_labels.json
```

Controles:

```text
s = SAME
d = DIFFERENT
a = AMBIGUOUS
k = SKIP
q = guardar y salir
```

El programa guarda después de cada decisión.

### Mostrar resumen

```bash
python label_episode_pairs.py pair_review_queue.json \
  --labels pair_labels.json \
  --summary
```

### Validar labels

```bash
python validate_pair_labels.py pair_review_queue.json pair_labels.json
```

El validator comprueba, entre otras cosas:

- `pair_id` válido y único;
- pertenencia a la cola fuente;
- hash de la cola;
- snapshot de features;
- contexto cross-session;
- labels permitidos.

---

## 14. Calibration dataset y anti-leakage

`build_calibration_dataset.py` hace split por **sesión**, no por par, para evitar leakage entre calibración y evaluación.

Esto es correcto para evaluación final, pero con pocos sessions puede dejar muy pocos pares dentro de cada split.

Regla práctica actual:

- **no eliminar el split anti-leakage** para conseguir métricas más lindas;
- si el split es demasiado pequeño, usar el pool humano completo sólo para exploración/calibración provisional;
- no presentar esas métricas como evaluación independiente.

---

## 15. Boundary review

Cuando la cola inicial sólo cubre extremos, se usan colas pequeñas y dirigidas para aprender la frontera.

### Hard cases cercanos

```bash
python boundary_review_queue.py \
  episode_pair_features.json \
  pair_labels.json \
  --output boundary_review_queue.json
```

Etiquetar:

```bash
python label_episode_pairs.py boundary_review_queue.json \
  --labels boundary_pair_labels.json
```

### Frontera de REJECT

Para estudiar casos entre 45 y 623.5 m sin repetir labels existentes:

```bash
python reject_boundary_review_queue.py \
  episode_pair_features.json \
  --labels pair_labels.json boundary_pair_labels.json \
  --output reject_boundary_review_queue.json
```

Etiquetar:

```bash
python label_episode_pairs.py reject_boundary_review_queue.json \
  --labels reject_boundary_pair_labels.json
```

Estas herramientas **seleccionan casos para revisión**. Sus bandas/distancias no son automáticamente thresholds del matcher.

---

# PARTE E — MATCHER H2 v0.2

## 16. Estado y filosofía

El matcher actual es deliberadamente conservador:

```text
MATCH / AMBIGUOUS / REJECT
```

No intenta forzar una decisión para todos los pares.

Status:

```text
CALIBRATED_PROVISIONAL_SINGLE_CONTEXT
```

Contexto calibrado actualmente:

```text
Circuit de Spa-Francorchamps
layout: Circuit de Spa-Francorchamps
vehicle_variant: LMP2_ELMS
human labels: 40
```

---

## 17. Reglas provisionales actuales

### Núcleo de MATCH

Un par puede entrar automáticamente en el núcleo de `MATCH` si cumple:

```text
center_distance_abs_diff_m <= 5.5
overlap_over_shorter >= 0.98
overlap_over_union >= 0.33
shared_channels >= 1
```

Además existe un veto de weak-shape conflict que puede mantener el caso como `AMBIGUOUS`.

### Núcleo de REJECT

Después de la calibración humana de la frontera:

```text
center_distance_abs_diff_m > 250.0
overlap_over_union == 0
```

puede clasificarse automáticamente como `REJECT`.

### Todo lo demás

Permanece:

```text
AMBIGUOUS
```

No generalizar estos valores a otro contexto sin labels nuevos.

---

## 18. Ejecutar matcher

```bash
python episode_pair_matcher.py \
  calibration_batches/BATCH/episode_pair_features.json \
  --output calibration_batches/BATCH/episode_pair_matches.json
```

Checkpoint Spa actual:

```text
Pairs:      5506
MATCH:        23
AMBIGUOUS:   699
REJECT:     4784
```

---

## 19. Validar matcher contra labels humanos

```bash
python validate_episode_pair_matcher.py \
  episode_pair_matcher.py \
  calibration_batches/BATCH/pair_labels.json \
  calibration_batches/BATCH/boundary_pair_labels.json \
  calibration_batches/BATCH/reject_boundary_pair_labels.json
```

Lo más importante es preservar:

```text
SAME -> REJECT: 0
DIFFERENT -> MATCH: 0
```

Los `AMBIGUOUS` humanos no deben ser forzados automáticamente por una regla sin evidencia.

---

## 20. Auditar las 5506 decisiones

```bash
python audit_episode_pair_matches.py \
  calibration_batches/BATCH/episode_pair_features.json \
  calibration_batches/BATCH/episode_pair_matches.json
```

Para listar también todos los matches:

```bash
python audit_episode_pair_matches.py \
  calibration_batches/BATCH/episode_pair_features.json \
  calibration_batches/BATCH/episode_pair_matches.json \
  --show-matches
```

El auditor muestra:

- distribución MATCH/AMBIGUOUS/REJECT;
- reglas que tomaron la decisión;
- bins de distancia;
- estadísticas de overlap;
- ambiguos más cercanos;
- lista de MATCH si se solicita.

### Check obligatorio del join

La salida correcta de auditor v0.2 debe incluir:

```text
FEATURE JOIN: resolved=<TOTAL> missing=0
```

Si todos los pares aparecen como `missing`, `None` o `inf`, verificar la versión del auditor antes de recalcular el matcher.

---

## 21. `pair_id` y compatibilidad de outputs viejos

El archivo raw `episode_pair_features.json` históricamente no traía `pair_id`.

`pair_review_queue.py` generaba después un `stable_pair_id`.

El matcher actual también emite ese ID estable.

`audit_episode_pair_matches.py` v0.2 puede resolver outputs viejos usando `pair_index` cuando el matcher anterior dejó `pair_id = null`.

Por eso, ante un audit roto, **no regenerar automáticamente 5506 pares**: primero comprobar si el problema es sólo de join/schema del auditor.

---

# PARTE F — H2.2: DEEPSEEK COMO PRE-REVISOR

## 22. Objetivo

DeepSeek se usa como **preseleccionador / pre-etiquetador**, nunca como sustituto automático del ground truth humano.

Flujo:

```text
40 labels humanos
    -> benchmark ciego de DeepSeek
    -> medir acuerdo y errores peligrosos
    -> si es aceptable
       -> pre-review del pool AMBIGUOUS
       -> humano revisa conflictos/dudosos/muestras de control
       -> pool humano ampliado
       -> recalibración posterior del matcher
```

La procedencia debe mantenerse separada:

```text
human_label
deepseek_label
deepseek_confidence
matcher_decision
```

---

## 23. Preparar benchmark ciego

El benchmark elimina antes de la inferencia:

- `human_label`;
- notas humanas;
- lens de selección;
- decisión/regla del matcher;
- thresholds del matcher.

Ejecutar:

```bash
python prepare_deepseek_pair_benchmark.py \
  calibration_batches/BATCH/pair_labels.json \
  calibration_batches/BATCH/boundary_pair_labels.json \
  calibration_batches/BATCH/reject_boundary_pair_labels.json \
  --output calibration_batches/BATCH/deepseek_pair_benchmark_queue.json
```

Con el pool actual debería resultar en 40 pares ciegos.

---

## 24. Configurar DeepSeek en Codespaces/Linux

```bash
export DEEPSEEK_API_KEY="TU_API_KEY"
export DEEPSEEK_MODEL="deepseek-v4-pro"
```

Opcionalmente:

```bash
export DEEPSEEK_API_URL="https://api.deepseek.com/chat/completions"
```

En Codespaces es preferible almacenar la API key como secret y exportarla al entorno, no commitearla.

---

## 25. Dry run del reviewer

Antes de gastar API:

```bash
python deepseek_pair_reviewer.py \
  calibration_batches/BATCH/deepseek_pair_benchmark_queue.json \
  --output calibration_batches/BATCH/deepseek_pair_benchmark_reviews.json \
  --dry-run
```

El dry run comprueba queue/model/features y no envía requests.

---

## 26. Ejecutar review real

```bash
python deepseek_pair_reviewer.py \
  calibration_batches/BATCH/deepseek_pair_benchmark_queue.json \
  --output calibration_batches/BATCH/deepseek_pair_benchmark_reviews.json
```

Cada par se procesa en una request aislada.

La respuesta estructurada incluye:

```text
label: SAME / DIFFERENT / AMBIGUOUS
confidence: HIGH / MEDIUM / LOW
reason_codes
decisive_evidence
reason
```

### Ejecución resumible

El archivo de salida se guarda después de cada par.

Si la ejecución se corta, correr **el mismo comando**. Los reviews `VALID` existentes se reutilizan.

Si se cambia la queue fuente, el reviewer impide reutilizar un output incompatible salvo `--overwrite` o un nuevo path.

### Herramientas útiles

Limitar cantidad:

```bash
python deepseek_pair_reviewer.py QUEUE.json --output REVIEWS.json --limit 5
```

Ejecutar un único par:

```bash
python deepseek_pair_reviewer.py QUEUE.json \
  --output REVIEWS.json \
  --only-pair-id PAIR_ID
```

Sobrescribir output:

```bash
python deepseek_pair_reviewer.py QUEUE.json \
  --output REVIEWS.json \
  --overwrite
```

El reviewer también reporta requests, tokens, cache hit/miss y costo estimado cuando conoce el pricing del modelo configurado.

---

## 27. Validar DeepSeek contra humanos

Sólo después de terminar la inferencia ciega:

```bash
python validate_deepseek_pair_reviewer.py \
  calibration_batches/BATCH/deepseek_pair_benchmark_reviews.json \
  calibration_batches/BATCH/pair_labels.json \
  calibration_batches/BATCH/boundary_pair_labels.json \
  calibration_batches/BATCH/reject_boundary_pair_labels.json \
  --json-output calibration_batches/BATCH/deepseek_pair_benchmark_validation.json
```

El validator reporta:

- matriz de confusión;
- exact agreement;
- HIGH-confidence coverage;
- HIGH-confidence exact agreement;
- flips directos `SAME <-> DIFFERENT`;
- lista completa de mismatches.

### Safety gate H2.2

No se impuso un porcentaje arbitrario de agreement.

El gate de seguridad exige:

```text
todos los 40 pares humanos evaluados y válidos
0 HIGH-confidence SAME <-> DIFFERENT direct flips
```

Después se evalúan agreement y cobertura como métricas de **utilidad**, no como sustituto del juicio humano.

### Siguiente etapa

Si el benchmark es aceptable, DeepSeek podrá pre-revisar el pool actual de 699 `AMBIGUOUS` para priorizar revisión humana.

Política prevista:

```text
HIGH SAME / HIGH DIFFERENT
    -> candidatos fuertes; auditar por muestreo humano
MEDIUM
    -> prioridad de revisión humana
LOW / AMBIGUOUS
    -> revisión humana o mantener sin resolver
```

La expansión automática a los 699 no debe ejecutarse antes de aprobar el benchmark ciego.

---

# PARTE G — CODESPACES

## 28. Uso de GitHub Codespaces

El repo puede usarse para:

- History DB;
- calibración H2;
- pair features;
- revisión humana;
- matcher/auditor;
- DeepSeek API;
- tests y desarrollo Python.

DeepSeek permite trabajar sin cargar la GPU local mientras LMU está abierto.

Para comandos H2 en Codespaces usar paths Linux:

```text
/
```

en lugar de `\`.

Ejemplo:

```bash
cd /workspaces/raithreshzz
```

---

# PARTE H — TROUBLESHOOTING

## 29. El script dice una versión vieja

Antes de interpretar un resultado extraño:

```bash
grep -n "VERSION" script.py | head
```

Para el auditor, por ejemplo:

```bash
grep -n "AUDIT_VERSION" audit_episode_pair_matches.py
```

Si se esperaba v0.2 y aparece v0.1, reemplazar primero el archivo genérico. No recalcular datos todavía.

---

## 30. Cola vieja de 98 pares

Una queue schema 1.0 podía conservar una cola grande anterior.

La política actual usa schema 1.1 y máximo inicial de 24 pares.

Si `BATCH_STATUS.json` muestra queue incompatible o schema viejo, regenerar la cola con el script actual/orchestrator actual.

---

## 31. `lmu_track_layout` no existe

Error típico de una History DB vieja:

```text
Referenced column "lmu_track_layout" not found
```

Solución:

```bash
python session_history.py init
```

Después reimportar los JSON para enriquecer contexto legacy:

```bash
python session_history.py import-dir . --recursive
python validate_history_db.py
```

---

## 32. `FEATURE JOIN: missing`

Si auditor muestra todos los centers como `inf` o features `None`:

1. comprobar que se está ejecutando auditor v0.2;
2. comprobar `FEATURE JOIN`;
3. no asumir que el matcher falló;
4. no regenerar features/matches hasta descartar incompatibilidad de join.

---

## 33. DeepSeek reviewer se interrumpe

Volver a ejecutar exactamente el mismo comando.

Los pares ya guardados con `status=VALID` aparecen como:

```text
REUSED
```

No usar `--overwrite` salvo que realmente se quiera descartar el review anterior.

---

## 34. No relajar validators para hacer pasar una prueba

Orden preferido:

```text
hecho determinista
    -> representación estructurada
        -> validación
            -> interpretación LLM
                -> render
```

Si una salida falla:

1. determinar si el hecho determinista está mal;
2. revisar schema/representación;
3. revisar renderer/prompt/repair;
4. recién después considerar cambiar una regla;
5. nunca debilitar el validator sólo para silenciar un error.

---

# PARTE I — HISTORIAL ACTUAL Y LÍMITES

## 35. Persistent patterns / historical reference

El roadmap histórico continúa:

```text
H1 persistence/history
H2 calibrated matcher
H2.2 assisted calibration/review
H3 persistent pattern types
H4 historical benchmark selector
H5.1 dual reference
H5.2 raw cross-session comparison     <- disponible en modo observacional
```

Todavía no crear `persistent_pattern` automáticamente sólo porque dos episodios fueron `MATCH`.

H4 selecciona una `historical_reference` compatible y H5.1 conserva separadas la referencia de la sesión y la histórica.

H5.2 v0.1 compara ambas vueltas desde sus DuckDB raw cuando están disponibles. La comparación es determinista, valida el delta temporal y produce zonas espaciales observacionales. Si falta cualquiera de los dos DuckDB, la etapa queda `SKIPPED_NOT_APPLICABLE`.

Todavía no usar esas zonas históricas como instrucciones de coaching del LLM: en v0.1 `session_reference` sigue siendo la autoridad y `historical_actions_authorized=false` hasta definir un contrato específico de prompt, output y validator.

---

# 36. Checklist rápido — sesión normal

```text
[ ] DuckDB en telemetria/
[ ] analyze_telemetry.py
[ ] validación temporal/objetiva OK
[ ] llm_analysis_deepseek.py o llm_analysis.py
[ ] revisar debrief A/B/C
[ ] validate_llm_analysis_output.py
[ ] conservar JSON determinista para History
[ ] H4/H5.1 si existe referencia histórica compatible
[ ] H5.2 si ambos DuckDB raw están disponibles
```

---

# 37. Checklist rápido — H2

```text
[ ] History schema 4
[ ] layout explícito
[ ] vehicle_variant correcto
[ ] validate_history_db.py PASS
[ ] generar calibration batch
[ ] revisar BATCH_STATUS.json
[ ] etiquetar queue inicial
[ ] validar labels
[ ] generar hard-case queues sólo si hacen falta
[ ] validar matcher contra labels humanos
[ ] ejecutar matcher completo
[ ] auditar FEATURE JOIN missing=0
[ ] inspeccionar distribución MATCH/AMBIGUOUS/REJECT
[ ] benchmark ciego DeepSeek antes de usar pseudo-labels
[ ] mantener provenance humano/LLM/matcher separada
```

---

# 38. Convenciones de desarrollo

- Scripts de uso normal: nombres genéricos sin versión.
- Releases/artifacts: pueden conservar versión explícita.
- `telemetria/`: ubicación estándar de DuckDB LMU.
- DeepSeek: backend principal de iteración mientras se mantiene LMU abierto.
- Ollama/ingenierov3: checkpoints de paridad local.
- Python conserva la autoridad sobre hechos y reglas deterministas.
- El LLM no re-detecta zonas, no suma eventos y no inventa targets.
- El matcher H2 debe preferir `AMBIGUOUS` a una decisión no respaldada.
- Labels humanos siguen siendo el ground truth fuerte.
- Pseudo-labels DeepSeek nunca deben mezclarse silenciosamente con labels humanos.

---

## Documentación relacionada

- `README_GUIA_USUARIO.md` — guía detallada de track profiles; para versiones, H2 y flujo operativo actual prevalece este `README.md`.
- `PROJECT_STATUS.md` — estado general del proyecto.
- `H2_LAYOUT_CONTEXT_GATE_v1_0.md` — contrato de contexto H2.
- `H2_MATCHER_V0_2_NOTES.md` — matcher provisional v0.2.
- `H2_2_DEEPSEEK_ASSISTED_REVIEW_v1_0.md` — revisión asistida por DeepSeek.
- `HISTORICAL_REFERENCE_ROADMAP_v1_0.md` — roadmap de historial/referencia futura.

