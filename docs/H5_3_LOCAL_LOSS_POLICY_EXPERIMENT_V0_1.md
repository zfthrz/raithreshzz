# H5.3h — Local-loss policy experiment v0.1

## Propósito

Evaluar si alguna pérdida local de una vuelta globalmente más rápida merece estudio
adicional, sin debilitar la política H5.3 vigente y sin generar acciones de coaching.

## Gates v0.1

Un caso solo puede quedar como `LOCAL_POLICY_CANDIDATE` cuando:

- fue revisado como `WITHHELD_BUT_ACTIONABLE`;
- todas sus ocurrencias tienen límites espaciales;
- existen métricas de acelerador y freno;
- cada pérdida local es de al menos `0.20 s`.

Todo incumplimiento produce `WITHHELD`. El umbral es una hipótesis experimental,
no un umbral productivo ni una estimación universal de accionabilidad.

## Autoridad

- No modifica `historical_action_policy.py`.
- No deriva una instrucción desde los deltas de canal.
- Todo candidato conserva `authorization.authorized=false`.
- `historical_actions_authorized=false`.
- La referencia de sesión sigue siendo la autoridad.

## Resultado inicial

Sobre los seis casos del auditor H5.3g:

- 1 `LOCAL_POLICY_CANDIDATE`: Interlagos T12 — Junção (`+0.294 s` local);
- 5 `WITHHELD`;
- 0 acciones autorizadas.

Antes de experimentar con un mapeo de acciones se necesitan casos confirmatorios
independientes, preferentemente en más de una sesión y circuito.
