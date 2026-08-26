# D3 — LLM Runtime Dependency Audit v0.2

**Estado:** AUDIT ORIGINAL (v0.1) + CIERRE IMPLEMENTADO (2026-08-25).
D3.1–D3.4 están implementados, el modo deterministic-first es el **default**
de runtime y **D2.9 ya es el ranker determinista de producción** (cutover
2026-08-25): el pipeline default es 100% determinista, con el ranker LLM
disponible sólo como rollback (`RACE_ENGINEER_LLM_RANKER=1`). Este documento
conserva el audit original como referencia analítica.

**Fecha:** 2026-08-25 · **Método:** call graph real (no búsqueda por nombre).

## 0. Cierre D3 (post-implementación)

### Qué cambió

| Ítem | Estado |
|---|---|
| D3.1 — H5.2 narrativa non-blocking | IMPLEMENTADO: `h5_2_llm_skip_on_failure()` marca `SKIPPED_NOT_APPLICABLE` y el análisis continúa. |
| D3.2 — Comparison summary deterministic-first | IMPLEMENTADO: `RACE_ENGINEER_SUMMARY_DETERMINISTIC` + `build_deterministic_comparison_summary`. |
| D3.3 — Global prose deterministic-first | IMPLEMENTADO: `RACE_ENGINEER_GLOBAL_DETERMINISTIC` + `build_deterministic_global_fallback` + `build_deterministic_next_session_priorities`. |
| D3.4 — Episode interpretation deterministic-first | IMPLEMENTADO: `RACE_ENGINEER_EPISODE_DETERMINISTIC` + `build_deterministic_grounded_episode_fallback`; episodios genuinamente interpretativos quedan fail-closed REJECTED. |
| D3.5 — Ranker determinista (L2) | IMPLEMENTADO (cutover 2026-08-25): D2.9 product policy por default; rollback `RACE_ENGINEER_LLM_RANKER=1`. |
| D3.6 — LLM offline fuera del runtime | FORMALIZADO: pair review (H2.2) y selección H5.3c siguen siendo offline. |

### Mecanismo del default

Nuevo switch maestro en los 4 backends (`llm_analysis*.py`):

```text
RACE_ENGINEER_DETERMINISTIC_FIRST   default "1" -> los tres modos
                                          (episodio, summary, global)
                                          usan salida determinista sin LLM.

RACE_ENGINEER_EPISODE_DETERMINISTIC   =0 desactiva sólo episodio
RACE_ENGINEER_SUMMARY_DETERMINISTIC   =0 desactiva sólo summary
RACE_ENGINEER_GLOBAL_DETERMINISTIC    =0 desactiva sólo global

RACE_ENGINEER_DETERMINISTIC_FIRST=0   desactiva el default global;
                                      un flag específico =1 sigue forzando
                                      ese modo individual.
```

Con el default activo, el runtime por comparación **no hace ninguna llamada
LLM**: episodio, summary, global y ranker (D2.9 product policy) son
deterministas y no llaman transporte. La clasificación
(PRIORITARIO / SECUNDARIO / NO_ACCIONABLE) sale de
`product_priority_ranker.build_product_priority_ranker_response` y alimenta la
narrativa y el ordenamiento del summary determinista. El ranker LLM queda como
rollback explícito (`RACE_ENGINEER_LLM_RANKER=1`).

### Evidencia

- **901/901 episodios** del corpus `data/generated/llm_results/` (todas las
  sesiones/tracks/backends) se reconstruyen con
  `build_deterministic_grounded_episode_fallback` + validator, sin fallos. El
  camino fail-closed de D3.4 no se disparó con datos reales.
- Validación real con los 3 modos activos (`--force-llm`, Spa
  `R_2026-08-10T01_03_52Z`): exit 0, `[llm] RUN`, `[llm_validator] RUN`
  ("Ground truth, contrato de episodios y render final consistentes").
- Validación real post-cutover (Fuji `P_2026-08-19T19_38_36Z`, 3 comparisons,
  `--force-llm` sin API key): `[llm] RUN` 100% determinista, **HTTP requests:
  0 / tokens: 0 / costo $0.00**, `[llm_validator] RUN` PASS, RESULT PASS.
- Suite completa: **1300 PASS / 0 FAIL / 0 SKIP**.

### Riesgo residual conocido

Un episodio futuro genuinamente interpretativo (Python no puede reconstruir el
contrato) falla la comparación en fail-closed en vez de degradar silenciosamente.
Con 0 casos en el corpus actual el riesgo es teórico; si aparece, la opción es
extender el grounded fallback (sin debilitar validators) o definir un manejo
explícito antes de promocionar D3.4 a producción.

## 1. Executive summary

El pipeline "LLM" de Race Engineer ya es mayormente determinista en la
superficie: `next_stint_plan`, `driver_cues`, targets, P9/P10/P11 y
`episode_ground_truth` los construye Python. Pero el runtime todavía hace **6
tipos de llamadas LLM** (D3-L1..L6), y **5 de ellas pueden bloquear el análisis
completo de una sesión** aunque los hechos deterministas ya estén disponibles.
La única dependencia **production-authoritative** que decide semántica es el
ranker de prioridad (D3-L2) y la interpretación por episodio (D3-L1); el resto
es wording/estructura validada (L3, L4) u observacional (L5, L6).

Conclusión: hoy **NO** se puede construir un debrief 100% determinista sin
decisión sobre el ranker (D2), pero sí se pueden **eliminar sin tocar D2** al
menos 3 dependencias (L5, L3, L4) que hoy pueden matar un análisis por una
caída del backend LLM.

## 2. Runtime flow textual

```text
telemetria/<archivo>.duckdb
  -> race_engineer.py analyze
      1. analyze_telemetry.py --validate      (Python, determinista)
      2. llm_analysis_<backend>.py            (SUBPROCESO; D3-L1..L4)
           por comparison:
             L1 episodio x N  -> interpretación aislada (LLM + fallback)
             L2 ranker        -> order + priority_cut + no_actionable (LLM)
             L3 summary       -> resumen de la comparison (LLM + repair)
           -> next_stint_plan / driver_cues / P9/P10/P11 = PYTHON
           L4 global          -> global_analysis / conclusion (LLM + fallback)
      3. validate_llm_analysis_output.py      (validator)
      4. session_history.py (History)         (Python)
      5. h5_2_llm: historical_llm_analysis.py (D3-L5, narrativa observacional)
      6. h5_3: build/render/validate          (Python determinista; sin LLM)
  -> data/generated/llm_results/<session>/<debrief>.json
```

La etapa `h5_3` del orquestador NO llama al LLM: los candidatos, render y
validator son deterministas. La selección LLM de H5.3c (D3-L6) es una
herramienta offline shadow.

## 3. Censo de llamadas LLM en runtime

Transportes (uno por backend): `deepseek_chat` (llm_analysis_deepseek.py:2251),
`ollama_chat` (llm_analysis.py:2034, alias = llm_analysis_ingenierov3.py),
`llamacpp_chat` (llm_analysis_llamacpp.py:2333). Los cuatro sitios de llamada
se repiten idénticos en los tres backends.

| ID | Caller | Archivo:línea (deepseek) | Prompt | Output esperado | Validator | Retry/repair |
|---|---|---|---|---|---|---|
| D3-L1 | `get_validated_episode_response` | 6037→6070 | `EPISODE_SYSTEM_PROMPT` (`build_single_episode_prompt`) | assessment de episodio (grounded, hipótesis, recomendación) | `validate_single_episode_llm_response` | 2 intentos + `deterministic_episode_semantic_fallback` / prune |
| D3-L2 | `get_validated_comparison_ranker_response` | 7105→7132 | `COMPARISON_RANKER_SYSTEM_PROMPT` | `ordered_episode_ids`, `priority_cut_rank`, `no_actionable_start_rank` | `validate_comparison_ranker_response` | 2 intentos; shadow determinista (D2) observacional |
| D3-L3 | `get_validated_comparison_summary_response` | 7555→7584 | `COMPARISON_SUMMARY_SYSTEM_PROMPT` | resumen/conclusion por comparison | `validate_comparison_summary_llm_response` | 2 intentos + repair `target_reference` + prune; `build_deterministic_comparison_summary` existe |
| D3-L4 | `get_validated_global_response` | 17544 | `GLOBAL_SYSTEM_PROMPT` | `global_analysis`, `conclusion`, `repeated_observations`, highlights | `validate_global_llm_response` | 3 intentos + repairs deterministas (repeated_observations, steering anchor, list overflow) + `build_deterministic_global_fallback` |
| D3-L5 | `historical_llm_analysis.generate_response` | historical_llm_analysis.py:412→377 | narrativa H5.2 | `overview_code`, `selected_zones`, `limitation_codes` | `validate_historical_llm_analysis.py` | 1 llamada; fallback de salida si no valida |
| D3-L6 | `historical_candidate_selection.generate_response` | historical_candidate_selection.py:451→416 | selección H5.3c | selección de candidatos shadow | `validate_historical_candidate_selection.py` | offline tool (no en orquestador) |

## 4. Authority map

| ID | Producción authority | Bloquea el análisis | Cambia next_stint_plan | Cambia classifications | Sólo wording | Reemplazo determinista |
|---|---|---|---|---|---|---|
| D3-L1 | SÍ (interpretación episodio) | SÍ (comparison REJECT → RuntimeError) | Indirecto (alimenta summary) | No (prioridad la pone L2) | No | PARTIAL (`deterministic_episode_semantic_fallback`) |
| D3-L2 | SÍ (prioridad/cuts) | SÍ (ranker REJECT → comparison REJECT) | Indirecto (priority → plan) | SÍ | No | PARTIAL (D2.1/D2.3/D2.4 shadow, no promovido) |
| D3-L3 | No (estructura validada) | SÍ (summary REJECT → comparison REJECT) | No | No | Sí (resumen) | COMPLETE (`build_deterministic_comparison_summary`) |
| D3-L4 | No (prosa validada) | SÍ (global REJECT → RuntimeError) | No | No | Sí (prosa global) | COMPLETE (`build_deterministic_global_fallback`) |
| D3-L5 | No (observacional) | SÍ (h5_2_llm FAILED → return 1) | No | No | Sí (narrativa H5.2) | NONE (presentación) |
| D3-L6 | No (shadow) | No (offline) | No | No | No | COMPLETE (`historical_candidate_selection_runtime.py`) |

## 5. Failure-mode map

- **Timeout / backend caído / JSON inválido:**
  - L1-L3: reintentos de transporte (2) + generación (3) + validación (2). Si
    aún inválido → `REJECTED` → `RuntimeError` → el subproceso sale != 0 → la
    etapa `llm` del orquestador falla → **el análisis entero de la sesión
    falla**, aunque Python ya tenga todos los facts y el plan.
  - L4: igual, con 3 intentos y fallback determinista; si falla → `RuntimeError`
    → misma consecuencia.
  - L5: falla del backend → `h5_2_llm FAILED` → **return 1**: una narrativa
    observacional puede matar el análisis ya completado.
  - L6: no afecta runtime.
- **Puntos donde una caída del LLM mata un análisis que Python ya podría
  completar:** L1..L4 (etapa llm) y L5 (narrativa H5.2). El orquestador no
  tiene modo "deterministic-only" que reemplace esos bloques (el `--no-llm`
  existe pero desactiva el debrief entero, no produce un debrief determinista).

## 6. Existing deterministic substitutes

- `build_deterministic_comparison_summary` (L3) — completo.
- `build_deterministic_global_fallback` + repairs deterministas (L4) — completo
  para prosa.
- `deterministic_episode_semantic_fallback` (L1) — parcial (repara campos
  semánticos, no reemplaza la interpretación entera).
- D2.1/D2.3/D2.4 (`build_deterministic_comparison_ranker_response`,
  `build_calibrated_priority_cut_rank`, `build_calibrated_no_actionable_*`) —
  shadow, no promovido (D2 en HOLD).
- `historical_candidate_selection_runtime.py` — reemplazo determinista de L6.

## 7. Extraction difficulty

| ID | Dificultad | Riesgo | Depende de D2 |
|---|---|---|---|
| D3-L5 | Baja (decouplar etapa) | Bajo | No |
| D3-L4 | Baja-media (usar fallback por defecto) | Medio (prosa cambia a templated) | No |
| D3-L3 | Media (resumen determinista primero) | Medio | No |
| D3-L1 | Alta (interpretación semántica) | Alto | Parcial |
| D3-L2 | Muy alta (autoridad de prioridad) | Alto | SÍ |
| D3-L6 | N/A (ya offline) | Bajo | No |

## 8. Roadmap D3.x propuesto (basado en código real)

Orden original: **primero lo que NO depende de D2**. Estado actual:

| Ítem | Estado | Nota |
|---|---|---|
| D3.1 — H5.2 narrative non-blocking (L5) | IMPLEMENTADO | `h5_2_llm_skip_on_failure()`; sin `return 1`. |
| D3.2 — Global prose deterministic-first (L4) | IMPLEMENTADO | `build_deterministic_global_fallback` + `next_session_priorities` deterministas. |
| D3.3 — Comparison summary deterministic-first (L3) | IMPLEMENTADO | `build_deterministic_comparison_summary`; LLM queda en opt-out. |
| D3.4 — Episode interpretation determinista (L1) | IMPLEMENTADO | Grounded fallback por canal; interpretativos fail-closed. |
| D3.5 — Ranker (L2) | IMPLEMENTADO | D2.9 product policy = ranker de producción (default); rollback `RACE_ENGINEER_LLM_RANKER=1`. |
| D3.6 — Lazy/offline LLM | FORMALIZADO | H2.2 / H5.3c fuera del runtime. |

## 9. Low-hanging fruit — TOP 3

1. **D3-L5 (narrativa H5.2)**: observacional, presentation-only, y hoy puede
   matar el análisis. Eliminar el bloqueo (non-blocking) es el cambio más chico
   y de mayor valor.
2. **D3-L3 (summary)**: `build_deterministic_comparison_summary` ya existe;
   el LLM sólo reformatea facts validados → se puede hacer deterministic-first.
3. **D3-L4 (global prose)**: fallback determinista casi completo; la prosa
   global puede ser templated con LLM opcional.

## 10. Preguntas que responde este audit

- ¿Se puede construir hoy un debrief funcional 100% determinista? **Estructura
  sí** (plan/cues/P9-P11/ground truth ya son Python); **autoridad de prioridad
  no**, porque D3-L2 sigue siendo LLM y el reemplazo D2 no está promovido.
- ¿Cuál es la dependencia más difícil de extraer? **D3-L2 (ranker)** — es la
  única con authority semántica real y su reemplazo depende de la decisión D2.
- ¿Cuántas llamadas bloquean hoy? **5 de 6** (L1-L5).

## Limitaciones

- El audit es estático sobre el call graph; no se ejecutaron llamadas LLM.
- Líneas referidas al backend deepseek; los backends ollama/llamacpp replican
  los mismos 4 sitios (llm_analysis.py:5872/6393/6845/16823,
  llm_analysis_llamacpp.py:6161/6682/7134/17069).
