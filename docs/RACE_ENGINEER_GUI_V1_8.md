# Race Engineer desktop GUI v1.8

GUI v1.8 agrega desplazamiento directo al mapa GPS ampliado.

## Uso

1. Abrir una sesión con mapa disponible.
2. Usar la rueda sobre el mapa para ampliar o reducir.
3. Mantener presionado el botón derecho y arrastrar para desplazar el circuito.
4. Usar el botón izquierdo sobre el trazado para mover el punto blanco de telemetría.
5. Pulsar `Restablecer mapa` para recuperar la vista completa.

El desplazamiento se habilita únicamente por encima de `1x`. Sus límites conservan
al menos una parte del circuito dentro del área visible.

## Alineación

Una sola transformación de canvas se aplica al trazado GPS, zonas H5.2, prioridades
H5.4, marcador de inicio y punto blanco. Por eso todas las capas permanecen alineadas
durante el zoom y el desplazamiento. Cambiar de sesión o restablecer el mapa elimina
zoom y desplazamiento.

## Autoridad

Esta función modifica solamente la presentación. No cambia muestras GPS, `Lap Dist`,
zonas, prioridades, selección de referencias ni coaching. El zoom y desplazamiento
del gráfico inferior siguen siendo independientes.
