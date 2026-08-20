# H5.3 Point 6 — Real-new-session audit harness v0.1

**Estado:** OBSERVATIONAL_AUDIT_ONLY
**Autoridad:** ninguna
**historical_actions_authorized:** false
**Schema version:** 1.0

Este documento describe la herramienta de auditoría offline/reproducible
que consume los artefactos reales generados por `race_engineer.py`
(el pipeline H5.3 completo: H4, H5.1, H5.2, H5.3a-f) y genera un
informe de auditoría sin volver a ejecutar ningún paso del pipeline.

---

## 1. Objetivo

Validar con sesiones reales nuevas (Imola, Interlagos, Fuji, etc.)
que el pipeline shadow H5.3 cumple sus invariantes:

- **selector** usa solo observation codes autorizados;
- **action policy** no genera acciones para current_faster;
- **validator** reporta estados válidos;
- **human_review** campos manuales permanecen NULL (el auditor no
  los completa);
- **classification** es determinista por candidato;
- **multitrack summary** agrega correctamente por pista.

---

## 2. Arquitectura

```
INPUT
  ├─ analysis.json
  ├─ h4/historical_reference_selection.json
  ├─ h5_1/dual_reference_context.json
  ├─ h5_2/cross_session_comparison.json
  ├─ h5_3/historical_coaching_candidates.json
  ├─ h5_3/historical_section.json
  ├─ h5_3_shadow/shadow_pipeline.json
  └─ h5_3_shadow/historical_actions.json

AUDITOR (audit_session())
  ├─ audit_identity()      → track/layout/vehicle/context
  ├─ audit_analyzer()      → valid_laps/comparison_status
  ├─ audit_h5_3_eligibility()  → candidates/eligible/withheld
  ├─ audit_llm_selection()   → observation_code verification
  ├─ audit_action_policy()   → actions/withheld/anti-regression
  ├─ audit_validator()       → section/status actions/status
  └─ classify_candidate()    → CLEAN_AUTHORIZED/WITHHELD/INVALID

OUTPUT
  └─ data/generated/h5_3_real_session_audit/<timestamp>/audit.json
```

---

## 3. Clasificación por candidato

La función `classify_candidate()` devuelve un estado determinista
por prioridad:

| Prioridad | Estado | Condición |
|-----------|--------|-----------|
| 1 | `SELECTOR_INVALID` | Selected observation_codes not in authorized |
| 2 | `POLICY_INVALID` | Anti-regression violated (current_faster with actions) |
| 3 | `VALIDATOR_FAILED` | Section/status or actions/status invalid |
| 4 | `CLEAN_AUTHORIZED` | Candidate has authorized action (all checks pass) |
| 5 | `CLEAN_WITHHELD` | Candidate withheld by valid reason |
| 6 | `NOT_APPLICABLE` | Insufficient data |

---

## 4. Estados del auditor

| Estado | Significado |
|--------|-------------|
| `AUDIT_COMPLETE` | Todos los artifacts presentes y audit finalizado |
| `INCOMPLETE_AUDIT` | Faltan artifacts obligatorios (FAIL-CLOSED) |
| `NOT_APPLICABLE` | insufficient_comparable_laps (no es fallo) |
| `ERROR` | Excepción inesperada |

---

## 5. Human review layer

Los campos de `human_review` permanecen `NULL` (no los completa
el auditor):

```json
{
  "human_review": {
    "actionability": null,
    "observation_correct": null,
    "action_correct": null,
    "notes": null
  }
}
```

---

## 6. Uso

### Single session

```powershell
python audit_h5_3_real_sessions.py <session_result_dir>
```

### Multitrack

```powershell
python audit_h5_3_real_sessions.py <dir1> <dir2> <dir3>
```

### With input directory

```powershell
python audit_h5_3_real_sessions.py --input-dir <directory>
```

### With custom output

```powershell
python audit_h5_3_real_sessions.py <dir> --output data/generated/h5_3_real_session_audit/my_batch
```

---

## 7. Output schema

```json
{
  "metadata": {
    "schema_version": "1.0",
    "audit_version": "0.1",
    "created_at_utc": "2026-08-19T...",
    "purpose": "H5.3 Point 6: real-new-session audit",
    "policy": {
      "historical_actions_authorized": false,
      "session_reference_remains_authority": true,
      "audit_is_observation_only": true,
      "no_llm_called": true,
      "no_human_labels_used": true
    }
  },
  "session_audits": [
    {
      "session": "<label>",
      "identity": { "track": "...", "track_layout": "...", "vehicle_variant": "..." },
      "analyzer": { "valid_laps": 5, "status": "SUPPORTED" },
      "eligibility": { "total_candidates": 1, "eligible": 1 },
      "selector_audit": { "selected_count": 1, "observation_codes_valid": true },
      "policy_audit": { "authorized_actions": 1, "anti_regression_passed": true },
      "validator_audit": { "section_pass": true, "actions_pass": true },
      "status": "AUDIT_COMPLETE",
      "candidate_results": [
        {
          "candidate_id": "candidate_001",
          "status": "CLEAN_AUTHORIZED",
          "delta_change_s": -0.5,
          "delta_sign": "current_slower"
        }
      ],
      "human_review": [
        {
          "candidate_id": "candidate_001",
          "spatial_range_m": "1200-1500",
          "human_review": { ... }
        }
      ],
      "session_summary": { ... }
    }
  ],
  "multitrack_summary": {
    "tracks_count": 1,
    "sessions_count": 2,
    "candidates_total": 3,
    "clean_authorized": 2,
    "clean_withheld": 1,
    "observation_counts": { ... },
    "action_counts": { ... }
  }
}
```

---

## 8. Tests

El archivo `tests/test_h5_3_real_session_audit.py` cubre 11 casos:

1. **Clean authorized** — candidate tiene acción autorizada
2. **Clean withheld** — candidate con razón de withheld válida
3. **Selector invalid** — observation codes no autorizados
4. **Policy invalid** — anti-regression violated
5. **Validator failed** — section/status o actions/status inválido
6. **Incomplete audit** — faltan artifacts
7. **Not applicable** — insufficient_laps
8. **Multitrack aggregation** — conteos cruzados por pista
9. **Human review null** — campos manuales permanecen nulos
10. **Deterministic repeatability** — mismo input = mismo output
11. **No human labels affect status** — clasificación no depende de labels humanos

```powershell
python -m pytest tests/test_h5_3_real_session_audit.py -v
python -m pytest -q
```

---

## 9. Invariants

- **No re-execution** del pipeline (LLM, eligibility, selection, actions)
- **No human labels** como input ni para clasificación
- **Fail-closed**: faltan artifacts -> `INCOMPLETE_AUDIT`
- **insufficient_laps** -> `NOT_APPLICABLE` (no es fallo)
- **human_review** campos manuales `NULL` (no los completa el auditor)
- **Classification** determinista por prioridad
- **No promover** producción (`historical_actions_authorized=false`)
- **Session reference** permanece autoridad (`session_reference_remains_authority=true`)

---

## 10. Próximos pasos

- Validar con sesiones reales (Imola, Interlagos, Fuji)
- Multitrack aggregation
- Human review layer (campos manuales)
- NO promover producción hasta que el equipo decida

---

**Resultado:** La auditoría es observacional y no modifica ningún
artefacto del pipeline. El informe se escribe en
`data/generated/h5_3_real_session_audit/<timestamp>/audit.json`.
