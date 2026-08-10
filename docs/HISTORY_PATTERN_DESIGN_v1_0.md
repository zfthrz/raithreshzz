# Race Engineer — History & Pattern Matching Design v1.0

## Estado

Este documento define la arquitectura posterior a:

- `analyze_telemetry.py v3.8`
- `llm_analysis.py v3.8.2`
- `session_history.py v1.0`
- `episode_pair_features.py v1.0`

No define thresholds de matching.

No habilita todavía etiquetas de patrón.

---

# 1. Objetivo

El historial debe permitir distinguir:

1. una observación aislada;
2. una repetición dentro de la misma sesión;
3. una repetición entre sesiones independientes;
4. un patrón persistente.

El LLM nunca debe decidir por sí solo si existe recurrencia.

Python debe calcular la evidencia de recurrencia y entregar esa conclusión estructurada al LLM.

---

# 2. Principio de independencia

No toda repetición tiene el mismo peso.

Dos comparaciones de vueltas dentro de la misma sesión comparten:

- condiciones;
- setup;
- combustible;
- pista;
- temperatura;
- estado del piloto;
- referencia temporal.

Por eso varias observaciones dentro de la misma sesión NO deben contar como varias sesiones independientes.

Jerarquía conceptual:

`single_observation`

`within_session_repeat`

`cross_session_repeat`

`persistent_pattern`

No se asignarán estas etiquetas hasta calibrar el matcher.

---

# 3. Identidad espacial

Nunca se debe exigir igualdad exacta de metros.

Cada episodio guarda:

- `start_distance_m`
- `end_distance_m`
- `center_distance_m`
- `start_lap_fraction`
- `end_lap_fraction`
- `center_lap_fraction`

La fracción de vuelta sirve como representación normalizada frente a pequeñas diferencias de distancia registrada entre sesiones.

Metros siguen siendo la representación principal para el piloto.

---

# 4. Features neutrales de episodio

Por episodio:

## Espaciales

- inicio
- fin
- centro
- longitud
- inicio normalizado
- fin normalizado
- centro normalizado

## Temporales

- `action_time_loss_s`
- `delta_start_s`
- `delta_end_s`

## Evidencia

- `evidence_strength`
- cantidad de canales
- presencia de speed propagation
- cantidad de loss clusters asociados

## Por canal

- canal
- cantidad de eventos
- longitud soportada
- coverage del episodio
- primer inicio
- último fin
- offset desde inicio del episodio
- offset hasta fin del episodio
- media de las diferencias medias
- mayor pico absoluto
- consistencia de dirección

No se asigna todavía `primary_action`.

---

# 5. Features neutrales entre dos episodios

`episode_pair_features.py` calcula sin clasificar:

## Espacio absoluto

- diferencia entre centros
- diferencia entre inicios
- diferencia entre finales
- overlap en metros
- union en metros
- overlap / union
- overlap / episodio más corto
- overlap / episodio más largo
- similitud de longitudes

## Espacio normalizado

- diferencia entre center fractions
- diferencia entre start fractions
- diferencia entre end fractions
- overlap normalizado
- overlap normalizado / union
- overlap normalizado / episodio más corto

## Canales

- canales de A
- canales de B
- canales compartidos
- canales exclusivos de A
- canales exclusivos de B
- Jaccard de canales

## Impacto

- pérdida A
- pérdida B
- similitud simétrica de magnitud de pérdida

## Por canal compartido

- diferencia absoluta de coverage
- diferencia de onset offset
- diferencia de end offset
- similitud de mean difference
- similitud de peak difference
- consistencia de dirección

Estas son features de calibración, no decisiones.

---

# 6. Lo que NO debe hacer el matcher

El matcher no debe asumir que:

- mismo centro = mismo problema;
- mismos canales = misma acción;
- misma pérdida temporal = mismo problema;
- speed propagation = acción equivalente;
- dos episodios cercanos siempre deben fusionarse;
- varias comparaciones de una sesión equivalen a varias sesiones independientes.

---

# 7. Futuras tablas

No crear todavía.

## `episode_matches`

Representaría decisiones pairwise ya calibradas.

Campos conceptuales:

- match_id
- episode_pk_a
- episode_pk_b
- matcher_version
- match_score
- match_status
- spatial_score
- channel_score
- temporal_score
- calibrated_at
- feature_snapshot_json

`match_status` podría ser:

- matched
- ambiguous
- rejected

No fijar thresholds todavía.

## `patterns`

Una entidad agrupadora de episodios equivalentes.

Campos conceptuales:

- pattern_id
- track
- pattern_version
- center_distance_estimate
- center_fraction_estimate
- dominant_channel_candidate
- first_seen
- last_seen
- independent_session_count
- observation_count
- persistence_state

## `pattern_members`

- pattern_id
- episode_pk
- session_id
- membership_confidence
- matcher_version

---

# 8. Primary / secondary action

No implementar aún.

Primero recopilar:

- coverage por canal;
- onset offset;
- end offset;
- event count;
- mean difference;
- peak difference;
- overlap con crecimiento positivo del delta.

Una futura clasificación podrá usar:

- `dominant`
- `supporting`
- `transient`

Pero las reglas deben calibrarse con casos reales.

Ejemplo conceptual:

Un canal que cubre casi todo el episodio y empieza al inicio es un candidato natural a `dominant`.

Un canal breve que aparece sólo al comienzo puede ser `supporting` o `transient`.

No codificar todavía esta lógica.

---

# 9. Fases temporales de un episodio

Diseño futuro:

`action_onset`

`action_interval`

`speed_propagation`

`delta_growth_end`

`recovery`

Campos futuros potenciales:

- action_start_m
- action_end_m
- propagation_start_m
- propagation_end_m
- delta_growth_end_m
- recovery_start_m
- recovery_end_m

No implementar hasta revisar casos reales.

---

# 10. Recurrencia

Diseño conceptual:

## single_observation

Un episodio aislado.

## within_session_repeat

Episodios suficientemente equivalentes dentro de una misma sesión.

No aumenta `independent_session_count`.

## cross_session_repeat

Episodios equivalentes presentes en más de una sesión independiente.

## persistent_pattern

Recurrencia estable a lo largo de suficientes sesiones independientes y/o tiempo.

No fijar cantidades mínimas todavía.

---

# 11. Evidencia independiente

El historial debe almacenar dos contadores separados:

- `observation_count`
- `independent_session_count`

Ejemplo:

Una sesión con cuatro comparaciones que muestran el mismo episodio:

`observation_count = 4`

`independent_session_count = 1`

Esto evita sobreestimar recurrencia.

---

# 12. LLM futuro

El LLM no recibirá todos los pares históricos.

Python debe producir una estructura resumida.

Ejemplo conceptual:

```json
{
  "pattern_state": "cross_session_repeat",
  "independent_session_count": "...Python...",
  "observation_count": "...Python...",
  "location": "...Python...",
  "common_channels": ["throttle"],
  "supporting_channels": ["steering_magnitude"],
  "speed_propagation_frequency": "...Python...",
  "evidence": "...Python..."
}
```

El LLM únicamente interpretará:

- qué podría significar para el piloto;
- cómo priorizar la práctica;
- qué hipótesis son razonables;
- qué no puede concluirse.

---

# 13. Track / vehicle scope

Primera versión del matcher:

- mismo circuito obligatorio;
- mismo vehículo recomendado;
- mismo layout obligatorio cuando esté disponible.

El JSON actual confirma mismo vehículo dentro de una sesión, pero todavía no tenemos una identidad de vehículo persistente entre sesiones suficientemente diseñada.

Antes de matching definitivo debe agregarse una identidad estable del coche/vehículo si la telemetría la proporciona.

Este punto puede convertirse en bloqueo futuro.

---

# 14. Session type

P, Q y R no deben considerarse necesariamente equivalentes.

En una primera etapa deben conservarse como feature/contexto:

- Practice
- Qualifying
- Race

No decidir todavía si se permiten matches entre tipos distintos.

Los datos deben mostrar si esto importa suficientemente.

---

# 15. Gates de prueba

## GATE A — LLM v3.8.2

Debe cumplirse:

- `llm_analysis.py v3.8.2` termina;
- `validate_llm_analysis_output.py` devuelve PASS;
- todos los episodios están presentes;
- no hay cifras producidas por el LLM;
- ground truth correcto;
- render final correcto.

Si falla:

NO seguir modificando la arquitectura LLM.

---

## GATE B — History import

Importar al menos varios JSON v3.8.

Debe comprobarse:

- import idempotente;
- reimportar mismo JSON no duplica datos;
- sesiones correctas;
- comparaciones correctas;
- episodios correctos;
- canales correctos;
- lap fractions plausibles;
- speed propagations correctas.

Si falla:

NO implementar matcher.

---

## GATE C — Multiple sessions same track

Necesitamos varias sesiones independientes del mismo circuito.

Idealmente incluir:

- una sesión con un episodio claramente parecido a otra;
- un episodio claramente diferente;
- diferencias pequeñas de límites espaciales;
- episodios con canales parcialmente coincidentes.

Sin esto:

NO elegir thresholds de matching.

---

## GATE D — Pair feature inspection

Ejecutar `episode_pair_features.py`.

Inspeccionar distribución de:

- center distance diff;
- center fraction diff;
- overlap ratios;
- channel Jaccard;
- coverage differences.

Debemos poder identificar manualmente pares:

- claramente equivalentes;
- claramente distintos;
- ambiguos.

Sin ejemplos ambiguos:

NO diseñar todavía un score definitivo.

---

# 16. Punto exacto donde debemos pausar

Podemos implementar sin pruebas:

- esquema histórico;
- importador;
- features neutrales;
- contratos;
- validadores;
- exportadores;
- documentación.

NO debemos implementar sin pruebas:

- thresholds de matching;
- score final;
- matched / rejected;
- clustering de patrones;
- persistent_pattern;
- dominant/supporting/transient;
- fases de curva;
- nombres de curvas;
- causalidad más agresiva.

---

# 17. Próxima fase después de las pruebas

Cuando GATE A y B pasen:

1. importar varias sesiones;
2. generar pair features;
3. seleccionar manualmente ejemplos positivos/negativos;
4. estudiar distribución;
5. definir matcher v0.1;
6. dejar una zona `ambiguous`;
7. validar contra sesiones no usadas para calibrar;
8. recién entonces crear tablas de patterns.

---

# 18. Principio rector

Cada nueva capa debe reducir libertad del LLM.

Python:

- mide;
- valida;
- agrupa;
- rankea;
- determina recurrencia.

LLM:

- interpreta;
- explica;
- recomienda;
- expresa incertidumbre.

No invertir estas responsabilidades.
