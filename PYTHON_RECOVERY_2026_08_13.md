# Race Engineer — Python objective recovery (2026-08-13)

Este paquete NO incluye ningún `llm_analysis*.py`.

## Runtime estable incluido

- `braking_point_v2_1.py`
  - detector 2.1 / schema 2.1
- `throttle_point_v1_2_1.py`
  - detector 1.2.1 / schema 1.2
  - onset/release conservan la lógica 1.1
  - full-throttle attainment observacional
  - partial lift observacional
- `throttle_episode_sequence_v1_0.py`
  - NUEVO
  - conserva múltiples eventos físicos de acelerador por `driver_action_episode`
  - usa como fuente `throttle_point_v1_2_1`
  - no cambia ranking, episodios ni coaching

`throttle_point_v1_1.py` se incluye únicamente como referencia de regresión para demostrar que onset/release no cambiaron. El recovery patcher NO lo instala como runtime.

## Recuperación recomendada desde un repo atrasado

Copiar todos los `.py` al root del proyecto y ejecutar:

```powershell
python .\apply_objective_python_recovery_2026_08_13.py .\analyze_telemetry.py
```

Instala de forma idempotente, en este orden:

1. Brake Point 2.1
2. Throttle Point 1.2.1
3. Throttle Episode Sequence 1.0

No modifica ningún archivo LLM.

Para verificar sin modificar:

```powershell
python .\apply_objective_python_recovery_2026_08_13.py --check .\analyze_telemetry.py
```

## Suite de regresión

```powershell
python .\run_race_engineer_regressions.py --analyzer .\analyze_telemetry.py
```

Validaciones actuales:

- contrato de versiones;
- brake onset/release 2.1;
- frenada activa al final del trace conserva onset;
- throttle onset/release idénticos a 1.1;
- full-throttle sostenido confirmado;
- pico full-throttle transitorio rechazado;
- partial lift corto y medio aceptados;
- modulación profunda/larga rechazada como partial lift;
- pairing monotónico salta eventos faltantes;
- dos eventos físicos de throttle dentro de un episodio;
- un episodio acotado no arrastra el segundo evento fuera de tolerancia;
- episodios sin throttle se ignoran;
- enriquecimiento multi-evento no cambia orden/ranking;
- recovery desde analyzer sin parches;
- migración de imports/hooks viejos;
- recovery textualmente idempotente;
- auditoría del `analyze_telemetry.py` real.

La suite fue validada contra una copia limpia de `analyze_telemetry_v3_8.py` con resultado:

```text
20 PASS / 0 FAIL / 0 SKIP
```

## Parches directos incluidos

- `apply_braking_point_patch_v2_1.py`
- `apply_throttle_point_patch_v1_2_1.py`
- `apply_throttle_episode_sequence_patch_v1_0.py`

Para recuperación desde una PC/repositorio desactualizado, preferir el patcher universal `apply_objective_python_recovery_2026_08_13.py`.
