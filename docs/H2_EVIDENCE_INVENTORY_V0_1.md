# H2 + Phase E — Inventario de evidencia real v0.1

**Fecha:** 2026-08-24
**Estado History:** 68 sesiones importadas, schema 4
**Matcher:** episode_pair_matcher.py v0.3

---

## 0. Resumen ejecutivo

**Historia actual:** 68 sesiones en History DB (schema 4), distribuidas en 14 tracks y 6 vehicle variants.

**Calibrated matchers:** 4 contextos registrados en `episode_pair_matcher.py` CALIBRATIONS:
- Spa LMP2_ELMS: `CALIBRATED_PROVISIONAL_SINGLE_CONTEXT` (72 labels)
- Imola LMP2_ELMS: `CALIBRATED_PROVISIONAL_LOW_EVIDENCE` (24 labels, MATCH core + REJECT)
- Interlagos LMP2_ELMS: `CALIBRATED_PROVISIONAL_LOW_EVIDENCE` (24 labels, MATCH core + REJECT)
- Monza HYPER: `CALIBRATED_PROVISIONAL_LOW_EVIDENCE` (24 labels, REJECT-only, MATCH disabled)
- Monza LMP2_ELMS: `CALIBRATED_PROVISIONAL_LOW_EVIDENCE` (24 labels, REJECT-only, MATCH disabled)

**Uncalibrated contexts con batches labelados:** Fuji LMP2_ELMS (24 labels), Sarthe LMP2_WEC (24 labels)

**H5.2 Phase E:** Spa raw H5.2 generado (determinista). Sarthe LMP2_WEC / Imola HYPER / Sarthe HYPER bloqueados por gates H4.

---

## 1. Inventario por contexto (track + vehicle)

### 1.1 Circuit de Spa-Francorchamps / LMP2_ELMS (CALIBRATED)

| Campo | Valor |
|---|---|
| **Contexto** | Spa-Francorchamps | LMP2_ELMS |
| **Batches** | 034f (6 sessions) |
| **Historia sessions** | #1, #2, #3, #4, #5, #6, #25, #24 |
| **Sesiones independientes** | ≥6 (P/Q/R, sessions distintas) |
| **Valid laps por sesion** | 3-13 laps |
| **H2 calibration** | PASS — 72 labels, `CALIBRATED_PROVISIONAL_SINGLE_CONTEXT` |
| **H2 evaluation** | calibration_pairs=2, evaluation_pairs=1 (batch 034f) |
| **H2 matcher status** | `CALIBRATED_PROVISIONAL_SINGLE_CONTEXT` |
| **H2 pairs total** | 5506 |
| **H4 status** | No requiere — referencia directa disponible en sesiones actuales |
| **H5.1 status** | No requiere — referencia directa disponible |
| **H5.2 raw** | GENERADO (primer raw H5.2 de Spa) |
| **H5.2 LLM** | Pendiente |
| **H5.3 shadow** | SKIPPED_NOT_APPLICABLE (sin H5.2 LLM autorizado) |
| **Track profile** | `spa_francorchamps_nomenclature.json` (v1) |
| **Gaps** | Ninguno para H2. H5.2 raw generado pero requiere validacion humana |

### 1.2 Autodromo Enzo e Dino Ferrari (Imola) / LMP2_ELMS (PROVISIONAL)

| Campo | Valor |
|---|---|
| **Contexto** | Imola | LMP2_ELMS |
| **Batches** | 5a8126df14 (18 sessions, labelado), bc05233dea (6 sessions, labelado) |
| **Historia sessions** | #9, #10, #15, #18, #19, #20, #23, #29-#34, #36, #43, #48, #50-#52, #57, #61-#65, #67 |
| **Sesiones independientes** | 18 (LMP2_ELMS) + 6 (LMP2_ELMS Monza context) |
| **Valid laps por sesion** | 1-11 laps (muchas con 1-2 laps) |
| **H2 calibration** | PROVISIONAL — 24 labels (2 SAME, 6 DIFFERENT, 1 AMBIGUOUS) |
| **H2 evaluation** | calibration_pairs=9, evaluation_pairs=1 |
| **H2 matcher status** | `CALIBRATED_PROVISIONAL_LOW_EVIDENCE` (MATCH core + REJECT) |
| **H2 pairs total** | 17523 (batch 5a8126df14) |
| **H4 status** | Requiere ≥2 sesiones same-track same-vehicle con ref lap |
| **H5.1 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.2 raw** | BLOQUEADO — H4 no puede seleccionar referencia con evidencia limitada |
| **H5.2 LLM** | Bloqueado |
| **H5.3 shadow** | SKIPPED_NOT_APPLICABLE |
| **Track profile** | `imola_nomenclature.json` (v1) |
| **Gaps** | Falta evidencia SAME en calibracion para matcher robusto. H5.2 requiere sesiones nuevas o reutilizacion de batches existentes. |

### 1.3 Autódromo José Carlos Pace (Interlagos) / LMP2_ELMS (PROVISIONAL)

| Campo | Valor |
|---|---|
| **Contexto** | Interlagos | LMP2_ELMS |
| **Batches** | 40c70a4dd3 (8 sessions, labelado) |
| **Historia sessions** | #11, #12, #22, #37, #38, #58, #59, #60 |
| **Sesiones independientes** | 8 (LMP2_ELMS) |
| **Valid laps por sesion** | 1-5 laps |
| **H2 calibration** | PROVISIONAL — 24 labels (1 SAME, 2 DIFFERENT, 1 AMBIGUOUS) |
| **H2 evaluation** | calibration_pairs=4, evaluation_pairs=5 (evaluacion READINESS=PASS) |
| **H2 matcher status** | `CALIBRATED_PROVISIONAL_LOW_EVIDENCE` (MATCH core + REJECT) |
| **H2 pairs total** | 4476 |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | Disponible |
| **H5.2 raw** | Pendiente — se puede generar si H4+H5.1 son validos |
| **H5.2 LLM** | Pendiente |
| **H5.3 shadow** | SKIPPED_NOT_APPLICABLE |
| **Track profile** | `interlagos_nomenclature_v1_0.json` |
| **Gaps** | Few independent sessions. evaluation_readiness=PASS pero calibration_only=4 pairs. |

### 1.4 Autodromo Nazionale Monza / HYPER (REJECT-ONLY)

| Campo | Valor |
|---|---|
| **Contexto** | Monza | HYPER |
| **Batches** | aa020d588d (6 sessions, labelado), 636633bd5e |
| **Historia sessions** | #13, #14, #16, #17, #21, #41 |
| **Sesiones independientes** | 6 (HYPER) |
| **Valid laps por sesion** | 1-4 laps |
| **H2 calibration** | REJECT-ONLY — 24 labels (0 SAME, 7 DIFFERENT, 0 AMBIGUOUS) |
| **H2 evaluation** | calibration_pairs=7, evaluation_pairs=0 |
| **H2 matcher status** | `CALIBRATED_PROVISIONAL_LOW_EVIDENCE` (REJECT >1000m, MATCH disabled) |
| **H2 pairs total** | 2236 (batch aa020d588d) |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | Disponible |
| **H5.2 raw** | Pendiente |
| **H5.2 LLM** | Pendiente |
| **H5.3 shadow** | SKIPPED_NOT_APPLICABLE |
| **Track profile** | `monza_nomenclature.json` |
| **Gaps** | 0 SAME labels en calibracion. Se necesitan sesiones nuevas para obtener labels SAME. |

### 1.5 Autodromo Nazionale Monza / LMP2_ELMS (REJECT-ONLY)

| Campo | Valor |
|---|---|
| **Contexto** | Monza | LMP2_ELMS |
| **Batches** | bc05233dea (6 sessions, labelado), d4379744c6 |
| **Historia sessions** | #15, #18, #19, #20, #23, #40 |
| **Sesiones independientes** | 6 (LMP2_ELMS) |
| **Valid laps por sesion** | 1-11 laps |
| **H2 calibration** | REJECT-ONLY — 24 labels (0 SAME, 7 DIFFERENT, 0 AMBIGUOUS) |
| **H2 evaluation** | calibration_pairs=7, evaluation_pairs=0 |
| **H2 matcher status** | `CALIBRATED_PROVISIONAL_LOW_EVIDENCE` (REJECT >1000m, MATCH disabled) |
| **H2 pairs total** | 1452 (batch bc05233dea) |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | Disponible |
| **H5.2 raw** | Pendiente |
| **H5.2 LLM** | Pendiente |
| **H5.3 shadow** | SKIPPED_NOT_APPLICABLE |
| **Track profile** | `monza_nomenclature.json` |
| **Gaps** | 0 SAME labels en calibracion. H5.2 requiere sesiones nuevas o reutilizacion. |

### 1.6 Fuji Speedway / LMP2_ELMS (UNCALIBRATED)

| Campo | Valor |
|---|---|
| **Contexto** | Fuji | LMP2_ELMS |
| **Batches** | b0b0f526f9 (5 sessions, labelado) |
| **Historia sessions** | #7, #8, #35, #39, #44, #56 |
| **Sesiones independientes** | 5 (LMP2_ELMS) + 1 (HYPER) |
| **Valid laps por sesion** | 2-8 laps |
| **H2 calibration** | LABELADO pero NO CALIBRADO — 24 labels |
| **H2 evaluation** | calibration_pairs=23, evaluation_pairs=0 |
| **H2 matcher status** | NO_CALIBRATION_FOR_CONTEXT |
| **H2 pairs total** | 2251 |
| **H4 status** | Disponible para sesiones con ≥2 valid laps |
| **H5.1 status** | Disponible |
| **H5.2 raw** | Pendiente |
| **H5.2 LLM** | Pendiente |
| **H5.3 shadow** | SKIPPED_NOT_APPLICABLE |
| **Track profile** | `fuji_speedway_nomenclature.json` |
| **Gaps** | Sin calibracion matcher. Falta al menos un contexto independiente para particion de evaluacion. |

### 1.7 Circuit de la Sarthe / LMP2_WEC (UNCALIBRATED)

| Campo | Valor |
|---|---|
| **Contexto** | Sarthe | LMP2_WEC |
| **Batches** | 2c500b2970 (5 sessions, labelado) |
| **Historia sessions** | #26, #27, #28, #30, #31 |
| **Sesiones independientes** | 5 (LMP2_WEC) |
| **Valid laps por sesion** | 1-3 laps |
| **H2 calibration** | LABELADO pero NO CALIBRADO — 24 labels |
| **H2 evaluation** | calibration_pairs=13, evaluation_pairs=0 |
| **H2 matcher status** | NO_CALIBRATION_FOR_CONTEXT |
| **H2 pairs total** | 899 |
| **H4 status** | Requiere sesiones con ≥2 valid laps y ref lap |
| **H5.1 status** | Limitado — muchas sesiones con 1 valid lap |
| **H5.2 raw** | BLOQUEADO — H4 reference lap no disponible para la mayoria de sesiones |
| **H5.2 LLM** | Bloqueado |
| **H5.3 shadow** | SKIPPED_NOT_APPLICABLE |
| **Track profile** | `la_sarthe_profile_v0_1.json` (VALIDATED_MULTI_SESSION) |
| **Gaps** | Sesiones con muy pocos valid laps. Se necesitan ≥2-3 sesiones nuevas con ≥3 valid laps cada una. |

### 1.8 Circuit de la Sarthe / HYPER (BLOCKED)

| Campo | Valor |
|---|---|
| **Contexto** | Sarthe | HYPER |
| **Batches** | 4687173702 (3 sessions, BLOCKED) |
| **Historia sessions** | #53, #54, #67 |
| **Sesiones independientes** | 3 (HYPER) |
| **Valid laps por sesion** | 1 lap (todas) |
| **H2 calibration** | BLOCKED — no cross-session episode pairs (insuficientes sesiones) |
| **H2 evaluation** | N/A |
| **H2 matcher status** | NO_CALIBRATION_FOR_CONTEXT |
| **H2 pairs total** | 0 |
| **H4 status** | BLOQUEADO — ninguna sesion con ≥2 valid laps |
| **H5.1 status** | BLOQUEADO — sin ref lap |
| **H5.2 raw** | BLOQUEADO — sin H4 |
| **H5.2 LLM** | Bloqueado |
| **H5.3 shadow** | SKIPPED_NOT_APPLICABLE |
| **Track profile** | `la_sarthe_profile_v0_1.json` (VALIDATED_MULTI_SESSION) |
| **Gaps** | Critico: todas las sesiones tienen 1 valid lap. Se requieren ≥2-3 sesiones nuevas con ≥3 valid laps cada una. |

### 1.9 Otros contextos sin calibracion

| Contexto | Sessions | Valid laps | H2 | H4 | H5.2 |
|---|---|---|---|---|---|
| Daytona / LMP2_ELMS | #46 (1 session) | 2 laps | BLOCKED | Pendiente | Pendiente |
| Paul Ricard / LMP2_ELMS | #47 (1 session) | 1 lap | BLOCKED | BLOQUEADO | BLOQUEADO |
| Laguna Seca / GT3 | #55 (1 session) | 1 lap | BLOCKED | BLOQUEADO | BLOQUEADO |
| Spa / LMP3 | #68 (1 session) | 1 lap | BLOCKED | BLOQUEADO | BLOQUEADO |
| Imola / GT3 | #66 (1 session) | 1 lap | BLOCKED | BLOQUEADO | BLOQUEADO |

---

## 2. Tabla resumen de estado

| Contexto | Sessions | Usable | H2 Status | Eval Split | H4 Status | H5.2 Status | Missing | Next Action |
|---|---|---|---|---|---|---|---|---|
| Spa / LMP2_ELMS | 6+ | 6 | CALIBRATED | PASS | READY | GENERATED | Ninguno | H5.2 LLM validation |
| Imola / LMP2_ELMS | 18+ | 6+ | PROVISIONAL | PASS | READY | BLOQUEADO | evidencia SAME matcher | Reutilizar batch para H5.2 |
| Interlagos / LMP2_ELMS | 8 | 8 | PROVISIONAL | PASS | READY | PENDING | — | Generar H5.2 raw |
| Monza / HYPER | 6 | 6 | REJECT-ONLY | FAIL | READY | PENDING | 0 SAME labels | NUEVA TELEMETRIA |
| Monza / LMP2_ELMS | 6 | 6 | REJECT-ONLY | FAIL | READY | PENDING | 0 SAME labels | NUEVA TELEMETRIA |
| Fuji / LMP2_ELMS | 5+ | 5 | UNCALIBRATED | FAIL | READY | PENDING | calibration matcher | NUEVA CALIBRACION |
| Sarthe / LMP2_WEC | 5 | 2 | UNCALIBRATED | FAIL | BLOCKED | BLOQUEADO | sesiones con ≥3 laps | NUEVA TELEMETRIA |
| Sarthe / HYPER | 3 | 0 | BLOCKED | FAIL | BLOQUEADO | BLOQUEADO | sesiones con ≥3 laps | NUEVA TELEMETRIA |

---

## 3. Reutilizacion de datos existentes

### 3.1 Interlagos / LMP2_ELMS — H5.2 puede generarse sin nueva telemetria

- 8 sesiones en History, 8 LMP2_ELMS
- Sessions #11 (5 valid laps), #12 (5 valid laps), #38 (5 valid laps) son usables
- H4 puede seleccionar referencia sin problema
- H5.2 raw puede generarse para Interlagos inmediatamente

### 3.2 Imola / LMP2_ELMS — H5.2 puede generarse sin nueva telemetria

- 18 sesiones en History, 18 LMP2_ELMS
- Sessions #19 (11 valid laps), #10 (6 valid laps) son usables
- H4 puede seleccionar referencia sin problema
- H5.2 raw puede generarse para Imola inmediatamente

### 3.3 Spa / LMP2_ELMS — H5.2 raw ya generado

- Ya existe primer H5.2 raw de Spa. Solo falta H5.2 LLM validation.

---

## 4. Campaña minima recomendada

### Prioridad 1 — Desbloquear H5.2 para Interlagos + Imola (sin nueva telemetria)

**Accion:** Ejecutar pipeline H4+H5.2 determinista para Interlagos + Imola usando sesiones existentes.

**Sesiones Interlagos para H5.2:**
- #11: LMP2_ELMS, 5 valid laps, ref lap=7
- #12: LMP2_ELMS, 5 valid laps, ref lap=13
- #38: LMP2_ELMS, 5 valid laps, ref lap=6

**Sesiones Imola para H5.2:**
- #19: LMP2_ELMS, 11 valid laps, ref lap=10
- #10: LMP2_ELMS, 6 valid laps, ref lap=4

**Impacto:** Desbloquea H5.2 para 2 contexts simultaneamente. Sin costo de telemetria nueva.

### Prioridad 2 — Fuji matcher calibration (sin nueva telemetria)

**Accion:** Ejecutar episode_pair_matcher sobre batch b0b0f526f9 y registrar thresholds en CALIBRATIONS.

**Impacto:** Fuji pasa de NO_CALIBRATION para CALIBRATED_PROVISIONAL_LOW_EVIDENCE.

### Prioridad 3 — NUEVA TELEMETRIA para desbloquear objetivos

**CALIBRATION SESSION REQUIRED:**

| Pista | Vehiculo/Contexto | Sesiones minimas | Valid laps/sesion | Gap que desbloquea | DuckDB a devolver |
|---|---|---|---|---|---|
| Sarthe | LMP2_WEC | 2-3 | ≥3 cada una | H2 eval + H4 + H5.2 | `Circuit de la Sarthe_P_YYYY-MM-DDTHH_MM_SSZ.duckdb` |
| Sarthe | HYPER | 2-3 | ≥3 cada una | H2 + H4 + H5.2 | `Circuit de la Sarthe_P_YYYY-MM-DDTHH_MM_SSZ.duckdb` |
| Monza | HYPER | ≥2 | ≥3 cada una | H2 eval (SAME evidence) | `Autodromo Nazionale Monza_P_YYYY-MM-DDTHH_MM_SSZ.duckdb` |
| Monza | LMP2_ELMS | ≥2 | ≥3 cada una | H2 eval (SAME evidence) | `Autodromo Nazionale Monza_P_YYYY-MM-DDTHH_MM_SSZ.duckdb` |
| Fuji | LMP2_ELMS | 1+ | ≥2 cada una | H2 eval split | `Fuji Speedway_P_YYYY-MM-DDTHH_MM_SSZ.duckdb` |

---

## 5. Tests/comandos ejecutados

```powershell
python session_history.py list     # 68 sessions confirmed
python session_history.py stats    # schema 4
dir telemetria /b                  # 70+ duckdb files
dir calibration_batches /b         # 11 batch directories
# Read all BATCH_STATUS.json files
# Read episode_pair_matcher.py CALIBRATIONS registry
```

---

## 6. Archivos modificados

Ningun archivo fue modificado en esta fase. Este inventario es informativo.

---

## 7. Suggested commit message (cuando se implemente el inventario)

```
docs: H2 + Phase E evidence inventory v0.1 — 68 sessions, 5 calibrated, 3 pending

Inventory of all available telemetry and history data across 14 tracks
and 6 vehicle variants. 4 H2 matchers calibrated (Spa/Imola/Interlagos/Monza).
H5.2 raw generated for Spa; Interlagos + Imola ready for immediate H5.2
pipeline execution without new telemetry. Sarthe/WEC and Sarthe/HYPER
require new sessions with >=3 valid laps each.
```
