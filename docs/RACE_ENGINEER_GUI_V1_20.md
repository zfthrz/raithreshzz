# Race Engineer desktop GUI v1.20

GUI v1.20 incorpora recuperación manual reversible para una cola detenida por un
debrief que falla repetidamente.

## Posponer y liberar la cola

El botón aparece únicamente cuando una sesión `HISTORY_READY` conserva un
`last_debrief_error` y acumuló al menos tres intentos. Después de confirmarlo:

- pasa a `DEBRIEF_DEFERRED`;
- permanece importada en History;
- conserva intentos y último error;
- deja de participar en la cola automática de debriefs.

## Reactivar

Cuando no existe otra sesión bloqueante, el panel permite reactivar la primera
sesión pospuesta. Vuelve a `HISTORY_READY`, se ubica al final mediante un nuevo
`history_ready_at` y reinicia el contador de intentos. La evidencia del error
anterior se conserva para diagnóstico.

## Seguridad

- Ambas acciones requieren confirmación humana.
- Se rechazan mientras el runtime está `RUNNING`.
- Antes de escribir se verifica que tamaño y `mtime_ns` del estado no cambiaron.
- La escritura reutiliza el reemplazo atómico del estado de ingest.
- No se elimina telemetría, History, resultados ni evidencia de errores.
- El scan reconoce `DEBRIEF_DEFERRED` como estado terminal y no lo reimporta.

Validación del checkpoint: `1331 passed` en la suite completa.
