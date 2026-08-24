# Race Engineer desktop GUI v1.14

GUI v1.14 agrega el tab **Diagnóstico → Calibración**, un panel read-only con el
estado de la calibración H2 por contexto.

## Panel de calibración

- Tabla con una fila por batch de `calibration_batches/`: contexto
  (circuito · variante), cantidad de sesiones, labels revisados (`X/24`),
  estado de la partición de evaluación (`PASS` con cantidad de pares o el estado
  real) y status del matcher resuelto por contexto.
- Colores por estado del matcher: verde (calibrado), dorado (provisional),
  gris (sin calibración) y rojo (bloqueado/desconocido).
- Línea de resumen: contextos calibrados, datasets listos y cantidad de batches.

La vista se calcula en `race_engineer_ui_model.py`
(`load_calibration_summary`) leyendo los `BATCH_STATUS.json` versionados; no
consulta DuckDB ni modifica nada.

## Autoridad

Presentación únicamente: no cambia matcher, thresholds ni calibración.
