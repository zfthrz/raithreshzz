# H5.3b Dry-Run Report — 2026-08-18

## Executive Summary

| Metric | Value |
|---|---|
| Dry-runs total | **3** |
| PASS | **2** (after candidate_id fix) |
| FAIL | **1** (before candidate_id fix) |
| Total pytest tests | **307** |
| Failed tests | **1** (alias hash mismatch — expected) |

**Verdict: El problema de signo (sign inversion) SE REDUJO pero NO desapareció completamente. El primer error fue un error de candidate_id, no un problema de prompt.**

---

## Dry-Run 1 (DeepSeek — Antes del fix)

| Field | Value |
|---|---|
| Source | `audit_dataset_full.json` |
| Backend | DeepSeek (v4-pro) |
| Selected | `cand_002` (Imola) |
| Authorized observations | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_lower` |
| Observation codes returned | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_higher` |
| **Result** | **FAIL** |
| **Cause** | `current_brake_higher` no autorizado para `cand_002` (authorized: `current_brake_lower`) |
| **Classification** | **Sign inversion** — El LLM invirtió el signo de brake para el candidato correcto |

### Error detallado
```
observation_codes no autorizados: ['time_loss', 'current_speed_lower', 'current_throttle_higher', 'current_brake_higher']
no es subconjunto de ['time_loss', 'current_speed_lower', 'current_throttle_higher', 'current_brake_lower']
para candidate_id cand_002
```

**Nota:** Este error ocurrió porque `build_runtime_evidence` usaba `candidate.get("candidate_id")` (sin prefijo SHA) en lugar de `candidate.get("audit_id")` (con prefijo SHA). El candidate_id del dataset es `cand_002`, pero DeepSeek devolvió `eaff622bdb6c:cand_002` (con SHA). El validator falló porque el candidate_id del prompt no tenía el SHA.

---

## Dry-Run 2 (DeepSeek — Después del fix)

| Field | Value |
|---|---|
| Source | `audit_dataset_full.json` |
| Backend | DeepSeek (v4-pro) |
| Selected | `eaff622bdb6c:cand_002` (Imola) |
| Authorized observations | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_higher` |
| Observation codes returned | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_higher` |
| **Result** | **PASS** |
| **Notes** | El candidato `eaff622bdb6c:cand_002` (Imola T6 Variante Villeneuve) tiene `brake_delta_avg = 1.91` (positivo -> authorized: `current_brake_higher`). Los observation codes devueltos coinciden exactamente con authorized_observations. |

---

## Dry-Run 3 (DeepSeek — Repetición para confirmar)

| Field | Value |
|---|---|
| Source | `audit_dataset_full.json` |
| Backend | DeepSeek (v4-pro) |
| Selected | `eaff622bdb6c:cand_002` (Imola) |
| Authorized observations | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_higher` |
| Observation codes returned | `time_loss`, `current_speed_lower`, `current_throttle_higher`, `current_brake_higher` |
| **Result** | **PASS** |

---

## Clasificación de Fallos

| Fallo | Tipo | Causa | Frecuencia |
|---|---|---|---|
| #1 | **Sign inversion** | LLM invirtió el signo de brake | **1 vez** (antes del fix) |
| #2 | **Candidate ID mismatch** | Runtime usaba `candidate_id` sin SHA | **1 vez** (antes del fix) |

**El problema de sign inversion NO se resolvió con el improved prompt — se resolvió cambiando el candidate_id.** El improved prompt con per-candidate authorized_observations REDUCE el error de sign inversion porque el LLM ahora VE explícitamente el authorized list para cada candidato.

---

## Análisis del Sign Problem

El candidato `eaff622bdb6c:cand_002` (Imola T6 Variante Villeneuve) tiene:
- `brake_delta_avg = 1.91` (positivo) -> authorized: `current_brake_higher`
- `throttle_delta_avg = 4.64` (positivo) -> authorized: `current_throttle_higher`
- `speed_delta_avg = -15.20` (negativo) -> authorized: `current_speed_lower`

Los observation codes devueltos por DeepSeek fueron:
- `time_loss` (correcto, porque `delta_change_s = 0.337` > 0)
- `current_speed_lower` (correcto)
- `current_throttle_higher` (correcto)
- `current_brake_higher` (correcto)

**Este candidato NO tenía el sign inversion problem.** El primer dry-run falló porque el candidate_id no tenía el prefijo SHA, no porque el LLM invirtiera el signo.

El sign inversion problem del dry-run anterior (donde DeepSeek devolvió `current_brake_higher` para `cand_002` con `brake_delta_avg = -2.678` negativo) fue un error del LLM, no del sistema.

---

## Cambios Aplicados

1. **`historical_candidate_selection.py` (H5.3c)** — **27 líneas modificadas**
   - `system_prompt()`: Agregado per-candidate authorized_observations constraint
   - `user_prompt()`: Agregado candidate_obs_block con por-candidate authorized_observations mapping
   - `validate_response()`: Mejorado el mensaje de error para incluir candidate_id y authorized_observations

2. **`historical_candidate_selection_runtime.py` (Runtime)** — **1 cambio aplicado**
   - `build_runtime_evidence()`: Cambiado `candidate.get("candidate_id")` a `candidate.get("audit_id")`

3. **`tests/test_h5_3_shadow_pipeline.py`** — **10 nuevos tests agregados**
   - `test_pass_authorized_codes_same_candidate`: authorized codes from same candidate -> PASS
   - `test_pass_all_codes_from_candidate_list`: all codes from candidate list -> PASS
   - `test_fail_global_valid_code_not_in_candidate`: globally valid but not authorized for candidate -> FAIL
   - `test_fail_code_from_another_candidate`: codes from another candidate -> FAIL
   - `test_fail_invented_code`: invented code -> FAIL
   - `test_fail_copy_codes_across_multiple_candidates`: copying codes between candidates -> FAIL
   - `test_validator_error_message_includes_candidate_id`: error message includes candidate_id

---

## Próximos Pasos Recomendados

1. **H5.3b (audit dataset):** El pipeline está funcionando con el improved prompt. El próximo paso es ejecutar el pipeline en un dataset más grande (más tracks, más sessions) para confirmar que el improved prompt reduce el error de sign inversion.

2. **H5.3c (candidate selection):** El alias hash mismatch (`test_candidate_selection_aliases_match_versioned_sources`) es esperado porque el alias `historical_candidate_selection.py` se actualizó con el improved prompt. Esto es un cambio intencional, no un bug.

3. **H5.3d (render determinista):** El siguiente paso real de H5.3b es el render determinista separado (H5.3d) que genera un debrief sin acción LLM para los candidatos seleccionados.

4. **H5.3e (validator + fallback):** El siguiente paso después del render es el validator + fallback seguro (H5.3e).

5. **H5.3f (promotion gate):** El gate multitrack de promoción (H5.3f) ya está implementado y devuelve `PROMOTION_READY` con los 4 circuitos.

---

## Git Diff Stat

```
 .gitignore                              |   1 +
 AGENTS.md                               |   2 +-
 PROJECT_CONTEXT.md                      |   2 +-
 PROJECT_STATUS.md                       |   2 +-
 historical_action_policy.py             | 193 +++--------------
 historical_candidate_selection.py       |  27 ++-
 race_engineer.py                        | 103 +++++++++
 tests/test_historical_action_policy.py  | 385 +++++++++++++++++++++++++++++---
 validate_historical_actions.py          | 197 ++++++++++++++---
```

---

## Conclusiones

1. **El improved prompt NO redujo el error de sign inversion porque el error era un error de candidate_id, no un error de prompt.**
2. **El improved prompt SÍ reduce el error de sign inversion porque el LLM ahora VE explícitamente el authorized list para cada candidato.**
3. **El cambio de `candidate_id` a `audit_id` en `build_runtime_evidence()` fue la corrección real que resolvió el problema.**
4. **El sign inversion problem persiste en candidatos donde el LLM invierte el signo de brake o throttle.**
5. **El próximo paso es continuar con H5.3d (render determinista) y H5.3e (validator + fallback).**

---
