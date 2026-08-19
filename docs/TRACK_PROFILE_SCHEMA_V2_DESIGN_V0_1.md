# Track Profile Schema v2 Design v0.1

**Fecha:** 2026-08-19
**Estado:** DESIGN_ONLY — NO IMPLEMENT
**Golden profiles:** Fuji v0.3, Imola v0.3, Monza v0.3

---

## DECISIÓN ACTUAL

| Parámetro | Valor |
|-----------|-------|
| **IMPLEMENT_NOW** | **NO** |
| **DECISIÓN** | DESIGN_SCHEMA_V2_BUT_DO_NOT_IMPLEMENT |
| **MOTIVO** | No hay caso de uso claro que justifique implementación inmediata; H5.2 ya funciona con turn boundaries; el valor de segments es alto para coaching pero medio para H5.2 |

---

## 1. SEMÁNTICA

### 1.1 Qué ES un `straight`

```
straight = región de baja curvatura entre turns consecutivos donde:
  a) No se detecta un peak de curvatura separado que justifique un turn
  b) La evidencia de curvatura es monótona o subumbral (peak < threshold)
  c) La distancia entre turn end y next turn start > umbral (≥ 100 m)
  d) La evidencia proviene de curvature trajectory analysis
```

**Características:**
- `type = "straight"`
- Cubre la región entre el `end_m` de un turn y el `start_m` del siguiente turn
- `related_turn_ids` identifica los turns adyacentes
- Documentado actualmente en `geometric_notes[].type = "gap_explanation"` con `classification = "straight_real_track_feature"`

**Ejemplos:**
- Monza Lesmo 2→Ascari: 940 m (straight principal de Monza)
- Monza Ascari→Alboreto: 835 m (straight de Parabolica)
- Imola Gresini→Turn 16: 430 m (straight más largo de Imola)

### 1.2 Qué ES un `transition`

```
transition = región corta entre complejos de turns donde:
  a) La distancia es < umbral de straight (< 100 m)
  b) Representa una zona de desaceleración/aceleración entre complejos
  c) No se detecta un apex independiente
  d) La curvatura puede ser monótona o con pequeños picos subumbrales
```

**Características:**
- `type = "transition"`
- Más corta que un straight típico
- Documentada en `geometric_notes[].type = "gap_explanation"` con `classification = "transition_zone"`

**Ejemplos:**
- Fuji 100R→Hairpin: 72 m (deceleration zone)
- Fuji GR Supra→Panasonic: 84 m (left-to-right direction change)

### 1.3 Qué NO debe ser un `segment`

| Tipo | Por qué NO es segment | Representación actual |
|------|----------------------|-----------------------|
| **Turn** | Ya cubierto por `turns` | `turns[].start_m → turns[].end_m` |
| **Complex** | Agrupación semántica de turns, no región | `turns[].group` |
| **ignored_geometric_feature** | Es un punto de curvatura, no una región | `ignored_geometric_features_m[].center_m` |
| **Low-curvature turn** | Turn deliberado bajo threshold | `manual_low_curvature_turns[]` |
| **Unknown** | No debe haber regiones unknown en v2 | — |
| **Braking zone** | Derivable implícitamente del inicio del turn; no explícita | `turns[].start_m` |
| **Exit zone** | Derivable implícitamente del final del turn; no explícita | `turns[].end_m` |
| **Boundary offset** | Gap < 50 m; no es región modelable | `geometric_notes[].acceptable_boundary_offset` |
| **Touching boundary** | Gap = 0 m; no hay región entre turns | `geometric_notes[].touching_boundary` |
| **Low-curvature continuation** | Es un turn, no un gap entre turns | `manual_low_curvature_turns[]` |

### 1.4 Relación con turns/complexes/ignored_geometric_features

| Entidad | v1 | v2 | Intersección |
|---------|----|----|-------------|
| **turns** | `[start_m, end_m]` | No cambia | Disjunta de segments |
| **segments** | No existe | `[start_m, end_m]` | Disjunta de turns |
| **complexes** | `group` field | No cambia | Los complexes agrupan turns; segments están entre complexes |
| **ignored_geometric_features** | `center_m` point | No cambia | Los segments documentan la región; el feature es un punto dentro de la región |

**Invarianza de partición (CORREGIDO — selective, no full):**
```
union(turns, segments) ⊆ [0, lap_length_m]   (no necesariamente igual)
intersection(turns, segments) = empty
uncovered_regions = [0, lap_length_m] \ union(turns, segments)   (válidos)
```

### 1.5 Relación con `ignored_geometric_features_m`

Los `ignored_geometric_features_m` son **puntos de curvatura ignorados** (no regiones). En v2, estos puntos pueden caer dentro de un segment (ej. un ignored feature puede estar en medio de un straight). No se reinterpreta como región.

---

## 2. COVERAGE

### 2.1 COVERAGE FINAL: SELECTIVE / EVIDENCE-DRIVEN

**Definición formal:**

```
SELECTIVE COVERAGE — segments son evidence-driven, no full-coverage obligatorios:
  - segments cubren SOLO regiones con evidencia suficiente (curvature trajectory analysis)
  - segments NO están obligados a cubrir todo el lap
  - segments NO están obligados a cubrir todos los gaps entre turns
  - uncovered regions son válidas (no son error)
  - ausencia de segment NO es error
  - uncovered regions se documentan en geometric_notes como "gap no_modelled" (opcional)
  - uncovered regions pueden ser:
    a) boundary_offset aceptable (0-50m, ya documentado)
    b) zona de baja relevancia estratégica (no hay braking/acceleration significativo)
    c) zona donde los turns se solapan (overlap > 0, cubre la región)
    d) zona donde no hay evidencia de curvatura suficiente para modelar
```

### 2.2 Full coverage vs selective coverage

| Métrica | Full (A) | Selective (B) |
|---------|----------|---------------|
| **Duplicación** | Alta: cada región es turn O segment | Ninguna: cada región es turn O segment |
| **Complejidad** | Alta: hay que decidir qué cubre qué | Baja: turns cubren turns, segments cubren lo demás |
| **Overlap checking** | Requiere verificar turn vs segment | Requiere verificar turn vs segment (igual) |
| **Beneficio funcional** | Medio: más redundancy | Alto: explicit straight/transition identification |

**Veredicto: B (Selective / Evidence-driven)**

### 2.3 Ejemplo de partición (Monza v2 hipotético)

```
turns (34.4% del lap):
  [890, 950]  T1 Rettifilo
  [950, 1020] T2 Rettifilo
  [1180, 1760] T3 Curva Grande
  [2098, 2170] T4 Roggia
  [2170, 2230] T5 Roggia
  [2460, 2660] T6 Lesmo 1
  [2815, 2945] T7 Lesmo 2
  [3885, 3990] T8 Ascari
  [3990, 4105] T9 Ascari
  [4105, 4225] T10 Ascari
  [5060, 5535] T11 Alboreto

segments (evidence-driven, no full):
  [1020, 1180]    seg_1 straight T2→T3 (160 m)
  [1760, 2098]    seg_2 straight T3→T4 (338 m)
  [2230, 2460]    seg_3 straight T5→T6 (230 m)
  [2660, 2815]    seg_4 straight T6→T7 (155 m)
  [2945, 3885]    seg_5 straight T7→T8 (940 m)
  [4225, 5060]    seg_6 straight T10→T11 (835 m)

uncovered (no evidence-driven segments para estas regiones):
  [0, 890]        — zona antes de T1 (no modelado como segment)
  [5535, lap]     — zona después de T11 (no modelado como segment)
```

### 2.4 Ejemplo de partición (Fuji v2 hipotético)

```
turns (56.0% del lap):
  [718, 814]   T1 TGR Corner
  [830, 1050]  T2 Turn 2
  [1256, 1388] T3 Coca-Cola Corner
  [1482, 1701] T4 100R
  [1701, 1882] T5 100R
  [1954, 2100] T6 Hairpin
  [2100, 2210] T7 Turn 7
  [2220, 2470] T8 Turn 8
  [2470, 2780] T9 300R
  [2800, 2872] T10 Dunlop Corner
  [2872, 2950] T11 Dunlop
  [2950, 3078] T12 Dunlop
  [3078, 3214] T13 13th Corner
  [3218, 3352] T14 Turn 14
  [3352, 3458] T15 GR Supra Corner
  [3542, 3760] T16 Panasonic Corner

segments (evidence-driven, no full):
  [1050, 1256]    seg_1 straight T2→T3 (206 m)
  [1388, 1482]    seg_2 transition T3→T4 (94 m)
  [1882, 1954]    seg_3 transition T5→T6 (72 m)
  [3458, 3542]    seg_4 transition T15→T16 (84 m)

uncovered (no evidence-driven segments):
  [0, 718]        — zona antes de T1
  [5726, 4526]    — zona después de T16 (wraparound)
  Minor gaps (0-20 m) entre turns: no modelados (acceptable_boundary_offset)
```

---

## 3. INVARIANTS

### 3.1 Invariants corregidos para SELECTIVE COVERAGE

```
CORRECTED invariants for selective/evidence-driven coverage:
  1. segments son OPTIONAL — un perfil v2 puede tener 0 segments
  2. start_distance_m < end_distance_m
  3. start_distance_m >= 0
  4. end_distance_m <= lap_length_m
  5. segment_id único en todo el perfil
  6. segments ordenados por start_distance_m
  7. segments disjuntos (no se solapan entre sí)
  8. segments disjuntos de turns (no se solapan con turns)
  9. related_turn_ids no vacío
  10. type ∈ {"straight", "transition"}
  11. confidence ∈ {"low", "medium", "high"}
  12. provenance derivable de geometric_notes si v1 existía
  13. coverage es evidence-driven — cada segment debe tener evidencia
  14. uncovered regions son válidas — no hay error si no hay segment

ELIMINADO: "La unión de turns ∪ segments cubre todo el lap (full coverage)"
RAZÓN: Implica full coverage obligatorio. En realidad: union(turns, segments) ⊆ [0, lap_length_m]
```

### 3.2 Invariants de ordering (CORREGIDO)

```
ordering (CORREGIDO — sin full coverage):
  1. turns ordenados por start_m ascending
  2. segments ordenados por start_m ascending
  3. turns ∪ segments ordenados por start_m ascending combinados
  4. Para cada punto p del lap, pertenece a:
     - un turn [start_m, end_m], O
     - un segment [start_m, end_m], O
     - una uncovered region [0, lap_length_m] \ union(turns, segments)
  5. No hay solapamientos entre turns consecutivos (v1)
  6. No hay solapamientos entre segments consecutivos (v2)

ELIMINADO: "Para cada punto p del lap, pertenece a EXACTAMENTE una región"
RAZÓN: Implica full coverage. En realidad: puntos en uncovered regions no pertenecen a turn ni segment
ELIMINADO: "segment.start_distance_m = prev_turn.end_distance_m (si no hay gap)"
RAZÓN: Asume full coverage. En realidad: puede haber gaps entre segment y turn
ELIMINADO: "segment.end_distance_m = next_turn.start_distance_m (si no hay gap)"
RAZÓN: Asume full coverage. En realidad: puede haber gaps entre segment y turn
```

### 3.3 Invariants de solapamiento (overlap rules)

| Regla | Descripción |
|-------|-------------|
| **Turn vs turn** | `turns[i].end_m <= turns[i+1].start_m` (disjuntos) |
| **Segment vs segment** | `segments[i].end_m <= segments[i+1].start_m` (disjuntos) |
| **Turn vs segment** | `turn.end_m <= segment.start_m` O `segment.end_m <= turn.start_m` (disjuntos) |
| **Turn vs segment interaction** | Si un segment está entre dos turns, su `start_m = turn_N.end_m` y su `end_m = turn_N+1.start_m` |

### 3.4 Wraparound start/finish

```
wraparound:
  1. El lap comienza en 0 y termina en lap_length_m
  2. El último turn del lap (ej. T11 Monza) termina en 5535 m
  3. El primer turn del lap (ej. T1 Monza) comienza en 890 m
  4. Si el perfil tiene lap wrapping, el segmento entre el último turn y el primero
     se representa como un segment con start_m > end_m (zona wraparound)
  5. En v2 hipotético, el segmento wraparound sería:
     [turn_last.end_m, lap_length_m] ∪ [0, turn_first.start_m]
```

**Nota:** Ninguno de los 3 golden profiles tiene wraparound. Este invariant es para futuros perfiles que necesiten wrapping.

### 3.5 Layout hard context

```
layout_hard_context:
  1. El mismo track + layout NO puede tener dos schemas diferentes (v1 vs v2)
  2. El mismo perfil puede tener v1 Y v2 coexistentes (no se migran)
  3. El loader de v2 verifica que layout y track no cambien
  4. El validator v0.2 valida ambos v1 y v2 (no se reemplaza)
```

---

## 4. PRIORITY RULE CORREGIDO

### 4.1 Categorías de entidades

**A) Primary spatial entities** (contienen rango físico, se usan para resolve physical location):

| Entidad | Representa | Usado para location? |
|---------|-----------|----------------------|
| **turns** | Región de alta curvatura | SÍ — primer nivel de prioridad |
| **segments** | Región de baja curvatura | SÍ — segundo nivel de prioridad |

**B) Geometric annotations** (son metadata/evidence, NO compiten en location priority):

| Entidad | Representa | Usado para location? |
|---------|-----------|----------------------|
| **ignored_geometric_features_m** | Punto de curvatura ignorado | NO — es un punto, no una región |
| **manual_low_curvature_turns** | Turn deliberado bajo umbral | NO — ya está representado por turns |

### 4.2 Location priority corrected

```
CORRECTED location priority (v2):

A) PRIMARY SPATIAL ENTITIES:
   1. turn (si d ∈ turn.start_m → turn.end_m)
   2. segment (si d ∈ segment.start_m → segment.end_m)

B) GEOMETRIC ANNOTATIONS (no compiten en priority):
   3. ignored_geometric_features[].center_m (si d ≈ center_m)
      — NO es un contenedor de location; es evidencia de curvatura
   4. manual_low_curvature_turn[].turn_id
      — NO es un contenedor de location; es annotation de confianza

REGLA CORREGIDA: turn > segment >> ignored_feature, manual_low_curvature

Las entidades de tipo B son metadata/evidence annotations.
No representan rangos físicos de location.
No compiten en la priority de location.
```

### 4.3 Physical location resolution

| Escenario | Resolución |
|-----------|-----------|
| **d ∈ turn A Y d ∈ segment B** | Prioridad: turn A |
| **d ∈ turn A Y d ∈ turn B** | Error: turns no deben solaparse |
| **d ∈ segment A Y d ∈ segment B** | Error: segments no deben solaparse |
| **d ∈ ignored_feature center** | Metadata — no es location |
| **d ∈ manual_low_curvature turn** | Metadata — no es location |
| **d ∉ turn Y d ∉ segment** | Uncovered region — no hay entity |

---

## 5. BACKWARD COMPATIBILITY

### 5.1 v1 sigue válido

```
v1_valid = true:
  - Schema v1 con turns = válido en todos los casos
  - Loader futuro puede leer v1 (ignora segments si ausentes)
  - Validator v0.2 valida v1 sin segments
  - H5.2 localization funciona con v1 (usando turns como boundaries)
```

### 5.2 v2 loader futuro

```
v2_loader:
  - Si profile.schema_version == 1: usar v1 path (no segments)
  - Si profile.schema_version == 2: validar + usar v2 path (segments + turns)
  - Si profile.schema_version > 2: NO SUPPORTED
  - Si profile.schema_version NO es int: ERROR
```

### 5.3 No migración automática

```
no_auto_migrate:
  - Los perfiles v1 NO se migran a v2
  - Cada pista tiene su propio ciclo de vida: v1 → v2 cuando sea necesario
  - No se convierten turns en segments automáticamente
  - No se reescriben perfiles existentes
```

### 5.4 H5.2 localization debe seguir funcionando

```
h52_compatibility:
  - find_validated_track_profile() filtra por status (no por schema_version)
  - profile_boundaries() devuelve start_m/end_m de turns (v1)
  - Si schema_version == 2, profile_boundaries() devuelve start_m/end_m de turns + segments
  - localize_trend_zones() usa profile_boundaries() como cut points
  - La unión de turns ∪ segments ⊆ [0, lap_length_m] (puede dejar uncovered regions)
```

---

## 6. SEGMENT TYPES COUNT

### 6.1 Gap analysis → segment mapping

Del gap analysis (TRACK_PROFILE_SCHEMA_GAP_ANALYSIS_V0_1.md, §2.3):

| Classification | Count | Tracks | ¿Califica como segment? |
|----------------|-------|--------|-------------------------|
| straight_real_track_feature | 11 | Monza (6), Imola (5), Fuji (1) | **SÍ** — gap ≥ umbral, evidencia clara |
| straight_short_real_track_feature | 1 | Fuji (1) | **NO** — 94 m < umbral de straight (100 m); clasificado como transition |
| transition_zone | 2 | Fuji (2) | **SÍ** — ya es transition |
| acceptable_boundary_offsets | 11 | Imola (6), Fuji (5) | **NO** — gaps < 50 m no son regiones modelables |
| touching_boundary | 4 | Imola (2), Fuji (2) | **NO** — gap = 0 m |
| low_curvature_continuation | 1 | Fuji (1) | **NO** — es un turn, no un gap entre turns |

### 6.2 Por qué 11 straights en v2 (no 12)

El gap analysis reportó **12 straights** (11 `straight_real_track_feature` + 1 `straight_short_real_track_feature`).

El schema v2 tiene **11 straights** porque:

| Segmento | Distancia | Clasificación en gap analysis | Clasificación en v2 |
|----------|-----------|-------------------------------|----------------------|
| Monza T2→T3 | 160 m | straight_real | straight |
| Monza T3→T4 | 338 m | straight_real | straight |
| Monza T5→T6 | 230 m | straight_real | straight |
| Monza T6→T7 | 155 m | straight_real | straight |
| Monza T7→T8 | 940 m | straight_real | straight |
| Monza T10→T11 | 835 m | straight_real | straight |
| Imola T4→T5 | 280 m | straight_real | straight |
| Imola T6→T7 | 170 m | straight_real | straight |
| Imola T7→T8 | 230 m | straight_real | straight |
| Imola T13→T14 | 310 m | straight_real | straight |
| Imola T15→T16 | 430 m | straight_real | straight |
| Fuji T2→T3 | 206 m | straight_real | straight |
| Fuji T3→T4 | 94 m | straight_short_real | **NO** — < 100 m threshold |

**La regla de umbral es:**

```
umbral_straight_min_m = 100
umbral_transition_max_m = 100

straight: gap_m > umbral_straight_min_m AND curvature evidence clear
transition: gap_m < umbral_transition_max_m AND transition entre complejos
boundary_offset: gap_m < 50 m (acceptable boundary)
touching_boundary: gap_m == 0 m
```

El Fuji T3→T4 (94 m) es **< 100 m** → no califica como straight → califica como **transition** (si evidencia lo soporta).

### 6.3 ¿Qué NO se convierte en segment?

| Tipo | Razón | Ejemplo |
|------|-------|---------|
| **boundary_offsets** (11) | Gap < 50 m; es acceptable_boundary, no región modelable | Imola T8 (50 m), Fuji T7 (10 m) |
| **touching_boundary** (4) | Gap = 0 m; no hay región entre turns | Imola T2, Fuji T14 |
| **low_curvature_continuation** (1) | Es un turn, no un gap entre turns | Fuji T7 |

---

## 7. EJEMPLOS V2 HIPOTÉTICOS

### 7.1 Ejemplo: Monza straight T7→T8 (~940 m)

```json
{
  "schema_version": 2,
  "profile_id": "monza-lmu-f1-11turn-v0.4",
  "status": "VALIDATED_MULTI_SESSION",
  "track": "Autodromo Nazionale Monza",
  "layout": "Autodromo Nazionale Monza",
  "turns": [ /* identico a v0.3 — no cambiar */ ],
  "segments": [
    {
      "segment_id": "monza_seg_lesmo2_to_ascari",
      "type": "straight",
      "start_distance_m": 2945.0,
      "end_distance_m": 3885.0,
      "related_turn_ids": ["T7", "T8"],
      "confidence": "high",
      "provenance": "geometric_notes.note_5.gap_t7_to_t8",
      "evidence": {
        "peak_curvature_rad_per_m": 0.0010,
        "intermediate_peak_detected": false,
        "curvature_direction_change": "right_to_left",
        "source": "calibration_session + independent_validation"
      }
    }
  ],
  "display_policy": { /* identico a v0.3 */ },
  "geometric_notes": { /* identico a v0.3 — no cambiar */ }
}
```

### 7.2 Ejemplo: Imola straight Gresini→Turn 16 (~430 m)

```json
{
  "schema_version": 2,
  "profile_id": "imola-lmu-19turn-v0.4",
  "status": "VALIDATED_MULTI_SESSION",
  "track": "Autodromo Enzo e Dino Ferrari",
  "layout": "Autodromo Enzo e Dino Ferrari",
  "turns": [ /* identico a v0.3 — no cambiar */ ],
  "segments": [
    {
      "segment_id": "imola_seg_gresini_to_turn16",
      "type": "straight",
      "start_distance_m": 3430.0,
      "end_distance_m": 3860.0,
      "related_turn_ids": ["T15", "T16"],
      "confidence": "high",
      "provenance": "geometric_notes.note_5.gap_t15_to_t16",
      "evidence": {
        "peak_curvature_rad_per_m": 0.0036,
        "intermediate_peak_detected": false,
        "curvature_direction_change": "left_to_right",
        "source": "calibration_session + independent_validation"
      }
    }
  ],
  "display_policy": { /* identico a v0.3 */ },
  "geometric_notes": { /* identico a v0.3 — no cambiar */ }
}
```

### 7.3 Ejemplo: Fuji transition 100R→Hairpin (72 m)

```json
{
  "schema_version": 2,
  "profile_id": "fuji-speedway-lmu-wec16-v0.4",
  "status": "VALIDATED_MULTI_SESSION",
  "track": "Fuji Speedway",
  "layout": "Fuji Speedway",
  "turns": [ /* identico a v0.3 — no cambiar */ ],
  "segments": [
    {
      "segment_id": "fuji_seg_100r_to_hairpin",
      "type": "transition",
      "start_distance_m": 1882.0,
      "end_distance_m": 1954.0,
      "related_turn_ids": ["T5", "T6"],
      "confidence": "medium",
      "provenance": "geometric_notes.note_3.gap_t5_to_t6",
      "evidence": {
        "peak_curvature_rad_per_m": 0.0012,
        "intermediate_peak_detected": false,
        "curvature_direction_change": "right_to_left",
        "source": "calibration_session + independent_validation"
      }
    }
  ],
  "display_policy": { /* identico a v0.3 */ },
  "geometric_notes": { /* identico a v0.3 — no cambiar */ }
}
```

---

## 8. MIGRATION RISKS

### 8.1 Riesgos si se implementa v2 hoy

| # | Riesgo | Descripción | Severidad |
|---|--------|-------------|-----------|
| **1** | **Parsers existentes leen v2** | Los parsers actuales asumen schema v1; v2 agrega `segments` como campo desconocido | MEDIA |
| **2** | **H5.2 localization cambia** | `profile_boundaries()` ahora incluye segments; el split por boundaries cambia | MEDIA |
| **3** | **Validator v0.1 no valida v2** | El validator actual no verifica invariants de segments (disjuntos, gaps) | BAJA |
| **4** | **Confusión de IDs** | Si `segment_id` usa formato similar a `turn.id`, puede haber ambigüedad | BAJA |
| **5** | **Overlapping turns** | Si turns existentes tienen overlaps accidentales, la partición breaks | BAJA |
| **6** | **Layout hard context** | Si un perfil tiene v1 y v2 coexistentes, `find_validated_track_profile()` debe elegir | MEDIA |
| **7** | **H5.3 historical coaching** | Si H5.3 requiere explicit segments, el loader de v2 debe conocer el schema | BAJA |

### 8.2 Mitigación de riesgos

| Riesgo | Mitigación |
|--------|-----------|
| **Parsers leen v2** | `schema_version` distingue v1 de v2; parsers existentes ignoran campo desconocido |
| **H5.2 cambia** | `profile_boundaries()` en v2 incluye segments; el split por boundaries es igual |
| **Validator no valida v2** | Validator v0.2 valida v2; v0.1 sigue válido |
| **Confusión de IDs** | `segment_id` usa prefijo `seg_`; `turn_id` usa `T1`, `T2` |
| **Overlapping turns** | Validator v0.1 ya detecta overlaps; v2 los hereda |
| **Layout hard context** | Loader futuro elige por track+layout exacto; si hay v1 y v2, ambos existen |
| **H5.3** | Si H5.3 requiere segments, el loader de v2 debe conocer el schema; v1 sigue sin segments |

---

## 9. PROMOTION GATE

### 9.1 Condiciones antes de IMPLEMENTAR v2

| Condición | Estado | Descripción |
|-----------|--------|-------------|
| **C1: Mínimo de golden profiles** | PENDIENTE | ≥3 perfiles golden con segments diseñados (actualmente 0) |
| **C2: Evidence requirements** | PENDIENTE | Cada segment debe tener evidencia de curvatura (peak, intermediate_peak, curvature_direction_change) |
| **C3: Parser tests** | PENDIENTE | Tests unitarios para v2 loader (disjuntos, gaps, invariants) |
| **C4: Localization regression tests** | PENDIENTE | H5.2 localization no debe regressar al usar v2 vs v1 |
| **C5: Validator v0.2** | PENDIENTE | Validator v0.2 valida both v1 y v2; segments disjuntos, gaps |
| **C6: Backward compat tests** | PENDIENTE | Parsers v1 + H5.2 localization siguen funcionando con perfiles v1 |
| **C7: H5.3 compatibility** | PENDIENTE | Si H5.3 requiere segments, debe funcionar con v2 |
| **C8: Coexistencia v1/v2** | PENDIENTE | Si hay v1 y v2 coexistentes, loader elige correctamente |

### 9.2 Checklist de promoción

```
PROMOTION_GATE:
  [ ] C1: ≥3 golden profiles con segments diseñados (Fuji, Imola, Monza en v2 hipotético)
  [ ] C2: Cada segment tiene evidencia de curvatura
  [ ] C3: Parser tests para v2 (100% coverage de invariants)
  [ ] C4: H5.2 localization regression tests (no regression v1 vs v2)
  [ ] C5: Validator v0.2 implementado y validado
  [ ] C6: Backward compat tests (parsers v1 + H5.2 localization)
  [ ] C7: H5.3 compatibility (si H5.3 requiere segments)
  [ ] C8: Coexistencia v1/v2 (loader elige correctamente)
  [ ] C9: 0 FAILURES en regression suite (pytest + race_engineer_regressions)
  [ ] C10: No se rompe schema v1 (no migración)
```

### 9.3 No se implementa hasta que:

1. **No hay caso de uso claro** — H5.2 ya funciona con turn boundaries; segments son redundantes.
2. **No hay golden profiles reales** — Los 3 golden profiles (Fuji, Imola, Monza) tienen segments hipotéticos, no reales.
3. **No hay parser tests** — No se implementa v2 loader sin tests unitarios.
4. **No hay validation regression** — No se promueve sin regresión en H5.2 localization.

---

## 10. IMPLEMENT_NOW = NO

### 10.1 Estado actual

| Parámetro | Valor |
|-----------|-------|
| **IMPLEMENT_NOW** | **NO** |
| **DECISIÓN** | DESIGN_SCHEMA_V2_BUT_DO_NOT_IMPLEMENT |
| **DOCUMENTO** | `docs/TRACK_PROFILE_SCHEMA_V2_DESIGN_V0_1.md` |

### 10.2 Prerequisitos pendientes

| # | Prerequisito | Estado | Descripción |
|---|-------------|--------|-------------|
| 1 | **Golden profiles reales con segments** | PENDIENTE | Diseñar v2 para ≥3 perfiles reales |
| 2 | **Evidence requirements** | PENDIENTE | Cada segment debe tener evidencia de curvatura |
| 3 | **Parser v2** | PENDIENTE | Loader v2 para segments |
| 4 | **Validator v0.2** | PENDIENTE | Validator que valida invariants de segments |
| 5 | **H5.2 regression tests** | PENDIENTE | No regression al usar v2 vs v1 |
| 6 | **Backward compat tests** | PENDIENTE | Parsers v1 + H5.2 localization |
| 7 | **H5.3 compatibility** | PENDIENTE | Si H5.3 requiere segments |
| 8 | **Coexistencia v1/v2** | PENDIENTE | Loader elige correctamente |

### 10.3 Acciones pendientes

| Acción | Estado |
|--------|--------|
| **Diseñar v2 para golden profiles reales** | PENDIENTE |
| **Implementar parser v2** | PENDIENTE |
| **Implementar validator v0.2** | PENDIENTE |
| **Implementar regression tests** | PENDIENTE |
| **Promover v2 a production** | PENDIENTE |

---

## 11. RESULTADO DE TESTS

### 11.1 pytest

```
pytest -q: 453 PASS / 0 FAIL / 0 SKIP (full suite — sin --ignore)
```

### 11.2 Regressions

```
run_race_engineer_regressions.py --analyzer analyze_telemetry.py: 55 PASS / 0 FAIL / 0 SKIP
```

### 11.3 Regressions status

| Suite | Resultado |
|-------|-----------|
| `pytest -q` | 453 PASSED |
| `run_race_engineer_regressions.py` | 55 PASSED |

---

## 12. MODELO DE SEGMENTS ELEGIDO

| Parámetro | Valor |
|-----------|-------|
| **type** | `straight` | `transition` |
| **coverage** | **EVIDENCE-DRIVEN** — selective, no obligatorio |
| **overlap rules** | Disjuntos entre sí; disjuntos de turns |
| **migration risks** | Media (parsers existentes, H5.2 localization) |
| **prerequisitos** | 8 prerequisitos pendientes |

---

## 13. NO SE HIZO

| Acción | Estado |
|--------|--------|
| **Modificar schema v1** | ❌ No |
| **Implementar schema v2** | ❌ No |
| **Mover límites de turns** | ❌ No |
| **Modificar validator** | ❌ No |
| **Crear golden profiles v2** | ❌ No |
| **Implementar parser v2** | ❌ No |
| **Hacer commit** | ❌ No |
| **Hacer push** | ❌ No |

---

**FIN DEL REPORTE**
