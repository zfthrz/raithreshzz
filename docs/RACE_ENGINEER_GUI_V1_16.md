# Race Engineer desktop GUI v1.16

GUI v1.16 agrega **playback de telemetría** en Telemetría:

- Fila `Playback:` con los botones `▶ Play / ⏸ Pausa` y `⏮ Inicio`, debajo de
  los selectores de curvas y plan (siempre visible en el ancho default).
- Play avanza automáticamente el punto blanco a lo largo de la vuelta (10 Hz),
  actualizando el mapa GPS, el cursor del gráfico de canales y las lecturas de
  velocidad/freno/acelerador; se detiene al llegar al final.
- Pausa congela en el punto actual; `⏮ Inicio` rebobina al comienzo de la vuelta.
- El playback se detiene solo al arrastrar el punto, elegir una curva o una zona
  del plan, o al cambiar de sesión.

## Pulido estético

- Barra de acento teal bajo el header (línea de 2 px).
- Botón `▶ Play` con estilo accent (teal, con hover/pressed/disabled).
- Tabs con fondo seleccionado sutil (`#22282e`) y hover `#2c363b`.
- Headings de tablas con gris azulado más suave (`#9fb3c8`).

## Autoridad

Presentación únicamente: no modifica telemetría, plan ni coaching.
