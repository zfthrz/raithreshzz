# Driver Analysis Eligibility Gate v1.0

## Problema

`analyze_telemetry.py` puede conservar comparaciones válidas temporalmente que no
son apropiadas para análisis del piloto. Esas comparaciones se identifican con:

```text
recommended_for_driver_analysis = false
```

Por ejemplo, una vuelta muy lenta puede seguir siendo geométricamente completa y
cerrar temporalmente con exactitud, pero no debe alimentar la calibración de
recurrencia.

## Política

`session_history.py` conserva todas las comparaciones y episodios para auditoría.

`episode_pair_features.py` sólo carga episodios cuya comparación cumple:

```sql
c.recommended_for_driver_analysis IS TRUE
```

Este filtro se aplica antes de construir cualquier par cross-session.

## Gates de un candidato de calibración

Un episodio sólo puede entrar al conjunto candidato si:

1. su comparación fue recomendada para análisis del piloto;
2. tiene una variante de vehículo conocida y soportada;
3. el otro episodio pertenece a otra sesión;
4. ambos pertenecen al mismo circuito;
5. ambos pertenecen a la misma `vehicle_variant`.

No se introducen thresholds, weights, scores ni decisiones automáticas de
matching.
