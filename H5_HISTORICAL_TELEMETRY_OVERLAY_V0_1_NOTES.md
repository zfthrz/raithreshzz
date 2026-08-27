# H5 historical telemetry overlay v0.1

## Estado

Implementado como mejora de presentación de la GUI. No cambia decisiones H4/H5,
coaching, prioridades ni datos persistidos.

## Objetivo

Superponer en la pestaña **Telemetría** los canales de la referencia histórica
seleccionada por H4 sobre la vuelta de referencia de la sesión actual:

- velocidad;
- acelerador;
- freno.

La sesión actual continúa siendo la traza visual principal. La referencia H4 se
dibuja con líneas atenuadas y discontinuas.

## Fuente de verdad

La GUI no selecciona una referencia nueva. Consume
`selected_historical_reference` del artefacto H4 ya existente.

H4 aporta `session_id`, `lap`, `duration_s` y `source_json_path`.
`source_json_path` se resuelve contra `SessionRecord.analysis_path` de las
sesiones descubiertas por la GUI. Como fallback determinista, si el JSON de
análisis conserva un `state.json` hermano, se lee exclusivamente el campo
`database`.

La DuckDB histórica se abre mediante el `load_track_map()` existente, que usa
conexión read-only.

Si no se puede resolver el JSON histórico, el `state.json`, la DuckDB o la
vuelta seleccionada, la funcionalidad falla de forma silenciosa y el gráfico
continúa mostrando sólo la sesión actual.

## Alineación visual v0.1

No se comparan índices de muestra ni timestamps entre sesiones.

Ambas trazas usan `lap_distance_m` como eje X físico. Cada vuelta conserva sus
muestras nativas; no se interpola ni se calcula una nueva señal.

Para que la superposición sea comparable:

- ambas vueltas comparten el mismo límite Y de velocidad;
- acelerador y freno conservan 0–100 %;
- la histórica se proyecta sobre el mismo rango X visible de la sesión actual;
- el zoom/pan del gráfico sigue estando gobernado por la sesión actual.

## Archivos / puntos de extensión

### `race_engineer_track_map.py`

- `telemetry_speed_scale(...)`
- `build_track_telemetry_chart(...)`: parámetros opcionales
  `speed_max_kmh`, `axis_start_distance_m`, `axis_end_distance_m`.

Los parámetros mantienen el comportamiento previo cuando no se utilizan.

### `race_engineer_gui.py`

- `resolve_historical_telemetry_reference(...)`
- `RaceEngineerApp.current_historical_track_map`
- `RaceEngineerApp._start_historical_telemetry_request(...)`
- `_poll_track_map_queue()` acepta `historical_done` / `historical_error`
- `_render_track_telemetry_chart()` dibuja histórica primero y actual encima.

La carga histórica se hace en thread de fondo y reutiliza `track_map_cache`.

## Fuera de alcance deliberadamente

Queda para una fase posterior / Codex:

1. resampling/interpolación de ambas vueltas sobre una grilla común;
2. delta-time acumulado por distancia;
3. diferencias numéricas de velocidad/throttle/brake punto a punto;
4. cursor dual y tooltips comparativos;
5. anotaciones automáticas de braking point / throttle pickup;
6. uso de estas diferencias como evidencia de coaching;
7. overlay histórico en el preview de Resumen;
8. selector manual de otra referencia histórica.

No implementar esos puntos reutilizando índices de muestra. Cualquier métrica
comparativa futura debe definir primero una política explícita de alineamiento
por distancia y validarla con tests.

## Contrato de autoridad

- H4 sigue siendo la única autoridad para elegir la vuelta histórica.
- La referencia histórica sigue siendo observacional.
- No reemplaza la referencia intra-sesión.
- No modifica H2/H3.
- No modifica History.
- No modifica H5.2 ni sus zonas.
- La superposición es estrictamente una capa de presentación.

## Validación recomendada

```powershell
python -m pytest tests\test_race_engineer_track_map.py tests\test_historical_telemetry_overlay.py -q
python -m pytest -q
python race_engineer_gui.py
```

Prueba manual:

1. seleccionar una sesión con H4 disponible;
2. abrir **Telemetría**;
3. confirmar una traza sólida actual y una discontinua histórica en los tres canales;
4. comprobar que el rótulo `History #... · vuelta ...` corresponde a H4;
5. hacer zoom con la rueda y confirmar que ambas trazas conservan el mismo eje X;
6. seleccionar una sesión sin H4 y confirmar que el gráfico se comporta como antes.

## Siguiente checkpoint para Codex

Partir de este overlay visual, no de H5.2 ni de H2/H3. Antes de agregar
`delta_time`, diseñar y testear una función pura de resampling por
`lap_distance_m` que preserve huecos/datos faltantes, no mezcle pasadas después
de un reset de `Lap Dist`, defina resolución/tolerancia, produzca resultados
deterministas y no convierta la referencia histórica en autoridad de coaching
sin una fase separada de validación.

## H4 vehicle compatibility policy update

H4 v0.3 no longer requires exact `car_name_raw` equality. Historical eligibility
is gated by the existing `vehicle_variant` / class boundary. Different teams or
car numbers inside the same class are comparable when the remaining H4 gates pass.

`car_name_raw` remains observable through
`compatibility_observations.same_car_name_raw`, but it is not an eligibility gate.

The strict `vehicle_variant` boundary remains unchanged; for example,
`LMP2_ELMS` still does not match another LMP2 variant.
