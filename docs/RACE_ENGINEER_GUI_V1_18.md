# Race Engineer desktop GUI v1.18

GUI v1.18 incorpora el resultado del scheduler al catálogo abierto sin polling
pesado ni escrituras desde la interfaz.

## Auto-refresh inteligente

- Cada cinco segundos se calcula un fingerprint barato de los `state.json` bajo
  `data/generated/runs`.
- El fingerprint contiene únicamente la ruta relativa, `mtime_ns` y tamaño de cada
  archivo.
- `refresh()` sólo se ejecuta cuando se agrega, modifica o elimina un estado.
- Si no hubo cambios, no se reconstruyen el catálogo, el mapa ni la telemetría.
- La recarga reutiliza el `session_key` existente para preservar, cuando sigue
  disponible, la sesión seleccionada.
- Mientras la GUI ejecuta un análisis propio, la comprobación periódica no refresca
  la vista. El refresco normal de finalización sigue siendo la autoridad.
- Al cerrar la ventana se cancela el callback pendiente de Tkinter.

La implementación usa `root.after(...)` en el hilo principal y no agrega threads.

## Estado `HISTORY_READY`

El texto de estado ahora explica que la sesión ya está guardada en History y que el
scheduler puede generar automáticamente el debrief determinista. El botón
`Analizar` continúa disponible como alternativa manual.

## Autoridad y escritura

Esta integración es estrictamente read-only. La GUI no modifica:

- `state.json`;
- `telemetry_auto_ingest.json`;
- la base History;
- telemetría o artefactos de coaching.

El scheduler y el pipeline determinista conservan la autoridad sobre las
transiciones de estado.

## Validación

```text
pruebas focalizadas GUI/UI/ingest/scheduler: 123 passed
suite completa del working tree:             1315 passed
git diff --check:                             PASS
```
