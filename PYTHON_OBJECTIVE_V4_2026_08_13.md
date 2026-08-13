# Race Engineer — Objective Python v4 (2026-08-13)

No contiene ni modifica LLM Analysis.

## Stack objetivo

- Brake Point 2.1 / schema 2.1
- Throttle Point 1.2.1 / schema 1.2
- Throttle Episode Sequence 1.0
- Throttle Sustained Modulation 1.0
- Full Throttle Attainment Recurrence 1.0
- Throttle Modulation Recurrence 1.0
  - partial lift recurrence
  - sustained throttle modulation recurrence
- Regression Suite 1.3
- Objective recovery 2026.08.13-v4

## Nuevo en v4

### Partial lift recurrence

Identidad física: `reference_lap + reference_event_id`.

Un patrón repetido requiere al menos 2 comparison laps con el mismo estado de desviación:

- `additional_in_comparison`
- `fewer_in_comparison`

`same_count`, datos faltantes y observaciones no disponibles se preservan, pero no cuentan como contradicción ni como recurrencia de desviación.

### Sustained throttle modulation recurrence

Usa `paired_event_context` para no mezclar varios eventos físicos dentro de un episodio grande.
Además de recurrencia por cantidad, conserva el tipo objetivo de modulación:

- `deep`
- `long`
- `deep_and_long`

La clasificación sólo cuenta una vez por comparison lap para evitar inflar soporte si hay múltiples modulaciones del mismo tipo en una vuelta.

## Contrato

Todo lo nuevo es:

```text
observational_only = true
affects_ranking = false
affects_session_priority = false
authorized_coaching = false
```

No cambia detección física, pairing, episodios, ranking, prioridades ni coaching.

## Upgrade desde v3 / 31 PASS

Descomprimir el hotfix en el root del repo:

```bash
unzip -o race_engineer_throttle_modulation_recurrence_v1_0_hotfix.zip
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
RACE ENGINEER PYTHON REGRESSION SUITE v1.3
RESULT: 40 PASS / 0 FAIL / 0 SKIP
```

El upgrade incremental desde Objective Python v3 fue probado explícitamente y pasa 40/40.
