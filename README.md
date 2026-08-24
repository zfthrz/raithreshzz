# Race Engineer

Proyecto de análisis de telemetría y coaching para **Le Mans Ultimate (LMU)**.

Este README documenta el flujo operativo actual del proyecto: análisis de una sesión, track profiles, historial persistente, calibración cross-session H2, matcher provisional y revisión asistida por DeepSeek.

> Para comandos de uso normal se usan nombres **genéricos sin sufijos de versión** (`llm_analysis.py`, `episode_pair_matcher.py`, etc.). Los archivos versionados se conservan como releases/historial, pero no hace falta escribir la versión en cada comando.

> Guía práctica del orquestador: [`docs/RACE_ENGINEER_COMMAND_GUIDE.md`](docs/RACE_ENGINEER_COMMAND_GUIDE.md).

> Automatización de History: [`docs/AUTOMATIC_TELEMETRY_INGEST_V0_1.md`](docs/AUTOMATIC_TELEMETRY_INGEST_V0_1.md). Menú contextual seguro: [`docs/RACE_ENGINEER_CONTEXT_MENU.md`](docs/RACE_ENGINEER_CONTEXT_MENU.md).

> Interfaz de escritorio: [`docs/RACE_ENGINEER_GUI_V1_14.md`](docs/RACE_ENGINEER_GUI_V1_14.md).

> Traspaso para continuar en ChatGPT actualizado al 23/08/2026: [`docs/CHATGPT_HANDOFF_2026_08_23.md`](docs/CHATGPT_HANDOFF_2026_08_23.md).

---

## 1. Estado actual del proyecto

Componentes principales:

| Componente | Estado actual |
|---|---|
| `analyze_telemetry.py` | v3.8 — análisis determinista intra-session |
| `llm_analysis.py` / `llm_analysis_deepseek.py` | baseline operativa 3.10.8.5.4 |
| `llm_analysis_llamacpp.py` | 3.10.8.5.4 — backend local llama.cpp (OpenAI-compatible), default `qwen3-14b` |
| `session_history.py` | v1.4 — History schema 4 |
| `validate_history_db.py` | v1.3 |
| `episode_pair_features.py` | v1.2 — hard context gate con layout |
| `pair_review_queue.py` | schema 1.1 — cola humana estratificada |
| `prepare_calibration_batch.py` | orchestrator 1.5 |
| `episode_pair_matcher.py` | H2 v0.3 — `CALIBRATED_PROVISIONAL_SINGLE_CONTEXT` |
| `audit_episode_pair_matches.py` | v0.2 |
| DeepSeek assisted pair review | H2.2 v1.0 — benchmark en curso |
| `auto_ingest_telemetry.py` | v0.1 — ingest directo desde LMU, History prioritario y backfill gradual |
| `analyze_telemetry_file.py` | v0.2 — launcher seguro con override explícito sólo para la espera de estabilidad |
| `hidden_history_ingest.py` | runner sin consola con log local rotativo para la tarea programada |
| H5.3a-f + runtime 0.2 | shadow: candidatos, auditoría, selección unificada y render validado |
| `race_engineer_gui.py` | v1.14 — hub de sesiones con panel de estado de calibración H2 |

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
├─ telemetria/                      # copia local opcional; automatización lee UserData/Telemetry
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

Para evaluar el Qwen3.8 27B local sin reemplazar `ingenierov3`:

```powershell
python llm_analysis_qwen3_8_27b_iq3m.py "ARCHIVO.json"
```

Resultados y recomendación: [`docs/LLM_BACKEND_BENCHMARK_MONZA_V0_1.md`](docs/LLM_BACKEND_BENCHMARK_MONZA_V0_1.md).

#### LLM episode prompt shadow gate

`run_llm_prompt_shadow.py` ejecuta experimentos opt-in bajo
`data/generated/llm_prompt_shadow/` sin reemplazar producción. El gate acepta
como evidencia de prompt solamente pares con la misma fuente determinista,
backend y modelo:

```powershell
python assess_llm_prompt_shadow_promotion.py `
  "data\generated\llm_results\SESSION\PRODUCTION.json" `
  "data\generated\llm_prompt_shadow\episode-grounding-shadow-v0.1" `
  --output "data\generated\diagnostics\llm_prompt_shadow_promotion_v0_1.json"
```

Estado actual: `PROMOTION_BLOCKED_INSUFFICIENT_PAIRED_EVIDENCE`. El par exacto
de Imola está empatado en 4/43 reparaciones; Monza y Fuji cambian también de
modelo y permanecen como observaciones no pareadas. Ver
[`docs/LLM_PROMPT_SHADOW_PROMOTION_GATE_V0_1.md`](docs/LLM_PROMPT_SHADOW_PROMOTION_GATE_V0_1.md).

### Backend local vía llama.cpp

Si querés usar otro LLM local servido por llama.cpp (API compatible con OpenAI),
por ejemplo Qwen 3 14B, configurá el endpoint y el nombre del modelo:

```powershell
$env:LLAMACPP_API_URL = "http://localhost:8080/v1/chat/completions"
$env:LLAMACPP_MODEL = "qwen3-14b"

python race_engineer.py analyze "telemetria\ARCHIVO.duckdb" --backend llamacpp
```

Los valores por defecto ya apuntan a `http://localhost:8080/v1/chat/completions`
con el modelo `qwen3-14b`; solo hace falta tener el server de llama.cpp
levantado. El mismo backend se puede usar para la narrativa histórica H5.2 y la
selección de candidatos H5.3c pasando `--backend llamacpp`.

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

Desde la política de actionability `1.7`, un punto físico de acelerador no se mezcla
con toda la secuencia de referencia en una sola frase. El punto queda como
`Qué cambiar` y la secuencia pasa a `Segundo cue` cuando hay espacio. En zonas mixtas,
el límite de dos cues sigue respetándose y la forma completa permanece visible en la
sección descriptiva de referencia. Esto mejora la lectura sin cambiar el ranking ni
favorecer freno o acelerador por nombre de canal.

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

Un resultado ya existente puede rerenderizarse sin repetir la llamada LLM:

```powershell
python rerender_llm_analysis_output.py "data\generated\llm_results\SESSION\RESULTADO.json" --output "data\generated\rerender_tests\preview.json"
```

La utilidad recalcula solamente `driver_cues`, los campos globales deterministas y el
render final; después ejecuta el validator completo. Nunca sobrescribe el archivo
fuente por defecto y registra `llm_called=false`. Es una herramienta de migración y
validación de presentación, no una forma de alterar evidencia objetiva.

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

### Circuit de la Sarthe

`track_profiles/la_sarthe_profile_v0_1.json` está validado sobre cinco vueltas
completas de tres sesiones LMU independientes del layout exacto
`Circuit de la Sarthe`. Usa una secuencia local de 19 segmentos: los nombres ACO
son autoritativos y sus números no deben presentarse como la numeración FIA oficial
de 33 curvas. Los complejos largos se localizan por intervalos, no por un único
máximo de curvatura. Evidencia y fuentes:
`docs/LA_SARTHE_TRACK_PROFILE_V0_1.md`.

---

# PARTE C — H1: HISTORIAL PERSISTENTE

## 8. History DB

El historial usa una DuckDB separada de los DuckDB crudos de LMU:

```text
race_engineer_history.duckdb
```

Estado actual:

```text
session_history v1.4
schema version 4
```

Schema 3 agregó contexto explícito de:

```text
lmu_track_layout
```

### Inicializar o migrar

```bash
python session_history.py init
```

Schema 4 agrega la persistencia derivada y versionada de H3 sin modificar los
episodios fuente. `init` migra de schema 2 o 3 a schema 4 sin borrar los datos
históricos.

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

# PARTE E — MATCHER H2 v0.3

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

Los umbrales exactos se leen de `episode_pair_matcher.py` v0.3 y siguen siendo
provisionales para el contexto Spa calibrado; no copiarlos a otros circuitos o
vehículos sin evidencia nueva.

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
H5.2 LLM historical narrative         <- observacional y validada
H5.3 historical coaching debrief       <- roadmap productivo; H5.3a-f implementadas en shadow
```

Todavía no crear `persistent_pattern` automáticamente sólo porque dos episodios fueron `MATCH`.

El primer batch H2 de Monza Hypercar tiene 24 pares revisados por una persona
(`9 SAME`, `13 DIFFERENT`, `2 AMBIGUOUS`). El split por sesión dejó 13 pares de
calibración y ningún par interno de evaluación, por lo que el resultado se conserva
como evidencia inicial `READY_FOR_MORE_REAL_DATA`; no habilita todavía un matcher
Monza ni H3. Detalles: `docs/H2_MONZA_HYPER_CALIBRATION_V0_1.md`.

El batch independiente de Monza `LMP2_ELMS` reúne 3 sesiones del IDEC Sport #18 y
24 pares revisados (`11 SAME`, `12 DIFFERENT`, `1 AMBIGUOUS`). El split conserva
5 pares de calibración, excluye 19 pares cross-partition y tampoco obtiene pares
internos de evaluación. Su estado es `READY_FOR_MORE_REAL_DATA` y no habilita
matcher ni H3. Detalles: `docs/H2_MONZA_LMP2_ELMS_CALIBRATION_V0_1.md`.

H4 selecciona una `historical_reference` compatible y H5.1 conserva separadas la referencia de la sesión y la histórica.

H5.2 v0.2 compara ambas vueltas desde sus DuckDB raw cuando están disponibles. La comparación es determinista, valida el delta temporal y conserva las tendencias amplias para auditoría. Con un track profile validado exacto, divide esas tendencias en zonas localizadas por límites del perfil antes de exponerlas al LLM. Si no existe un perfil exacto, declara un fallback no localizado; si falta cualquiera de los dos DuckDB, la etapa queda `SKIPPED_NOT_APPLICABLE`.

El contrato LLM histórico v0.1 puede seleccionar hasta tres zonas H5.2 y únicamente códigos observacionales autorizados por Python para cada una. El LLM no escribe texto libre: Python arma todo el render final con hechos y cifras exactos. Un validator separado rechaza zonas inventadas, claves adicionales, códigos no autorizados o evidencia alterada.

La selección puede auditarse sin llamar nuevamente al modelo:

```powershell
python audit_h5_2_zone_selection.py "data\generated\h5_2\SESSION\cross_session_comparison.json" "data\generated\h5_2_llm\SESSION\RESULTADO_1.json" "data\generated\h5_2_llm\SESSION\RESULTADO_2.json" --output "data\generated\h5_2_audits\selection_audit.json"
```

El auditor compara impacto absoluto, intensidad por 100 m y especificidad de curva,
pero funciona exclusivamente en modo shadow. No decide que un modelo sea correcto,
no cambia la selección productiva y no autoriza coaching. Las pruebas Monza/Imola
mostraron que impacto e intensidad pueden divergir, por lo que todavía no existe una
fórmula determinista de relevancia promovida.

El checkpoint multitrack real cubre Fuji, Imola, Interlagos y Monza. En los cuatro casos pasaron tanto el validator raw como el validator de narrativa histórica. El conjunto incluye vueltas actuales más lentas (`+1.280 s`, `+0.600 s`) y más rápidas (`-0.180 s`, `-1.120 s`) que la referencia histórica, sin cambiar la autoridad de coaching. Monza también confirmó que H4 rechaza mezclar Hypercar con LMP2_ELMS. Los detalles están en `docs/H5_2_MULTITRACK_VALIDATION_V0_1.md`.

Las zonas históricas siguen sin autorizar instrucciones de coaching: `session_reference` continúa como autoridad y `historical_actions_authorized=false`.

El objetivo histórico H5.3 (debrief separado contra la mejor vuelta histórica
compatible) se está desarrollando por etapas. H5.3a (candidatos deterministas en
shadow), H5.3b (dataset de auditoría + revisión humana) y H5.3c (selección LLM
controlada) están implementadas con evidencia real Imola/Monza y siguen sin
autorizar acciones. H5.3d (render determinista separado), H5.3e (validator +
fallback seguro) y H5.3f (gate multitrack de promoción) también están implementadas.
El gate real devuelve `PROMOTION_READY` con los 4 circuitos y ambos signos de delta;
la producción histórica sigue sin autorizar (`historical_actions_authorized=false`).
El orquestador integra una etapa `h5_3` observacional (candidatos + sección
determinista + validator) que queda `SKIPPED_NOT_APPLICABLE` si faltan prerequisitos.
Nivel 2: `historical_action_policy.py` construye candidatos de acción cerrados de
freno/acelerador solamente para comparaciones seleccionadas de vueltas actuales más
lentas; la velocidad y el tiempo nunca se convierten en acciones, las vueltas más
rápidas quedan retenidas y `historical_actions_authorized` permanece en `false`.
La elegibilidad runtime v0.2 conserva el signo global de la comparación separado de
los deltas locales de zona, de modo que una vuelta globalmente `current_faster` queda
retenida aunque contenga zonas locales con pérdida.
El pipeline runtime adicional usa selección determinista por defecto y no llama a
ningún modelo salvo que `H5_3_BACKEND` se configure explícitamente como `deepseek`,
`ollama` o `llamacpp`. Sus artefactos reutilizables quedan bajo
`data/generated/h5_3_shadow/<session>/` y no modifican el debrief visible.
Una auditoría shadow (`audit_historical_actions_actionability.py`) clasifica las
acciones en freno/acelerador/mixtas sin promover ninguna preferencia de canal.
H5.3g reconstruye además los casos `current_faster + WITHHELD` desde fuentes con
hash. La primera ejecución real encontró seis casos: uno correctamente retenido,
uno retenido pero accionable y cuatro ambiguos. Es evidencia para diseñar una futura
política local en shadow; no elimina la protección global ni habilita coaching.
H5.3h prueba esa política local como una hipótesis separada y conservadora: exige
label `WITHHELD_BUT_ACTIONABLE`, pérdida local mínima de `0,20 s` y evidencia de
ambos controles. El resultado inicial conserva un único candidato no autorizado y
retiene los otros cinco; todavía no genera instrucciones para el piloto.
Con dos sesiones nuevas de Interlagos, la cola v5 quedó completa en 23/23 y H5.3h
pasó a tres candidatos no autorizados. H5.3i separa recurrencia exacta por curva de
patrones entre curvas: el resultado inicial es 0 recurrencias exactas y 1 patrón
contextual compartido por T8 y T12. Ese patrón no confirma ninguna curva ni autoriza
una instrucción.
La preparación de nuevas revisiones queda automatizada por
`maintain_h5_3_action_review.py`: detecta nuevos artifacts shadow, crea una revisión
numerada solo si cambió la cola y migra exclusivamente labels idénticos. El ejecutor
oculto de History lo invoca sin consola; nunca llama al LLM ni responde la revisión.
Cuando no quedan labels pendientes también reconstruye y valida automáticamente los
auditores H5.3g/h/i. Si falta una decisión humana, la cadena se detiene de forma
segura en `WAITING_FOR_HUMAN_REVIEW`.
Contrato:
[`docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md`](docs/H5_3_HISTORICAL_COACHING_ROADMAP_V0_1.md).

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
[ ] narrativa histórica H5.2 validada si el LLM está habilitado
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
