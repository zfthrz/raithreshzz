# Race Engineer — Matcher Calibration Specification v1.0

## Propósito

Definir cómo se calibrará el matcher de episodios históricos cuando existan suficientes sesiones reales.

Este documento NO contiene thresholds, pesos ni decisiones automáticas.

---

# 1. Unidad de calibración

La unidad básica es un par de `driver_action_episode` pertenecientes a:

- mismo circuito;
- distintas sesiones para calibración principal.

También podrán generarse pares dentro de una misma sesión para estudiar repetición interna, pero no deben mezclarse con evidencia independiente.

---

# 2. Etiquetas humanas de referencia

Cada par revisado manualmente debe recibir una de tres etiquetas:

## SAME

Los dos episodios representan razonablemente la misma región y el mismo tipo general de diferencia de conducción.

No implica causalidad idéntica.

## DIFFERENT

Los episodios no deben considerarse la misma observación histórica.

## AMBIGUOUS

Los datos no permiten decidir de forma fiable.

AMBIGUOUS es una clase válida y necesaria.

Nunca forzar todos los pares a SAME o DIFFERENT.

---

# 3. Fuente de verdad de etiquetas

Las etiquetas de calibración deben provenir de revisión humana de:

- posición;
- canales;
- contexto de episodios;
- telemetría objetiva;
- sesiones originales cuando sea necesario.

El LLM NO debe producir las etiquetas de verdad usadas para calibrar el matcher.

Puede ayudar a explicar pares, pero no definir ground truth.

---

# 4. Features disponibles

El matcher podrá usar únicamente features deterministas calculadas por Python.

## Espaciales

- `center_distance_abs_diff_m`
- `start_distance_abs_diff_m`
- `end_distance_abs_diff_m`
- `overlap_m`
- `overlap_over_union`
- `overlap_over_shorter`
- `overlap_over_longer`
- `length_similarity`

## Normalizadas

- `center_fraction_abs_diff`
- `start_fraction_abs_diff`
- `end_fraction_abs_diff`
- `fraction_overlap`
- `fraction_overlap_over_union`
- `fraction_overlap_over_shorter`

## Canales

- `channel_jaccard`
- `shared_channels`
- `channels_only_a`
- `channels_only_b`

## Temporal impact

- `action_time_loss_similarity`

Debe tratarse como evidencia secundaria.

Dos ejecuciones del mismo comportamiento pueden producir impactos temporales distintos.

## Por canal compartido

- coverage difference
- onset offset difference
- end offset difference
- mean difference similarity
- peak difference similarity
- direction consistency

---

# 5. Features que NO deben dominar inicialmente

No usar como criterio principal:

- magnitud exacta de `action_time_loss_s`;
- evidence strength;
- presencia de speed propagation;
- rank dentro de la sesión.

Estas variables pueden cambiar por contexto aunque el comportamiento sea recurrente.

---

# 6. Prioridad conceptual del matcher

Sin fijar pesos, la arquitectura inicial debería priorizar:

1. ubicación espacial;
2. solapamiento espacial;
3. compatibilidad de canales;
4. forma temporal interna del canal;
5. magnitud de impacto como evidencia secundaria.

---

# 7. Candidate generation vs final matching

Separar dos problemas:

## Candidate generation

Reduce el universo de pares potenciales.

Debe ser permisivo.

Su objetivo es no perder matches plausibles.

## Final matcher

Decide:

- matched
- ambiguous
- rejected

Debe ser más conservador.

No implementar ninguno hasta observar distribuciones reales.

---

# 8. Falsos positivos vs falsos negativos

Para Race Engineer es peor afirmar:

"este es un hábito recurrente"

cuando no lo es,

que dejar de detectar temporalmente una recurrencia real.

Por lo tanto, el matcher final debe priorizar precisión sobre recall.

Debe existir una zona `ambiguous`.

---

# 9. Separación de calibración y evaluación

No evaluar sobre los mismos pares usados para elegir thresholds.

La separación debe realizarse por SESIONES, no por pares aleatorios.

Motivo:

pares de episodios que comparten una misma sesión no son estadísticamente independientes.

Diseño recomendado:

- grupo de sesiones para calibración;
- grupo distinto de sesiones para validación.

---

# 10. Evitar leakage

No permitir que episodios de una sesión aparezcan simultáneamente en:

- calibración;
- validación.

Si una sesión está en calibración, todos sus pares asociados pertenecen a calibración.

---

# 11. Métricas de evaluación

Para `matched`:

- precision;
- recall;
- false positive count.

Precision debe tener prioridad.

Para `ambiguous`:

- porcentaje de casos difíciles correctamente enviados a ambiguity;
- tasa de matches incorrectos que deberían haber sido ambiguous.

No optimizar solamente accuracy global.

---

# 12. Sesiones independientes

Al construir patrones históricos:

`observation_count`

y

`independent_session_count`

deben mantenerse separados.

Varias comparaciones de la misma sesión pueden aumentar `observation_count`.

No deben aumentar `independent_session_count`.

---

# 13. Matching dentro de sesión

El matching within-session puede compartir el mismo extractor de features.

Sin embargo debe producir una relación distinta:

`within_session_candidate`

No debe confundirse con evidencia cross-session.

---

# 14. Identidad de vehículo

Antes de declarar un patrón persistente debe resolverse la identidad estable del vehículo entre sesiones.

Estado actual:

el JSON v3.8 confirma mismo vehículo DENTRO de cada sesión.

Todavía no existe un identificador persistentemente validado ENTRE sesiones.

Hasta resolverlo:

- se puede calibrar ubicación y canales por circuito;
- NO se debe afirmar que una recurrencia entre coches distintos representa el mismo hábito con la misma confianza.

---

# 15. Identidad de layout

La cadena `track` debe tratarse como scope inicial.

A futuro debe existir:

- track identity;
- layout identity.

No mezclar layouts diferentes aunque compartan nombre base.

---

# 16. Session type

Practice, Qualifying y Race deben conservarse.

Primera calibración:

analizar si session type cambia suficientemente las distribuciones.

No asumir todavía:

- que siempre deben separarse;
- que siempre pueden combinarse.

---

# 17. Transitividad

Problema:

A puede parecerse a B.

B puede parecerse a C.

Eso NO garantiza automáticamente que A sea equivalente a C.

Por tanto, no usar connected components simples sin control.

Un futuro pattern cluster debe validar coherencia interna.

Opciones a estudiar:

- medoid + compatibilidad con todos los miembros;
- complete-link style constraints;
- centroid espacial + restricciones de canales;
- revisión de miembros ambiguos.

No elegir estrategia todavía.

---

# 18. Pattern representative

Un patrón futuro no debería guardar simplemente el primer episodio.

Debe calcular un representante determinista:

- centro espacial robusto;
- intervalo espacial representativo;
- canales comunes;
- distribución de coverage;
- distribución de impacto;
- frecuencia de speed propagation.

Preferir medianas/estadísticos robustos frente a un único ejemplo.

---

# 19. Evolución de un patrón

Un patrón puede cambiar con entrenamiento.

El historial debe permitir observar:

- frecuencia;
- impacto;
- ubicación;
- canales;
- tendencia temporal.

No diseñar todavía "mejorando/empeorando" hasta tener suficiente historial.

---

# 20. Versionado

Toda decisión de match futura debe registrar:

- `matcher_version`;
- features usadas;
- thresholds/pesos;
- fecha de calibración.

Si cambia el matcher, debe ser posible recalcular matches sin destruir datos fuente.

Nunca sobrescribir episodios originales.

---

# 21. Dataset de revisión manual

Formato conceptual por fila:

```json
{
  "episode_pk_a": "...",
  "episode_pk_b": "...",
  "track": "...",
  "features": {},
  "human_label": "SAME | DIFFERENT | AMBIGUOUS",
  "review_notes": "",
  "reviewed_at": ""
}
```

No guardar texto del LLM como etiqueta humana.

---

# 22. Muestreo para calibración

No revisar sólo pares obviamente cercanos.

Necesitamos:

- positivos claros;
- negativos claros;
- casos de misma zona pero canales distintos;
- canales iguales en zonas distintas;
- fuerte solapamiento con distinto onset;
- poco solapamiento pero centros cercanos;
- impactos temporales muy diferentes;
- episodios largos vs cortos;
- casos ambiguos.

---

# 23. Primera versión del score

No implementar aún.

Forma conceptual:

`spatial_component`

`channel_component`

`shape_component`

`impact_component`

`context_component`

La salida no debe ser sólo un número.

Debe conservar componentes separados para diagnóstico.

---

# 24. Zona ambigua

Debe existir explícitamente.

Ejemplo conceptual:

score alto -> matched

score intermedio -> ambiguous

score bajo -> rejected

No fijar límites antes de calibración.

---

# 25. Seguridad semántica

Aunque dos episodios hagan match:

NO significa automáticamente:

- misma causa;
- mismo error exacto;
- misma recomendación;
- mismo impacto.

Significa:

"evidencia objetiva compatible con una recurrencia en una zona y comportamiento similar."

---

# 26. Integración con LLM

El LLM futuro recibirá una estructura ya decidida por Python.

Ejemplo conceptual:

```json
{
  "pattern_id": "...",
  "state": "cross_session_repeat",
  "common_action_channels": [],
  "independent_session_count": "...",
  "observation_count": "...",
  "spatial_summary": {},
  "impact_summary": {},
  "uncertainty": {}
}
```

El LLM no podrá:

- alterar members;
- cambiar recurrence state;
- recalcular score;
- convertir ambiguous en matched.

---

# 27. Gate obligatorio antes de implementar matcher

Se necesita:

1. `llm_analysis v3.8.2` validado;
2. history DB validada;
3. varias sesiones del mismo circuito importadas;
4. pair features generadas;
5. revisión manual de pares;
6. ejemplos SAME, DIFFERENT y AMBIGUOUS;
7. identidad del vehículo evaluada.

Sin estos puntos:

NO implementar thresholds.

---

# 28. Primer experimento futuro

Cuando haya datos:

1. elegir un circuito con varias sesiones;
2. exportar todos los cross-session pairs;
3. ordenar manualmente por diferencia de centro;
4. revisar distribución de overlap;
5. revisar channel Jaccard;
6. etiquetar una muestra;
7. estudiar qué features separan clases;
8. recién entonces proponer candidate gate.

---

# 29. Criterio de éxito

El matcher es útil si:

- raramente inventa recurrencias;
- conserva casos dudosos como ambiguous;
- identifica repeticiones obvias;
- explica por qué hizo match;
- sus decisiones son reproducibles;
- no depende del LLM.

---

# 30. Punto de bloqueo actual

En este punto el diseño puede continuar conceptualmente, pero cualquier implementación de:

- candidate thresholds;
- match score;
- pattern clustering;
- dominant action classification;

requiere observar datos reales.

Ese es el límite deliberado antes de pruebas.
