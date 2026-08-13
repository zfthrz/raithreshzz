# Race Engineer — Objective Python v3 (2026-08-13)

Este paquete NO contiene ni modifica LLM Analysis.

## Baseline

- Brake Point 2.1 / schema 2.1
- Throttle Point 1.2.1 / schema 1.2
  - onset/release conservan lógica 1.1
  - full-throttle attainment observacional
  - partial lift observacional
- Throttle Episode Sequence 1.0
  - múltiples eventos físicos de acelerador por `driver_action_episode`
  - observacional
- Throttle Sustained Modulation 1.0
  - modulación recuperada demasiado profunda/larga para `partial_lift`
  - observacional
- Full Throttle Attainment Recurrence 1.0
  - NUEVO
  - recurrencia entre comparaciones de una misma sesión
  - observacional

## Full Throttle Attainment Recurrence 1.0

Identidad física del punto:

```text
(reference_lap, reference_event_id)
```

Como la vuelta de referencia es la misma para todas las comparaciones de la
sesión, `reference_event_id` permite seguir el mismo evento físico entre
vueltas comparadas.

Contrato:

- mínimo 2 observaciones válidas con la misma dirección/estado para repetición;
- `UNAVAILABLE` no suma soporte ni se considera contradicción;
- una comparación donde el punto no aparece tampoco es contradicción;
- asignaciones duplicadas del mismo punto dentro de una comparación se
  deduplican antes del conteo;
- si dos duplicados contienen hechos incompatibles, esa comparación queda
  `CONFLICT` y no suma soporte;
- patrones admitidos:
  - `earlier_in_comparison_lap`
  - `later_in_comparison_lap`
  - `similar_to_reference`
  - `reference_attained_comparison_not_confirmed`
  - `comparison_attained_reference_not_confirmed`

El módulo produce a nivel raíz:

```json
"full_throttle_attainment_recurrence": {
  "version": "1.0",
  "repeated_pattern_count": 0,
  "patterns": []
}
```

Cada patrón conserva las observaciones fuente, count de soporte, comparaciones
faltantes/unavailable, consistencia y —para patrones de timing— mediana/rango
del delta espacial.

Sigue siendo explícitamente:

```text
observational_only = true
affects_ranking = false
affects_session_priority = false
authorized_coaching = false
```

## Instalación / actualización desde Objective Python v2.1

Descomprimir el hotfix en el root del repo:

```bash
unzip -o race_engineer_full_throttle_recurrence_v1_0_hotfix.zip
```

Aplicar el recovery universal actualizado:

```bash
python ./apply_objective_python_recovery_2026_08_13.py ./analyze_telemetry.py
```

Debe imprimir:

```text
Full Throttle Attainment Recurrence: 1.0
```

Verificar:

```bash
python ./run_race_engineer_regressions.py --analyzer ./analyze_telemetry.py
```

Resultado esperado:

```text
RACE ENGINEER PYTHON REGRESSION SUITE v1.2
RESULT: 31 PASS / 0 FAIL / 0 SKIP
```

## Resultado esperado con la sesión Spa ya conocida

Reproduciendo los hechos objetivos preservados en el JSON de Spa 4→3 / 4→2 /
4→1, Recurrence 1.0 encuentra tres patrones repetidos consistentes:

- `throttle_a:08` — Jacky Ickx: `earlier_in_comparison_lap`, support 2,
  mediana -17 m.
- `throttle_a:09` — Pouhon: `later_in_comparison_lap`, support 2,
  mediana +35 m.
- `throttle_a:04` — Les Combes:
  `comparison_attained_reference_not_confirmed`, support 2, con una tercera
  observación `UNAVAILABLE`.

Esto es sólo una validación observacional. Ninguno entra todavía en coaching o
prioridad de sesión.
