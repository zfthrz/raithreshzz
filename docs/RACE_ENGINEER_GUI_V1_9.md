# Race Engineer desktop GUI v1.9

GUI v1.9 agrega ubicación por curva al punto blanco del mapa GPS.

## Uso

Al seleccionar o arrastrar el punto blanco, la fila de estado muestra su distancia y,
cuando existe un perfil compatible, la curva o transición calibrada correspondiente.
Esta identificación también funciona fuera de las zonas comparativas H5.2.

Los textos de ubicación y telemetría adaptan su ancho al panel y continúan en las
filas necesarias. El contenido completo permanece visible al redimensionar la ventana.

## Perfil autorizado

La GUI busca solamente perfiles de producción con estado `VALIDATED` o
`VALIDATED_MULTI_SESSION`, coincidencia exacta de circuito y layout y una versión
contractual inequívoca. Si no hay coincidencia exacta, muestra metros sin asignar un
nombre. Los perfiles experimentales `shadow_v2` no participan.

## Autoridad

La ubicación reutiliza el resolvedor determinista y `LMU Lap Dist`; no infiere nombres
desde el dibujo GPS. Es una ayuda de inspección de solo lectura y no modifica zonas,
prioridades, referencias históricas ni coaching.
