# Calibration Batch Orchestrator v1.0

`prepare_calibration_batch.py` automatiza la preparación de datos reales hasta
el punto seguro anterior al matcher.

## Regla principal

El script NO implementa:

- thresholds;
- weights;
- match scores;
- matching automático;
- clustering;
- persistent_pattern.

Su función es orquestar, validar y dejar un estado explícito.

## Uso inicial

Desde la raíz del repo:

```bash
python prepare_calibration_batch.py data/generated
```

Si los JSON están en subdirectorios:

```bash
python prepare_calibration_batch.py data/generated --recursive
```

Si el History DB contiene más de un circuito con al menos dos sesiones, el
script se detiene y pide un nombre exacto:

```bash
python prepare_calibration_batch.py data/generated \
  --track "Autodromo Nazionale Monza"
```

## Flujo

1. valida que existan los scripts del proyecto;
2. inicializa History DB;
3. importa los JSON de análisis;
4. valida History DB;
5. exige al menos dos sesiones del mismo circuito;
6. genera `episode_pair_features.json`;
7. genera `pair_review_queue.json`;
8. se detiene para revisión humana;
9. valida labels cuando existan;
10. exige que toda la queue esté revisada;
11. genera `calibration_dataset.json`;
12. genera `calibration_feature_report.json`;
13. informa si el split tiene pares de evaluación utilizables.

## Batches inmutables por conjunto de sesiones

El directorio del batch contiene un ID derivado de:

- session_id;
- track;
- SHA-256 del JSON fuente;
- versión de análisis;
- timestamp.

Ejemplo:

```text
calibration_batches/
└── autodromo-nazionale-monza-a1b2c3d4e5/
    ├── BATCH_STATUS.json
    ├── episode_pair_features.json
    ├── pair_review_queue.json
    ├── pair_labels.json
    ├── calibration_dataset.json
    ├── calibration_feature_report.json
    └── logs/
```

Si se agrega una nueva sesión, cambia el batch ID. La queue vieja y sus labels
no se sobrescriben.

Esto evita invalidar accidentalmente el hash de una revisión humana ya hecha.

## Primera ejecución esperada

La primera ejecución normalmente termina con:

```text
overall_status: READY_FOR_HUMAN_REVIEW
```

y `BATCH_STATUS.json` incluye el comando exacto para etiquetar:

```bash
python label_episode_pairs.py \
  .../pair_review_queue.json \
  --labels .../pair_labels.json
```

Después de etiquetar algunos pares, volver a ejecutar el mismo comando produce:

```text
overall_status: WAITING_FOR_HUMAN_REVIEW
```

hasta que la queue esté completa.

## Labels completas

Cuando toda la queue fue revisada:

- se ejecuta `validate_pair_labels.py`;
- se crea el split calibration/evaluation por sesión;
- se genera el reporte descriptivo.

Si evaluation queda sin pares internos:

```text
overall_status: READY_FOR_MORE_REAL_DATA
evaluation_readiness: WARNING_EMPTY
```

No es un error de software. Significa que todavía no hay suficiente estructura
independiente para una evaluación útil.

## Gates

### History validation FAIL

STOP.

### Menos de dos sesiones del mismo track

STOP.

### Varios tracks elegibles sin `--track`

STOP y pide selección explícita.

### Cero pair features

STOP.

### Labels ausentes

PAUSA normal para revisión humana.

### Labels incompletas

PAUSA normal. No se construye dataset.

### Label validation FAIL

STOP.

### Evaluation vacía

Se genera el reporte disponible, pero el status queda `READY_FOR_MORE_REAL_DATA`.

## Status

Cada batch mantiene:

```text
BATCH_STATUS.json
```

con:

- circuito;
- batch ID;
- sesiones;
- session signature;
- cantidad de pair features;
- cantidad de pares en review;
- progreso de labels;
- dataset readiness;
- evaluation readiness;
- next action;
- matcher siempre bloqueado.

Además cada comando externo queda registrado en `logs/`.
