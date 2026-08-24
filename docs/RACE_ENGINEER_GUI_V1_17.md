# Race Engineer desktop GUI v1.17

GUI v1.17 mejora la **resolución de la telemetría**:

- La reconstrucción GPS/telemetría ahora alinea a **20 Hz por default**
  (antes 10 Hz). La telemetría LMU nativa es ~100 Hz; la grilla de alineación
  conserva el doble de muestras por vuelta (mapa y gráfico más finos, más
  detalle al hacer zoom).
- Selector `Resolución:` en la fila de playback: `20 Hz` (default), `10 Hz` o
  `50 Hz`. Cambiarlo reconstruye la vuelta con la nueva grilla.
- El playback ajusta su paso según la resolución para mantener velocidad 1×.

## Autoridad

Presentación read-only: re-muestrea canales nativos sobre una grilla uniforme
determinista; no modifica telemetría, plan ni coaching.
