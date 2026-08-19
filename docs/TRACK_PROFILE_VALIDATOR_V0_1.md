# Track Profile Validator v0.1

**Estado:** Shadow / Deterministic read-only audit
**Fecha:** 2026-08-18

## Objetivo

Crear un auditor/validator determinista para track profiles existentes en `track_profiles/`.

El validator es **read-only**: inspecciona y reporta, **no corrige, normaliza ni modifica** ningún perfil.

## Checks implementados

### 1. ORDERING

- `start_m < end_m` por turno
- Puntos/zonas ordenados por distancia (start_m ascendente)
- `apex_m` dentro de [start_m, end_m]

### 2. LAP BOUNDS

- Ninguna distancia < 0
- Ninguna distancia > lap_length_m (derivado de `calibration.source_lap_dist_max_m` o último end_m de turno)

### 3. GAPS / OVERLAPS

- **Gaps**: `end_m` de turno N < `start_m` de turno N+1
- **Overlaps**: `start_m` de turno N+1 < `end_m` de turno N
- Umbral informativo: 2% de lap_length
- Umbral de error: 5% de lap_length
- **Reporta, NO asume automáticamente que son errores**

### 4. DUPLICATE PHYSICAL POINTS

- Turnos con misma o casi misma distancia (tolerancia ±5 m) que representan entidades incompatibles (nombres o grupos distintos)
- No deduplica automáticamente

### 5. LAYOUT CONSISTENCY

- Presente: campos `track` y `layout`
- `track == layout` dentro del perfil
- `calibration` block como proxy para `lmu_track_layout` (hard context)

### 6. GPS CONSISTENCY

- `source_gps_path_m_approx` negativo → error
- `gps_coverage` fuera de [0, 1] → error
- `gps_coverage` ausente → informativo (no error)
- No inventa GPS

### 7. SEMANTIC STRUCTURE

- `direction`: válido (`left`, `right`, `mixed`)
- `direction_sequence`: elementos en (`left`, `right`)
- `aliases`: lista (si presente)
- `name`: requerido por schema
- No exige campos que el schema actual no requiera

### 8. PROVENANCE / CONFIDENCE

- `schema_version`: presente, de tipo int
- `profile_id`: presente
- `status`: presente
- `calibration.source_session`: informativo si ausente
- `display_policy`: informativo si ausente

## Output schema

```json
{
  "schema_version": 1,
  "validator_version": "0.1",
  "profile_id": "...",
  "track": "...",
  "layout": "...",
  "lap_length_m": 5000.0,
  "status": "VALID | VALID_WITH_WARNINGS | INVALID",
  "error_count": 0,
  "warning_count": 0,
  "informational_count": 0,
  "findings": [
    {
      "code": "...",
      "severity": "error | warning | informational",
      "entity_id": "...",
      "entity_name": "...",
      "distance_start_m": 100.0,
      "distance_end_m": 200.0,
      "deterministic_message": "...",
      "evidence": {...}
    }
  ],
  "summary": {
    "checks_run": ["ORDERING", "LAP_BOUNDS", "GAPS_OVERLAPS", ...],
    "turn_count": 11,
    "profile_status": "...",
    "calibration_present": true
  }
}
```

## Status

| Status | Descripción |
|---|---|
| `VALID` | Sin errores, sin warnings |
| `VALID_WITH_WARNINGS` | Warnings encontrados, sin errores |
| `INVALID` | Errores encontrados |

## Uso

### CLI

```powershell
python validate_track_profiles.py track_profiles/*.json
```

Con override de lap length:

```powershell
python validate_track_profiles.py track_profiles/monza_profile_v0_2.json --lap-length-m 5779.35
```

Con output JSON:

```powershell
python validate_track_profiles.py track_profiles/*.json --output data/generated/track_profile_validator.json
```

### API

```python
from validate_track_profiles import validate_profile, validate_profiles
from pathlib import Path

# Single profile
result = validate_profile(
    Path("track_profiles/monza_profile_v0_2.json"),
    lap_length_m=5779.35,
)

# Multiple profiles
profiles = sorted(Path("track_profiles/").glob("*.json"))
aggregate = validate_profiles(profiles)
```

## Prohibiciones

- **NO corrige perfiles**
- **NO normaliza LMP2_ELMS/LMP2**
- **NO cambia coaching**
- **NO usa LLM**
- **NO hace commit**
- **NO hace push**

## Test suite

```powershell
python -m pytest tests/test_track_profile_validator.py -v
```

Cobertura de tests:
- Perfil válido
- Distancia negativa
- > lap length
- Inverted range
- Overlap
- Gap
- Duplicate point
- Apex outside corner
- Invalid GPS
- Layout mismatch
- Missing optional data no produce false error
- Deterministic repeatability

## Resultados sobre perfiles actuales

Ver salida del validator al final de la ejecución del punto siguiente.
