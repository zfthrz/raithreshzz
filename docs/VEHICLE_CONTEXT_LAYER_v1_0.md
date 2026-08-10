# Vehicle Context Layer v1.0

## Objetivo

Evitar que el histórico de Race Engineer compare episodios de vehículos con
reglamentos o categorías incompatibles.

La identidad se obtiene directamente de la tabla `metadata` de los `.duckdb`
de Le Mans Ultimate.

## Fuentes LMU

Se leen estas claves cuando existen:

- `CarClass`
- `CarName`
- `CarSetup`
- `WeatherConditions`
- `TrackName`
- `TrackLayout`
- `SessionType`
- `RecordingTime`

No se modifica el `.duckdb` fuente.

## Identidad normalizada

El JSON de `analyze_telemetry.py` añade:

```json
"vehicle_identity": {
  "family": "LMP2",
  "variant": "LMP2_ELMS",
  "car_class_raw": "LMP2_ELMS",
  "car_name_raw": "IDEC Sport #18:ELMS25",
  "supported_domain": true,
  "identity_source": "lmu_metadata"
}
```

### Regla crítica LMP2

`LMP2_ELMS` y `LMP2` NO son equivalentes.

- raw `LMP2_ELMS` -> family `LMP2`, variant `LMP2_ELMS`
- raw `LMP2` -> family `LMP2`, variant `LMP2_WEC`

La familia permite agrupar conceptualmente ambos reglamentos, pero la variante
es un hard gate de matching.

## Dominio soportado

La primera versión sólo acepta para matching las familias:

- GT3
- GTE
- LMP3
- LMP2
- HYPERCAR

Una clase desconocida conserva `car_class_raw`, pero queda con
`supported_domain=false` y no participa en pares cross-session.

## Session context

El análisis añade también:

```json
"session_context": {
  "lmu_track_name": "Circuit de Spa-Francorchamps",
  "lmu_session_type": "Qualify",
  "weather_conditions": "Light Clouds",
  "setup_available": true,
  "setup_sha256": "...",
  "setup_raw_sha256": "...",
  "setup_hash_basis": "effective_current_values"
}
```

## Hash de setup

`CarSetup` contiene datos de UI/historial que no describen el setup efectivo,
por ejemplo:

- `lastSavedStringValue`
- `numChangesValue`
- `diffComparisonValue`
- `gearGraph`

Por eso existen dos hashes:

- `setup_sha256`: sólo valores actuales efectivos (`value` + `stringValue`) de
  entradas `VM_*` y `WM_*` disponibles.
- `setup_raw_sha256`: hash del JSON raw completo para auditoría.

El matching NO exige setup idéntico.

## History DB schema v2

`session_history.py` migra schema v1 -> v2 de forma aditiva y añade a
`sessions`:

- `vehicle_family`
- `vehicle_variant`
- `car_class_raw`
- `car_name_raw`
- `vehicle_identity_source`
- `vehicle_supported_domain`
- `weather_conditions`
- `setup_sha256`
- `setup_raw_sha256`
- `setup_available`
- `lmu_session_type`
- `lmu_track_name`

Sesiones legacy sin vehicle context pueden permanecer en el DB, pero el
validator las marca con warning y `episode_pair_features.py` las excluye de
matching cross-session.

## Hard gate de pair generation

Un par sólo puede generarse si:

```text
session_a != session_b
AND track_a == track_b
AND vehicle_variant_a == vehicle_variant_b
AND vehicle_variant IS NOT NULL
AND supported_domain_a == true
AND supported_domain_b == true
```

No son hard gates:

- `CarName`
- setup
- clima
- tipo de sesión

Esos valores se conservan como features/contexto del par.

## Batch identity

`prepare_calibration_batch.py` v1.1 selecciona por:

```text
TRACK + VEHICLE_VARIANT
```

Ejemplo:

```text
circuit-de-spa-francorchamps--lmp2-elms-<batch-id>/
```

El comando de pair features recibe siempre ambos filtros:

```bash
python episode_pair_features.py \
  --track "Circuit de Spa-Francorchamps" \
  --vehicle-variant LMP2_ELMS
```

## Dataset Spa disponible

El inventario inicial del usuario contiene siete sesiones compatibles de:

```text
Circuit de Spa-Francorchamps + LMP2_ELMS
```

con Practice, Qualify y Race, setups distintos y dos descripciones de clima.
Ese contexto es apropiado para el primer batch real después de reanalizar los
`.duckdb` con esta capa activa.
