# Race Engineer desktop GUI v1.10

GUI v1.10 agrega una capa visual opcional de curvas validadas al mapa GPS.

## Uso

1. Abrir una sesión con un perfil exacto validado.
2. Activar la casilla `Curvas` junto a los controles del mapa.
3. Inspeccionar los intervalos coloreados, los puntos de ápice y sus nombres.
4. Desactivar la casilla para recuperar el mapa simplificado.

La casilla permanece deshabilitada cuando no existe un perfil compatible y comienza
sin seleccionar para evitar saturar la vista general.

## Representación

- azul verdoso tenue: intervalo calibrado de la curva;
- punto celeste: ápice definido por el perfil;
- texto: número interno y nombre conservado por el perfil;
- capas superiores: zonas H5.2, plan completo y foco H5.4.

Todos los elementos comparten la transformación de zoom y desplazamiento. El marcador
blanco conserva su selección y continúa mostrando la ubicación completa debajo.

## Autoridad

La capa se construye únicamente desde el perfil de producción validado con coincidencia
exacta de circuito y layout. No detecta curvas desde el dibujo, no modifica `Lap Dist`,
no cambia zonas comparativas y no concede autoridad de coaching.
