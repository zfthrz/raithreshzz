# H3 runtime utility audit v0.1

## Objetivo

Medir la cobertura y el aporte observacional de H3 en el corpus runtime existente
sin modificar producción. El audit consume exclusivamente:

- `data/generated/h3_1/*/persistent_pattern_selection.json`;
- el H4 del mismo identificador de sesión, cuando existe;
- el H5.2 del mismo identificador de sesión, cuando existe.

No abre History, no llama H2 ni un LLM, no cambia selecciones, thresholds, ranking,
`next_stint_plan` o autoridad histórica.

## Métricas

- estados H3 por sesión;
- membresías exactas H3.1 y proyecciones H3.2 por separado;
- estados `persistent_pattern`, `cross_session_repeat` y `single_observation`;
- patrones del mismo contexto observados en varias sesiones runtime;
- disponibilidad conjunta o complementaria respecto de H5;
- violaciones del contrato observacional, identidades duplicadas y colisiones de
  `pattern_id` entre contextos.

Las proyecciones y repeticiones de sólo dos sesiones son señales de revisión. El
audit no las denomina falsos positivos ni aplica un umbral para promoverlas.

## Uso

```powershell
python audit_h3_runtime_utility.py
```

Output regenerable:

```text
data/generated/diagnostics/h3_runtime_utility_audit.json
```

## Primer checkpoint real

```text
artefactos H3 válidos:                 49
artefactos inválidos:                   0
sesiones con H3 recurrente/proyectado: 33
edges de membresía exacta:            322
edges de proyección calibrada:         102
H3 + H5 disponibles:                   22
H3 disponible sin H5:                  11
sin H3 recurrente ni H5:               16
patrones vistos en varias sesiones:    43
violaciones de autoridad:               0
identidades duplicadas:                 0
colisiones entre contextos:             0
```

Este resultado demuestra cobertura y complementariedad, no calidad causal ni
autoridad de coaching. El siguiente uso correcto es revisar la estabilidad de las
proyecciones y los casos de dos sesiones con evidencia humana independiente.
