# Race Engineer desktop GUI v1.7

GUI v1.7 incorpora zoom real sobre el mapa GPS del circuito.

## Uso

1. Abrir una sesión con mapa disponible.
2. Colocar el cursor sobre la zona de interés.
3. Usar la rueda para ampliar o reducir.
4. Pulsar `Restablecer mapa` para recuperar la vista completa.

El estado informa el nivel actual, desde `1.00x` hasta un máximo de `8.00x`.

## Alineación

La transformación visual se aplica en conjunto al trazado GPS, zonas H5.2,
prioridades/foco H5.4, marcador de inicio y punto blanco arrastrable. Las selecciones
continúan referidas al mismo punto físico después de ampliar. Al cambiar de sesión el
mapa vuelve automáticamente a `1x`.

## Autoridad

El zoom modifica solamente coordenadas de canvas. No cambia muestras GPS, distancias
LMU, zonas, prioridades ni coaching. El gráfico inferior mantiene su propio zoom
temporal completamente independiente.
