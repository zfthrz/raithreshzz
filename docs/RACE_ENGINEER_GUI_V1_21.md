# Race Engineer desktop GUI v1.21

GUI v1.21 elimina el aviso obsoleto de modelo/costo y automatiza la preparación
de colas H2 para labeling humano.

## Inicio de análisis

El doble clic sobre una sesión comienza directamente el pipeline Python
determinista. Se mantienen la validación del DuckDB, el bloqueo de LMU, tamaño,
vueltas válidas, estabilidad y el override explícito de diez minutos. No se
muestra modelo porque el runtime principal no llama un LLM ni genera cargos.

## Mantenimiento de colas

Después del mantenimiento History, `maintain_calibration_queues.py`:

- agrupa History por track, layout y vehicle variant compatibles;
- exige al menos dos sesiones;
- compara los session IDs actuales con los batches existentes;
- reutiliza un batch exacto sin ejecutarlo nuevamente;
- prepara como máximo un contexto cambiado por ciclo;
- ejecuta `prepare_calibration_batch.py --skip-import`;
- registra estado local en `data/local/calibration_queue_maintenance.json`.

La generación se limita a features y `pair_review_queue.json`. Los labels siguen
siendo humanos y ningún threshold o matcher se promueve automáticamente. Un fallo
se registra como warning y no invalida el mantenimiento exitoso de History.

La pestaña Calibración observa fingerprints de `BATCH_STATUS.json` y
`pair_labels.json`, y actualiza solamente su tabla cuando cambia un batch o el
avance del labeling; mapa y telemetría no se reconstruyen.

Validación del checkpoint: `1351 passed`.
