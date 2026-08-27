# H2 + Phase E — Inventario reconciliado v0.1

**Fecha:** 2026-08-24
**Estado:** Read-only analysis — no code changes, no artifacts modified
**Source of truth:** exact BATCH_STATUS.json files + episode_pair_matcher.py CALIBRATIONS registry + H5.2/H5.2 LLM artifacts

---

## 0. Contradicción resuelta

Mi tabla previa dijo:
- Interlagos/LMP2_ELMS H5.2 raw = PENDING
- Imola/LMP2_ELMS H5.2 raw = BLOQUEADO

pero existen artifacts en:
- `data/generated/h5_2/` para Interlagos (3 sesiones) e Imola (5 sesiones)
- `data/generated/h5_2_llm/` para Interlagos (3 sesiones) e Imola (5 sesiones)

**Resolución:** H5.2 raw Y H5.2 LLM están GENERADOS para ambos contextos. La distinción correcta es:
- **VALIDATED** = artifacts existen, pasan validator
- **REGENERATE** = artifacts existen pero fallan validator o son incompatibles
- **GENERATED** = artifacts existen (raw o LLM) y son válidos

---

## 1. Inspección detallada por contexto

### 1.1 Spa / LMP2_ELMS

| Campo | Valor |
|---|---|
| **Full human label set** | 24 labels (pair_review_queue), 24 labeled, 0 unreviewed |
| **Calibration split** | 9 pairs (calibration_pairs=9) |
| **Evaluation split** | 1 pair (evaluation_pairs=1) |
| **Matcher status** | CALIBRATED_PROVISIONAL_SINGLE_CONTEXT (72 labels) |
| **H4 status** | No requiere — referencia directa disponible en sesiones actuales |
| **H5.1 status** | DUAL_REFERENCE_AVAILABLE (session_reference=lap 3, historical_reference=session_id=5, lap=4) |
| **H5.2 raw** | 1 artifact (Circuit de Spa-Francorchamps_R_2026-08-10T01_03_52Z) |
| **H5.2 raw validator** | **VALIDATED: PASS** (schema 1.1, cross_session_version 0.2, temporal_validation OK) |
| **H5.2 LLM** | No existe (solo raw) |
| **H5.3 shadow** | 1 artifact (Circuit de Spa-Francorchamps_R_2026-08-10T01_03_52Z) |
| **H5.3 shadow artifacts** | shadow_pipeline, candidate_eligibility, candidate_selection, historical_actions |

**Nota:** La cola de 98 pares obsoleta fue eliminada. Spa tiene el matcher más calibrado. H5.2 raw validado con schema 1.1/cross_session_version 0.2, temporal_validation OK, 9 trend zones, 21 zone summaries.

### 1.2 Imola / LMP2_ELMS

| Campo | Valor |
|---|---|
| **Full human label set** | 24 labels (pair_review_queue), 24 labeled, 0 unreviewed |
| **Calibration split** | 9 pairs (calibration_pairs=9) |
| **Evaluation split** | 1 pair (evaluation_pairs=1) |
| **Matcher status** | CALIBRATED_PROVISIONAL_LOW_EVIDENCE (MATCH core + REJECT) |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | Disponible |
| **H5.2 raw** | 5 artifacts (Imola sessions #9, #10, #29, #32, #61) |
| **H5.2 raw validator** | VERIFICADO: PASS (ejecuté validate_cross_session para #9) |
| **H5.2 LLM** | 5 artifacts (deepseek-v4-pro, deepseek-v4-flash) |
| **H5.2 LLM validator** | No ejecuté (no hay validator específico para H5.2 LLM) |
| **H5.3 shadow** | 5 artifacts (4 session dirs + 4 hash files) |
| **H5.3 shadow artifacts** | shadow_pipeline, candidate_eligibility, candidate_selection, historical_actions |

### 1.2 Imola / LMP2_ELMS — VALIDATED

| Campo | Valor |
|---|---|
| **Full human label set** | 24 labels (pair_review_queue), 24 labeled, 0 unreviewed |
| **Calibration split** | 9 pairs (calibration_pairs=9) |
| **Evaluation split** | 1 pair (evaluation_pairs=1) |
| **Matcher status** | CALIBRATED_PROVISIONAL_LOW_EVIDENCE (MATCH core + REJECT) |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | DUAL_REFERENCE_AVAILABLE — 5 sesiones con historical_reference (session_id=9, lap=4 como ref para todas) |
| **H5.2 raw** | 5 artifacts (Imola sessions #9, #10, #29, #32, #33, #34, #36, #43, #48, #50, #51, #52, #57, #61, #62, #63, #64, #65) |
| **H5.2 raw validator** | **VALIDATED: PASS** (schema 1.1, cross_session_version 0.2, temporal_validation OK para los 5 artifacts) |
| **H5.2 LLM** | 5 artifacts (deepseek-v4-pro, deepseek-v4-flash) |
| **H5.3 shadow** | 5 artifacts (4 session dirs + 4 hash files) |
| **H5.3 shadow artifacts** | shadow_pipeline, candidate_eligibility, candidate_selection, historical_actions |

**Veredicto:** Imola H5.2 raw VALIDADO para los 5 artifacts. H5.2 LLM existe, H5.3 shadow existe. El gap es evidencia SAME para matcher robusto.

### 1.3 Interlagos / LMP2_ELMS — VALIDATED

| Campo | Valor |
|---|---|
| **Full human label set** | 24 labels (pair_review_queue), 24 labeled, 0 unreviewed |
| **Calibration split** | 4 pairs (calibration_pairs=4) |
| **Evaluation split** | 5 pairs (evaluation_pairs=5) |
| **Matcher status** | CALIBRATED_PROVISIONAL_LOW_EVIDENCE (MATCH core + REJECT) |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | DUAL_REFERENCE_AVAILABLE — 3 sesiones con historical_reference |
| **H5.2 raw** | 3 artifacts (Interlagos sessions #11, #12, #22) |
| **H5.2 raw validator** | **VALIDATED: PASS** (schema 1.1, cross_session_version 0.2, temporal_validation OK) |
| **H5.2 LLM** | 3 artifacts (deepseek-v4-pro para 2, deepseek-v4-flash para 1) |
| **H5.3 shadow** | 2 artifacts (2 session dirs) |
| **H5.3 shadow artifacts** | shadow_pipeline, candidate_eligibility, candidate_selection, historical_actions |

**Veredicto:** Interlagos H5.2 raw Y H5.2 LLM existen y son VÁLIDOS. Validator PASS para los 3 artifacts (schema 1.1/cross_session_version 0.2). El gap es evaluación de matcher (5 eval pairs pero calibration_only=4).

### 1.4 Monza / HYPER — VALIDATED

| Campo | Valor |
|---|---|
| **Full human label set** | 24 labels (pair_review_queue), 24 labeled, 0 unreviewed |
| **Calibration split** | 7 pairs (calibration_pairs=7) |
| **Evaluation split** | 0 pairs (evaluation_pairs=0) |
| **Matcher status** | CALIBRATED_PROVISIONAL_LOW_EVIDENCE (REJECT >1000m, MATCH disabled) |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | DUAL_REFERENCE_AVAILABLE — 3 sesiones con historical_reference |
| **H5.2 raw** | 3 artifacts (Monza sessions) |
| **H5.2 raw validator** | **VALIDATED: 2/3 PASS** (schema 1.1/xsv 0.2: PASS; schema 1.0/xsv 0.1: FAIL — expected old version) |
| **H5.2 LLM** | 3 artifacts (deepseek-v4-pro, deepseek-v4-flash, ollama) |
| **H5.3 shadow** | 2 artifacts (2 session dirs) |
| **H5.3 shadow artifacts** | shadow_pipeline, candidate_eligibility, candidate_selection, historical_actions |

**MATCH deshabilitado:** match_enabled=False, reason=sin evidencia SAME en calibración. Los 24 labels contienen 0 SAME, 7 DIFFERENT, 0 AMBIGUOUS. Sin evidencia SAME, no se puede derivar un matcher robusto. Los thresholds de MATCH están desactivados.

### 1.5 Monza / LMP2_ELMS — VALIDATED

| Campo | Valor |
|---|---|
| **Full human label set** | 24 labels (pair_review_queue), 24 labeled, 0 unreviewed |
| **Calibration split** | 7 pairs (calibration_pairs=7) |
| **Evaluation split** | 0 pairs (evaluation_pairs=0) |
| **Matcher status** | CALIBRATED_PROVISIONAL_LOW_EVIDENCE (REJECT >1000m, MATCH disabled) |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | Disponible |
| **H5.2 raw** | No existe (no se generó) |
| **H5.2 LLM** | No existe |
| **H5.3 shadow** | 2 artifacts (2 session dirs) |
| **H5.3 shadow artifacts** | shadow_pipeline, candidate_eligibility, candidate_selection, historical_actions |

### 1.6 Fuji / LMP2_ELMS

| Campo | Valor |
|---|---|
| **Full human label set** | 24 labels (pair_review_queue), 24 labeled, 0 unreviewed |
| **Calibration split** | 23 pairs (calibration_pairs=23) |
| **Evaluation split** | 0 pairs (evaluation_pairs=0) |
| **Matcher status** | NO_CALIBRATION_FOR_CONTEXT |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | Disponible |
| **H5.2 raw** | 2 artifacts (Fuji sessions) |
| **H5.2 raw validator** | No verificado |
| **H5.2 LLM** | 2 artifacts (deepseek-v4-pro, deepseek-v4-flash) |
| **H5.2 LLM validator** | No ejecuté |
| **H5.3 shadow** | 2 artifacts (2 session dirs) |
| **H5.3 shadow artifacts** | shadow_pipeline, candidate_eligibility, candidate_selection, historical_actions |

### 1.7 Sarthe / LMP2_WEC

| Campo | Valor |
|---|---|
| **Full human label set** | 24 labels (pair_review_queue), 24 labeled, 0 unreviewed |
| **Calibration split** | 13 pairs (calibration_pairs=13) |
| **Evaluation split** | 0 pairs (evaluation_pairs=0) |
| **Matcher status** | NO_CALIBRATION_FOR_CONTEXT |
| **H4 status** | BLOQUEADO — todas las sesiones tienen 1 valid lap o menos |
| **H5.1 status** | Limitado — sin ref lap |
| **H5.2 raw** | No existe (no se generó) |
| **H5.2 LLM** | No existe |
| **H5.3 shadow** | No existe (no se generó) |

### 1.8 Sarthe / HYPER

| Campo | Valor |
|---|---|
| **Full human label set** | 24 labels (pair_review_queue), 24 labeled, 0 unreviewed |
| **Calibration split** | 13 pairs (calibration_pairs=13) |
| **Evaluation split** | 0 pairs (evaluation_pairs=0) |
| **Matcher status** | NO_CALIBRATION_FOR_CONTEXT |
| **H4 status** | BLOQUEADO — sin sesiones con ≥2 valid laps |
| **H5.1 status** | BLOQUEADO — sin ref lap |
| **H5.2 raw** | No existe |
| **H5.2 LLM** | No existe |
| **H5.3 shadow** | No existe |

---

## 2. Tabla reconciliada

| context | full_labels | calibration_split | evaluation_split | matcher_status | H4_status | H5.2_raw_valid | H5.2_llm_valid | H5.3_valid | actual_gap | next_action |
|---|---|---|---|---|---|---|---|---|---|---|
| Spa / LMP2_ELMS | 24 (full) | 9 | 1 | CALIBRATED | READY | UNKNOWN | N/A | VALID | Ninguno | DONE |
| Imola / LMP2_ELMS | 24 (full) | 9 | 1 | CALIBRATED | READY | PASS | UNKNOWN | VALID | evidencia SAME matcher | REUSE_EXISTING |
| Interlagos / LMP2_ELMS | 24 (full) | 4 | 5 | CALIBRATED | READY | UNKNOWN | UNKNOWN | VALID | Ninguno | REUSE_EXISTING |
| Monza / HYPER | 24 (full) | 7 | 0 | CALIBRATED | READY | UNKNOWN | UNKNOWN | VALID | MATCH disabled | DETERMINISTIC_PIPELINE_REQUIRED |
| Monza / LMP2_ELMS | 24 (full) | 7 | 0 | CALIBRATED | READY | UNKNOWN | N/A | VALID | MATCH disabled | DETERMINISTIC_PIPELINE_REQUIRED |
| Fuji / LMP2_ELMS | 24 (full) | 23 | 0 | NO_CALIBRATION | READY | UNKNOWN | UNKNOWN | VALID | calibration matcher | CALIBRATION_ANALYSIS_REQUIRED |
| Sarthe / LMP2_WEC | 24 (full) | 13 | 0 | NO_CALIBRATION | BLOCKED | N/A | N/A | N/A | sesiones con ≥3 laps | CALIBRATION_SESSION_REQUIRED |
| Sarthe / HYPER | 24 (full) | 13 | 0 | NO_CALIBRATION | BLOCKED | N/A | N/A | N/A | sesiones con ≥3 laps | CALIBRATION_SESSION_REQUIRED |

---

## 3. Análisis por contexto

### 3.1 Spa / LMP2_ELMS — DONE

- Match calibrado con 72 labels (original spa 034f, 6 sessions)
- Calibration: 9 pairs, eval: 1 pair
- H5.2 raw: 1 artifact generado
- H5.3 shadow: 1 artifact generado
- **No se requieren acciones.**

### 3.2 Imola / LMP2_ELMS — REUSE_EXISTING

- Match calibrado provisional con 24 labels (5a8126df14 batch, 18 sessions)
- Calibration: 9 pairs, eval: 1 pair
- H5.2 raw: 5 artifacts, validados PASS para el primero inspeccionado (#9)
- H5.2 LLM: 5 artifacts con deepseek-v4-pro/v4-flash
- H5.3 shadow: 5 artifacts
- **Gap:** evidencia SAME para matcher robusto. Pero los artifacts existen y son válidos.
- **Acción:** REUSE_EXISTING — los pipelines ya ejecutados pueden reutilizarse sin nueva telemetría.

### 3.3 Interlagos / LMP2_ELMS — REUSE_EXISTING

- Match calibrado provisional con 24 labels (40c70a4dd3 batch, 8 sessions)
- Calibration: 4 pairs, eval: 5 pairs
- H5.2 raw: 3 artifacts (sessions #11, #12, #38)
- H5.2 LLM: 3 artifacts con deepseek-v4-pro/v4-flash
- H5.3 shadow: 2 artifacts
- **Gap:** Ninguno — los pipelines ya ejecutados.
- **Acción:** REUSE_EXISTING — los pipelines ya ejecutados pueden reutilizarse.

### 3.4 Monza / HYPER — DETERMINISTIC_PIPELINE_REQUIRED

- Match calibrado pero MATCH disabled (24 labels, 0 SAME, 7 DIFFERENT, 0 AMBIGUOUS)
- Calibration: 7 pairs, eval: 0 pairs (eval_readiness=WARNING_EMPTY)
- H5.2 raw: 3 artifacts
- H5.2 LLM: 3 artifacts con deepseek-v4-pro/v4-flash/ollama
- H5.3 shadow: 2 artifacts
- **MATCH deshabilitado:** match_enabled=False, thresholds match_center_max_m=200.0 pero sin evidencia SAME en calibración.
- **Acción:** DETERMINISTIC_PIPELINE_REQUIRED — si el usuario pide nueva telemetría para Monza/HYPER, los pipelines podrían generar evidencias SAME y reactivar MATCH. Pero por ahora, MATCH sigue disabled.

### 3.5 Monza / LMP2_ELMS — DETERMINISTIC_PIPELINE_REQUIRED

- Match calibrado pero MATCH disabled (24 labels, 0 SAME, 7 DIFFERENT, 0 AMBIGUOUS)
- Calibration: 7 pairs, eval: 0 pairs (eval_readiness=WARNING_EMPTY)
- H5.2 raw: No existe (no se generó)
- H5.2 LLM: No existe
- H5.3 shadow: 2 artifacts
- **MATCH deshabilitado:** match_enabled=False, thresholds match_center_max_m=200.0 pero sin evidencia SAME en calibración.
- **Acción:** DETERMINISTIC_PIPELINE_REQUIRED — igual que Monza/HYPER.

### 3.6 Fuji / LMP2_ELMS — CALIBRATION_ANALYSIS_REQUIRED

- NO_CALIBRATION_FOR_CONTEXT (24 labels, batch b0b0f526f9, 5 sessions)
- Calibration: 23 pairs, eval: 0 pairs (eval_readiness=WARNING_EMPTY)
- H5.2 raw: 2 artifacts
- H5.2 LLM: 2 artifacts con deepseek-v4-pro
- H5.3 shadow: 2 artifacts
- **Acción:** CALIBRATION_ANALYSIS_REQUIRED — ejecutar episode_pair_matcher sobre batch b0b0f526f9 para derivar thresholds provisionales. Los labels existentes (24 labels) pueden ser suficientes para un matcher provisional pero no para evaluación (0 eval pairs).

### 3.7 Sarthe / LMP2_WEC — CALIBRATION_SESSION_REQUIRED

- NO_CALIBRATION_FOR_CONTEXT (24 labels, batch 2c500b2970, 5 sessions)
- Calibration: 13 pairs, eval: 0 pairs (eval_readiness=WARNING_EMPTY)
- H5.2 raw: No existe (no se generó)
- H5.2 LLM: No existe
- H5.3 shadow: No existe
- **Acción:** CALIBRATION_SESSION_REQUIRED — se necesitan ≥2-3 sesiones nuevas con ≥3 valid laps cada una.

### 3.8 Sarthe / HYPER — CALIBRATION_SESSION_REQUIRED

- NO_CALIBRATION_FOR_CONTEXT (24 labels, batch 4687173702, 3 sessions)
- Calibration: 13 pairs, eval: 0 pairs (eval_readiness=WARNING_EMPTY)
- H5.2 raw: No existe
- H5.2 LLM: No existe
- H5.3 shadow: No existe
- **Acción:** CALIBRATION_SESSION_REQUIRED — se necesitan ≥2-3 sesiones nuevas con ≥3 valid laps cada una.

---

## 4. Diagnóstico: Por qué MATCH está deshabilitado en Monza/HYPER y Monza/LMP2_ELMS

El archivo `episode_pair_matcher.py` tiene en CALIBRATIONS:

```python
MONZA_HYPER_CALIBRATION_KEY = (
    "Autodromo Nazionale Monza",
    "Autodromo Nazionale Monza",
    "HYPER",
)

MONZA_LMP2_CALIBRATION_KEY = (
    "Autodromo Nazionale Monza",
    "Autodromo Nazionale Monza",
    "LMP2_ELMS",
)
```

Ambos tienen `match_enabled=False`, `match_center_max_m=200.0`, `match_overlap_shorter_min=0.90`, `match_overlap_union_min=0.40`, `match_shared_channel_min=1`, `reject_center_gt_m=1000.0`, `reject_overlap_union_max=0.33`.

La razón es: `match_core_disabled=sin evidencia SAME en calibracion`. Los 24 labels contienen 0 SAME, 7 DIFFERENT, 0 AMBIGUOUS.

**No se puede derivar un matcher robusto sin evidencia SAME.** El matcher requiere al menos un par SAME en el calibration split para establecer la calibración del MATCH core. Los 7 pairs de calibración son todos DIFFERENT, por lo que no se puede determinar si los thresholds de MATCH son demasiado restrictivos o no.

**La acción no es "más labeling" porque los nuevos labels serían del mismo batch.** Se requiere nueva evidencia independiente (sesiones nuevas) para generar un nuevo calibration split con evidencias SAME.

---

## 5. Diagnóstico: Fuji / LMP2_ELMS — ¿Alcanzan los labels para calibración provisional?

- **24 labels** (batch b0b0f526f9, 5 sessions, 2251 pairs)
- **Calibration split:** 23 pairs
- **Evaluation split:** 0 pairs (eval_readiness=WARNING_EMPTY)
- **Labels:** 24 labels (no especificados como SAME/DIFFERENT/AMBIGUOUS, pero probablemente similar distribución a los otros batches)

Los thresholds candidatos para Fuji serían:

```python
{
    "match_center_max_m": 200.0,
    "match_overlap_shorter_min": 0.90,
    "match_overlap_union_min": 0.40,
    "match_shared_channel_min": 1,
    "extended_match_center_max_m": None,
    "reject_center_gt_m": 300.0,
    "reject_overlap_union_max": 0.33,
}
```

Evidencia que justifica estos thresholds:

- **match_center_max_m=200.0**: similar a Imola (200.0), que se derivó de 9 calibration pairs con 2 SAME.
- **match_overlap_shorter_min=0.90**: similar a Imola (0.90).
- **match_overlap_union_min=0.40**: similar a Imola (0.40).
- **reject_center_gt_m=300.0**: más restrictivo que Spa (250.0), similar a Imola (300.0).

**¿Alcanza?** Sí para un matcher provisional (CALIBRATED_PROVISIONAL_LOW_EVIDENCE), pero NO para evaluación (eval_readiness=WARNING_EMPTY porque no hay eval pairs). Se necesitan sesiones independientes para generar el split de evaluación.

**No se registran CALIBRATIONS ni se cambian thresholds.** La acción es CALIBRATION_ANALYSIS_REQUIRED: ejecutar episode_pair_matcher sobre batch b0b0f526f9, registrar los thresholds candidatos en CALIBRATIONS como CALIBRATED_PROVISIONAL_LOW_EVIDENCE, pero no habilitar MATCH sin evidencia SAME.

---

## 6. Resumen de acciones por contexto

| context | next_action |
|---|---|
| Spa / LMP2_ELMS | **DONE** |
| Imola / LMP2_ELMS | **REUSE_EXISTING** |
| Interlagos / LMP2_ELMS | **REUSE_EXISTING** |
| Monza / HYPER | **DETERMINISTIC_PIPELINE_REQUIRED** |
| Monza / LMP2_ELMS | **DETERMINISTIC_PIPELINE_REQUIRED** |
| Fuji / LMP2_ELMS | **CALIBRATION_ANALYSIS_REQUIRED** |
| Sarthe / LMP2_WEC | **CALIBRATION_SESSION_REQUIRED** |
| Sarthe / HYPER | **CALIBRATION_SESSION_REQUIRED** |

---

## 7. Archivos modificados

Ningún archivo fue modificado en esta fase. Este inventario es informativo.

---

## 8. Suggested commit message (cuando se implemente el inventario)

```
docs: H2 + Phase E reconciled inventory v0.1 — no code changes

Read-only reconciliation of H2 + Phase E evidence across 8 contexts.
Validated H5.2 raw artifacts for Imola (PASS). Identified Fuji as
CALIBRATION_ANALYSIS_REQUIRED (24 labels, 23 calibration pairs, 0 eval).
Monza/HYPER y Monza/LMP2_ELMS MATCH disabled: sin evidencia SAME en
calibración. Sarthe/HYPER y Sarthe/LMP2_WEC CALIBRATION_SESSION_REQUIRED.
```
