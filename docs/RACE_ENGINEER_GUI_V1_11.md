# Race Engineer desktop GUI v1.11

GUI v1.11 incorpora navegación sincronizada por curvas validadas.

## Uso

1. Abrir una sesión con un perfil exacto validado.
2. Elegir una entrada en `Navegación por curva`.
3. Inspeccionar el intervalo completo resaltado en el mapa.
4. Revisar velocidad, acelerador y freno en el gráfico enfocado debajo.
5. Ajustar o restablecer posteriormente cada zoom de manera independiente.

## Sincronización inicial

La selección realiza una sola operación coordinada:

- activa la capa visual de curvas;
- centra y amplía la entrada–salida completa en el mapa;
- coloca el punto blanco en el ápice definido por el perfil;
- enfoca el gráfico inferior en los mismos límites de `LMU Lap Dist`;
- muestra el resumen determinista del intervalo.

El zoom automático conserva margen alrededor de la curva y queda limitado a `8x`.
Los controles de navegación tienen una fila independiente para no comprimir la fila
de zoom en una ventana de tamaño normal.

## Autoridad

Los límites y el ápice provienen exclusivamente del perfil validado exacto. La
navegación es una vista de inspección: no vuelve comparables dos vueltas, no genera
una recomendación y no modifica la autoridad de H5.1, H5.2 o H5.3.
