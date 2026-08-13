# Race Engineer — Objective Python v5 (2026-08-13)

Este paquete NO contiene ni modifica LLM Analysis.

## Baseline objetivo

- Brake Point 2.1 / schema 2.1
- Throttle Point 1.2.1 / schema 1.2
- Throttle Episode Sequence 1.0
- Throttle Sustained Modulation 1.0
- Full Throttle Attainment Recurrence 1.0
- Throttle Modulation Recurrence 1.0
- **Throttle Physical Point Profile 1.0**

## Throttle Physical Point Profile 1.0

Capa session-level de unificación. No detecta eventos nuevos.

Identidad física:

```text
reference_lap + reference_event_id
```

Cada perfil reúne, cuando existen, hechos ya producidos por los módulos previos:

- secuencia física del evento
- onset
- release
- full-throttle attainment
- partial lifts
- sustained throttle modulation
- recurrencia de full-throttle attainment
- recurrencia de partial lift
- recurrencia de sustained throttle modulation

Salida:

```text
analysis_output["throttle_physical_point_profiles"]
```

Cada punto contiene `features` y `recurrence` separados para evitar reinterpretar los datos.

### Reglas

- un evento `comparison-only` no crea un perfil de referencia;
- una misma asignación física repetida en dos episodios de la misma vuelta se deduplica;
- si las asignaciones duplicadas difieren, se conserva `duplicate_conflict = true`;
- el snapshot del evento de referencia conserva un flag de consistencia entre comparaciones;
- los patrones de recurrencia se adjuntan por `reference_event_id`, sin recalcularlos.

### Contrato

```text
observational_only = true
affects_ranking = false
affects_session_priority = false
authorizes_new_coaching = false
source_only_no_redetection = true
```

El perfil puede preservar dentro de sus observaciones una autorización numérica ya emitida por el detector de onset/release. Eso NO constituye una autorización nueva del perfil.

## Recovery v5

Orden de hooks por comparación:

1. Brake Point 2.1
2. Throttle Point 1.2.1
3. Throttle Episode Sequence 1.0
4. Throttle Sustained Modulation 1.0

Orden de hooks session-level:

1. Full Throttle Attainment Recurrence 1.0
2. Throttle Modulation Recurrence 1.0
3. Throttle Physical Point Profile 1.0

El profile corre último para consumir los hechos y recurrencias ya calculados.

## Actualización desde Objective Python v4

Descomprimir el hotfix en el root del repo:

```bash
unzip -o race_engineer_throttle_physical_point_profile_v1_0_hotfix.zip
```

Aplicar recovery:

```bash
python ./apply_objective_python_recovery_2026_08_13.py ./analyze_telemetry.py
```

Verificar:

```bash
python ./run_race_engineer_regressions.py --analyzer ./analyze_telemetry.py
```

Resultado esperado:

```text
RACE ENGINEER PYTHON REGRESSION SUITE v1.4
RESULT: 47 PASS / 0 FAIL / 0 SKIP
```

## Validación realizada

Se verificaron dos rutas:

```text
analyzer limpio -> recovery v5 -> 47/0/0
Objective Python v4 -> recovery v5 -> 47/0/0
```

Además, una segunda ejecución del recovery es text-idempotent.
