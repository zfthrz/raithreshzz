# Fuji Speedway Profile v0.3 — Final Report

**Fecha:** 2026-08-18
**Estado:** ✅ Completado — sin errores, warnings explicados

---

## 1. Resumen de cambios estructurales (v0.2 → v0.3)

### Cambios realizados

| Campo | v0.2 | v0.3 | Cambio |
|-------|------|------|--------|
| `schema_version` | 1 | 1 | **Sin cambio** |
| `profile_id` | `fuji-speedway-lmu-wec16-v0.2` | `fuji-speedway-lmu-wec16-v0.3` | **Actualizado** |
| `calibration` | Identical | Identical | **Sin cambio** |
| `ignored_geometric_features_m` | 3 entries | 3 entries | **Sin cambio** |
| `manual_low_curvature_turns` | 4 entries | 4 entries | **Sin cambio** |
| `turns` | 16 entries | 16 entries | **Sin cambio** |
| `display_policy` | Identical | Identical | **Sin cambio** |
| `geometric_notes` | Ausente | 7 notes | **Nuevo campo** |

### Campo agregado: `geometric_notes`

| Nota | ID | Tipo | Entidad | Gap (m) | Clasificación |
|------|----|------|---------|---------|---------------|
| 1 | `gap_t2_to_t3` | straight_real_track_feature | Turn 2 → Coca-Cola Corner | 206 | Straight real track feature |
| 2 | `gap_t3_to_t4` | straight_short_real_track_feature | Coca-Cola Corner → 100R | 94 | Short straight |
| 3 | `gap_t5_to_t6` | transition_zone | 100R → Hairpin | 72 | Transition zone |
| 4 | `gap_t15_to_t16` | transition_zone | GR Supra Corner → Panasonic | 84 | Transition zone |
| 5 | `minor_gaps` | acceptable_boundary_offsets | Múltiple | 0–20 | Acceptable boundary offsets |
| 6 | `t7_low_curvature_continuation` | low_curvature_continuation | Turn 7 | — | Low-curvature continuation |
| 7 | `gps_coverage_limitation` | calibration_limitation | GPS coverage | — | Known limitation |

---

## 2. Validación

### Validator output v0.2 vs v0.3

| Métrica | v0.2 | v0.3 |
|---------|------|------|
| Status | `VALID_WITH_WARNINGS` | `VALID_WITH_WARNINGS` |
| Errors | 0 | 0 |
| Warnings | 2 | 2 |
| Informational | 7 | 7 |

### Warnings (identicos en v0.2 y v0.3)

1. **Gap 206 m** entre end de Turn 2 y start de Coca-Cola Corner — 4.6% del lap
2. **Gap 94 m** entre end de Coca-Cola Corner y start de 100R — 2.1% del lap

### Informational (identicos en v0.2 y v0.3)

1. Minor gap 16.0 m entre TGR Corner y Turn 2
2. Minor gap 72.0 m entre 100R y Hairpin
3. Minor gap 10.0 m entre Turn 7 y Turn 8
4. Minor gap 20.0 m entre 300R y Dunlop Corner
5. Minor gap 4.0 m entre 13th Corner y Turn 14
6. Minor gap 84.0 m entre GR Supra Corner y Panasonic Corner
7. GPS coverage not available in calibration sessions

---

## 3. Decisiones técnicas

### 3.1 `ignored_geometric_features_m` NO usado para straights

**Veredicto:** Semanticamente incorrecto. Su semántica existente es **curvature features no numeradas** (no straights/gaps).

**Evidencia de perfiles existentes:**

| Perfil | Semántica de `ignored_geometric_features_m` |
|--------|---------------------------------------------|
| La Sarthe | "secondary strong-curvature point", "approach curvature", "low-curvature geometric feature" |
| Spa | "geometric bend not separately numbered", "Kemmel curvature not separately numbered", "low-curvature geometric feature" |
| Monza | "low-curvature transition", "exit/transition curvature", "low-curvature feature" |
| Interlagos | "low-curvature transition", "low-curvature feature", "secondary curvature" |
| Fuji v0.2 | "secondary strong-curvature point inside 100R complex", "entry curvature inside T14-T15", "early curvature inside T16" |

### 3.2 `geometric_notes` como campo libre

**Decisión:** Usar `geometric_notes` como metadata documental libre.

**Justificación:**
- Schema v1 no requiere `geometric_notes`, pero tampoco lo rechaza.
- El validator lo acepta sin interpretar su contenido.
- No modifica comportamiento runtime ni validator.
- Compatible con parsers existentes (campo desconocido es ignorado por JSON parsers).

### 3.3 T7: Sin cambio de geometría

**Decisión:** Mantener T7 sin cambio, documentar como low-curvature continuation.

**Evidencia:**
- Independent validation: offset -56 m (observed apex 2084 m vs expected 2140 m)
- Exceeds ±35 m tolerance threshold → WARNING status
- No evidence sufficient to redefine boundary
- Calibrated interval mapping remains authoritative

---

## 4. Tests

### Fuji v0_3 tests

| Test | Estado |
|------|--------|
| `test_v03_loads_successfully` | ✅ PASSED |
| `test_v03_profile_id_updated` | ✅ PASSED |
| `test_turn_count_unchanged` | ✅ PASSED |
| `test_turn_geometry_identical` | ✅ PASSED |
| `test_lap_length_identical` | ✅ PASSED |
| `test_layout_identical` | ✅ PASSED |
| `test_aliases_unchanged` | ✅ PASSED |
| `test_ignored_geometric_features_m_identical` | ✅ PASSED |
| `test_manual_low_curvature_turns_identical` | ✅ PASSED |
| `test_display_policy_identical` | ✅ PASSED |
| `test_v03_has_geometric_notes` | ✅ PASSED |
| `test_v03_geometric_notes_has_expected_notes` | ✅ PASSED |
| `test_v03_note_ids_expected` | ✅ PASSED |
| `test_v03_gaps_documented_as_straight_transitions` | ✅ PASSED |
| `test_v03_t7_documented_as_low_curvature` | ✅ PASSED |
| `test_v03_gps_documented_as_limitation` | ✅ PASSED |
| `test_v03_schema_version_unchanged` | ✅ PASSED |
| `test_v03_required_fields_present` | ✅ PASSED |
| `test_v03_geometric_notes_is_freeform_dict` | ✅ PASSED |
| `test_v03_turns_structure_unchanged` | ✅ PASSED |
| `test_v03_validator_passes` | ✅ PASSED |

**Total:** 21/21 PASSED

### Full test suite

| Suite | Total | PASSED | FAILED | SKIPPED |
|-------|-------|--------|--------|---------|
| `pytest -q` | 368 | 368 | 0 | 0 |

### Race engineer regressions

| Suite | Total | PASSED | FAILED | SKIPPED |
|-------|-------|--------|--------|---------|
| `run_race_engineer_regressions.py` | 55 | 55 | 0 | 0 |

---

## 5. Warnings restantes

| Warning | Clasificación | Explicación |
|---------|---------------|-------------|
| **Gap 206 m T2→T3** | Expected — real track straight | Fuji contains an expected straight section between Turn 2 and Coca-Cola Corner (run-off/drainage zone). Curvature evidence shows no intermediate peak. |
| **Gap 94 m T3→T4** | Expected — real track straight | Short straight section between Coca-Cola Corner and 100R. Curvature evidence shows no intermediate peak. |

**Veredicto:** Cada warning restante está explicado y es legítimo. No se modificó el validator para ocultarlos. No se corrigió la geometría de turns para eliminarlos.

---

## 6. Compatibilidad de schema/parser

### Schema v1 compatibility

| Verificación | Resultado |
|---------------|-----------|
| `schema_version` | ✅ Still 1 |
| `profile_id` | ✅ Updated to v0.3 |
| `required fields` | ✅ All present |
| `turns structure` | ✅ Identical |
| `calibration structure` | ✅ Identical |
| `display_policy structure` | ✅ Identical |
| `geometric_notes` | ✅ Free-form dict (schema v1 doesn't enforce it) |

### Parser compatibility

- `geometric_notes` es un campo libre que no afecta la estructura de `turns`, `calibration` ni `display_policy`.
- Parsers existentes que leen `turns`, `calibration` o `display_policy` no se ven afectados.
- El validator no interpreta `geometric_notes` — lo ignera completamente.

---

## 7. Archivos entregados

| Archivo | Descripción |
|---------|-------------|
| `track_profiles/fuji_speedway_profile_v0_3.json` | Profile v0.3 con `geometric_notes` |
| `tests/test_fuji_speedway_profile_v0_3.py` | 21 tests específicos para v0.3 |

---

## 8. No se hizo

| Acción | Estado |
|--------|--------|
| Modificar `schema_version` | ❌ No |
| Mover límites de turns | ❌ No |
| Corregir geometría de T7 | ❌ No |
| Usar `ignored_geometric_features_m` para straights | ❌ No |
| Modificar el validator | ❌ No |
| Ocultar warnings con hacks | ❌ No |
| Inventar datos | ❌ No |
| Estimar distancias "a ojo" | ❌ No |
| Invertir GPS | ❌ No |
| Completar campos opcionales sin fuente | ❌ No |
| Hacer commit | ❌ No |
| Hacer push | ❌ No |

---

## 9. Checklist final

```text
[✓] DuckDB en telemetria/
[✓] Analyze telemetry (v0.2 geometry preserved)
[✓] Validación temporal/objetiva OK
[✓] Validator v0.3: 2 warnings, 7 informational, 0 errors
[✓] Validator v0.3 vs v0.2: Identical warnings
[✓] geometric_notes: 7 notes explicando gaps, T7, GPS
[✓] 21 tests v0.3: 21 PASSED
[✓] Full test suite: 368 PASSED
[✓] Regressions: 55 PASSED
[✓] No commit
[✓] No push
```

---

## 10. Conclusiones

1. **v0.3 preserva exactamente la geometría de v0.2** — No se modificaron start/end/apex de ningún turn.
2. **Los warnings son legítimos** — Son gaps reales del circuito (straights/transition zones) que no requieren corrección.
3. **`geometric_notes` es el campo correcto** — Metadata libre que documenta los gaps sin afectar el validator ni los parsers existentes.
4. **T7 permanece sin cambio** — La evidencia es insuficiente para redefinir el boundary; el calibrated interval mapping sigue siendo autoritativo.
5. **Compatibilidad total** — Schema v1, validator, parsers existentes no se ven afectados.

---

**FIN DEL REPORTE**
