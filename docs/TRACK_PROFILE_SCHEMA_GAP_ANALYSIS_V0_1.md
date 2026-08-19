# Track Profile Schema Gap Analysis v0.1

**Fecha:** 2026-08-19
**Estado:** Análisis, sin implementación
**Perfiles analizados:** Fuji v0.3, Imola v0.3, Monza v0.3

---

## 1. COVERAGE

### 1.1 % lap cubierto por turn ranges

| Track | Lap (m) | Turns | Turn range coverage | % cubierto | % uncovered |
|-------|---------|-------|---------------------|------------|-------------|
| Monza | 5,779.35 | 11 | 1,987.0 | **34.4%** | 65.6% |
| Imola | 4,892.01 | 19 | 2,480.0 | **50.7%** | 49.3% |
| Fuji | 4,526.01 | 16 | 2,536.0 | **56.0%** | 44.0% |

### 1.2 % uncovered y cantidad/longitud de gaps

| Track | Total uncovered | # gaps entre turns | Gap más largo | % del lap más largo |
|-------|-----------------|---------------------|---------------|---------------------|
| Monza | 3,792.4 m | 6 | 940.0 m | 16.3% |
| Imola | 2,412.0 m | 9 | 430.0 m | 8.8% |
| Fuji | 1,990.0 m | 8 | 206.0 m | 4.6% |

### 1.3 Observaciones

- **Monza**: 65.6% uncovered es el peor caso. El gap más largo (940 m, 16.3%) es el straight principal entre Lesmo 2 y Ascari — es un straight real de Monza, no un artefacto.
- **Imola**: 49.3% uncovered es moderado. El gap más largo (430 m, 8.8%) es el straight entre Gresini y Rivazza — también un straight real.
- **Fuji**: 56.0% uncovered parece alto pero Fuji tiene turns más compactos y 16 turns en 4,526 m — el perfil más denso del conjunto.

### 1.4 La cobertura "baja" es intencional

Los turns en schema v1 representan **curvas/apexes**, no straights ni transiciones. La cobertura de turn range no es un defecto del schema — es la semántica correcta: turns son regiones de alta curvatura, los straights no son turns.

El schema v1 cubte intencionalmente ~34-56% del lap con turns y documenta el resto en `geometric_notes`.

---

## 2. CLASIFICACIÓN DE TODOS LOS GAPS

### 2.1 Tabla completa de gaps entre turns

| Track | From | To | from_m | to_m | length_m | %lap | Classification | Evidence |
|-------|------|----|--------|------|----------|------|----------------|----------|
| Monza | Rettifilo (T2) | Curva Grande (T3) | 1020 | 1180 | 160.0 | 2.8% | straight_real_track_feature | intermediate_peak=False |
| Monza | Curva Grande (T3) | Roggia (T4) | 1760 | 2098 | 338.0 | 5.8% | straight_real_track_feature | intermediate_peak=False |
| Monza | Roggia (T5) | Lesmo 1 (T6) | 2230 | 2460 | 230.0 | 4.0% | straight_real_track_feature | intermediate_peak=False |
| Monza | Lesmo 1 (T6) | Lesmo 2 (T7) | 2660 | 2815 | 155.0 | 2.7% | straight_real_track_feature | intermediate_peak=False |
| Monza | Lesmo 2 (T7) | Ascari (T8) | 2945 | 3885 | 940.0 | 16.3% | straight_real_track_feature | intermediate_peak=False |
| Monza | Ascari (T10) | Alboreto (T11) | 4225 | 5060 | 835.0 | 14.5% | straight_real_track_feature | intermediate_peak=False |
| Imola | Tamburello (T4) | Villeneuve (T5) | 980 | 1260 | 280.0 | 5.7% | straight_real_track_feature | intermediate_peak=False |
| Imola | Villeneuve (T6) | Tosa (T7) | 1480 | 1650 | 170.0 | 3.5% | straight_real_track_feature | intermediate_peak=False |
| Imola | Tosa (T7) | Turn 8 (T8) | 1770 | 2000 | 230.0 | 4.7% | straight_real_track_feature | intermediate_peak=False |
| Imola | Acque Minerali (T13) | Gresini (T14) | 2990 | 3300 | 310.0 | 6.3% | straight_real_track_feature | intermediate_peak=False |
| Imola | Gresini (T15) | Turn 16 (T16) | 3430 | 3860 | 430.0 | 8.8% | straight_real_track_feature | intermediate_peak=False |
| Fuji | Turn 2 → Coca-Cola (T3) | 1050 | 1256 | 206.0 | 4.6% | straight_real_track_feature | intermediate_peak=False |
| Fuji | Coca-Cola (T3) → 100R (T4) | 1388 | 1482 | 94.0 | 2.1% | straight_short_real_track_feature | intermediate_peak=False |
| Fuji | 100R (T5) → Hairpin (T6) | 1882 | 1954 | 72.0 | 1.6% | transition_zone | intermediate_peak=False |
| Fuji | GR Supra (T15) → Panasonic (T16) | 3458 | 3542 | 84.0 | 1.9% | transition_zone | intermediate_peak=False |

### 2.2 Tabla de boundary offsets (minor gaps)

| Track | Turn | Gap (m) | Classification |
|-------|------|---------|----------------|
| Imola | T2 | 0.0 | touching_boundary |
| Imola | T3 | 0.0 | touching_boundary |
| Imola | T8 | 50.0 | acceptable_boundary_offset |
| Imola | T10 | 80.0 | acceptable_boundary_offset |
| Imola | T16 | 70.0 | acceptable_boundary_offset |
| Imola | T19 | 100.0 | acceptable_boundary_offset |
| Fuji | T1 | 16.0 | acceptable_boundary_offset |
| Fuji | T7 | 10.0 | acceptable_boundary_offset |
| Fuji | T8 | 20.0 | acceptable_boundary_offset |
| Fuji | T13 | 4.0 | touching_boundary |
| Fuji | T14 | 0.0 | touching_boundary |

### 2.3 Clasificación resumida por categoría

| Classification | Count | Tracks |
|----------------|-------|--------|
| straight_real_track_feature | 11 | Monza (6), Imola (5), Fuji (1) |
| straight_short_real_track_feature | 1 | Fuji (1) |
| transition_zone | 2 | Fuji (2) |
| acceptable_boundary_offsets | 11 | Imola (6), Fuji (5) |
| touching_boundary | 4 | Imola (2), Fuji (2) |
| low_curvature_continuation | 1 | Fuji (1) — Turn 7 |

**Conclusión:** Todos los gaps son **straights reales** o **transiciones** documentadas con evidencia de curvatura intermedia (intermediate_peak=False). Ningún gap indica turns faltantes.

---

## 3. LIMITACIONES DE V1

### 3.1 Limitaciones reales del schema v1

| # | Limitación | Descripción | Impacto funcional |
|---|-----------|-------------|-------------------|
| 1 | **No hay entidad explícita para straights** | Los straights no tienen representación estructural — solo se documentan en `geometric_notes` | H5.2 zone localization debe inferir straights desde gaps entre turns |
| 2 | **No hay entidad explícita para transiciones** | Las transiciones entre turns (ej. Fuji 100R→Hairpin, 72 m) no están representadas | No se puede distinguir un straight real de una transición de complejos |
| 3 | **Turn boundaries vs physical location** | Cada turn define [start_m, apex_m, end_m] pero no hay "braking zone", "exit", "entry" separados | El coaching no puede referenciar braking/exit zones estructuradas |
| 4 | **No hay coverage ratio por tipo** | No se puede calcular cuántas curvas vs straights vs transiciones hay por lap | Solo se puede inferir manualmente |
| 5 | **`ignored_geometric_features_m` no representa straights** | Su semántica es "curvature features no numeradas", no "regiones de baja curvatura entre turns" | No se usa para segmentación |

### 3.2 Cosas ya representables en v1

| # | Representable | Cómo |
|---|--------------|------|
| 1 | **Complejos de turns** | `group` field agrupa turns (ej. "Lesmo", "Ascari", "Dunlop") |
| 2 | **Aliases** | `aliases` por turn permite múltiples nombres |
| 3 | **Secuencia de dirección** | `direction_sequence` implícita en turns ordenados |
| 4 | **Provenance** | `calibration` con sessions independientes y validation results |
| 5 | **GPS limitation** | `geometric_notes` con `data_limitation` type |
| 6 | **Confianza por turn** | `validation_summary.turn_results[].status` (PASS/WARNING/FAIL) |
| 7 | **Policy de display** | `display_policy` con preferencias |
| 8 | **Low-curvature turns** | `manual_low_curvature_turns` (Fuji, Imola) |

### 3.3 Problemas del validator v0.1

| # | Problema | Detalle |
|---|----------|---------|
| 1 | **No valida gaps esperables** | El validator reporta gaps como warnings/informational pero no tiene forma de marcarlos como "expected" |
| 2 | **No valida coverage** | No hay check de % cobertura mínima por tipo |
| 3 | **No valida consistencia turn/segment** | Si v2 agrega segments, el validator no valida la consistencia entre turns y segments |
| 4 | **No valida intentional uncovered** | No hay forma de declarar "estas regiones están intencionalmente sin cubrir" |

### 3.4 Metadata puramente documental

| Campo | Tipo | ¿Estructural? |
|-------|------|---------------|
| `geometric_notes` | Free-form dict | No — el validator lo ignora |
| `display_policy` | Dict | Sí — usado por renderers |
| `calibration` | Dict | Sí — usado por H5.2 localization |
| `ignored_geometric_features_m` | List | Sí — audit, no usado para gaps |
| `manual_low_curvature_turns` | List | Sí — solo Fuji/Imola |

---

## 4. EVALUACIÓN: SEGMENTS PARA FUTURO SCHEMA

### 4.1 Propuesta: entity `segments`

```json
{
  "segments": [
    {
      "id": "seg_1",
      "type": "straight",
      "start_distance_m": 1020.0,
      "end_distance_m": 1180.0,
      "related_turns": ["T2", "T3"],
      "confidence": "high",
      "provenance": "geometric_notes.gap_t2_to_t3"
    },
    {
      "id": "seg_2",
      "type": "transition",
      "start_distance_m": 1882.0,
      "end_distance_m": 1954.0,
      "related_turns": ["T5", "T6"],
      "confidence": "high",
      "provenance": "geometric_notes.gap_t5_to_t6"
    }
  ]
}
```

### 4.2 Beneficio funcional real para Race Engineer

| Beneficio | Descripción | Impacto |
|-----------|-------------|---------|
| **H5.2 zone localization** | Los segments reemplazan los gaps actuales como boundaries explícitos para split de trend zones | Medio — el split por turn boundaries ya funciona, los segments serían redundantes |
| **Explicit straight identification** | Los straights no necesitan ser inferidos desde geometric_notes | Alto — el coaching puede referenciar straights sin buscar en geometric_notes |
| **Coverage validation** | Se puede validar que todos los gaps están representados como segments | Bajo — ya hay geometric_notes para documentar |
| **Consistencia turn-segment** | El validator puede verificar que turns y segments no se superponen | Medio — importante si segments cubren todo el lap |

### 4.3 Riesgo: duplicar turns

- Si `segments` cubren **todo el lap**, entonces los turns y segments se superponen → duplicación.
- Si `segments` cubren **sólo los gaps**, entonces no hay duplicación: turns = turn regions, segments = non-turn regions.

**Recomendación:** Los segments deben cubrir **sólo las regiones no-turn** (straights, transitions). Los turns cubren las turn regions. La unión de turns + segments = todo el lap.

### 4.4 ¿Segments deben cubrir todo el lap o sólo regiones relevantes?

**Regiones relevantes:**
- `straight` — straight real entre turns (evidencia: gap entre turns, no peak de curvatura)
- `transition` — zona de transición entre complejos (evidencia: gap corto, low curvature)
- `complex` — región conteniendo un complejo de turns (actualmente cubierto por `group`)

**No cubrir:**
- `turn` — ya cubierto por turns
- `unknown` — no debería haber regiones unknown

**Región de cobertura:**
- Los segments deben cubrir **sólo las regiones no-turn** entre turns.
- Los turns cubren las turn regions.
- La unión de turns + segments = todo el lap.

### 4.5 Distancia → physical track location en v2

| Elemento | v1 (current) | v2 (proposed) |
|----------|-------------|---------------|
| Turn apex | `turns[].apex_m` | Mismo, sin cambio |
| Turn start | `turns[].start_m` | Mismo, sin cambio |
| Turn end | `turns[].end_m` | Mismo, sin cambio |
| Straight | No representado | `segments[].start_distance_m` → `segments[].end_distance_m` |
| Braking zone | No representado | Optional: `braking_distance_m` dentro de turn o segment |
| Exit zone | No representado | Optional: `exit_distance_m` dentro de turn |
| Complex | `turns[].group` | `segments[].type=complex` o turns agrupados |
| Transition | No representado | `segments[].type=transition` |

**Ambigüedades reales de v1:**

1. **Braking zone vs turn apex**: En v1, la braking zone es implícita (el inicio del turn). En v2, podría ser explícita.
2. **Exit zone vs turn end**: En v1, el exit zone es implícito (el final del turn). En v2, podría ser explícita.
3. **Complex boundaries**: En v1, el `group` field agrupa turns pero no define límites físicos. En v2, el complejo podría tener límites explícitos.

---

## 5. PROPOSICIÓN DE FUTURE VALIDATOR v0.2

### 5.1 Checks propuestos

| Check | Descripción | v1 | v2 |
|-------|-------------|----|----|
| **expected_gaps** | Validar que todos los gaps entre turns tienen entry en geometric_notes | ❌ | ✅ |
| **uncovered_distance** | Validar que % uncovered es razonable para el tipo de pista | ❌ | ✅ |
| **segment_overlap** | Validar que segments no se superponen con turns | ❌ | ✅ |
| **turn_consistency** | Validar que turns y segments no se superponen | ❌ | ✅ |
| **intentional_uncovered** | Validar que regiones intencionalmente sin cubrir están documentadas | ❌ | ✅ |

### 5.2 Detalle de cada check

#### expected_gaps
- Para cada gap entre turns, debe existir una entrada en `geometric_notes` con `type=gap_explanation` o `type=straight_explanation`.
- El `start_m`/`end_m` del gap debe coincidir con el `start_m`/`end_m` de la entrada.

#### uncovered_distance
- El % uncovered debe ser razonable para el tipo de pista:
  - Monza (alta velocidad): >50% uncovered es esperado (muchos straights)
  - Imola (mixto): >40% uncovered es esperado
  - Fuji (alta densidad de curvas): >30% uncovered es esperado
- Si % uncovered es anómalamente bajo → warning (posible sobre-annotación)

#### segment_overlap
- Para cada segment, verificar que `[segment.start_distance_m, segment.end_distance_m]` no intersecta con `[turn.start_m, turn.end_m]` de ningún turn.

#### turn_consistency
- Para cada par de turns consecutivos, verificar que `[turn_n.start_m, turn_n.end_m]` y `[turn_n+1.start_m, turn_n+1.end_m]` no se superponen.
- Si se superponen, el overlap debe ser documentado en `geometric_notes`.

#### intentional_uncovered
- Para cada región entre turns que NO tiene entry en `geometric_notes`, verificar que no hay gap significativo (gap < umbral).
- Si hay un gap > umbral sin entry → error.

---

## 6. BACKWARD COMPATIBILITY: V1 Y V2 COEXISTENTES

### 6.1 Estrategia de coexistencia

| Aspecto | Estrategia |
|---------|-----------|
| **schema_version** | v1 mantiene `schema_version: 1`, v2 usa `schema_version: 2` |
| **Migración** | NO migrar v1 → v2. Los perfiles v1 siguen siendo válidos como `schema_version: 1` |
| **Validator** | v0.2 del validator valida ambos schemas: v1 (checks existentes) y v2 (checks adicionales) |
| **Parsers** | Los parsers existentes que leen `schema_version: 1` no se ven afectados por v2 |
| **H5.2 localization** | `find_validated_track_profile` filtra por `status in {VALIDATED, VALIDATED_MULTI_SESSION}`, no por schema_version |
| **Segments en v1** | Si v1 tiene `segments`, el parser los ignera (campo desconocido) |

### 6.2 No migración

- Los perfiles v1 existentes **no se migran** a v2.
- Cada pista tiene su propio ciclo de vida: v1 → v2 cuando sea necesario.
- Si v2 agrega `segments`, los perfiles v1 siguen funcionando porque H5.2 ya funciona con splits por turn boundaries.

---

## 7. DECISIÓN FINAL

### Opciones

| Opción | Descripción |
|--------|-------------|
| **A) KEEP_SCHEMA_V1** | No cambiar schema v1. Los gaps ya están documentados en `geometric_notes`. H5.2 ya funciona con turn boundaries. |
| **B) DESIGN_SCHEMA_V2_BUT_DO_NOT_IMPLEMENT** | Diseñar schema v2 completo pero no implementarlo hasta que haya un caso de uso claro. |
| **C) IMPLEMENT_SCHEMA_V2_NEXT** | Implementar schema v2 inmediatamente. |

### 7.1 Evaluación de cada opción

#### Opción A: KEEP_SCHEMA_V1

**A favor:**
- Schema v1 es funcional: 368 tests PASSED, 55 regressions PASSED
- `geometric_notes` ya documenta todos los gaps con evidencia
- H5.2 ya funciona con turn boundaries
- Los segments no dan beneficio funcional inmediato sobre v1
- Más coverage no significa mejor calidad si la cobertura ya es documentada

**En contra:**
- Los straights no están representados estructuralmente
- Si el roadmap requiere explicit straight/transition zones en el futuro, v1 no los tiene
- El validator v0.1 no valida gaps esperables

**Veredicto:** A es la opción correcta **si no hay un caso de uso claro para segments**. El valor de segments para H5.2 es medio (el split por turn boundaries ya funciona). El valor de segments para el coaching es alto (explicit straight identification).

#### Opción B: DESIGN_SCHEMA_V2_BUT_DO_NOT_IMPLEMENT

**A favor:**
- Permite diseñar la spec completa antes de implementar
- No rompe v1 (no migración)
- Se puede implementar cuando haya un caso de uso claro
- Se puede validar con los 3 profiles existentes

**En contra:**
- La spec puede ser compleja: segments vs turns vs geometric_notes
- Hay riesgo de over-engineering

**Veredicio:** B es la opción recomendada. Diseñar schema v2 pero no implementarlo hasta que haya un caso de uso claro (ej. si H5.3 requiere explicit straight/transition zones para historical coaching).

#### Opción C: IMPLEMENT_SCHEMA_V2_NEXT

**A favor:**
- Resolvería todas las limitaciones de v1 inmediatamente
- Los segments serían el estándar para todos los futuros perfiles

**En contra:**
- Rompe parsers existentes
- Rompe H5.2 localization (necesita conocer schema v2)
- No hay caso de uso claro que justifique la migración inmediata
- Los 368 tests actuales no incluyen segments

**Veredicto:** C es prematuro. No hay un caso de uso que justifique la implementación inmediata de v2.

### 7.2 DECISIÓN: B

**DESIGN_SCHEMA_V2_BUT_DO_NOT_IMPLEMENT**

**Justificación:**

1. **Schema v1 es funcional pero incompleto** — 34-56% de turn range coverage es intencional (los straights no son turns). Los gaps están documentados en `geometric_notes`. El validator v0.1 funciona correctamente.

2. **El beneficio de segments para H5.2 es medio** — El split por turn boundaries ya funciona para H5.2 zone localization. Los segments son redundantes para H5.2.

3. **El beneficio de segments para el coaching es alto** — Explicit straight identification es útil para el coaching (ej. "straight de 940 m después de Lesmo 2").

4. **No hay caso de uso claro para implementación inmediata** — El roadmap H5.3 (historical coaching) podría necesitar explicit straight/transition zones, pero no está confirmado.

5. **Diseñar v2 no rompe v1** — Los perfiles v1 siguen siendo válidos. La coexistencia es posible.

**Acción siguiente:**
- Crear spec de schema v2 en `docs/TRACK_PROFILE_SCHEMA_V2_SPEC.md` (si se justifica).
- No modificar perfiles existentes.
- No implementar schema v2.

---

## 8. RESULTADO DE TESTS

### 8.1 pytest

```
pytest -q: 368 PASS / 0 FAIL / 0 SKIP
```

### 8.2 Regressions

```
run_race_engineer_regressions.py --analyzer analyze_telemetry.py: 55 PASS / 0 FAIL / 0 SKIP
```

### 8.3 Regressions status

| Suite | Total | PASSED | FAILED | SKIPPED |
|-------|-------|--------|--------|---------|
| pytest | 368 | 368 | 0 | 0 |
| race_engineer_regressions | 55 | 55 | 0 | 0 |

---

## 9. RESUMEN FINAL

| Métrica | Resultado |
|---------|-----------|
| **DECISIÓN** | **B) DESIGN_SCHEMA_V2_BUT_DO_NOT_IMPLEMENT** |
| **Coverage** | Monza: 34.4%, Imola: 50.7%, Fuji: 56.0% |
| **Gaps por categoría** | straight (12), transition (2), boundary_offsets (11), low_curvature (1) |
| **Beneficio real de segments** | Alto para coaching, medio para H5.2 |
| **Riesgos** | No hay riesgo si se mantiene B (no implementación) |
| **Tests** | 368/368 pytest PASSED, 55/55 regressions PASSED |

---

## 10. NO SE HIZO

| Acción | Estado |
|--------|--------|
| Modificar schema v1 | ❌ No |
| Implementar schema v2 | ❌ No |
| Mover límites de turns | ❌ No |
| Modificar validator | ❌ No |
| Hacer commit | ❌ No |
| Hacer push | ❌ No |

---

**FIN DEL REPORTE**
